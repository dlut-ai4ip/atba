"""Single-account login authentication — not a multi-user account system, just a barrier for
internal/test-environment deployments, preventing anyone who gets the URL casually shared with them
from directly calling LLM/retrieval APIs that cost real money. The username/password are configured via
environment variables (atba/.env, see atba/.env.example), defaulting to atba / atba — the defaults only
exist so it runs for local testing without a configured .env; **production deployments must override
these in atba/.env**, don't count on nobody guessing the default credentials.

The token is a simple opaque string signed by the app itself (an HMAC-SHA256-signed payload), not a JWT
library, no third-party login integration — this app has one hardcoded test account and no user
database; a genuine account system (refresh tokens/session storage/multi-user) would be pure
over-engineering — being able to verify "this token was genuinely issued by this service and hasn't
expired" is enough.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional

from fastapi import Header, HTTPException

AUTH_USERNAME = os.environ.get("ATBA_AUTH_USERNAME", "atba")
AUTH_PASSWORD = os.environ.get("ATBA_AUTH_PASSWORD", "atba")

# The signing key — the default value here isn't a secure default, it just lets things run without
# configuration; production deployments must override this in atba/.env with a genuinely random value,
# e.g.: python -c "import secrets; print(secrets.token_hex(32))"
AUTH_SECRET_KEY = os.environ.get("ATBA_AUTH_SECRET_KEY", "atba-dev-secret-change-me-in-production")

# Token lifetime — 7 days. This isn't a high-sensitivity system (no real user data/payments), so a
# duration was chosen where "log in once and you basically don't need to log in again every day," not a
# short-lived session chosen for security reasons.
TOKEN_TTL_SECONDS = 7 * 24 * 3600


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + padding)


def _sign(payload_b64: str) -> str:
    sig = hmac.new(AUTH_SECRET_KEY.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).digest()
    return _b64url_encode(sig)


def verify_credentials(username: str, password: str) -> bool:
    """A constant-time comparison — avoids leaking a "username correct, password wrong" style partial-
    match side channel through response-time differences."""
    return hmac.compare_digest(username, AUTH_USERNAME) and hmac.compare_digest(password, AUTH_PASSWORD)


def create_token(username: str) -> tuple[str, int]:
    """Issues a token, returning (the token string, the expiry time as a Unix timestamp in seconds)."""
    expires_at = int(time.time()) + TOKEN_TTL_SECONDS
    payload_b64 = _b64url_encode(json.dumps({"sub": username, "exp": expires_at}).encode("utf-8"))
    return f"{payload_b64}.{_sign(payload_b64)}", expires_at


def _decode_and_verify(token: str) -> dict:
    try:
        payload_b64, signature = token.split(".", 1)
    except ValueError as e:
        raise ValueError("Malformed token") from e
    if not hmac.compare_digest(_sign(payload_b64), signature):
        raise ValueError("Signature mismatch")
    payload = json.loads(_b64url_decode(payload_b64))
    if payload.get("exp", 0) < time.time():
        raise ValueError("Token has expired, please log in again")
    return payload


async def require_auth(authorization: Optional[str] = Header(None)) -> str:
    """A FastAPI dependency — attached to routes that require login (see the `protected` router group
    in api.py), validating the `Authorization: Bearer <token>` header. Returns the username from the
    token — currently unused since there's only one account, kept so that if multi-user support is
    genuinely added later, callers (each route handler) don't have to change this dependency's
    signature just to get "who is the current user."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not logged in or missing credentials")
    token = authorization[len("Bearer ") :]
    try:
        payload = _decode_and_verify(token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    return payload["sub"]
