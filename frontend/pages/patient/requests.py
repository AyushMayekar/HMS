"""
Patient Admin Requests page.
"""
import streamlit as st

from frontend.components.navbar import page_head, section_title, breadcrumb, privacy_banner, empty_state
from frontend.utils.session import require_role, current_user
from frontend.utils.states import display_api_error, format_datetime, status_pill
from frontend.api.services import AdminRequestService, AppointmentService, PaymentService, CatalogService
from frontend.config import REQUEST_CATEGORIES
from frontend.pages.patient._helpers import (
    appointment_context,
    build_doctor_map,
    render_flash,
    set_flash,
    short_id,
)

DESCRIPTION_MIN = 10
DESCRIPTION_MAX = 2000  # keeps the query-string payload well within server limits


def render():
    page_head(
        "Support Requests",
        "Raise and track administrative requests: refunds, billing disputes, medical records, and more.",
        noindex=True,
    )
    require_role(["patient"])
    current_user()

    breadcrumb(["Patient", "Support Requests"])
    privacy_banner()
    render_flash("requests")

    service = AdminRequestService()

    # ---------- Create ----------
    section_title("Raise a New Request", "Describe what you need and our administrative team will follow up.")

    category_labels = {c: c.replace("_", " ").title() for c in REQUEST_CATEGORIES}

    with st.form("create_request_form"):
        category = st.selectbox(
            "Category",
            list(category_labels.keys()),
            format_func=lambda c: category_labels[c],
        )
        link_kind = st.selectbox(
            "Link to a record (optional)",
            ["None", "Appointment", "Payment"],
            key="req_link_kind",
            help="Reference the appointment or invoice this request concerns.",
        )

        appt_options = {}
        pay_options = {}

        if link_kind == "Appointment":
            appts_res = AppointmentService().list(limit=100)
            appts = appts_res.data if appts_res.success else []
            if not appts_res.success:
                display_api_error(appts_res)
            doctors_res = CatalogService().doctors()
            doctor_map = build_doctor_map(doctors_res.data if doctors_res.success else [])
            appt_options = {
                appointment_context(a, doctor_map): a.get("appointment_id")
                for a in appts
            }
            if appt_options:
                st.selectbox("Appointment", list(appt_options.keys()), key="req_link_appt")
            else:
                st.caption("No appointments on record to link.")
        elif link_kind == "Payment":
            pays_res = PaymentService().list(limit=100)
            pays = pays_res.data if pays_res.success else []
            pay_options = {
                f"Payment #{p.get('payment_id', '')[:8]} · {p.get('currency', 'INR')} {p.get('amount', 0):,.2f}": p.get("payment_id")
                for p in pays
            }
            if pay_options:
                st.selectbox("Payment", list(pay_options.keys()), key="req_link_pay")
            else:
                st.caption("No payment records to link.")

        description = st.text_area(
            "Description",
            placeholder="Provide the details of your request (e.g. unexpected charge on my last invoice, request for a copy of lab reports…)",
            help=f"Be specific so the team can resolve it faster. {DESCRIPTION_MIN}-{DESCRIPTION_MAX} characters.",
            max_chars=DESCRIPTION_MAX,
        )
        st.caption(f"Description length: {len((description or '').strip())} / {DESCRIPTION_MAX} characters "
                   f"(minimum {DESCRIPTION_MIN}).")

        submitted = st.form_submit_button("Submit Request", type="primary", icon=":material/send:",
                                          width="stretch")

    if submitted:
        description_value = (description or "").strip()
        if len(description_value) < DESCRIPTION_MIN:
            st.error(f"Please provide a description of at least {DESCRIPTION_MIN} characters so the team can act on it.")
        elif len(description_value) > DESCRIPTION_MAX:
            st.error(f"Please keep the description under {DESCRIPTION_MAX} characters.")
        else:
            selected_appt = None
            selected_pay = None
            if link_kind == "Appointment":
                label = st.session_state.get("req_link_appt")
                selected_appt = appt_options.get(label)
            elif link_kind == "Payment":
                label = st.session_state.get("req_link_pay")
                selected_pay = pay_options.get(label)

            with st.spinner("Submitting your request..."):
                result = service.create(
                    category=category,
                    description=description_value,
                    appointment_id=selected_appt,
                    payment_id=selected_pay,
                )
            if result.success:
                message = (result.data or {}).get("message") or "Your request has been submitted successfully."
                request_id = (result.data or {}).get("request_id")
                if request_id:
                    message = f"{message} Reference: {short_id(request_id)}"
                set_flash("requests", "success", message)
                st.rerun()
            else:
                display_api_error(result)

    st.divider()

    # ---------- List ----------
    section_title("My Requests", "Track the status of everything you've raised.")
    filters = ["All", "pending", "in_progress", "resolved", "rejected"]
    status_filter = st.segmented_control(
        "Filter by status",
        filters,
        default="All",
        key="request_status_filter",
    )

    list_params = {}
    if status_filter != "All":
        list_params["status_filter"] = status_filter

    res = service.list(**list_params, limit=100)
    requests = res.data if res.success else []

    if not requests:
        empty_state(
            "No requests found.",
            "Use Raise a New Request above to get help from the administrative team.",
        )
    else:
        for req in requests:
            col1, col2 = st.columns([3, 1], vertical_alignment="top")
            with col1:
                category = req.get("category", "Unknown")
                req_id = short_id(req.get("request_id"))
                st.write(f"**{category.replace('_', ' ').title()}** · `{req_id}`")
                desc = req.get("description", "")
                if desc:
                    st.write(desc)

                created = req.get("created_at")
                if created:
                    st.caption(f"Requested {format_datetime(created)}")
                updated = req.get("updated_at")
                if updated and updated != created:
                    st.caption(f"Updated {format_datetime(updated)}")

                resolution = req.get("resolution")
                if resolution:
                    st.caption(f"**Resolution:** {resolution}")
                elif req.get("assigned_to"):
                    st.caption(f"Assigned to: {req.get('assigned_to')}")
            with col2:
                status_pill(req.get("status", "unknown"))


if __name__ == "__main__":
    render()