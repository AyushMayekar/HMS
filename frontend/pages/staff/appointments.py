"""
Staff Appointments (Operations) page.
"""
from __future__ import annotations

from datetime import timedelta

import streamlit as st

from frontend.components.navbar import page_head, section_title, breadcrumb, empty_state
from frontend.components.analytics import (
    department_selector,
    extract_predicted_wait,
    format_percent,
    hospital_now,
    is_scheduled_in_past,
    parse_timestamp,
    remember_predicted_wait,
)
from frontend.utils.session import require_role, current_user
from frontend.utils.states import display_api_error, format_datetime, status_pill
from frontend.api.staff_admin_services import StaffAppointmentService
from frontend.config import APPOINTMENT_STATUSES

STATUS_OPTIONS = ["All"] + list(APPOINTMENT_STATUSES.keys())
DATE_FILTER_OPTIONS = ["Any date", "Today", "Tomorrow", "Next 7 days", "Past dates"]

CONFIRM_KEY = "staff_checkin_confirm"
FLASH_KEY = "staff_action_flash"

RESOLVED_STATUSES = ("completed", "cancelled", "no_show")


def render():
    page_head(
        "Appointment Operations",
        "Check patients in, run the visit lifecycle, and flag no-shows — with full patient, doctor, and department details.",
        noindex=True,
    )
    require_role(["staff"])
    current_user()

    breadcrumb(["Staff", "Appointments"])

    # ---------- Feedback from the previous action ----------
    flash = st.session_state.pop(FLASH_KEY, None)
    if flash:
        st.success(flash.get("message", "Action completed."))
        if flash.get("wait_minutes") is not None:
            with st.container(border=True):
                wc1, wc2 = st.columns([1, 3])
                with wc1:
                    st.metric("Predicted waiting time", f"{round(flash['wait_minutes'])} min")
                with wc2:
                    st.caption(
                        f"Estimated wait after check-in for {flash.get('patient', 'the patient')}, "
                        "returned by the check-in service. It also appears on today's visit cards "
                        "while the visit is still active."
                    )

    # ---------- Filters ----------
    col1, col2, col3 = st.columns(3)
    with col1:
        status_filter = st.selectbox(
            "Appointment status",
            STATUS_OPTIONS,
            format_func=lambda s: APPOINTMENT_STATUSES.get(s, "All statuses"),
            key="staff_appt_status",
        )
    with col2:
        dept_name, dept_id = department_selector(key_prefix="staff_appt")
    with col3:
        date_filter = st.selectbox(
            "Scheduled date",
            DATE_FILTER_OPTIONS,
            key="staff_appt_date",
            help="Filters visits by their scheduled date in the hospital's local time.",
        )

    query = {}
    if status_filter != "All":
        query["status"] = status_filter
    if dept_id:
        query["department_id"] = dept_id

    service = StaffAppointmentService()
    res = service.list(limit=200, **query)
    if not res.success:
        display_api_error(res)
        st.stop()

    appointments = [a for a in (res.data or []) if matches_date_filter(a, date_filter)]
    appointments.sort(key=lambda a: str(a.get("scheduled_start") or ""))

    if not appointments:
        if res.data:
            empty_state(
                "No appointments match the current filters.",
                "Adjust the status, department, or scheduled-date filter.",
                icon="",
            )
        else:
            empty_state("No appointments found.", "New bookings will appear here.", icon="")
        return

    section_title(
        f"{len(appointments)} appointment(s)",
        "Soonest first — patient, doctor, and department details with the available check-in actions.",
    )

    for a in appointments:
        render_operation_row(a, service)


def matches_date_filter(a: dict, date_filter: str) -> bool:
    """Frontend date filtering (the API has no date parameter)."""
    if date_filter == "Any date":
        return True
    start = parse_timestamp(a.get("scheduled_start"))
    if start is None:
        return True
    day = start.date()
    today = hospital_now().date()
    if date_filter == "Today":
        return day == today
    if date_filter == "Tomorrow":
        return day == today + timedelta(days=1)
    if date_filter == "Next 7 days":
        return today <= day <= today + timedelta(days=7)
    if date_filter == "Past dates":
        return day < today
    return True


def render_operation_row(a: dict, service: StaffAppointmentService) -> None:
    """Render an appointment with its operational details and lifecycle actions."""
    appointment_id = a.get("appointment_id")
    status = a.get("appointment_status")
    checked_in = bool(a.get("actual_checkin_time"))
    service_started = bool(a.get("actual_service_start"))
    service_ended = bool(a.get("actual_service_end"))
    resolved = status in RESOLVED_STATUSES
    past = is_scheduled_in_past(a.get("scheduled_start"))
    patient = a.get("patient_name") or "Patient name not available"

    with st.container(border=True):
        col1, col2, col3 = st.columns([3.2, 1.3, 1])
        with col1:
            st.write(
                f"**{patient}** · {a.get('department_name') or 'Department not set'} · "
                f"Dr. {a.get('doctor_name') or 'Doctor'}"
            )
            details = [format_datetime(a.get("scheduled_start"))]
            if a.get("patient_email"):
                details.append(str(a.get("patient_email")))
            details.append(f"Appointment `#{str(appointment_id or '')[:8]}`")
            if a.get("reason"):
                details.append(str(a.get("reason")))
            st.caption(" · ".join(details))
        with col2:
            probability = a.get("no_show_probability")
            st.metric(
                "Predicted no-show",
                format_percent(probability) if probability is not None else "—",
                help="Likelihood, from the ML model, that this patient will not attend.",
            )
        with col3:
            status_pill(status or "unknown")

        if checked_in:
            queue = a.get("patients_ahead_at_checkin")
            queue_text = f" · {queue} patient(s) ahead in the queue" if queue is not None else ""
            st.caption(f"Checked in at {format_datetime(a.get('actual_checkin_time'))}{queue_text}")
        if service_started:
            st.caption(f"Service started at {format_datetime(a.get('actual_service_start'))}")
        if service_ended:
            st.caption(f"Service ended at {format_datetime(a.get('actual_service_end'))}")

        # Pre-check-in waiting-time hint (booking estimate only)
        if status == "booked" and not checked_in and not past:
            estimate = a.get("predicted_wait_minutes")
            if estimate is not None:
                st.caption(f"Estimated wait at booking: {round(estimate)} min")

        if resolved:
            return

        confirm_id = st.session_state.get(CONFIRM_KEY)
        confirm_pending = confirm_id is not None and str(confirm_id) == str(appointment_id)
        can_checkin = status == "booked" and not checked_in and not past
        can_no_show = status == "booked" and not checked_in and not past
        can_start = checked_in and not service_started
        can_end = service_started and not service_ended

        if confirm_pending:
            render_checkin_confirmation(a, service, patient)
            return

        actions = []
        if can_checkin:
            actions.append("checkin")
        if can_no_show:
            actions.append("noshown")
        if can_start:
            actions.append("start")
        if can_end:
            actions.append("end")

        if not actions:
            if status == "booked" and not checked_in and past:
                st.caption(
                    "The scheduled time has passed — check-in and no-show actions are "
                    "no longer available for this visit."
                )
            return

        cols = st.columns(len(actions), gap="small")
        for col, action in zip(cols, actions):
            with col:
                if action == "checkin":
                    if st.button(
                        "Check In",
                        key=f"op_checkin_{appointment_id}",
                        type="primary",
                        width="stretch",
                    ):
                        st.session_state[CONFIRM_KEY] = appointment_id
                        st.rerun()
                elif action == "noshown":
                    if st.button(
                        "Mark No-Show",
                        key=f"op_noshow_{appointment_id}",
                        width="stretch",
                    ):
                        run_action(
                            service.mark_no_show,
                            a,
                            f"{patient} marked as no-show.",
                        )
                elif action == "start":
                    if st.button(
                        "Start Service",
                        key=f"op_start_{appointment_id}",
                        type="primary",
                        width="stretch",
                    ):
                        run_action(
                            service.start_service,
                            a,
                            f"Service started for {patient}.",
                        )
                elif action == "end":
                    if st.button(
                        "End Service",
                        key=f"op_end_{appointment_id}",
                        type="primary",
                        width="stretch",
                    ):
                        run_action(
                            service.end_service,
                            a,
                            f"Service ended for {patient}.",
                        )


def render_checkin_confirmation(a: dict, service: StaffAppointmentService, patient: str) -> None:
    """Inline confirmation step shown before a check-in is submitted."""
    appointment_id = a.get("appointment_id")
    st.warning(f"Check in {patient}? Confirm to record the check-in now, or cancel to go back.")

    c1, c2 = st.columns(2, gap="small")
    with c1:
        confirmed = st.button(
            "Confirm",
            key=f"op_checkin_confirm_{appointment_id}",
            type="primary",
            width="stretch",
        )
    with c2:
        cancelled = st.button(
            "Cancel",
            key=f"op_checkin_cancel_{appointment_id}",
            width="stretch",
        )

    if cancelled:
        st.session_state.pop(CONFIRM_KEY, None)
        st.rerun()
    if confirmed:
        st.session_state.pop(CONFIRM_KEY, None)
        result = service.check_in(appointment_id)
        if result.success:
            wait = extract_predicted_wait(result.data)
            remember_predicted_wait(appointment_id, wait)
            st.session_state[FLASH_KEY] = {
                "message": f"{patient} checked in successfully.",
                "wait_minutes": wait,
                "patient": patient,
            }
            st.rerun()
        else:
            display_api_error(result)


def run_action(action, a: dict, success_text: str) -> None:
    """Run a staff lifecycle action and standardize the feedback."""
    result = action(a.get("appointment_id"))
    if result.success:
        st.session_state[FLASH_KEY] = {"message": success_text}
        st.rerun()
    else:
        display_api_error(result)


if __name__ == "__main__":
    render()
