"""
Department management service.
CRUD operations for hospital departments.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.config.settings import get_supabase_admin_client
from app.services.audit_service import log_audit_event
from app.utils.exceptions import DepartmentNotFoundError, InvalidOperationError
from app.utils.logger import log_info


def list_departments(
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """List departments with optional status filter."""
    admin_supabase = get_supabase_admin_client()

    query = admin_supabase.table("departments").select("*", count="exact")

    if status:
        query = query.eq("status", status)

    response = query.order("name").range(offset, offset + limit - 1).execute()

    return {
        "departments": response.data or [],
        "total": response.count or 0,
        "limit": limit,
        "offset": offset,
    }


def get_department(department_id: str) -> dict[str, Any]:
    """Get a single department by ID."""
    admin_supabase = get_supabase_admin_client()

    response = (
        admin_supabase
        .table("departments")
        .select("*")
        .eq("department_id", department_id)
        .execute()
    )

    if not response.data:
        raise DepartmentNotFoundError(department_id)

    return response.data[0]


def create_department(
    *,
    name: str,
    description: str,
    information: str,
    status: str = "active",
    actor_id: str,
    actor_role: str,
) -> dict[str, Any]:
    """Create a new department (admin only)."""
    admin_supabase = get_supabase_admin_client()

    now = datetime.now(timezone.utc)
    department_id = str(uuid4())

    payload = {
        "department_id": department_id,
        "name": name,
        "description": description,
        "information": information,
        "status": status,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    insert_res = admin_supabase.table("departments").insert(payload).execute()

    if not insert_res.data:
        raise InvalidOperationError("Failed to create department.")

    log_audit_event(
        user_id=actor_id,
        user_role=actor_role,
        action="create_department",
        resource_type="departments",
        resource_id=department_id,
        new_value={"name": name, "status": status},
    )

    log_info("Department created", department_id=department_id, name=name)
    return insert_res.data[0]


def update_department(
    *,
    department_id: str,
    name: str | None = None,
    description: str | None = None,
    information: str | None = None,
    status: str | None = None,
    actor_id: str,
    actor_role: str,
) -> dict[str, Any]:
    """Update a department (admin only)."""
    admin_supabase = get_supabase_admin_client()

    # Verify exists
    existing = admin_supabase.table("departments").select("*").eq("department_id", department_id).execute()
    if not existing.data:
        raise DepartmentNotFoundError(department_id)

    update_fields = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if name is not None:
        update_fields["name"] = name
    if description is not None:
        update_fields["description"] = description
    if information is not None:
        update_fields["information"] = information
    if status is not None:
        update_fields["status"] = status

    if len(update_fields) <= 1:  # only updated_at
        return existing.data[0]

    update_res = (
        admin_supabase
        .table("departments")
        .update(update_fields)
        .eq("department_id", department_id)
        .execute()
    )

    log_audit_event(
        user_id=actor_id,
        user_role=actor_role,
        action="update_department",
        resource_type="departments",
        resource_id=department_id,
        old_value=existing.data[0],
        new_value=update_fields,
    )

    log_info("Department updated", department_id=department_id)
    return update_res.data[0] if update_res.data else existing.data[0]
