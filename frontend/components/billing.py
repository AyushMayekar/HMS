"""
Shared billing presentation for appointment invoices.

Both the patient portal and the doctor workspace render the same server-side
calculation:

    invoice_amount = consultation_charge
                   + SUM(prescriptions.total_amount)
                   + SUM(diagnostic_test_orders.total_amount)

Nothing here computes or edits money — it only displays what the backend
returns (``billing_summary`` plus the appointment's line items).
"""
from __future__ import annotations

from typing import Any, Optional

import streamlit as st

from frontend.utils.states import format_datetime, status_pill


def _money(value: Any, currency: str = "INR") -> str:
    """Format a stored amount for display."""
    try:
        return f"{currency} {float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return f"{currency} 0.00"


def render_billing_summary(billing: Optional[dict]) -> None:
    """Consultation charge, medicine total, diagnostic total, final total."""
    if not billing:
        st.caption("No billing summary is available for this visit yet.")
        return

    currency = billing.get("currency") or "INR"
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Consultation charge", _money(billing.get("consultation_charge"), currency))
    c2.metric("Medicines", _money(billing.get("medicine_total"), currency))
    c3.metric("Diagnostic tests", _money(billing.get("diagnostic_total"), currency))
    c4.metric("Total invoice", _money(billing.get("final_total"), currency))

    payment_status = billing.get("payment_status")
    if payment_status:
        st.write("**Payment status:**")
        status_pill(str(payment_status), custom_label=str(payment_status).title())
    else:
        st.caption("Payment status: not recorded yet.")


def render_prescriptions_table(rows: Optional[list]) -> None:
    """Prescriptions recorded for one appointment."""
    if not rows:
        st.caption("No prescriptions recorded for this visit yet.")
        return
    data = [
        {
            "Medicine": r.get("medicine_name") or r.get("medicine_id") or "—",
            "Qty": r.get("quantity"),
            "Dosage": r.get("dosage") or "—",
            "Frequency": r.get("frequency") or "—",
            "Days": r.get("duration_days"),
            "Prescribed": format_datetime(r.get("prescribed_at")),
            "Charge": _money(r.get("total_amount"), r.get("currency") or "INR"),
        }
        for r in rows
    ]
    st.dataframe(data, width="stretch", hide_index=True)


def render_diagnostic_orders_table(rows: Optional[list]) -> None:
    """Diagnostic orders recorded for one appointment."""
    if not rows:
        st.caption("No diagnostic tests ordered for this visit yet.")
        return
    data = [
        {
            "Test": r.get("test_name") or r.get("test_id") or "—",
            "Qty": r.get("quantity"),
            "Priority": (r.get("priority") or "routine").title(),
            "Status": (r.get("status") or "—").title(),
            "Ordered": format_datetime(r.get("ordered_at")),
            "Charge": _money(r.get("total_amount"), r.get("currency") or "INR"),
        }
        for r in rows
    ]
    st.dataframe(data, width="stretch", hide_index=True)
