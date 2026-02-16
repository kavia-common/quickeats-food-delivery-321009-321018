from fastapi import APIRouter, HTTPException

from src.api.core.db import fetch_all, fetch_one, get_db_conn, jsonable
from src.api.models import MenuItem, Restaurant

router = APIRouter(prefix="/restaurants", tags=["restaurants"])


@router.get(
    "",
    response_model=list[Restaurant],
    summary="List restaurants",
    description="Returns a list of restaurants for browsing.",
)
def list_restaurants() -> list[Restaurant]:
    """
    PUBLIC_INTERFACE
    list_restaurants
    List all restaurants.
    """
    with get_db_conn() as conn:
        rows = fetch_all(
            conn,
            """
            SELECT id, name, cuisine, rating, eta_minutes
            FROM restaurants
            ORDER BY id ASC
            """,
        )
    return [Restaurant(**jsonable(r)) for r in rows]


@router.get(
    "/{restaurant_id}",
    response_model=Restaurant,
    summary="Get restaurant details",
    description="Returns a single restaurant by id.",
)
def get_restaurant(restaurant_id: int) -> Restaurant:
    """
    PUBLIC_INTERFACE
    get_restaurant
    Fetch a restaurant by id.
    """
    with get_db_conn() as conn:
        row = fetch_one(
            conn,
            """
            SELECT id, name, cuisine, rating, eta_minutes
            FROM restaurants
            WHERE id=%s
            """,
            (restaurant_id,),
        )
    if not row:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    return Restaurant(**jsonable(row))


@router.get(
    "/{restaurant_id}/menu",
    response_model=list[MenuItem],
    summary="Get restaurant menu",
    description="Returns menu items for a restaurant.",
)
def get_menu(restaurant_id: int) -> list[MenuItem]:
    """
    PUBLIC_INTERFACE
    get_menu
    Returns list of menu items for a restaurant.
    """
    with get_db_conn() as conn:
        exists = fetch_one(conn, "SELECT id FROM restaurants WHERE id=%s", (restaurant_id,))
        if not exists:
            raise HTTPException(status_code=404, detail="Restaurant not found")

        rows = fetch_all(
            conn,
            """
            SELECT id, restaurant_id, name, description, price
            FROM menu_items
            WHERE restaurant_id=%s
            ORDER BY id ASC
            """,
            (restaurant_id,),
        )
    return [MenuItem(**jsonable(r)) for r in rows]
