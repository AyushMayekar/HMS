"""
Appointment billing service.
Single source of truth for the authoritative appointment bill:

    invoice_amount = consultation_charge
                   + SUM(prescriptions.total_amount)
                   + SUM(diagnostic_test_orders.total_amount)

``appointments.invoice_amount`` stays the final calculated amount and
``appointments.consultation_charge`` preserves the base consultation charge
independently of it. Nothing outside this module recalculates the invoice,
and no client-supplied amount is ever trusted.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config.settings import get_supabase_admin_client
from app.utils.exceptions import AppointmentNotFoundError
from app.utils.logger import log_info

# Base consultation charge applied at booking time, and the fallback for
# appointments booked before consultation_charge existed.
DEFAULT_CONSULTATION_CHARGE = 500.0


def money(value: Any) -> float:
    """Coerce a stored amount to a rounded float (never raises)."""
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _catalog_names(admin_supabase, table: str, key: str, ids: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch catalog rows (name + charge) for the ids actually used."""
    ids = sorted({i for i in ids if i})
    if not ids:
        return {}
    response = admin_supabase.table(table).select("*").in_(key, ids).execute()
    return {row.get(key): row for row in (response.data or [])}


def get_billing_context(
    admin_supabase,
    appointment: dict[str, Any],
) -> dict[str, Any]:
    """
    Compute (never persist) the bill of an appointment.

    Returns the totals plus the appointment's own clinical line items
    enriched with catalog names, so the patient and doctor views render one
    shared calculation.
    """
    appointment_id = appointment.get("appointment_id")

    pres_res = (
        admin_supabase
        .table("prescriptions")
        .select("*")
        .eq("appointment_id", appointment_id)
        .execute()
    )
    prescriptions = pres_res.data or []

    order_res = (
        admin_supabase
        .table("diagnostic_test_orders")
        .select("*")
        .eq("appointment_id", appointment_id)
        .execute()
    )
    orders = order_res.data or []

    medicines = _catalog_names(
        admin_supabase, "medicines", "medicine_id",
        [p.get("medicine_id") for p in prescriptions],
    )
    tests = _catalog_names(
        admin_supabase, "diagnostic_tests", "test_id",
        [o.get("test_id") for o in orders],
    )

    consultation_charge = (
        money(appointment.get("consultation_charge"))
        if appointment.get("consultation_charge") is not None
        else DEFAULT_CONSULTATION_CHARGE
    )

    medicine_total = round(sum(money(p.get("total_amount")) for p in prescriptions), 2)
    diagnostic_total = round(sum(money(o.get("total_amount")) for o in orders), 2)
    final_total = round(consultation_charge + medicine_total + diagnostic_total, 2)

    currency = "INR"
    for row in (*prescriptions, *orders):
        if row.get("currency"):
            currency = row["currency"]
            break

    enriched_prescriptions = [
        {**p, "medicine_name": (medicines.get(p.get("medicine_id")) or {}).get("name")}
        for p in prescriptions
    ]
    enriched_orders = [
        {**o, "test_name": (tests.get(o.get("test_id")) or {}).get("name")}
        for o in orders
    ]

    return {
        "appointment_id": appointment_id,
        "consultation_charge": consultation_charge,
        "medicine_total": medicine_total,
        "diagnostic_total": diagnostic_total,
        "final_total": final_total,
        "currency": currency,
        "payment_status": appointment.get("payment_status_at_booking"),
        "prescriptions": enriched_prescriptions,
        "diagnostic_test_orders": enriched_orders,
    }


def to_billing_summary(context: dict[str, Any]) -> dict[str, Any]:
    """Public billing summary shape shared by patient and doctor responses."""
    return {
        "consultation_charge": context["consultation_charge"],
        "medicine_total": context["medicine_total"],
        "diagnostic_total": context["diagnostic_total"],
        "final_total": context["final_total"],
        "currency": context["currency"],
        "payment_status": context["payment_status"],
    }


def load_appointment(admin_supabase, appointment_id: str) -> dict[str, Any]:
    """Load an appointment row or raise AppointmentNotFoundError."""
    response = (
        admin_supabase
        .table("appointments")
        .select("*")
        .eq("appointment_id", appointment_id)
        .execute()
    )
    if not response.data:
        raise AppointmentNotFoundError(appointment_id)
    return response.data[0]


def refresh_invoice_amount(appointment_id: str) -> dict[str, Any]:
    """
    Recalculate and persist ``appointments.invoice_amount`` for one
    appointment, then return its billing context.

    Called whenever a prescription or diagnostic order record changes.
    """
    admin_supabase = get_supabase_admin_client()
    appointment = load_appointment(admin_supabase, appointment_id)
    context = get_billing_context(admin_supabase, appointment)

    stored = money(appointment.get("invoice_amount"))
    if stored != context["final_total"]:
        now = datetime.now(timezone.utc)
        (
            admin_supabase
            .table("appointments")
            .update({
                "invoice_amount": context["final_total"],
                "updated_at": now.isoformat(),
            })
            .eq("appointment_id", appointment_id)
            .execute()
        )
        log_info(
            "Appointment invoice recalculated",
            appointment_id=appointment_id,
            invoice_amount=context["final_total"],
        )

    return context
