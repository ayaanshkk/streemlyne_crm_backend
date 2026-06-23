"""
services/auth_service.py
JWT generation and verification for StreemLyne CRM.

Supports two token types:
  - staff    → issued to UserMaster (internal staff/admin)
  - customer → issued to CustomerAuth (customer portal)

Staff token payload (matches auth_middleware._resolve_user_from_token):
    {
        "user_id":     <int>,      ← read by auth_middleware via payload.get("user_id")
        "employee_id": <int>,      ← used for tenant scoping
        "type":        "staff",
        "iat":         <timestamp>,
        "exp":         <timestamp>
    }

Customer token payload:
    {
        "customer_user_id": <int>,
        "client_id":        <int>,
        "tenant_id":        <int>,
        "type":             "customer",
        "iat":              <timestamp>,
        "exp":              <timestamp>
    }

Expiry:
  Staff tokens    → 8 hours
  Customer tokens → 24 hours
"""

import jwt
from datetime import datetime, timedelta, timezone
from typing import Optional

STAFF_TOKEN_TTL_HOURS    = 8
CUSTOMER_TOKEN_TTL_HOURS = 24

TOKEN_TYPE_STAFF    = "staff"
TOKEN_TYPE_CUSTOMER = "customer"


# ── Generation ────────────────────────────────────────────────────────────────

def generate_staff_token(user_id: int, employee_id: int, secret_key: str) -> str:
    """
    Generate a signed JWT for an internal staff user.

    Uses 'user_id' as the claim name to match what auth_middleware
    reads via payload.get("user_id") in _resolve_user_from_token.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "user_id":     user_id,
        "employee_id": employee_id,
        "type":        TOKEN_TYPE_STAFF,
        "iat":         now,
        "exp":         now + timedelta(hours=STAFF_TOKEN_TTL_HOURS),
    }
    return jwt.encode(payload, secret_key, algorithm="HS256")


def generate_customer_token(
    customer_user_id: int,
    client_id: int,
    tenant_id: int,
    secret_key: str,
) -> str:
    """
    Generate a signed JWT for a customer portal user.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "customer_user_id": customer_user_id,
        "client_id":        client_id,
        "tenant_id":        tenant_id,
        "type":             TOKEN_TYPE_CUSTOMER,
        "iat":              now,
        "exp":              now + timedelta(hours=CUSTOMER_TOKEN_TTL_HOURS),
    }
    return jwt.encode(payload, secret_key, algorithm="HS256")


# ── Verification ──────────────────────────────────────────────────────────────

def decode_token(token: str, secret_key: str) -> Optional[dict]:
    """
    Decode and verify any StreemLyne JWT.
    Returns the payload dict on success, None on any failure
    (expired, bad signature, malformed, etc.).
    """
    try:
        return jwt.decode(token, secret_key, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def decode_staff_token(token: str, secret_key: str) -> Optional[dict]:
    """Decode a staff JWT. Returns None if it is a customer token."""
    payload = decode_token(token, secret_key)
    if payload and payload.get("type") == TOKEN_TYPE_STAFF:
        return payload
    return None


def decode_customer_token(token: str, secret_key: str) -> Optional[dict]:
    """Decode a customer JWT. Returns None if it is a staff token."""
    payload = decode_token(token, secret_key)
    if payload and payload.get("type") == TOKEN_TYPE_CUSTOMER:
        return payload
    return None