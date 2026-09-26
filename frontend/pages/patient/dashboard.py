"""
Patient Dashboard page.

A read-only overview: the next visit, outstanding invoices, departments and a
compact reminders/requests panel — all backed by live backend data. Counts,
lists, booking and every appointment action live on the consolidated
Appointments page (History / Payments / Feedback are sections there).
"""
import streamlit as st

from frontend.components.navbar import (
    page_head,
    section_title,
    breadcrumb,
    privacy_banner,
    empty_state,
)
from frontend.components.cards import department_card
from frontend.components.ui import expandable_row, loading, page_slice
from frontend.utils.session import require_role, current_user
from frontend.utils.states import status_pill, format_datetime, display_api_error
from frontend.api.services import (
    AppointmentService,
    PaymentService,
    AdminRequestService,
    ReminderService,
    CatalogService,
)
from frontend.pages.patient.appointments import open_section
from frontend.pages.patient._helpers import (
    build_doctor_map,
    doctor_display,
    is_checked_in,
    predicted_wait_minutes,
    render_flash,
    short_id,
)

DEPARTMENT_CARD_LIMIT = 6
REMINDERS_PAGE_SIZE = 5   # reminders per page in the status panel
REQUESTS_PAGE_SIZE = 5    # requests per page in the status panel


def render():
    page_head(
        "Patient Dashboard",
        "Your care overview: appointments, payments, and requests.",
        noindex=True,
    )

    require_role(["patient"])
    user = current_user()

    breadcrumb(["Patient", "Dashboard"])
    privacy_banner()
    render_flash("dashboard")

    if st.session_state.pop("_show_welcome_toast", False):
        st.toast("Successfully signed in. Welcome to your patient portal.")

    # ------------------------------------------------------------------
    # Load dashboard data (only what this screen renders)
    # ------------------------------------------------------------------
    appt_service = AppointmentService()
    pay_service = PaymentService()
    catalog = CatalogService()

    with loading("Loading your dashboard"):
        appointments_res = appt_service.list(limit=100)
        payments_res = pay_service.list()
        dept_res = catalog.departments()
        doctors_res = catalog.doctors()

    for response in (appointments_res, payments_res, dept_res, doctors_res):
        if not response.success:
            display_api_error(response)

    appointments = appointments_res.data if appointments_res.success else []
    payments = payments_res.data if payments_res.success else []
    departments = (dept_res.data or []) if (dept_res.success and dept_res.data) else []
    doctor_map = build_doctor_map(doctors_res.data if doctors_res.success else [])

    upcoming = [
        a for a in appointments
        if a.get("appointment_status") not in ("completed", "cancelled", "no_show")
    ]
    upcoming.sort(key=lambda a: a.get("scheduled_start") or "")
    pending_payments = sum(1 for p in payments if p.get("status") == "pending")

    # ------------------------------------------------------------------
    # Welcome — counts and appointment actions now live on the consolidated
    # Appointments hub (History / Payments / Feedback are sections there),
    # so this screen stays a read-only overview that links into it.
    # ------------------------------------------------------------------
    section_title(
        f"Welcome, {user.display_name}",
        "Review your hospital activity below, or open Appointments for booking, "
        "history, feedback and payments.",
    )

    if pending_payments:
        st.info(
            f"You have {pending_payments} outstanding invoice"
            f"{'s' if pending_payments != 1 else ''}. "
            f"{'Settle it' if pending_payments == 1 else 'Settle them'} "
            "from the Payments section of Appointments."
        )

    st.divider()

    # ------------------------------------------------------------------
    # Next visit — one compact preview; booking, rescheduling and cancelling
    # all live on the Appointments hub.
    # ------------------------------------------------------------------
    section_title(
        "Next Visit",
        "The essentials at a glance. Book, reschedule and cancel from Appointments.",
    )

    if not upcoming:
        empty_state(
            "No upcoming appointments",
            "Open Appointments to book a visit with one of our specialists.",
            icon="",
        )
    else:
        _render_next_visit(upcoming[0], doctor_map, total=len(upcoming))

    _render_hub_links(pending_payments)

    st.divider()

    # ------------------------------------------------------------------
    # Departments (equal-height cards, description revealed on demand)
    # ------------------------------------------------------------------
    section_title(
        "Hospital Departments",
        "Live information about our specialties, open a card for the full description.",
    )

    if not departments:
        if not dept_res.success:
            empty_state(
                "Department information could not be loaded.",
                "Please try again in a moment.",
                icon="",
            )
        else:
            empty_state("No departments are listed yet.", "Please check back soon.", icon="")
    else:
        visible = departments[:DEPARTMENT_CARD_LIMIT]
        with st.container(key="mc_dept_grid"):
            for i in range(0, len(visible), 3):
                cols = st.columns(3, gap="medium")
                for j, col in enumerate(cols):
                    idx = i + j
                    if idx < len(visible):
                        with col:
                            _render_department_card(visible[idx])

        registry = st.session_state.get("_mc_pages", {})
        departments_page = registry.get("departments") or "pages/public/departments.py"
        st.page_link(
            departments_page,
            label="View departments",
            icon=":material/local_hospital:",
            width="stretch",
        )

    st.divider()

    # ------------------------------------------------------------------
    # Reminders + request status (fetched only when opened)
    # ------------------------------------------------------------------
    render_status_panel()


def render_status_panel() -> None:
    """Reminders and administrative requests, loaded when the panel opens."""
    section_title("Reminders & Requests")

    def body():
        rem_service = ReminderService()
        req_service = AdminRequestService()
        with loading("Loading reminders and requests"):
            reminders_res = rem_service.list()
            requests_res = req_service.list()

        for response in (reminders_res, requests_res):
            if not response.success:
                display_api_error(response)

        reminders = reminders_res.data if reminders_res.success else []
        requests = requests_res.data if requests_res.success else []

        st.markdown("**Reminders**")
        if not reminders:
            st.caption("No appointment reminders yet. Staff send reminders for higher-risk visits.")
        else:
            rem_rows, _, _ = page_slice(
                reminders, len(reminders), REMINDERS_PAGE_SIZE, "dash_reminders_page",
            )
            for rem in rem_rows:
                st.caption(
                    f"Sent {format_datetime(rem.get('sent_at') or rem.get('created_at'))} "
                    f"· Reference {short_id(rem.get('appointment_id'))}"
                )

        st.markdown("**Requests**")
        if not requests:
            st.caption("You have not submitted any administrative requests.")
        else:
            req_rows, _, _ = page_slice(
                requests, len(requests), REQUESTS_PAGE_SIZE, "dash_requests_page",
            )
            for req in req_rows:
                status = str(req.get("status") or "").replace("_", " ").title()
                st.caption(
                    f"{status} · {str(req.get('category') or 'request').replace('_', ' ').title()} "
                    f"· {format_datetime(req.get('created_at'))}"
                )

    expandable_row(
        "patient_dash_status",
        title="Reminders and request status",
        meta="Open to see the latest appointment reminders and the state of your requests.",
        pill=None,
        actions=body,
    )


def _render_next_visit(appt: dict, doctor_map: dict, total: int) -> None:
    """Read-only preview of the nearest appointment — the hub owns the actions."""
    status = appt.get("appointment_status") or "unknown"
    dept = appt.get("department_name") or "Department"

    with st.container(border=True):
        left, right = st.columns([5, 1], vertical_alignment="top")
        with left:
            st.markdown(f"**{dept} · {doctor_display(doctor_map, appt.get('doctor_id'))}**")
            st.caption(
                f"{format_datetime(appt.get('scheduled_start'))} · "
                f"Appointment {short_id(appt.get('appointment_id'))}"
            )
        with right:
            status_pill(status)

        if is_checked_in(appt):
            wait = predicted_wait_minutes(appt)
            checked_in_at = format_datetime(appt.get("actual_checkin_time"))
            if wait is not None:
                st.info(f"Checked in at {checked_in_at} · Predicted waiting time: about {wait} min")
            else:
                st.info(
                    f"Checked in at {checked_in_at}. Your predicted waiting time "
                    "will appear here as soon as it is available."
                )

        if total > 1:
            st.caption(
                f"{total} upcoming appointments in total. Open Appointments to "
                "review and manage all of them."
            )


def _render_hub_links(pending_payments: int) -> None:
    """Entry points into the consolidated Appointments hub."""
    registry = st.session_state.get("_mc_pages", {}) or {}
    appointments_page = registry.get("patient_appointments") or "pages/patient/appointments.py"

    if pending_payments:
        left, right = st.columns([3, 2], gap="small")
        with left:
            st.page_link(
                appointments_page,
                label="Open Appointments",
                icon=":material/calendar_month:",
                width="stretch",
            )
        with right:
            if st.button(
                "Open Payments",
                key="dash_open_payments",
                icon=":material/credit_card:",
                width="stretch",
            ):
                open_section("Payments")
    else:
        st.page_link(
            appointments_page,
            label="Open Appointments",
            icon=":material/calendar_month:",
            width="stretch",
        )


def _render_department_card(dept: dict) -> None:
    """Equal-height department card; the description expands in place."""
    name = dept.get("name") or "Unknown department"
    desc = dept.get("description") or ""
    status = dept.get("status") or "active"
    open_key = f"dept_open::{dept.get('department_id')}"

    with st.container(border=True):
        head_left, head_right = st.columns([4, 1], vertical_alignment="top")
        with head_left:
            st.markdown(f"**{name}**")
        with head_right:
            status_pill(status)

        is_open = bool(st.session_state.get(open_key, False))
        if desc:
            if is_open:
                st.write(desc)
            else:
                st.markdown(f'<div class="mc-clamp-3">{desc}</div>', unsafe_allow_html=True)
        if is_open and dept.get("information"):
            st.caption(str(dept.get("information")))

        label = "Show less" if is_open else "Show more"
        if st.button(label, key=f"dept_toggle_{dept.get('department_id')}", width="stretch"):
            st.session_state[open_key] = not is_open
            st.rerun()


if __name__ == "__main__":
    render()
