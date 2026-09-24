"""
Doctor Clinic Desk (dashboard).

Profile from the doctor's own record plus today's assigned visits. Every
number comes from the doctor-scoped endpoints — no global data is shown here.
"""
from __future__ import annotations

import streamlit as st

from frontend.components.navbar import page_head, section_title, breadcrumb
from frontend.components.analytics import hospital_today, parse_timestamp
from frontend.utils.session import require_role, current_user
from frontend.utils.states import display_api_error, format_datetime, status_pill
from frontend.api.services import DoctorService

RESOLVED_STATUSES = ("completed", "cancelled", "no_show")


def render():
    page_head(
        "Clinic Desk",
        "Your profile and today's assigned patients — start the consultation from the visit card.",
        noindex=True,
    )
    require_role(["doctor"])
    current_user()

    breadcrumb(["Doctor", "Clinic Desk"])

    service = DoctorService()

    # ---------- Profile ----------
    profile_res = service.profile()
    if not profile_res.success:
        display_api_error(profile_res)
        st.stop()

    profile_data = profile_res.data or {}
    doctor = profile_data.get("doctor") or {}
    department = profile_data.get("department") or {}
    profile = profile_data.get("profile") or {}

    with st.container(border=True):
        st.write(
            f"**Dr. {profile.get('full_name') or doctor.get('full_name') or 'Doctor'}** · "
            f"{doctor.get('specialization') or 'General Medicine'} · "
            f"{department.get('name') or 'Department not set'}"
        )
        details = []
        if doctor.get("qualification"):
            details.append(str(doctor["qualification"]))
        if doctor.get("years_of_experience") is not None:
            details.append(f"{doctor['years_of_experience']} years of experience")
        details.append(f"Email {profile.get('email') or '—'}")
        st.caption(" · ".join(details))

    st.divider()

    # ---------- Today's assigned visits ----------
    section_title(
        "Today's Assigned Patients",
        "Only appointments assigned to you. Check-in stays with the front desk; "
        "start the service here when the patient is with you.",
    )

    res = service.appointments(limit=200)
    if not res.success:
        display_api_error(res)
        return

    appointments = res.data or []
    today = hospital_today()
    today_appts = [
        a for a in appointments
        if (parse_timestamp(a.get("scheduled_start")) or None) is not None
        and parse_timestamp(a.get("scheduled_start")).date() == today
    ]
    today_appts.sort(key=lambda a: str(a.get("scheduled_start") or ""))

    active_today = [a for a in today_appts if a.get("appointment_status") not in RESOLVED_STATUSES]
    waiting = [a for a in active_today if a.get("actual_checkin_time") and not a.get("actual_service_start")]
    in_service = [a for a in active_today if a.get("actual_service_start") and not a.get("actual_service_end")]
    completed = [a for a in today_appts if a.get("appointment_status") == "completed"]

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Assigned today", len(today_appts))
    k2.metric("Checked in, waiting", len(waiting))
    k3.metric("In consultation", len(in_service))
    k4.metric("Completed today", len(completed))

    st.divider()

    if not active_today:
        section_title(
            "Upcoming Assigned Visits",
            "Bookings that still need to be checked in by the front desk.",
        )
        upcoming = [
            a for a in appointments
            if a.get("appointment_status") not in RESOLVED_STATUSES
        ]
        if upcoming:
            for a in upcoming[:10]:
                render_visit_card(a)
        else:
            st.info("No upcoming visits assigned.")


def render_visit_card(a: dict) -> None:
    """Compact card for one assigned visit with an 'Open' shortcut."""
    status = a.get("appointment_status") or "unknown"
    appointment_id = a.get("appointment_id")
    patient = a.get("patient_name") or "Patient name not available"

    with st.container(border=True):
        col1, col2, col3 = st.columns([3.4, 1.6, 1])
        with col1:
            st.write(
                f"**{patient}** · {a.get('department_name') or 'Department not set'}"
            )
            details = [format_datetime(a.get("scheduled_start"))]
            if a.get("patient_email"):
                details.append(str(a.get("patient_email")))
            details.append(f"Appointment `#{str(appointment_id or '')[:8]}`")
            if a.get("reason"):
                details.append(str(a.get("reason")))
            st.caption(" · ".join(details))
        with col2:
            if a.get("actual_checkin_time"):
                st.caption(f"Checked in {format_datetime(a.get('actual_checkin_time'))}")
            elif status == "booked":
                st.caption("Waiting for front-desk check-in")
        with col3:
            status_pill(status)

        if st.button(
            "Open visit",
            key=f"doc_open_{appointment_id}",
            width="stretch",
            icon=":material/open_in_new:",
        ):
            st.session_state["doctor_visit_target"] = appointment_id
            st.switch_page("pages/doctor/appointments.py")


if __name__ == "__main__":
    render()
