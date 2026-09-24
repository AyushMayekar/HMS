"""
Staff appointment service.
Operations for staff/admin to manage appointments.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.config.settings import get_supabase_admin_client
from app.config.time import get_current_datetime
from app.services.audit_service import log_audit_event
from app.services.prediction_service import predict_waiting_time
from app.utils.exceptions import (
    AppointmentInPastError,
    AppointmentNotFoundError,
    InvalidOperationError,
)
from app.utils.logger import log_info

# Service-start is only rejected once the scheduled time is long gone —
# a legitimately checked-in patient may start service a little late.
SERVICE_START_OVERDUE_MARGIN = timedelta(hours=6)


def _parse_scheduled_start(value: Any) -> datetime | None:
    """Parse an ISO scheduled_start into an aware datetime (naive => UTC)."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _assert_schedule_action_allowed(
    appointment: dict[str, Any],
    *,
    action: str,
    margin: timedelta = timedelta(0),
) -> None:
    """
    Reject lifecycle actions on past appointments with the standard
    CONFLICT/409 envelope. "Past" is evaluated against the configured
    hospital timezone (config/settings.py -> hospital_timezone) so the
    backend gate matches what staff see locally.
    """
    scheduled = _parse_scheduled_start(appointment.get("scheduled_start"))
    if scheduled is None:
        return
    if scheduled < get_current_datetime() - margin:
        raise AppointmentInPastError(
            f"Cannot {action}: the appointment's scheduled time "
            f"({appointment.get('scheduled_start')}) has already passed."
        )


def _enrich_appointments(admin_supabase, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Attach real display names alongside ids for staff operational views:
    patient_name / patient_email (profiles), doctor_name (doctors),
    department_name (departments, falling back to the row's stored value).
    """
    if not rows:
        return rows

    patient_ids = {r.get("patient_id") for r in rows if r.get("patient_id")}
    doctor_ids = {r.get("doctor_id") for r in rows if r.get("doctor_id")}
    department_ids = {r.get("department_id") for r in rows if r.get("department_id")}

    profiles_by_id: dict[str, dict[str, Any]] = {}
    doctors_by_id: dict[str, dict[str, Any]] = {}
    departments_by_id: dict[str, dict[str, Any]] = {}

    if patient_ids:
        res = (
            admin_supabase.table("profiles")
            .select("user_id, full_name, email")
            .in_("user_id", list(patient_ids))
            .execute()
        )
        profiles_by_id = {p.get("user_id"): p for p in (res.data or [])}
    if doctor_ids:
        res = (
            admin_supabase.table("doctors")
            .select("doctor_id, full_name")
            .in_("doctor_id", list(doctor_ids))
            .execute()
        )
        doctors_by_id = {d.get("doctor_id"): d for d in (res.data or [])}
    if department_ids:
        res = (
            admin_supabase.table("departments")
            .select("department_id, name")
            .in_("department_id", list(department_ids))
            .execute()
        )
        departments_by_id = {d.get("department_id"): d for d in (res.data or [])}

    enriched: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        profile = profiles_by_id.get(item.get("patient_id")) or {}
        item["patient_name"] = profile.get("full_name")
        item["patient_email"] = profile.get("email")
        item["doctor_name"] = (doctors_by_id.get(item.get("doctor_id")) or {}).get("full_name")
        if not item.get("department_name"):
            item["department_name"] = (
                departments_by_id.get(item.get("department_id")) or {}
            ).get("name")
        enriched.append(item)
    return enriched


def list_all_appointments(
    *,
    appointment_status: str | None = None,
    department_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """List all appointments (staff/admin operational scope)."""
    admin_supabase = get_supabase_admin_client()

    query = admin_supabase.table("appointments").select("*", count="exact")

    if appointment_status:
        query = query.eq("appointment_status", appointment_status)
    if department_id:
        query = query.eq("department_id", department_id)

    response = query.order("scheduled_start", desc=True).range(offset, offset + limit - 1).execute()

    return {
        "appointments": _enrich_appointments(admin_supabase, response.data or []),
        "total": response.count or 0,
        "limit": limit,
        "offset": offset,
    }


def get_appointment(appointment_id: str) -> dict[str, Any]:
    """Get a single appointment (staff/admin scope), with the same name
    enrichment as the list endpoint."""
    admin_supabase = get_supabase_admin_client()

    res = admin_supabase.table("appointments").select("*").eq("appointment_id", appointment_id).execute()
    if not res.data:
        raise AppointmentNotFoundError(appointment_id)

    return _enrich_appointments(admin_supabase, [res.data[0]])[0]


def check_in_appointment(
    *,
    appointment_id: str,
    actor_id: str,
    actor_role: str,
) -> dict[str, Any]:
    """
    Check in a patient. Records actual_checkin_time and calculates queue state.
    This triggers waiting-time prediction eligibility.
    """
    admin_supabase = get_supabase_admin_client()

    appt_res = admin_supabase.table("appointments").select("*").eq("appointment_id", appointment_id).execute()
    if not appt_res.data:
        raise AppointmentNotFoundError(appointment_id)

    appointment = appt_res.data[0]

    if appointment.get("appointment_status") != "booked":
        raise InvalidOperationError(f"Cannot check in an appointment with status '{appointment.get('appointment_status')}'.")

    # Past appointments can no longer be checked in (CONFLICT/409).
    _assert_schedule_action_allowed(appointment, action="check in the patient")

    now = datetime.now(timezone.utc)

    # Calculate queue state: patients ahead = checked-in patients in same department still waiting
    queue_res = (
        admin_supabase
        .table("appointments")
        .select("appointment_id")
        .eq("department_id", appointment.get("department_id"))
        .eq("appointment_status", "booked")
        .not_.is_("actual_checkin_time", "null")
        .is_("actual_service_start", "null")
        .lt("actual_checkin_time", now.isoformat())
        .execute()
    )
    patients_ahead = len(queue_res.data) if queue_res.data else 0

    # Queue length = total checked-in patients still waiting (same department)
    queue_length = patients_ahead + 1  # includes this patient

    update_fields = {
        "actual_checkin_time": now.isoformat(),
        "queue_length_at_checkin": queue_length,
        "patients_ahead_at_checkin": patients_ahead,
        "updated_at": now.isoformat(),
    }

    update_res = (
        admin_supabase
        .table("appointments")
        .update(update_fields)
        .eq("appointment_id", appointment_id)
        .execute()
    )

    log_audit_event(
        user_id=actor_id,
        user_role=actor_role,
        action="check_in_appointment",
        resource_type="appointments",
        resource_id=appointment_id,
        old_value={"actual_checkin_time": None},
        new_value=update_fields,
        status="success",
    )

    result = dict(update_res.data[0] if update_res.data else appointment)

    # Predicted waiting time at check-in (existing waiting-time prediction
    # service) — included so staff/patient dashboards can show it right after
    # check-in. Never fails the check-in itself.
    wait_minutes: float | None = None
    try:
        wait_prediction = predict_waiting_time(appointment_id)
        prediction = wait_prediction.get("prediction") or {}
        if wait_prediction.get("prediction_status") == "success":
            wait_minutes = prediction.get("predicted_wait_minutes")
    except Exception:
        wait_minutes = None
    result["predicted_waiting_min"] = wait_minutes
    result["predicted_wait_minutes"] = wait_minutes  # alias kept for existing UIs

    log_info(
        "Patient checked in",
        appointment_id=appointment_id,
        actor_id=actor_id,
        predicted_waiting_min=wait_minutes,
    )
    return result


def start_service(
    *,
    appointment_id: str,
    actor_id: str,
    actor_role: str,
) -> dict[str, Any]:
    """Record service start time."""
    admin_supabase = get_supabase_admin_client()

    appt_res = admin_supabase.table("appointments").select("*").eq("appointment_id", appointment_id).execute()
    if not appt_res.data:
        raise AppointmentNotFoundError(appointment_id)

    appointment = appt_res.data[0]

    if not appointment.get("actual_checkin_time"):
        raise InvalidOperationError("Cannot start service before check-in.")

    if appointment.get("actual_service_start"):
        raise InvalidOperationError("Service has already started.")

    # Stale records: only reject when the scheduled time is long past.
    _assert_schedule_action_allowed(
        appointment,
        action="start service",
        margin=SERVICE_START_OVERDUE_MARGIN,
    )

    now = datetime.now(timezone.utc)

    update_res = (
        admin_supabase
        .table("appointments")
        .update({
            "actual_service_start": now.isoformat(),
            "updated_at": now.isoformat(),
        })
        .eq("appointment_id", appointment_id)
        .execute()
    )

    log_audit_event(
        user_id=actor_id,
        user_role=actor_role,
        action="start_service",
        resource_type="appointments",
        resource_id=appointment_id,
        status="success",
    )

    log_info("Service started", appointment_id=appointment_id, actor_id=actor_id)
    return update_res.data[0] if update_res.data else appointment


def end_service(
    *,
    appointment_id: str,
    actor_id: str,
    actor_role: str,
) -> dict[str, Any]:
    """Record service end time and calculate actual wait."""
    admin_supabase = get_supabase_admin_client()

    appt_res = admin_supabase.table("appointments").select("*").eq("appointment_id", appointment_id).execute()
    if not appt_res.data:
        raise AppointmentNotFoundError(appointment_id)

    appointment = appt_res.data[0]

    if not appointment.get("actual_service_start"):
        raise InvalidOperationError("Cannot end service before starting it.")

    if appointment.get("actual_service_end"):
        raise InvalidOperationError("Service has already ended.")

    now = datetime.now(timezone.utc)

    # Calculate actual wait
    actual_wait_minutes = None
    if appointment.get("actual_checkin_time") and appointment.get("actual_service_start"):
        checkin = datetime.fromisoformat(appointment["actual_checkin_time"])
        service_start = datetime.fromisoformat(appointment["actual_service_start"])
        actual_wait_minutes = (service_start - checkin).total_seconds() / 60

    update_fields = {
        "actual_service_end": now.isoformat(),
        "actual_wait_minutes": round(actual_wait_minutes, 2) if actual_wait_minutes is not None else None,
        "waiting_time_target": round(actual_wait_minutes, 2) if actual_wait_minutes is not None else None,
        "appointment_status": "completed",
        "updated_at": now.isoformat(),
    }

    update_res = (
        admin_supabase
        .table("appointments")
        .update(update_fields)
        .eq("appointment_id", appointment_id)
        .execute()
    )

    log_audit_event(
        user_id=actor_id,
        user_role=actor_role,
        action="end_service",
        resource_type="appointments",
        resource_id=appointment_id,
        status="success",
    )

    log_info("Service ended", appointment_id=appointment_id, actor_id=actor_id, wait_minutes=actual_wait_minutes)
    return update_res.data[0] if update_res.data else appointment


def mark_no_show(
    *,
    appointment_id: str,
    actor_id: str,
    actor_role: str,
) -> dict[str, Any]:
    """Mark an appointment as no-show."""
    admin_supabase = get_supabase_admin_client()

    appt_res = admin_supabase.table("appointments").select("*").eq("appointment_id", appointment_id).execute()
    if not appt_res.data:
        raise AppointmentNotFoundError(appointment_id)

    appointment = appt_res.data[0]

    if appointment.get("appointment_status") != "booked":
        raise InvalidOperationError(f"Cannot mark no-show for appointment with status '{appointment.get('appointment_status')}'.")

    # Past appointments can no longer be marked no-show (CONFLICT/409).
    _assert_schedule_action_allowed(appointment, action="mark the appointment no-show")

    now = datetime.now(timezone.utc)

    update_res = (
        admin_supabase
        .table("appointments")
        .update({
            "appointment_status": "no_show",
            "no_show_target": True,
            "updated_at": now.isoformat(),
        })
        .eq("appointment_id", appointment_id)
        .execute()
    )

    log_audit_event(
        user_id=actor_id,
        user_role=actor_role,
        action="mark_no_show",
        resource_type="appointments",
        resource_id=appointment_id,
        status="success",
    )

    log_info("Appointment marked no-show", appointment_id=appointment_id, actor_id=actor_id)
    return update_res.data[0] if update_res.data else appointment
