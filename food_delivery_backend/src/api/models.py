from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class UserPublic(BaseModel):
    """Public user payload returned to the frontend."""

    id: int = Field(..., description="User id")
    name: str = Field(..., description="Display name")
    email: str = Field(..., description="Email address")
    created_at: Optional[datetime] = Field(None, description="Account creation time (UTC)")


class AuthRegisterRequest(BaseModel):
    """Register new account request."""

    name: str = Field(..., min_length=1, description="User name")
    email: str = Field(..., min_length=3, description="Email")
    password: str = Field(..., min_length=6, description="Password (min 6 chars)")


class AuthLoginRequest(BaseModel):
    """Login request."""

    email: str = Field(..., min_length=3, description="Email")
    password: str = Field(..., min_length=1, description="Password")


class AuthResponse(BaseModel):
    """Auth response. Frontend accepts {access_token|token, user}."""

    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field("bearer", description="Token type")
    user: UserPublic = Field(..., description="Authenticated user")


class Restaurant(BaseModel):
    """Restaurant summary/details."""

    id: int = Field(..., description="Restaurant id")
    name: str = Field(..., description="Restaurant name")
    cuisine: str = Field(..., description="Cuisine category")
    rating: Optional[float] = Field(None, description="Average rating")
    eta_minutes: Optional[int] = Field(None, description="Estimated delivery time in minutes")


class MenuItem(BaseModel):
    """Menu item details."""

    id: int = Field(..., description="Menu item id")
    restaurant_id: int = Field(..., description="Restaurant id")
    name: str = Field(..., description="Item name")
    description: str = Field("", description="Item description")
    price: float = Field(..., ge=0, description="Unit price")


class OrderItemIn(BaseModel):
    """Order item included at checkout."""

    menu_item_id: int = Field(..., description="Menu item id")
    quantity: int = Field(..., ge=1, description="Quantity")


class CreateOrderRequest(BaseModel):
    """Checkout/place order request as used by the React app."""

    restaurant_id: int = Field(..., description="Restaurant id")
    items: list[OrderItemIn] = Field(..., min_length=1, description="Items to order")
    delivery_address: str = Field(..., min_length=1, description="Delivery address")
    payment_method: str = Field("card", description="Payment method: card|cash")


class OrderItem(BaseModel):
    """Stored order line item."""

    id: int = Field(..., description="Order item id")
    menu_item_id: int = Field(..., description="Menu item id")
    name: str = Field(..., description="Menu item name")
    quantity: int = Field(..., description="Quantity")
    unit_price: float = Field(..., description="Unit price")
    line_total: float = Field(..., description="Line total")


class Order(BaseModel):
    """Order details."""

    id: int = Field(..., description="Order id")
    user_id: Optional[int] = Field(None, description="User id (nullable for guest orders)")
    restaurant_id: int = Field(..., description="Restaurant id")
    restaurant_name: Optional[str] = Field(None, description="Restaurant display name")
    delivery_address: str = Field(..., description="Delivery address")
    payment_method: str = Field(..., description="Payment method")
    status: str = Field(..., description="Order status lifecycle state")
    subtotal: float = Field(..., description="Subtotal")
    delivery_fee: float = Field(..., description="Delivery fee")
    service_fee: float = Field(..., description="Service fee")
    total: float = Field(..., description="Total amount")
    created_at: Optional[datetime] = Field(None, description="Created time")
    updated_at: Optional[datetime] = Field(None, description="Last updated time")


class OrderWithItems(BaseModel):
    """Order plus line items."""

    order: Order = Field(..., description="Order header")
    items: list[OrderItem] = Field(..., description="Line items")


class PaymentRequest(BaseModel):
    """Simple payment request (demo / non-PCI)."""

    method: str = Field(..., description="Payment method used: card|cash")
    card_last4: Optional[str] = Field(None, description="Last 4 digits (demo only)")


class PaymentResponse(BaseModel):
    """Payment initiation/confirmation response."""

    status: str = Field(..., description="payment_status: succeeded|pending|failed")
    provider: str = Field("mock", description="Payment provider identifier")
    details: dict[str, Any] = Field(default_factory=dict, description="Provider details")


class TrackingMessage(BaseModel):
    """Message sent over WebSocket for order tracking."""

    order_id: int = Field(..., description="Order id")
    status: str = Field(..., description="Current status")
    message: str = Field("", description="Human-readable message")
    ts: datetime = Field(..., description="Event timestamp (UTC)")
    meta: dict[str, Any] = Field(default_factory=dict, description="Extra event metadata")
