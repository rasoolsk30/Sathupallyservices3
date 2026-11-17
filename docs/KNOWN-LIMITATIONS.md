# Known Limitations

**Project:** SATHUPALLY SERVICE HUB · **Updated:** 2026-11-17 · **Status:** pre-Milestone 3

This is the living limitations register (master prompt artifact #18, maintained from Milestone 2
onward). Every entry states the limitation, its impact, and what would remove it. Nothing here is
hidden by the codebase or by the test suite.

---

## L1 — Rate limiting is per-process (single worker only) ⚠ operational

**Limitation.** `app/core/ratelimit.py` stores counters in process memory.
**Impact.** With more than one uvicorn worker, each worker keeps its own counters, so the
effective login/registration limits multiply by the worker count. Counters also reset on restart.
**Mitigations in place.** Production boot logs an explicit warning; `README.md`,
`docs/ARCHITECTURE.md` §6.1 and this file document the constraint.
**Removed by.** A Redis-backed (or database-backed) shared limiter, added before any multi-worker
or multi-instance deployment.

## L2 — Reverse-proxy trust is operator-configured

**Limitation.** `X-Forwarded-For` is honoured only for peers listed in `TRUSTED_PROXIES`, which
defaults to empty (header ignored). uvicorn must run with `--no-proxy-headers`.
**Impact.** If the operator sets `TRUSTED_PROXIES` incorrectly, IP-based controls (rate limiting,
audit attribution) degrade. If uvicorn is started with proxy headers enabled, the ASGI server may
rewrite `request.client` before the app's own decision.
**Mitigations.** Startup guidance, a runtime warning when the header arrives untrusted, and
13 regression tests covering spoofing.
**Removed by.** Nothing purely in code — this is a deployment-correctness item; container entrypoints
in Milestone 11 will pin the flag.

## L3 — External integrations are not connected

| Integration | State | Effect |
|---|---|---|
| Payment gateway | Disabled (`PAYMENT_GATEWAY` unset) | Only cash / direct-UPI / admin-recorded flows are usable; online checkout returns a clear error |
| SMS / OTP | Disabled (`OTP_ENABLED=false`) | `POST /auth/verify-otp` returns HTTP 503 `otp_not_configured` — never a fake success |
| Email | Disabled (`SMTP_*` unset) | In-app notifications only; no email delivery is claimed |
| WhatsApp | Click-to-chat links only | No WhatsApp Business API integration |

**Removed by.** Owner-provided credentials and approved providers (Indian SMS/PAYMENT merchant
account). Code paths for gateway signature verification exist but have not been exercised against a
live gateway.

## L4 — Authentication features not yet built

- No TOTP/MFA enrolment or verification endpoints (schema columns exist, `ADMIN_MFA_REQUIRED` is inert).
- No account-deletion / data-retention workflow (required before public launch per §13).
- No password-reset-by-OTP flow (depends on L3).
- `must_change_password` **is** enforced (allowlisted endpoints only) and cleared by
  `POST /auth/change-password` — removed from this list after the M2.2 review.

## L5 — Product surface not built yet

Customer/provider/employee/admin applications, the booking state machine, quotations, payments,
financial ledger, settlements, refunds, complaints, reviews, notifications, maps and reports are
**not implemented**. Milestones 3–10 of the master prompt cover them. The API currently exposes
authentication only.

## L6 — Testing gaps

| Not yet tested | Reason |
|---|---|
| Frontend, responsive breakpoints, Telugu font rendering | Frontend not built |
| Playwright end-to-end journeys | Requires the frontend |
| Payment gateway signature/webhook replay against a real provider | No merchant account |
| Backup → restore rehearsal | Scheduled for Milestone 11 (scripts exist, never executed against a real dump) |
| Load / soak testing | Deferred to Milestone 10 |
| Windows-native installation | Documented, but only Linux has been exercised |
| Docker Compose bring-up | Not written yet |

## L7 — Test-database safety is enforced, with documented operator obligations

The harness refuses to destroy a database unless **all** of these hold: explicit
`SSH_ALLOW_DESTRUCTIVE_TEST_DB_RESET=1` opt-in, PostgreSQL backend, database name **ending** in
`_test`, loopback host (unless `SSH_ALLOW_REMOTE_TEST_DB=1`), not the configured application
database, live `current_database()` re-check, and no `platform_production_marker` table.
**Residual risk.** An operator who sets both opt-in flags and points at a remote `*_test` database
has explicitly overridden the remaining protections; that is deliberate and logged in the run output.

## L8 — Data and legal items requiring the owner

- Village list: only the mandal headquarters is seeded; the remaining mandal villages must be
  confirmed against official records.
- Service pricing: reference rows are `QUOTE_ONLY` at ₹0 — real prices must be configured before
  any booking can be priced.
- Terms, Privacy and About pages are drafts and require qualified legal review.
- GST/tax treatment, employment classification and any local licensing require accountant/legal input.

## L9 — Schema and migration notes

- A single migration (`244f672fa5b3_initial_schema`) applies the whole schema; downgrade paths have
  never been exercised.
- Financial columns use integer paise; no floating point is used anywhere in money paths, but no
  property-based tests exist yet for rounding at the edges (no rounding is performed — amounts are
  integers throughout).

## L10 — Deadlock freedom depends on lock-order discipline ⚠ design invariant

**Limitation.** PostgreSQL serialises concurrent authentication work with row locks on two classes
of row: `users` and `auth_refresh_tokens`. Deadlock freedom is not automatic — it depends on every
code path acquiring them in the same order.

**Enforced invariant.** Any transaction that touches both classes takes the **user row first** and
**refresh-token rows second**. This is implemented by `_lock_user_row()` and `_lock_token_row()` in
`app/api/v1/auth.py`, which are the only lock helpers; `logout` takes the user lock even though it
only mutates token rows.

**How it is guarded.** `backend/tests/test_lock_order.py` captures the SQL each endpoint emits and
asserts the first `FOR UPDATE` targets `users`. A companion test proves that the inverted order
genuinely produces SQLSTATE 40P01 on PostgreSQL, so the ordering is not theoretical.

**Residual risk.** A future endpoint (for example an admin "revoke all sessions for user" action)
that locks token rows before the user row would reintroduce ABBA. Such code must use the helpers,
and reviewers should treat any new `with_for_update()` on token rows without a preceding user lock
as a defect. Deadlock errors are never caught or suppressed; they surface as HTTP 500.

**Not affected by this invariant.** Single-class operations (for example an update touching only
`bookings`) cannot form a cycle with the authentication locks.

## L11 — Durability ordering: mutating endpoints must commit before returning ⚠ design rule

**Defect that produced this entry (fixed in Milestone 2.4).** Endpoints relied on the `get_db`
yield dependency to commit. FastAPI runs a yield dependency's exit code *after* the response is
flushed to the ASGI server, so a client could receive `200 OK` while the transaction was still
open. Measured: 20/20 probe responses and 25/25 login responses arrived before the commit.

**Why it mattered.** `POST /auth/change-password` revokes every session, but a login whose INSERT
committed only after the response escaped that revocation — the UPDATE could not see an
uncommitted row. Callers could also read stale state from another connection immediately after a
success response.

**Rule now enforced.** Every mutating endpoint calls `commit_or_raise(db)` on the request session
*before* returning. `get_db`'s teardown commit remains only as a safety net; it is documented as
unable to guarantee read-after-write visibility and must never be relied upon.

**How it is guarded.** `backend/tests/test_commit_ordering.py` repeats each scenario 12× and reads
persisted state from an independent `psycopg` autocommit connection immediately after the HTTP
response. Six of the seven tests fail deterministically against the pre-fix code.

**Residual risk.** A future endpoint that writes and returns without calling `commit_or_raise`
reintroduces the window. Reviewers should treat any mutating handler that lacks the call as a
defect. There is no automated lint for this yet; the test suite only covers the endpoints that
currently exist.

## L12 — Security-state persistence failure is surfaced as 503, not as the rejection ⚠ operational rule

**Defect that produced this entry (fixed in Milestone 2.5).** `_commit_security_state()` caught a
commit failure, logged it, and still raised the intended authentication error. A client could
therefore be told "invalid credentials" while the failed-login counter, the account lock and the
audit row had all been discarded — allowing unlimited unrecorded password guessing.

**Behaviour now.** If that commit fails, the endpoint rolls back and returns
`503 security_state_not_persisted` with a fixed message containing no SQL, driver detail,
credentials or stack trace. The original 401/401-reuse rejection is returned **only** when the
security state was durably committed.

**Client-facing consequence.** Clients must treat `503 security_state_not_persisted` as a
retryable condition, not as "wrong password". A frontend must not render it as an authentication
failure.

**Residual risk.** Retries after a failed security-state commit may double-count an attempt in
the audit log once the database recovers; attempts are not idempotency-keyed.

## L13 — Documentation drift has no automated guard

`README.md` previously described a `frontend/` directory and a `docs/INSTALL_LOCAL.md` that did
not exist. Both claims were removed in Milestone 2.5 and the tree was corrected against reality.
There is still **no automated check** that documentation matches the repository; reviewers must
verify claims manually. Installation instructions beyond the two quick-start blocks do not exist
until Milestone 11.

## L14 — Guard host identity: what is resolved, and what is still not guaranteed

**Corrected in Milestone 2.7.** An earlier revision of this entry claimed the live check
"narrowed" the DNS-alias gap. That claim was too generous for the code as written: host identity
was compared **syntactically only**, and two hostnames pointing at the same server were treated as
different servers. The guard now resolves names, and this entry states precisely what that does and
does not establish.

### What the guard now does

| Situation | Behaviour |
|---|---|
| Both hosts are literal IPs / loopback aliases | Compared after normalisation (`localhost`, `127.0.0.0/8`, `::1`, Unix socket → one identity). No DNS |
| Hosts differ syntactically and a collision is therefore possible | Both names are resolved with `socket.getaddrinfo`; a shared address means "same server" and the reset is refused |
| Resolution fails or returns nothing | Treated as **same server** → reset refused (fail closed) |
| Wildcard bind address (`0.0.0.0`, `::`) | Never accepted as a destination; treated as colliding |
| Application `DATABASE_URL` missing / unparseable / non-PostgreSQL / no database name | Reset refused (Milestone 2.7; previously the collision check was silently skipped) |

### What is still not guaranteed

1. **TOCTOU.** Resolution happens at guard time; DNS could change before the connection is made.
   The live check (`verify_connected_database`) re-reads the address the server itself reports and
   is the backstop, but the two checks are not atomic.
2. **Addresses the server reports may differ from the address the client used** — NAT, port
   forwarding, proxies or a Unix socket (`inet_server_addr()` is NULL, which is treated as
   loopback, i.e. fail closed). If names *and* reported addresses differ, the guard concludes
   "different server"; that conclusion is only as good as the reported address.
3. **Availability trade-off.** If DNS is unavailable in the environment, a same-named test database
   is refused even when it would have been safe. This is deliberate: refusing is recoverable,
   dropping the wrong schema is not.
4. **Not a security boundary.** The guard protects against operator misconfiguration, not against
   an attacker who controls the environment (they could simply run `DROP SCHEMA` themselves).

**Guidance.** Configure the test database with a literal loopback address (`127.0.0.1`) and keep
the application `DATABASE_URL` explicit. Do not rely on hostname resolution as a safety layer.
