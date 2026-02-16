from fastapi import APIRouter, Depends

from src.api.core.auth import get_current_user
from src.api.models import UserPublic

router = APIRouter(tags=["auth"])


@router.get(
    "/me",
    response_model=UserPublic,
    summary="Get current user",
    description="Returns the authenticated user from the Bearer token.",
)
def me(user: dict = Depends(get_current_user)) -> UserPublic:
    """
    PUBLIC_INTERFACE
    me
    Returns current authenticated user.
    """
    return UserPublic(**user)
