from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from src.api.core.auth import get_current_user_optional
from src.api.core.db import (
    execute,
    execute_returning_one,
    fetch_all,
    fetch_one,
    get_db_conn,
    jsonable,
)
from src.api.models import (
    CreateOrderRequest,
    Order,
    OrderItem,
    OrderWithItems,
    PaymentRequest,
    PaymentResponse,
)

router = APIRouter(prefix="/orders", tags=["orders"])


def _fees_for(subtotal: float) -> tuple[float, float]:
    """Compute delivery/service fees similarly to frontend demo logic."""
    if subtotal <= 0:
        return 0.0, 0.0
    delivery_fee = 2.99
    service_fee = min(4.5, subtotal * 0.06)
    return float(delivery_fee), float(service_fee)


def _add_order_event(conn: Any, order_id: int, status: str, message: str, meta: dict | None = None) -> None:
    execute(
        conn,
        """
        INSERT INTO order_events (order_id, status, message, meta)
        VALUES (%s, %s, %s, %s::jsonb)
        """,
        (order_id, status, message, jsonable(meta or {})),
    )


def _touch_order_updated(conn: Any, order_id: int) -> None:
    execute(conn, "UPDATE orders SET updated_at = NOW() WHERE id=%s", (order_id,))


@router.post(
    "",
    response_model=Order,
    summary="Place an order (checkout)",
    description="Creates an order with items. Authentication is optional; user_id will be set when token is provided.",
)
def create_order(payload: CreateOrderRequest, user: dict | None = Depends(get_current_user_optional)) -> Order:
    """
    PUBLIC_INTERFACE
    create_order
    Place a new order; returns the created order header.
    """
    with get_db_conn() as conn:
        rest = fetch_one(conn, "SELECT id, name FROM restaurants WHERE id=%s", (payload.restaurant_id,))
        if not rest:
            raise HTTPException(status_code=404, detail="Restaurant not found")

        # Fetch menu items for price validation
        menu_ids = [i.menu_item_id for i in payload.items]
        # Prevent empty or duplicates issues
        if not menu_ids:
            raise HTTPException(status_code=400, detail="No items provided")

        # Build a dict of menu_item_id -> row
        rows = fetch_all(
            conn,
            """
            SELECT id, name, price
            FROM menu_items
            WHERE restaurant_id=%s AND id = ANY(%s)
            """,
            (payload.restaurant_id, menu_ids),
        )
        by_id = {int(r["id"]): r for r in rows}

        subtotal = 0.0
        line_items: list[dict] = []
        for item in payload.items:
            r = by_id.get(int(item.menu_item_id))
            if not r:
                raise HTTPException(status_code=400, detail=f"Invalid menu_item_id: {item.menu_item_id}")
            unit_price = float(r["price"])
            line_total = unit_price * int(item.quantity)
            subtotal += line_total
            line_items.append(
                {
                    "menu_item_id": int(item.menu_item_id),
                    "quantity": int(item.quantity),
                    "unit_price": unit_price,
                    "line_total": float(line_total),
                }
            )

        delivery_fee, service_fee = _fees_for(subtotal)
        total = float(subtotal + delivery_fee + service_fee)

        order = execute_returning_one(
            conn,
            """
            INSERT INTO orders (
              user_id, restaurant_id, delivery_address, payment_method,
              status, subtotal, delivery_fee, service_fee, total
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING
              id, user_id, restaurant_id, delivery_address, payment_method,
              status, subtotal, delivery_fee, service_fee, total, created_at, updated_at
            """,
            (
                (int(user["id"]) if user else None),
                int(payload.restaurant_id),
                payload.delivery_address,
                payload.payment_method,
                "created",
                subtotal,
                delivery_fee,
                service_fee,
                total,
            ),
        )
        order_id = int(order["id"])

        for li in line_items:
            execute(
                conn,
                """
                INSERT INTO order_items (order_id, menu_item_id, quantity, unit_price, line_total)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (order_id, li["menu_item_id"], li["quantity"], li["unit_price"], li["line_total"]),
            )

        _add_order_event(conn, order_id, "created", "Order created")
        # Move quickly to "confirmed" as a realistic lifecycle start
        execute(conn, "UPDATE orders SET status=%s, updated_at=NOW() WHERE id=%s", ("confirmed", order_id))
        _add_order_event(conn, order_id, "confirmed", "Restaurant confirmed the order")
        _touch_order_updated(conn, order_id)

        order_out = jsonable(order)
        order_out["status"] = "confirmed"
        order_out["restaurant_name"] = rest["name"]
        return Order(**order_out)


@router.get(
    "",
    response_model=list[Order],
    summary="List user's orders",
    description="Returns orders for the authenticated user. If not authenticated, returns empty list.",
)
def list_orders(user: dict | None = Depends(get_current_user_optional)) -> list[Order]:
    """
    PUBLIC_INTERFACE
    list_orders
    List orders for current user.
    """
    if not user:
        return []
    with get_db_conn() as conn:
        rows = fetch_all(
            conn,
            """
            SELECT o.id, o.user_id, o.restaurant_id, r.name AS restaurant_name,
                   o.delivery_address, o.payment_method, o.status,
                   o.subtotal, o.delivery_fee, o.service_fee, o.total,
                   o.created_at, o.updated_at
            FROM orders o
            JOIN restaurants r ON r.id = o.restaurant_id
            WHERE o.user_id=%s
            ORDER BY o.id DESC
            """,
            (int(user["id"]),),
        )
    return [Order(**jsonable(r)) for r in rows]


@router.get(
    "/{order_id}",
    response_model=OrderWithItems,
    summary="Get order details",
    description="Returns order header + items. If authenticated, enforces ownership.",
)
def get_order(order_id: int, user: dict | None = Depends(get_current_user_optional)) -> OrderWithItems:
    """
    PUBLIC_INTERFACE
    get_order
    Get order details for tracking.
    """
    with get_db_conn() as conn:
        order = fetch_one(
            conn,
            """
            SELECT o.id, o.user_id, o.restaurant_id, r.name AS restaurant_name,
                   o.delivery_address, o.payment_method, o.status,
                   o.subtotal, o.delivery_fee, o.service_fee, o.total,
                   o.created_at, o.updated_at
            FROM orders o
            JOIN restaurants r ON r.id = o.restaurant_id
            WHERE o.id=%s
            """,
            (order_id,),
        )
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        if user and order.get("user_id") is not None and int(order["user_id"]) != int(user["id"]):
            raise HTTPException(status_code=403, detail="Forbidden")

        items = fetch_all(
            conn,
            """
            SELECT oi.id, oi.menu_item_id, mi.name, oi.quantity, oi.unit_price, oi.line_total
            FROM order_items oi
            JOIN menu_items mi ON mi.id = oi.menu_item_id
            WHERE oi.order_id=%s
            ORDER BY oi.id ASC
            """,
            (order_id,),
        )
    return OrderWithItems(
        order=Order(**jsonable(order)),
        items=[OrderItem(**jsonable(i)) for i in items],
    )


@router.post(
    "/{order_id}/pay",
    response_model=PaymentResponse,
    summary="Pay for an order (mock flow)",
    description=(
        "Demo payment endpoint used by the UI if present. "
        "This does NOT integrate a real PSP; it simulates success and advances lifecycle."
    ),
)
def pay_order(order_id: int, payload: PaymentRequest) -> PaymentResponse:
    """
    PUBLIC_INTERFACE
    pay_order
    Simulates payment and advances the order lifecycle to 'preparing'.
    """
    with get_db_conn() as conn:
        order = fetch_one(conn, "SELECT id, status FROM orders WHERE id=%s", (order_id,))
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        # If already paid/advanced, return ok (idempotent-ish).
        if order["status"] not in ("created", "confirmed"):
            return PaymentResponse(status="succeeded", provider="mock", details={"note": "Already processed"})

        execute(conn, "UPDATE orders SET status=%s, updated_at=NOW() WHERE id=%s", ("preparing", order_id))
        _add_order_event(
            conn,
            order_id,
            "preparing",
            "Payment accepted; restaurant is preparing your order",
            meta={"method": payload.method, "card_last4": payload.card_last4},
        )
        _touch_order_updated(conn, order_id)

    return PaymentResponse(status="succeeded", provider="mock", details={"method": payload.method})


@router.post(
    "/{order_id}/advance",
    summary="Advance order status (demo/admin)",
    description="Moves the order to the next lifecycle state for demo/testing tracking updates.",
)
def advance_order(order_id: int) -> dict:
    """
    PUBLIC_INTERFACE
    advance_order
    Advances an order through: confirmed -> preparing -> out_for_delivery -> delivered.
    """
    flow = ["confirmed", "preparing", "out_for_delivery", "delivered"]
    with get_db_conn() as conn:
        order = fetch_one(conn, "SELECT id, status FROM orders WHERE id=%s", (order_id,))
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        cur = str(order["status"])
        if cur not in flow:
            # If some unknown state, normalize to confirmed
            nxt = "confirmed"
        else:
            idx = flow.index(cur)
            nxt = flow[min(idx + 1, len(flow) - 1)]

        execute(conn, "UPDATE orders SET status=%s, updated_at=NOW() WHERE id=%s", (nxt, order_id))
        _add_order_event(conn, order_id, nxt, f"Order status updated to {nxt}")
        _touch_order_updated(conn, order_id)

    return {"order_id": order_id, "status": nxt, "ts": datetime.now(tz=timezone.utc).isoformat()}
