"""Unit tests for the destructive-test-database guard (no database required).

These prove that a database name merely *containing* "test" is not accepted, that an
explicit opt-in is mandatory, and that the harness refuses to target the application
database, a remote host, reserved names, or a production-marked database.
"""
from __future__ import annotations

import pytest

from tests.guards import (
    LOOPBACK_IDENTITY,
    OPT_IN_ENV,
    WILDCARD_IDENTITY,
    UnsafeTestDatabaseError,
    assert_disposable_test_database,
    configured_application_database_url,
    normalize_host,
    read_env_file_value,
    verify_connected_database,
)

GOOD_URL = "postgresql+psycopg://ssh_app:secret@127.0.0.1:5432/sathupally_test"


def _check(url: str, **kwargs):
    kwargs.setdefault("opt_in", "1")
    kwargs.setdefault("allow_remote", "")
    kwargs.setdefault("app_url", "postgresql+psycopg://ssh_app:secret@127.0.0.1:5432/sathupally")
    return assert_disposable_test_database(url, **kwargs)


class TestOptIn:
    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off", " "])
    def test_missing_or_false_opt_in_is_refused(self, value):
        with pytest.raises(UnsafeTestDatabaseError, match=OPT_IN_ENV):
            _check(GOOD_URL, opt_in=value)

    def test_absent_opt_in_environment_variable_is_refused(self, monkeypatch):
        monkeypatch.delenv(OPT_IN_ENV, raising=False)
        with pytest.raises(UnsafeTestDatabaseError, match=OPT_IN_ENV):
            assert_disposable_test_database(
                GOOD_URL,
                app_url="postgresql+psycopg://u:p@127.0.0.1:5432/sathupally",
                allow_remote="",
            )

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "Yes", " on ", "y"])
    def test_truthy_opt_in_is_accepted(self, value):
        assert _check(GOOD_URL, opt_in=value).database == "sathupally_test"


class TestDatabaseIdentity:
    @pytest.mark.parametrize(
        "url",
        [
            "postgresql+psycopg://u:p@127.0.0.1:5432/sathupally",        # the application database
            "postgresql+psycopg://u:p@127.0.0.1:5432/test",              # bare 'test', no suffix
            "postgresql+psycopg://u:p@127.0.0.1:5432/contest_db",        # merely contains 'test'
            "postgresql+psycopg://u:p@127.0.0.1:5432/testdata",          # prefix only
            "postgresql+psycopg://u:p@127.0.0.1:5432/my_test_backup",    # suffix missing
            "postgresql+psycopg://u:p@127.0.0.1:5432/testing",           # not a suffix
            "postgresql+psycopg://u:p@127.0.0.1:5432/postgres",          # system database
            "postgresql+psycopg://u:p@127.0.0.1:5432/template1",         # system database
        ],
    )
    def test_unsafe_database_names_are_refused(self, url):
        with pytest.raises(UnsafeTestDatabaseError):
            _check(url)

    @pytest.mark.parametrize("name", ["sathupally_test", "ssh_test", "a_TEST", "x_test"])
    def test_valid_suffix_names_accepted(self, name):
        assert _check(f"postgresql+psycopg://u:p@127.0.0.1:5432/{name}").database == name

    def test_non_postgresql_backend_refused(self):
        with pytest.raises(UnsafeTestDatabaseError, match="PostgreSQL"):
            _check("sqlite:///tmp/sathupally_test.db")

    def test_unparseable_url_refused(self):
        with pytest.raises(UnsafeTestDatabaseError, match="not parseable"):
            _check("this is not a url")


class TestLocality:
    @pytest.mark.parametrize("host", ["db.example.com", "10.0.0.5", "192.168.1.20", "[::2]"])
    def test_remote_hosts_refused_by_default(self, host):
        url = f"postgresql+psycopg://u:p@{host}:5432/sathupally_test"
        with pytest.raises(UnsafeTestDatabaseError, match="loopback"):
            _check(url)

    def test_remote_host_allowed_only_with_explicit_flag(self):
        url = "postgresql+psycopg://u:p@db.example.com:5432/sathupally_test"
        assert _check(url, allow_remote="1").host == "db.example.com"

    @pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "[::1]"])
    def test_loopback_hosts_accepted(self, host):
        assert _check(f"postgresql+psycopg://u:p@{host}:5432/sathupally_test") is not None


class TestApplicationDatabaseCollision:
    def test_same_host_port_and_database_as_app_is_refused(self):
        with pytest.raises(UnsafeTestDatabaseError, match="application DATABASE_URL"):
            _check(GOOD_URL, app_url=GOOD_URL)

    def test_same_database_on_different_host_is_allowed(self):
        """A provably different server is safe.

        R2.5: this uses a literal IP, not a hostname. Since the guard now fails closed,
        an unresolvable name like `other-host` is rejected because it cannot be *proven*
        different — see TestUnresolvableHostFailsClosed.
        """
        assert _check(
            GOOD_URL, app_url="postgresql+psycopg://u:p@192.0.2.10:5432/sathupally_test"
        ) is not None

    def test_different_database_is_allowed(self):
        assert _check(GOOD_URL, app_url="postgresql+psycopg://u:p@127.0.0.1:5432/sathupally") is not None

    def test_no_configured_app_url_still_enforces_other_layers(self):
        with pytest.raises(UnsafeTestDatabaseError):
            _check("postgresql+psycopg://u:p@127.0.0.1:5432/sathupally", app_url=None)


class TestEnvFileReader:
    def test_reads_value_from_env_file(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("# comment\nDATABASE_URL=postgresql+psycopg://u:p@h/db\nJWT_SECRET=x\n", encoding="utf-8")
        assert read_env_file_value("DATABASE_URL", env) == "postgresql+psycopg://u:p@h/db"

    def test_missing_key_returns_none(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("OTHER=1\n", encoding="utf-8")
        assert read_env_file_value("DATABASE_URL", env) is None

    def test_missing_file_returns_none(self, tmp_path):
        assert read_env_file_value("DATABASE_URL", tmp_path / "nope.env") is None


def test_configured_application_database_url_reads_project_env():
    """The project's own backend/.env must resolve, so the collision check is real."""
    value = configured_application_database_url()
    assert value, "expected an application DATABASE_URL from env or backend/.env"


# ---------------------------------------------------------------------------------------
# R2.4 review fixes: loopback alias normalisation and wildcard rejection.
# Regression cover for two bypasses:
#   (a) 0.0.0.0 was accepted as a loopback host;
#   (b) localhost / 127.0.0.1 / ::1 were compared as literal strings, so the
#       application-vs-test collision check could be skipped by renaming the host.
# ---------------------------------------------------------------------------------------


class TestHostIdentityNormalisation:
    @pytest.mark.parametrize(
        "host",
        ["localhost", "LOCALHOST", "localhost.", "127.0.0.1", "127.0.0.2", "::1", "[::1]", "", None],
    )
    def test_loopback_aliases_collapse_to_one_identity(self, host):
        assert normalize_host(host) == LOOPBACK_IDENTITY

    @pytest.mark.parametrize("host", ["0.0.0.0", "::", "*"])
    def test_wildcard_bind_addresses_are_not_loopback(self, host):
        assert normalize_host(host) == WILDCARD_IDENTITY

    @pytest.mark.parametrize("host", ["db.example.com", "10.0.0.5", "postgres.internal"])
    def test_real_hosts_keep_their_own_identity(self, host):
        assert normalize_host(host) == host


class TestWildcardHostRejected:
    @pytest.mark.parametrize("host", ["0.0.0.0", "[::]"])
    def test_wildcard_test_host_is_refused(self, host):
        with pytest.raises(UnsafeTestDatabaseError, match="wildcard"):
            _check(f"postgresql+psycopg://ssh_app:secret@{host}:5432/sathupally_test")

    def test_wildcard_is_refused_even_with_remote_flag(self):
        """The remote escape hatch must not legitimise a wildcard bind address."""
        with pytest.raises(UnsafeTestDatabaseError, match="wildcard"):
            _check(
                "postgresql+psycopg://ssh_app:secret@0.0.0.0:5432/sathupally_test",
                allow_remote="1",
            )


class TestLoopbackAliasCollisionBypass:
    """The exact bypasses named in the review: the same server under two names."""

    @pytest.mark.parametrize(
        ("app_host", "test_host"),
        [
            ("localhost", "127.0.0.1"),
            ("127.0.0.1", "localhost"),
            ("localhost", "[::1]"),
            ("[::1]", "localhost"),
            ("127.0.0.2", "127.0.0.1"),   # same loopback /8
            ("localhost.", "localhost"),  # trailing FQDN dot
        ],
    )
    def test_alias_pair_with_same_database_is_refused(self, app_host, test_host):
        test_url = f"postgresql+psycopg://ssh_app:secret@{test_host}:5432/sathupally_test"
        app_url = f"postgresql+psycopg://ssh_app:secret@{app_host}:5432/sathupally_test"
        with pytest.raises(UnsafeTestDatabaseError, match="application DATABASE_URL"):
            _check(test_url, app_url=app_url)

    def test_wildcard_application_host_collides_with_loopback_test_host(self):
        """A wildcard app URL may point anywhere, so it must be treated as a collision."""
        with pytest.raises(UnsafeTestDatabaseError, match="application DATABASE_URL"):
            _check(GOOD_URL, app_url="postgresql+psycopg://ssh_app:secret@0.0.0.0:5432/sathupally_test")

    def test_alias_pair_with_different_database_is_allowed(self):
        """Aliasing must not create false positives: different DB names are still safe."""
        assert _check(
            GOOD_URL, app_url="postgresql+psycopg://ssh_app:secret@localhost:5432/sathupally"
        ) is not None


class TestPortAndDatabaseDistinctions:
    def test_different_port_is_not_a_collision(self):
        """A different port is a different PostgreSQL cluster, so it is genuinely safe."""
        assert _check(
            "postgresql+psycopg://ssh_app:secret@127.0.0.1:5433/sathupally_test",
            app_url="postgresql+psycopg://ssh_app:secret@localhost:5432/sathupally_test",
        ) is not None

    def test_same_port_alias_is_a_collision(self):
        with pytest.raises(UnsafeTestDatabaseError, match="application DATABASE_URL"):
            _check(
                "postgresql+psycopg://ssh_app:secret@127.0.0.1:5433/sathupally_test",
                app_url="postgresql+psycopg://ssh_app:secret@localhost:5433/sathupally_test",
            )

    def test_different_database_name_is_not_a_collision(self):
        assert _check(
            "postgresql+psycopg://ssh_app:secret@127.0.0.1:5432/sathupally_test",
            app_url="postgresql+psycopg://ssh_app:secret@127.0.0.1:5432/sathupally",
        ) is not None

    def test_database_name_comparison_is_case_insensitive(self):
        with pytest.raises(UnsafeTestDatabaseError, match="application DATABASE_URL"):
            _check(
                "postgresql+psycopg://ssh_app:secret@127.0.0.1:5432/Sathupally_Test",
                app_url="postgresql+psycopg://ssh_app:secret@localhost:5432/sathupally_test",
            )


class _FakeResult:
    def __init__(self, row=None, scalar=None):
        self._row, self._scalar = row, scalar

    def one(self):
        return self._row

    def scalar(self):
        return self._scalar


class _FakeConnection:
    """Minimal stand-in so the live identity check can be unit-tested without a server."""

    def __init__(self, database="sathupally_test", server_addr="127.0.0.1", server_port=5432, marker=None):
        self.database, self.server_addr, self.server_port, self.marker = (
            database, server_addr, server_port, marker,
        )

    def execute(self, statement, params=None):
        sql = str(statement)
        if "current_database()" in sql:
            return _FakeResult(row=(self.database, self.server_addr, self.server_port))
        if "to_regclass" in sql:
            return _FakeResult(scalar=self.marker)
        raise AssertionError(f"unexpected SQL in fake connection: {sql}")


class TestLiveIdentityVerification:
    """The decisive check: what the server itself reports, not what the URL claimed."""

    def test_live_check_refuses_when_alias_hides_the_application_database(self):
        conn = _FakeConnection(database="sathupally_test", server_addr="127.0.0.1", server_port=5432)
        with pytest.raises(UnsafeTestDatabaseError, match="SAME database"):
            verify_connected_database(
                conn, app_url="postgresql+psycopg://u:p@localhost:5432/sathupally_test"
            )

    def test_live_check_refuses_via_ipv6_alias(self):
        conn = _FakeConnection(database="sathupally_test", server_addr="::1", server_port=5432)
        with pytest.raises(UnsafeTestDatabaseError, match="SAME database"):
            verify_connected_database(
                conn, app_url="postgresql+psycopg://u:p@localhost:5432/sathupally_test"
            )

    def test_live_check_refuses_when_listening_address_is_unknown(self):
        """Unix-socket connection: inet_server_addr() is NULL, so identity is uncertain."""
        conn = _FakeConnection(database="sathupally_test", server_addr=None, server_port=None)
        with pytest.raises(UnsafeTestDatabaseError, match="SAME database"):
            verify_connected_database(
                conn, app_url="postgresql+psycopg://u:p@localhost:5432/sathupally_test"
            )

    def test_live_check_allows_a_distinct_test_database(self):
        conn = _FakeConnection(database="sathupally_test", server_addr="127.0.0.1", server_port=5432)
        assert verify_connected_database(
            conn, app_url="postgresql+psycopg://u:p@localhost:5432/sathupally"
        ) == "sathupally_test"

    def test_live_check_allows_same_name_on_a_different_port(self):
        conn = _FakeConnection(database="sathupally_test", server_addr="127.0.0.1", server_port=5433)
        assert verify_connected_database(
            conn, app_url="postgresql+psycopg://u:p@127.0.0.1:5432/sathupally_test"
        ) == "sathupally_test"

    def test_live_check_still_rejects_a_non_test_database(self):
        conn = _FakeConnection(database="sathupally", server_addr="127.0.0.1", server_port=5432)
        with pytest.raises(UnsafeTestDatabaseError, match="does not end with"):
            verify_connected_database(conn, app_url="postgresql+psycopg://u:p@127.0.0.1:5432/sathupally_test")

    def test_live_check_still_rejects_the_production_marker(self):
        conn = _FakeConnection(marker="platform_production_marker")
        with pytest.raises(UnsafeTestDatabaseError, match="declares itself production"):
            verify_connected_database(conn, app_url=None)


class TestExistingConfigurationStillWorks:
    def test_repository_test_database_configuration_is_accepted(self):
        """The project's own .env test URL must still pass every layer."""
        from tests.conftest import TEST_DB_URL  # noqa: PLC0415

        assert assert_disposable_test_database(
            TEST_DB_URL,
            app_url="postgresql+psycopg://ssh_app:secret@127.0.0.1:5432/sathupally",
            opt_in="1",
            allow_remote="",
        ) is not None

    def test_opt_in_is_still_required_for_the_normalised_path(self):
        """Normalisation must not have relaxed the explicit opt-in."""
        with pytest.raises(UnsafeTestDatabaseError, match="opt-in"):
            assert_disposable_test_database(
                GOOD_URL,
                app_url="postgresql+psycopg://u:p@127.0.0.1:5432/sathupally",
                opt_in="",
                allow_remote="",
            )


# ---------------------------------------------------------------------------------------
# R2.5 review fixes: the application-database identity layer must FAIL CLOSED.
# Previously a missing, unparseable or database-less DATABASE_URL silently skipped the
# collision check, so the strongest safety layer became a no-op.
# ---------------------------------------------------------------------------------------


class TestApplicationIdentityFailsClosed:
    @pytest.mark.parametrize("app_url", ["", "   ", None])
    def test_missing_application_url_refuses(self, app_url, monkeypatch):
        """Requirement 1: no application DATABASE_URL -> refuse."""
        monkeypatch.setattr("tests.guards.configured_application_database_url", lambda: None)
        with pytest.raises(UnsafeTestDatabaseError, match="NOT configured"):
            _check(GOOD_URL, app_url=app_url)

    def test_missing_application_url_refuses_even_with_a_valid_test_url(self, monkeypatch):
        """The test URL is perfect; the reset is refused purely because the app is unknown."""
        monkeypatch.setattr("tests.guards.configured_application_database_url", lambda: None)
        with pytest.raises(UnsafeTestDatabaseError, match="NOT configured"):
            _check(GOOD_URL, app_url=None)

    @pytest.mark.parametrize(
        "bad_url",
        ["not-a-url", "://missing-scheme", "postgresql+psycopg://[::1", "%%%"],
    )
    def test_unparseable_application_url_refuses(self, bad_url):
        """Requirement 2: an unparseable application URL -> refuse."""
        with pytest.raises(UnsafeTestDatabaseError, match="cannot be parsed"):
            _check(GOOD_URL, app_url=bad_url)

    @pytest.mark.parametrize(
        "url_without_db",
        [
            "postgresql+psycopg://u:p@127.0.0.1:5432/",
            "postgresql+psycopg://u:p@127.0.0.1:5432",
        ],
    )
    def test_application_url_without_a_database_refuses(self, url_without_db):
        """Requirement 3: unknown application database identity -> refuse."""
        with pytest.raises(UnsafeTestDatabaseError, match="does not name a database"):
            _check(GOOD_URL, app_url=url_without_db)

    def test_non_postgresql_application_url_refuses(self):
        with pytest.raises(UnsafeTestDatabaseError, match="cannot be compared"):
            _check(GOOD_URL, app_url="mysql+mysqldb://u:p@127.0.0.1:3306/app")

    def test_valid_application_configuration_still_passes(self):
        """Guard against over-correction: a complete configuration is still accepted."""
        assert _check(GOOD_URL) is not None

    def test_refusal_message_does_not_leak_credentials(self):
        with pytest.raises(UnsafeTestDatabaseError) as excinfo:
            _check(GOOD_URL, app_url="not-a-url-at-all-with-s3cret-token")
        assert "s3cret-token" not in str(excinfo.value)


class TestLiveCheckFailsClosed:
    def test_live_missing_application_url_refuses(self, monkeypatch):
        monkeypatch.setattr("tests.guards.configured_application_database_url", lambda: None)
        conn = _FakeConnection()
        with pytest.raises(UnsafeTestDatabaseError, match="NOT configured"):
            verify_connected_database(conn, app_url=None)

    def test_live_unparseable_application_url_refuses(self):
        conn = _FakeConnection()
        with pytest.raises(UnsafeTestDatabaseError, match="cannot be parsed"):
            verify_connected_database(conn, app_url="definitely not a url")

    def test_live_application_url_without_database_refuses(self):
        conn = _FakeConnection()
        with pytest.raises(UnsafeTestDatabaseError, match="does not name a database"):
            verify_connected_database(conn, app_url="postgresql+psycopg://u:p@127.0.0.1:5432/")


class TestDnsAliasIdentity:
    """A DNS name that resolves to the application server must not bypass the check."""

    @staticmethod
    def _resolver(mapping):
        """Override resolution for the hosts in `mapping`; delegate for everything else."""
        from tests import guards

        real = guards._resolve_addresses

        def resolve(host):
            key = (host or "").strip().lower()
            if key in mapping:
                return mapping[key]
            return real(host)

        return resolve

    def test_dns_name_resolving_to_loopback_collides(self, monkeypatch):
        monkeypatch.setattr(
            "tests.guards._resolve_addresses", self._resolver({"app-db.internal": {"127.0.0.1"}})
        )
        with pytest.raises(UnsafeTestDatabaseError, match="application DATABASE_URL"):
            _check(GOOD_URL, app_url="postgresql+psycopg://u:p@app-db.internal:5432/sathupally_test")

    def test_dns_name_resolving_to_a_different_host_is_allowed(self, monkeypatch):
        monkeypatch.setattr(
            "tests.guards._resolve_addresses", self._resolver({"app-db.internal": {"10.20.30.40"}})
        )
        assert _check(
            GOOD_URL, app_url="postgresql+psycopg://u:p@app-db.internal:5432/sathupally_test"
        ) is not None

    def test_unresolvable_host_fails_closed(self, monkeypatch):
        """An unresolvable name cannot be proven different, so the reset is refused."""
        monkeypatch.setattr("tests.guards._resolve_addresses", self._resolver({}))
        with pytest.raises(UnsafeTestDatabaseError, match="application DATABASE_URL"):
            _check(GOOD_URL, app_url="postgresql+psycopg://u:p@unresolvable.invalid:5432/sathupally_test")

    def test_unix_socket_collides_with_a_name_resolving_to_loopback(self, monkeypatch):
        """A Unix-socket application DB is local, so a loopback test DB is the same server."""
        monkeypatch.setattr(
            "tests.guards._resolve_addresses",
            self._resolver({"app-db.internal": {"127.0.0.1"},
                            "": {"127.0.0.1", "::1"}}),
        )
        with pytest.raises(UnsafeTestDatabaseError, match="application DATABASE_URL"):
            _check(
                "postgresql+psycopg://u:p@/sathupally_test",
                app_url="postgresql+psycopg://u:p@app-db.internal:5432/sathupally_test",
            )
