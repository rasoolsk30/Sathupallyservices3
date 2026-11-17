# SATHUPALLY SERVICE HUB — System Architecture

**Tagline:** Your Local Services. One Trusted Platform.
**Market:** Sathupally Mandal, Telangana · Telugu + English · INR

---

## 1. System overview

A modular monolith:

```
┌────────────────────────────────────────────────────────────────┐
│  Frontend (React + TypeScript + Vite, PWA)                     │
│  One codebase, four role experiences:                          │
│   /app/customer   /app/provider   /app/employee   /admin       │
└───────────────▲────────────────────────────────────────────────┘
                │ REST /api/v1 (JSON, JWT bearer)
┌───────────────┴────────────────────────────────────────────────┐
│  Backend (FastAPI, Python 3.12+)                               │
│  api/v1 routers → services (business rules) → SQLAlchemy       │
│  core: auth, RBAC, audit, rate-limit, errors, settings         │
└───────────────▲────────────────────────────────────────────────┘
                │ psycopg3
┌───────────────┴────────────────────────────────────────────────┐
│  PostgreSQL 16+ (all money in integer paise, UTC timestamps)   │
└────────────────────────────────────────────────────────────────┘
        │                                   │
  Object storage (local disk / S3-compatible)   Notification adapters
  private: KYC docs, job evidence        (in-app real; email/SMS/WhatsApp
                                          disabled until configured)
```

Why a modular monolith: single business owner, low traffic at pilot scale, zero-cost-first.
Module boundaries (`api → services → models`) keep seams clean so matching, payments or
notifications can be extracted to separate services later without rewriting the product.

## 2. Backend module map

| Package | Responsibility |
|---|---|
| `app/core` | settings, DB session, security (Argon2id, JWT), RBAC dependencies, error envelope, rate limiting, audit writer |
| `app/models` | SQLAlchemy 2.x ORM for every table in §9 of the master prompt |
| `app/schemas` | Pydantic request/response models — never ORM objects directly |
| `app/api/v1` | REST routers, one file per domain |
| `app/services` | Booking state machine, provider matching, pricing & commission, ledger, settlements, refunds, notifications, document storage |
| `app/seed.py` | Non-production reference data only (roles, permissions, categories, services, villages flagged provisional) |
| `scripts/create_admin.py` | Creates the first Super Admin from environment variables (no demo users shipped) |

## 2.1 Persistence ordering (durability before response)

FastAPI runs a `yield` dependency's exit code **after** the response is handed to the ASGI server,
so a commit performed in `get_db`'s teardown races the client. Measured on this stack: 20/20
responses arrived before the commit finished.

Therefore **every mutating endpoint commits explicitly** via `commit_or_raise(db)` before returning
its success response. `get_db`'s own commit exists only as a safety net and must never be relied
upon for read-after-write visibility. Regression cover: `backend/tests/test_commit_ordering.py`
repeats each scenario 12× and verifies persisted rows from an independent connection.

## 2.2 Failing closed on security-state persistence

Endpoints that persist security state while rejecting a request (failed-login counters, lockouts,
token-family revocations, audit rows) commit **before** raising. If that commit fails, the intended
rejection is replaced by `503 security_state_not_persisted` — reporting the rejection would assert
that state was recorded when it was not. The replacement error carries no SQL, credentials or stack
trace; the cause is logged server-side only.

## 2.3 Destructive-test-DB guard fails closed

`backend/tests/guards.py` decides whether the suite may drop and recreate a schema. If the
application `DATABASE_URL` is missing, unparseable, non-PostgreSQL or names no database, the reset
is **refused** — an unknown application identity can never authorise a destructive operation.
Host identity is compared after normalisation (`localhost` / `127.0.0.0/8` / `::1` / Unix socket
are one identity) and, when two hosts differ syntactically, after DNS resolution; inconclusive
resolution counts as the same server. See `docs/KNOWN-LIMITATIONS.md` L14 for the residual gaps.

## 3. Money & time

- **Money:** integer **paise** (`BIGINT`) everywhere. Display layer formats ₹. No floats in any financial path.
- **Commission:** basis points (`rate_bps`), default 1000 = 10 %. Computed only on eligible service charges, excluding taxes and pass-through materials per contract.
- **Time:** stored UTC (`TIMESTAMPTZ`), rendered Asia/Kolkata. Business dates (attendance, ledger entry date) are plain `DATE` in IST.

## 4. Booking state machine (§8)

Valid transitions are declared in one table in `app/services/booking_state.py` and enforced
inside a DB transaction with `SELECT … FOR UPDATE` on the booking row. Every transition writes
`booking_status_history` (actor, from, to, reason, timestamp).

```
REQUESTED → PROVIDER_MATCHING → PROVIDER_ASSIGNED → ACCEPTED
ACCEPTED → (QUOTE_SUBMITTED → QUOTE_APPROVED)? → CONFIRMED
CONFIRMED → WORK_STARTED → WORK_PAUSED? → ADDITIONAL_QUOTE_REQUIRED? → WORK_STARTED
WORK_STARTED → COMPLETED_PENDING_CONFIRMATION → COMPLETED → PAYMENT_PENDING
PAYMENT_PENDING → PAYMENT_CONFIRMED → CLOSED
Terminal alternatives: REJECTED, CANCELLED, EXPIRED, DISPUTED, REFUND_PENDING, REFUNDED
```

Instant bookings skip quotation states **only** when a provider has actually accepted; the UI never
promises immediate service before acceptance. Additional work requires a new approved quotation.

## 5. Financial engine (§11)

Double-entry-compatible ledger (`financial_ledger`). Every money event posts balanced entries.

Accounts: `CUSTOMER_RECEIVABLE`, `CASH_IN_HAND`, `UPI_CLEARING`, `GATEWAY_CLEARING`,
`PLATFORM_COMMISSION_REVENUE`, `COMPANY_SERVICE_REVENUE`, `PROVIDER_PAYABLE`,
`EMPLOYEE_COMPENSATION_EXPENSE`, `MATERIAL_EXPENSE`, `TRAVEL_EXPENSE`,
`TAX_PAYABLE`, `REFUND_PAYABLE`.

Independent-provider job (₹1,000, 10 %):
- Debit CASH/UPI/GATEWAY clearing 1000 · Credit COMPANY/PROVIDER split:
  Credit PROVIDER_PAYABLE 900 · Credit PLATFORM_COMMISSION_REVENUE 100.

Company-employee job (₹1,000, materials 200, employee 300, travel 50, other 50):
- Customer collection debits clearing 1000; credits COMPANY_SERVICE_REVENUE 1000.
- Expense side debits MATERIAL 200, EMPLOYEE_COMP 300, TRAVEL 50 → contribution 400
  is an **analytics figure**, not a ledger balancing item.

Commission is finalized only when a booking reaches `COMPLETED`; settlements aggregate
finalized commissions into `provider_settlements` (DRAFT → APPROVED → PAID) with item-level traceability.
Refunds always create `refunds` + compensating ledger entries and adjust the provider payable.

## 6. Security model (§13)

- Argon2id password hashing; password policy enforced server-side.
- Short-lived access JWT (default 30 min) + rotating refresh token stored **hashed** in
  `auth_refresh_tokens` with revocation on logout and reuse detection.
- RBAC: `roles` ↔ `permissions` seeded; endpoints declare `require_permissions("…")`.
  Backend is the only authority — hiding a button is never access control.
- Login abuse: per-IP + per-account rate limits, failed-attempt counter, temporary lockout.
- File uploads: extension + MIME allow-list, size cap, stored outside web root under a random key,
  served only through an authorised download endpoint (signed URLs when object storage supports it).
- Payments: server-side order creation, signature verification, idempotency keys, webhook
  replay protection via unique `(provider, event_id)`, no browser-trusted success.
- Client IP / proxies: `X-Forwarded-For` is **ignored entirely** unless the socket peer is listed in
  `TRUSTED_PROXIES` (IPs/CIDRs). When trusted, hops are scanned right-to-left and the first
  non-proxy address wins, so client-supplied left-most entries can never dictate the recorded IP.
  Run uvicorn with `--no-proxy-headers` so the ASGI server does not rewrite `request.client`
  from the header before the app applies its own trust decision. A middleware logs a security
  warning when the header arrives with no trusted proxy configured.
- **Lock ordering (deadlock freedom):** concurrent authentication work locks the `users` row
  **first** and `auth_refresh_tokens` rows **second**, in every path (refresh, reuse detection,
  password change, logout). A previous revision inverted this in `refresh` and could deadlock
  against `change-password` (PostgreSQL SQLSTATE 40P01). Deadlocks are never caught or suppressed;
  the uniform order prevents them. Any future code that locks token rows must take the user lock
  first — `backend/tests/test_lock_order.py` asserts the emitted SQL order.
- Audit: every admin mutation and sensitive action writes `audit_logs` (immutable; no delete API).
- CSRF: JWT in `Authorization` header (not ambient cookies) for the SPA → CSRF surface removed;
  document it in the security checklist.

## 6.1 Known limitation — rate limiting is per-process (explicit)

The limiter in `app/core/ratelimit.py` keeps counters in process memory. Consequences:

- It is correct **only with a single uvicorn worker**. With N workers each keeps its own
  counters, so the effective limit becomes roughly N × the configured value.
- Counters reset on deploy/restart.
- Multi-worker deployments MUST move the limiter to a shared store (Redis) before scaling out.

The application logs a warning at startup when `ENV=production`, and the constraint is repeated in
`docs/KNOWN-LIMITATIONS.md` and `README.md`. No automated test can catch a misconfigured worker
count, so this is an operational control, not a code control.

## 7. API conventions

- Base path `/api/v1`; JSON only; UTC ISO-8601 timestamps.
- Auth: `Authorization: Bearer <access>`; refresh via `POST /auth/refresh`.
- Errors: `{"error": {"code": "…", "message": "…", "details": […]}}` with correct HTTP status.
- Lists: `?page=&page_size=&sort=&q=` → `{"items": [], "total": n, "page": 1, "page_size": 20, "pages": m}`.
- Writes that can be retried accept `Idempotency-Key` (bookings, payments).
- OpenAPI served at `/api/v1/openapi.json`, Swagger UI at `/docs` (non-production only).

## 8. Deployment topology (§17–18)

- **Local (primary):** Docker Compose (Postgres + backend + built frontend) **or** native
  `scripts/setup_local.sh` for machines without Docker. Works on Windows 10/11 (WSL2 or native Python + local PostgreSQL).
- **Free-tier pilot:** backend on a free Python host, Postgres on a free managed tier (or same VM),
  frontend static build on any static host. Every paid capability is optional and behind env flags.
- **Backups:** `scripts/backup_db.sh` (timestamped `.dump` + upload hook), `scripts/restore_db.sh`
  with a restore **test** command documented in `docs/BACKUP_RESTORE.md`.
- **Rollback:** previous application archive + `alembic downgrade` guidance; migrations are
  additive-first so rollback rarely requires schema reversal.

## 9. Milestone plan and status

| # | Milestone | Status after this session |
|---|---|---|
| 1 | Inspection + architecture + scaffold | see CHANGELOG §M1 |
| 2 | Database + authentication | see CHANGELOG §M2 |
| 3–12 | per master prompt | pending |

## 10. Deliberate non-goals for MVP

Kubernetes, microservices, message brokers, paid AI APIs, real-time provider GPS tracking,
WhatsApp Business API (click-to-chat links only). Revisit after pilot data.

## 11. Risk register (selected)

| Risk | Mitigation |
|---|---|
| Free-tier host sleeps / limits | Documented limits; backup host instructions; no assumption of permanence |
| Payment gateway onboarding delay | Direct cash/UPI + admin-recorded flows ship first; gateway flagged until merchant account approved |
| Telugu font rendering on old Android | Bundled Noto Sans Telugu subset in PWA; fallback chain documented |
| SMS OTP provider absent | Password + optional OTP behind feature flag; OTP endpoints return explicit 503 until configured |
| Single-person operations | Admin MFA (TOTP) supported; audit trail on every privileged action |
