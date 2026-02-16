from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

import psycopg2
from psycopg2.extras import RealDictCursor

from src.api.core.config import get_settings


def _build_dsn() -> str:
    """Build a PostgreSQL DSN from env vars; prefer POSTGRES_URL if present."""
    s = get_settings()
    if s.postgres_url:
        return s.postgres_url

    # Fallback if URL not provided (still env-driven).
    # NOTE: Orchestrator should provide POSTGRES_URL; this fallback is best-effort.
    #
    # Important: in this project the database container commonly exposes Postgres on 5000
    # (see database/db_connection.txt), not 5432.
    host = "localhost"
    port = s.postgres_port or "5000"
    user = s.postgres_user or "postgres"
    password = s.postgres_password or ""
    db = s.postgres_db or "postgres"
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


@contextmanager
def get_db_conn() -> Generator[Any, None, None]:
    """
    PUBLIC_INTERFACE
    get_db_conn
    Context manager that yields a psycopg2 connection (RealDictCursor).

    Returns:
        psycopg2 connection
    """
    dsn = _build_dsn()
    conn = psycopg2.connect(dsn)
    try:
        yield conn
    finally:
        conn.close()


def fetch_all(conn: Any, query: str, params: tuple | None = None) -> list[dict]:
    """Fetch all rows as list[dict]."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, params or ())
        return list(cur.fetchall())


def fetch_one(conn: Any, query: str, params: tuple | None = None) -> dict | None:
    """Fetch single row as dict or None."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, params or ())
        row = cur.fetchone()
        return dict(row) if row else None


def execute(conn: Any, query: str, params: tuple | None = None) -> None:
    """Execute statement (INSERT/UPDATE/DELETE) and commit."""
    with conn.cursor() as cur:
        cur.execute(query, params or ())
    conn.commit()


def execute_returning_one(conn: Any, query: str, params: tuple | None = None) -> dict:
    """Execute statement with RETURNING and commit; returns single row dict."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, params or ())
        row = cur.fetchone()
    conn.commit()
    return dict(row) if row else {}


def utcnow() -> datetime:
    """UTC now helper."""
    return datetime.now(tz=timezone.utc)


def ensure_schema_and_seed() -> None:
    """
    PUBLIC_INTERFACE
    ensure_schema_and_seed
    Creates required tables (if missing) and seeds demo restaurants/menu.

    This function is idempotent and safe to call on startup.
    """
    ddl = [
        """
        CREATE TABLE IF NOT EXISTS users (
          id SERIAL PRIMARY KEY,
          name TEXT NOT NULL,
          email TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS restaurants (
          id SERIAL PRIMARY KEY,
          name TEXT NOT NULL,
          cuisine TEXT NOT NULL,
          rating NUMERIC NULL,
          eta_minutes INTEGER NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS menu_items (
          id SERIAL PRIMARY KEY,
          restaurant_id INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          price NUMERIC NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS orders (
          id SERIAL PRIMARY KEY,
          user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
          restaurant_id INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE RESTRICT,
          delivery_address TEXT NOT NULL,
          payment_method TEXT NOT NULL,
          status TEXT NOT NULL,
          subtotal NUMERIC NOT NULL,
          delivery_fee NUMERIC NOT NULL,
          service_fee NUMERIC NOT NULL,
          total NUMERIC NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS order_items (
          id SERIAL PRIMARY KEY,
          order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
          menu_item_id INTEGER NOT NULL REFERENCES menu_items(id) ON DELETE RESTRICT,
          quantity INTEGER NOT NULL,
          unit_price NUMERIC NOT NULL,
          line_total NUMERIC NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS order_events (
          id SERIAL PRIMARY KEY,
          order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
          status TEXT NOT NULL,
          message TEXT NOT NULL DEFAULT '',
          meta JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    ]

    with get_db_conn() as conn:
        for stmt in ddl:
            execute(conn, stmt)

        # Seed restaurants if empty
        existing = fetch_one(conn, "SELECT COUNT(*)::int AS c FROM restaurants")
        if (existing or {}).get("c", 0) > 0:
            return

        r1 = execute_returning_one(
            conn,
            """
            INSERT INTO restaurants (name, cuisine, rating, eta_minutes)
            VALUES (%s, %s, %s, %s)
            RETURNING id, name, cuisine, rating, eta_minutes
            """,
            ("Pasta Palace", "Italian", 4.6, 30),
        )
        r2 = execute_returning_one(
            conn,
            """
            INSERT INTO restaurants (name, cuisine, rating, eta_minutes)
            VALUES (%s, %s, %s, %s)
            RETURNING id, name, cuisine, rating, eta_minutes
            """,
            ("Sushi Sprint", "Japanese", 4.8, 25),
        )

        menu_seed = [
            (r1["id"], "Spaghetti Carbonara", "Classic carbonara with pancetta.", 14.99),
            (r1["id"], "Margherita Pizza", "San Marzano tomato, mozzarella, basil.", 12.50),
            (r2["id"], "Salmon Nigiri", "Fresh salmon over seasoned rice.", 8.99),
            (r2["id"], "California Roll", "Crab, avocado, cucumber.", 7.49),
        ]
        for row in menu_seed:
            execute(
                conn,
                """
                INSERT INTO menu_items (restaurant_id, name, description, price)
                VALUES (%s, %s, %s, %s)
                """,
                row,
            )

        # Also create an initial "system" event for each restaurant? Not needed.


def jsonable(obj: Any) -> Any:
    """Best-effort JSON serialization helper for db rows containing decimals/datetimes."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, datetime):
        return obj.isoformat()
    # decimals from psycopg2 show as Decimal; dump via str then parse number in frontend if desired
    try:
        import decimal

        if isinstance(obj, decimal.Decimal):
            return float(obj)
    except Exception:
        pass
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [jsonable(v) for v in obj]
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return str(obj)
