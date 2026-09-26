"""
Doctor availability service.
CRUD operations for bookable time slots.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from app.config.settings import get_supabase_admin_client
from app.schema.admin import DoctorSlotSchedule
from app.services.audit_service import log_audit_event
from app.utils.exceptions import AvailabilityNotFoundError, InvalidOperationError
from app.utils.logger import log_info


BOOKING_WINDOW_DAYS = 30

# One bulk insert covers a full week of slots (98 rows at the default
# schedule); the chunk only exists so a pathological schedule cannot
# exceed PostgREST's request-size limits.
INSERT_CHUNK_SIZE = 500


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


def _normalize_time(value: Any) -> str:
    """Normalise a time to ``HH:MM:SS`` so de-duplication is exact.

    PostgREST returns ``time`` columns as ``HH:MM:SS`` while callers may send
    ``HH:MM``; both must compare equal.
    """
    text = str(value or "").strip()
    if len(text) >= 8:
        return text[:8]
    if len(text) == 5:
        return f"{text}:00"
    return text


def build_availability_rows(
    *,
    doctor_id: str,
    department_id: str,
    schedule: DoctorSlotSchedule,
) -> list[dict[str, Any]]:
    """
    Expand a schedule into concrete ``doctor_availability`` rows.

    Pure function — it writes nothing, so callers can validate the schedule
    before committing the doctor record. The date range is checked against the
    30-day booking window because ``GET /catalog/availability`` only ever
    serves ``today .. today + 29``; slots outside it could never be booked.
    """
    today = date.today()
    first_day = schedule.start_date
    last_day = first_day + timedelta(days=schedule.days - 1)
    booking_end = today + timedelta(days=BOOKING_WINDOW_DAYS - 1)

    if first_day < today:
        raise InvalidOperationError("The slot start date cannot be in the past.")

    if last_day > booking_end:
        raise InvalidOperationError(
            f"Slots can only be created within the {BOOKING_WINDOW_DAYS}-day booking "
            f"window (through {booking_end.isoformat()})."
        )

    # Daily window minus the optional break, e.g. 09:00-13:00 + 14:00-17:00.
    windows = [(schedule.start_time, schedule.end_time)]
    if schedule.break_start is not None and schedule.break_end is not None:
        windows = [
            (schedule.start_time, schedule.break_start),
            (schedule.break_end, schedule.end_time),
        ]

    slot_delta = timedelta(minutes=schedule.slot_minutes)
    created_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []

    day = first_day
    while day <= last_day:
        for window_start, window_close_time in windows:
            cursor = datetime.combine(day, window_start)
            window_close = datetime.combine(day, window_close_time)

            while cursor + slot_delta <= window_close:
                slot_end = cursor + slot_delta
                rows.append(
                    {
                        "availability_id": str(uuid4()),
                        "doctor_id": doctor_id,
                        "department_id": department_id,
                        "slot_date": day.isoformat(),
                        "start_time": cursor.strftime("%H:%M:%S"),
                        "end_time": slot_end.strftime("%H:%M:%S"),
                        "slot_capacity": schedule.slot_capacity,
                        "booked_count": 0,
                        "status": "available",
                        "created_at": created_at,
                        "updated_at": created_at,
                    }
                )
                cursor = slot_end
        day += timedelta(days=1)

    if not rows:
        raise InvalidOperationError("The requested schedule would not create any slots.")

    return rows


def insert_availability_rows(
    rows: list[dict[str, Any]],
    *,
    doctor_id: str,
    actor_id: str,
    actor_role: str,
) -> dict[str, Any]:
    """
    Bulk-insert generated rows, skipping any ``(slot_date, start_time)`` the
    doctor already has, then write a single audit entry for the batch.

    Returns a summary: ``created`` / ``skipped`` / ``start_date`` / ``end_date``.
    """
    if not rows:
        return {"created": 0, "skipped": 0, "start_date": None, "end_date": None}

    admin_supabase = get_supabase_admin_client()

    slot_dates = sorted({row["slot_date"] for row in rows})

    existing_res = (
        admin_supabase
        .table("doctor_availability")
        .select("slot_date, start_time")
        .eq("doctor_id", doctor_id)
        .gte("slot_date", slot_dates[0])
        .lte("slot_date", slot_dates[-1])
        .execute()
    )
    existing = {
        (str(row.get("slot_date")), _normalize_time(row.get("start_time")))
        for row in (existing_res.data or [])
    }

    pending = [
        row
        for row in rows
        if (row["slot_date"], _normalize_time(row["start_time"])) not in existing
    ]
    skipped = len(rows) - len(pending)

    created = 0
    for index in range(0, len(pending), INSERT_CHUNK_SIZE):
        chunk = pending[index : index + INSERT_CHUNK_SIZE]
        insert_res = (
            admin_supabase
            .table("doctor_availability")
            .insert(chunk)
            .execute()
        )
        if not insert_res.data:
            raise InvalidOperationError("Failed to create availability slots.")
        created += len(insert_res.data)

    created_dates = sorted({row["slot_date"] for row in pending})
    summary = {
        "created": created,
        "skipped": skipped,
        "start_date": created_dates[0] if created_dates else None,
        "end_date": created_dates[-1] if created_dates else None,
    }

    if created:
        log_audit_event(
            user_id=actor_id,
            user_role=actor_role,
            action="create_availability_schedule",
            resource_type="doctor_availability",
            resource_id=doctor_id,
            new_value=summary,
        )

    log_info(
        "Availability schedule created",
        doctor_id=doctor_id,
        created=created,
        skipped=skipped,
    )

    return summary