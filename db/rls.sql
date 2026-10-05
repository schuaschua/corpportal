-- Row-level security: every company-owned row is visible to, and writable by, only the
-- company whose id is in SESSION_CONTEXT('company_id'). corp_common.db sets that key on
-- every scoped connection from the caller's identity (never from request input).
-- SQL Server / Azure SQL only; skipped under SQLite (the services also filter by
-- company_id in every query, so tests exercise the same scoping).
-- ops.users, ops.companies, ops.outbox, ops.access_log and ops.pipeline_* are not filtered:
-- the services read users before the company is known, and the outbox relay reads every
-- company.
--
-- The lake pipeline writes serving rows for every company, so members of the database role
-- pipeline_writer pass the predicate. The exemption is by role membership (IS_MEMBER), never
-- by session context: the APIs set SESSION_CONTEXT, so a context key could be forged by a
-- bug there, but they cannot change which principal they connect as. db/init_db.py creates
-- the role (and, locally, a login in it); in Azure the Databricks identity is added to it.

DROP SECURITY POLICY IF EXISTS ops.company_isolation;
GO
DROP FUNCTION IF EXISTS ops.fn_company_predicate;
GO
IF DATABASE_PRINCIPAL_ID(N'pipeline_writer') IS NULL CREATE ROLE pipeline_writer;
GO
CREATE FUNCTION ops.fn_company_predicate(@company_id INT)
RETURNS TABLE
WITH SCHEMABINDING
AS
RETURN
    SELECT 1 AS allowed
    WHERE @company_id = CAST(SESSION_CONTEXT(N'company_id') AS INT)
       OR IS_MEMBER(N'pipeline_writer') = 1;
GO
CREATE SECURITY POLICY ops.company_isolation
    ADD FILTER PREDICATE ops.fn_company_predicate(company_id) ON ops.accounts,
    ADD BLOCK  PREDICATE ops.fn_company_predicate(company_id) ON ops.accounts AFTER INSERT,
    ADD BLOCK  PREDICATE ops.fn_company_predicate(company_id) ON ops.accounts AFTER UPDATE,
    ADD FILTER PREDICATE ops.fn_company_predicate(company_id) ON ops.transactions,
    ADD BLOCK  PREDICATE ops.fn_company_predicate(company_id) ON ops.transactions AFTER INSERT,
    ADD FILTER PREDICATE ops.fn_company_predicate(company_id) ON ops.beneficiaries,
    ADD BLOCK  PREDICATE ops.fn_company_predicate(company_id) ON ops.beneficiaries AFTER INSERT,
    ADD FILTER PREDICATE ops.fn_company_predicate(company_id) ON ops.payments,
    ADD BLOCK  PREDICATE ops.fn_company_predicate(company_id) ON ops.payments AFTER INSERT,
    ADD BLOCK  PREDICATE ops.fn_company_predicate(company_id) ON ops.payments AFTER UPDATE,
    ADD FILTER PREDICATE ops.fn_company_predicate(company_id) ON ops.scheduled_payments,
    ADD FILTER PREDICATE ops.fn_company_predicate(company_id) ON serving.cash_position,
    ADD FILTER PREDICATE ops.fn_company_predicate(company_id) ON serving.forecast,
    ADD FILTER PREDICATE ops.fn_company_predicate(company_id) ON serving.anomalies
    WITH (STATE = ON);
GO
