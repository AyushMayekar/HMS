"""
Patient Appointment History.

Rendered standalone (``render``) and as a section of the consolidated
Appointments hub (``render_content``), the same split used by Administration
› Management.
"""
from datetime import datetime

import streamlit as st

from frontend.components.navbar import page_head, section_title, breadcrumb, privacy_banner, empty_state
from frontend.components.ui import page_slice
from frontend.utils.session import require_role, current_user
from frontend.utils.states import status_pill, format_datetime, display_api_error
from frontend.api.services import AppointmentService, CatalogService
from frontend.config import APPOINTMENT_STATUSES
from frontend.pages.patient._helpers import build_doctor_map, doctor_display, short_id

PAGE_SIZE = 10  # history records per page, applied after the status filter


def render():
    page_head(
        "Appointment History",
        "A complete record of your visits, cancellations, and consultations.",
        noindex=True,
    )
    require_role(["patient"])
    current_user()

    breadcrumb(["Patient", "History"])
    privacy_banner()
    render_content()


def render_content() -> None:
    """Timeline of past visits — also used by the consolidated Appointments page."""
    service = AppointmentService()
    res = service.list(limit=200)
    if not res.success:
        display_api_error(res)
        return

    appointments = res.data or []

    doctors_res = CatalogService().doctors()
    if not doctors_res.success:
        display_api_error(doctors_res)
    doctor_map = build_doctor_map(doctors_res.data if doctors_res.success else [])

    status_filter = st.segmented_control(
        "Filter",
        ["All", "completed", "cancelled", "no_show"],
        default="All",
        key="history_status_filter",
        format_func=lambda s: "All" if s == "All" else APPOINTMENT_STATUSES.get(s, s),
    )
    if status_filter != "All":
        appointments = [a for a in appointments if a.get("appointment_status") == status_filter]

    if not appointments:
        empty_state(
            "No appointments on record.",
            "Your completed and past visits will appear here.",
            icon="",
        )
        return

    section_title(f"{len(appointments)} record(s)", "Sorted newest first")

    # Newest first, then paginate — page math always runs after filtering.
    appointments = sorted(
        appointments,
        key=lambda a: str(a.get("scheduled_start") or ""),
        reverse=True,
    )
    page_rows, _, _ = page_slice(appointments, len(appointments), PAGE_SIZE, "history_page")

    # Group the current page by year/month for a timeline feel
    buckets: dict[str, list] = {}
    for appt in page_rows:
        start = appt.get("scheduled_start") or ""
        month_key = start[:7] if start else "Unknown"
        buckets.setdefault(month_key, []).append(appt)

    for month_key, group in buckets.items():
        try:
            label = datetime.strptime(month_key, "%Y-%m").strftime("%B %Y")
        except ValueError:
            label = month_key
        st.markdown(f"#### {label}")
        for a in group:
            with st.container(border=True):
                col1, col2 = st.columns([3, 1], vertical_alignment="top")
                with col1:
                    dept = a.get("department_name") or "Department"
                    st.write(f"**{dept}** · {doctor_display(doctor_map, a.get('doctor_id'))}")
                    st.caption(format_datetime(a.get("scheduled_start")))
                    st.caption(f"Appointment ID: {short_id(a.get('appointment_id'))}")
                    reason = a.get("reason")
                    if reason:
                        st.caption(f"Reason: {reason}")
                with col2:
                    status_pill(a.get("appointment_status", "unknown"))


if __name__ == "__main__":
    render()
