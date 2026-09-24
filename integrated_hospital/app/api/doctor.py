"""
Doctor API routes.
Clinical workflow for the doctor role: profile, assigned appointments,
service lifecycle, prescriptions and diagnostic orders.

Every route derives doctor identity from the authenticated profile
(``profiles.doctor_id``) - request payloads never carry doctor_id,
patient_id, unit_charge, total_amount or invoice_amount.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.auth import AuthContext, require_doctor
from app.schema.doctor import CreateDiagnosticOrderRequest, CreatePrescriptionRequest
from app.services.doctor_clinical_service import (
    create_diagnostic_order,
    create_prescription,
    end_doctor_service,
    get_doctor_appointment,
    get_doctor_profile,
    list_diagnostic_tests,
    list_doctor_appointments,
    list_medicines,
    start_doctor_service,
)

router = APIRouter(
    prefix="/doctor",
    tags=["Doctor"],
)


def _doctor_id(auth: AuthContext) -> str:
    """Doctor identity always comes from the authenticated profile."""
    return auth.profile.get("doctor_id")


@router.get("/profile", status_code=status.HTTP_200_OK, summary="Doctor profile")
def get_profile_endpoint(auth: AuthContext = Depends(require_doctor)):
    """Profile, doctor record and department of the logged-in doctor."""
    data = get_doctor_profile(profile=auth.profile)
    return {"success": True, "data": data}


@router.get("/appointments", status_code=status.HTTP_200_OK, summary="List assigned appointments")
def list_appointments_endpoint(
    appointment_status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(require_doctor),
):
    """List only the appointments assigned to the logged-in doctor."""
    result = list_doctor_appointments(
        doctor_id=_doctor_id(auth),
        appointment_status=appointment_status,
        limit=limit,
        offset=offset,
    )
    return {"success": True, "data": result["appointments"], "total": result["total"]}


@router.get("/appointments/{appointment_id}", status_code=status.HTTP_200_OK, summary="Appointment detail")
def get_appointment_endpoint(
    appointment_id: str,
    auth: AuthContext = Depends(require_doctor),
):
    """Appointment detail with this appointment's orders and current bill."""
    appointment = get_doctor_appointment(
        doctor_id=_doctor_id(auth),
        appointment_id=appointment_id,
    )
    return {"success": True, "data": appointment}


@router.post(
    "/appointments/{appointment_id}/start-service",
    status_code=status.HTTP_200_OK,
    summary="Start service",
)
def start_service_endpoint(
    appointment_id: str,
    auth: AuthContext = Depends(require_doctor),
):
    """Start the consultation (requires a check-in) and record the wait."""
    result = start_doctor_service(
        doctor_id=_doctor_id(auth),
        appointment_id=appointment_id,
        actor_id=auth.user.id,
        actor_role=auth.profile.get("role", "doctor"),
    )
    return {"success": True, "message": "Service started.", "data": result}


@router.post(
    "/appointments/{appointment_id}/prescriptions",
    status_code=status.HTTP_201_CREATED,
    summary="Add prescription",
)
def create_prescription_endpoint(
    appointment_id: str,
    payload: CreatePrescriptionRequest,
    auth: AuthContext = Depends(require_doctor),
):
    """Prescribe a catalog medicine for an in-service appointment."""
    result = create_prescription(
        doctor_id=_doctor_id(auth),
        appointment_id=appointment_id,
        medicine_id=payload.medicine_id,
        quantity=payload.quantity,
        dosage=payload.dosage,
        frequency=payload.frequency,
        duration_days=payload.duration_days,
        instructions=payload.instructions,
        actor_id=auth.user.id,
        actor_role=auth.profile.get("role", "doctor"),
    )
    return {
        "success": True,
        "message": "Prescription recorded and the invoice has been recalculated.",
        "data": result["prescription"],
        "billing": result["billing"],
    }


@router.post(
    "/appointments/{appointment_id}/diagnostic-orders",
    status_code=status.HTTP_201_CREATED,
    summary="Order diagnostic test",
)
def create_diagnostic_order_endpoint(
    appointment_id: str,
    payload: CreateDiagnosticOrderRequest,
    auth: AuthContext = Depends(require_doctor),
):
    """Order a catalog diagnostic test for an in-service appointment."""
    result = create_diagnostic_order(
        doctor_id=_doctor_id(auth),
        appointment_id=appointment_id,
        test_id=payload.test_id,
        quantity=payload.quantity,
        priority=payload.priority,
        notes=payload.notes,
        actor_id=auth.user.id,
        actor_role=auth.profile.get("role", "doctor"),
    )
    return {
        "success": True,
        "message": "Diagnostic order recorded and the invoice has been recalculated.",
        "data": result["diagnostic_order"],
        "billing": result["billing"],
    }


@router.post(
    "/appointments/{appointment_id}/end-service",
    status_code=status.HTTP_200_OK,
    summary="End service",
)
def end_service_endpoint(
    appointment_id: str,
    auth: AuthContext = Depends(require_doctor),
):
    """End the consultation. Payment records are not modified here."""
    result = end_doctor_service(
        doctor_id=_doctor_id(auth),
        appointment_id=appointment_id,
        actor_id=auth.user.id,
        actor_role=auth.profile.get("role", "doctor"),
    )
    return {"success": True, "message": "Service ended.", "data": result}


@router.get("/medicines", status_code=status.HTTP_200_OK, summary="Medicines catalog")
def list_medicines_endpoint(
    status_filter: str | None = Query(default="active", alias="status"),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(require_doctor),
):
    """Read-only medicines catalog for prescribing (no writes)."""
    result = list_medicines(status=status_filter, limit=limit, offset=offset)
    return {"success": True, "data": result["medicines"], "total": result["total"]}


@router.get("/diagnostic-tests", status_code=status.HTTP_200_OK, summary="Diagnostic tests catalog")
def list_diagnostic_tests_endpoint(
    status_filter: str | None = Query(default="active", alias="status"),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(require_doctor),
):
    """Read-only diagnostic tests catalog for ordering (no writes)."""
    result = list_diagnostic_tests(status=status_filter, limit=limit, offset=offset)
    return {"success": True, "data": result["diagnostic_tests"], "total": result["total"]}
