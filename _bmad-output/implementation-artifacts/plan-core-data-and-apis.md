---
title: 'Core data model, synthetic generator, accounts and payments APIs'
type: 'feature'
ticket: ''
created: '2026-09-30'
status: 'built'
route: 'full'
route_source: 'auto'
baseline_revision: 'c12a87ecc94ccbcaac6ebac0b975259130e3cb8b'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['inline-single']
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/specs/spec-corporate-portal-poc/SPEC.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-corportal-2026-09-30/EXPERIENCE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The portal PoC has no code yet. Everything else (UI, lake pipelines, ML, CI) needs a ledger, believable synthetic AED data and APIs to build on.

**Approach:** Build the following, runnable locally with `docker compose up`:
- An Azure SQL–compatible schema: an operational ledger with a payment approval state machine and an outbox table, plus a `serving` schema the portal reads.
- A deterministic synthetic data generator.
- Two Python FastAPI services: `accounts-api` for reads and `payments-api` for writes.

## Boundaries & Constraints

**Always:**
- Python 3.12 + FastAPI + SQLAlchemy Core.
- One shared package `corp_common` (DB, auth, company scoping, region header).
- All money is `DECIMAL(18,2)` AED, formatted by the UI and not the API.
- Every query is scoped to the caller's `company_id`, taken from their identity and never from request input.
- Every response carries `X-Served-From: $REGION`.
- The SQL host and credentials come from env only.
- Hard cap for this plan: 15 tests or fewer; the whole project cap is 100.

**Never:**
- Terraform or Azure resources.
- Kong, Istio or Vault config.
- UI code.
- Event Hubs publishing (piece 3 reads the outbox).
- ML.
- Passwords in code, other than the local compose `.env.example`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Create payment | Priya POSTs 450,000 Reserve→Operating | 201, status `AWAITING_APPROVAL`, balances unchanged | — |
| Approve | Tom approves it | `EXECUTED`; Reserve −450k, Operating +450k, 2 transactions and outbox rows written in one DB transaction | — |
| Self-approve | Priya approves her own payment | 403 "You can't approve a payment you created." | nothing changes |
| Cross-company | Omar (Fabrikam) GETs a Northwind account or payment | 404 | attempt logged as `access_denied` with the user and the target |
| Double approve | Two concurrent approves | exactly one executes | the loser gets 409 |
| Insufficient funds | amount > from-account balance at approval | 409, status stays `AWAITING_APPROVAL` | — |
| Reject | Tom rejects | `REJECTED` + outbox row, no ledger change | — |

</frozen-after-approval>

## Code Map

Greenfield: the repo has only planning artifacts, `infra/bootstrap/` (do not touch) and `docs/governance/`.

- `db/schema.sql`, holding:
  - schemas `ops` and `serving`;
  - tables `companies`, `users`, `accounts`, `transactions`, `beneficiaries`, `payments`, `scheduled_payments`, `outbox`, `access_log`;
  - `serving` tables `cash_position`, `forecast`, `anomalies`.
- `db/rls.sql`: SQL Server row-level security keyed on `SESSION_CONTEXT('company_id')`. Applied in compose and Azure; skipped under SQLite.
- `services/common/corp_common/`, holding:
  - `db.py`: the engine from `DB_URL`; sets session context per connection on MSSQL.
  - `auth.py`: `AUTH_MODE=dev` reads the `X-Demo-User` username. `entra` validates the bearer JWT with PyJWT against the JWKS in `ENTRA_TENANT_ID`/`ENTRA_AUDIENCE`, then maps `oid` to `users.entra_oid`.
  - `middleware.py`: region header.
- `services/accounts-api/app.py`:
  - `GET /me`, `/accounts`, `/accounts/{id}/transactions`, `/dashboard` (from `serving.cash_position` + `serving.anomalies`) and `/healthz`.
- `services/payments-api/app.py`:
  - `POST /payments`, `GET /payments`, `POST /payments/{id}/approve|reject`, `GET /beneficiaries` and `/healthz`.
- `data/generator/generate.py`, with a `--seed` and `--as-of` date:
  - 8 UAE LLCs, including **Northwind Logistics LLC**. Its users are Priya Nair (initiator) and Tom Okafor (approver). Omar Haddad is at Fabrikam Trading LLC.
  - 90 days of history, with payroll cycles, suppliers, customer inflows and seasonality.
  - 3 planted anomalies:
    - Harbour Freight Co at 4× average (2 days before as-of);
    - a same-day duplicate supplier payment;
    - a weekend 02:00 payment to a first-time beneficiary.
  - Seeds the `serving` tables so the UI works before piece 3 exists.
- `docker-compose.yml`: `sqlserver` (mssql 2022, `platform: linux/amd64`), a `db-init` job (schema + rls + generator), `accounts-api:8001`, `payments-api:8002`.
- `pyproject.toml` (uv workspace) and `tests/`.

## Tasks & Acceptance

**Execution:**
- [x] `pyproject.toml`, `services/common/**` -- uv workspace with the shared package -- one dependency set for both services.
- [x] `db/schema.sql`, `db/rls.sql` -- DDL portable to SQLite for tests, where possible -- tests stay fast without SQL Server.
- [x] `data/generator/generate.py` -- deterministic generator calibrated so that Northwind as-of matches the demo figures in Design Notes -- the demo story has to be true in the data.
- [x] `services/accounts-api/**` -- read endpoints -- CAP-1/2/3.
- [x] `services/payments-api/**` -- state machine, with the approve step as a single transaction using `UPDATE … WHERE status='AWAITING_APPROVAL'` -- CAP-4, concurrency row.
- [x] `services/*/Dockerfile` -- python:3.12-slim + msodbcsql18 -- the same images later run in AKS.
- [x] `docker-compose.yml`, `.env.example`, `README.md` (run section only) -- local stack.
- [x] `tests/` -- ≤15 tests on SQLite: the I/O matrix rows, generator determinism and Northwind figures, and the region header.

**Acceptance Criteria:**
- Given a fresh clone, when `docker compose up` completes, then `curl -H 'X-Demo-User: priya' localhost:8001/dashboard` returns Northwind's figures with `X-Served-From: local`.
- Given `--seed 42`, when the generator runs twice, then the outputs are identical.
- Given Tom approves the 450k top-up, when Priya reads `/dashboard`, then the operational balances reflect it. (The serving figures refresh in piece 3.)
- Given the whole test suite, when `uv run pytest` runs, then it passes in under 30 s with ≤15 tests.

## Implementation Notes

- `docker compose up` needs `cp .env.example .env` first: the compose file refuses to start without `MSSQL_SA_PASSWORD` rather than hard-coding one.
- `db/schema.sql` is T-SQL; `corp_common/schema.py` translates it for SQLite (GO batches, `-- mssql-only` batches skipped, IDENTITY/NVARCHAR(MAX)/index syntax rewritten). SQLite attaches `ops` and `serving` as separate files and uses `BEGIN IMMEDIATE` so concurrent approvals serialise.
- Cross-company targets return 404 via a `Denied` exception; the handler writes `ops.access_log` after the scoped transaction has rolled back.
- `AUTH_MODE` defaults to `entra` (fail closed); compose sets `dev`. Only approvers (Tom) can approve; creators can neither approve nor reject their own payment.
- Money is returned as fixed-point strings (`"5800000.00"`). `/dashboard` returns the serving KPIs plus an `operational` block read live from the ledger (reflects an approval immediately).
- Outbox events: `payment.executed` + one `transaction.posted` per ledger row on approve; `payment.rejected` on reject. Nothing on create.
- db-init keeps existing data on re-run unless `RESEED=1`; the default as-of is today in Gulf time.
- All stored timestamps are UTC; generator business times are Gulf Standard Time (UTC+4), so the weekend anomaly is Saturday 02:00 GST.
- RLS filters `accounts`, `transactions`, `beneficiaries`, `payments`, `scheduled_payments` and the three `serving` tables; `users`, `companies`, `outbox` and `access_log` are not filtered. The lake/ML writers in pieces 3–4 must set `SESSION_CONTEXT('company_id')` (or the policy needs an exemption) to update or delete `serving` rows.

## Plan Change Log

## Review Triage Log

- Pass 1 (one inline reviewer, per the owner's single-reviewer rule): 1 medium, 1 low.
  - medium, patch: in entra mode the issuer was unchecked unless `ENTRA_ISSUER` was set. Microsoft's signing keys are shared across tenants, so it now defaults to the tenant v2.0 issuer (`corp_common/auth.py`).
  - low, patch: EXPERIENCE.md defined Available as Operating + Payroll; aligned it to every account except Reserve, which matches the generator.
  - Checked and fine: approve is atomic (claim + guarded debit roll back together); denial logging uses a separate connection, so it survives the rollback; the input validator rejects from == to and amounts ≤ 0.
  - Deferred to piece 3: RLS on the `serving` tables means pipeline writers must set session context or be exempted.

## Design Notes

**Northwind as-of figures:**
- Accounts: Operating 2,860,000; Reserve 2,240,000; Payroll 150,000; Collections 550,000. Total 5,800,000.
- Supplier `scheduled_payments` in the next 7 days total 1,780,000.
- `available` = non-Reserve balances − scheduled = 1,780,000.
- Payroll of 1,900,000 is due on the first Thursday at least 3 days after as-of.
- `forecast_low` = available − payroll = −120,000.
- IBANs follow the pattern `AE07 0331 0000 xxxx xxxx 00n`.

**Auth:** dev mode uses the header only because it's local. In entra mode, Kong validates too; the services re-validate because it's cheap and gives defense in depth.

## Verification

**Commands:**
- `uv run pytest -q` -- expected: passes, ≤15 tests.
- `docker compose up -d --build && curl -si -H 'X-Demo-User: priya' localhost:8001/dashboard` -- expected: 200, `X-Served-From: local`, total 5800000.00.
