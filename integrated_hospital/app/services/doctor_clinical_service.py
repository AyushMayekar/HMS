"""
Doctor clinical service.
Doctor-owned clinical workflow: profile, assigned appointments, start/end
service, prescriptions and diagnostic orders.

Identity and billing fields are always derived server-side from the
authenticated profile and the appointment - never from the request payload.
A doctor only ever sees appointments whose ``doctor_id`` matches their own
``profiles.doctor_id``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.config.settings import get_supabase_admin_client
from app.services.audit_service import log_audit_event
from app.services.billing_service import (
    get_billing_context,
    refresh_invoice_amount,
    to_billing_summary,
)
from app.utils.exceptions import (
    AppointmentNotFoundError,
    DiagnosticTestNotFoundError,
    ForbiddenError,
    InvalidOperationError,
    MedicineNotFoundError,
)
from app.utils.logger import log_info

# Statuses that resolve (or forbid) the visit lifecycle.
RESOLVED_STATUSES = ("cancelled", "no_show", "completed")

# "In service" status written when a doctor starts service. This is the
# status the application already uses for an ongoing consultation
# (frontend APPOINTMENT_STATUSES / appointment cards).
IN_SERVICE_STATUS = "in_consultation"


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO timestamp into an aware datetime (naive => UTC)."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _patient_profiles(admin_supabase, patient_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Resolve patient display info for the appointments being returned."""
    ids = sorted({i for i in patient_ids if i})
    if not ids:
        return {}
    response = (
        admin_supabase
        .table("profiles")
        .select("user_id, full_name, email")
        .in_("user_id", ids)
        .execute()
    )
    return {p.get("user_id"): p for p in (response.data or [])}


def _enrich(rows: list[dict[str, Any]], admin_supabase) -> list[dict[str, Any]]:
    """Attach patient name/email to appointment rows."""
    profiles = _patient_profiles(admin_supabase, [r.get("patient_id") for r in rows])
    enriched = []
    for row in rows:
        item = dict(row)
        patient = profiles.get(item.get("patient_id")) or {}
        item["patient_name"] = patient.get("full_name")
        item["patient_email"] = patient.get("email")
        enriched.append(item)
    return enriched


# ============================================================
# PROFILE / APPOINTMENTS
# ============================================================

def get_doctor_profile(*, profile: dict[str, Any]) -> dict[str, Any]:
    """
    Build the doctor profile from profiles -> doctors -> departments.
    No doctor identity is duplicated: the profile row is the one already
    loaded from the authenticated JWT.
    """
    admin_supabase = get_supabase_admin_client()
    doctor_id = profile.get("doctor_id")

    doc_res = (
        admin_supabase
        .table("doctors")
        .select("*")
        .eq("doctor_id", doctor_id)
        .execute()
    )
    if not doc_res.data:
        raise ForbiddenError("This account is not linked to a doctor record.")

    doctor = doc_res.data[0]

    department = None
    if doctor.get("department_id"):
        dept_res = (
            admin_supabase
            .table("departments")
            .select("*")
            .eq("department_id", doctor["department_id"])
            .execute()
        )
        department = dept_res.data[0] if dept_res.data else None

    return {
        "profile": profile,
        "doctor": doctor,
        "department": department,
    }


def list_doctor_appointments(
    *,
    doctor_id: str,
    appointment_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """List appointments assigned to the logged-in doctor (soonest first)."""
    admin_supabase = get_supabase_admin_client()

    query = (
        admin_supabase
        .table("appointments")
        .select("*", count="exact")
        .eq("doctor_id", doctor_id)
    )
    if appointment_status:
        query = query.eq("appointment_status", appointment_status)

    response = (
        query
        .order("scheduled_start", desc=False)
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows = response.data or []

    return {
        "appointments": _enrich(rows, admin_supabase),
        "total": response.count or 0,
        "limit": limit,
        "offset": offset,
    }


def get_doctor_appointment(
    *,
    doctor_id: str,
    appointment_id: str,
) -> dict[str, Any]:
    """
    Full detail for one assigned appointment: patient, clinical line items
    recorded for this appointment and the current bill.
    """
    admin_supabase = get_supabase_admin_client()
    appointment = _load_assigned_appointment(admin_supabase, doctor_id, appointment_id)

    context = get_billing_context(admin_supabase, appointment)
    enriched = _enrich([appointment], admin_supabase)[0]

    enriched["patient"] = {
        "user_id": enriched.get("patient_id"),
        "full_name": enriched.get("patient_name"),
        "email": enriched.get("patient_email"),
    }
    enriched["prescriptions"] = context["prescriptions"]
    enriched["diagnostic_test_orders"] = context["diagnostic_test_orders"]
    enriched["billing_summary"] = to_billing_summary(context)

    return enriched


# ============================================================
# OWNERSHIP / STATE GUARDS
# ============================================================

def _load_assigned_appointment(
    admin_supabase,
    doctor_id: str,
    appointment_id: str,
) -> dict[str, Any]:
    """Load an appointment and enforce doctor ownership."""
    response = (
        admin_supabase
        .table("appointments")
        .select("*")
        .eq("appointment_id", appointment_id)
        .execute()
    )
    if not response.data:
        raise AppointmentNotFoundError(appointment_id)

    appointment = response.data[0]
    if appointment.get("doctor_id") != doctor_id:
        raise ForbiddenError("You do not have access to this appointment.")

    return appointment


def _require_active_service(appointment: dict[str, Any]) -> None:
    """Clinical orders are only allowed while the visit is in service."""
    status = appointment.get("appointment_status")

    if status in RESOLVED_STATUSES:
        raise InvalidOperationError(
            f"Cannot record clinical orders for an appointment that is '{status}'."
        )
    if not appointment.get("actual_checkin_time"):
        raise InvalidOperationError("The patient has not been checked in yet.")
    if not appointment.get("actual_service_start"):
        raise InvalidOperationError("Service has not started yet.")
    if appointment.get("actual_service_end"):
        raise InvalidOperationError("Service has already ended.")


# ============================================================
# SERVICE LIFECYCLE
# ============================================================

def start_doctor_service(
    *,
    doctor_id: str,
    appointment_id: str,
    actor_id: str,
    actor_role: str,
) -> dict[str, Any]:
    """
    Start the consultation for an assigned, already checked-in appointment.

    Sets ``actual_service_start``, writes ``actual_wait_minutes``
    (service start - check-in) for the existing operational analytics /
    waiting-time model, and moves the appointment to the in-service status.
    """
    admin_supabase = get_supabase_admin_client()
    appointment = _load_assigned_appointment(admin_supabase, doctor_id, appointment_id)

    status = appointment.get("appointment_status")
    if status in RESOLVED_STATUSES:
        raise InvalidOperationError(
            f"Cannot start service for an appointment that is '{status}'."
        )
    if not appointment.get("actual_checkin_time"):
        raise InvalidOperationError("Cannot start service before check-in.")
    if appointment.get("actual_service_start"):
        raise InvalidOperationError("Service has already started.")

    now = datetime.now(timezone.utc)
    wait_minutes = None
    checkin = _parse_timestamp(appointment.get("actual_checkin_time"))
    if checkin is not None:
        wait_minutes = round((now - checkin).total_seconds() / 60, 2)

    update_fields = {
        "actual_service_start": now.isoformat(),
        "appointment_status": IN_SERVICE_STATUS,
        "updated_at": now.isoformat(),
    }
    if wait_minutes is not None:
        update_fields["actual_wait_minutes"] = wait_minutes

    update_res = (
        admin_supabase
        .table("appointments")
        .update(update_fields)
        .eq("appointment_id", appointment_id)
        .execute()
    )

    log_audit_event(
        user_id=actor_id,
        user_role=actor_role,
        action="doctor_start_service",
        resource_type="appointments",
        resource_id=appointment_id,
        old_value={"appointment_status": status, "actual_service_start": None},
        new_value=update_fields,
        status="success",
    )

    log_info(
        "Service started by doctor",
        appointment_id=appointment_id,
        doctor_id=doctor_id,
        actual_wait_minutes=wait_minutes,
    )
    return update_res.data[0] if update_res.data else {**appointment, **update_fields}


def end_doctor_service(
    *,
    doctor_id: str,
    appointment_id: str,
    actor_id: str,
    actor_role: str,
) -> dict[str, Any]:
    """
    End the consultation for an assigned appointment whose service started.

    Payment records are never touched here: the bill already reflects the
    orders created during the consultation.
    """
    admin_supabase = get_supabase_admin_client()
    appointment = _load_assigned_appointment(admin_supabase, doctor_id, appointment_id)

    if not appointment.get("actual_service_start"):
        raise InvalidOperationError("Cannot end service before starting it.")
    if appointment.get("actual_service_end"):
        raise InvalidOperationError("Service has already ended.")
    if appointment.get("appointment_status") in ("cancelled", "no_show"):
        raise InvalidOperationError(
            f"Cannot end service for an appointment that is '{appointment.get('appointment_status')}'."
        )

    now = datetime.now(timezone.utc)
    update_fields = {
        "actual_service_end": now.isoformat(),
        "appointment_status": "completed",
        "updated_at": now.isoformat(),
    }

    # Same operational target the staff end-of-service path writes.
    wait_minutes = appointment.get("actual_wait_minutes")
    if wait_minutes is not None:
        update_fields["waiting_time_target"] = round(float(wait_minutes), 2)

    update_res = (
        admin_supabase
        .table("appointments")
        .update(update_fields)
        .eq("appointment_id", appointment_id)
        .execute()
    )

    log_audit_event(
        user_id=actor_id,
        user_role=actor_role,
        action="doctor_end_service",
        resource_type="appointments",
        resource_id=appointment_id,
        old_value={
            "appointment_status": appointment.get("appointment_status"),
            "actual_service_end": None,
        },
        new_value=update_fields,
        status="success",
    )

    log_info("Service ended by doctor", appointment_id=appointment_id, doctor_id=doctor_id)
    return update_res.data[0] if update_res.data else {**appointment, **update_fields}


# ============================================================
# CLINICAL ORDERS
# ============================================================

def create_prescription(
    *,
    doctor_id: str,
    appointment_id: str,
    medicine_id: str,
    quantity: int,
    dosage: str,
    frequency: str,
    duration_days: int,
    instructions: str | None = None,
    actor_id: str,
    actor_role: str,
) -> dict[str, Any]:
    """
    Record a prescription against an in-service appointment.

    patient_id, unit_charge and total_amount are derived server-side from
    the appointment and the medicines catalog, then the appointment invoice
    is recalculated.
    """
    admin_supabase = get_supabase_admin_client()
    appointment = _load_assigned_appointment(admin_supabase, doctor_id, appointment_id)
    _require_active_service(appointment)

    med_res = (
        admin_supabase
        .table("medicines")
        .select("*")
        .eq("medicine_id", medicine_id)
        .execute()
    )
    if not med_res.data:
        raise MedicineNotFoundError(medicine_id)

    medicine = med_res.data[0]
    if medicine.get("status") != "active":
        raise InvalidOperationError("The selected medicine is not currently available.")

    now = datetime.now(timezone.utc)
    unit_charge = round(float(medicine.get("charge") or 0), 2)

    payload = {
        "prescription_id": str(uuid4()),
        "patient_id": appointment.get("patient_id"),
        "doctor_id": doctor_id,
        "appointment_id": appointment_id,
        "medicine_id": medicine_id,
        "quantity": quantity,
        "dosage": dosage,
        "frequency": frequency,
        "duration_days": duration_days,
        "instructions": instructions,
        "unit_charge": unit_charge,
        "currency": medicine.get("currency") or "INR",
        "billing_status": "not_billed",
        "status": "active",
        "prescribed_at": now.isoformat(),
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    insert_res = admin_supabase.table("prescriptions").insert(payload).execute()
    if not insert_res.data:
        raise InvalidOperationError("Failed to record the prescription.")

    context = refresh_invoice_amount(appointment_id)

    log_audit_event(
        user_id=actor_id,
        user_role=actor_role,
        action="create_prescription",
        resource_type="prescriptions",
        resource_id=payload["prescription_id"],
        old_value=None,
        new_value={
            "appointment_id": appointment_id,
            "medicine_id": medicine_id,
            "quantity": quantity,
        },
        status="success",
    )

    log_info(
        "Prescription recorded",
        appointment_id=appointment_id,
        doctor_id=doctor_id,
    )
    return {
        "prescription": insert_res.data[0],
        "billing": to_billing_summary(context),
    }


def create_diagnostic_order(
    *,
    doctor_id: str,
    appointment_id: str,
    test_id: str,
    quantity: int,
    priority: str,
    notes: str | None = None,
    actor_id: str,
    actor_role: str,
) -> dict[str, Any]:
    """
    Order a diagnostic test for an in-service appointment.

    patient_id, unit_charge and total_amount are derived server-side from
    the appointment and the diagnostic_tests catalog, then the appointment
    invoice is recalculated.
    """
    admin_supabase = get_supabase_admin_client()
    appointment = _load_assigned_appointment(admin_supabase, doctor_id, appointment_id)
    _require_active_service(appointment)

    test_res = (
        admin_supabase
        .table("diagnostic_tests")
        .select("*")
        .eq("test_id", test_id)
        .execute()
    )
    if not test_res.data:
        raise DiagnosticTestNotFoundError(test_id)

    test = test_res.data[0]
    if test.get("status") != "active":
        raise InvalidOperationError("The selected diagnostic test is not currently available.")

    now = datetime.now(timezone.utc)
    unit_charge = round(float(test.get("charge") or 0), 2)

    payload = {
        "order_id": str(uuid4()),
        "patient_id": appointment.get("patient_id"),
        "doctor_id": doctor_id,
        "appointment_id": appointment_id,
        "test_id": test_id,
        "quantity": quantity,
        "priority": priority,
        "notes": notes,
        "unit_charge": unit_charge,
        "currency": test.get("currency") or "INR",
        "billing_status": "not_billed",
        "status": "ordered",
        "ordered_at": now.isoformat(),
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    insert_res = admin_supabase.table("diagnostic_test_orders").insert(payload).execute()
    if not insert_res.data:
        raise InvalidOperationError("Failed to record the diagnostic order.")

    context = refresh_invoice_amount(appointment_id)

    log_audit_event(
        user_id=actor_id,
        user_role=actor_role,
        action="create_diagnostic_order",
        resource_type="diagnostic_test_orders",
        resource_id=payload["order_id"],
        old_value=None,
        new_value={
            "appointment_id": appointment_id,
            "test_id": test_id,
            "quantity": quantity,
            "priority": priority,
        },
        status="success",
    )

    log_info(
        "Diagnostic order recorded",
        appointment_id=appointment_id,
        doctor_id=doctor_id,
    )
    return {
        "diagnostic_order": insert_res.data[0],
        "billing": to_billing_summary(context),
    }


# ============================================================
# READ-ONLY CATALOGS
# ============================================================

def list_medicines(*, status: str | None = "active", limit: int = 200, offset: int = 0) -> dict[str, Any]:
    """Read-only medicines catalog (never writable by a doctor)."""
    admin_supabase = get_supabase_admin_client()
    query = admin_supabase.table("medicines").select("*", count="exact")
    if status:
        query = query.eq("status", status)
    response = query.order("name").range(offset, offset + limit - 1).execute()
    return {"medicines": response.data or [], "total": response.count or 0}


def list_diagnostic_tests(*, status: str | None = "active", limit: int = 200, offset: int = 0) -> dict[str, Any]:
    """Read-only diagnostic tests catalog (never writable by a doctor)."""
    admin_supabase = get_supabase_admin_client()
    query = admin_supabase.table("diagnostic_tests").select("*", count="exact")
    if status:
        query = query.eq("status", status)
    response = query.order("name").range(offset, offset + limit - 1).execute()
    return {"diagnostic_tests": response.data or [], "total": response.count or 0}
