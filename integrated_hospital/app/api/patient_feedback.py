"""
Patient feedback API routes.
Submit and view feedback for completed appointments.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.auth import AuthContext, require_patient
from app.schema.patient import SubmitFeedbackRequest
from app.services.patient_feedback_service import (
    get_patient_feedback,
    list_patient_feedback,
    submit_feedback,
)

router = APIRouter(
    prefix="/patient/feedback",
    tags=["Patient Feedback"],
)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Submit feedback")
def submit_feedback_endpoint(
    payload: SubmitFeedbackRequest,
    patient: AuthContext = Depends(require_patient),
):
    """Submit feedback for a completed appointment."""
    feedback = submit_feedback(
        patient_id=patient.user.id,
        appointment_id=payload.appointment_id,
        rating=payload.rating,
        comment=payload.comment,
        feedback_channel=payload.feedback_channel,
    )
    return {"success": True, "message": "Feedback submitted successfully.", "data": feedback}


@router.get("", status_code=status.HTTP_200_OK, summary="List own feedback")
def list_feedback_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    patient: AuthContext = Depends(require_patient),
):
    """List all feedback submissions by the authenticated patient."""
    result = list_patient_feedback(patient_id=patient.user.id, limit=limit, offset=offset)
    return {"success": True, "data": result["feedback"], "total": result["total"]}


@router.get("/{feedback_id}", status_code=status.HTTP_200_OK, summary="View feedback details")
def get_feedback_endpoint(
    feedback_id: str,
    patient: AuthContext = Depends(require_patient),
):
    """Retrieve a single feedback entry."""
    feedback = get_patient_feedback(patient_id=patient.user.id, feedback_id=feedback_id)
    return {"success": True, "data": feedback}
