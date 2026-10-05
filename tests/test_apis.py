import threading
from decimal import Decimal

from sqlalchemy import select

from conftest import AS_OF, as_user
from corp_common import tables as t

OPERATING, RESERVE = 1, 2  # Northwind account ids
FABRIKAM_ACCOUNT = 5


def create_topup(payments, amount="450000.00"):
    r = payments.post("/payments", headers=as_user("priya"), json={
        "from_account_id": RESERVE, "to_account_id": OPERATING, "amount": amount,
        "value_date": AS_OF.isoformat(), "reference": "Payroll top-up"})
    assert r.status_code == 201, r.text
    return r.json()


def balances(accounts, user="priya"):
    r = accounts.get("/accounts", headers=as_user(user))
    return {a["id"]: Decimal(a["balance"]) for a in r.json()["accounts"]}


def test_dashboard_serves_northwind_figures_with_region_header(accounts):
    r = accounts.get("/dashboard", headers=as_user("priya"))
    assert r.status_code == 200
    assert r.headers["X-Served-From"] == "local"
    body = r.json()
    assert body["company"]["name"] == "Northwind Logistics LLC"
    assert (body["total_cash"], body["available"], body["forecast_low"]) == ("5800000.00", "1780000.00", "-120000.00")
    assert body["payroll_due"] == {"date": "2026-10-08", "amount": "1900000.00"}
    assert len(body["trend"]) == 90
    assert body["trend"][-1]["non_reserve"] == "3560000.00"  # the forecast's basis: excl. Reserve
    assert [a["counterparty"] for a in body["anomalies"]] == ["Harbour Freight Co"]
    assert body["operational"]["available"] == "1780000.00"


def test_region_header_on_every_response(accounts, payments, monkeypatch):
    monkeypatch.setenv("REGION", "westus3")
    for client, path, headers in [(accounts, "/healthz", {}), (accounts, "/me", {}),  # 401 too
                                  (payments, "/beneficiaries", as_user("tom")), (payments, "/payments/999999", as_user("tom"))]:
        assert client.get(path, headers=headers).headers["X-Served-From"] == "westus3"


def test_create_payment_awaits_approval_and_leaves_balances(accounts, payments):
    before = balances(accounts)
    p = create_topup(payments)
    assert p["status"] == "AWAITING_APPROVAL"
    assert p["awaiting_approval_from"] == ["Tom Okafor"]
    assert balances(accounts) == before


def test_approve_executes_in_one_transaction(accounts, payments, db):
    p = create_topup(payments)
    r = payments.post(f"/payments/{p['id']}/approve", headers=as_user("tom"))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "EXECUTED"
    after = balances(accounts)
    assert after[RESERVE] == Decimal("1790000.00") and after[OPERATING] == Decimal("3310000.00")
    with db.connect() as conn:
        txns = conn.execute(select(t.transactions).where(t.transactions.c.payment_id == p["id"])).mappings().all()
        events = conn.execute(select(t.outbox.c.event_type).where(t.outbox.c.aggregate_id.in_(
            [str(p["id"])] + [str(x["id"]) for x in txns]))).scalars().all()
    assert sorted(x["amount"] for x in txns) == [Decimal("-450000.00"), Decimal("450000.00")]
    assert sorted(events) == ["payment.executed", "transaction.posted", "transaction.posted"]
    dash = accounts.get("/dashboard", headers=as_user("priya")).json()
    assert dash["operational"]["available"] == "2230000.00"  # serving figures refresh in piece 3
    assert dash["total_cash"] == "5800000.00"


def test_self_approval_refused(accounts, payments, db):
    p = create_topup(payments)
    r = payments.post(f"/payments/{p['id']}/approve", headers=as_user("priya"))
    assert r.status_code == 403
    assert r.json()["detail"] == "You can't approve a payment you created."
    assert payments.get(f"/payments/{p['id']}", headers=as_user("priya")).json()["status"] == "AWAITING_APPROVAL"


def test_cross_company_access_is_404_and_logged(accounts, payments, db):
    p = create_topup(payments)
    assert accounts.get(f"/accounts/{OPERATING}/transactions", headers=as_user("omar")).status_code == 404
    assert payments.get(f"/payments/{p['id']}", headers=as_user("omar")).status_code == 404
    assert payments.post(f"/payments/{p['id']}/approve", headers=as_user("layla")).status_code == 404
    # Company comes from identity: a Fabrikam user cannot spend from a Northwind account either.
    r = payments.post("/payments", headers=as_user("omar"), json={
        "from_account_id": OPERATING, "to_account_id": FABRIKAM_ACCOUNT, "amount": "1.00"})
    assert r.status_code == 404
    with db.connect() as conn:
        log = conn.execute(select(t.access_log)).mappings().all()
    assert [(e["username"], e["action"], e["target_type"], e["target_id"]) for e in log] == [
        ("omar", "access_denied", "account", str(OPERATING)),
        ("omar", "access_denied", "payment", str(p["id"])),
        ("layla", "access_denied", "payment", str(p["id"])),
        ("omar", "access_denied", "account", str(OPERATING)),
    ]
    assert payments.get(f"/payments/{p['id']}", headers=as_user("priya")).json()["status"] == "AWAITING_APPROVAL"


def test_concurrent_approvals_execute_exactly_once(accounts, payments):
    p = create_topup(payments)
    barrier, codes = threading.Barrier(2), []

    def approve():
        barrier.wait()
        codes.append(payments.post(f"/payments/{p['id']}/approve", headers=as_user("tom")).status_code)

    threads = [threading.Thread(target=approve) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert sorted(codes) == [200, 409]
    assert balances(accounts)[RESERVE] == Decimal("1790000.00")


def test_insufficient_funds_leaves_payment_awaiting(accounts, payments):
    p = create_topup(payments, amount="2240000.01")
    r = payments.post(f"/payments/{p['id']}/approve", headers=as_user("tom"))
    assert r.status_code == 409
    assert payments.get(f"/payments/{p['id']}", headers=as_user("tom")).json()["status"] == "AWAITING_APPROVAL"
    assert balances(accounts)[RESERVE] == Decimal("2240000.00")


def test_reject_writes_outbox_without_ledger_change(accounts, payments, db):
    before = balances(accounts)
    p = create_topup(payments)
    r = payments.post(f"/payments/{p['id']}/reject", headers=as_user("tom"))
    assert r.status_code == 200 and r.json()["status"] == "REJECTED"
    assert balances(accounts) == before
    with db.connect() as conn:
        events = conn.execute(select(t.outbox.c.event_type)).scalars().all()
        txns = conn.execute(select(t.transactions).where(t.transactions.c.payment_id == p["id"])).all()
    assert events == ["payment.rejected"] and txns == []


def test_workload_identity_url_signs_in_with_entra_token(monkeypatch):
    import struct
    import sys
    from unittest.mock import MagicMock

    import azure.identity

    from corp_common import db as corp_db

    class FakeCredential:
        def get_token(self, scope):
            assert scope == corp_db.SQL_TOKEN_SCOPE
            return type("Token", (), {"token": "tok"})()

    monkeypatch.setattr(azure.identity, "WorkloadIdentityCredential", FakeCredential)
    # No connection is opened, so a stub stands in for pyodbc (unixODBC may not be installed).
    monkeypatch.setitem(sys.modules, "pyodbc", MagicMock(version="5.1.0", paramstyle="qmark"))
    engine = corp_db.create_db_engine(
        "mssql+pyodbc://@sql.example:1433/corportal?driver=ODBC+Driver+18+for+SQL+Server"
        "&Authentication=ActiveDirectoryWorkloadIdentity"
    )
    assert "Authentication" not in engine.url.query  # ours, never passed to ODBC
    cparams, cargs = {}, ["DRIVER={ODBC Driver 18 for SQL Server};Server=sql.example;Trusted_Connection=Yes;Encrypt=yes"]
    for listener in engine.dialect.dispatch.do_connect:
        listener(engine.dialect, None, cargs, cparams)
    assert "Trusted_Connection" not in cargs[0] and "Encrypt=yes" in cargs[0]  # FA005 otherwise
    raw = "tok".encode("utf-16-le")
    assert cparams["attrs_before"] == {corp_db.SQL_COPT_SS_ACCESS_TOKEN: struct.pack("<I", len(raw)) + raw}


def test_entra_first_sign_in_links_by_email_once(accounts, monkeypatch):
    from corp_common import auth

    monkeypatch.setenv("AUTH_MODE", "entra")
    claims = {"oid": "oid-priya", "preferred_username": "Priya@Example.com"}
    monkeypatch.setattr(auth, "_claims_from_bearer", lambda request: claims)
    r = accounts.get("/me")
    assert r.status_code == 200 and r.json()["username"] == "priya"  # linked on first sign-in
    claims = {"oid": "oid-priya"}  # later: the oid alone is enough
    assert accounts.get("/me").json()["username"] == "priya"
    claims = {"oid": "oid-impostor", "preferred_username": "priya@example.com"}
    assert accounts.get("/me").status_code == 401  # an already-linked user is never re-linked
