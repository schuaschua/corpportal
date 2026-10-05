"""payments-api: payment creation and the two-person approval state machine (CAP-4).

    AWAITING_APPROVAL --approve (another approver, funds ok)--> EXECUTED
    AWAITING_APPROVAL --reject  (another user)-----------------> REJECTED

Approval is one DB transaction: a conditional UPDATE ... WHERE status='AWAITING_APPROVAL'
claims the payment (so of two concurrent approvals exactly one wins), then a conditional
debit (balance >= amount), the credit, the ledger rows and the outbox rows. Any failure
rolls the whole thing back.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, select, update

from corp_common import tables as t
from corp_common.app_factory import create_app
from corp_common.auth import User, current_user
from corp_common.db import company_connection
from corp_common.scoping import Denied, money, utcnow

app = create_app("payments-api")

AWAITING, EXECUTED, REJECTED = "AWAITING_APPROVAL", "EXECUTED", "REJECTED"

Money = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=2)]


class PaymentIn(BaseModel):
    from_account_id: int
    to_account_id: int | None = None
    beneficiary_id: int | None = None
    amount: Money
    value_date: date | None = None
    reference: str | None = Field(default=None, max_length=140)

    @model_validator(mode="after")
    def _one_destination(self):
        if (self.to_account_id is None) == (self.beneficiary_id is None):
            raise ValueError("Choose either a destination account or a beneficiary.")
        if self.to_account_id is not None and self.to_account_id == self.from_account_id:
            raise ValueError("The from and to accounts must be different.")
        return self


# ------------------------------------------------------------------ queries

creator = t.users.alias("creator")
decider = t.users.alias("decider")
from_acct = t.accounts.alias("from_acct")
to_acct = t.accounts.alias("to_acct")


def _payment_query(company_id: int):
    p = t.payments
    return (
        select(
            p,
            creator.c.display_name.label("created_by_name"),
            decider.c.display_name.label("decided_by_name"),
            from_acct.c.name.label("from_account_name"),
            to_acct.c.name.label("to_account_name"),
            t.beneficiaries.c.name.label("beneficiary_name"),
            t.anomalies.c.score.label("anomaly_score"),
            t.anomalies.c.reason.label("anomaly_reason"),
        )
        .select_from(
            p.join(creator, creator.c.id == p.c.created_by)
            .outerjoin(decider, decider.c.id == p.c.decided_by)
            .join(from_acct, from_acct.c.id == p.c.from_account_id)
            .outerjoin(to_acct, to_acct.c.id == p.c.to_account_id)
            .outerjoin(t.beneficiaries, t.beneficiaries.c.id == p.c.beneficiary_id)
            .outerjoin(
                t.anomalies,
                and_(t.anomalies.c.payment_id == p.c.id, t.anomalies.c.company_id == p.c.company_id),
            )
        )
        .where(p.c.company_id == company_id)
    )


def _approvers(conn, company_id: int) -> list[dict]:
    rows = conn.execute(
        select(t.users.c.id, t.users.c.display_name).where(
            and_(t.users.c.company_id == company_id, t.users.c.role == "approver")
        ).order_by(t.users.c.id)
    ).mappings().all()
    return [dict(r) for r in rows]


def _serialize(row, approvers: list[dict]) -> dict:
    iso = lambda v: v.isoformat() if v is not None else None  # noqa: E731
    return {
        "id": row["id"],
        "status": row["status"],
        "amount": money(row["amount"]),
        "currency": row["currency"],
        "value_date": iso(row["value_date"]),
        "reference": row["reference"],
        "from_account": {"id": row["from_account_id"], "name": row["from_account_name"]},
        "to_account": (
            {"id": row["to_account_id"], "name": row["to_account_name"]} if row["to_account_id"] else None
        ),
        "beneficiary": (
            {"id": row["beneficiary_id"], "name": row["beneficiary_name"]} if row["beneficiary_id"] else None
        ),
        "created_by": {"id": row["created_by"], "name": row["created_by_name"]},
        "created_at": iso(row["created_at"]),
        "decided_by": {"id": row["decided_by"], "name": row["decided_by_name"]} if row["decided_by"] else None,
        "decided_at": iso(row["decided_at"]),
        "executed_at": iso(row["executed_at"]),
        "awaiting_approval_from": (
            [a["display_name"] for a in approvers if a["id"] != row["created_by"]]
            if row["status"] == AWAITING
            else []
        ),
        "anomaly": (
            {"score": str(row["anomaly_score"]), "reason": row["anomaly_reason"]}
            if row["anomaly_reason"] is not None
            else None
        ),
    }


def _load(conn, user: User, payment_id: int) -> dict:
    row = conn.execute(_payment_query(user.company_id).where(t.payments.c.id == payment_id)).mappings().first()
    if row is None:
        raise Denied(user, "payment", payment_id)
    return _serialize(row, _approvers(conn, user.company_id))


def _owned(conn, table, user: User, obj_id: int, target_type: str):
    row = conn.execute(
        select(table).where(and_(table.c.id == obj_id, table.c.company_id == user.company_id))
    ).mappings().first()
    if row is None:
        raise Denied(user, target_type, obj_id)
    return row


def _outbox(conn, company_id: int, aggregate_type: str, aggregate_id, event_type: str, payload: dict, now):
    conn.execute(
        t.outbox.insert().values(
            company_id=company_id,
            aggregate_type=aggregate_type,
            aggregate_id=str(aggregate_id),
            event_type=event_type,
            payload=json.dumps(payload, default=str, sort_keys=True),
            created_at=now,
        )
    )


# ------------------------------------------------------------------ endpoints


@app.get("/beneficiaries")
def list_beneficiaries(user: User = Depends(current_user)):
    with company_connection(user.company_id) as conn:
        rows = conn.execute(
            select(t.beneficiaries)
            .where(t.beneficiaries.c.company_id == user.company_id)
            .order_by(t.beneficiaries.c.name)
        ).mappings().all()
    return {
        "beneficiaries": [
            {"id": r["id"], "name": r["name"], "iban": r["iban"], "category": r["category"]} for r in rows
        ]
    }


@app.get("/payments")
def list_payments(
    status: str | None = Query(None, pattern=f"^({AWAITING}|{EXECUTED}|{REJECTED})$"),
    limit: int = Query(200, ge=1, le=1000),
    user: User = Depends(current_user),
):
    q = _payment_query(user.company_id)
    if status:
        q = q.where(t.payments.c.status == status)
    q = q.order_by(t.payments.c.created_at.desc(), t.payments.c.id.desc()).limit(limit)
    with company_connection(user.company_id) as conn:
        rows = conn.execute(q).mappings().all()
        approvers = _approvers(conn, user.company_id)
    return {"payments": [_serialize(r, approvers) for r in rows]}


@app.get("/payments/{payment_id}")
def get_payment(payment_id: int, user: User = Depends(current_user)):
    with company_connection(user.company_id) as conn:
        return _load(conn, user, payment_id)


@app.post("/payments", status_code=201)
def create_payment(body: PaymentIn, user: User = Depends(current_user)):
    now = utcnow()
    with company_connection(user.company_id) as conn:
        _owned(conn, t.accounts, user, body.from_account_id, "account")
        if body.to_account_id is not None:
            _owned(conn, t.accounts, user, body.to_account_id, "account")
        if body.beneficiary_id is not None:
            _owned(conn, t.beneficiaries, user, body.beneficiary_id, "beneficiary")
        result = conn.execute(
            t.payments.insert().values(
                company_id=user.company_id,  # from identity, never from the body
                from_account_id=body.from_account_id,
                to_account_id=body.to_account_id,
                beneficiary_id=body.beneficiary_id,
                amount=body.amount,
                currency="AED",
                value_date=body.value_date or now.date(),
                reference=body.reference,
                status=AWAITING,
                created_by=user.id,
                created_at=now,
            )
        )
        return _load(conn, user, result.inserted_primary_key[0])


def _check_decider(payment, user: User, verb: str) -> None:
    if payment["created_by"] == user.id:
        raise HTTPException(403, f"You can't {verb} a payment you created.")
    if verb == "approve" and user.role != "approver":
        raise HTTPException(403, "Only an approver can approve payments.")
    if payment["status"] != AWAITING:
        raise HTTPException(409, f"This payment is already {payment['status'].lower()}.")


def _claim(conn, user: User, payment_id: int, new_status: str, now) -> None:
    values = {"status": new_status, "decided_by": user.id, "decided_at": now}
    if new_status == EXECUTED:
        values["executed_at"] = now
    claimed = conn.execute(
        update(t.payments)
        .where(
            and_(
                t.payments.c.id == payment_id,
                t.payments.c.company_id == user.company_id,
                t.payments.c.status == AWAITING,
            )
        )
        .values(**values)
    )
    if claimed.rowcount != 1:
        # Someone else decided it between our read and our update.
        raise HTTPException(409, "This payment has already been decided.")


def _post(conn, company_id, account_id, payment_id, amount: Decimal, category, counterparty, description, now):
    balance_after = conn.execute(
        select(t.accounts.c.balance).where(t.accounts.c.id == account_id)
    ).scalar_one()
    result = conn.execute(
        t.transactions.insert().values(
            company_id=company_id,
            account_id=account_id,
            payment_id=payment_id,
            booked_at=now,
            value_date=now.date(),
            amount=amount,
            balance_after=balance_after,
            category=category,
            counterparty=counterparty,
            description=description,
        )
    )
    return {
        "id": result.inserted_primary_key[0],
        "account_id": account_id,
        "amount": money(amount),
        "balance_after": money(balance_after),
        "category": category,
        "counterparty": counterparty,
        "booked_at": now.isoformat(),
    }


@app.post("/payments/{payment_id}/approve")
def approve_payment(payment_id: int, user: User = Depends(current_user)):
    now = utcnow()
    cid = user.company_id
    with company_connection(cid) as conn:
        payment = _owned(conn, t.payments, user, payment_id, "payment")
        _check_decider(payment, user, "approve")
        _claim(conn, user, payment_id, EXECUTED, now)

        amount = Decimal(str(payment["amount"]))
        debited = conn.execute(
            update(t.accounts)
            .where(
                and_(
                    t.accounts.c.id == payment["from_account_id"],
                    t.accounts.c.company_id == cid,
                    t.accounts.c.balance >= amount,
                )
            )
            .values(balance=t.accounts.c.balance - amount, updated_at=now)
        )
        if debited.rowcount != 1:
            # Raising rolls back the claim too, so the payment stays AWAITING_APPROVAL.
            raise HTTPException(409, "Insufficient funds in the from account. The payment is still awaiting approval.")

        src = _owned(conn, t.accounts, user, payment["from_account_id"], "account")
        reference = payment["reference"] or f"Payment {payment_id}"
        posted = []
        if payment["to_account_id"] is not None:
            dst = _owned(conn, t.accounts, user, payment["to_account_id"], "account")
            conn.execute(
                update(t.accounts)
                .where(and_(t.accounts.c.id == dst["id"], t.accounts.c.company_id == cid))
                .values(balance=t.accounts.c.balance + amount, updated_at=now)
            )
            posted.append(_post(conn, cid, src["id"], payment_id, -amount, "transfer",
                                f"{dst['name']} {dst['iban']}", reference, now))
            posted.append(_post(conn, cid, dst["id"], payment_id, amount, "transfer",
                                f"{src['name']} {src['iban']}", reference, now))
        else:
            ben = _owned(conn, t.beneficiaries, user, payment["beneficiary_id"], "beneficiary")
            posted.append(_post(conn, cid, src["id"], payment_id, -amount, "supplier",
                                ben["name"], reference, now))

        result = _load(conn, user, payment_id)
        _outbox(conn, cid, "payment", payment_id, "payment.executed",
                {"payment": result, "transaction_ids": [p["id"] for p in posted]}, now)
        for p in posted:
            _outbox(conn, cid, "transaction", p["id"], "transaction.posted",
                    {**p, "company_id": cid, "payment_id": payment_id}, now)
    return result


@app.post("/payments/{payment_id}/reject")
def reject_payment(payment_id: int, user: User = Depends(current_user)):
    now = utcnow()
    with company_connection(user.company_id) as conn:
        payment = _owned(conn, t.payments, user, payment_id, "payment")
        _check_decider(payment, user, "reject")
        _claim(conn, user, payment_id, REJECTED, now)
        result = _load(conn, user, payment_id)
        _outbox(conn, user.company_id, "payment", payment_id, "payment.rejected", {"payment": result}, now)
    return result
