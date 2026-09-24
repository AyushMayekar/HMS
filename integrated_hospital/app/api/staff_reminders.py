"""
Staff reminders API routes.
Create and manage reminders for appointments.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.auth import AuthContext, require_staff_or_admin
from app.schema.staff import CreateReminderRequest
from app.services.reminder_service import create_staff_reminder, list_reminders

router = APIRouter(
    prefix="/staff/reminders",
    tags=["Staff Reminders"],
)


@router.post("/{appointment_id}", status_code=status.HTTP_201_CREATED, summary="Create reminder")
def create_reminder_endpoint(
    appointment_id: str,
    payload: CreateReminderRequest,
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """Create a reminder for an appointment."""
    reminder = create_staff_reminder(
        staff_id=auth.user.id,
        staff_role=auth.profile.get("role", "staff"),
        appointment_id=appointment_id,
        reminder_type=payload.reminder_type,
        hours_before_appointment=payload.hours_before_appointment,
        message=payload.message,
    )
    return {"success": True, "message": "Reminder created.", "data": reminder}


@router.get("", status_code=status.HTTP_200_OK, summary="List all reminders")
def list_reminders_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """List all reminders (staff/admin)."""
    result = list_reminders(limit=limit, offset=offset)
    return {"success": True, "data": result["reminders"], "total": result["total"]}
