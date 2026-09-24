"""
Users API routes.
Authenticated user profile endpoints.
"""
from fastapi import APIRouter, Depends

from app.dependencies.auth import AuthContext, get_current_profile


router = APIRouter(prefix="", tags=["Users"])


@router.get("/users/me")
def get_current_user_profile(
    auth: AuthContext = Depends(get_current_profile),
):
    """Return the authenticated user's profile."""
    return {
        "success": True,
        "data": {
            "user_id": auth.user.id,
            "email": auth.user.email,
            "full_name": auth.profile.get("full_name"),
            "role": auth.profile.get("role"),
            "status": auth.profile.get("status"),
            "phone": auth.profile.get("phone"),
        },
    }
