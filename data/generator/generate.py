"""Deterministic synthetic data generator for the Corporate Portal PoC (CAP-9).

Builds 8 UAE LLCs with AED accounts, 90 days of ledger history (payroll cycles,
suppliers, customer inflows with seasonality), upcoming scheduled payments, 3 planted
anomalies, and seeds the `serving` tables so the portal works before the lake exists. The
seeded forecast and anomaly rows are placeholders (`seed-0`); the first ML scoring run
(databricks/src/corp_pipelines/ml) replaces them.

Northwind Logistics LLC is calibrated to the demo story (as of the start of --as-of):
  Operating 2,860,000 / Reserve 2,240,000 / Payroll 150,000 / Collections 550,000
  supplier payments due in the next 7 days 1,780,000 -> available 1,780,000
  payroll 1,900,000 due the first Thursday at least 3 days after as-of -> forecast low -120,000

All timestamps are stored in UTC; the business day is Gulf Standard Time (UTC+4).
Same --seed and --as-of always produce identical output.

Usage:
  python data/generator/generate.py --seed 42 --as-of 2026-10-05              # summary + digest
  python data/generator/generate.py --seed 42 --as-of 2026-10-05 --load       # load into DB_URL
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

HISTORY_DAYS = 90
GST = timedelta(hours=4)  # Gulf Standard Time offset, no DST
CENT = Decimal("0.01")
ZERO = Decimal("0.00")

NORTHWIND = {
    "operating": Decimal("2860000.00"),
    "reserve": Decimal("2240000.00"),
    "payroll": Decimal("150000.00"),
    "collections": Decimal("550000.00"),
    "scheduled_7d": Decimal("1780000.00"),
    "payroll_amount": Decimal("1900000.00"),
}

ACCOUNT_KINDS = [("operating", "Operating"), ("reserve", "Reserve"), ("payroll", "Payroll"), ("collections", "Collections")]

COMPANIES = [
    {"name": "Northwind Logistics LLC", "emirate": "Dubai", "industry": "Logistics",
     "users": [("priya", "Priya Nair", "Treasurer", "initiator"), ("tom", "Tom Okafor", "CFO", "approver")],
     # Demo sign-in: the Entra users priya@example.com / tom@example.com link by email (infra/entra).
     "emails": {"priya": "priya@example.com", "tom": "tom@example.com"},
     "suppliers": [("Harbour Freight Co", 62000, 7), ("Gulf Fuel Supplies LLC", 380000, 7),
                   ("Jebel Ali Warehousing LLC", 310000, 14), ("Emirates Tyre Trading LLC", 85000, 14),
                   ("Al Quoz Fleet Services LLC", 140000, 7), ("Desert Line Maintenance LLC", 95000, 7),
                   ("Falcon Customs Brokerage LLC", 260000, 7)],
     "customers": ["Blue Dune Retail LLC", "Marina Home Furnishings LLC", "Al Futtaim Traders LLC",
                   "Crescent Electronics LLC", "Palm Grocers LLC", "Oasis Pharma Distribution LLC",
                   "Saffron Foods LLC", "Creek Building Materials LLC"]},
    {"name": "Fabrikam Trading LLC", "emirate": "Abu Dhabi", "industry": "General trading",
     "users": [("omar", "Omar Haddad", "Finance Manager", "initiator"), ("layla", "Layla Mansour", "CFO", "approver")]},
    {"name": "Litware Technologies LLC", "emirate": "Dubai", "industry": "IT services",
     "users": [("aisha", "Aisha Rahman", "Treasurer", "initiator"), ("daniel", "Daniel Fischer", "CFO", "approver")]},
    {"name": "Adatum Healthcare LLC", "emirate": "Sharjah", "industry": "Healthcare",
     "users": [("fatima", "Fatima Al Suwaidi", "Treasurer", "initiator"), ("rahul", "Rahul Menon", "CFO", "approver")]},
    {"name": "Woodgrove Hospitality LLC", "emirate": "Dubai", "industry": "Hospitality",
     "users": [("sara", "Sara Costa", "Finance Manager", "initiator"), ("khalid", "Khalid Al Nuaimi", "CFO", "approver")]},
    {"name": "Proseware Retail LLC", "emirate": "Ajman", "industry": "Retail",
     "users": [("mei", "Mei Lin", "Treasurer", "initiator"), ("yusuf", "Yusuf Qasim", "CFO", "approver")]},
    {"name": "Wingtip Marine Services LLC", "emirate": "Fujairah", "industry": "Marine services",
     "users": [("anna", "Anna Kowalski", "Treasurer", "initiator"), ("hamdan", "Hamdan Al Ketbi", "CFO", "approver")]},
    {"name": "Lamna Engineering LLC", "emirate": "Ras Al Khaimah", "industry": "Engineering",
     "users": [("vikram", "Vikram Iyer", "Treasurer", "initiator"), ("noura", "Noura Al Hashimi", "CFO", "approver")]},
]

SUPPLIER_POOL = [
    "Emirates Office Supplies LLC", "Al Noor Facilities Management LLC", "Sharjah Packaging Industries LLC",
    "Gulf Telecom Services LLC", "Dubai Cleaning Co LLC", "Arabian Security Services LLC",
    "Horizon IT Solutions LLC", "Pearl Catering LLC", "Najm Transport LLC", "Silverline Printing LLC",
    "Al Wasl Electrical Contracting LLC", "Mirdif Water Supplies LLC", "Coral Insurance Brokers LLC",
    "Summit Engineering Supplies LLC", "Zayed Port Logistics LLC", "Barsha Legal Consultants LLC",
]
CUSTOMER_POOL = [
    "Sunrise Retail LLC", "Al Mamzar Trading LLC", "Golden Sands Hotels LLC", "Hatta Holdings LLC",
    "Nakheel Contracting LLC", "Emerald Clinics LLC", "Seef Distribution LLC", "Qasr Events LLC",
    "Meydan Motors LLC", "Karama Wholesale LLC", "Yas Leisure LLC", "Deira Imports LLC",
    "Al Barari Developments LLC", "Mushrif Schools LLC", "Ruwais Energy Services LLC",
]

# Planted anomalies (CAP-8): which company carries which.
ANOMALY_SPIKE = 1        # Northwind: Harbour Freight Co at 4x its average, 2 days before as-of
ANOMALY_DUPLICATE = 3    # Litware: same supplier, same amount, same day
ANOMALY_WEEKEND = 5      # Woodgrove: Saturday 02:00 (GST) to a first-time beneficiary


def money(x) -> Decimal:
    return Decimal(str(x)).quantize(CENT, rounding=ROUND_HALF_UP)


def to_utc(local: datetime) -> datetime:
    return local - GST


def at(d: date, hh: int, mm: int = 0) -> datetime:
    """A Gulf-local wall clock time on day d, as naive UTC."""
    return to_utc(datetime.combine(d, time(hh, mm)))


def business_day(d: date) -> date:
    while d.weekday() >= 5:  # UAE weekend is Saturday/Sunday
        d += timedelta(days=1)
    return d


def next_payroll_date(as_of: date) -> date:
    """First Thursday at least 3 days after as-of."""
    d = as_of + timedelta(days=3)
    while d.weekday() != 3:
        d += timedelta(days=1)
    return d


def iban(company_id: int, account_no: int, n: int) -> str:
    # AE07 0331 0000 xxxx xxxx 00n
    return f"AE07 0331 0000 {company_id:04d} {account_no:04d} 00{n}"


def external_iban(rng: random.Random) -> str:
    bank = rng.choice(["0260", "0330", "0350", "0400", "0460"])
    digits = f"{rng.randrange(10**12):012d}"
    return f"AE{rng.randrange(10, 99)} {bank} {digits[:4]} {digits[4:8]} {digits[8:12]} {rng.randrange(1000):03d}"


class Company:
    def __init__(self, cid: int, spec: dict, rng: random.Random, as_of: date):
        self.id, self.spec, self.rng, self.as_of = cid, spec, rng, as_of
        self.start = as_of - timedelta(days=HISTORY_DAYS)
        self.events: list[dict] = []    # ledger entries (account kind, booked_at, amount, ...)
        self.payments: list[dict] = []  # executed supplier payments, local ids
        self.beneficiaries: list[dict] = []
        self.scheduled: list[dict] = []
        self.anomalies: list[dict] = []

    # ---------------------------------------------------------------- setup
    def setup(self):
        rng = self.rng
        if self.id == 1:
            self.targets = {k: NORTHWIND[k] for k in ("operating", "reserve", "payroll", "collections")}
            self.payroll_amount = NORTHWIND["payroll_amount"]
            suppliers = self.spec["suppliers"]
            self.customers = self.spec["customers"]
            self.next_payroll = next_payroll_date(self.as_of)
        else:
            scale = rng.uniform(0.35, 2.2)
            r = lambda lo, hi: money(round(scale * rng.uniform(lo, hi), -4))  # noqa: E731
            self.targets = {"operating": r(1.4e6, 3.2e6), "reserve": r(0.8e6, 3.0e6),
                            "payroll": r(0.05e6, 0.3e6), "collections": r(0.2e6, 0.8e6)}
            self.payroll_amount = r(0.6e6, 1.6e6)
            names = rng.sample(SUPPLIER_POOL, 6)
            suppliers = [(n, round(scale * rng.uniform(40000, 260000), -3), rng.choice([7, 7, 14])) for n in names]
            self.customers = rng.sample(CUSTOMER_POOL, 8)
            self.next_payroll = self.as_of + timedelta(days=rng.randint(4, 24))
        self.suppliers = []
        for name, typical, cadence in suppliers:
            ben = {"name": name, "iban": external_iban(rng), "category": "supplier",
                   "created_at": at(self.start - timedelta(days=rng.randint(30, 400)), 10)}
            self.beneficiaries.append(ben)
            self.suppliers.append({"ben": ben, "typical": typical, "cadence": cadence})

    # ---------------------------------------------------------------- history
    def event(self, kind, booked_at, amount, category, counterparty, description, payment=None):
        self.events.append({"kind": kind, "booked_at": booked_at, "amount": money(amount), "category": category,
                            "counterparty": counterparty, "description": description, "payment": payment,
                            "seq": len(self.events)})

    def supplier_payment(self, sup, booked_at, amount, reference, created_at=None):
        rng = self.rng
        pay = {"ben": sup["ben"], "amount": money(amount), "reference": reference,
               "created_at": created_at or booked_at - timedelta(hours=rng.randint(2, 30)), "executed_at": booked_at,
               "value_date": (booked_at + GST).date(), "seq": len(self.payments)}
        self.payments.append(pay)
        self.event("operating", booked_at, -pay["amount"], "supplier", sup["ben"]["name"], reference, pay)
        return pay

    def seasonality(self, d: date, i: int) -> float:
        weekday = [1.25, 1.1, 1.0, 1.05, 0.85, 0.12, 0.08][d.weekday()]
        month_end = 1.45 if d.day >= 26 or d.day <= 2 else 1.0
        trend = 1.0 + 0.12 * i / HISTORY_DAYS
        return weekday * month_end * trend

    def history(self):
        rng, start, as_of = self.rng, self.start, self.as_of
        days = [start + timedelta(days=i) for i in range(HISTORY_DAYS)]

        # Supplier payments from Operating.
        for sup in self.suppliers:
            d = start + timedelta(days=rng.randrange(sup["cadence"]))
            while True:
                pay_day = business_day(d)
                if pay_day >= as_of:
                    break
                i = (pay_day - start).days
                amount = sup["typical"] * math.exp(rng.gauss(0, 0.12)) * (0.9 + 0.2 * self.seasonality(pay_day, i) / 1.3)
                self.supplier_payment(sup, at(pay_day, rng.randint(9, 14), rng.randrange(60)),
                                      round(amount, -1), f"INV-{rng.randrange(10000, 99999)}")
                d += timedelta(days=sup["cadence"])

        # Payroll every 4 weeks: funding transfer the day before, WPS salary run on the day.
        pd = self.next_payroll - timedelta(days=28)
        while pd - timedelta(days=1) >= start:
            if pd < as_of:
                amount = self.payroll_amount if self.id == 1 else money(float(self.payroll_amount) * rng.uniform(0.97, 1.03))
                label = f"Payroll {pd:%d %b %Y}"
                self.event("operating", at(pd - timedelta(days=1), 16), -amount, "transfer", "Payroll account", f"Funding {label}")
                self.event("payroll", at(pd - timedelta(days=1), 16), amount, "transfer", "Operating account", f"Funding {label}")
                self.event("payroll", at(pd, 8), -amount, "payroll", "WPS salary transfer", label)
            pd -= timedelta(days=28)

        # Monthly bank fee (Operating) and interest (Reserve).
        for d in days:
            if d.day == 1:
                self.event("operating", at(d, 6), -525, "fee", "Contoso Digital Bank", "Account maintenance fee")
                interest = float(self.targets["reserve"]) * 0.035 / 12 * rng.uniform(0.97, 1.03)
                self.event("reserve", at(d, 6), round(interest, 2), "interest", "Contoso Digital Bank", "Interest credit")

        self.plant_anomalies()

        # Customer inflows into Collections (swept to Operating the same evening), scaled so
        # Operating drifts down gently and never dips below a 10% cushion of its target.
        op_events = [(e["booked_at"], e["amount"]) for e in self.events if e["kind"] == "operating"]
        outflows = -sum(a for _, a in op_events)
        raw = []
        for i, d in enumerate(days):
            n = rng.randint(2, 6) if d.weekday() < 5 else rng.randint(0, 1)
            for _ in range(n):
                customer = rng.choice(self.customers)
                raw.append((d, rng.lognormvariate(0, 0.6) * self.seasonality(d, i), customer,
                            rng.randint(8, 17), rng.randrange(60),
                            f"Customer receipt {customer.split()[0].upper()}-{rng.randrange(1000, 9999)}"))
        wsum = sum(r[1] for r in raw)
        target_in = float(outflows) * rng.uniform(0.94, 0.98)
        cushion = self.targets["operating"] * Decimal("0.10")
        for _ in range(50):
            amounts = [money(round(r[1] * target_in / wsum, -1)) for r in raw]
            daily = defaultdict(Decimal)
            for r, amount in zip(raw, amounts):
                daily[r[0]] += amount
            path = sorted(op_events + [(at(d, 18), v) for d, v in daily.items()])
            bal = self.targets["operating"] - sum((a for _, a in path), ZERO)
            low = bal
            for _, a in path:
                bal += a
                low = min(low, bal)
            if low >= cushion:
                break
            target_in -= float(cushion - low) * 1.2
        for (d, _, customer, hh, mm, ref), amount in zip(raw, amounts):
            self.event("collections", at(d, hh, mm), amount, "customer", customer, ref)
        # End-of-day cash concentration sweep Collections -> Operating.
        for d in days:
            if daily[d] > 0:
                self.event("collections", at(d, 18), -daily[d], "transfer", "Operating account", "Daily sweep to Operating")
                self.event("operating", at(d, 18), daily[d], "transfer", "Collections account", "Daily sweep from Collections")

    def plant_anomalies(self):
        rng, as_of = self.rng, self.as_of
        if self.id == ANOMALY_SPIKE:
            sup = next(s for s in self.suppliers if s["ben"]["name"] == "Harbour Freight Co")
            prior = [p["amount"] for p in self.payments if p["ben"] is sup["ben"]]
            avg = sum(prior) / len(prior)
            pay = self.supplier_payment(sup, at(as_of - timedelta(days=2), 11, 20), money(avg * 4), "INV-HF-40417")
            self.anomalies.append({"payment": pay, "score": Decimal("0.9700"),
                                   "reason": "Unusual: 4× this supplier's average"})
        if self.id == ANOMALY_DUPLICATE:
            day = business_day(as_of - timedelta(days=19))
            sup = self.suppliers[0]
            amount = money(round(sup["typical"] * 1.07, -1))
            ref = f"INV-{rng.randrange(10000, 99999)}"
            first = self.supplier_payment(sup, at(day, 10, 5), amount, ref, created_at=at(day, 9, 12))
            dup = self.supplier_payment(sup, at(day, 10, 47), amount, ref, created_at=at(day, 9, 54))
            self.anomalies.append({"payment": dup, "score": Decimal("0.9100"), "first": first,
                                   "reason": "Possible duplicate: same supplier, amount and day as an earlier payment"})
        if self.id == ANOMALY_WEEKEND:
            day = as_of - timedelta(days=8)
            while day.weekday() != 5:  # most recent Saturday at least 8 days back
                day -= timedelta(days=1)
            booked = at(day, 2, 0)
            ben = {"name": "Swift Horizon General Trading LLC", "iban": external_iban(rng), "category": "supplier",
                   "created_at": booked - timedelta(minutes=18)}
            self.beneficiaries.append(ben)
            pay = self.supplier_payment({"ben": ben}, booked, money(round(float(self.targets["operating"]) * 0.11, -2)), "URGENT SETTLEMENT")
            self.anomalies.append({"payment": pay, "score": Decimal("0.9400"),
                                   "reason": "Unusual: Saturday 02:00 payment to a first-time beneficiary"})

    # ---------------------------------------------------------------- upcoming
    def upcoming(self):
        rng, as_of = self.rng, self.as_of
        picks = []
        for sup in self.suppliers:
            offset = rng.randrange(sup["cadence"])
            for d in (offset, offset + sup["cadence"]):
                if d < 14:
                    picks.append((business_day(as_of + timedelta(days=d)), sup, sup["typical"] * math.exp(rng.gauss(0, 0.1))))
        picks.sort(key=lambda p: (p[0], p[1]["ben"]["name"]))
        in7 = [p for p in picks if (p[0] - as_of).days < 7]
        later = [p for p in picks if (p[0] - as_of).days >= 7]
        if self.id == 1:
            # Calibrate the next 7 days to exactly 1,780,000 in round thousands.
            k = float(NORTHWIND["scheduled_7d"]) / sum(a for *_, a in in7)
            amounts = [money(round(a * k, -3)) for *_, a in in7]
            amounts[-1] += NORTHWIND["scheduled_7d"] - sum(amounts)
        else:
            amounts = [money(round(a, -3)) for *_, a in in7]
        amounts += [money(round(a, -3)) for *_, a in later]
        for (d, sup, _), amount in zip(in7 + later, amounts):
            self.scheduled.append({"kind": "supplier", "ben": sup["ben"], "account": "operating", "amount": amount,
                                   "due_date": d, "description": f"{sup['ben']['name']} scheduled payment"})
        self.scheduled.append({"kind": "payroll", "ben": None, "account": "payroll", "amount": self.payroll_amount,
                               "due_date": self.next_payroll, "description": f"Payroll {self.next_payroll:%d %b %Y}"})


def generate(seed: int = 42, as_of: date | None = None) -> dict[str, list[dict]]:
    """Return every table's rows. Pure function of (seed, as_of)."""
    as_of = as_of or date.today()
    rng = random.Random(seed)
    companies = []
    for cid, spec in enumerate(COMPANIES, start=1):
        c = Company(cid, spec, random.Random(rng.getrandbits(64)), as_of)
        c.setup()
        c.history()
        c.upcoming()
        companies.append(c)

    out: dict[str, list[dict]] = defaultdict(list)
    snapshot_at = at(as_of, 3)
    user_id = ben_id = acct_id = sched_id = 0
    for c in companies:
        c.user_ids = {}
        out["companies"].append({"id": c.id, "name": c.spec["name"], "trade_licence": f"CN-{1000000 + c.id * 7919:07d}",
                                 "emirate": c.spec["emirate"], "industry": c.spec["industry"]})
        for username, display, title, role in c.spec["users"]:
            user_id += 1
            c.user_ids[role] = user_id
            out["users"].append({"id": user_id, "company_id": c.id, "username": username, "display_name": display,
                                 "title": title, "role": role, "email": c.spec.get("emails", {}).get(username, f"{username}@{c.spec['name'].split()[0].lower()}.example"),
                                 "entra_oid": None})
        c.account_ids = {}
        for n, (kind, label) in enumerate(ACCOUNT_KINDS, start=1):
            acct_id += 1
            c.account_ids[kind] = acct_id
            out["accounts"].append({"id": acct_id, "company_id": c.id, "name": label, "kind": kind,
                                    "iban": iban(c.id, 1000 + c.id * 10 + n, n), "currency": "AED",
                                    "balance": c.targets[kind], "updated_at": snapshot_at})
        for ben in c.beneficiaries:
            ben_id += 1
            ben["id"] = ben_id
            out["beneficiaries"].append({"id": ben_id, "company_id": c.id, "name": ben["name"], "iban": ben["iban"],
                                         "category": ben["category"], "created_at": ben["created_at"]})
        for s in c.scheduled:
            sched_id += 1
            out["scheduled_payments"].append({"id": sched_id, "company_id": c.id, "from_account_id": c.account_ids[s["account"]],
                                              "beneficiary_id": s["ben"]["id"] if s["ben"] else None, "kind": s["kind"],
                                              "amount": s["amount"], "due_date": s["due_date"], "description": s["description"]})

    # Payments: global ids in creation order.
    all_pay = sorted(((p["created_at"], c.id, p["seq"], c, p) for c in companies for p in c.payments), key=lambda x: x[:3])
    for pid, (*_, c, p) in enumerate(all_pay, start=1):
        p["id"] = pid
        out["payments"].append({"id": pid, "company_id": c.id, "from_account_id": c.account_ids["operating"],
                                "to_account_id": None, "beneficiary_id": p["ben"]["id"], "amount": p["amount"],
                                "currency": "AED", "value_date": p["value_date"], "reference": p["reference"],
                                "status": "EXECUTED", "created_by": c.user_ids["initiator"], "created_at": p["created_at"],
                                "decided_by": c.user_ids["approver"], "decided_at": p["executed_at"] - timedelta(minutes=5),
                                "executed_at": p["executed_at"]})

    # Ledger: opening balance per account so the history ends exactly at the target balance.
    all_ev = sorted(((e["booked_at"], c.id, e["seq"], c, e) for c in companies for e in c.events), key=lambda x: x[:3])
    running = {}
    for c in companies:
        for kind in c.targets:
            net = sum((e["amount"] for e in c.events if e["kind"] == kind), ZERO)
            running[(c.id, kind)] = c.targets[kind] - net
        c.opening = {kind: running[(c.id, kind)] for kind in c.targets}
    c_min = defaultdict(lambda: None)
    for tid, (*_, c, e) in enumerate(all_ev, start=1):
        key = (c.id, e["kind"])
        running[key] += e["amount"]
        e["id"] = tid
        if c_min[key] is None or running[key] < c_min[key]:
            c_min[key] = running[key]
        out["transactions"].append({"id": tid, "company_id": c.id, "account_id": c.account_ids[e["kind"]],
                                    "payment_id": e["payment"]["id"] if e["payment"] else None,
                                    "booked_at": e["booked_at"], "value_date": (e["booked_at"] + GST).date(),
                                    "amount": e["amount"], "balance_after": running[key], "category": e["category"],
                                    "counterparty": e["counterparty"], "description": e["description"]})
    for key, low in c_min.items():
        if low is not None and low < 0:
            raise AssertionError(f"negative running balance {key}: {low}")

    anomaly_id = 0
    for c in companies:
        serving_rows(c, out, snapshot_at)
        for a in c.anomalies:
            anomaly_id += 1
            p = a["payment"]
            txn = next(e for e in c.events if e["payment"] is p)
            reason = a["reason"]
            if "first" in a:
                reason = f"{reason} (payment {a['first']['id']})"
            out["anomalies"].append({"id": anomaly_id, "company_id": c.id, "payment_id": p["id"], "transaction_id": txn["id"],
                                     "occurred_at": p["executed_at"], "counterparty": p["ben"]["name"], "amount": p["amount"],
                                     "score": a["score"], "reason": reason, "detected_at": p["executed_at"] + timedelta(minutes=15),
                                     "model_name": "payment-anomaly-baseline", "model_version": "seed-0"})
    return dict(out)


def serving_rows(c: Company, out: dict, snapshot_at: datetime) -> None:
    """Seed serving.cash_position (daily, 90 days to as-of) and serving.forecast (30 days)."""
    as_of = c.as_of
    # Start-of-day balances per account kind, from the opening balance forward.
    bal = dict(c.opening)
    by_day = defaultdict(list)
    for e in c.events:
        by_day[(e["booked_at"] + GST).date()].append(e)
    supplier_out = defaultdict(Decimal)  # local date -> supplier outflow (history + scheduled)
    for e in c.events:
        if e["category"] == "supplier":
            supplier_out[(e["booked_at"] + GST).date()] += -e["amount"]
    for s in c.scheduled:
        if s["kind"] == "supplier":
            supplier_out[s["due_date"]] += s["amount"]
    payroll_days = sorted({(e["booked_at"] + GST).date() for e in c.events if e["category"] == "payroll"} | {c.next_payroll})
    payroll_amt = {c.next_payroll: c.payroll_amount}
    for e in c.events:
        if e["category"] == "payroll":
            payroll_amt[(e["booked_at"] + GST).date()] = -e["amount"]

    for i in range(HISTORY_DAYS + 1):
        d = c.start + timedelta(days=i)
        if i:
            for e in by_day[d - timedelta(days=1)]:
                bal[e["kind"]] += e["amount"]
        if d < c.start + timedelta(days=1):
            continue  # 90 rows: start+1 .. as_of
        total = sum(bal.values(), ZERO)
        non_reserve = total - bal["reserve"]
        sched = sum((supplier_out[d + timedelta(days=k)] for k in range(7)), ZERO)
        available = non_reserve - sched
        due = next(p for p in payroll_days if p >= d)
        low = available - payroll_amt[due] if (due - d).days < 10 else available
        out["cash_position"].append({"company_id": c.id, "as_of_date": d, "total_cash": total, "available": available,
                                     "scheduled_out_7d": sched, "payroll_due_date": due, "payroll_due_amount": payroll_amt[due],
                                     "forecast_low": low, "refreshed_at": snapshot_at if d == as_of else at(d, 3)})
    assert all(bal[k] == c.targets[k] for k in bal), "serving balances out of step with ledger"

    # Baseline forecast of non-Reserve cash: known scheduled outflows and payroll, expected
    # receipts only from day 7 (not yet invoiced), historic supplier run-rate beyond day 14.
    receipts = [e["amount"] for e in c.events if e["category"] == "customer"]
    daily_in = sum(receipts, ZERO) / HISTORY_DAYS
    hist_sup = sum((v for k, v in supplier_out.items() if k < as_of), ZERO) / HISTORY_DAYS
    balance = sum(c.targets.values(), ZERO) - c.targets["reserve"]
    for k in range(30):
        d = as_of + timedelta(days=k)
        balance -= supplier_out[d] if k < 14 else hist_sup
        if (d - c.next_payroll).days % 28 == 0 and d >= c.next_payroll:
            balance -= c.payroll_amount
        if k >= 7:
            balance += daily_in * Decimal(7) / Decimal(5) if d.weekday() < 5 else ZERO
        band = abs(balance) * Decimal("0.03") + Decimal(k) * Decimal("0.004") * sum(c.targets.values(), ZERO)
        out["forecast"].append({"company_id": c.id, "forecast_date": d, "predicted_balance": money(balance),
                                "lower_bound": money(balance - band), "upper_bound": money(balance + band),
                                "model_name": "cash-forecast-baseline", "model_version": "seed-0", "generated_at": snapshot_at})


# ------------------------------------------------------------------ output


def digest(data: dict) -> str:
    blob = json.dumps(data, default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


LOAD_ORDER = ["companies", "users", "accounts", "beneficiaries", "payments", "transactions", "scheduled_payments",
              "cash_position", "forecast", "anomalies"]


def load(engine, data: dict) -> None:
    """Insert every table (schema must already exist and be empty)."""
    from corp_common import tables as t

    with engine.begin() as conn:
        for name in LOAD_ORDER:
            rows = data.get(name, [])
            for i in range(0, len(rows), 1000):
                conn.execute(getattr(t, name).insert(), rows[i:i + 1000])


def summary(data: dict) -> dict:
    nw_accounts = {a["name"]: str(a["balance"]) for a in data["accounts"] if a["company_id"] == 1}
    nw_pos = [p for p in data["cash_position"] if p["company_id"] == 1][-1]
    return {
        "rows": {k: len(v) for k, v in data.items()},
        "northwind": {"accounts": nw_accounts, **{k: str(v) for k, v in nw_pos.items() if k != "company_id"}},
        "anomalies": [{"company_id": a["company_id"], "payment_id": a["payment_id"], "reason": a["reason"]} for a in data["anomalies"]],
        "digest": digest(data),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--as-of", type=date.fromisoformat, default=None,
                    help="business date the data ends at (default: today in Gulf Standard Time)")
    ap.add_argument("--load", action="store_true", help="insert into the database at DB_URL")
    ap.add_argument("--json", help="also write the full dataset to this JSON file")
    args = ap.parse_args(argv)
    as_of = args.as_of or (datetime.now(timezone.utc) + GST).date()
    data = generate(args.seed, as_of)
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(data, fh, default=str, sort_keys=True, indent=1)
    if args.load:
        from corp_common.db import get_engine

        load(get_engine(), data)
    print(json.dumps({"seed": args.seed, "as_of": as_of.isoformat(), **summary(data)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
