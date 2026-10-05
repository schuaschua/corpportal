import re
from datetime import date, timedelta
from decimal import Decimal

from conftest import AS_OF, dataset, generator


def test_same_seed_same_output_different_seed_differs():
    a = generator.generate(42, AS_OF)
    b = generator.generate(42, AS_OF)
    assert generator.digest(a) == generator.digest(b)
    assert generator.digest(generator.generate(43, AS_OF)) != generator.digest(a)


def test_northwind_figures_and_planted_anomalies():
    data = dataset()
    assert len(data["companies"]) == 8
    assert all(c["name"].endswith(" LLC") for c in data["companies"])
    nw = next(c for c in data["companies"] if c["name"] == "Northwind Logistics LLC")
    balances = {a["kind"]: a["balance"] for a in data["accounts"] if a["company_id"] == nw["id"]}
    assert balances == {"operating": Decimal("2860000.00"), "reserve": Decimal("2240000.00"),
                        "payroll": Decimal("150000.00"), "collections": Decimal("550000.00")}
    assert all(re.fullmatch(r"AE07 0331 0000 \d{4} \d{4} 00\d", a["iban"]) for a in data["accounts"])

    sched = sum(s["amount"] for s in data["scheduled_payments"] if s["company_id"] == nw["id"]
                and s["kind"] == "supplier" and s["due_date"] < AS_OF + timedelta(days=7))
    assert sched == Decimal("1780000.00")

    pos = [p for p in data["cash_position"] if p["company_id"] == nw["id"]]
    assert len(pos) == 90 and pos[-1]["as_of_date"] == AS_OF
    latest = pos[-1]
    assert latest["total_cash"] == Decimal("5800000.00")
    assert latest["available"] == Decimal("1780000.00")
    assert latest["payroll_due_amount"] == Decimal("1900000.00")
    assert latest["payroll_due_date"] == date(2026, 10, 8)  # Thursday, 3 days after Monday as-of
    assert latest["forecast_low"] == Decimal("-120000.00")

    # Ledger history ends exactly at the account balances.
    for acct in data["accounts"]:
        txns = [t for t in data["transactions"] if t["account_id"] == acct["id"]]
        assert txns[-1]["balance_after"] == acct["balance"]

    anomalies = data["anomalies"]
    assert len(anomalies) == 3
    by_id = {p["id"]: p for p in data["payments"]}
    spike = next(a for a in anomalies if a["company_id"] == nw["id"])
    assert spike["counterparty"] == "Harbour Freight Co"
    assert (spike["occurred_at"] + generator.GST).date() == AS_OF - timedelta(days=2)
    prior = [p["amount"] for p in data["payments"] if p["beneficiary_id"] == by_id[spike["payment_id"]]["beneficiary_id"]
             and p["id"] != spike["payment_id"]]
    assert spike["amount"] == generator.money(sum(prior) / len(prior) * 4)
    dup = next(a for a in anomalies if "duplicate" in a["reason"])
    twins = [p for p in data["payments"] if p["company_id"] == dup["company_id"] and p["amount"] == dup["amount"]
             and p["value_date"] == by_id[dup["payment_id"]]["value_date"]]
    assert len(twins) == 2
    weekend = next(a for a in anomalies if "first-time" in a["reason"])
    local = weekend["occurred_at"] + generator.GST
    assert local.weekday() == 5 and local.hour == 2
    ben_id = by_id[weekend["payment_id"]]["beneficiary_id"]
    assert [p["id"] for p in data["payments"] if p["beneficiary_id"] == ben_id] == [weekend["payment_id"]]
