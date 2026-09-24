"""
Patient payments API routes.
Simulated payment processing for appointments.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.auth import AuthContext, require_patient
from app.schema.patient import CreatePaymentRequest
from app.services.patient_payment_service import (
    create_payment,
    get_patient_payment,
    list_patient_payments,
)

router = APIRouter(
    prefix="/patient/payments",
    tags=["Patient Payments"],
)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a simulated payment")
def create_payment_endpoint(
    payload: CreatePaymentRequest,
    patient: AuthContext = Depends(require_patient),
):
    """Create a simulated payment for the patient's appointment."""
    payment = create_payment(
        patient_id=patient.user.id,
        appointment_id=payload.appointment_id,
        currency=payload.currency,
        payment_method=payload.payment_method,
        insurance_used=payload.insurance_used,
        claim_required=payload.claim_required,
    )
    return {"success": True, "message": "Payment processed successfully.", "data": payment}


@router.get("", status_code=status.HTTP_200_OK, summary="List own payment history")
def list_payments_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    patient: AuthContext = Depends(require_patient),
):
    """List all payments made by the authenticated patient."""
    result = list_patient_payments(patient_id=patient.user.id, limit=limit, offset=offset)
    return {"success": True, "data": result["payments"], "total": result["total"]}


@router.get("/{payment_id}", status_code=status.HTTP_200_OK, summary="View payment details")
def get_payment_endpoint(
    payment_id: str,
    patient: AuthContext = Depends(require_patient),
):
    """Retrieve details of a single payment."""
    payment = get_patient_payment(patient_id=patient.user.id, payment_id=payment_id)
    return {"success": True, "data": payment}
