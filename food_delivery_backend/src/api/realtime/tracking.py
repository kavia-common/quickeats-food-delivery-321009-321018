from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from src.api.core.auth import get_current_user_optional
from src.api.core.db import fetch_one, get_db_conn, jsonable


@dataclass
class Connection:
    websocket: WebSocket
    order_id: int
    user_id: int | None


class OrderTrackingHub:
    """In-memory hub: keeps active WebSocket connections grouped by order_id."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._connections: list[Connection] = []

    async def connect(self, websocket: WebSocket, order_id: int, user_id: int | None) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.append(Connection(websocket=websocket, order_id=order_id, user_id=user_id))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections = [c for c in self._connections if c.websocket is not websocket]

    async def broadcast_order(self, order_id: int, message: dict[str, Any]) -> None:
        async with self._lock:
            targets = [c for c in self._connections if c.order_id == order_id]
        # Send outside lock
        for c in targets:
            try:
                await c.websocket.send_json(message)
            except Exception:
                # Best-effort; client may have dropped
                pass


hub = OrderTrackingHub()


async def order_tracking_ws(websocket: WebSocket) -> None:
    """
    PUBLIC_INTERFACE
    order_tracking_ws
    WebSocket endpoint handler for order tracking updates.

    Query params:
      - order_id: required
      - token: optional JWT (frontend passes token in query for WS convenience)

    Behavior:
      - Sends an initial snapshot with current order status
      - Then emits periodic status snapshots (polling DB) until socket closes.
    """
    params = websocket.query_params
    order_id_raw = params.get("order_id")
    if not order_id_raw:
        await websocket.close(code=1008)
        return
    try:
        order_id = int(order_id_raw)
    except ValueError:
        await websocket.close(code=1008)
        return

    # Authenticate (optional). If token present, enforce that user owns the order (when user_id is set on order).
    token = params.get("token")
    user = None
    try:
        # We reuse dependency logic by calling it directly (it can accept query token).
        user = get_current_user_optional(credentials=None, token=token)
    except Exception:
        user = None

    with get_db_conn() as conn:
        order = fetch_one(
            conn,
            """
            SELECT id, user_id, status, updated_at
            FROM orders
            WHERE id=%s
            """,
            (order_id,),
        )
    if not order:
        await websocket.accept()
        await websocket.send_json(
            {
                "order_id": order_id,
                "status": "not_found",
                "message": "Order not found",
                "ts": datetime.now(tz=timezone.utc).isoformat(),
            }
        )
        await websocket.close(code=1008)
        return

    if user and order.get("user_id") is not None and int(order["user_id"]) != int(user["id"]):
        await websocket.accept()
        await websocket.send_json(
            {
                "order_id": order_id,
                "status": "forbidden",
                "message": "Forbidden",
                "ts": datetime.now(tz=timezone.utc).isoformat(),
            }
        )
        await websocket.close(code=1008)
        return

    user_id = int(user["id"]) if user else None
    await hub.connect(websocket, order_id=order_id, user_id=user_id)

    try:
        # Send initial snapshot
        await websocket.send_json(
            {
                "order_id": order_id,
                "status": str(order["status"]),
                "message": "Tracking connected",
                "ts": datetime.now(tz=timezone.utc).isoformat(),
                "meta": {"updated_at": jsonable(order.get("updated_at"))},
            }
        )

        # Polling loop (simple and robust). In a real system we'd use LISTEN/NOTIFY or a message bus.
        last_status = str(order["status"])
        last_updated = str(order.get("updated_at") or "")
        while True:
            await asyncio.sleep(2.0)
            with get_db_conn() as conn:
                cur = fetch_one(
                    conn,
                    "SELECT status, updated_at FROM orders WHERE id=%s",
                    (order_id,),
                )
            if not cur:
                await websocket.send_json(
                    {
                        "order_id": order_id,
                        "status": "not_found",
                        "message": "Order deleted",
                        "ts": datetime.now(tz=timezone.utc).isoformat(),
                    }
                )
                await websocket.close(code=1008)
                return

            status = str(cur["status"])
            updated = str(cur.get("updated_at") or "")
            if status != last_status or updated != last_updated:
                last_status, last_updated = status, updated
                await websocket.send_json(
                    {
                        "order_id": order_id,
                        "status": status,
                        "message": f"Order status: {status}",
                        "ts": datetime.now(tz=timezone.utc).isoformat(),
                        "meta": {"updated_at": jsonable(cur.get("updated_at"))},
                    }
                )

    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(websocket)
