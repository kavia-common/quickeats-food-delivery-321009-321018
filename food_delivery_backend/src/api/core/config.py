import os
from dataclasses import dataclass


def _get_env(name: str, default: str | None = None) -> str | None:
    """Internal helper to read environment variables safely."""
    value = os.getenv(name)
    if value is None:
        return default
    return value


@dataclass(frozen=True)
class Settings:
    """Strongly-typed application settings derived from environment variables."""

    postgres_url: str | None
    postgres_user: str | None
    postgres_password: str | None
    postgres_db: str | None
    postgres_port: str | None

    jwt_secret: str
    jwt_issuer: str
    jwt_audience: str
    jwt_exp_minutes: int

    cors_allow_origins: list[str]


def get_settings() -> Settings:
    """
    PUBLIC_INTERFACE
    get_settings
    Loads environment-driven settings for DB + JWT + CORS.

    Env vars used:
    - POSTGRES_URL, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_PORT
    - JWT_SECRET, JWT_ISSUER, JWT_AUDIENCE, JWT_EXP_MINUTES
    - CORS_ALLOW_ORIGINS (comma-separated, default "*")
    """
    cors_raw = _get_env("CORS_ALLOW_ORIGINS", "*") or "*"
    cors = ["*"] if cors_raw.strip() == "*" else [o.strip() for o in cors_raw.split(",") if o.strip()]

    jwt_secret = _get_env("JWT_SECRET", "dev-secret-change-me")
    # NOTE: Orchestrator should set JWT_SECRET in .env for non-dev usage.

    return Settings(
        postgres_url=_get_env("POSTGRES_URL"),
        postgres_user=_get_env("POSTGRES_USER"),
        postgres_password=_get_env("POSTGRES_PASSWORD"),
        postgres_db=_get_env("POSTGRES_DB"),
        postgres_port=_get_env("POSTGRES_PORT"),
        jwt_secret=jwt_secret,
        jwt_issuer=_get_env("JWT_ISSUER", "quickeats"),
        jwt_audience=_get_env("JWT_AUDIENCE", "quickeats-web"),
        jwt_exp_minutes=int(_get_env("JWT_EXP_MINUTES", "1440") or "1440"),  # default: 24h
        cors_allow_origins=cors,
    )
