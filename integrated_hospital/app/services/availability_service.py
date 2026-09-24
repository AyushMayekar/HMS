"""
Doctor availability service.
CRUD operations for bookable time slots.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from app.config.settings import get_supabase_admin_client
from app.services.audit_service import log_audit_event
from app.utils.exceptions import AvailabilityNotFoundError, InvalidOperationError
from app.utils.logger import log_info


BOOKING_WINDOW_DAYS = 30


def list_availability(
    *,
    department_id: str | None = None,
    doctor_id: str | None = None,
    slot_date: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """
    List doctor availability slots.

    For available/bookable slots, when no explicit date filter is supplied,
    only slots within the 30-day booking window are returned.

    Explicit date filters always take precedence.
    """

    admin_supabase = get_supabase_admin_client()

    # ---------------------------------------------------------------
    # BOOKING WINDOW
    # ---------------------------------------------------------------
    # Patient booking/rescheduling calls use status="available" without
    # providing dates. In that case, automatically restrict the query
    # to today through today + 29 days.
    #
    # Example:
    #   today       = 2026-09-24
    #   start_date  = 2026-09-24
    #   end_date    = 2026-10-23
    #
    # This filter is applied BEFORE pagination, so historical rows
    # cannot consume the first 50 results.
    # ---------------------------------------------------------------
    if (
        status == "available"
        and slot_date is None
        and start_date is None
        and end_date is None
    ):
        today = date.today()

        start_date = today.isoformat()
        end_date = (
            today + timedelta(days=BOOKING_WINDOW_DAYS - 1)
        ).isoformat()

    # ---------------------------------------------------------------
    # QUERY
    # ---------------------------------------------------------------
    query = (
        admin_supabase
        .table("doctor_availability")
        .select("*", count="exact")
    )

    if department_id:
        query = query.eq("department_id", department_id)

    if doctor_id:
        query = query.eq("doctor_id", doctor_id)

    if slot_date:
        query = query.eq("slot_date", slot_date)

    if start_date:
        query = query.gte("slot_date", start_date)

    if end_date:
        query = query.lte("slot_date", end_date)

    if status:
        query = query.eq("status", status)

    # ---------------------------------------------------------------
    # ORDER + PAGINATION
    # ---------------------------------------------------------------
    response = (
        query
        .order("slot_date", desc=False)
        .order("start_time", desc=False)
        .range(offset, offset + limit - 1)
        .execute()
    )

    # ---------------------------------------------------------------
    # SAFETY FILTER
    # ---------------------------------------------------------------
    # Supabase/PostgREST cannot safely compare one column against
    # another using:
    #
    #     .lt("booked_count", "slot_capacity")
    #
    # Therefore we do the capacity check in Python after retrieval.
    #
    # This only applies to normal "available" booking requests.
    # ---------------------------------------------------------------
    rows = response.data or []

    if status == "available":
        rows = [
            row
            for row in rows
            if (
                row.get("booked_count") is not None
                and row.get("slot_capacity") is not None
                and row["booked_count"] < row["slot_capacity"]
            )
        ]

    return {
        "availability": rows,
        "total": response.count or 0,
        "limit": limit,
        "offset": offset,
    }


def get_availability(availability_id: str) -> dict[str, Any]:
    """Retrieve a single doctor availability slot by ID."""

    admin_supabase = get_supabase_admin_client()

    response = (
        admin_supabase
        .table("doctor_availability")
        .select("*")
        .eq("availability_id", availability_id)
        .execute()
    )

    if not response.data:
        raise AvailabilityNotFoundError(availability_id)

    return response.data[0]


def create_availability(
    *,
    doctor_id: str,
    department_id: str,
    slot_date: str,
    start_time: str,
    end_time: str,
    slot_capacity: int = 5,
    actor_id: str,
    actor_role: str,
) -> dict[str, Any]:
    """Create a new availability slot (admin/staff only)."""

    admin_supabase = get_supabase_admin_client()

    now = datetime.now(timezone.utc)
    availability_id = str(uuid4())

    payload = {
        "availability_id": availability_id,
        "doctor_id": doctor_id,
        "department_id": department_id,
        "slot_date": slot_date,
        "start_time": start_time,
        "end_time": end_time,
        "slot_capacity": slot_capacity,
        "booked_count": 0,
        "status": "available",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    insert_res = (
        admin_supabase
        .table("doctor_availability")
        .insert(payload)
        .execute()
    )

    if not insert_res.data:
        raise InvalidOperationError(
            "Failed to create availability slot."
        )

    log_audit_event(
        user_id=actor_id,
        user_role=actor_role,
        action="create_availability",
        resource_type="doctor_availability",
        resource_id=availability_id,
        new_value={
            "doctor_id": doctor_id,
            "slot_date": slot_date,
            "start_time": start_time,
        },
    )

    log_info(
        "Availability slot created",
        availability_id=availability_id,
        doctor_id=doctor_id,
    )

    return insert_res.data[0]