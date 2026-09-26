"""
Doctor management service.
CRUD operations for doctor records and availability.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.config.settings import get_supabase_admin_client
from app.schema.admin import DoctorSlotSchedule
from app.services.audit_service import log_audit_event
from app.services.availability_service import (
    build_availability_rows,
    insert_availability_rows,
)
from app.utils.exceptions import DoctorNotFoundError, InvalidOperationError
from app.utils.logger import log_error, log_info


def list_doctors(
    *,
    department_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """List doctors with optional filters."""
    admin_supabase = get_supabase_admin_client()

    query = admin_supabase.table("doctors").select("*", count="exact")

    if department_id:
        query = query.eq("department_id", department_id)
    if status:
        query = query.eq("status", status)

    response = query.order("full_name").range(offset, offset + limit - 1).execute()

    return {
        "doctors": response.data or [],
        "total": response.count or 0,
        "limit": limit,
        "offset": offset,
    }


def get_doctor(doctor_id: str) -> dict[str, Any]:
    """Get a single doctor by ID."""
    admin_supabase = get_supabase_admin_client()

    response = (
        admin_supabase
        .table("doctors")
        .select("*")
        .eq("doctor_id", doctor_id)
        .execute()
    )

    if not response.data:
        raise DoctorNotFoundError(doctor_id)

    return response.data[0]


def create_doctor(
    *,
    department_id: str,
    full_name: str,
    specialization: str,
    experience_years: int,
    status: str = "active",
    slot_schedule: DoctorSlotSchedule | None = None,
    actor_id: str,
    actor_role: str,
) -> dict[str, Any]:
    """
    Create a new doctor record (admin only), optionally generating bookable
    availability slots for that doctor in the same request.

    Returns ``{"doctor", "slot_summary", "slot_warning"}``. ``slot_summary`` is
    ``None`` when no schedule was requested; ``slot_warning`` is only set when
    the doctor row committed but slot generation failed — the doctor still
    exists, so the request must not be reported as a failure.
    """
    admin_supabase = get_supabase_admin_client()

    now = datetime.now(timezone.utc)
    doctor_id = str(uuid4())

    # Expand (and validate) the schedule BEFORE writing the doctor row, so a
    # rejected schedule never leaves a half-created doctor behind.
    planned_rows = (
        build_availability_rows(
            doctor_id=doctor_id,
            department_id=department_id,
            schedule=slot_schedule,
        )
        if slot_schedule is not None
        else []
    )

    payload = {
        "doctor_id": doctor_id,
        "department_id": department_id,
        "full_name": full_name,
        "specialization": specialization,
        "experience_years": experience_years,
        "status": status,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    insert_res = admin_supabase.table("doctors").insert(payload).execute()

    if not insert_res.data:
        raise InvalidOperationError("Failed to create doctor record.")

    log_audit_event(
        user_id=actor_id,
        user_role=actor_role,
        action="create_doctor",
        resource_type="doctors",
        resource_id=doctor_id,
        new_value={"full_name": full_name, "department_id": department_id},
    )

    log_info("Doctor created", doctor_id=doctor_id, full_name=full_name)

    slot_summary: dict[str, Any] | None = None
    slot_warning: str | None = None

    if planned_rows:
        try:
            slot_summary = insert_availability_rows(
                planned_rows,
                doctor_id=doctor_id,
                actor_id=actor_id,
                actor_role=actor_role,
            )
        except Exception as exc:  # noqa: BLE001 - the doctor row already committed
            log_error(
                "Doctor created but availability generation failed",
                doctor_id=doctor_id,
                error=str(exc),
            )
            slot_warning = (
                "Doctor created, but availability slots could not be generated "
                "(no slots exist for this doctor yet)."
            )

    return {
        "doctor": insert_res.data[0],
        "slot_summary": slot_summary,
        "slot_warning": slot_warning,
    }


def update_doctor(
    *,
    doctor_id: str,
    department_id: str | None = None,
    full_name: str | None = None,
    specialization: str | None = None,
    experience_years: int | None = None,
    status: str | None = None,
    actor_id: str,
    actor_role: str,
) -> dict[str, Any]:
    """Update a doctor record (admin only)."""
    admin_supabase = get_supabase_admin_client()

    existing = admin_supabase.table("doctors").select("*").eq("doctor_id", doctor_id).execute()
    if not existing.data:
        raise DoctorNotFoundError(doctor_id)

    update_fields: dict[str, Any] = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if department_id is not None:
        update_fields["department_id"] = department_id
    if full_name is not None:
        update_fields["full_name"] = full_name
    if specialization is not None:
        update_fields["specialization"] = specialization
    if experience_years is not None:
        update_fields["experience_years"] = experience_years
    if status is not None:
        update_fields["status"] = status

    if len(update_fields) <= 1:
        return existing.data[0]

    update_res = (
        admin_supabase
        .table("doctors")
        .update(update_fields)
        .eq("doctor_id", doctor_id)
        .execute()
    )

    log_audit_event(
        user_id=actor_id,
        user_role=actor_role,
        action="update_doctor",
        resource_type="doctors",
        resource_id=doctor_id,
        old_value=existing.data[0],
        new_value=update_fields,
    )

    log_info("Doctor updated", doctor_id=doctor_id)
    return update_res.data[0] if update_res.data else existing.data[0]
