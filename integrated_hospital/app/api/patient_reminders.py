"""
Patient reminders API routes.
View own reminders (read-only for patients).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.auth import AuthContext, require_patient
from app.services.reminder_service import list_patient_reminders

router = APIRouter(
    prefix="/patient/reminders",
    tags=["Patient Reminders"],
)


@router.get("", status_code=status.HTTP_200_OK, summary="List own reminders")
def list_reminders_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    patient: AuthContext = Depends(require_patient),
):
    """List all reminders sent to the authenticated patient."""
    result = list_patient_reminders(patient_id=patient.user.id, limit=limit, offset=offset)
    return {"success": True, "data": result["reminders"], "total": result["total"]}
