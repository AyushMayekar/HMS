"""
Reminder service.
Staff/admin create reminders; patients view their own reminders.
Spec §16: staff reminder list = fixed 24-hour reminder model over every
upcoming appointment, with the backend's no-show prediction.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.config.settings import get_supabase_admin_client
from app.services.audit_service import log_audit_event
from app.services.staff_appointment_service import _enrich_appointments
from app.utils.exceptions import AppointmentNotFoundError, InvalidOperationError
from app.utils.logger import log_info

# Fixed 24-hour reminder model (spec §16): reminders go out 24h before the
# appointment; the value reported for appointments without a reminder row.
DEFAULT_REMINDER_HOURS = 24.0


def create_staff_reminder(
    *,
    staff_id: str,
    staff_role: str,
    appointment_id: str,
    reminder_type: str = "in_app",
    hours_before_appointment: float = 24.0,
    message: str = "",
) -> dict[str, Any]:
    """Create an appointment reminder initiated by staff/admin."""
    admin_supabase = get_supabase_admin_client()

    # Verify appointment exists
    appt_res = (
        admin_supabase
        .table("appointments")
        .select("appointment_id, patient_id, appointment_status, scheduled_start")
        .eq("appointment_id", appointment_id)
        .execute()
    )
    if not appt_res.data:
        raise AppointmentNotFoundError(appointment_id)

    appointment = appt_res.data[0]
    patient_id = appointment.get("patient_id")
    if not patient_id:
        raise InvalidOperationError("Appointment has no patient associated.")

    now = datetime.now(timezone.utc)
    reminder_id = str(uuid4())

    reminder_payload = {
        "reminder_id": reminder_id,
        "appointment_id": appointment_id,
        "patient_id": patient_id,
        "sent_by": staff_id,
        "reminder_type": reminder_type,
        "sent_at": now.isoformat(),
        "hours_before_appointment": hours_before_appointment,
        "status": "sent",
        "message": message or f"Reminder for your appointment on {appointment.get('scheduled_start', 'N/A')}",
        "created_at": now.isoformat(),
    }

    insert_res = admin_supabase.table("reminders").insert(reminder_payload).execute()
    if not insert_res.data:
        raise InvalidOperationError("Failed to record reminder.")

    # Update appointment reminder flags
    try:
        admin_supabase.table("appointments").update({
            "reminder_sent": True,
            "reminder_hours_before": hours_before_appointment,
            "updated_at": now.isoformat(),
        }).eq("appointment_id", appointment_id).execute()
    except Exception:
        pass  # Non-fatal if flags aren't updated

    log_audit_event(
        user_id=staff_id,
        user_role=staff_role,
        action="create_reminder",
        resource_type="reminders",
        resource_id=reminder_id,
        old_value=None,
        new_value={"appointment_id": appointment_id, "patient_id": patient_id},
        status="success",
    )

    log_info("Reminder created", staff_id=staff_id, reminder_id=reminder_id, appointment_id=appointment_id)
    return insert_res.data[0]


def list_patient_reminders(
    *,
    patient_id: str,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """List reminders sent to the authenticated patient (read-only)."""
    admin_supabase = get_supabase_admin_client()

    response = (
        admin_supabase
        .table("reminders")
        .select("*", count="exact")
        .eq("patient_id", patient_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )

    return {
        "reminders": response.data or [],
        "total": response.count or 0,
        "limit": limit,
        "offset": offset,
    }


def _resolve_no_show_prediction(
    appointment_id: str | None,
    stored_entry: dict[str, Any] | None,
) -> tuple[Any, Any, Any, Any]:
    """
    (no_show_probability, risk_level, predicted_no_show, last_scored_at) for
    one appointment.

    Prefers the latest SUCCESSFUL stored prediction (prediction_logs) — real
    backend data already scored for this visit.

    Listing never runs inference: the previous fallback scored each
    appointment live inside ``GET /staff/reminders``, which cost ~2 sequential
    database round-trips per row (~370 ms) and made the staff dashboard/reminders
    page take ~77 s for ``limit=200`` — far beyond the 30 s client timeout.
    Scores are now produced only by the explicit selection action
    (``POST /predictions/no-show-batch``, max 10) or the scheduled 24h job;
    appointments that have not been scored yet simply report ``None``.
    """
    if stored_entry is None:
        return None, None, None, None

    prediction = stored_entry.get("prediction")
    if isinstance(prediction, str):
        try:
            prediction = json.loads(prediction)
        except (TypeError, ValueError):
            prediction = None
    if isinstance(prediction, dict):
        # NOTE: a rule-based prediction carries ``risk_score`` but no
        # ``no_show_probability`` — ``.get`` keeps it None instead of
        # fabricating a percentage.
        return (
            prediction.get("no_show_probability"),
            prediction.get("risk_level"),
            prediction.get("no_show"),
            stored_entry.get("predicted_at"),
        )
    return None, None, None, None


def list_reminders(
    *,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """
    List upcoming appointments for the staff reminders view (spec §16).

    Returns EVERY upcoming appointment — with or without an existing reminder
    row — enriched with real patient/doctor/department names, reminder fields
    flattened when a reminder exists, and the stored no-show prediction when
    one exists (listing never runs inference — see ``_resolve_no_show_prediction``).
    Reminder timing is the fixed 24-hour model (hours_before_appointment defaults to 24).
    """
    admin_supabase = get_supabase_admin_client()
    now = datetime.now(timezone.utc)

    response = (
        admin_supabase
        .table("appointments")
        .select("*", count="exact")
        .eq("appointment_status", "booked")
        .gte("scheduled_start", now.isoformat())
        .order("scheduled_start")
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows = _enrich_appointments(admin_supabase, response.data or [])

    appointment_ids = [r.get("appointment_id") for r in rows if r.get("appointment_id")]

    # Existing reminder rows — latest per appointment (real reminder state).
    reminder_by_appointment: dict[str, dict[str, Any]] = {}
    if appointment_ids:
        try:
            rem_res = (
                admin_supabase
                .table("reminders")
                .select("*")
                .in_("appointment_id", appointment_ids)
                .order("created_at", desc=True)
                .limit(500)
                .execute()
            )
            for rem in rem_res.data or []:
                appt_id = rem.get("appointment_id")
                if appt_id and appt_id not in reminder_by_appointment:
                    reminder_by_appointment[appt_id] = rem
        except Exception:
            reminder_by_appointment = {}

    # Latest successful stored no-show prediction per appointment.
    stored_prediction: dict[str, dict[str, Any]] = {}
    if appointment_ids:
        try:
            log_res = (
                admin_supabase
                .table("prediction_logs")
                .select("entity_id, predicted_at, prediction")
                .eq("prediction_type", "no_show")
                .eq("prediction_status", "success")
                .in_("entity_id", appointment_ids)
                .execute()
            )
            for entry in log_res.data or []:
                appt_id = entry.get("entity_id")
                if not appt_id:
                    continue
                previous = stored_prediction.get(appt_id)
                if previous is None or str(entry.get("predicted_at") or "") > str(previous.get("predicted_at") or ""):
                    stored_prediction[appt_id] = entry
        except Exception:
            stored_prediction = {}

    items: list[dict[str, Any]] = []
    for row in rows:
        appointment_id = row.get("appointment_id")
        item = dict(row)

        reminder = reminder_by_appointment.get(appointment_id) or {}
        item["reminder_id"] = reminder.get("reminder_id")
        item["reminder_type"] = reminder.get("reminder_type")
        item["sent_at"] = reminder.get("sent_at")
        item["reminder_created_at"] = reminder.get("created_at")
        reminder_hours = reminder.get("hours_before_appointment")
        item["hours_before_appointment"] = (
            reminder_hours if reminder_hours is not None else DEFAULT_REMINDER_HOURS
        )
        item["reminder_message"] = reminder.get("message")
        item["reminder_sent"] = bool(reminder) or bool(row.get("reminder_sent"))

        probability, risk_level, predicted_no_show, last_scored_at = _resolve_no_show_prediction(
            appointment_id, stored_prediction.get(appointment_id)
        )
        item["no_show_probability"] = probability
        item["risk_level"] = risk_level
        item["predicted_no_show"] = predicted_no_show
        item["last_scored_at"] = last_scored_at
        items.append(item)

    return {
        "reminders": items,
        "total": response.count or 0,
        "limit": limit,
        "offset": offset,
    }
