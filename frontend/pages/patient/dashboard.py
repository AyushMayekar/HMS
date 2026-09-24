"""
Patient Dashboard page.

Department cards, upcoming appointments (with the checked-in waiting-time
forecast), quick booking, reminders, and support requests — all backed by
live backend data.
"""
import streamlit as st
from datetime import datetime, timedelta

from frontend.components.navbar import (
    page_head,
    section_title,
    breadcrumb,
    privacy_banner,
    empty_state,
)
from frontend.components.cards import kpi_row, department_card, request_card
from frontend.components.date_picker import booking_date_picker
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
    set_flash,
    show_booking_wait_preview,
    short_id,
    slot_datetime,
    slot_scheduled_start,
    slot_time_label,
)

BOOKING_WINDOW_DAYS = 30
DEPARTMENT_CARD_LIMIT = 6
QUICK_BOOK_REASON_MAX = 500  # backend BookAppointmentRequest.reason limit


def render():
    page_head(
        "Patient Dashboard",
        "Your care overview — appointments, payments, requests, and quick booking.",
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
    # Load dashboard data
    # ------------------------------------------------------------------
    appt_service = AppointmentService()
    pay_service = PaymentService()
    req_service = AdminRequestService()
    rem_service = ReminderService()
    catalog = CatalogService()

    appointments_res = appt_service.list(limit=100)
    payments_res = pay_service.list()
    requests_res = req_service.list()
    reminders_res = rem_service.list()
    dept_res = catalog.departments()
    doctors_res = catalog.doctors()

    for response in (appointments_res, payments_res, requests_res, reminders_res, dept_res, doctors_res):
        if not response.success:
            display_api_error(response)

    appointments = appointments_res.data if appointments_res.success else []
    payments = payments_res.data if payments_res.success else []
    requests = requests_res.data if requests_res.success else []
    reminders = reminders_res.data if reminders_res.success else []
    departments = (dept_res.data or []) if (dept_res.success and dept_res.data) else []
    doctor_map = build_doctor_map(doctors_res.data if doctors_res.success else [])

    # ------------------------------------------------------------------
    # Welcome + KPIs
    # ------------------------------------------------------------------
    section_title(
        f"Welcome, {user.display_name}",
        "Review your hospital activity below, or continue to Appointments for the full booking flow.",
    )

    kpi_row([
        ("Appointments", len(appointments), None, None),
        ("Pending Payments", sum(1 for p in payments if p.get("status") == "pending"), None, None),
        ("Admin Requests", len(requests), None, None),
        ("Reminders", len(reminders), None, None),
    ])

    st.divider()

    # ------------------------------------------------------------------
    # Upcoming appointments (checked-in patients see their waiting time)
    # ------------------------------------------------------------------
    section_title(
        "Upcoming Appointments",
        "Active visits that are not completed, cancelled, or marked no-show.",
    )

    upcoming = [
        a for a in appointments
        if a.get("appointment_status") not in ("completed", "cancelled", "no_show")
    ]
    upcoming.sort(key=lambda a: a.get("scheduled_start") or "")

    if not upcoming:
        empty_state(
            "No upcoming appointments",
            "Use Quick Book below or open Appointments for the full booking flow.",
            icon="",
        )
    for appt in upcoming[:5]:
        _render_upcoming_card(appt, doctor_map)

    st.divider()

    # ------------------------------------------------------------------
    # Departments (descriptive cards + navigation to the full directory)
    # ------------------------------------------------------------------
    section_title(
        "Hospital Departments",
        "Live information about our specialties — open any card for details, or browse the full directory.",
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
        for i in range(0, len(visible), 3):
            cols = st.columns(3, gap="medium")
            for j, col in enumerate(cols):
                idx = i + j
                if idx < len(visible):
                    with col:
                        department_card(visible[idx])

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
    # Quick Book Appointment
    # ------------------------------------------------------------------
    section_title(
        "Quick Book Appointment",
        "Choose a department, available date, and open time slot. For the full booking flow, use the Appointments page.",
    )

    if not departments:
        st.info("Quick booking is unavailable because department data could not be loaded.")
    else:
        _render_quick_book(departments, doctor_map, catalog, appt_service)

    st.divider()

    # ------------------------------------------------------------------
    # Reminders
    # ------------------------------------------------------------------
    section_title("Latest Reminders")

    if not reminders:
        empty_state(
            "No appointment reminders yet.",
            "Staff may send reminders for higher no-show risk visits.",
            icon="",
        )
    else:
        for rem in reminders[:3]:
            with st.container(border=True):
                st.write("**Appointment reminder sent**")
                st.caption(f"Sent {format_datetime(rem.get('sent_at') or rem.get('created_at'))}")
                st.caption(f"Reference: {short_id(rem.get('appointment_id'))}")

    # ------------------------------------------------------------------
    # Request status
    # ------------------------------------------------------------------
    section_title("Request Status")

    if not requests:
        empty_state(
            "You have not submitted any administrative requests.",
            "Open Requests to raise billing, refund, or reschedule assistance.",
            icon="",
        )
    else:
        for req in requests[:5]:
            request_card(req, key_prefix="dash")


def _render_upcoming_card(appt: dict, doctor_map: dict) -> None:
    """One upcoming appointment: details, status, checked-in waiting time, actions."""
    with st.container(border=True):
        top = st.columns([3, 1], vertical_alignment="top")
        with top[0]:
            dept = appt.get("department_name") or "Department"
            st.write(f"**{dept}** · {doctor_display(doctor_map, appt.get('doctor_id'))}")
            st.caption(format_datetime(appt.get("scheduled_start")))
            st.caption(f"Appointment ID: {short_id(appt.get('appointment_id'))}")
        with top[1]:
            status_pill(appt.get("appointment_status") or "unknown")

        # Waiting-time placement: only while the patient is checked in and
        # the visit has not been completed / cancelled / marked no-show.
        if is_checked_in(appt):
            wait = predicted_wait_minutes(appt)
            checked_in_at = format_datetime(appt.get("actual_checkin_time"))
            if wait is not None:
                st.markdown(f"#### :material/schedule: Predicted waiting time: ~{wait} min")
                st.caption(f"Checked in at {checked_in_at}")
            else:
                st.info(
                    f"Checked in at {checked_in_at}. Your predicted waiting time "
                    "will appear here as soon as it is available."
                )

        status = appt.get("appointment_status")
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
                    "Cancel",
                    key=f"dash_cancel_{appt.get('appointment_id')}",
                    width="stretch",
                ):
                    st.session_state["cancel_target"] = appt.get("appointment_id")
                    st.switch_page("pages/patient/appointments.py")


def _render_quick_book(departments: list, doctor_map: dict, catalog: CatalogService, appt_service) -> None:
    """Department -> date -> slot -> confirm, with the backend waiting preview."""
    dept_names = [d.get("name") for d in departments if d.get("name")]
    selected_department = st.selectbox("Department", dept_names, key="patient_booking_department")
    if not selected_department:
        return

    dept = next((d for d in departments if d.get("name") == selected_department), None)
    if not dept:
        return

    slots_res = catalog.availability(department_id=dept.get("department_id"))
    if not slots_res.success:
        display_api_error(slots_res)
        return
    if not slots_res.data:
        empty_state(
            "No open time slots for this department right now.",
            "Try another department or check back later.",
            icon="",
        )
        return

    # Group real slots by date (slot_date + start_time).
    today = datetime.now().date()
    calendar_end = today + timedelta(days=BOOKING_WINDOW_DAYS)

    slots_by_date = {}
    for slot in slots_res.data:
        slot_dt = slot_datetime(slot)
        if not slot_dt:
            continue
        if today <= slot_dt.date() <= calendar_end:
            slots_by_date.setdefault(slot_dt.date(), []).append(slot)

    calendar_days = sorted(slots_by_date.keys())
    if not calendar_days:
        empty_state(
            "No bookable dates in the next 30 days.",
            "Check back soon — new slots are released regularly.",
            icon="",
        )
        return

    booking_date_picker(
        calendar_days,
        session_key="patient_booking_selected_date",
        key_prefix="dash_cal",
        label="Select Date",
        clear_keys_on_change=["patient_booking_selected_slot"],
    )

    selected_date = st.session_state.get("patient_booking_selected_date")
    if not selected_date:
        return

    st.divider()
    st.markdown(f"**Available time slots — {selected_date.strftime('%A, %d %B %Y')}**")

    day_slots = sorted(
        slots_by_date.get(selected_date, []),
        key=lambda s: str(s.get("start_time") or ""),
    )
    if not day_slots:
        st.info("No slots available on this date. Please choose another date.")
        return

    slot_cols = st.columns(min(3, len(day_slots)), gap="small")
    for idx, slot in enumerate(day_slots):
        with slot_cols[idx % len(slot_cols)]:
            slot_id = slot.get("availability_id")
            is_selected = st.session_state.get("patient_booking_selected_slot") == slot_id
            with st.container(border=True):
                st.markdown(f"**{slot_time_label(slot)}**")
                st.caption(
                    f"{doctor_display(doctor_map, slot.get('doctor_id'))} · "
                    f"{selected_date.strftime('%d %b %Y')}"
                )
                if st.button(
                    "Selected" if is_selected else "Select",
                    key=f"select_slot_{slot_id}",
                    type="primary" if is_selected else "secondary",
                    width="stretch",
                ):
                    st.session_state["patient_booking_selected_slot"] = slot_id
                    st.rerun()

    # ------------------------------------------------------------------
    # Appointment summary + confirm
    # ------------------------------------------------------------------
    selected_slot_id = st.session_state.get("patient_booking_selected_slot")
    selected_slot = next(
        (s for s in day_slots if s.get("availability_id") == selected_slot_id),
        None,
    )
    if not selected_slot:
        return

    st.divider()
    st.markdown("**Appointment Summary**")

    # Backend waiting-time forecast for the chosen slot (shown at selection).
    show_booking_wait_preview(
        selected_slot.get("doctor_id"),
        slot_scheduled_start(selected_slot),
        cache_key=str(selected_slot_id),
        availability_id=selected_slot_id,
    )

    doc_id = selected_slot.get("doctor_id")
    doctor = doctor_map.get(doc_id) or {}
    slot_dt = slot_datetime(selected_slot)

    col1, col2 = st.columns(2, gap="large")
    with col1:
        st.write(f"**Department:** {selected_department}")
        st.write(f"**Doctor:** {doctor_display(doctor_map, doc_id)}")
        if doctor.get("specialization"):
            st.write(f"**Specialization:** {doctor['specialization']}")
    with col2:
        if slot_dt:
            st.write(f"**Date:** {slot_dt.strftime('%A, %d %B %Y')}")
            st.write(f"**Time:** {slot_dt.strftime('%I:%M %p')}")
        else:
            st.write(f"**Date & Time:** {format_datetime(slot_scheduled_start(selected_slot))}")

    reason = st.text_input(
        "Visit reason (optional)",
        placeholder="Briefly describe the reason for your visit",
        key="patient_booking_reason",
        max_chars=QUICK_BOOK_REASON_MAX,
        help=f"Up to {QUICK_BOOK_REASON_MAX} characters.",
    )

    st.info(
        "Review the appointment details above. The appointment is created only "
        "after you confirm — you will receive your appointment ID afterwards."
    )

    if st.button(
        "Confirm Booking",
        type="primary",
        icon=":material/verified:",
        width="stretch",
        key="confirm_calendar_booking",
    ):
        reason_value = (reason or "").strip()
        if len(reason_value) > QUICK_BOOK_REASON_MAX:
            st.error(f"The visit reason must be at most {QUICK_BOOK_REASON_MAX} characters.")
            return

        with st.spinner("Booking your appointment..."):
            result = appt_service.book(
                doctor_id=doc_id,
                availability_id=selected_slot_id,
                reason=reason_value or None,
            )
        if result.success:
            appointment_id = (result.data or {}).get("appointment_id")
            message = "Your appointment has been booked successfully."
            if appointment_id:
                message = f"Your appointment has been booked successfully. Appointment ID: {appointment_id}"
            set_flash("dashboard", "success", message, code=appointment_id)
            st.session_state.pop("patient_booking_selected_date", None)
            st.session_state.pop("patient_booking_selected_slot", None)
            st.session_state.pop("patient_booking_reason", None)
            st.rerun()
        else:
            display_api_error(result)


if __name__ == "__main__":
    render()
