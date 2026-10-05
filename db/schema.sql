-- Corporate Portal PoC: operational ledger (ops) and portal read model (serving).
-- Written for Azure SQL / SQL Server 2022. corp_common.schema translates it for SQLite
-- (tests): batches are split on GO lines, batches marked "-- mssql-only" are skipped,
-- and IDENTITY / NVARCHAR(MAX) / index syntax is rewritten.
-- This script is a full reset: it drops and recreates every table.
-- All money is DECIMAL(18,2) AED.

-- mssql-only
IF SCHEMA_ID(N'ops') IS NULL EXEC(N'CREATE SCHEMA ops');
GO
-- mssql-only
IF SCHEMA_ID(N'serving') IS NULL EXEC(N'CREATE SCHEMA serving');
GO

DROP TABLE IF EXISTS serving.models;
DROP TABLE IF EXISTS serving.anomalies;
DROP TABLE IF EXISTS serving.forecast;
DROP TABLE IF EXISTS serving.cash_position;
DROP TABLE IF EXISTS ops.pipeline_runs;
DROP TABLE IF EXISTS ops.pipeline_trace;
DROP TABLE IF EXISTS ops.access_log;
DROP TABLE IF EXISTS ops.outbox;
DROP TABLE IF EXISTS ops.scheduled_payments;
DROP TABLE IF EXISTS ops.transactions;
DROP TABLE IF EXISTS ops.payments;
DROP TABLE IF EXISTS ops.beneficiaries;
DROP TABLE IF EXISTS ops.accounts;
DROP TABLE IF EXISTS ops.users;
DROP TABLE IF EXISTS ops.companies;
GO

CREATE TABLE ops.companies (
    id              INT            NOT NULL PRIMARY KEY,
    name            NVARCHAR(200)  NOT NULL,
    trade_licence   NVARCHAR(40)   NOT NULL,
    emirate         NVARCHAR(40)   NOT NULL,
    industry        NVARCHAR(60)   NOT NULL
);

CREATE TABLE ops.users (
    id              INT            NOT NULL PRIMARY KEY,
    company_id      INT            NOT NULL,
    username        NVARCHAR(50)   NOT NULL UNIQUE,
    display_name    NVARCHAR(100)  NOT NULL,
    title           NVARCHAR(60)   NOT NULL,
    role            NVARCHAR(20)   NOT NULL,   -- initiator | approver
    email           NVARCHAR(200)  NOT NULL,
    entra_oid       NVARCHAR(64)   NULL,
    CONSTRAINT fk_users_company FOREIGN KEY (company_id) REFERENCES ops.companies(id)
);
CREATE UNIQUE INDEX ux_users_entra_oid ON ops.users(entra_oid) WHERE entra_oid IS NOT NULL;

CREATE TABLE ops.accounts (
    id              INT            NOT NULL PRIMARY KEY,
    company_id      INT            NOT NULL,
    name            NVARCHAR(100)  NOT NULL,
    kind            NVARCHAR(20)   NOT NULL,   -- operating | reserve | payroll | collections
    iban            NVARCHAR(34)   NOT NULL UNIQUE,
    currency        CHAR(3)        NOT NULL,
    balance         DECIMAL(18,2)  NOT NULL,
    updated_at      DATETIME2(3)   NOT NULL,
    CONSTRAINT fk_accounts_company FOREIGN KEY (company_id) REFERENCES ops.companies(id)
);
CREATE INDEX ix_accounts_company ON ops.accounts(company_id);

CREATE TABLE ops.beneficiaries (
    id              INT            NOT NULL PRIMARY KEY,
    company_id      INT            NOT NULL,
    name            NVARCHAR(200)  NOT NULL,
    iban            NVARCHAR(34)   NOT NULL,
    category        NVARCHAR(30)   NOT NULL,   -- supplier
    created_at      DATETIME2(3)   NOT NULL,
    CONSTRAINT fk_beneficiaries_company FOREIGN KEY (company_id) REFERENCES ops.companies(id)
);
CREATE INDEX ix_beneficiaries_company ON ops.beneficiaries(company_id);

-- Payment approval state machine:
--   AWAITING_APPROVAL --approve (different user, funds ok)--> EXECUTED
--   AWAITING_APPROVAL --reject (different user)-------------> REJECTED
-- Exactly one of to_account_id (internal transfer) / beneficiary_id (external) is set.
CREATE TABLE ops.payments (
    id              BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    company_id      INT            NOT NULL,
    from_account_id INT            NOT NULL,
    to_account_id   INT            NULL,
    beneficiary_id  INT            NULL,
    amount          DECIMAL(18,2)  NOT NULL,
    currency        CHAR(3)        NOT NULL,
    value_date      DATE           NOT NULL,
    reference       NVARCHAR(140)  NULL,
    status          NVARCHAR(20)   NOT NULL,
    created_by      INT            NOT NULL,
    created_at      DATETIME2(3)   NOT NULL,
    decided_by      INT            NULL,
    decided_at      DATETIME2(3)   NULL,
    executed_at     DATETIME2(3)   NULL,
    CONSTRAINT fk_payments_company FOREIGN KEY (company_id) REFERENCES ops.companies(id),
    CONSTRAINT fk_payments_from FOREIGN KEY (from_account_id) REFERENCES ops.accounts(id),
    CONSTRAINT fk_payments_to FOREIGN KEY (to_account_id) REFERENCES ops.accounts(id),
    CONSTRAINT fk_payments_beneficiary FOREIGN KEY (beneficiary_id) REFERENCES ops.beneficiaries(id),
    CONSTRAINT fk_payments_created_by FOREIGN KEY (created_by) REFERENCES ops.users(id),
    CONSTRAINT fk_payments_decided_by FOREIGN KEY (decided_by) REFERENCES ops.users(id),
    CONSTRAINT ck_payments_status CHECK (status IN ('AWAITING_APPROVAL', 'EXECUTED', 'REJECTED')),
    CONSTRAINT ck_payments_amount CHECK (amount > 0)
);
CREATE INDEX ix_payments_company_status ON ops.payments(company_id, status);

-- Ledger entries. amount is signed: negative = debit, positive = credit.
CREATE TABLE ops.transactions (
    id              BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    company_id      INT            NOT NULL,
    account_id      INT            NOT NULL,
    payment_id      BIGINT         NULL,
    booked_at       DATETIME2(3)   NOT NULL,
    value_date      DATE           NOT NULL,
    amount          DECIMAL(18,2)  NOT NULL,
    balance_after   DECIMAL(18,2)  NOT NULL,
    category        NVARCHAR(30)   NOT NULL,   -- customer | supplier | payroll | transfer | fee | interest
    counterparty    NVARCHAR(200)  NOT NULL,
    description     NVARCHAR(200)  NOT NULL,
    CONSTRAINT fk_transactions_company FOREIGN KEY (company_id) REFERENCES ops.companies(id),
    CONSTRAINT fk_transactions_account FOREIGN KEY (account_id) REFERENCES ops.accounts(id),
    CONSTRAINT fk_transactions_payment FOREIGN KEY (payment_id) REFERENCES ops.payments(id)
);
CREATE INDEX ix_transactions_account_booked ON ops.transactions(account_id, booked_at);

CREATE TABLE ops.scheduled_payments (
    id              INT            NOT NULL PRIMARY KEY,
    company_id      INT            NOT NULL,
    from_account_id INT            NOT NULL,
    beneficiary_id  INT            NULL,
    kind            NVARCHAR(20)   NOT NULL,   -- supplier | payroll
    amount          DECIMAL(18,2)  NOT NULL,
    due_date        DATE           NOT NULL,
    description     NVARCHAR(200)  NOT NULL,
    CONSTRAINT fk_scheduled_company FOREIGN KEY (company_id) REFERENCES ops.companies(id),
    CONSTRAINT fk_scheduled_account FOREIGN KEY (from_account_id) REFERENCES ops.accounts(id),
    CONSTRAINT fk_scheduled_beneficiary FOREIGN KEY (beneficiary_id) REFERENCES ops.beneficiaries(id)
);
CREATE INDEX ix_scheduled_company_due ON ops.scheduled_payments(company_id, due_date);

-- Transactional outbox. Written in the same DB transaction as the state change;
-- piece 3 publishes unpublished rows (published_at IS NULL) to Event Hubs in id order.
CREATE TABLE ops.outbox (
    id              BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    company_id      INT            NOT NULL,
    aggregate_type  NVARCHAR(40)   NOT NULL,
    aggregate_id    NVARCHAR(40)   NOT NULL,
    event_type      NVARCHAR(60)   NOT NULL,
    payload         NVARCHAR(MAX)  NOT NULL,
    created_at      DATETIME2(3)   NOT NULL,
    published_at    DATETIME2(3)   NULL
);
CREATE INDEX ix_outbox_unpublished ON ops.outbox(published_at, id);

CREATE TABLE ops.access_log (
    id              BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    occurred_at     DATETIME2(3)   NOT NULL,
    user_id         INT            NULL,
    username        NVARCHAR(50)   NULL,
    company_id      INT            NULL,
    action          NVARCHAR(40)   NOT NULL,   -- access_denied
    target_type     NVARCHAR(40)   NOT NULL,
    target_id       NVARCHAR(40)   NOT NULL,
    detail          NVARCHAR(400)  NULL
);

-- Lake pipeline progress (piece 3). The outbox relay writes the event_hubs stage and the
-- medallion batch writes bronze, silver, gold and serving; one row per stage per payment.
-- Not company-filtered: accounts-api checks the payment belongs to the caller first.
CREATE TABLE ops.pipeline_trace (
    payment_id      BIGINT         NOT NULL,
    stage           NVARCHAR(20)   NOT NULL,   -- event_hubs | bronze | silver | gold | serving
    at              DATETIME2(3)   NOT NULL,
    CONSTRAINT pk_pipeline_trace PRIMARY KEY (payment_id, stage)
);

-- One row per medallion batch, including batches that found no new events.
CREATE TABLE ops.pipeline_runs (
    id                  BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    run_id              NVARCHAR(64)   NOT NULL,
    started_at          DATETIME2(3)   NOT NULL,
    finished_at         DATETIME2(3)   NOT NULL,
    events_ingested     INT            NOT NULL,   -- rows landed in bronze by this batch
    events_new          INT            NOT NULL,   -- rows new to silver (after dedupe)
    companies_refreshed INT            NOT NULL,
    status              NVARCHAR(20)   NOT NULL,   -- succeeded
    next_batch_at       DATETIME2(3)   NULL
);
CREATE INDEX ix_pipeline_runs_finished ON ops.pipeline_runs(finished_at);

-- ---------------------------------------------------------------- serving
-- Read model the portal dashboard reads. Seeded by the generator; refreshed by the
-- lake pipelines (piece 3) and the ML jobs (piece 4: train writes serving.models, score
-- replaces serving.forecast and serving.anomalies, every row naming its model and version).

CREATE TABLE serving.cash_position (
    company_id          INT            NOT NULL,
    as_of_date          DATE           NOT NULL,
    total_cash          DECIMAL(18,2)  NOT NULL,
    available           DECIMAL(18,2)  NOT NULL,   -- non-Reserve balances minus supplier payments due in 7 days
    scheduled_out_7d    DECIMAL(18,2)  NOT NULL,
    payroll_due_date    DATE           NULL,
    payroll_due_amount  DECIMAL(18,2)  NULL,
    forecast_low        DECIMAL(18,2)  NULL,       -- available minus payroll due
    refreshed_at        DATETIME2(3)   NOT NULL,
    CONSTRAINT pk_cash_position PRIMARY KEY (company_id, as_of_date)
);

CREATE TABLE serving.forecast (
    company_id          INT            NOT NULL,
    forecast_date       DATE           NOT NULL,
    predicted_balance   DECIMAL(18,2)  NOT NULL,
    lower_bound         DECIMAL(18,2)  NOT NULL,
    upper_bound         DECIMAL(18,2)  NOT NULL,
    model_name          NVARCHAR(100)  NOT NULL,
    model_version       NVARCHAR(40)   NOT NULL,
    generated_at        DATETIME2(3)   NOT NULL,
    CONSTRAINT pk_forecast PRIMARY KEY (company_id, forecast_date)
);

CREATE TABLE serving.anomalies (
    id                  INT            NOT NULL PRIMARY KEY,
    company_id          INT            NOT NULL,
    payment_id          BIGINT         NULL,
    transaction_id      BIGINT         NULL,
    occurred_at         DATETIME2(3)   NOT NULL,
    counterparty        NVARCHAR(200)  NOT NULL,
    amount              DECIMAL(18,2)  NOT NULL,
    score               DECIMAL(6,4)   NOT NULL,
    reason              NVARCHAR(400)  NOT NULL,
    detected_at         DATETIME2(3)   NOT NULL,
    model_name          NVARCHAR(100)  NOT NULL,
    model_version       NVARCHAR(40)   NOT NULL
);
CREATE INDEX ix_anomalies_company ON serving.anomalies(company_id, occurred_at);

-- The registered ML models the scores come from (one row per model, replaced on each
-- training run). Not company data: metrics are aggregates over all companies.
CREATE TABLE serving.models (
    model_name          NVARCHAR(100)  NOT NULL PRIMARY KEY,   -- cash_forecast | payment_anomaly
    registered_name     NVARCHAR(200)  NOT NULL,               -- Unity Catalog: corportal.ml.<model_name>
    model_version       NVARCHAR(40)   NOT NULL,
    trained_at          DATETIME2(3)   NOT NULL,
    metrics             NVARCHAR(MAX)  NOT NULL,               -- JSON object of the run's metrics
    run_id              NVARCHAR(64)   NULL                    -- MLflow run
);
GO
