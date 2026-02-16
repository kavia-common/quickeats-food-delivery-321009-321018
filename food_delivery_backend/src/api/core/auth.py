from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext

from src.api.core.config import get_settings
from src.api.core.db import fetch_one, get_db_conn, jsonable

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Hash a password using passlib bcrypt."""
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against stored hash."""
    try:
        return pwd_context.verify(password, password_hash)
    except Exception:
        return False


def create_access_token(user_id: int, email: str) -> str:
    """
    PUBLIC_INTERFACE
    create_access_token
    Creates a signed JWT for the user.

    Returns:
        Encoded JWT string.
    """
    s = get_settings()
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "iss": s.jwt_issuer,
        "aud": s.jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=s.jwt_exp_minutes)).timestamp()),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict[str, Any]:
    """Decode/validate a JWT and return payload or raise."""
    s = get_settings()
    return jwt.decode(
        token,
        s.jwt_secret,
        algorithms=["HS256"],
        audience=s.jwt_audience,
        issuer=s.jwt_issuer,
        options={"require": ["exp", "iat", "sub"]},
    )


def _get_token_from_query(token: str | None) -> str | None:
    if not token:
        return None
    return token.strip() or None


def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    token: str | None = None,
) -> dict | None:
    """
    PUBLIC_INTERFACE
    get_current_user_optional
    FastAPI dependency: returns current user dict if authenticated, else None.

    Accepts:
    - Authorization: Bearer <token>
    - Or a 'token' query parameter (used by WebSocket client convenience)
    """
    raw = None
    if credentials and credentials.scheme.lower() == "bearer":
        raw = credentials.credentials
    raw = raw or _get_token_from_query(token)
    if not raw:
        return None

    try:
        payload = decode_token(raw)
        user_id = int(payload["sub"])
    except Exception:
        return None

    with get_db_conn() as conn:
        user = fetch_one(conn, "SELECT id, name, email, created_at FROM users WHERE id=%s", (user_id,))
    return jsonable(user) if user else None


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """
    PUBLIC_INTERFACE
    get_current_user
    FastAPI dependency: returns current user dict or raises 401.
    """
    user = get_current_user_optional(credentials=credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
