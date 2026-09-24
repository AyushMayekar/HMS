"""
Patient Payments page.

Pay an outstanding invoice with a validated payment method (card / UPI / cash),
then track every transaction with clear pending / paid / failed states.
Payment processing is simulated backend-side.
"""
import streamlit as st

from frontend.components.navbar import page_head, section_title, breadcrumb, privacy_banner, empty_state
from frontend.utils.session import require_role, current_user
from frontend.utils.states import status_pill, format_datetime, display_api_error
from frontend.api.services import PaymentService, AppointmentService, CatalogService
from frontend.pages.patient._helpers import (
    build_doctor_map,
    card_number_error,
    doctor_display,
    render_flash,
    set_flash,
    short_id,
    upi_id_error,
)

PAYMENT_METHODS = {
    "card": "Credit / Debit Card",
    "upi": "UPI",
    "cash": "Cash",
}

# Backend payment statuses -> pill status keys (config knows paid/failed/pending).
_PILL_STATUS = {
    "success": "paid",
    "paid": "paid",
    "pending": "pending",
    "failed": "failed",
    "refunded": "refunded",
}

_FILTERS = {
    "Paid": ("success", "paid"),
    "Pending": ("pending",),
    "Failed": ("failed",),
    "Refunded": ("refunded",),
}


def _payment_reference_error(method: str, value: str):
    """Inline validation for the per-method payment reference."""
    if method == "card":
        return card_number_error(value)
    if method == "upi":
        return upi_id_error(value)
    return None  # cash needs no online reference


def render():
    page_head(
        "Payments",
        "View your invoices and make secure payments for consultations.",
        noindex=True,
    )
    require_role(["patient"])
    current_user()

    breadcrumb(["Patient", "Payments"])
    privacy_banner()
    render_flash("payments")

    pay_service = PaymentService()
    appt_service = AppointmentService()

    # ---------- Make a payment ----------
    section_title("Make a Payment", "Pay an outstanding invoice for a booking.")

    appts_res = appt_service.list(limit=100)
    doctors_res = CatalogService().doctors()
    if not appts_res.success:
        display_api_error(appts_res)
    if not doctors_res.success:
        display_api_error(doctors_res)

    appts = appts_res.data if appts_res.success else []
    doctor_map = build_doctor_map(doctors_res.data if doctors_res.success else [])

    # Only real outstanding invoices: not cancelled / no-show, and the booking
    # was not already settled at booking time.
    eligible = [
        a for a in appts
        if a.get("appointment_status") not in ("cancelled", "no_show")
        and a.get("payment_status_at_booking") in (None, "pending", "unpaid")
    ]

    if not eligible:
        st.info("You have no outstanding invoices at the moment.")
    else:
        eligible.sort(key=lambda a: a.get("scheduled_start") or "")
        appt_options = {
            f"{a.get('department_name') or 'Department'} · "
            f"{doctor_display(doctor_map, a.get('doctor_id'))} · "
            f"{format_datetime(a.get('scheduled_start'))} · "
            f"ID {short_id(a.get('appointment_id'))}": a
            for a in eligible
        }

        pick = st.selectbox("Select booking", list(appt_options.keys()), key="pay_appt_pick")
        appt = appt_options[pick]
        default_amount = float(appt.get("invoice_amount") or 0) or 1.0

        # The amount is derived by the server from the appointment invoice
        # (consultation charge + prescriptions + diagnostic orders); it is
        # intentionally not client-editable.
        st.caption(
            f"Billed amount: **INR {default_amount:,.2f}** — "
            "the payment amount is taken from your visit's invoice "
            "(consultation charge + medicines + diagnostic tests)."
        )

        method = st.selectbox(
            "Payment method",
            list(PAYMENT_METHODS.keys()),
            format_func=lambda m: PAYMENT_METHODS[m],
            key="pay_method_select",
        )

        # Per-method required inputs (validated inline before submitting).
        reference = ""
        reference_error = None
        if method == "card":
            reference = st.text_input(
                "Card number",
                placeholder="1234 5678 9012 3456",
                key="pay_card_number",
                max_chars=23,
                help="12-19 digits. Spaces are allowed.",
            )
            reference_error = card_number_error(reference) if reference else None
            if reference and reference_error:
                st.error(reference_error)
        elif method == "upi":
            reference = st.text_input(
                "UPI ID",
                placeholder="name@bank",
                key="pay_upi_id",
                help="Enter your UPI ID in the format name@bank.",
            )
            reference_error = upi_id_error(reference) if reference else None
            if reference and reference_error:
                st.error(reference_error)
        else:
            st.caption("No online payment reference is required for cash payments.")

        insurance_used = st.checkbox("Pay with insurance", key="pay_insurance",
                                     help="Use your insurance coverage for this visit.")
        claim_required = st.checkbox("Submit insurance claim", key="pay_claim",
                                     help="Request a claim to be initiated.",
                                     disabled=not insurance_used)

        # Validate on submit; keep the contextual message next to the field.
        submitted = st.button("Pay Now", type="primary", icon=":material/credit_card:",
                              width="stretch")

        if submitted:
            if method in ("card", "upi"):
                reference_error = _payment_reference_error(method, reference)
                if reference_error:
                    st.error(reference_error)
                    return

            with st.spinner("Processing payment..."):
                result = pay_service.create(
                    appointment_id=appt.get("appointment_id"),
                    payment_method=method,
                    insurance_used=bool(insurance_used),
                    claim_required=bool(claim_required),
                    # Method-specific input (card number / UPI id); validated
                    # inline here and again by the backend.
                    payment_method_reference=(
                        reference.strip() if method in ("card", "upi") else None
                    ),
                )

            if not result.success:
                display_api_error(result)
                return

            data = result.data or {}
            status = data.get("status")
            txn_ref = data.get("transaction_reference")
            ref_note = f" Reference: {txn_ref}." if txn_ref else ""
            paid_amount = float(data.get("amount") or default_amount)
            amount_note = f"INR {paid_amount:,.2f} via {PAYMENT_METHODS[method]}"

            if status == "success":
                set_flash(
                    "payments",
                    "success",
                    f"Payment of {amount_note} succeeded.{ref_note} A receipt has been issued for this visit.",
                )
                st.rerun()
            elif status == "failed":
                st.error(
                    f"The payment of {amount_note} could not be completed.{ref_note} "
                    "Please try again or use a different method."
                )
            else:
                st.warning(
                    f"Payment of {amount_note} is pending.{ref_note} "
                    "You will be notified once it is confirmed."
                )

    st.divider()

    # ---------- History ----------
    section_title("Payment History", "All transactions on your account, newest first.")
    filter_labels = ["All"] + list(_FILTERS.keys())
    status_filter = st.segmented_control(
        "Filter",
        filter_labels,
        default="All",
        key="payments_status_filter",
    )

    res = pay_service.list(limit=200)
    if not res.success:
        display_api_error(res)
    payments = res.data if res.success else []

    if status_filter and status_filter != "All":
        allowed = _FILTERS.get(status_filter, ())
        payments = [p for p in payments if p.get("status") in allowed]

    if not payments:
        empty_state("No payments found.", "Payments you make will appear here with their receipts.", icon="")
        return

    total_paid = sum(p.get("amount", 0) or 0 for p in payments
                     if p.get("status") in ("success", "paid"))
    k1, k2, k3 = st.columns(3)
    k1.metric("Transactions", len(payments))
    k2.metric("Total settled (INR)", f"{total_paid:,.2f}")
    k3.metric("Pending", sum(1 for p in payments if p.get("status") == "pending"))

    for p in payments:
        with st.container(border=True):
            col1, col2 = st.columns([3, 1], vertical_alignment="top")
            with col1:
                paid_amount = p.get("amount", 0) or 0
                currency = p.get("currency", "INR")
                method_value = p.get("payment_method", "")
                ref = p.get("transaction_reference", "")
                method_text = f" · via {PAYMENT_METHODS.get(method_value, method_value)}" if method_value else ""
                st.write(f"**{currency} {paid_amount:,.2f}**{method_text}")
                st.caption(f"Appointment: {short_id(p.get('appointment_id'))}")
                if ref:
                    st.caption(f"Reference: {ref}")
                st.caption(f"Initiated {format_datetime(p.get('initiated_at') or p.get('created_at'))}")
                if p.get("paid_at"):
                    st.caption(f"Paid {format_datetime(p.get('paid_at'))}")
            with col2:
                raw_status = p.get("status", "unknown")
                status_pill(_PILL_STATUS.get(raw_status, raw_status))


if __name__ == "__main__":
    render()
