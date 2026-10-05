"""Caller identity.

AUTH_MODE=dev    X-Demo-User: <username> (local compose only).
AUTH_MODE=entra  Authorization: Bearer <JWT>. The token is validated with PyJWT against the
                 tenant's JWKS (ENTRA_TENANT_ID, ENTRA_AUDIENCE; optional ENTRA_JWKS_URL and
                 ENTRA_ISSUER overrides for External ID / ciamlogin.com), then its `oid` claim
                 is mapped to ops.users.entra_oid. First sign-in: a user not linked yet is
                 matched once by the token's email (preferred_username) and linked to that
                 oid. Kong validates too; this is defense in depth.

The caller's company_id always comes from ops.users, never from request input.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import HTTPException, Request
from sqlalchemy import func, select, update

from . import tables as t
from .db import system_connection


@dataclass(frozen=True)
class User:
    id: int
    company_id: int
    company_name: str
    username: str
    display_name: str
    title: str
    role: str
    email: str


def _auth_mode() -> str:
    return os.environ.get("AUTH_MODE", "entra").lower()  # fail closed


@lru_cache(maxsize=1)
def _jwks_client() -> jwt.PyJWKClient:
    tenant = os.environ["ENTRA_TENANT_ID"]
    url = os.environ.get(
        "ENTRA_JWKS_URL", f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys"
    )
    return jwt.PyJWKClient(url, cache_keys=True)


def _claims_from_bearer(request: Request) -> dict:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in to continue.")
    token = header[7:].strip()
    try:
        key = _jwks_client().get_signing_key_from_jwt(token).key
        options = {"require": ["exp", "aud", "oid"]}
        # Pin the issuer to our tenant: Microsoft signing keys are shared across tenants.
        issuer = os.environ.get("ENTRA_ISSUER") or f"https://login.microsoftonline.com/{os.environ['ENTRA_TENANT_ID']}/v2.0"
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=os.environ["ENTRA_AUDIENCE"],
            issuer=issuer,
            options=options,
        )
    except (jwt.PyJWTError, KeyError) as exc:
        raise HTTPException(401, "Your session is not valid. Sign in again.") from exc
    return claims


def _link_by_email(oid: str, email: str) -> None:
    """First sign-in: attach this oid to the not-yet-linked user with the token's email."""
    with system_connection() as conn:
        conn.execute(
            update(t.users)
            .where(func.lower(t.users.c.email) == email.lower(), t.users.c.entra_oid.is_(None))
            .values(entra_oid=oid)
        )


def _lookup(where) -> User | None:
    q = (
        select(t.users, t.companies.c.name.label("company_name"))
        .join(t.companies, t.companies.c.id == t.users.c.company_id)
        .where(where)
    )
    with system_connection() as conn:
        row = conn.execute(q).mappings().first()
    if row is None:
        return None
    return User(
        id=row["id"],
        company_id=row["company_id"],
        company_name=row["company_name"],
        username=row["username"],
        display_name=row["display_name"],
        title=row["title"],
        role=row["role"],
        email=row["email"],
    )


def current_user(request: Request) -> User:
    """FastAPI dependency returning the authenticated caller."""
    mode = _auth_mode()
    if mode == "dev":
        username = request.headers.get("x-demo-user", "").strip().lower()
        if not username:
            raise HTTPException(401, "Sign in to continue.")
        user = _lookup(t.users.c.username == username)
    elif mode == "entra":
        claims = _claims_from_bearer(request)
        oid = str(claims["oid"])
        user = _lookup(t.users.c.entra_oid == oid)
        email = claims.get("preferred_username") or claims.get("email")
        if user is None and email:
            _link_by_email(oid, str(email))
            user = _lookup(t.users.c.entra_oid == oid)
    else:
        raise HTTPException(500, "Server auth is misconfigured.")
    if user is None:
        raise HTTPException(401, "Your account is not set up for this portal.")
    return user
