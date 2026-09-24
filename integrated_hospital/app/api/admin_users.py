"""
Admin user management API routes.
Staff/admin user governance operations.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.auth import AuthContext, require_admin
from app.schema.admin import AdminUpdateUserRequest
from app.services.admin_user_service import (
    create_staff_user,
    get_user,
    list_users,
    update_user,
)

router = APIRouter(
    prefix="/admin/users",
    tags=["Admin User Management"],
)


@router.get("", status_code=status.HTTP_200_OK, summary="List all users")
def list_users_endpoint(
    role: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(require_admin),
):
    """List all user profiles (admin only)."""
    result = list_users(role=role, status=status_filter, limit=limit, offset=offset)
    return {"success": True, "data": result["users"], "total": result["total"]}


@router.get("/{user_id}", status_code=status.HTTP_200_OK, summary="Get user")
def get_user_endpoint(
    user_id: str,
    auth: AuthContext = Depends(require_admin),
):
    """Get a single user profile (admin only)."""
    user = get_user(user_id)
    return {"success": True, "data": user}


@router.patch("/{user_id}", status_code=status.HTTP_200_OK, summary="Update user")
def update_user_endpoint(
    user_id: str,
    payload: AdminUpdateUserRequest,
    auth: AuthContext = Depends(require_admin),
):
    """Update a user's role or status (admin only)."""
    user = update_user(
        user_id=user_id,
        role=payload.role,
        status=payload.status,
        actor_id=auth.user.id,
    )
    return {"success": True, "message": "User updated.", "data": user}


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create staff user")
def create_staff_user_endpoint(
    full_name: str = Query(min_length=1, max_length=120),
    email: str = Query(min_length=3, max_length=255),
    phone: str | None = Query(default=None, max_length=30),
    role: Literal["staff", "admin"] = Query(default="staff"),
    auth: AuthContext = Depends(require_admin),
):
    """
    Create a staff/admin account (admin only).

    Creates a real Supabase auth user (so the account can sign in with the
    emailed 8-digit OTP) plus the matching profile row. Phone is optional;
    role defaults to "staff".
    """
    user = create_staff_user(
        full_name=full_name,
        email=email,
        phone=phone,
        role=role,
        actor_id=auth.user.id,
    )
    return {"success": True, "message": "User created.", "data": user}
