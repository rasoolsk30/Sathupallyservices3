# CHANGELOG

All milestones record the actual files created/modified at file level.
Dates are IST. This project started greenfield on 2026-11-17; there was no pre-existing project to preserve.

---

## Milestone 1 — Project inspection and architecture (2026-11-17)

### Inspection
- Workspace `/home/user` inspected: **empty** (no existing project, no user data at risk).
- No pre-modification backup was required; every archive from this point forward is preserved.

### Files created
| File | Purpose |
|---|---|
| `docs/CAPABILITY-REPORT.md` | Section 25.1 capability matrix with evidence |
| `docs/ARCHITECTURE.md` | System design: module map, state machines, money/time rules, financial accounts, security model, deployment topology, risk register |
| `README.md` | Repo layout + quick start (Linux and Windows) |
| `.gitignore` | Excludes env files, venv, node_modules, storage, backups |
| `backend/requirements.txt`, `backend/requirements-dev.txt` | Pinned dependency sets |
| `backend/.env.example` | Environment template with every integration flagged |
| `scripts/setup_local.sh` | One-command local setup (venv, DB creation, migrations, seed) |
| `scripts/backup_db.sh`, `scripts/restore_db.sh` | Backup/restore with production-name guard |
| `scripts/make_zip.sh` | Reproducible delivery archive builder (excludes secrets/caches) |
| Directory scaffold | `backend/app/{core,models,schemas,api/v1,services}`, `backend/alembic`, `backend/tests`, `frontend/`, `docs/`, `scripts/`, `delivery/` |

### Environment decisions recorded
- PostgreSQL 17.12 installed locally in the build sandbox; databases `sathupally` (dev) and `sathupally_test` (disposable test) created.
- Money = integer **paise** (`BIGINT`) in every financial column. Time stored UTC (`TIMESTAMPTZ`).
- Commission in basis points; default 1000 bps = 10 %.

---

## Milestone 2 — Database and authentication (2026-11-17)

### Database
- **51 ORM tables** across 8 model modules + Alembic configuration; initial migration `244f672fa5b3_initial_schema.py` created by autogenerate and applied — verified 52 tables in PostgreSQL (51 + `alembic_version`).

Files:
- `backend/app/models/base.py` — declarative base, naming conventions, PK/timestamp mixins
- `backend/app/models/enums.py` — 40+ StrEnums (booking status, payment types, ledger accounts, …)
- `backend/app/models/columns.py` — string-backed enum column helper with CHECK constraints
- `backend/app/models/identity.py` — users, roles, permissions, role_permissions, user_roles, auth_refresh_tokens, customer/provider/employee profiles, provider_documents, employee_attendance
- `backend/app/models/catalog.py` — villages, service_zones, service_categories, services, service_pricing, provider_skills, provider_service_areas, provider_availability
- `backend/app/models/customer.py` — customer_addresses, customer_preferences
- `backend/app/models/booking.py` — bookings, booking_items, booking_assignments (partial unique index for one active assignment), booking_status_history, quotations, quotation_items, job_evidence, job_time_logs
- `backend/app/models/finance.py` — payment_methods, payments, payment_webhook_events, invoices, invoice_items, commissions, provider_settlements, settlement_items, employee_compensation, refunds, financial_ledger (UUID entry groups for double-entry postings)
- `backend/app/models/quality.py` — reviews, complaints, dispute_messages, support_tickets
- `backend/app/models/communication.py` — notifications, notification_preferences, message_templates
- `backend/app/models/admin.py` — system_settings, audit_logs, feature_flags, content_pages
- `backend/app/models/__init__.py` — imports all models for autogenerate
- `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`
- `backend/alembic/versions/244f672fa5b3_initial_schema.py`

### Core platform
- `backend/app/core/config.py` — env-driven settings; production boot guard rejects weak JWT secrets / CHANGE_ME DB URLs
- `backend/app/core/db.py` — SQLAlchemy 2.x engine + session with commit/rollback discipline
- `backend/app/core/security.py` — Argon2id hashing, password policy, HS256 access tokens (issuer + type claims), refresh-token helpers (SHA-256 at rest)
- `backend/app/core/errors.py` — uniform `{"error": {...}}` envelope + handlers for app/validation/HTTP/unhandled errors
- `backend/app/core/ratelimit.py` — in-process sliding-window limiter (single-worker caveat documented)
- `backend/app/core/audit.py` — append-only audit writer
- `backend/app/core/deps.py` — bearer auth, `AuthContext` with DB-loaded roles+permissions, `require_permissions` dependency factory

### Authentication API (`/api/v1/auth`)
- `backend/app/api/v1/auth.py` — register (customer + profile + preferences in one transaction), login (phone/email, per-IP and per-account limits, 5-strike 15-minute lockout), refresh with rotation + reuse detection (revokes the token family), logout (single/all sessions), me (roles + permission list), verify-otp returns **honest 503** until an SMS provider is configured
- `backend/app/schemas/auth.py` — request/response schemas, Indian phone normalisation to +91 E.164
- `backend/app/schemas/common.py` — pagination envelope, message response, paise formatting helper
- `backend/app/api/v1/router.py`, `backend/app/main.py` — app wiring, CORS (bearer-only, no cookies ⇒ no CSRF surface), health endpoint with DB check, production-only docs disable

### Reference data
- `backend/app/seed.py` — idempotent reference seed: **84 permissions, 7 roles, 180 role-permission links, 4 payment methods, 5 feature flags, 7 system settings, 4 draft content pages, 14 message templates, 10 categories, 38 services (Telugu + English), 1 village**. Shipping **zero users, providers, bookings, payments or reviews**.
- `backend/scripts/create_admin.py` — creates the first Super Admin from CLI + env password (no demo credentials in source)
- Prices deliberately seeded as `QUOTE_ONLY` with 0 amount and a note that the owner must configure real prices before pilot.

### Tests
- `backend/tests/conftest.py` — disposable `*_test` DB guard, real Alembic migrations in test setup, seed, per-test transaction rollback, dependency override, factories
- `backend/tests/test_health.py` — health, OpenAPI, error envelope
- `backend/tests/test_auth.py` — 22 tests: registration variants, duplicate/weak-password/invalid-phone, Argon2 at rest, login by phone/email, wrong password, lockout, inactive account, SQL-injection-safe login, token refresh rotation + reuse revocation, logout single/all, OTP honest 503, RBAC dependency unit tests
- `backend/tests/test_seed_reference.py` — no seeded users, role matrix correctness, bilingual catalogue, 50 required tables present, active-assignment unique index enforced

### Database changes
- Migration `244f672fa5b3` (initial schema). No destructive operations were performed on any existing data.

### Defects found & fixed during the milestone
1. Ambiguous FK on `User.user_roles` (two FKs to `users`) → explicit `foreign_keys`.
2. `OPS_PERMS` referenced an undefined permission `admin:attendance:manage` → added the permission plus a seed-time guard that fails fast on any undefined permission code.
3. Test email domain `.test` rejected by the email validator (reserved TLD) → tests use `example.com`.

### Remaining issues at end of M2
- Rate limiting and rate-limit state are per-process (single worker only).
- Admin MFA schema columns exist; TOTP enrolment endpoint not built yet.
- OTP and email delivery are not integrated (explicitly disabled, honest 503 / no fake sends).

### Manual verification required from owner
- Confirm the village list and service catalogue wording/pricing before the pilot.

---

## Milestone 2.1 — independent review corrections (2026-11-17)

The owner's independent review of the M1/M2 archives identified four defects. All four were
reproduced, fixed, and covered by regression tests that fail on the pre-fix code.

### Defects, root cause and fix

| # | Defect | Root cause | Fix |
|---|---|---|---|
| 1 | Failed-login counters and lockouts never persisted | `get_db` rolls back on exceptions; the counter was mutated and then `AuthError` was raised, discarding it | `_commit_security_state()` commits attempt counters, lockout and audit rows **before** raising |
| 2 | Refresh-token family revocation never persisted | Same rollback path discarded the `UPDATE … revoked_at` on reuse detection | Revocation is committed before raising; family stays dead |
| 3 | Production guard accepted lowercase/dev credentials | Check compared only the literal `"CHANGE_ME"` | Case-insensitive denylist over the parsed URL password (exact + substring), minimum length, no-password rejection, unparseable-URL rejection, JWT rules extended |
| 4 | `X-Forwarded-For` trusted from any client | `client_ip()` returned the left-most header entry unconditionally | Trust only when the socket peer is in `TRUSTED_PROXIES`; scan hops right-to-left and take the first non-proxy address |

**Additional issue found while verifying #4:** uvicorn's default `--proxy-headers` rewrites
`request.client` from `X-Forwarded-For` for peers in `forwarded-allow-ips` (default `127.0.0.1`),
so the spoofed address reached the app before its own trust logic ran. Fixed operationally by
running with `--no-proxy-headers` (README, setup script, architecture doc) and by adding a
middleware that logs a security warning when the header arrives with no trusted proxy configured.

**Test-harness defect (why the suite missed 1 and 2):** the `client` fixture overrode `get_db`
with a generator that never rolled back, so rollback-dependent behaviour was untestable. It now
uses the production contract (commit on success, rollback on exception).

### Files changed
| File | Change |
|---|---|
| `backend/app/api/v1/auth.py` | `_commit_security_state()`; lockout/attempt/audit persistence; reuse revocation persistence; security-event logging; `sqlalchemy.update` import |
| `backend/app/core/config.py` | Case-insensitive production denylists, `production_problems()`, parsed-URL password checks, `trusted_proxies` setting |
| `backend/app/core/ratelimit.py` | Trusted-proxy `client_ip()`, IP/CIDR parsing, bracketed IPv6 and `host:port` handling, network cache |
| `backend/app/main.py` | `X-Forwarded-For` guard middleware + `time` import |
| `backend/tests/conftest.py` | `connection`/`session_factory`/`db_session` fixtures; `make_production_get_db()`; production-semantics `client` |
| `backend/tests/test_review_regressions.py` | **New** — 34 regression tests covering findings 1–4 |
| `backend/.env.example` | `TRUSTED_PROXIES` documented |
| `README.md`, `scripts/setup_local.sh` | `uvicorn --no-proxy-headers` in run commands and proxy guidance |
| `docs/ARCHITECTURE.md` | §6 client-IP / proxy trust model |
| `CHANGELOG.md`, `TEST-REPORT.md` | This addendum |

### Database changes
None. No migration was added or altered; schema remains `244f672fa5b3`.

### Test results
`pytest` → **64 passed, exit 0** (was 30). Pre-fix code + new tests → **26 failed, 8 passed, exit 1**.

---

## Milestone 2.2 — second review round: test-DB safety, row locking, password change (2026-11-17)

Two further defects and three follow-ups from the owner's independent review of the M2.1 archive.

### Finding 5 — destructive test-database reset was under-protected
`conftest.py` dropped the `public` schema guarded only by a "name contains test" substring check.

**Fix — layered guard in `backend/tests/guards.py` (new module).** A destructive reset now requires
**all** of:

1. Explicit opt-in `SSH_ALLOW_DESTRUCTIVE_TEST_DB_RESET=1` (nothing in the repo sets it implicitly).
2. PostgreSQL backend, and a database name that **ends** with `_test` (suffix, not substring).
3. Not a reserved/system name (`postgres`, `template0/1`, `sathupally`, `production`, `prod`).
4. Loopback host unless `SSH_ALLOW_REMOTE_TEST_DB=1` is deliberately set.
5. Not the same host/port/database as the configured application `DATABASE_URL` (env or `backend/.env`).
6. Live re-check after connecting: `current_database()` must end with `_test`, and the database must
   not contain a `platform_production_marker` table (an operator-created "I am production" marker).

Failures abort with `pytest.exit(..., returncode=2)` listing **every** violated layer.
`scripts/run_tests.sh` provides the opt-in for ordinary local runs.

### Finding 6 — authentication was not concurrency-safe
Failed-login counting and refresh-token rotation were read-modify-write cycles with **no row locks**,
so concurrent requests could lose increments or mint two valid sessions from one token.

**Fix — PostgreSQL row-level locking in `app/api/v1/auth.py`.**
- `_locked_user()` takes `SELECT … FOR UPDATE` on the user row before any attempt-counter mutation;
  the success path re-checks lockout state under the same lock.
- `/auth/refresh` takes `SELECT … FOR UPDATE` on the token row, so simultaneous refreshes serialise;
  the loser observes `revoked_at` and triggers reuse detection.
- Lock order is always user row → token rows (reuse path locks the user first) to stay deadlock-free.
- **Second-order bug found while testing:** `FOR UPDATE` alone was insufficient because SQLAlchemy
  returned the *stale identity-map instance*, discarding the increment committed by the transaction
  we had just waited for. Fixed with `execution_options(populate_existing=True)` on both locked reads.
  This was caught by the new concurrency test reporting `failed_login_count == 1` instead of 8.

### Item 3 — `must_change_password` enforced
- `create_access_token` carries a `pwd_change_required` claim; `get_current_user` refuses every
  endpoint except an allowlist (`/auth/me`, `/auth/change-password`, `/auth/logout`, `/auth/refresh`)
  with `403 password_change_required`. Backend-enforced, not UI-only.
- New `POST /api/v1/auth/change-password`: verifies the current password, applies the shared password
  policy, rejects reuse of the same password, rehashes with Argon2id, clears the flag, revokes every
  existing session and returns a fresh token pair for this device.
- `UserOut` now exposes `must_change_password` so clients can route to the change screen.
- Failed attempts are audited (`auth.password_change_failed`); success is audited (`auth.password_changed`).

### Item 4 — single-worker rate limiting documented explicitly
- `docs/KNOWN-LIMITATIONS.md` created (limitations register, L1–L9).
- `docs/ARCHITECTURE.md` §6.1 states the constraint and demands a shared limiter before scale-out.
- `README.md` points to the register; production startup logs an explicit warning.

### Files changed in this round
| File | Change |
|---|---|
| `backend/tests/guards.py` | **New** — layered destructive-reset guard |
| `backend/tests/conftest.py` | Guard wiring, `PROTECTED_APP_DB_URL` captured pre-override, `live_server`/`live_client`/`cleanup_phones` fixtures, blunt substring assert removed |
| `backend/app/api/v1/auth.py` | Row locking + `populate_existing`, `change-password` endpoint, `must_change_password` claim, password-change auditing |
| `backend/app/core/deps.py` | `password_change_required` enforcement + allowlist |
| `backend/app/schemas/auth.py` | `ChangePasswordRequest`; `must_change_password` on `UserOut` |
| `backend/app/main.py` | Production warning about in-process rate limiting |
| `backend/tests/test_testdb_guard.py` | **New** — 43 guard tests |
| `backend/tests/test_concurrency_auth.py` | **New** — 5 concurrency tests on a real uvicorn server |
| `backend/tests/test_password_change.py` | **New** — 14 enforcement/change-flow tests |
| `scripts/run_tests.sh` | **New** — sets the destructive-test opt-in |
| `docs/KNOWN-LIMITATIONS.md` | **New** — limitations register |
| `docs/ARCHITECTURE.md`, `README.md` | Rate-limit limitation, test-safety instructions |

### Database changes
None. Still the single migration `244f672fa5b3`.

### Test results
`pytest` → **126 passed, exit 0** (was 64). Removing the row locks in a scratch copy → the 4 genuine
concurrency tests fail. Removing the guard opt-in → run aborts with exit 2.

### Defects found and fixed *during* this round
1. Guard's own collision check read `DATABASE_URL` after conftest overwrote it → false collision;
   fixed by capturing the protected URL before the override.
2. `FOR UPDATE` without `populate_existing` still lost updates (identity-map staleness).
3. Short passwords returned `validation_error` instead of the documented `weak_password`; policy now
   owns length checks for the change-password endpoint.
4. Test authoring errors (IPv6 URLs need brackets, a stale token legitimately revokes the family).

---

## Milestone 2.3 — consistent database lock order (2026-11-17)

Independent review of R2 found an inconsistent lock order that could deadlock PostgreSQL.

### Defect
| Path | Order before | Order required |
|---|---|---|
| `POST /auth/refresh` | token row → **then** user row (reuse path) | user → token |
| `POST /auth/change-password` | user → tokens | user → token |
| `POST /auth/logout` | tokens only (no user lock) | user → token |

`refresh` holding a token lock while waiting for the user lock, against `change-password`
holding the user lock while waiting for token rows, is an ABBA cycle. PostgreSQL resolves it by
aborting one transaction with `deadlock detected` (SQLSTATE 40P01).

### Fix — one enforced order: **USER row first, then refresh-token rows**
- `_lock_user_row()` and `_lock_token_row()` are the only lock helpers; both use
  `SELECT … FOR UPDATE` with `populate_existing=True`.
- `/refresh` now: (0) **unlocked** probe to discover the owning user → (1) lock USER →
  (2) lock TOKEN and re-read it under the lock (state may have changed while waiting) →
  (3) rotate or run reuse detection, which mutates the family **while the user lock is held**.
- `/logout` now takes the user lock first even though it only mutates token rows, so *every*
  transaction that touches both lock classes follows the same order.
- Deadlock errors are **not** caught or suppressed anywhere; they cannot occur because the order
  is uniform. The generic error handler would surface any such error as HTTP 500.

### Files changed
| File | Change |
|---|---|
| `backend/app/api/v1/auth.py` | `_lock_user_row`/`_lock_token_row` helpers; refresh restructured to user→token; logout takes user lock; module docstring documents the invariant |
| `backend/tests/test_lock_order.py` | **New** — 10 tests (hazard proof, SQL-order assertions, three endpoint races) |
| `backend/tests/conftest.py` | `cleanup_phones` normalises numbers to E.164 (see defects below) |
| `docs/ARCHITECTURE.md` | §6 lock-order invariant |
| `docs/KNOWN-LIMITATIONS.md` | L10 lock-order discipline + residual risk |
| `CHANGELOG.md`, `TEST-REPORT.md` | This addendum |

### Test evidence
- Full suite: **136 passed, exit 0** (was 126), run twice consecutively with zero leftover rows.
- With the original order restored in a scratch copy, three deterministic tests fail:
  `test_refresh_locks_user_before_token`, `test_refresh_reuse_path_locks_user_before_token`,
  `test_logout_locks_user_before_tokens`.
- `test_inverted_lock_order_deadlocks_postgres` proves the hazard is real: PostgreSQL aborts one
  transaction with SQLSTATE 40P01 for the inverted sequence.

### Defects found and fixed *during* this round
1. **Leftover rows from live-server tests.** `cleanup_phones` stored raw 10-digit numbers while
   accounts are stored as `+91…`, so the teardown `DELETE` matched nothing. This polluted later
   assertions (`test_seed_created_no_users`) and produced 409 conflicts on re-runs. Teardown now
   normalises to E.164; verified `leftover_users=0` after two consecutive full runs.
2. **Vacuous SQL assertions.** Early versions of the race tests queried by un-normalised phone and
   therefore matched no rows; assertions were tightened to the E.164 identity.
3. **Superuser-only setting in a test.** `SET deadlock_timeout` requires superuser; the test now
   relies on PostgreSQL's 1s default and sets only `lock_timeout`.
4. **Two race assertions encoded the wrong invariant.** When the password change wins the race, the
   replacement session it issues legitimately remains active. Assertions now require that no
   *pre-race* session survives and that any survivor is the change's own replacement.

---

## Milestone 2.4 (R2.2) — commit-after-response defect fixed (2026-11-17)

### Defect
Every mutating endpoint relied on the `get_db` yield-dependency to commit. FastAPI runs that
dependency's exit code **after** the response has been flushed to the ASGI server, so a client
could receive `200 OK` while the transaction was still open.

**Proof of mechanism (framework-level probe, no project code):** with a 3 ms commit simulated in
the dependency teardown, **20/20** responses reached the client *before* the commit completed.
Earlier measurements against this API found the issued refresh token invisible to an independent
connection immediately after `200` in **25/25** cases, and the password-change revocation leaving
**4 active sessions instead of 1** in **10/10** cases.

**Security impact.** `POST /auth/change-password` revokes every session, but a login whose INSERT
committed only after the response escaped the revocation, because the revocation UPDATE could not
see an uncommitted row. Any caller could also read stale state from a different connection
immediately after a success response.

**Why the suite hid it for so long.** `TestClient` finalises dependencies before the test's
assertions run, so 136 in-process tests stayed green. Only the three live-server tests exercised
real network timing — and one of them failed in 2 of 5 runs.

### Fix
- New `commit_or_raise(db)` in `app/core/db.py` commits on the request session and rolls back on
  failure. Its docstring states the rule and the security rationale.
- Explicit `commit_or_raise(db)` before the success return in all five mutating handlers:
  `register`, `login`, `refresh` (rotation), `change-password`, `logout`.
- `get_db` keeps its commit as a **safety net only** and is documented as unable to guarantee
  read-after-write visibility, so the trap cannot be re-introduced silently.
- Lock order (user row → token rows) is unchanged; `_lock_user_row`/`_lock_token_row` are untouched.
- `_commit_security_state()` failure paths are unchanged and still commit before raising.

### Files changed
| File | Change |
|---|---|
| `backend/app/core/db.py` | Added `commit_or_raise()`; documented why teardown commit cannot be trusted |
| `backend/app/api/v1/auth.py` | Explicit commit on all five mutating success paths; docstring notes persistence ordering |
| `backend/tests/test_commit_ordering.py` | **New** — 7 read-after-write regression tests, repeated 12× each on an independent `psycopg` connection |
| `docs/KNOWN-LIMITATIONS.md` | New L11 (durability ordering + rule for future endpoints) |
| `docs/ARCHITECTURE.md` | §2 persistence-ordering rule |
| `CHANGELOG.md`, `TEST-REPORT.md` | This addendum |

### Test results
Full suite (**143 tests**, was 136): **8 consecutive runs, 143 passed each, exit code 0**.
Previously 2 of 5 runs failed. Pre-fix code against the new tests: **6 of 7 failed**.

### Not changed
Lock ordering, token rotation semantics, reuse detection, password policy, RBAC, test-DB guards,
migrations (still the single revision `244f672fa5b3`), and all five prior archives.

---

## Milestone 2.5 (R2.3) — review fixes: security-state commit failure, documentation accuracy (2026-11-17)

### Defect (review finding) — commit failure disguised as an authentication rejection

`_commit_security_state()` in `backend/app/api/v1/auth.py` did this:

```python
try:
    db.commit()
except Exception:                      # swallowed
    db.rollback()
    log.exception(...)
raise error                            # original auth error, unconditionally
```

The three call sites are the security-critical rejection paths: failed login (attempt counter,
lockout, audit row), refresh-token reuse (whole-family revocation, audit row), and incorrect
current password on change-password (audit row).

If the commit failed, the client still received `401 invalid_credentials`. That is a false
statement about system state: the failed-login counter did not increment, the audit row was
discarded, and an account could be brute-forced indefinitely with every attempt reported as an
ordinary rejection.

### Fix

- New `SecurityStateNotPersistedError` (503, code `security_state_not_persisted`) in
  `app/core/errors.py`. Its message is fixed and carries no SQL, driver detail, credentials or
  stack trace; it is rendered by the existing `AppError` envelope handler.
- `_commit_security_state()` now rolls back, logs the real cause server-side only, and raises
  `SecurityStateNotPersistedError() from None`. **The original authentication error is raised
  only when the commit succeeds.**
- Rollback itself is wrapped so a dead connection cannot mask the failure.
- `commit_or_raise()` and all five mutating success paths are unchanged (verified correct).

### Review item 2 — verification, not rewrite (all checked, no defects found)

| Checked | Method | Result |
|---|---|---|
| `commit_or_raise()` + all mutating endpoints | grep of every `@router.post` and its commit path | 5/5 mutating endpoints commit before returning. `POST /verify-otp` writes nothing (pure 503) so needs none |
| register / login / refresh / logout / change-password ordering | `tests/test_commit_ordering.py` × 5 consecutive runs | 7 passed each |
| Refresh-token reuse detection + family revocation | `tests/test_lock_order.py` + new reuse tests | passed |
| User-first, token-second lock ordering | `_lock_user_row` at line 295 precedes `_lock_token_row` at 301; refresh/logout/change-password all user-first | unchanged |
| Concurrent failed-login counters, simultaneous refresh | `tests/test_concurrency_auth.py` + `test_lock_order.py` × 5 runs | 15 passed each |
| `must_change_password` enforcement | `app/core/deps.py` server-side allowlist; `tests/test_password_change.py:60` asserts 403 `password_change_required` | correct |
| Destructive test-DB safeguards | `tests/test_testdb_guard.py` × 3 runs | 43 passed each |

One test expectation of my own was wrong and was corrected rather than changing working code:
on lockout the counter deliberately resets to 0 (`auth.py`, existing `test_concurrency_auth.py:102`),
so the durable evidence of a lockout is `locked_until`, not `failed_login_count`.

### Review item 3 — documentation accuracy

Verified against the real tree and corrected:

| Claim | Reality | Action |
|---|---|---|
| `README.md` layout listed `frontend/` as existing | `frontend/` does not exist (Milestone 3 not started) | Layout now states it is absent; explicit "Not yet present" paragraph |
| `README.md`: "Full instructions: `docs/INSTALL_LOCAL.md`" | File does not exist | Replaced with a statement that the guide is unwritten until Milestone 11 |
| `README.md` layout: "docs/ — architecture, manuals, security, operations, deployment" | Only 3 docs exist | Listed the three actual files |
| `docs/CAPABILITY-REPORT.md`: "PostgreSQL 17.12" | Verified 17.11 in this environment | Corrected with a note about the sandbox image change |

### Files changed

| File | Change |
|---|---|
| `backend/app/core/errors.py` | Added `SecurityStateNotPersistedError` |
| `backend/app/api/v1/auth.py` | `_commit_security_state()` propagates persistence failure instead of swallowing it |
| `backend/tests/test_security_state_commit.py` | **New** — 9 tests (success persistence + commit-failure behaviour) |
| `README.md` | Removed false `frontend/` and `docs/INSTALL_LOCAL.md` claims |
| `docs/CAPABILITY-REPORT.md` | PostgreSQL version corrected |
| `docs/KNOWN-LIMITATIONS.md` | New L12 (security-state persistence failure) + L13 (documentation drift) |
| `CHANGELOG.md`, `TEST-REPORT.md` | This addendum |

### Test results

Full suite **152 tests** (was 143): **3 consecutive runs, 152 passed, exit code 0**.
Discrimination: against the R2.2 implementation, **5 of 5** commit-failure tests fail.
Targeted repeats: commit-ordering ×5, concurrency+lock-order ×5, test-DB guards ×3 — all green.

### Not changed

Lock ordering, token rotation/reuse semantics, password policy, RBAC, rate limiting, migrations
(still `244f672fa5b3`), and all six prior archives.

---

## Milestone 2.6 (R2.4) — test-database guard identity bypass fixed (2026-11-17)

### Defect 1 (review item 1) — already corrected in R2.3, verified not rewritten

The review restated the `_commit_security_state()` finding. That was fixed in Milestone 2.5:
a failed commit now rolls back and raises `503 security_state_not_persisted` instead of
returning the original 401. Verified against this round's specification:

| Requirement | Status |
|---|---|
| Commit succeeds → raise original auth error | yes (`raise error` after a successful commit) |
| Commit fails → roll back | yes, guarded so a dead connection cannot mask it |
| Log the real exception server-side only | yes (`log.exception`, never sent to the client) |
| Sanitized 5xx | yes — 503 `security_state_not_persisted` (an appropriate 5xx) |
| No credentials/SQL/internals to client | asserted by `_assert_no_leak` over 10 markers |
| Never return the original 401 on failure | yes — `raise ... from None` replaces it |

All five mandatory regression tests exist and pass (`tests/test_security_state_commit.py`).

### Defect 2 (review item 2) — NEW, fixed here

`backend/tests/guards.py` had three real bypasses, each reproduced before the fix:

| Bypass | Pre-fix behaviour |
|---|---|
| `0.0.0.0` listed in `LOOPBACK_HOSTS` | accepted as a loopback test host |
| Hosts compared as literal strings | app `localhost` vs test `127.0.0.1` with the **same database name** was ALLOWED → the destructive reset would have dropped the application database |
| Same, IPv6 | app `localhost` vs test `[::1]`, same database name → ALLOWED |
| Wildcard on the app side | app `0.0.0.0` vs test `127.0.0.1`, same database name → ALLOWED |
| Live check took no application URL | `verify_connected_database(conn)` could not compare what the server reported against the application database |

**Fix**

- `0.0.0.0`, `::` and `*` removed from accepted destinations and rejected explicitly, even when
  `SSH_ALLOW_REMOTE_TEST_DB=1` is set.
- New `normalize_host()` maps `localhost`, any `127.0.0.0/8` address, `::1`, `[::1]`, a trailing
  FQDN dot and an empty host (Unix socket) to one `LOOPBACK_IDENTITY` using the stdlib
  `ipaddress` module; `0.0.0.0`/`::` map to `WILDCARD_IDENTITY`.
- Collision test now compares normalised identities and fails closed when either side is a
  wildcard; port and database-name checks preserved (and database names compare case-insensitively).
- `verify_connected_database(connection, *, app_url=None)` now reads
  `current_database()`, `host(inet_server_addr())` and `inet_server_port()` and refuses when the
  live identity equals the application database's identity. A NULL address (Unix socket) is
  treated as loopback, i.e. uncertain → refuse.
- Reserved-name check added to the live verification.
- Explicit destructive-test opt-in and the production-marker check are unchanged and still
  enforced (regression-tested).

**End-to-end proof** (`verification/logs/guard_blocks_destructive_reset.log`): with the test URL
and application URL naming the same database through different aliases, pytest exits with
**code 2** and the table count stays at **52 before and after** — no DROP occurred.

### Files changed

| File | Change |
|---|---|
| `backend/tests/guards.py` | Host normalisation, wildcard rejection, normalised collision test, strengthened live identity verification |
| `backend/tests/conftest.py` | Passes the protected application URL to the live check |
| `backend/tests/test_testdb_guard.py` | **39 new tests** (43 → 82) |
| `verification/probe_guard_behaviour.py` | **New** — 7-case behavioural probe used for discrimination |
| `verification/logs/*.log` | **New** — executed test output committed with the source |
| `scripts/make_zip.sh` | Excludes `.git` from delivery archives |
| `.gitignore` | **New** — keeps secrets, caches and build output out of version control |
| `docs/KNOWN-LIMITATIONS.md` | New **L14** (DNS-resolved aliases remain a residual gap) |
| `CHANGELOG.md`, `TEST-REPORT.md` | This addendum |

### Test results

Full suite **191 tests** (was 152): **2 consecutive runs, 191 passed, exit code 0**.
Guard tests independently: 82 passed, exit 0, ×3 repeats. Discrimination: the 7-case probe scores
**3/7 against R2.3 and 7/7 against R2.4**.

### Not changed

Authentication flows, lock ordering, token rotation, rate limiting, RBAC, migrations
(`244f672fa5b3`) and all seven prior archives.

---

## Milestone 2.7 (R2.5) — fail-open collision check fixed; DNS identity documented honestly (2026-11-17)

### Defect (review finding) — collision check failed OPEN

`assert_disposable_test_database()` and `verify_connected_database()` both did this:

```python
candidate_app_url = app_url if app_url is not None else configured_application_database_url()
if candidate_app_url:          # <-- skipped entirely when nothing is configured
    try:
        app = make_url(candidate_app_url)
    except Exception:
        app = None             # <-- collision check skipped when parsing fails
    if app is not None:
        ...                    # the safety layer
```

So the strongest safety layer became a no-op whenever the application URL was missing, malformed,
or named no database. A developer who cloned the repo without `backend/.env` (or with a typo in
`DATABASE_URL`) would have run the destructive suite with **no collision protection at all** —
only the `_test` suffix layer, which cannot detect a misconfigured `TEST_DATABASE_URL`.

### Fix — the identity layer now fails closed

- New `_application_database_identity()` is the single place that resolves the application URL and
  raises a problem when it is **missing**, **unparseable**, **non-PostgreSQL**, or **names no
  database**. Nothing is skipped; the reset is refused in every one of those cases.
- `assert_disposable_test_database()` and `verify_connected_database()` both use it, so the URL
  layer and the live layer behave identically.
- Error messages explain the fix without echoing the URL (no credential leakage).

### Safety correction found while fixing this

With `app_url=None` the guard re-read the `DATABASE_URL` environment variable — but `conftest`
overwrites that variable with the **test** URL before the guard runs. The refusal therefore fired
as a confusing "self collision" instead of "application database is not configured".
`conftest` now passes `""` explicitly when no application URL exists, so the accurate reason is
reported. Verified end-to-end (`verification/logs/fail_closed_end_to_end.log`).

### DNS alias identity — implemented, not just documented

The review asked for either a real DNS-resolved comparison or an honest limitation. Both:
`_same_server()` now resolves hostnames with `socket.getaddrinfo` when two hosts differ
syntactically (i.e. only when a collision is actually possible) and treats a shared address as the
same server. Inconclusive resolution is treated as **same**, so uncertainty can never authorise a
destructive reset.

`docs/KNOWN-LIMITATIONS.md` L14 was rewritten: it no longer claims the live check reliably catches
DNS aliases, and now lists the genuine residual gaps (TOCTOU, NAT/proxy-reported addresses, the
DNS-unavailable availability trade-off, and that this is not a security boundary).

### One pre-existing test expectation changed (disclosed)

`test_same_database_on_different_host_is_allowed` used the hostname `other-host`. Under fail-closed
resolution an unresolvable name cannot be *proven* different, so the guard now refuses it. The test
was changed to use a literal IP (`192.0.2.10`, TEST-NET-1) which preserves its original intent —
"a provably different server is allowed" — without weakening the guard.

### Files changed

| File | Change |
|---|---|
| `backend/tests/guards.py` | `_application_database_identity()` (fail closed), `_resolve_addresses()`, resolver-aware `_same_server()`, module docstring |
| `backend/tests/conftest.py` | Passes `""` instead of `None` when no application URL exists |
| `backend/tests/test_testdb_guard.py` | **20 new tests** (82 → 102); one expectation changed as disclosed above |
| `verification/probe_guard_behaviour.py` | Extended to 10 cases (fail-open cases 8–10) |
| `verification/logs/*.log` | Re-executed test output |
| `docs/KNOWN-LIMITATIONS.md` | L14 rewritten |
| `README.md` | Notes that running the suite now requires an explicit application `DATABASE_URL` |
| `CHANGELOG.md`, `TEST-REPORT.md` | This addendum |

### Test results

Full suite **211 tests** (was 191): **2 consecutive runs, 211 passed, exit code 0**.
Guard tests independently: **102 passed, exit 0**, ×3.
Discrimination: the 10-case probe scores **7/10 against R2.4 and 10/10 against R2.5**.
End-to-end: missing / unparseable / database-less application URLs each abort a real pytest run
with **exit code 2** and **52 tables before and after** — no `DROP` executed.

### Not changed

Authentication code, lock ordering, token rotation, rate limiting, RBAC, migrations
(`244f672fa5b3`), and all eight prior archives.

---

## Milestone 2.8 (R2.6) — release-evidence correction; GitHub dotfile omission fixed (2026-11-17)

R2.6 exists solely to close the two blockers found during independent verification of R2.5.
No application code, test logic, migration, guard rule or database behaviour was changed.

### Blocker 1 — stale verification evidence

`verification/logs/new_regression_tests.log` was an **R2.4 artefact** (captured
2026-11-17T14:19:23Z) reporting **82** guard tests. The R2.5 tree contains **102** guard tests, so
the shipped log contradicted the release it shipped with.

It is now regenerated from a genuine run against the frozen R2.5 source:

```
collected 102 items -> 102 passed, 1 warning in 0.13s     EXIT_CODE=0
collected   9 items ->   9 passed, 1 warning in 9.53s     EXIT_CODE=0
```

Three further logs carried stale R2.4 headers/timestamps. Each was **re-executed** and
re-captured (not merely re-labelled):

| Log | Action | Evidence produced |
|---|---|---|
| `environment_identity.log` | re-captured | PG 17.11 / 170011, `sathupally_test`, 52 tables, alembic `244f672fa5b3`, source SHA-256 fingerprints, 211 collected |
| `guard_blocks_destructive_reset.log` | re-executed | alias collision refused, `PYTEST_EXIT=2`, tables 52 → 52 |
| `fail_closed_end_to_end.log` | re-executed | 3 scenarios, each `PYTEST_EXIT=2`, tables 52 → 52 |
| `full_suite_run1/2.log` | re-run | 211 passed, 0 failed, 0 skipped, exit 0, both runs |

No timestamp, count or environment value was written without a command producing it.

### Blocker 2 — GitHub omitted two dotfiles

Commit `edb7077b` (`"Add files via upload"`) was created through GitHub's **web uploader**, which
silently skips dot-prefixed paths. Consequently `.gitignore` (177 B) and `backend/.env.example`
(1,681 B) were present in every ZIP but absent from the repository.

That broke a documented instruction: `README.md` line 45 tells Windows users to run
`copy backend\.env.example backend\.env`, and a fresh clone had no such file.

Both files are now added (with `git add -f`). Verified after the fix: the file exists in a fresh
clone, the copy step produces `backend/.env` (1,681 bytes), and `.gitignore` rule
`.gitignore:2:backend/.env` correctly keeps the resulting secret out of version control.

### Files changed

| File | Change | Reason |
|---|---|---|
| `verification/logs/new_regression_tests.log` | regenerated | was stale R2.4 (82 vs 102) |
| `verification/logs/environment_identity.log` | re-captured | stale R2.4 header |
| `verification/logs/guard_blocks_destructive_reset.log` | re-executed | stale R2.4 timestamp |
| `verification/logs/fail_closed_end_to_end.log` | re-executed | R2.6 coherence |
| `verification/logs/full_suite_run1.log` | re-run | R2.6 evidence |
| `verification/logs/full_suite_run2.log` | re-run | R2.6 evidence |
| `CHANGELOG.md`, `TEST-REPORT.md` | this addendum | release record |

**Source files changed: none.** `backend/app/**`, `backend/tests/**`, `backend/alembic/**` and
`scripts/**` are byte-identical to R2.5.

### Test results

Full suite **211 passed, 0 failed, 0 skipped, 0 errors, exit code 0**, run twice.
