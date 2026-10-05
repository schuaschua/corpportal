---
title: 'Event flow: outbox relay to Event Hubs and bronze/silver/gold medallion pipelines'
type: 'feature'
ticket: ''
created: '2026-09-30'
status: 'built'
route: 'full'
route_source: 'auto'
baseline_revision: '94b52a6a4a963d923f4ae9501b9dcf4ccbeb35be'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['inline-single']
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/specs/spec-corporate-portal-poc/stack.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Approved payments sit in the ledger outbox and never reach the lake. The dashboard headline figures never move, and the behind-the-scenes drawer can't show the medallion stages that Act 3 of the demo depends on (CAP-5).

**Approach:** Add three things:
- An `outbox-relay` service that publishes outbox rows to Event Hubs.
- A PySpark + Delta medallion (bronze → silver → gold → SQL `serving`) packaged as a Databricks Asset Bundle, which also runs locally in a container.
- Stage tracing, so the drawer ticks each stage for a real payment.

## Boundaries & Constraints

**Always:**
- **Relay:**
  - Publishes in outbox `id` order, then sets `published_at`, giving at-least-once delivery. Downstream dedupes on the outbox `id`.
  - Sink is chosen by `RELAY_SINK`:
    - `eventhubs`: `azure-eventhub`, using `DefaultAzureCredential` in Azure or `EVENTHUB_CONNECTION_STRING` for the emulator or tests.
    - `files`: writes JSON lines to `LANDING_DIR` for local runs.
- **Pipelines:**
  - Idempotent: re-running with no new events changes nothing.
  - The bronze source is chosen by `BRONZE_SOURCE`: `kafka` (Event Hubs Kafka endpoint, used on Databricks) or `files` (`LANDING_DIR`, used locally).
  - Delta tables use the names `corportal.bronze.events`, `corportal.silver.transactions`, `corportal.silver.payments`, `corportal.gold.cash_position_daily` and `corportal.gold.payment_features`. On Databricks the catalog is Unity Catalog; locally it's a path under `LAKE_DIR`.
- **Serving write:**
  - Replace each company's rows in `serving.cash_position` using the same Available definition as the piece 1 generator: every account except Reserve, minus supplier payments scheduled in the next 7 days.
  - The writer connects as a dedicated `pipeline_writer` principal. `db/rls.sql` exempts it by role membership (`IS_MEMBER('pipeline_writer')`), never by session context the APIs could set.
- **Cadence:** one setting, `BATCH_CADENCE_SECONDS`, defaulting to 300. It drives the local loop and the Databricks job trigger (`availableNow` on a schedule).
- **Trace:**
  - The relay writes the `event_hubs` stage and the pipelines write `bronze`, `silver`, `gold` and `serving` stages to `ops.pipeline_trace (payment_id, stage, at)`.
  - Each batch writes one row to `ops.pipeline_runs`.
  - `GET /pipeline/trace/{payment_id}` on accounts-api is company-scoped and returns the stages plus `next_batch_at`.
- ≤12 new tests (the project total is currently 20).

**Never:**
- ML models (piece 4).
- Terraform or real Azure resources.
- A Databricks SQL warehouse.
- Model serving endpoints.
- Any change to the payment state machine.
- Always-on streaming clusters.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Publish | 3 unpublished outbox rows | all 3 are sent in id order and `published_at` is set; `event_hubs` trace written for payment events | — |
| Sink down | the publish call raises | nothing is marked published; the relay retries next tick | logs the error, doesn't crash |
| Duplicate event | the same outbox id lands twice | silver holds one row | dedupe on the event id |
| Approve flows through | Tom approves the AED 450k top-up | after one batch, `serving.cash_position` available is 2,230,000 and the trace shows all 6 stages | — |
| No new events | a batch runs on an unchanged landing dir | no serving change; a run row is still written | — |
| API trace for another company | Omar requests a Northwind payment trace | 404 + `access_denied` logged | — |

</frozen-after-approval>

## Code Map

- `db/schema.sql` (add `ops.pipeline_trace` and `ops.pipeline_runs`), `db/rls.sql` (predicate `OR IS_MEMBER('pipeline_writer') = 1`), `db/init_db.py` (create the local `pipeline_writer` login and user, add it to the role, grant it write on `serving` and `ops.pipeline_*` and read on `ops`).
- `services/common/corp_common/tables.py`: add the two tables. The `ops.outbox` table (`published_at` NULL means unpublished, with index `ix_outbox_unpublished`) already exists; reuse it.
- `services/payments-api/app.py`: writes `payment.executed`, `payment.rejected` and `transaction.posted`. Don't change it.
- `services/accounts-api/app.py`: add the trace endpoint. `/dashboard` already reads `serving.cash_position`.
- `web/src/components/BehindTheScenes.tsx`: swap the placeholder for polling `/api/accounts/pipeline/trace/{id}` every 5 s, showing the "Next batch in mm:ss" countdown from `next_batch_at`.
- New code:
  - `services/outbox-relay/`: app, Dockerfile.
  - `databricks/`:
    - `databricks.yml` (the bundle, with a job holding bronze, silver, gold and serving tasks on a single-node job cluster);
    - `src/corp_pipelines/` (`bronze.py`, `silver.py`, `gold.py`, `serving_writer.py`, `trace.py`, `run_local.py`);
    - `Dockerfile.local` (python + openjdk + delta-spark).
- `docker-compose.yml`: add the `outbox-relay` service (files sink, shared volume `lake`) and the `pipelines` service (a loop every `BATCH_CADENCE_SECONDS`, 60 by default locally).

## Tasks & Acceptance

**Execution:**
- [x] `db/*`, `corp_common/tables.py` -- trace/run tables, RLS exemption role, local pipeline login -- the writer can't pass RLS without them.
- [x] `services/outbox-relay/**` -- a polling relay with two sinks -- CAP-5 transport.
- [x] `databricks/src/corp_pipelines/**` -- bronze (raw JSON + ingest time), silver (typed and deduped), gold (daily cash position per account and company, plus payment features for piece 4), serving writer (local SQLAlchemy; JDBC with an Entra access token on Databricks) -- the medallion.
- [x] `databricks/databricks.yml` -- the bundle job, parameterised for catalog, cadence and the Event Hubs namespace -- Jenkins deploys it later.
- [x] `services/accounts-api/app.py` + `web/src/components/BehindTheScenes.tsx` -- the trace endpoint and live drawer -- the Act 3 climax.
- [x] `docker-compose.yml`, `README.md` -- local wiring.
- [x] `tests/` -- ≤12 tests covering the matrix. Pipeline tests use a local SparkSession on tiny inputs, marked so they can be skipped when there's no JVM.

**Acceptance Criteria:**
- Given the compose stack, when Tom approves a payment, then within 2 batch intervals the drawer ticks all six stages and the dashboard headline Available updates.
- Given `databricks bundle validate -t dev`, when run with placeholder variables, then it succeeds (skip if the CLI isn't installed, and note it).

## Implementation Notes

- **Six stages** = `ledger` (the payment's `executed_at`, derived by the endpoint) + the five trace rows. `stages` lists only the stages reached, in order; the response also carries `status` and `last_batch_at`.
- **Principals:** `db/rls.sql` creates the `pipeline_writer` role and adds `OR IS_MEMBER(N'pipeline_writer') = 1`. Grants go to the role, so in Azure it's enough to add the Databricks identity to it. Locally, `db/init_db.py` creates the login `pipeline_writer` with the database user `pipeline_writer_local`, because a user can't have the same name as a role (`PIPELINE_WRITER_PASSWORD`, default in compose). Checked on SQL Server: `sa` is not a member (`IS_MEMBER` = 0), so the APIs stay filtered. When existing data is kept, databases seeded before piece 3 get the two `ops.pipeline_*` tables through `metadata.create_all`.
- **Gold balances:** the latest lake `balance_after` for each account. Accounts with no lake event yet use the ledger's reference balance from `ops.accounts`; seed history predates the outbox. `gold.cash_position_daily` holds one row per account for the business date (`AS_OF`, else today in Gulf time), and that partition is replaced on each run.
- **Serving write:** for each company with new silver rows in this batch, delete and insert that company's row for the business date. Other dates are left alone, so the 90-day seeded trend stays. `company_position()` reproduces the generator's latest row for all 8 companies (tested).
- **Batch state:** tasks share a `run_id`. Bronze and silver tag new rows with it, and gold and serving only act when silver has rows from this run. A batch with nothing new makes no Delta commit and no serving write, but still writes its `ops.pipeline_runs` row. `next_batch_at` = max(start + cadence, finish).
- **Bundle schedule:** bundle variables can't do arithmetic, so the job trigger is a Quartz cron `batch_schedule` (default `0 0/5 * * * ?`), documented as having to match `batch_cadence_seconds`. The cadence also reaches the tasks as `BATCH_CADENCE_SECONDS` through `spark_env_vars`. Auth uses Unity Catalog service credentials (Event Hubs Kafka `databricks.serviceCredential`; SQL access token for JDBC), with a secret-scope connection string or `DefaultAzureCredential` as the fallback.
- **Extra modules** beyond the Code Map: `lake.py` (settings and Delta access), `sqlstore.py` (SQLAlchemy and JDBC stores), `cli.py` (wheel entry point), `databricks/pyproject.toml`, and a `relay` dependency group in the root `pyproject.toml` (`azure-eventhub`, `azure-identity`).
- **Local Spark tuning:** Delta data skipping is off and the driver JIT is C1-only. On Docker Desktop, alongside the emulated SQL Server, the first batch after a container start takes about 1 to 2 minutes (JVM warm-up). Later batches take 5 to 30 s.

## Plan Change Log

## Review Triage Log

- Pass 1 (one inline reviewer): 1 medium patched, 3 low deferred.
  - medium, patch: local CPU burn, about 2.4 cores. The relay now backs off up to 30 s when idle and its poll moves from 2 s to 5 s; the local cadence moves from 60 s to 120 s; the pipelines container is capped at 1.5 CPUs.
  - low, deferred to piece 4: `gold.payment_features` holds only portal-made payments, because the seeded 90-day history (including the 3 planted anomalies) never passed through the outbox. Piece 4 must backfill the seeded history into bronze, or the anomaly model can't find the planted anomalies.
  - low, deferred to the integration window: the Databricks Kafka read (serviceCredential) and the JDBC serving write are untested; `databricks bundle validate` hasn't been run.
  - low, accepted: a batch that fails midway leaves its trace stuck until the company's next event.

## Verification

**Commands:**
- `uv run pytest -q` -- expected: ≤32 tests total, all pass.
- `docker compose up -d --build`, approve a payment, wait 2 minutes, `curl -H 'X-Demo-User: priya' localhost:8088/api/accounts/pipeline/trace/<id>` -- expected: 6 stages.
