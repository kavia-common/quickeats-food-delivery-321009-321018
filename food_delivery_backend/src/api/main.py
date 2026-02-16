from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from src.api.core.config import get_settings
from src.api.core.db import ensure_schema_and_seed
from src.api.realtime.tracking import order_tracking_ws
from src.api.routers import auth as auth_router
from src.api.routers import me as me_router
from src.api.routers import orders as orders_router
from src.api.routers import restaurants as restaurants_router

openapi_tags = [
    {"name": "health", "description": "Health checks"},
    {"name": "auth", "description": "Registration, login, and current user"},
    {"name": "restaurants", "description": "Restaurant listing and menu browsing"},
    {"name": "orders", "description": "Checkout/order placement, order history, and payment demo"},
    {"name": "realtime", "description": "WebSocket real-time order tracking"},
]

app = FastAPI(
    title="QuickEats Backend API",
    description=(
        "Backend for QuickEats (food delivery demo): auth, restaurant browsing, checkout/order placement, "
        "and real-time order tracking over WebSocket.\n\n"
        "WebSocket usage:\n"
        "- Connect to `/ws?order_id=<id>&token=<jwt?>`\n"
        "- The frontend derives this from the REST API base and appends `/ws`.\n"
    ),
    version="0.1.0",
    openapi_tags=openapi_tags,
)

settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    """Create tables and seed demo data at startup (idempotent)."""
    ensure_schema_and_seed()


@app.get("/", tags=["health"], summary="Health check")
def health_check():
    """
    PUBLIC_INTERFACE
    health_check
    Returns a basic health response.
    """
    return {"message": "Healthy"}


@app.get(
    "/docs/ws",
    tags=["realtime"],
    summary="WebSocket usage notes",
    description="Human-readable help for connecting to the order tracking WebSocket endpoint.",
)
def websocket_usage() -> HTMLResponse:
    """
    PUBLIC_INTERFACE
    websocket_usage
    Returns simple documentation and examples for WebSocket usage.
    """
    html = """
    <html>
      <head><title>QuickEats WebSocket</title></head>
      <body style="font-family: ui-sans-serif, system-ui; padding: 16px;">
        <h1>Order Tracking WebSocket</h1>
        <p>Endpoint: <code>/ws</code></p>
        <p>Query params:</p>
        <ul>
          <li><code>order_id</code> (required)</li>
          <li><code>token</code> (optional JWT; if provided and order has a user_id, ownership is enforced)</li>
        </ul>
        <p>Example:</p>
        <pre>ws://localhost:3001/ws?order_id=123&token=&lt;jwt&gt;</pre>
        <p>The React frontend uses <code>REACT_APP_WS_URL</code> or derives from REST base.</p>
      </body>
    </html>
    """
    return HTMLResponse(html)


# REST routers
app.include_router(auth_router.router)
app.include_router(me_router.router)
app.include_router(restaurants_router.router)
app.include_router(orders_router.router)


@app.websocket("/ws")
async def ws_entrypoint(websocket: WebSocket):
    """
    PUBLIC_INTERFACE
    ws_entrypoint
    WebSocket endpoint for real-time order tracking.

    Parameters:
      - websocket: the client socket
    Returns:
      - Streams JSON messages with order status updates until disconnected.
    """
    await order_tracking_ws(websocket)
