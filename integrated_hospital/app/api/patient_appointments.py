"""
Patient appointments API routes.
Book, list, view, reschedule, and cancel appointments.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.auth import AuthContext, require_patient
from app.schema.patient import BookAppointmentRequest, PatientCancelRequest, PatientRescheduleRequest
from app.services.patient_appointment_service import (
    book_appointment,
    cancel_patient_appointment,
    get_patient_appointment,
    list_patient_appointments,
    reschedule_patient_appointment,
)

router = APIRouter(
    prefix="/patient/appointments",
    tags=["Patient Appointments"],
)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Book an appointment")
def book_appointment_endpoint(
    payload: BookAppointmentRequest,
    patient: AuthContext = Depends(require_patient),
):
    """Book an appointment. Patient identity derived from JWT."""
    appointment = book_appointment(
        patient_id=patient.user.id,
        doctor_id=payload.doctor_id,
        availability_id=payload.availability_id,
        reason=payload.reason,
    )
    return {"success": True, "message": "Appointment booked successfully.", "data": appointment}


@router.get("", status_code=status.HTTP_200_OK, summary="List own appointments")
def list_appointments_endpoint(
    appointment_status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    patient: AuthContext = Depends(require_patient),
):
    """List all appointments belonging to the authenticated patient."""
    result = list_patient_appointments(
        patient_id=patient.user.id,
        appointment_status=appointment_status,
        limit=limit,
        offset=offset,
    )
    return {"success": True, "data": result["appointments"], "total": result["total"]}


@router.get("/{appointment_id}", status_code=status.HTTP_200_OK, summary="View appointment details")
def get_appointment_endpoint(
    appointment_id: str,
    patient: AuthContext = Depends(require_patient),
):
    """Retrieve full details of a single appointment."""
    appointment = get_patient_appointment(patient_id=patient.user.id, appointment_id=appointment_id)
    return {"success": True, "data": appointment}


@router.patch("/{appointment_id}/reschedule", status_code=status.HTTP_200_OK, summary="Reschedule appointment")
def reschedule_appointment_endpoint(
    appointment_id: str,
    payload: PatientRescheduleRequest,
    patient: AuthContext = Depends(require_patient),
):
    """Reschedule the patient's own appointment."""
    rescheduled = reschedule_patient_appointment(
        patient_id=patient.user.id,
        appointment_id=appointment_id,
        new_availability_id=payload.new_availability_id,
    )
    return {"success": True, "message": "Appointment rescheduled successfully.", "data": rescheduled}


@router.post("/{appointment_id}/cancel", status_code=status.HTTP_200_OK, summary="Cancel appointment")
def cancel_appointment_endpoint(
    appointment_id: str,
    payload: PatientCancelRequest | None = None,
    patient: AuthContext = Depends(require_patient),
):
    """Cancel the patient's own appointment."""
    reason = payload.reason if payload else None
    cancelled = cancel_patient_appointment(patient_id=patient.user.id, appointment_id=appointment_id, reason=reason)
    return {"success": True, "message": "Appointment cancelled successfully.", "data": cancelled}
