"""
Patient feedback service.
Submit and retrieve patient feedback for completed appointments.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.config.settings import get_supabase_admin_client
from app.services.audit_service import log_audit_event
from app.utils.exceptions import (
    AppointmentNotFoundError,
    DuplicateFeedbackError,
    FeedbackNotFoundError,
    ForbiddenError,
    InvalidOperationError,
)
from app.utils.logger import log_info


def submit_feedback(
    *,
    patient_id: str,
    appointment_id: str,
    rating: int,
    comment: str | None = None,
    feedback_channel: str = "form",
) -> dict[str, Any]:
    """
    Submit feedback (rating 1-5 + optional comment) for a completed appointment.
    1. Verify appointment exists and belongs to patient.
    2. Verify appointment is completed.
    3. Prevent duplicate feedback.
    4. Insert feedback record.
    5. Update appointment satisfaction score.
    6. Audit log.
    """
    admin_supabase = get_supabase_admin_client()

    # 1. Verify appointment ownership
    appt_res = (
        admin_supabase
        .table("appointments")
        .select("appointment_id, patient_id, appointment_status")
        .eq("appointment_id", appointment_id)
        .execute()
    )
    if not appt_res.data:
        raise AppointmentNotFoundError(appointment_id)

    appointment = appt_res.data[0]
    if appointment.get("patient_id") != patient_id:
        raise ForbiddenError("You do not have access to this appointment.")

    # 2. Only allow feedback for completed appointments
    if appointment.get("appointment_status") != "completed":
        raise InvalidOperationError("Feedback can only be submitted for completed appointments.")

    # 3. Prevent duplicate feedback
    existing_res = (
        admin_supabase
        .table("feedback")
        .select("feedback_id")
        .eq("appointment_id", appointment_id)
        .eq("patient_id", patient_id)
        .execute()
    )
    if existing_res.data:
        raise DuplicateFeedbackError()

    now = datetime.now(timezone.utc)
    feedback_id = str(uuid4())

    feedback_payload = {
        "feedback_id": feedback_id,
        "appointment_id": appointment_id,
        "patient_id": patient_id,
        "rating": rating,
        "comment": comment,
        "feedback_channel": feedback_channel,
        "submitted_at": now.isoformat(),
        "created_at": now.isoformat(),
    }

    insert_res = admin_supabase.table("feedback").insert(feedback_payload).execute()
    if not insert_res.data:
        raise InvalidOperationError("Failed to record feedback.")

    # 5. Update appointment satisfaction score
    admin_supabase.table("appointments").update({
        "satisfaction_score": rating,
        "satisfaction_target": rating,
        "updated_at": now.isoformat(),
    }).eq("appointment_id", appointment_id).execute()

    log_audit_event(
        user_id=patient_id,
        user_role="patient",
        action="submit_feedback",
        resource_type="feedback",
        resource_id=feedback_id,
        old_value=None,
        new_value={"appointment_id": appointment_id, "rating": rating},
        status="success",
    )

    log_info("Feedback submitted by patient", patient_id=patient_id, feedback_id=feedback_id)
    return insert_res.data[0]


def list_patient_feedback(
    *,
    patient_id: str,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """List feedback entries scoped to the authenticated patient."""
    admin_supabase = get_supabase_admin_client()

    response = (
        admin_supabase
        .table("feedback")
        .select("*", count="exact")
        .eq("patient_id", patient_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )

    return {
        "feedback": response.data or [],
        "total": response.count or 0,
        "limit": limit,
        "offset": offset,
    }


def get_patient_feedback(
    *,
    patient_id: str,
    feedback_id: str,
) -> dict[str, Any]:
    """Retrieve a single feedback entry, enforcing patient ownership."""
    admin_supabase = get_supabase_admin_client()

    fb_res = (
        admin_supabase
        .table("feedback")
        .select("*")
        .eq("feedback_id", feedback_id)
        .execute()
    )
    if not fb_res.data:
        raise FeedbackNotFoundError(feedback_id)

    feedback = fb_res.data[0]
    if feedback.get("patient_id") != patient_id:
        raise ForbiddenError("You do not have access to this feedback.")

    return feedback
