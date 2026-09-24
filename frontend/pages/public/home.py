"""
Public Home page.
"""
from __future__ import annotations

import streamlit as st

from frontend.components.navbar import page_head, section_title, empty_state
from frontend.config import HOSPITAL
from frontend.api.services import CatalogService
from frontend.utils.session import current_role


def _registry() -> dict:
    """Page registry populated by frontend/app.py for st.page_link/st.switch_page."""
    return st.session_state.get("_mc_pages", {}) or {}


def _login_target():
    """Page object (preferred) or path for the Sign In page."""
    return _registry().get("login") or "pages/public/login.py"


def _departments_target():
    return _registry().get("departments") or "pages/public/departments.py"


def _dashboard_target() -> str:
    return {
        "patient": "pages/patient/dashboard.py",
        "staff": "pages/staff/dashboard.py",
        "admin": "pages/admin/dashboard.py",
    }.get(current_role() or "", "pages/patient/dashboard.py")


def _hero() -> None:
    """Gradient hero band (text/CSS only)."""
    st.markdown(
        f"""
        <div style="
            text-align: center;
            padding: 2.75rem 2rem;
            background: linear-gradient(135deg, var(--mc-navy) 0%, var(--mc-teal) 100%);
            border-radius: var(--mc-radius);
            color: white;
            margin-bottom: 1.25rem;
        ">
            <p style="font-size: clamp(1.15rem, 2vw, 1.4rem); margin: 0 0 0.75rem 0; opacity: 0.95;">
                {HOSPITAL.tagline}
            </p>
            <p style="font-size: 1rem; opacity: 0.85; margin: 0;">
                {HOSPITAL.address}<br>
                Care desk: {HOSPITAL.phone} &nbsp;|&nbsp; Emergency: {HOSPITAL.emergency}
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _cta_row(is_guest: bool) -> None:
    """Primary actions: Sign In (guests) or dashboard (signed-in), plus Departments."""
    left, right = st.columns(2, gap="medium")
    with left:
        if is_guest:
            if st.button(
                "Sign In to your portal",
                key="home_sign_in",
                type="primary",
                width="stretch",
            ):
                st.switch_page(_login_target())
            st.caption(
                "Passwordless: enter your email and we send an 8-digit code — no password to remember."
            )
        else:
            st.page_link(
                _dashboard_target(),
                label="Open your dashboard",
                icon=":material/dashboard:",
                width="stretch",
            )
            st.caption("You're signed in. Use the navigation above to manage your care.")
    with right:
        st.page_link(
            _departments_target(),
            label="Browse Departments",
            icon=":material/local_hospital:",
            width="stretch",
        )
        st.caption("Departments, services, and specialists — open to everyone, no account needed.")


def render() -> None:
    is_guest = not st.session_state.get("mc_auth", {}).get("logged_in")

    page_head(
        f"Welcome to {HOSPITAL.short_name}",
        "Sign in to your secure portal, or explore our departments and specialists — no account needed.",
    )

    _hero()
    _cta_row(is_guest)

    if is_guest:
        st.info(
            "Sign in to see your live appointments, reminders, and payment status in one "
            "place — department and specialist information below stays open to everyone."
        )

    # Live catalog totals (public endpoints — guests included).
    catalog = CatalogService()
    dept_res = catalog.departments()
    doctor_res = catalog.doctors()
    dept_count = len(dept_res.data) if dept_res.success and dept_res.data else None
    doctor_count = len(doctor_res.data) if doctor_res.success and doctor_res.data else None

    col1, col2, col3, col4 = st.columns(4, gap="medium")
    with col1:
        st.metric("Departments", dept_count if dept_count is not None else "—")
    with col2:
        st.metric("Specialists", doctor_count if doctor_count is not None else "—")
    with col3:
        st.metric("Care desk", HOSPITAL.care_desk)
    with col4:
        st.metric("Emergency", HOSPITAL.emergency)
    if dept_count is None or doctor_count is None:
        st.caption("Live totals are temporarily unavailable — please try again shortly.")

    st.divider()

    # Features
    section_title(
        f"Why Choose {HOSPITAL.short_name}",
        "Comprehensive healthcare services with modern technology",
    )

    features = [
        (
            ":material/local_hospital:",
            "Multispecialty departments",
            "Browse clinical departments, the services they provide, and their specialists.",
        ),
        (
            ":material/stethoscope:",
            "Experienced doctors",
            "Meet our consultants and their areas of specialization.",
        ),
        (
            ":material/calendar_month:",
            "Online appointment booking",
            "Book, reschedule, or cancel appointments from your portal.",
        ),
        (
            ":material/smart_toy:",
            "AI assistant",
            "Get help with bookings, hospital information, and support requests.",
        ),
        (
            ":material/credit_card:",
            "Secure payments",
            "Pay online by UPI, card, or cash — with insurance claim support.",
        ),
        (
            ":material/monitoring:",
            "Analytics & forecasting",
            "Live operational analytics and next-day demand forecasting for staff.",
        ),
        (
            ":material/notifications:",
            "Appointment reminders",
            "Automated reminders so you don't miss your visit.",
        ),
        (
            ":material/star:",
            "Patient feedback",
            "Rate your experience and help us improve.",
        ),
    ]

    cols = st.columns(2, gap="large")
    for idx, (icon, title, desc) in enumerate(features):
        with cols[idx % 2]:
            with st.container(border=True):
                st.markdown(f"### {icon} {title}")
                st.write(desc)

    st.divider()

    # Departments overview — live data, open to guests too.
    section_title("Our Departments", "Live from the hospital directory — open to everyone")

    if dept_res.success and dept_res.data:
        dept_cols = st.columns(3, gap="medium")
        for idx, dept in enumerate(dept_res.data[:6]):
            with dept_cols[idx % 3]:
                with st.container(border=True):
                    name = dept.get("name") or "Department"
                    desc = dept.get("description") or ""
                    st.write(f"**{name}**")
                    if desc:
                        st.caption(desc[:110] + ("…" if len(desc) > 110 else ""))
        st.page_link(
            _departments_target(),
            label="View all departments",
            icon=":material/arrow_forward:",
        )
    else:
        empty_state(
            "Department listings are unavailable right now",
            "Open the Departments page to try again in a moment.",
        )

    st.divider()

    # Emergency info (plain text/CSS — no icons in HTML blocks)
    st.markdown(
        f"""
        <div style="
            background: #FEF2F2;
            border: 1px solid #FECACA;
            border-radius: 12px;
            padding: 1.5rem;
            text-align: center;
        ">
            <h3 style="color: #B91C1C; margin: 0 0 0.5rem 0;">Emergency Services</h3>
            <p style="color: #991B1B; font-size: 1.25rem; font-weight: 600; margin: 0;">
                {HOSPITAL.emergency}
            </p>
            <p style="color: #991B1B; margin: 0.5rem 0 0 0;">
                Available 24 hours a day, 7 days a week
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.caption(HOSPITAL.disclaimer)


if __name__ == "__main__":
    render()
