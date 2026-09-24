"""
Admin user management service.
Staff/admin user governance operations.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config.settings import get_supabase_admin_client
from app.services.audit_service import log_audit_event
from app.utils.exceptions import ProfileNotFoundError, InvalidOperationError
from app.utils.logger import log_error, log_info


def list_users(
    *,
    role: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """List all user profiles with optional filters (admin only)."""
    admin_supabase = get_supabase_admin_client()

    query = admin_supabase.table("profiles").select("*", count="exact")

    if role:
        query = query.eq("role", role)
    if status:
        query = query.eq("status", status)

    response = query.order("registered_at", desc=True).range(offset, offset + limit - 1).execute()

    return {
        "users": response.data or [],
        "total": response.count or 0,
        "limit": limit,
        "offset": offset,
    }


def get_user(user_id: str) -> dict[str, Any]:
    """Get a single user profile (admin only)."""
    admin_supabase = get_supabase_admin_client()

    response = (
        admin_supabase
        .table("profiles")
        .select("*")
        .eq("user_id", user_id)
        .single()
        .execute()
    )

    if not response.data:
        raise ProfileNotFoundError()

    return response.data


def update_user(
    *,
    user_id: str,
    role: str | None = None,
    status: str | None = None,
    actor_id: str,
) -> dict[str, Any]:
    """Update a user's role or status (admin only)."""
    admin_supabase = get_supabase_admin_client()

    # Fetch existing profile
    existing_res = (
        admin_supabase
        .table("profiles")
        .select("*")
        .eq("user_id", user_id)
        .single()
        .execute()
    )

    if not existing_res.data:
        raise ProfileNotFoundError()

    existing = existing_res.data
    now = datetime.now(timezone.utc)

    update_fields: dict[str, Any] = {"updated_at": now.isoformat()}

    if role is not None:
        # Prevent admin from demoting themselves
        if user_id == actor_id and role != "admin":
            raise InvalidOperationError("Admin cannot change their own role.")
        update_fields["role"] = role

    if status is not None:
        update_fields["status"] = status

    if len(update_fields) <= 1:  # only updated_at
        return existing

    update_res = (
        admin_supabase
        .table("profiles")
        .update(update_fields)
        .eq("user_id", user_id)
        .execute()
    )

    log_audit_event(
        user_id=actor_id,
        user_role="admin",
        action="update_user",
        resource_type="profiles",
        resource_id=user_id,
        old_value={"role": existing.get("role"), "status": existing.get("status")},
        new_value=update_fields,
        status="success",
    )

    log_info("User updated by admin", user_id=user_id, actor_id=actor_id, update_fields=update_fields)
    return update_res.data[0] if update_res.data else existing


def create_staff_user(
    *,
    full_name: str,
    email: str,
    phone: str | None = None,
    role: str = "staff",
    actor_id: str,
) -> dict[str, Any]:
    """
    Create a staff/admin account end-to-end (admin only).

    Root-cause fix for staff account creation (spec §22): the old flow wrote
    a profile row keyed to a random UUID that was never linked to Supabase
    auth, so the account could not sign in. Now we:

    1. reject duplicate emails (existing profile OR auth user) with 409,
    2. create a real, email-confirmed auth user via the service-role
       admin API (sign-in then works through the existing 8-digit OTP flow),
    3. insert the profile row keyed to that auth user id,
    4. roll the auth user back if the profile insert fails, so no unusable
       half-created account is left behind.
    """
    from supabase_auth.errors import AuthApiError
    from supabase_auth.types import AdminUserAttributes

    from app.utils.exceptions import AccountAlreadyExistsError, UserCreationError

    admin_supabase = get_supabase_admin_client()
    normalized_email = (email or "").lower().strip()

    # 1. Duplicate check against existing profiles.
    existing = (
        admin_supabase
        .table("profiles")
        .select("user_id")
        .eq("email", normalized_email)
        .execute()
    )
    if existing.data:
        raise AccountAlreadyExistsError()

    admin_auth = admin_supabase.auth.admin

    # 2. Create the real auth user (email pre-confirmed: admin-provisioned).
    try:
        created = admin_auth.create_user(
            AdminUserAttributes(
                email=normalized_email,
                email_confirm=True,
                user_metadata={
                    "full_name": (full_name or "").strip(),
                    "role": role,
                    "phone": phone,
                },
            )
        )
    except AuthApiError as exc:
        if _is_duplicate_email_error(exc):
            raise AccountAlreadyExistsError()
        log_error(
            "Auth user creation failed",
            email=normalized_email,
            exception_type=type(exc).__name__,
        )
        raise UserCreationError()
    except Exception as exc:
        log_error(
            "Auth user creation failed",
            email=normalized_email,
            exception_type=type(exc).__name__,
        )
        raise UserCreationError() from exc

    auth_user = getattr(created, "user", None)
    user_id = getattr(auth_user, "id", None)
    if not user_id:
        raise UserCreationError()

    # 3. Profile row keyed to the auth user id.
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user_id,
        "full_name": (full_name or "").strip(),
        "email": normalized_email,
        "role": role,
        "phone": phone,
        "status": "active",
        "registered_at": now.isoformat(),
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    try:
        insert_res = admin_supabase.table("profiles").insert(payload).execute()
        profile_created = bool(insert_res.data)
    except Exception as exc:
        log_error(
            "Staff profile insert failed",
            email=normalized_email,
            exception_type=type(exc).__name__,
        )
        profile_created = False

    if not profile_created:
        # 4. Roll back the auth user so the email is not left occupied by an
        # account that cannot be used.
        try:
            admin_auth.delete_user(user_id)
        except Exception as exc:
            log_error(
                "Auth user rollback failed",
                user_id=user_id,
                exception_type=type(exc).__name__,
            )
        raise UserCreationError()

    log_audit_event(
        user_id=actor_id,
        user_role="admin",
        action="create_staff_user",
        resource_type="profiles",
        resource_id=user_id,
        new_value={"email": normalized_email, "role": role},
        status="success",
    )

    log_info("Staff user created", user_id=user_id, email=normalized_email, role=role)
    return insert_res.data[0]


def _is_duplicate_email_error(exc: Any) -> bool:
    """Map Supabase auth 'email already registered' responses to a 409."""
    code = getattr(exc, "code", None)
    if code in {"email_exists", "user_already_exists"}:
        return True
    message = str(getattr(exc, "message", "") or "").lower()
    if "email_exists" in message or "already registered" in message:
        return True
    return (
        getattr(exc, "status", None) == 422
        and "email" in message
        and ("exist" in message or "already" in message)
    )
