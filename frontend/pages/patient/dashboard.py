"""
Patient Dashboard page.

Upcoming appointments, departments and a compact reminders/requests panel —
all backed by live backend data. Booking lives on the Appointments page.
"""
import streamlit as st

from frontend.components.navbar import (
    page_head,
    section_title,
    breadcrumb,
    privacy_banner,
    empty_state,
)
from frontend.components.cards import kpi_row, department_card
from frontend.components.ui import expandable_row, loading
from frontend.utils.session import require_role, current_user
from frontend.utils.states import status_pill, format_datetime, display_api_error
from frontend.api.services import (
    AppointmentService,
    PaymentService,
    AdminRequestService,
    ReminderService,
    CatalogService,
)
from frontend.pages.patient._helpers import (
    build_doctor_map,
    doctor_display,
    is_checked_in,
    predicted_wait_minutes,
    render_flash,
    short_id,
)

DEPARTMENT_CARD_LIMIT = 6


def render():
    page_head(
        "Patient Dashboard",
        "Your care overview — appointments, payments, and requests.",
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
    completed = [a for a in appointments if a.get("appointment_status") == "completed"]
    pending_payments = sum(1 for p in payments if p.get("status") == "pending")

    # ------------------------------------------------------------------
    # Welcome + KPIs
    # ------------------------------------------------------------------
    section_title(
        f"Welcome, {user.display_name}",
        "Review your hospital activity below, or open Appointments for booking, "
        "history, feedback and payments.",
    )

    kpi_row([
        ("Appointments", len(appointments), None, None),
        ("Upcoming", len(upcoming), None, None),
        ("Completed visits", len(completed), None, None),
        ("Pending payments", pending_payments, None, None),
    ])

    st.divider()

    # ------------------------------------------------------------------
    # Upcoming appointments — compact expandable bars
    # ------------------------------------------------------------------
    section_title(
        "Upcoming Appointments",
        "Open a visit to see the waiting forecast and reschedule or cancel it.",
    )

    if not upcoming:
        empty_state(
            "No upcoming appointments",
            "Open Appointments to book a visit with one of our specialists.",
            icon="",
        )
    for appt in upcoming[:6]:
        _render_upcoming_row(appt, doctor_map)

    st.divider()

    # ------------------------------------------------------------------
    # Departments (equal-height cards, description revealed on demand)
    # ------------------------------------------------------------------
    section_title(
        "Hospital Departments",
        "Live information about our specialties — open a card for the full description.",
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
            for rem in reminders[:3]:
                st.caption(
                    f"Sent {format_datetime(rem.get('sent_at') or rem.get('created_at'))} "
                    f"· Reference {short_id(rem.get('appointment_id'))}"
                )

        st.markdown("**Requests**")
        if not requests:
            st.caption("You have not submitted any administrative requests.")
        else:
            for req in requests[:5]:
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


def _render_upcoming_row(appt: dict, doctor_map: dict) -> None:
    """One upcoming appointment: essentials collapsed, details and actions open."""
    status = appt.get("appointment_status") or "unknown"
    dept = appt.get("department_name") or "Department"

    meta = (
        f"{format_datetime(appt.get('scheduled_start'))} · "
        f"{doctor_display(doctor_map, appt.get('doctor_id'))} · "
        f"Appointment {short_id(appt.get('appointment_id'))}"
    )

    def actions():
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

        if status in ("booked", "confirmed"):
            c1, c2 = st.columns(2, gap="small")
            with c1:
                if st.button(
                    "Reschedule",
                    key=f"dash_reschedule_{appt.get('appointment_id')}",
                    icon=":material/event:",
                    width="stretch",
                ):
                    st.session_state["reschedule_target"] = appt.get("appointment_id")
                    st.switch_page("pages/patient/appointments.py")
            with c2:
                if st.button(
                    "Cancel appointment",
                    key=f"dash_cancel_{appt.get('appointment_id')}",
                    width="stretch",
                ):
                    st.session_state["cancel_target"] = appt.get("appointment_id")
                    st.switch_page("pages/patient/appointments.py")
        else:
            st.caption("This visit is with the clinical team. Changes are handled at the care desk.")

    expandable_row(
        str(appt.get("appointment_id")),
        title=f"{dept} · {doctor_display(doctor_map, appt.get('doctor_id'))}",
        meta=meta,
        pill=status,
        id_text=f"Appointment {appt.get('appointment_id')}",
        actions=actions,
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
