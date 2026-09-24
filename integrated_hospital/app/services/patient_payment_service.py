"""
Patient payment service.
Simulated payment processing. Never stores real payment credentials.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.config.settings import get_supabase_admin_client
from app.services.audit_service import log_audit_event
from app.services.billing_service import DEFAULT_CONSULTATION_CHARGE
from app.utils.exceptions import (
    AppointmentNotFoundError,
    ForbiddenError,
    InvalidOperationError,
    PaymentNotFoundError,
    PaymentSimulationError,
)
from app.utils.logger import log_info


def simulate_payment_outcome() -> dict[str, Any]:
    """
    Simulate a payment outcome.
    Returns success/failure/pending with a deterministic-ish result.
    90% success rate for demo purposes.
    """
    roll = random.random()

    if roll < 0.90:
        status = "success"
        transaction_ref = f"SIM-SUCCESS-{uuid4().hex[:12].upper()}"
    elif roll < 0.97:
        status = "failed"
        transaction_ref = f"SIM-FAILED-{uuid4().hex[:12].upper()}"
    else:
        status = "pending"
        transaction_ref = f"SIM-PENDING-{uuid4().hex[:12].upper()}"

    return {
        "status": status,
        "transaction_reference": transaction_ref,
    }


def create_payment(
    *,
    patient_id: str,
    appointment_id: str,
    currency: str = "INR",
    payment_method: str,
    insurance_used: bool = False,
    claim_required: bool = False,
) -> dict[str, Any]:
    """
    Create a simulated payment for a patient's own appointment.
    1. Verify appointment exists and belongs to patient.
    2. Read the payable amount from appointment.invoice_amount (server
       derived — a client-supplied amount is never trusted).
    3. Simulate payment outcome.
    4. Insert payment record.
    5. Update appointment payment status.
    6. Audit log.
    """
    admin_supabase = get_supabase_admin_client()

    # 1. Verify appointment ownership
    appt_res = (
        admin_supabase
        .table("appointments")
        .select("appointment_id, patient_id, appointment_status, invoice_amount, consultation_charge")
        .eq("appointment_id", appointment_id)
        .execute()
    )
    if not appt_res.data:
        raise AppointmentNotFoundError(appointment_id)

    appointment = appt_res.data[0]
    if appointment.get("patient_id") != patient_id:
        raise ForbiddenError("You do not have access to this appointment.")

    if appointment.get("appointment_status") == "cancelled":
        raise InvalidOperationError("Cannot create payment for a cancelled appointment.")

    # 2. Payable amount comes from the authoritative appointment bill.
    raw_amount = appointment.get("invoice_amount")
    if raw_amount is None:
        raw_amount = appointment.get("consultation_charge")
    if raw_amount is None:
        raw_amount = DEFAULT_CONSULTATION_CHARGE
    amount = round(float(raw_amount), 2)

    # 3. Simulate payment
    simulation = simulate_payment_outcome()

    now = datetime.now(timezone.utc)
    payment_id = str(uuid4())

    paid_at = now.isoformat() if simulation["status"] == "success" else None

    payment_payload = {
        "payment_id": payment_id,
        "appointment_id": appointment_id,
        "patient_id": patient_id,
        "amount": amount,
        "currency": currency,
        "payment_method": payment_method,
        "status": simulation["status"],
        "transaction_reference": simulation["transaction_reference"],
        "initiated_at": now.isoformat(),
        "paid_at": paid_at,
        "created_at": now.isoformat(),
    }

    insert_res = admin_supabase.table("payments").insert(payment_payload).execute()
    if not insert_res.data:
        raise InvalidOperationError("Failed to record payment.")

    # 4. Update appointment payment status
    if simulation["status"] == "success":
        admin_supabase.table("appointments").update({
            "payment_status_at_booking": "paid",
            "updated_at": now.isoformat(),
        }).eq("appointment_id", appointment_id).execute()

    log_audit_event(
        user_id=patient_id,
        user_role="patient",
        action="create_payment",
        resource_type="payments",
        resource_id=payment_id,
        old_value=None,
        new_value={
            "appointment_id": appointment_id,
            "amount": amount,
            "payment_method": payment_method,
            "status": simulation["status"],
        },
        status="success",
    )

    log_info("Simulated payment created", patient_id=patient_id, payment_id=payment_id, status=simulation["status"])
    return insert_res.data[0]


def list_patient_payments(
    *,
    patient_id: str,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """List payments scoped to the authenticated patient."""
    admin_supabase = get_supabase_admin_client()

    response = (
        admin_supabase
        .table("payments")
        .select("*", count="exact")
        .eq("patient_id", patient_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )

    return {
        "payments": response.data or [],
        "total": response.count or 0,
        "limit": limit,
        "offset": offset,
    }


def get_patient_payment(
    *,
    patient_id: str,
    payment_id: str,
) -> dict[str, Any]:
    """Retrieve a single payment, enforcing patient ownership."""
    admin_supabase = get_supabase_admin_client()

    pay_res = (
        admin_supabase
        .table("payments")
        .select("*")
        .eq("payment_id", payment_id)
        .execute()
    )
    if not pay_res.data:
        raise PaymentNotFoundError(payment_id)

    payment = pay_res.data[0]
    if payment.get("patient_id") != patient_id:
        raise ForbiddenError("You do not have access to this payment.")

    return payment
