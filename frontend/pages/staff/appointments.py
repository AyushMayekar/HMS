"""
Staff Appointments (Operations) content.

The list itself (filters, rows, Check In / No-Show) lives here and is shared: ``render()`` keeps this file usable as a standalone
page, while ``render_content()`` is what the merged Staff Operations page
(``staff/dashboard.py``) renders inside its radio switch — the same pattern
admin Management uses. Both surfaces therefore run the same API calls through
one row renderer instead of two near-copies.
"""
from __future__ import annotations

from datetime import timedelta

import streamlit as st

from frontend.components.navbar import page_head, section_title, breadcrumb, empty_state
from frontend.components.ui import doctor_label, expandable_row, loading, page_slice
from frontend.components.analytics import (
    department_selector,
    extract_predicted_wait,
    get_predicted_wait,
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
PAGE_SIZE = 10
PAGE_KEY = "staff_appt_page"

CONFIRM_KEY = "staff_checkin_confirm"
FLASH_KEY = "staff_action_flash"

RESOLVED_STATUSES = ("completed", "cancelled", "no_show")


def render():
    """Standalone page entry — kept for direct navigation and page links."""
    page_head(
        "Appointment Operations",
        "Check patients in, run the visit lifecycle, and flag no-shows, with full patient, doctor, and department details.",
        noindex=True,
    )
    require_role(["staff"])
    current_user()

    breadcrumb(["Staff", "Appointments"])

    render_flash()
    render_content()


def render_flash() -> None:
    """Success feedback from the previous check-in / lifecycle action."""
    flash = st.session_state.pop(FLASH_KEY, None)
    if not flash:
        return
    message = flash.get("message", "Action completed.") if isinstance(flash, dict) else str(flash)
    st.success(message)
    if not isinstance(flash, dict) or flash.get("wait_minutes") is None:
        return
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


def render_content() -> None:
    """Filters plus the paginated appointment list — no page chrome.

    Rendered by this file's own ``render()`` and by the merged Staff
    Operations page, so there is exactly one staff list, one row renderer and
    one set of lifecycle actions behind both entry points.
    """
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
    with loading("Loading appointments"):
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
        "Soonest first. Open a row to see the check-in actions.",
    )
    render_paginated_rows(appointments, service, page_key=PAGE_KEY)


def render_paginated_rows(
    rows: list[dict],
    service: StaffAppointmentService,
    *,
    page_key: str,
    group_by_department: bool = False,
) -> None:
    """Render ``rows`` one page at a time through the shared operation row.

    The page math is the last step, after every status / department / date /
    "today" filter has been applied, so the "showing x–y of z" bar always
    describes the filtered result set. When ``group_by_department`` is set the
    current page is grouped under a department heading before rendering.
    """
    page_rows, _offset, _limit = page_slice(rows, len(rows), PAGE_SIZE, page_key)

    if not group_by_department:
        for a in page_rows:
            render_operation_row(a, service)
        return

    grouped: dict[str, list[dict]] = {}
    for a in page_rows:
        grouped.setdefault(a.get("department_name") or "Unassigned department", []).append(a)
    for dept in sorted(grouped):
        section_title(dept, f"{len(grouped[dept])} visit(s) in this department on this page.")
        for a in grouped[dept]:
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
    """Compact bar: essentials collapsed, check-in / no-show actions expanded."""
    appointment_id = a.get("appointment_id")
    status = a.get("appointment_status")
    checked_in = bool(a.get("actual_checkin_time"))
    service_started = bool(a.get("actual_service_start"))
    service_ended = bool(a.get("actual_service_end"))
    resolved = status in RESOLVED_STATUSES
    past = is_scheduled_in_past(a.get("scheduled_start"))
    patient = a.get("patient_name") or "Patient name not available"

    meta = (
        f"{format_datetime(a.get('scheduled_start'))} · "
        f"{a.get('department_name') or 'Department not set'} · "
        f"{doctor_label(a.get('doctor_name'))}"
    )
    extra_bits = []
    if a.get("patient_email"):
        extra_bits.append(str(a.get("patient_email")))
    if a.get("reason"):
        extra_bits.append(str(a.get("reason")))
    if status == "booked" and not checked_in and not past and a.get("predicted_wait_minutes") is not None:
        extra_bits.append(f"Estimated wait at booking: {round(a['predicted_wait_minutes'])} min")
    if extra_bits:
        meta = f"{meta} · " + " · ".join(extra_bits)

    # Lifecycle timestamps each get their own line instead of being
    # " · "-joined onto the summary line.
    meta_lines = []
    if checked_in:
        queue = a.get("patients_ahead_at_checkin")
        queue_text = f", {queue} patient(s) ahead" if queue is not None else ""
        meta_lines.append(f"Checked in at {format_datetime(a.get('actual_checkin_time'))}{queue_text}")
        if status != "completed":
            wait = extract_predicted_wait(a)
            if wait is None:
                wait = get_predicted_wait(appointment_id)
            if wait is not None:
                meta_lines.append(f"Predicted wait {round(wait)} min")
    if service_started:
        meta_lines.append(f"Service started at {format_datetime(a.get('actual_service_start'))}")
    if service_ended:
        meta_lines.append(f"Service ended at {format_datetime(a.get('actual_service_end'))}")

    def actions():
        if resolved:
            st.caption("This visit is resolved, no actions are available.")
            return

        # The front desk's job ends at check-in: once a visit is checked in it
        # shows no buttons at all, only context — Start / End Service is the
        # clinician's action and lives on the doctor's Consultations page.
        can_checkin = status == "booked" and not checked_in and not past
        can_no_show = status == "booked" and not checked_in and not past

        confirm_id = st.session_state.get(CONFIRM_KEY)
        if confirm_id is not None and str(confirm_id) == str(appointment_id):
            if can_checkin:
                render_checkin_confirmation(a, service, patient)
                return
            # Prompt left over from an earlier click — drop it rather than
            # offer Confirm / Cancel on a visit that is already checked in.
            st.session_state.pop(CONFIRM_KEY, None)

        if not actions_available(can_checkin, can_no_show):
            if checked_in:
                st.caption("This visit is with the clinical team. Lifecycle actions continue on Consultations.")
            elif status == "booked" and past:
                st.caption(
                    "The scheduled time has passed. Check-in and no-show actions are "
                    "no longer available for this visit."
                )
            return

        cols = st.columns(2, gap="small")
        with cols[0]:
            if st.button(
                "Check In",
                key=f"op_checkin_{appointment_id}",
                type="primary",
                width="stretch",
                disabled=not can_checkin,
            ):
                st.session_state[CONFIRM_KEY] = appointment_id
                st.rerun()
        with cols[1]:
            if st.button(
                "Mark No-Show",
                key=f"op_noshow_{appointment_id}",
                width="stretch",
                disabled=not can_no_show,
            ):
                run_action(service.mark_no_show, a, f"{patient} marked as no-show.")

    expandable_row(
        str(appointment_id),
        title=f"{patient} · {a.get('department_name') or 'Department not set'}",
        meta=meta,
        meta_lines=meta_lines,
        pill=status or "unknown",
        id_text=f"Appointment {appointment_id}",
        actions=actions,
    )


def actions_available(can_checkin: bool, can_no_show: bool) -> bool:
    return bool(can_checkin or can_no_show)


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
        with loading("Recording check-in"):
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
    with loading("Saving your change"):
        result = action(a.get("appointment_id"))
    if result.success:
        st.session_state[FLASH_KEY] = {"message": success_text}
        st.rerun()
    else:
        display_api_error(result)


if __name__ == "__main__":
    render()
