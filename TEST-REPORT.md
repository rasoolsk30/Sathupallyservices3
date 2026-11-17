# TEST REPORT

**Project:** SATHUPALLY SERVICE HUB
**Date:** 2026-11-17 (Asia/Kolkata)
**Scope of this report:** Milestones 1 and 2
**Rule:** every result below is from a command that actually ran in this session. Nothing is predicted or assumed.

Legend: **PASS** = ran and passed · **FAIL→FIXED** = ran, failed, was fixed, re-ran and passed · **BLOCKED** = could not run (reason given) · **NOT RUN** = not attempted yet.

---

## 1. Environment (verified, not assumed)

| Item | Command | Real result | Status |
|---|---|---|---|
| Python | `python3 --version` | Python 3.13.18 | PASS |
| Node / npm | `node --version; npm --version` | v20.20.2 / 10.8.2 | PASS |
| PostgreSQL | `apt-get install postgresql` then `psql --version` | exit 0; PostgreSQL 17.12 | PASS |
| DB user/databases | `CREATE USER ssh_app…; CREATE DATABASE sathupally; CREATE DATABASE sathupally_test;` | exit 0, `SELECT current_database(), current_user;` → `sathupally / ssh_app` | PASS |
| Python deps | `pip install fastapi uvicorn[standard] sqlalchemy alembic psycopg[binary] pydantic-settings pyjwt argon2-cffi python-multipart pytest httpx email-validator` | exit 0; fastapi 0.163.1, sqlalchemy 2.1.9, alembic 1.20.1, PyJWT 2.15.1, psycopg 3.3.9 | PASS |
| Network to PyPI/npm | `curl -sI https://pypi.org/simple/` etc. | HTTP 200 / HTTP 200 | PASS |

## 2. Application import & schema construction

```
$ cd backend && PYTHONPATH=. python3 -c "from app.main import app; from app.models import Base; ..."
app routes: 5
tables: 51
(51 table names printed)
```
Status: **PASS** — all 51 ORM tables construct and the FastAPI app imports.

## 3. Migrations (real Alembic run against PostgreSQL)

```
$ alembic revision --autogenerate -m "initial schema"
Generating .../alembic/versions/244f672fa5b3_initial_schema.py ... done

$ alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade  -> 244f672fa5b3, initial schema

$ alembic current
244f672fa5b3 (head)

$ psql -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"
52        # 51 domain tables + alembic_version
```
Status: **PASS**. Both dev and test databases migrated; test DB rebuild is performed by the test harness itself via `alembic upgrade head`.

## 4. Reference seed (dev database)

```
$ python -m app.seed
INFO:ssh.seed:Reference data seeded.

$ SELECT counts:
perms=84 | roles=7 | role_perms=180 | categories=10 | services=38 | villages=1 | users=0
```
Status: **PASS** — reference data only; **zero users/bookings/payments/reviews seeded**.

## 5. Automated test suite

```
$ cd backend && pytest
..............................                                           [100%]
30 passed, 1 warning in 5.31s
```

**30 passed, 0 failed.** One deprecation warning from Starlette's TestClient (harmless, upstream notice about `httpx`).

| File | Tests | Covers |
|---|---|---|
| `tests/test_health.py` | 3 | health+DB ping, OpenAPI availability, error envelope on unknown route |
| `tests/test_auth.py` | 22 | registration success and 4 phone formats; duplicate 409; weak password 422; invalid phone 422; Argon2id hash at rest; login phone/email; wrong password 401; account lockout 423 after 5 strikes; inactive user 403; SQL-injection identifier safe; `/me` auth required / garbage token rejected; refresh rotation; refresh reuse revokes family; logout single and all sessions; OTP honest 503; RBAC dependency (all-of, any-of, empty) |
| `tests/test_seed_reference.py` | 5 | no seeded users; exact role set; super-admin has all 84 permissions; customer excluded from admin/finance perms; 10 bilingual categories; ≥38 bilingual services; 50 required tables exist; partial unique index on active assignments enforced |

Test isolation: each test runs inside a transaction that is rolled back; the schema is rebuilt from the real migrations in a **disposable** database whose name must contain `test` (hard assertion in `conftest.py`).

## 6. Failures encountered during this session (and their resolution)

| # | Failure (real) | Root cause | Fix | Re-run |
|---|---|---|---|---|
| 1 | `sqlalchemy.exc.AmbiguousForeignKeysError` on `User.user_roles` | two FKs from `user_roles` to `users` (`user_id`, `granted_by_id`) | explicit `foreign_keys="UserRole.user_id"` | PASS |
| 2 | `KeyError: 'admin:attendance:manage'` while seeding | role map referenced an undeclared permission | added permission + fail-fast guard in `seed()` | PASS |
| 3 | 10 auth tests failed with 422 | `email-validator` rejects reserved TLD `.test` | tests use `example.com` | PASS |
| 4 | `pytest` reported `30 passed` only after fixes above | — | — | PASS |

## 7. Explicitly NOT tested / BLOCKED at this point

| Item | Status | Reason |
|---|---|---|
| Frontend (React PWA), responsive breakpoints, Telugu font rendering | **NOT RUN** | Frontend not built yet (Milestone 3+) |
| Playwright E2E journeys | **NOT RUN** | Requires the frontend |
| Payment gateway signature/webhook tests | **BLOCKED** | No merchant account or gateway credentials; gateway remains flagged off |
| SMS OTP / email delivery | **BLOCKED** | No approved SMS/SMTP provider configured; endpoints return explicit 503 |
| Docker Compose bring-up | **NOT RUN** | Compose stack written in Milestone 11 packaging |
| Windows-native run | **NOT RUN** | Sandbox is Linux; Windows steps documented, verification needs owner machine |
| Load / concurrency testing | **NOT RUN** | Deferred to Milestone 10 |
| Database backup/restore rehearsal | **NOT RUN** | Scripts written; rehearsal scheduled for Milestone 11 (will execute real dump/restore and record output) |

## 8. Honest summary

Milestones 1–2 are functionally complete for their scope: schema (51 tables), migrations, RBAC seed and authentication/authorisation are implemented and covered by 30 passing automated tests executed in this session. **The product is not production-ready**: frontend, booking engine, payments and admin modules are not built yet, and no external integration has been exercised.

---

# ADDENDUM — Milestone 2.1 correction verification (2026-11-17)

> This addendum supersedes the test counts in §5 of the report above (30 tests). The original
> text is retained as a historical record of what was executed at the time.

## A1. Commands actually executed (exit codes captured)

```
$ python3 -m pytest                              # project, post-fix
64 passed, 1 warning in 7.87s
FINAL_PYTEST_EXIT=0

$ python3 -m pytest  # /tmp/prefix_check with the four defects re-introduced
26 failed, 8 passed, 1 warning in 5.06s
PRE_FIX_EXIT=1
```

The pre-fix run is a real execution against a scratch copy of the backend with the original
defective code restored — it proves the new tests are genuine regression tests, not tautologies.

## A2. Regression coverage added (34 tests, `tests/test_review_regressions.py`)

| Finding | Tests | What is asserted |
|---|---|---|
| 1 — login attempt persistence | 5 | counter survives rollback after 3 attempts; lockout after 5; expiry allows login; audit rows for `auth.login_failed` ×5 and `auth.account_locked` persisted; dependency contract (explicit commit survives, uncommitted work rolls back) |
| 2 — refresh reuse revocation | 2 | all token rows have `revoked_at`; rotated token dead afterwards; `auth.refresh_reuse_detected` audited |
| 3 — production safety | 14 | 9 database-credential cases (uppercase/lowercase/mixed `change_me`, dev default, `postgres`, `Passw0rd`, short, missing), 4 JWT cases, strong config accepted, case-insensitive `ENV`, development unaffected, unparseable URL rejected |
| 4 — client IP trust | 13 | header ignored with no trusted proxy; ignored from untrusted peer; honoured from trusted proxy; left-most spoof ignored; all-hops-trusted fallback; malformed entries; bracketed IPv6; invalid CIDR entries; missing header; end-to-end audit-IP assertion |

## A3. Live HTTP verification (uvicorn + real PostgreSQL, not TestClient)

Run with `--no-proxy-headers`, fresh dev database migrated by Alembic and seeded.

```
health: {"status":"ok","service":"SATHUPALLY SERVICE HUB","database":"ok","env":"development"}

FIX 1  register_status=201
       wrong_attempt_1=401 wrong_attempt_2=401 wrong_attempt_3=401
       DB after 3 wrong attempts -> failed_login_count=3 locked=false
       wrong_attempt_4=401 wrong_attempt_5=401
       DB after 5 wrong attempts -> failed_login_count=0 locked=true
       correct_password_while_locked=423
       audit rows -> auth.account_locked=1 auth.login_failed=5 auth.register=1

FIX 2  refresh_once=200  rotated_token_issued=yes
       replay_old_token=401
       DB token rows -> total=3 revoked=3
       rotated_token_after_reuse=401
       audit -> auth.refresh_reuse_detected

FIX 4  login_with_spoofed_xff=200
       audit ip stored -> 127.0.0.1        (spoofed value was 6.6.6.6)
       server log warning -> 1 occurrence

FIX 3  uppercase CHANGE_ME: rejected
       lowercase change_me: rejected
       dev default:           rejected
```

## A4. Defect found *while* fixing finding 4

First live attempt (uvicorn with default proxy headers) recorded the spoofed `6.6.6.6` in the
audit trail even though `client_ip()` ignored the header. Cause: uvicorn's `--proxy-headers`
rewrites `request.client` from `X-Forwarded-For` for `forwarded-allow-ips` (default `127.0.0.1`)
before application code executes. Resolved by running with `--no-proxy-headers` (README, setup
script, ARCHITECTURE §6) and a warning middleware; re-verified → `127.0.0.1`.

## A5. Still not tested / remaining limitations (updated)

- `must_change_password` is still not enforced at login.
- Rate limiting remains per-process (single worker).
- No TOTP/MFA endpoints yet.
- OTP, email and payment gateway integrations remain unconfigured (honest 503 / disabled flags).
- Frontend, booking engine, payments, admin modules: not built.
- Docker Compose, backup/restore rehearsal, Windows-native run, Playwright E2E, load tests: not run.
- `TRUSTED_PROXIES` must be set correctly by the operator in production; a wrong value weakens
  IP-based controls (documented in ARCHITECTURE §6).

---

# ADDENDUM 2 — Milestone 2.2 verification (2026-11-17)

Supersedes the counts in Addendum 1 (64 tests). Everything below was executed in this session.

## B1. Commands and exit codes

```
$ bash scripts/run_tests.sh
126 passed, 1 warning in 15.79s
RUNNER_EXIT=0

$ pytest tests/<file>.py            # per-file breakdown
test_health.py             3 passed
test_auth.py              22 passed
test_seed_reference.py     5 passed
test_review_regressions.py 34 passed
test_testdb_guard.py      43 passed
test_concurrency_auth.py   5 passed
test_password_change.py   14 passed
```

## B2. Guard refusal proofs (real runs, not simulations)

```
C1 no opt-in                 -> REFUSING ... explicit destructive-test opt-in missing ...        EXIT=2
C2 opt-in, target dev DB     -> REFUSING ...
                                - database name 'sathupally' must END WITH '_test'
                                - test URL points at the same host/port/database as the
                                  configured application DATABASE_URL                       EXIT=2
C3 opt-in, name 'contest_db' -> REFUSING ... must END WITH '_test'                             EXIT=2
C4 opt-in, remote 10.20.30.40-> REFUSING ... host is not loopback                              EXIT=2
```

## B3. Test database is dedicated; development database untouched

```
dev users BEFORE suite: 0
dev users AFTER suite:  0      dev_tables=52   dev_services=38
test_users_after_suite=0       test_revision=244f672fa5b3   test_tables=52
```

## B4. Concurrency tests are genuine regressions

Scratch copy with the `with_for_update()` clauses removed:

```
TestConcurrentFailedLogins::test_no_lost_updates_on_failed_login_counter      FAILED
TestConcurrentFailedLogins::test_lockout_fires_exactly_once_under_concurrency FAILED
TestConcurrentRefresh::test_simultaneous_refresh_yields_exactly_one_success   FAILED
TestConcurrentRefresh::test_many_simultaneous_refreshes_revoke_family_once    FAILED
TestSerialisedRotationStillWorks::test_sequential_refresh_chain_is_healthy    PASSED
4 failed, 1 passed
NO_LOCK_EXIT=1
```

With locks restored: 5 passed, `FULL_SUITE_EXIT=0`.

Observed pre-fix symptom that drove the second-order fix:
`AssertionError: expected 8 serialised increments, got 1 — lost update under concurrency`.

## B5. must_change_password enforcement

14 tests cover: session cannot reach non-allowlisted endpoints (403 `password_change_required`);
`/auth/me` and logout still work; change clears the flag; previous sessions revoked; new password
works and old one fails; wrong current password rejected **and audited**; weak passwords rejected;
same-password reuse rejected; rehash is Argon2id; unauthenticated change rejected.

## B6. Items still NOT tested / limitations (see docs/KNOWN-LIMITATIONS.md)

- Rate limiting remains in-process (single worker) — L1.
- Proxy trust is an operator obligation — L2.
- Gateway/SMS/email unconfigured — L3.
- No TOTP/MFA endpoints, no account deletion, no OTP password reset — L4.
- Product surface (booking, payments, frontend, admin) not built — L5.
- Frontend/E2E/load/backup-rehearsal/Windows/Docker not tested — L6.
- Migration downgrade paths never exercised.

---

# ADDENDUM 3 — Milestone 2.3 lock-order verification (2026-11-17)

Supersedes the counts in Addendum 2 (126 tests). All output below is from this session.

## C1. Full suite — executed twice for stability

```
$ pytest                      # run 1
136 passed, 1 warning in 21.21s        EXIT_RUN1=0

$ pytest                      # run 2
136 passed, 1 warning in 25.77s        EXIT_RUN2=0

$ psql -d sathupally_test -c "SELECT count(*) FROM users;"
leftover_users=0
```

Per-file: health 3 · auth 22 · seed_reference 5 · review_regressions 34 · testdb_guard 43 ·
concurrency_auth 5 · password_change 14 · **lock_order 10**.

Test database is the dedicated disposable `sathupally_test`, rebuilt by `alembic upgrade head`
(revision `244f672fa5b3`), with the destructive-reset guard opted into via
`SSH_ALLOW_DESTRUCTIVE_TEST_DB_RESET=1`.

## C2. Lock-order tests (new file, 10 tests)

| Test | Purpose | Result |
|---|---|---|
| `test_inverted_lock_order_deadlocks_postgres` | Proves the old order is a real ABBA cycle: two live connections, barrier-forced interleaving, one transaction must fail with SQLSTATE 40P01 | PASS |
| `test_uniform_order_never_deadlocks` | Same interleaving with the enforced order serialises cleanly | PASS |
| `test_refresh_locks_user_before_token` | SQL captured via `before_cursor_execute`: first `FOR UPDATE` targets `users` | PASS |
| `test_refresh_reuse_path_locks_user_before_token` | Same assertion on the reuse-detection branch | PASS |
| `test_change_password_locks_user_before_tokens` | Same assertion for the change flow | PASS |
| `test_logout_locks_user_before_tokens` | Same assertion for logout | PASS |
| `test_simultaneous_reuse_and_password_change` | Real concurrent HTTP: no 5xx, no pre-race session survives | PASS |
| `test_simultaneous_reuse_with_two_different_tokens_same_user` | Two revoked tokens replayed concurrently → both 401 `refresh_token_reused`, family stays revoked | PASS |
| `test_refresh_and_password_change_race` | Valid refresh racing a change: no 5xx, all pre-race sessions revoked | PASS |
| `test_password_change_revokes_every_session_sequentially` | 3 sessions; after change exactly 1 active (the replacement); replaying an old token revokes the family | PASS |

### Discrimination check (honest scope of each test)

With the **original token-first order restored** in `/tmp/prefix_order` (each test run in isolation):

```
test_refresh_locks_user_before_token                -> 1 failed     (deterministic)
test_refresh_reuse_path_locks_user_before_token     -> 1 failed     (deterministic)
test_logout_locks_user_before_tokens                -> 1 failed     (deterministic)
test_refresh_and_password_change_race               -> 1 passed     (not a reliable discriminator)
test_password_change_revokes_every_session_sequentially -> 1 passed (not a lock-order discriminator)
```

**Disclosed limitation:** deadlock reproduction depends on exact timing, so the HTTP-level race
tests guard invariants (no 5xx, revocation persistence) but do not deterministically reproduce
ABBA. The deterministic discrimination comes from the three SQL-order assertions plus the hazard
proof. One pre-fix full-file run *did* fail `test_refresh_and_password_change_race`, confirming the
race can surface the defect intermittently.

## C3. Reviewer item coverage

| Item | Evidence |
|---|---|
| 1. One consistent lock order | `_lock_user_row` / `_lock_token_row`; all four paths asserted |
| 2. Refresh + reuse paths corrected | SQL-order tests on both branches |
| 3. Password-change/refresh cannot deadlock | Uniform order + race test + ABBA hazard proof |
| 4a. Reuse + password change concurrently | `test_simultaneous_reuse_and_password_change` |
| 4b. Reuse of two tokens, same user | `test_simultaneous_reuse_with_two_different_tokens_same_user` |
| 4c. Refresh racing password change | `test_refresh_and_password_change_race` |
| 5. Family revocation persists | `unrevoked`/pre-race-hash assertions after concurrent reuse |
| 6. Password change revokes all sessions | sequential test asserts exactly one active replacement, then family revocation on replay |
| 7. Dedicated disposable DB + real migrations | guard-opted `sathupally_test`, `alembic upgrade head` |
| 8. Real output/exit codes | this addendum |

## C4. Defects found during this round (all fixed)

1. Live-server test teardown matched no rows (10-digit vs `+91`), leaving committed users behind.
   Fixed by normalising in `cleanup_phones`; verified `leftover_users=0` after two full runs.
2. Race-test SQL assertions were vacuous for the same reason; tightened to E.164.
3. `SET deadlock_timeout` is superuser-only; removed, relying on the 1s default.
4. Two race assertions encoded a wrong invariant (a winning password change legitimately leaves
   its replacement session active); corrected.

## C5. Remaining limitations

Unchanged from Addendum 2 and `docs/KNOWN-LIMITATIONS.md`, plus L10 (below): deadlock freedom
depends on lock-order discipline that future code must preserve; the SQL-order tests guard the
current endpoints only.

---

# ADDENDUM 4 — Milestone 2.4 (R2.2) commit-ordering verification (2026-11-17)

Supersedes the counts in Addendum 3 (136 tests). Everything below was executed in this session.

## D1. Environment and identity

```
PostgreSQL 17.11 (Debian 17.11-0+deb13u1) on x86_64-pc-linux-gnu
fastapi 0.163.1 | starlette 1.10.0 | sqlalchemy 2.1.9 | Python 3.13.18 | pytest 9.0.3

database = sathupally_test   role = ssh_app   host = 127.0.0.1   port = 5432
tables = 52                  alembic = 244f672fa5b3 (head)   history: <base> -> 244f672fa5b3
```

Command for every run (destructive-reset guard explicitly opted in; target is the disposable
`*_test` database on loopback, verified by `tests/guards.py`):

```
cd backend && SSH_ALLOW_DESTRUCTIVE_TEST_DB_RESET=1 \
  TEST_DATABASE_URL=postgresql+psycopg://ssh_app:***@127.0.0.1:5432/sathupally_test \
  python3 -m pytest -o addopts="" -v
```

## D2. Eight consecutive full-suite runs

| Run | Result | Warnings | Exit code | Log |
|---|---|---|---|---|
| 1 | 143 passed in 49.71s | 1 | 0 | `verification_logs/m24/run1.log` |
| 2 | 143 passed in 47.40s | 1 | 0 | `run2.log` |
| 3 | 143 passed in 53.25s | 1 | 0 | `run3.log` |
| 4 | 143 passed in 48.32s | 1 | 0 | `run4.log` |
| 5 | 143 passed in 50.35s | 1 | 0 | `run5.log` |
| 6 | 143 passed in 54.16s | 1 | 0 | `run6.log` |
| 7 | 143 passed in 47.21s | 1 | 0 | `run7.log` |
| 8 | 143 passed in 47.84s | 1 | 0 | `run8.log` |

**Failures: 0. Exit codes: 0 for all eight runs.**

The single warning in every run is one upstream deprecation notice, unrelated to project code:

```
StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated;
install `httpx2` instead.   (fastapi/testclient.py:1)
```

Per-file composition of the 143 (run 8): auth 22 · **commit_ordering 7** · concurrency_auth 5 ·
health 3 · lock_order 10 · password_change 14 · review_regressions 34 · seed_reference 5 ·
testdb_guard 43.

### Statistical note

Before this fix the suite failed in 2 of 5 runs (40 %). Eight consecutive clean runs would occur by
chance with probability ≈ 0.6^8 ≈ 1.7 % if the defect were still present, so the flake is
resolved rather than hidden.

## D3. Read-after-write regression tests (new, 7)

Each scenario repeats 12× and asserts persisted state through an **independent `psycopg`
connection with autocommit**, opened immediately after the HTTP response — bypassing the
application's pool entirely so nothing is masked by session state.

| Test | Asserts |
|---|---|
| `test_user_row_visible_immediately_after_201` | registration row exists with zero delay |
| `test_registration_token_visible_immediately_after_201` | issued refresh token persisted before 201 |
| `test_login_token_visible_immediately_after_200` | token count is `before + 1` immediately after 200 |
| `test_rotation_visible_immediately_after_200` | old token revoked **and** new token inserted |
| `test_only_replacement_session_active_immediately_after_200` | exactly 1 active session after a password change (the pre-fix failure showed 4) |
| `test_change_password_then_immediate_login_token_is_revoked` | pre-change token refused on immediate replay |
| `test_logout_all_visible_immediately_after_200` | all sessions revoked before the 200 |

## D4. Discrimination check (pre-fix code)

Explicit commits removed from a scratch copy at `/tmp/prefix_commit` (R2.1 behaviour restored):

```
test_user_row_visible_immediately_after_201                    FAILED
test_registration_token_visible_immediately_after_201          FAILED
test_login_token_visible_immediately_after_200                 FAILED
test_rotation_visible_immediately_after_200                    FAILED
test_only_replacement_session_active_immediately_after_200     FAILED
test_change_password_then_immediate_login_token_is_revoked     PASSED
test_logout_all_visible_immediately_after_200                  FAILED

6 failed, 1 passed        PREFIX_EXIT=1
```

**Honest disclosure:** six of seven discriminate deterministically. The seventh is a secondary
behavioural guard that can pass pre-fix because the replay request itself creates enough delay for
the post-response commit to land; it is retained as defence in depth, not as the discriminator.

## D5. Framework-level proof of the mechanism

Standalone probe outside the project (`/tmp/probe_race.py`), FastAPI 0.163 + uvicorn, dependency
teardown delayed 3 ms to simulate a real COMMIT round-trip:

```
responses received BEFORE the commit finished: 20/20
```

This confirms the ordering hazard is structural, not an artefact of this application.

## D6. What was deliberately not changed

Lock ordering (`_lock_user_row` → `_lock_token_row`), reuse detection semantics, token rotation,
password policy, RBAC, destructive-test-DB guards, the single migration `244f672fa5b3`, and all
five previously delivered archives.

## D7. Remaining limitations

See `docs/KNOWN-LIMITATIONS.md` (L1–L11). New this round: **L11 — durability ordering**, which
records the rule that every mutating endpoint must commit before returning and that `get_db`'s
teardown commit is a safety net only.

Still open, unchanged: single-worker rate limiting (L1), proxy trust (L2), unconfigured
gateway/SMS/email (L3), no TOTP/MFA/account-deletion/OTP-reset (L4), product surface not built
(L5), frontend/E2E/load/backup-rehearsal/Windows/Docker untested (L6), lock-order discipline for
future endpoints (L10), migration downgrade never exercised.

---

# ADDENDUM 5 — Milestone 2.5 (R2.3) review-fix verification (2026-11-17)

Supersedes the counts in Addendum 4 (143 tests). All results below were produced in this session.

## E1. Environment and identity

```
PostgreSQL 17.11 (Debian 17.11-0+deb13u1), server_version_num 170011
fastapi 0.163.1 | starlette 1.10.0 | sqlalchemy 2.1.9 | Python 3.13.18 | pytest 9.0.3

test database : sathupally_test   role: ssh_app   host: 127.0.0.1   port: 5432
alembic       : 244f672fa5b3 (head);  history: <base> -> 244f672fa5b3 (head), initial schema
application database `sathupally` was never used or reset.
```

## E2. Migration verification on a clean disposable database

`verification_logs/m25/migration_clean_db.log`

```
1. current_database()            -> sathupally_test
2. DROP DATABASE / CREATE DATABASE sathupally_test
3. tables after recreate         -> 0
4. alembic upgrade head          -> Running upgrade  -> 244f672fa5b3, initial schema
                                   alembic_exit=0
5. alembic current               -> 244f672fa5b3 (head)
6. tables after migration        -> 52
   alembic_version               -> 244f672fa5b3
```

The schema is created by the real Alembic migration from an empty database — not by
`create_all()`.

## E3. Full suite, three consecutive runs

Command (identical each run):

```
cd backend && SSH_ALLOW_DESTRUCTIVE_TEST_DB_RESET=1 \
  TEST_DATABASE_URL=postgresql+psycopg://ssh_app:***@127.0.0.1:5432/sathupally_test \
  python3 -m pytest -o addopts="" -v
```

| Run | Result | Failures | Warnings | Exit code | Log |
|---|---|---|---|---|---|
| 1 | 152 passed in 51.90s | 0 | 1 | **0** | `verification_logs/m25/full_run1.log` |
| 2 | 152 passed in 50.63s | 0 | 1 | **0** | `full_run2.log` |
| 3 | 152 passed in 49.38s | 0 | 1 | **0** | `full_run3.log` |

Single warning, upstream and unrelated: `StarletteDeprecationWarning: Using httpx with
starlette.testclient is deprecated; install httpx2 instead.`

Composition of 152: auth 22 · commit_ordering 7 · concurrency_auth 5 · health 3 · lock_order 10 ·
password_change 14 · review_regressions 34 · **security_state_commit 9** · seed_reference 5 ·
testdb_guard 43.

## E4. Repeated targeted runs

| Suite | Repeats | Result each |
|---|---|---|
| `test_commit_ordering.py` | 5 | 7 passed (25.22s / 25.49s / 25.73s / 26.03s / 26.58s) |
| `test_concurrency_auth.py` + `test_lock_order.py` | 5 | 15 passed (9.55s / 14.88s / 9.66s / 9.43s / 9.63s) |
| `test_testdb_guard.py` | 3 | 43 passed (0.04s / 0.03s / 0.03s) |

## E5. New tests — security-state commit (9)

| Test | Asserts |
|---|---|
| `test_failed_login_counter_committed_before_401` (×6 iterations) | counter = 1 and `auth.login_failed` audit row exist the instant the 401 arrives |
| `test_account_lock_committed_before_locked_response` | `locked_until` persisted; locked account refuses a correct password |
| `test_refresh_reuse_revocation_committed_before_401` | 0 active sessions immediately after the reuse rejection |
| `test_failed_login_returns_503_not_401_when_commit_fails` | **503 `security_state_not_persisted`, never 401** |
| `test_commit_failure_rolls_back_security_state` | counter 0 and audit rows 0 after rollback; login works again afterwards |
| `test_refresh_reuse_returns_503_not_reuse_401_when_commit_fails` | no false "all sessions revoked" claim |
| `test_change_password_wrong_current_returns_503_when_commit_fails` | same rule on the third call site |
| `test_unexpected_commit_exception_does_not_leak_internals` | DSN embedded in a `RuntimeError` never reaches the client |
| `test_original_code_preserved_when_commit_succeeds` | over-correction guard: real 401 `invalid_credentials` still returned |

Leak assertions scan the response body for `psql`, `postgresql`, `password`, `INSERT`, `SELECT`,
`Traceback`, `sqlalchemy`, `psycopg`, memory addresses and `.py` filenames.

## E6. Discrimination check

R2.2 implementation restored in a scratch tree (`/tmp/prefix_secstate`):

```
9 tests: 5 failed, 4 passed
FAILED test_failed_login_returns_503_not_401_when_commit_fails
FAILED test_commit_failure_rolls_back_security_state
FAILED test_refresh_reuse_returns_503_not_reuse_401_when_commit_fails
FAILED test_change_password_wrong_current_returns_503_when_commit_fails
FAILED test_unexpected_commit_exception_does_not_leak_internals
```

All five failure-path tests discriminate deterministically. The four that also pass pre-fix are
the success-path guards, which is their purpose.

## E7. Documentation accuracy (review item 3)

Checked against the real tree: `frontend/` absent, `docs/INSTALL_LOCAL.md` absent, `docs/` holds
only ARCHITECTURE / CAPABILITY-REPORT / KNOWN-LIMITATIONS. False claims removed from `README.md`
and the stale PostgreSQL version corrected in `docs/CAPABILITY-REPORT.md` (see CHANGELOG M2.5).

## E8. Remaining limitations

See `docs/KNOWN-LIMITATIONS.md` L1–L13. New this round: **L12** (a security-state persistence
failure is reported as 503 and the client must retry — the rejection itself is never claimed) and
**L13** (documentation drift, corrected here; no automated check prevents a new false claim).

---

# ADDENDUM 6 — Milestone 2.6 (R2.4) guard-identity verification (2026-11-17)

Supersedes Addendum 5 (152 tests). Every number below was produced by a command actually run.

## F1. Environment

```
PostgreSQL 17.11 (Debian 17.11-0+deb13u1), server_version_num 170011
python 3.13.18 | fastapi 0.163.1 | starlette 1.10.0 | sqlalchemy 2.1.9 | pytest 9.0.3
test database: sathupally_test  role ssh_app  server_addr 127.0.0.1  server_port 5432  tables 52
alembic: 244f672fa5b3 (head);  history <base> -> 244f672fa5b3 (head), initial schema
```

Evidence file: `verification/logs/environment_identity.log`. The application database
`sathupally` was never used or reset.

## F2. Exact commands

```bash
# full suite (run 1 and 2)
cd backend && SSH_ALLOW_DESTRUCTIVE_TEST_DB_RESET=1 \
  TEST_DATABASE_URL=postgresql+psycopg://ssh_app:***@127.0.0.1:5432/sathupally_test \
  python3 -m pytest -o addopts="" -v

# new guard regressions, independently
python3 -m pytest tests/test_testdb_guard.py -o addopts="" -v

# new security-state regressions, independently
python3 -m pytest tests/test_security_state_commit.py -o addopts="" -v

# discrimination probe (same script, two source trees)
PYTHONPATH=<tree>/backend python3 verification/probe_guard_behaviour.py
```

## F3. Full suite results

| Run | Result | Failures | Warnings | Exit code | Log |
|---|---|---|---|---|---|
| 1 | 191 passed in 54.79s | 0 | 1 | **0** | `verification/logs/full_suite_run1.log` |
| 2 | 191 passed in 54.26s | 0 | 1 | **0** | `verification/logs/full_suite_run2.log` |

Warning (upstream, unrelated): `StarletteDeprecationWarning: Using httpx with
starlette.testclient is deprecated; install httpx2 instead.`

Composition of 191: auth 22 · commit_ordering 7 · concurrency_auth 5 · health 3 · lock_order 10 ·
password_change 14 · review_regressions 34 · security_state_commit 9 · seed_reference 5 ·
**testdb_guard 82** (was 43).

## F4. Independent and repeated runs

| Suite | Repeats | Result | Exit |
|---|---|---|---|
| `test_testdb_guard.py` | 1 + 3 | 82 passed (0.10s; 0.07s / 0.07s / 0.08s) | 0 |
| `test_security_state_commit.py` | 1 + 3 | 9 passed (9.05s; 8.71s / 8.39s / 8.87s) | 0 |
| `test_commit_ordering.py` | 3 | 7 passed (28.86s / 27.96s / 28.09s) | 0 |
| `test_concurrency_auth.py` + `test_lock_order.py` | 3 | 15 passed (10.37s / 14.96s / 10.35s) | 0 |

Log: `verification/logs/new_regression_tests.log`.

## F5. Guard defects — reproduced before the fix

Run against the R2.3 `guards.py` taken from the delivered archive:

```
DEFECT 1: test host 0.0.0.0                        -> ALLOWED
DEFECT 2: app localhost vs test 127.0.0.1 (same db) -> ALLOWED
          app localhost vs test [::1]       (same db) -> ALLOWED
          app 0.0.0.0   vs test 127.0.0.1   (same db) -> ALLOWED
CONTROL:  app 127.0.0.1 vs test 127.0.0.1           -> REFUSED   (check existed, was too literal)
```

## F6. Discrimination — 7-case behavioural probe

`verification/probe_guard_behaviour.py`

| Case | R2.3 (pre-fix) | R2.4 (fixed) |
|---|---|---|
| localhost vs 127.0.0.1 cannot bypass collision | FAIL (allowed) | PASS (refused) |
| localhost vs ::1 cannot bypass collision | FAIL (allowed) | PASS (refused) |
| 0.0.0.0 rejected as a test host | FAIL (allowed) | PASS (refused) |
| different port is allowed | PASS | PASS |
| different database name is allowed | PASS | PASS |
| valid test configuration still works | PASS | PASS |
| live reset blocked when identity uncertain | FAIL (arg unsupported) | PASS (refused) |

**3/7 pre-fix, 7/7 fixed.** The probe is committed so a reviewer can re-run it.

## F7. End-to-end block of a destructive reset

`verification/logs/guard_blocks_destructive_reset.log`

```
DATABASE_URL  = ...@localhost:5432/sathupally_test
TEST_DATABASE_URL = ...@127.0.0.1:5432/sathupally_test      (same database, different alias)
tables BEFORE : 52
pytest        : _pytest.outcomes.Exit — REFUSING DESTRUCTIVE TEST DATABASE RESET
                "... app host 'localhost' and test host '127.0.0.1' are the same server
                 identity 'loopback'."
PYTEST_EXIT   : 2
tables AFTER  : 52      (no DROP executed)
```

## F8. Review item 1 — verification only

`_commit_security_state()` was corrected in Milestone 2.5; this round it was checked against the
new specification point by point (commit → original error; failure → rollback, server-side log,
sanitized 503, never the original 401) and no change was required. All five mandatory failure-path
tests pass and 5/5 fail deterministically against the pre-fix implementation (Addendum 5, §E6).

## F9. Documentation

`README.md` no longer presents `frontend/` or `docs/INSTALL_LOCAL.md` as existing — corrected in
Milestone 2.5 and re-checked here. `docs/CAPABILITY-REPORT.md` reports PostgreSQL 17.11.

## F10. Remaining limitations

See `docs/KNOWN-LIMITATIONS.md` L1–L14. New: **L14** — host identity is normalised
*syntactically*; DNS names that resolve to loopback are not resolved and still compare as a
distinct server. The live check narrows this (it compares the address the server reports) but does
not eliminate it. Use literal loopback addresses for the test database.

---

# ADDENDUM 7 — Milestone 2.7 (R2.5) fail-closed guard verification (2026-11-17)

Supersedes Addendum 6 (191 tests). Every result below was produced by a command actually run in
this session.

## G1. Environment

```
PostgreSQL 17.11 (Debian 17.11-0+deb13u1)  server_version_num 170011
python 3.13.18 | fastapi 0.163.1 | sqlalchemy 2.1.9 | pytest 9.0.3
test database: sathupally_test  role ssh_app  127.0.0.1:5432  tables 52
alembic: 244f672fa5b3 (head)
application database `sathupally` was never used or reset in any scenario below.
```

## G2. Defect — collision check failed open

The identity layer was wrapped in `if candidate_app_url:` with `except Exception: app = None`.
A missing or malformed application URL therefore skipped the collision check silently.

Probe against the R2.4 `guards.py` taken from the delivered archive:

```
[FAIL] 8. missing application DATABASE_URL refuses the reset         -> allowed (expected refused)
[FAIL] 9. unparseable application DATABASE_URL refuses the reset     -> allowed (expected refused)
[FAIL] 10. application URL with no database name refuses the reset   -> allowed (expected refused)
```

## G3. Fix — fail closed, with the correct diagnostic

`_application_database_identity()` now refuses on: missing URL, unparseable URL, non-PostgreSQL
URL, or a URL that names no database. Used by **both** `assert_disposable_test_database()` and
`verify_connected_database()`.

## G4. End-to-end evidence on a real pytest run

`verification/logs/fail_closed_end_to_end.log`

| Scenario | pytest result | Exit | Tables before → after |
|---|---|---|---|
| A. no application `DATABASE_URL` (env unset, `.env` moved aside) | "the application database is NOT configured … refusing to destroy anything" | **2** | 52 → 52 |
| B. `DATABASE_URL="this is not a database url"` | "cannot be parsed, so its database identity is unknown" | **2** | 52 → 52 |
| C. `DATABASE_URL=…:5432/` (no database name) | "does not name a database" | **2** | 52 → 52 |

No `DROP` was executed in any scenario. Scenario A initially refused for the wrong reason (a
"self collision", because `conftest` overwrites `DATABASE_URL` with the test URL before the guard
runs); `conftest` now passes `""` so the accurate message is produced. This was a real defect in
the diagnostic, not just wording — a false "self collision" would send an operator looking in the
wrong place.

## G5. DNS alias identity — implemented

`_same_server()` resolves both hosts with `socket.getaddrinfo` when they differ syntactically, and
treats a shared address as the same server. Unresolvable names are treated as **same** (fail
closed). Resolution is skipped when the hosts are already equal after normalisation, so the common
case (`127.0.0.1` vs `127.0.0.1`) performs no lookup.

Tests (`TestDnsAliasIdentity`, 4): name resolving to loopback collides; name resolving to a
different host is allowed; unresolvable name fails closed; Unix-socket application DB collides with
a name resolving to loopback.

## G6. Discrimination — 10-case probe

`verification/probe_guard_behaviour.py`, same script, two source trees:

| # | Case | R2.4 | R2.5 |
|---|---|---|---|
| 1 | localhost vs 127.0.0.1 collision | PASS | PASS |
| 2 | localhost vs ::1 collision | PASS | PASS |
| 3 | 0.0.0.0 rejected | PASS | PASS |
| 4 | different port allowed | PASS | PASS |
| 5 | different database allowed | PASS | PASS |
| 6 | valid configuration works | PASS | PASS |
| 7 | live reset blocked when identity uncertain | PASS | PASS |
| 8 | missing application URL refused | **FAIL** | PASS |
| 9 | unparseable application URL refused | **FAIL** | PASS |
| 10 | application URL with no database refused | **FAIL** | PASS |

**7/10 pre-fix → 10/10 fixed.**

## G7. Full suite

```
cd backend && SSH_ALLOW_DESTRUCTIVE_TEST_DB_RESET=1 \
  TEST_DATABASE_URL=postgresql+psycopg://ssh_app:***@127.0.0.1:5432/sathupally_test \
  python3 -m pytest -o addopts="" -v
```

| Run | Result | Failures | Warnings | Exit code | Log |
|---|---|---|---|---|---|
| 1 | 211 passed in 45.41s | 0 | 1 | **0** | `verification/logs/full_suite_run1.log` |
| 2 | 211 passed in 45.36s | 0 | 1 | **0** | `verification/logs/full_suite_run2.log` |

Only warning: `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated`
(upstream, unrelated).

Composition of 211: auth 22 · commit_ordering 7 · concurrency_auth 5 · health 3 · lock_order 10 ·
password_change 14 · review_regressions 34 · security_state_commit 9 · seed_reference 5 ·
**testdb_guard 102** (was 82).

Guard tests independently: **102 passed, exit 0**, three consecutive runs (0.08 s each).

## G8. Known limitation correction (L14)

L14 previously implied the live check reliably caught DNS aliases. It did not — identity was
syntactic. L14 has been rewritten to state exactly what is resolved, what the fail-closed rules
are, and the four residual gaps (TOCTOU, NAT/proxy-reported addresses, DNS-unavailable availability
trade-off, and that this is not a security boundary).

## G9. Operational consequence

Running the suite now requires an application `DATABASE_URL` (environment variable or
`backend/.env`) in addition to `TEST_DATABASE_URL`. Without one the run aborts with exit code 2 and
an explanatory message. This is the intended cost of failing closed and is noted in `README.md`.

---

# ADDENDUM 8 — Milestone 2.8 (R2.6) release-evidence correction (2026-11-17)

R2.6 changes **no application code**. It corrects verification evidence and closes two GitHub
omissions found during independent verification of R2.5.

## H1. Environment (re-captured this session)

```
PostgreSQL 17.11 (Debian 17.11-0+deb13u1)   server_version_num 170011
python 3.13.18 | fastapi 0.163.1 | starlette 1.10.0 | sqlalchemy 2.1.9 | pytest 9.0.3
test database: sathupally_test  role ssh_app  127.0.0.1:5432  52 tables
alembic: 244f672fa5b3 (head)   history: <base> -> 244f672fa5b3 (head), initial schema
baseline source commit: 7876ef8d84fbdb82487e922b60d9dcfdb36ab0aa (working tree clean)
```

Source fingerprints recorded in `verification/logs/environment_identity.log`:

```
guards.py            sha256 65c25f9db0af83d53642a1b7ceee454a896e6561d408535940842f2f5e3613db
test_testdb_guard.py sha256 cf0a66b58f9e0b85bf09204afadc3a1f9a93feaf1316c3ea2ac80186c76469a3
auth.py              sha256 573098d0085eb02f72073780561e8c1889208d4a9c367ca6b6c9d6d45762bce0
```

## H2. Commands executed

```bash
# 1. regenerate the stale log (Task 1)
cd backend
python3 -m pytest tests/test_testdb_guard.py -o addopts="" -v            # 102 passed, exit 0
python3 -m pytest tests/test_security_state_commit.py -o addopts="" -v   #   9 passed, exit 0

# 2. re-execute the two end-to-end guard proofs
#    (alias collision; and missing / unparseable / database-less app URL)

# 3. full suite, twice (Task 4)
cd backend && SSH_ALLOW_DESTRUCTIVE_TEST_DB_RESET=1 \
  TEST_DATABASE_URL=postgresql+psycopg://ssh_app:***@127.0.0.1:5432/sathupally_test \
  python3 -m pytest -o addopts="" -v -rs
```

## H3. Full-suite results

| Run | Result | Passed | Failed | Skipped | Errors | Exit | Log |
|---|---|---|---|---|---|---|---|
| 1 | 211 passed, 1 warning in 53.65s | 211 | 0 | 0 | 0 | **0** | `verification/logs/full_suite_run1.log` |
| 2 | 211 passed, 1 warning in 55.62s | 211 | 0 | 0 | 0 | **0** | `verification/logs/full_suite_run2.log` |

Only warning, upstream and unrelated: `StarletteDeprecationWarning: Using httpx with
starlette.testclient is deprecated; install httpx2 instead.`

## H4. Evidence-log corrections (Task 1)

| Log | Was | Now | How |
|---|---|---|---|
| `new_regression_tests.log` | R2.4, 82 guard tests | R2.6, 102 guard + 9 security = 0 exit | real run |
| `environment_identity.log` | R2.4 header | R2.6 capture | real capture |
| `guard_blocks_destructive_reset.log` | R2.4 timestamp | R2.6 | real re-execution |
| `fail_closed_end_to_end.log` | R2.5 | R2.6 | real re-execution |
| `full_suite_run1/2.log` | R2.5 | R2.6 | real re-run |

## H5. GitHub dotfile omission (Task 2)

`.gitignore` and `backend/.env.example` were absent from `edb7077b` because the commit was made
through GitHub's web uploader, which skips dot-prefixed paths. Both are now staged with
`git add -f`.

Verified on a fresh clone of the R2.6 commit:

```
.gitignore                   present
backend/.env.example         present (1681 bytes)
cp .env.example .env      -> backend/.env created (1681 bytes)
git check-ignore          -> .gitignore:2:backend/.env   (secret correctly excluded)
git status backend/.env   -> not staged — correct
```

The README Windows instruction `copy backend\.env.example backend\.env` therefore works.

## H6. Source stability (Task 3)

`git diff --stat` of the R2.6 commit touches **8 paths**: the 2 dotfiles and 6 log files.
No `.py`, `.sh`, `.ini`, `.mako` or migration file is modified. Application logic, authentication,
security guards and database behaviour are unchanged from R2.5.

## H7. Remaining limitations

Unchanged from R2.5: L1–L14. See `docs/KNOWN-LIMITATIONS.md`.
