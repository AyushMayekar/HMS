"""
Patient appointment service.
Handles appointment booking, listing, rescheduling, and cancellation.
Booking flow validates doctor/slot, calculates patient history, and creates records.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.config.settings import get_supabase_admin_client
from app.services.audit_service import log_audit_event
from app.utils.exceptions import (
    AppointmentNotFoundError,
    AvailabilityNotFoundError,
    DoctorNotFoundError,
    ForbiddenError,
    InvalidOperationError,
    SlotUnavailableError,
)
from app.utils.logger import log_info


def _calculate_patient_history(admin_supabase, patient_id: str) -> dict[str, Any]:
    """Calculate patient history features from prior appointments (before now)."""
    now = datetime.now(timezone.utc)

    prior_res = (
        admin_supabase
        .table("appointments")
        .select("*")
        .eq("patient_id", patient_id)
        .lt("booked_at", now.isoformat())
        .order("booked_at", desc=False)
        .execute()
    )

    prior_appointments = prior_res.data or []

    total_count = len(prior_appointments)
    completed_count = sum(1 for a in prior_appointments if a.get("appointment_status") == "completed")
    no_show_count = sum(1 for a in prior_appointments if a.get("appointment_status") == "no_show")
    cancellation_count = sum(1 for a in prior_appointments if a.get("appointment_status") == "cancelled")

    no_show_rate = no_show_count / total_count if total_count > 0 else 0.0

    # Average wait time from completed appointments with actual_wait_minutes
    wait_times = [
        a["actual_wait_minutes"]
        for a in prior_appointments
        if a.get("actual_wait_minutes") is not None and a.get("appointment_status") == "completed"
    ]
    avg_wait = sum(wait_times) / len(wait_times) if wait_times else 0.0

    # Average payment delay
    delays = [
        a["billing_delay_days"]
        for a in prior_appointments
        if a.get("billing_delay_days") is not None
    ]
    avg_delay = sum(delays) / len(delays) if delays else 0.0

    return {
        "is_new_patient": total_count == 0,
        "past_appointment_count": total_count,
        "past_completed_count": completed_count,
        "past_no_show_count": no_show_count,
        "past_cancellation_count": cancellation_count,
        "past_no_show_rate": round(no_show_rate, 4),
        "past_avg_wait_minutes": round(avg_wait, 2),
        "past_avg_payment_delay_days": round(avg_delay, 2),
    }


def _calculate_department_context(admin_supabase, department_id: str, slot_date: str) -> dict[str, Any]:
    """Calculate department operational context for the slot date."""
    # Count scheduled appointments for department on that date
    scheduled_res = (
        admin_supabase
        .table("appointments")
        .select("appointment_id", count="exact")
        .eq("department_id", department_id)
        .gte("scheduled_start", f"{slot_date}T00:00:00")
        .lt("scheduled_start", f"{slot_date}T23:59:59")
        .execute()
    )

    department_scheduled_today = scheduled_res.count or 0

    # Count active doctors in department
    active_doctors_res = (
        admin_supabase
        .table("doctors")
        .select("doctor_id", count="exact")
        .eq("department_id", department_id)
        .eq("status", "active")
        .execute()
    )

    department_active_doctors = active_doctors_res.count or 0

    # Count active staff (patients with role staff/admin)
    active_staff_res = (
        admin_supabase
        .table("profiles")
        .select("user_id", count="exact")
        .in_("role", ["staff", "admin"])
        .eq("status", "active")
        .execute()
    )

    department_active_staff = active_staff_res.count or 0

    return {
        "department_scheduled_today": department_scheduled_today,
        "department_active_doctors": department_active_doctors,
        "department_active_staff": department_active_staff,
    }


def _calculate_slot_context(slot: dict[str, Any]) -> dict[str, Any]:
    """Calculate slot capacity/utilization from availability record.

    slot_booked_count includes this appointment, and slot_utilization_pct must
    satisfy slot_utilization_pct == slot_booked_count / slot_capacity * 100 —
    the exact invariant of the training data (verified: 100% of seed rows).
    The previous version computed utilization from the PRE-increment count,
    feeding the model a utilization that disagreed with the stored booked
    count (train/serve skew).
    """
    slot_capacity = slot.get("slot_capacity", 1)
    booked_count = slot.get("booked_count", 0)
    booked_with_this = booked_count + 1
    utilization = (booked_with_this / slot_capacity * 100) if slot_capacity > 0 else 0.0

    return {
        "slot_capacity": slot_capacity,
        "slot_booked_count": booked_with_this,  # includes this appointment
        "slot_utilization_pct": round(utilization, 2),
    }


def _parse_slot_timestamp(value: str) -> datetime:
    """
    Parse a slot timestamp into an aware datetime.

    Accepts both 'YYYY-MM-DDTHH:MM' and the database's 'YYYY-MM-DDTHH:MM:SS'
    form (PostgreSQL time values always include seconds), e.g.
    '2026-09-23T10:30:00'. The previous implementation used
    ``datetime.strptime(value, "%Y-%m-%dT%H:%M")``, which raised
    ``ValueError: unconverted data remains: :00`` for any real slot time and
    produced a naive datetime that could not be subtracted from the aware
    ``datetime.now(timezone.utc)`` (TypeError).

    Naive values are interpreted as UTC so they share a clock with ``now``
    and with the UTC timestamps this record stores in ``booked_at`` /
    ``created_at``.
    """
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def book_appointment(
    *,
    patient_id: str,
    doctor_id: str,
    availability_id: str,
    reason: str | None = None,
    booking_channel: str = "form",
) -> dict[str, Any]:
    """
    Book an appointment for a patient.
    1. Verify doctor exists and is active.
    2. Verify availability slot, belongs to doctor, has capacity.
    3. Calculate patient history features.
    4. Calculate department and slot context.
    5. Create appointment record with all booking-time fields.
    6. Increment booked_count on slot.
    7. Audit log.
    """
    admin_supabase = get_supabase_admin_client()

    # 1. Verify doctor exists
    doc_res = (
        admin_supabase
        .table("doctors")
        .select("doctor_id, full_name, department_id, experience_years, status")
        .eq("doctor_id", doctor_id)
        .execute()
    )
    if not doc_res.data:
        raise DoctorNotFoundError(doctor_id)

    doctor = doc_res.data[0]
    if doctor.get("status") != "active":
        raise InvalidOperationError("The selected doctor is not currently available.")

    # 2. Verify availability slot
    slot_res = (
        admin_supabase
        .table("doctor_availability")
        .select("*")
        .eq("availability_id", availability_id)
        .execute()
    )
    if not slot_res.data:
        raise AvailabilityNotFoundError(availability_id)

    slot = slot_res.data[0]

    if slot["doctor_id"] != doctor_id:
        raise InvalidOperationError("The selected availability slot does not belong to the specified doctor.")

    if slot.get("status") != "available":
        raise SlotUnavailableError("The selected availability slot is not marked as available.")

    slot_capacity = slot.get("slot_capacity", 1)
    booked_count = slot.get("booked_count", 0)
    if booked_count >= slot_capacity:
        raise SlotUnavailableError("The selected availability slot has reached maximum capacity.")

    # 3. Build appointment record
    department_id = doctor.get("department_id") or slot.get("department_id")

    # Fetch department name
    department_name = None
    if department_id:
        dept_res = (
            admin_supabase
            .table("departments")
            .select("name")
            .eq("department_id", department_id)
            .execute()
        )
        if dept_res.data:
            department_name = dept_res.data[0].get("name")

    slot_date = slot["slot_date"]
    start_time = slot["start_time"]
    end_time = slot["end_time"]
    # Stored verbatim as "<date>T<time>". The database returns times as
    # HH:MM:SS (e.g. "2026-09-23T10:30:00"), so anything parsing these
    # values must use ISO parsing rather than a seconds-less format.
    scheduled_start = f"{slot_date}T{start_time}"
    scheduled_end = f"{slot_date}T{end_time}"

    # Parse the slot start once; every schedule feature below is derived
    # from this datetime object instead of re-parsing strings by hand.
    try:
        slot_start_dt = _parse_slot_timestamp(scheduled_start)
    except (TypeError, ValueError) as exc:
        raise InvalidOperationError(
            "The selected availability slot has an invalid date or time."
        ) from exc

    now = datetime.now(timezone.utc)
    appointment_id = str(uuid4())

    # Calculate booking-time features
    patient_history = _calculate_patient_history(admin_supabase, patient_id)
    slot_context = _calculate_slot_context(slot)
    dept_context = _calculate_department_context(admin_supabase, department_id, slot_date)

    # Schedule features derived from the parsed slot start
    appointment_hour = slot_start_dt.hour
    appointment_weekday = slot_start_dt.weekday()
    appointment_month = slot_start_dt.month

    # Lead time: hours from now until the scheduled start (never negative)
    lead_time_hours = max(0.0, (slot_start_dt - now).total_seconds() / 3600)

    # Payment requirement (simplified: always require payment for new visits)
    payment_required = True
    payment_status_at_booking = "pending"
    invoice_amount = 500.0  # default base amount
    insurance_used = False
    claim_required = False

    appointment_payload = {
        "appointment_id": appointment_id,
        "patient_id": patient_id,
        "doctor_id": doctor_id,
        "department_id": department_id,
        "department_name": department_name,
        "doctor_experience_years": doctor.get("experience_years", 0),
        "appointment_type": "new_visit" if patient_history["is_new_patient"] else "follow_up",
        "booking_channel": booking_channel,
        "booked_at": now.isoformat(),
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "lead_time_hours": round(lead_time_hours, 2),
        "appointment_hour": appointment_hour,
        "appointment_weekday": appointment_weekday,
        "appointment_month": appointment_month,
        # Patient history
        **patient_history,
        # Slot / capacity context
        **slot_context,
        # Department context
        **dept_context,
        # Reminder (not yet sent)
        "reminder_sent": False,
        "reminder_hours_before": None,
        # Payment context
        "payment_required": payment_required,
        "payment_status_at_booking": payment_status_at_booking,
        "invoice_amount": invoice_amount,
        "insurance_used": insurance_used,
        "claim_required": claim_required,
        # Status
        "appointment_status": "booked",
        # Audit
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    insert_res = (
        admin_supabase
        .table("appointments")
        .insert(appointment_payload)
        .execute()
    )
    if not insert_res.data:
        raise InvalidOperationError("Failed to create appointment record.")

    # 4. Increment booked_count on slot
    admin_supabase.table("doctor_availability").update(
        {"booked_count": booked_count + 1, "updated_at": now.isoformat()}
    ).eq("availability_id", availability_id).execute()

    # 5. Audit log
    log_audit_event(
        user_id=patient_id,
        user_role="patient",
        action="book_appointment",
        resource_type="appointments",
        resource_id=appointment_id,
        old_value=None,
        new_value={
            "doctor_id": doctor_id,
            "availability_id": availability_id,
            "scheduled_start": scheduled_start,
        },
        status="success",
    )

    log_info("Appointment booked by patient", patient_id=patient_id, appointment_id=appointment_id)
    return insert_res.data[0]


def list_patient_appointments(
    *,
    patient_id: str,
    appointment_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """List appointments scoped to the authenticated patient."""
    admin_supabase = get_supabase_admin_client()

    query = (
        admin_supabase
        .table("appointments")
        .select("*", count="exact")
        .eq("patient_id", patient_id)
    )

    if appointment_status:
        query = query.eq("appointment_status", appointment_status)

    response = query.order("scheduled_start", desc=True).range(offset, offset + limit - 1).execute()

    return {
        "appointments": response.data or [],
        "total": response.count or 0,
        "limit": limit,
        "offset": offset,
    }


def get_patient_appointment(
    *,
    patient_id: str,
    appointment_id: str,
) -> dict[str, Any]:
    """Retrieve a single appointment, enforcing patient ownership."""
    admin_supabase = get_supabase_admin_client()

    appt_res = (
        admin_supabase
        .table("appointments")
        .select("*")
        .eq("appointment_id", appointment_id)
        .execute()
    )
    if not appt_res.data:
        raise AppointmentNotFoundError(appointment_id)

    appointment = appt_res.data[0]
    if appointment.get("patient_id") != patient_id:
        raise ForbiddenError("You do not have access to this appointment.")

    # Enrich with doctor info
    if appointment.get("doctor_id"):
        doc_res = (
            admin_supabase
            .table("doctors")
            .select("doctor_id, full_name, specialization, experience_years, status")
            .eq("doctor_id", appointment["doctor_id"])
            .execute()
        )
        if doc_res.data:
            appointment["doctor"] = doc_res.data[0]

    # Enrich with department info
    if appointment.get("department_id"):
        dept_res = (
            admin_supabase
            .table("departments")
            .select("department_id, name, description, status")
            .eq("department_id", appointment["department_id"])
            .execute()
        )
        if dept_res.data:
            appointment["department"] = dept_res.data[0]

    return appointment


def reschedule_patient_appointment(
    *,
    patient_id: str,
    appointment_id: str,
    new_availability_id: str,
) -> dict[str, Any]:
    """Reschedule a patient's own appointment to a new availability slot."""
    admin_supabase = get_supabase_admin_client()

    # Verify appointment exists and belongs to patient
    appt_res = (
        admin_supabase
        .table("appointments")
        .select("*")
        .eq("appointment_id", appointment_id)
        .execute()
    )
    if not appt_res.data:
        raise AppointmentNotFoundError(appointment_id)

    appointment = appt_res.data[0]
    if appointment.get("patient_id") != patient_id:
        raise ForbiddenError("You do not have access to this appointment.")

    current_status = appointment.get("appointment_status")
    if current_status in ("cancelled", "completed", "no_show"):
        raise InvalidOperationError(f"Cannot reschedule an appointment that is already '{current_status}'.")

    # Verify new slot exists
    slot_res = (
        admin_supabase
        .table("doctor_availability")
        .select("*")
        .eq("availability_id", new_availability_id)
        .execute()
    )
    if not slot_res.data:
        raise AvailabilityNotFoundError(new_availability_id)

    slot = slot_res.data[0]

    if slot["doctor_id"] != appointment["doctor_id"]:
        raise InvalidOperationError("The new slot does not belong to the same doctor.")

    if slot.get("status") != "available":
        raise SlotUnavailableError("The new slot is not available.")

    if slot.get("booked_count", 0) >= slot.get("slot_capacity", 1):
        raise SlotUnavailableError("The new slot has reached maximum capacity.")

    # Update appointment
    slot_date = slot["slot_date"]
    start_time = slot["start_time"]
    end_time = slot["end_time"]
    new_start = f"{slot_date}T{start_time}"
    new_end = f"{slot_date}T{end_time}"
    now = datetime.now(timezone.utc)

    # Refresh the derived schedule/ML features that depend on the appointment
    # time. Without this, lead_time_hours / appointment_hour / weekday / month
    # (and the slot/department context written at the original booking) stayed
    # frozen at the OLD slot, so later inference would score stale inputs.
    new_start_dt = _parse_slot_timestamp(new_start)
    slot_context = _calculate_slot_context(slot)
    dept_context = _calculate_department_context(
        admin_supabase, appointment.get("department_id"), slot_date
    )

    update_payload = {
        "scheduled_start": new_start,
        "scheduled_end": new_end,
        "appointment_status": "booked",
        "lead_time_hours": round(max(0.0, (new_start_dt - now).total_seconds() / 3600), 2),
        "appointment_hour": new_start_dt.hour,
        "appointment_weekday": new_start_dt.weekday(),
        "appointment_month": new_start_dt.month,
        **slot_context,
        **dept_context,
        "updated_at": now.isoformat(),
    }

    update_res = (
        admin_supabase
        .table("appointments")
        .update(update_payload)
        .eq("appointment_id", appointment_id)
        .execute()
    )

    # Increment booked_count on new slot
    admin_supabase.table("doctor_availability").update(
        {"booked_count": slot.get("booked_count", 0) + 1, "updated_at": now.isoformat()}
    ).eq("availability_id", new_availability_id).execute()

    log_audit_event(
        user_id=patient_id,
        user_role="patient",
        action="reschedule_appointment",
        resource_type="appointments",
        resource_id=appointment_id,
        old_value={"scheduled_start": appointment.get("scheduled_start")},
        new_value={"new_start": new_start, "new_availability_id": new_availability_id},
        status="success",
    )

    log_info("Appointment rescheduled by patient", patient_id=patient_id, appointment_id=appointment_id)
    return update_res.data[0]


def cancel_patient_appointment(
    *,
    patient_id: str,
    appointment_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Cancel a patient's own appointment."""
    admin_supabase = get_supabase_admin_client()

    appt_res = (
        admin_supabase
        .table("appointments")
        .select("*")
        .eq("appointment_id", appointment_id)
        .execute()
    )
    if not appt_res.data:
        raise AppointmentNotFoundError(appointment_id)

    appointment = appt_res.data[0]
    if appointment.get("patient_id") != patient_id:
        raise ForbiddenError("You do not have access to this appointment.")

    current_status = appointment.get("appointment_status")
    if current_status == "completed":
        raise InvalidOperationError("Cannot cancel an appointment that has already been completed.")
    if current_status == "cancelled":
        return appointment  # Idempotent
    if current_status == "no_show":
        raise InvalidOperationError("Cannot cancel an appointment that was marked as no-show.")

    now = datetime.now(timezone.utc)
    update_res = (
        admin_supabase
        .table("appointments")
        .update({"appointment_status": "cancelled", "updated_at": now.isoformat()})
        .eq("appointment_id", appointment_id)
        .execute()
    )

    log_audit_event(
        user_id=patient_id,
        user_role="patient",
        action="cancel_appointment",
        resource_type="appointments",
        resource_id=appointment_id,
        old_value={"appointment_status": current_status},
        new_value={"appointment_status": "cancelled", "reason": reason or "Cancelled by patient"},
        status="success",
    )

    log_info("Appointment cancelled by patient", patient_id=patient_id, appointment_id=appointment_id)
    return update_res.data[0]
