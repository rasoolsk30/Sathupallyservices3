"""Guards that decide whether a database may be destroyed by the test harness.

The test suite DROPs and recreates the `public` schema. A database name that merely
contains the substring "test" is NOT sufficient protection — `contest_db`, `test`,
`mytest_prod` or a misconfigured `DATABASE_URL` would all pass. This module therefore
requires four independent layers of agreement before anything destructive happens:

1. **Explicit opt-in** — `SSH_ALLOW_DESTRUCTIVE_TEST_DB_RESET` must be set to a truthy
   value. Nothing in the repository sets it automatically; the operator (or
   `scripts/run_tests.sh`) must opt in for each run.
2. **Identity** — the URL must be PostgreSQL and the database name must END WITH
   `_test` (suffix, case-insensitive) and must not be a reserved/system name.
3. **Locality** — the host must be a loopback address unless
   `SSH_ALLOW_REMOTE_TEST_DB=1` is explicitly set.
4. **Non-collision** — the test URL must not resolve to the same database as the
   configured application `DATABASE_URL` (read from the environment and/or
   `backend/.env`). This layer **fails closed**: if the application URL is missing,
   unparseable, non-PostgreSQL or names no database, the destructive reset is refused
   rather than performed with the collision check skipped.

After connecting, `verify_connected_database()` re-checks the *live* identity
(`current_database()`) and refuses if the database declares itself production via a
`platform_production_marker` table.

Host identity is compared after normalisation and, when two hosts differ syntactically
but could still reach the same server, after DNS resolution. Inconclusive resolution is
treated as "same server" so that uncertainty can never authorise a destructive reset.

The URL-level functions are pure apart from DNS lookups, which only occur when a
collision is otherwise possible; the live check in `verify_connected_database()` needs a
connection.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from pathlib import Path

from sqlalchemy.engine import URL, make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
OPT_IN_ENV = "SSH_ALLOW_DESTRUCTIVE_TEST_DB_RESET"
ALLOW_REMOTE_ENV = "SSH_ALLOW_REMOTE_TEST_DB"
REQUIRED_SUFFIX = "_test"
RESERVED_DATABASES = {"postgres", "template0", "template1", "sathupally", "production", "prod"}
# --- host identity -------------------------------------------------------------------
# Every alias below reaches the SAME local PostgreSQL server, so they must compare equal
# when deciding whether the test database collides with the application database. The
# whole 127.0.0.0/8 block and IPv6 ::1 are loopback (checked with `ipaddress`), so
# 127.0.0.2 cannot be used to dodge a collision check against 127.0.0.1.
#
# `0.0.0.0` / `::` are WILDCARD *bind* addresses, not destinations: connecting "to" them is
# ambiguous and could land on any interface. They are NOT accepted as a test host.
LOOPBACK_IDENTITY = "loopback"   # normalised identity label, not a literal host
WILDCARD_IDENTITY = "wildcard"
LOOPBACK_ALIASES = {"localhost", "ip6-localhost", ""}  # "" = local Unix socket (still local)
WILDCARD_HOSTS = {"0.0.0.0", "::", "*"}
# Accepted destinations for a test URL (empty string = Unix socket).
LOOPBACK_HOSTS = LOOPBACK_ALIASES | {"127.0.0.1", "::1"}
PRODUCTION_MARKER_TABLE = "platform_production_marker"

_TRUTHY = {"1", "true", "yes", "y", "on"}


class UnsafeTestDatabaseError(RuntimeError):
    """Raised when a destructive test-database operation is not clearly safe."""


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUTHY


def normalize_host(host: str | None) -> str:
    """Map a host to a comparable *identity*.

    `localhost`, `127.0.0.1`, any other 127.0.0.0/8 address, `::1` and an empty host
    (Unix socket) all denote the same local server and collapse to LOOPBACK_IDENTITY.
    Wildcard bind addresses collapse to WILDCARD_IDENTITY. Anything else is returned
    lowercased with IPv6 brackets and a trailing FQDN dot removed.

    Without this, `localhost` and `127.0.0.1` compare as different literal strings and the
    application/test collision check can be bypassed.
    """
    raw = (host or "").strip().lower()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    raw = raw.rstrip(".")
    if raw in LOOPBACK_ALIASES:
        return LOOPBACK_IDENTITY
    if raw in WILDCARD_HOSTS:
        return WILDCARD_IDENTITY
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return raw
    if addr.is_loopback:
        return LOOPBACK_IDENTITY
    if addr.is_unspecified:
        return WILDCARD_IDENTITY
    return raw


def _resolve_addresses(host: str | None) -> set[str] | None:
    """Resolved IP literals for `host`, or None when resolution is inconclusive.

    - A literal IP needs no lookup.
    - An empty host is a local Unix socket, which can only reach the local server, so it
      is reported as the loopback addresses.
    - A name that does not resolve returns None. Callers MUST treat None as "cannot prove
      these are different servers" — never as "different".
    """
    raw = (host or "").strip().lower()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    if not raw:
        return {"127.0.0.1", "::1"}
    try:
        ipaddress.ip_address(raw)
    except ValueError:
        pass
    else:
        return {raw}
    try:
        infos = socket.getaddrinfo(raw, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, OSError, UnicodeError):
        return None
    addrs = {info[4][0] for info in infos if info[4]}
    return addrs or None


def _same_server(host_a: str | None, host_b: str | None) -> bool:
    """True when two hosts may reach the same PostgreSQL server.

    Fails CLOSED. A wildcard bind address, or a hostname that cannot be resolved, is
    reported as "same", because the reset must be blocked when identity is uncertain.
    Syntactically different names are resolved so a DNS alias for loopback (or for the
    application server) cannot slip past the collision check.
    """
    a, b = normalize_host(host_a), normalize_host(host_b)
    if a == b or WILDCARD_IDENTITY in (a, b):
        return True
    addrs_a = _resolve_addresses(host_a)
    addrs_b = _resolve_addresses(host_b)
    if addrs_a is None or addrs_b is None:
        return True  # inconclusive -> assume same server
    return bool(addrs_a & addrs_b)


def _application_database_identity(candidate_app_url: str | None, problems: list[str]) -> URL | None:
    """Resolve the application database URL, or record why its identity is unknown.

    FAIL CLOSED. If the application database cannot be identified there is no way to show
    that the disposable test database is a *different* database, so the destructive reset
    must not run. Skipping the collision check in that situation — the previous behaviour —
    turned the strongest safety layer into a no-op whenever DATABASE_URL was unset or
    malformed.
    """
    raw = (candidate_app_url or "").strip()
    if not raw:
        problems.append(
            "the application database is NOT configured (no DATABASE_URL in the environment or "
            "backend/.env), so it cannot be proven that the test database is a different "
            "database — refusing to destroy anything. Set DATABASE_URL, or create backend/.env "
            "from backend/.env.example."
        )
        return None
    try:
        app = make_url(raw)
    except Exception:
        problems.append(
            "the configured application DATABASE_URL cannot be parsed, so its database identity "
            "is unknown — refusing to destroy anything. Correct DATABASE_URL (check for typos, "
            "stray quotes or an unescaped password). The value is not echoed here to avoid "
            "leaking credentials."
        )
        return None
    if app.get_backend_name() != "postgresql":
        problems.append(
            f"the configured application DATABASE_URL uses backend "
            f"{app.get_backend_name()!r}, so it cannot be compared with a PostgreSQL test "
            "database — refusing to destroy anything."
        )
        return None
    if not (app.database or "").strip():
        problems.append(
            "the configured application DATABASE_URL does not name a database, so its identity "
            "is unknown — refusing to destroy anything."
        )
        return None
    return app


def read_env_file_value(key: str, path: Path | None = None) -> str | None:
    """Read a key from backend/.env without importing application settings."""
    env_path = path or (BACKEND_DIR / ".env")
    if not env_path.exists():
        return None
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() == key:
                return value.strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def configured_application_database_url() -> str | None:
    """The database this project would normally run against (env first, then .env)."""
    return os.environ.get("DATABASE_URL") or read_env_file_value("DATABASE_URL")


def _parse(url: str) -> URL:
    try:
        return make_url(url)
    except Exception as exc:  # sqlalchemy raises ArgumentError
        raise UnsafeTestDatabaseError(f"Test DATABASE URL is not parseable: {exc}") from exc


def assert_disposable_test_database(
    test_url: str,
    *,
    app_url: str | None = None,
    opt_in: str | None = None,
    allow_remote: str | None = None,
) -> URL:
    """Validate every safety layer; raise UnsafeTestDatabaseError listing all problems."""
    opt_in = os.environ.get(OPT_IN_ENV) if opt_in is None else opt_in
    allow_remote = os.environ.get(ALLOW_REMOTE_ENV) if allow_remote is None else allow_remote

    problems: list[str] = []

    if not _is_truthy(opt_in):
        problems.append(
            f"explicit destructive-test opt-in missing: set {OPT_IN_ENV}=1 for this run "
            "(scripts/run_tests.sh does this; CI must opt in deliberately)."
        )

    url = _parse(test_url)

    backend = url.get_backend_name()
    if backend != "postgresql":
        problems.append(f"expected a PostgreSQL URL, got backend {backend!r}.")

    database = (url.database or "").strip()
    if not database:
        problems.append("test URL does not name a database.")
    else:
        if not database.lower().endswith(REQUIRED_SUFFIX):
            problems.append(
                f"database name {database!r} must END WITH {REQUIRED_SUFFIX!r} "
                "(a name that merely contains 'test' is not sufficient)."
            )
        if database.lower() in RESERVED_DATABASES:
            problems.append(f"database name {database!r} is reserved and may hold real data.")

    raw_host = (url.host or "").strip().lower()
    if raw_host in WILDCARD_HOSTS:
        problems.append(
            f"host {raw_host!r} is a wildcard bind address, not a destination: it does not "
            "identify one server and could reach any interface. Use 127.0.0.1, ::1 or localhost."
        )
    elif not _is_truthy(allow_remote) and raw_host not in LOOPBACK_HOSTS:
        problems.append(
            f"host {raw_host!r} is not loopback; set {ALLOW_REMOTE_ENV}=1 only if you are certain "
            "the remote server is a disposable test instance."
        )

    candidate_app_url = app_url if app_url is not None else configured_application_database_url()
    app = _application_database_identity(candidate_app_url, problems)
    if app is not None:
        same_database = (app.database or "").lower() == database.lower()
        # Compare normalised identities, not literal strings: localhost / 127.0.0.1 / ::1 /
        # 127.0.0.2 / Unix socket are all the same local server, and a DNS alias resolving to
        # the application host is recognised when the names differ.
        same_host = _same_server(app.host, url.host)
        same_port = (app.port or 5432) == (url.port or 5432)
        if same_database and same_host and same_port:
            problems.append(
                "test URL points at the same host/port/database as the configured "
                f"application DATABASE_URL — refusing to destroy the application database. "
                f"(app host {app.host!r} and test host {url.host!r} are the same server "
                f"identity {normalize_host(url.host)!r}.)"
            )

    if problems:
        raise UnsafeTestDatabaseError(
            "REFUSING DESTRUCTIVE TEST DATABASE RESET for URL "
            f"{url.render_as_string(hide_password=True)}:\n  - " + "\n  - ".join(problems)
        )
    return url


def verify_connected_database(connection, *, app_url: str | None = None) -> str:
    """Re-check identity over a LIVE connection (defence in depth).

    URL parsing can be fooled by aliases, DNS names or a wildcard bind address, so the
    decisive test is what the server itself says: its database name, listening address and
    port. If that identity equals the application database's identity, the destructive
    reset is refused even when the connection strings looked different.
    """
    from sqlalchemy import text

    row = connection.execute(
        text("SELECT current_database(), host(inet_server_addr()), inet_server_port()")
    ).one()
    actual, server_addr, server_port = str(row[0]), row[1], row[2]

    problems: list[str] = []

    if not actual.lower().endswith(REQUIRED_SUFFIX):
        problems.append(
            f"connected database {actual!r} does not end with {REQUIRED_SUFFIX!r}; refusing destructive reset."
        )
    if actual.lower() in RESERVED_DATABASES:
        problems.append(f"connected database {actual!r} is a reserved/production name.")

    marker = connection.execute(
        text("SELECT to_regclass(:name)"), {"name": f"public.{PRODUCTION_MARKER_TABLE}"}
    ).scalar()
    if marker:
        problems.append(
            f"connected database {actual!r} contains {PRODUCTION_MARKER_TABLE}; it declares itself production."
        )

    candidate_app_url = app_url if app_url is not None else configured_application_database_url()
    app = _application_database_identity(candidate_app_url, problems)  # fails closed
    if app is not None and (app.database or "").lower() == actual.lower():
        # Same database NAME. Is it the same server? An unknown address (Unix socket, NULL
        # from inet_server_addr) is treated as local — fail closed.
        same_server = _same_server(app.host, server_addr if server_addr else "")
        same_port = (int(server_port) if server_port is not None else (app.port or 5432)) == (app.port or 5432)
        if same_server and same_port:
            problems.append(
                f"connected database {actual!r} on {server_addr or 'local socket'}:{server_port} is the "
                "SAME database as the configured application DATABASE_URL "
                f"({app.database!r} on {app.host!r}:{app.port or 5432}) — refusing destructive reset."
            )

    if problems:
        raise UnsafeTestDatabaseError(
            "REFUSING DESTRUCTIVE TEST DATABASE RESET on live connection:\n  - " + "\n  - ".join(problems)
        )
    return actual
