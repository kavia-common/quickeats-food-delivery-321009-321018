from fastapi import APIRouter, HTTPException
from pydantic import EmailStr

from src.api.core.auth import create_access_token, hash_password, verify_password
from src.api.core.db import execute_returning_one, fetch_one, get_db_conn, jsonable
from src.api.models import AuthLoginRequest, AuthRegisterRequest, AuthResponse, UserPublic

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=AuthResponse,
    summary="Register a new user",
    description="Creates a user account and returns an access token (auto-login).",
)
def register(payload: AuthRegisterRequest) -> AuthResponse:
    """
    PUBLIC_INTERFACE
    register
    Registers a new user and returns JWT token + user.
    """
    email = str(EmailStr(payload.email)).lower()
    with get_db_conn() as conn:
        existing = fetch_one(conn, "SELECT id FROM users WHERE email=%s", (email,))
        if existing:
            raise HTTPException(status_code=409, detail="Email already registered")

        user = execute_returning_one(
            conn,
            """
            INSERT INTO users (name, email, password_hash)
            VALUES (%s, %s, %s)
            RETURNING id, name, email, created_at
            """,
            (payload.name, email, hash_password(payload.password)),
        )

    token = create_access_token(user_id=int(user["id"]), email=user["email"])
    return AuthResponse(access_token=token, user=UserPublic(**jsonable(user)))


@router.post(
    "/login",
    response_model=AuthResponse,
    summary="Login",
    description="Validates email/password and returns a JWT access token.",
)
def login(payload: AuthLoginRequest) -> AuthResponse:
    """
    PUBLIC_INTERFACE
    login
    Login endpoint returning JWT token + user.
    """
    email = payload.email.lower().strip()
    with get_db_conn() as conn:
        user_row = fetch_one(
            conn,
            "SELECT id, name, email, password_hash, created_at FROM users WHERE email=%s",
            (email,),
        )
    if not user_row or not verify_password(payload.password, user_row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(user_id=int(user_row["id"]), email=user_row["email"])
    user_public = {k: v for k, v in user_row.items() if k != "password_hash"}
    return AuthResponse(access_token=token, user=UserPublic(**jsonable(user_public)))
