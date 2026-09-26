"""
Meridian Care Hospital — Streamlit frontend entrypoint.

Run with:  streamlit run frontend/app.py   (or the one-command launcher: python run_app.py)

This module wires together the public site, the role-based portals, the
custom top navigation, and the shared footer. Every screen is backed by a
real backend endpoint (FastAPI). Page-level role gating lives in
``frontend/utils/session.py::require_role``.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure the repo root is importable regardless of the working directory the
# app is launched from (this file lives at <repo>/frontend/app.py).
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import streamlit as st

from frontend.styles.theme import configure_page, inject_base_css
from frontend.utils.session import init_session_state, current_role
from frontend.components.navbar import render_navbar, render_footer

# =====================================================================
# Page configuration & global chrome
# =====================================================================
configure_page()
init_session_state()
inject_base_css()

# The footer renders once per script run at the end of app.py.
st.session_state["_mc_footer_done"] = False

# =====================================================================
# Page registry
# =====================================================================
# Icons use Material Symbols shortcodes (bundled with Streamlit) instead of
# OS emojis so navigation renders identically on Windows and Linux.
# Public
home = st.Page("pages/public/home.py", title="Home", icon=":material/home:", url_path="", default=True)
departments = st.Page("pages/public/departments.py", title="Departments", icon=":material/local_hospital:", url_path="departments")
about = st.Page("pages/public/about.py", title="About", icon=":material/info:", url_path="about")
contact = st.Page("pages/public/contact.py", title="Contact", icon=":material/call:", url_path="contact")
help_page = st.Page("pages/public/help.py", title="Help & FAQ", icon=":material/help:", url_path="help")
legal = st.Page("pages/public/legal.py", title="Privacy & Terms", icon=":material/verified_user:", url_path="legal")
login = st.Page("pages/public/login.py", title="Sign In", icon=":material/login:", url_path="signin")

# Patient portal
p_dashboard = st.Page("pages/patient/dashboard.py", title="Dashboard", icon=":material/dashboard:", url_path="dashboard")
p_appointments = st.Page("pages/patient/appointments.py", title="Appointments", icon=":material/calendar_month:", url_path="appointments")
p_assistant = st.Page("pages/patient/assistant.py", title="AI Assistant", icon=":material/support_agent:", url_path="assistant")
p_history = st.Page("pages/patient/history.py", title="History", icon=":material/history:", url_path="history")
p_payments = st.Page("pages/patient/payments.py", title="Payments", icon=":material/credit_card:", url_path="payments")
p_feedback = st.Page("pages/patient/feedback.py", title="Feedback", icon=":material/star:", url_path="feedback")
p_requests = st.Page("pages/patient/requests.py", title="Requests", icon=":material/inbox:", url_path="requests")
p_profile = st.Page("pages/patient/profile.py", title="Profile", icon=":material/person:", url_path="profile")

# Staff workspace
s_dashboard = st.Page("pages/staff/dashboard.py", title="Operations", icon=":material/monitoring:", url_path="staff")
s_appointments = st.Page("pages/staff/appointments.py", title="Appointments", icon=":material/checklist:", url_path="staff-appointments")
s_reminders = st.Page("pages/staff/reminders.py", title="Reminders", icon=":material/notifications:", url_path="reminders")
s_analytics = st.Page("pages/staff/analytics.py", title="Analytics", icon=":material/query_stats:", url_path="analytics")
s_predictions = st.Page("pages/staff/predictions.py", title="Forecasting", icon=":material/trending_up:", url_path="predictions")

# Doctor workspace
d_dashboard = st.Page("pages/doctor/dashboard.py", title="Clinic Desk", icon=":material/stethoscope:", url_path="doctor")
d_appointments = st.Page("pages/doctor/appointments.py", title="Consultations", icon=":material/clinical_notes:", url_path="doctor-appointments")

# Administration
a_dashboard = st.Page("pages/admin/dashboard.py", title="Overview", icon=":material/admin_panel_settings:", url_path="admin")
a_analytics = st.Page("pages/admin/analytics.py", title="Analytics", icon=":material/bar_chart:", url_path="admin-analytics")
a_users = st.Page("pages/admin/users.py", title="Users", icon=":material/groups:", url_path="users")
a_departments = st.Page("pages/admin/departments.py", title="Departments", icon=":material/health_and_safety:", url_path="admin-departments")
a_doctors = st.Page("pages/admin/doctors.py", title="Doctors", icon=":material/stethoscope:", url_path="doctors")
a_management = st.Page("pages/admin/management.py", title="Management", icon=":material/settings:", url_path="management")
a_audit = st.Page("pages/admin/audit_logs.py", title="Audit Logs", icon=":material/receipt_long:", url_path="audit-logs")
a_predictions = st.Page("pages/admin/predictions.py", title="Forecasting", icon=":material/trending_up:", url_path="admin-forecasts")

# System / error screens
not_found = st.Page("pages/system/not_found.py", title="Not Found", icon=":material/search:", url_path="not-found")
access_denied = st.Page("pages/system/access_denied.py", title="Access Denied", icon=":material/lock:", url_path="access-denied")
error_page = st.Page("pages/system/error_page.py", title="Error", icon=":material/error:", url_path="error")

# Registry used for st.page_link targets across pages.
st.session_state["_mc_pages"] = {
    "home": home,
    "departments": departments,
    "about": about,
    "contact": contact,
    "help": help_page,
    "legal": legal,
    "login": login,
    "patient_history": p_history,
    "patient_payments": p_payments,
    "patient_feedback": p_feedback,
    "patient_profile": p_profile,
    "patient_dashboard": p_dashboard,
    "patient_appointments": p_appointments,
    "admin_management": a_management,
    "admin_users": a_users,
    "admin_departments": a_departments,
    "admin_doctors": a_doctors,
    "admin_audit_logs": a_audit,
}

# =====================================================================
# Navigation (full registry so st.navigation stays stable across reruns;
# per-role access is enforced inside each page via require_role).
# =====================================================================
nav = st.navigation(
    {
        "Explore": [home, departments, about, contact, help_page, legal, login],
        "Patient Portal": [
            p_dashboard,
            p_appointments,
            p_assistant,
            p_history,
            p_payments,
            p_feedback,
            p_requests,
            p_profile,
        ],
        "Staff Workspace": [s_dashboard, s_appointments, s_reminders, s_analytics, s_predictions],
        "Doctor Workspace": [d_dashboard, d_appointments],
        "Administration": [a_dashboard, a_management, a_analytics, a_users, a_departments, a_doctors, a_audit, a_predictions],
        "System": [not_found, access_denied, error_page],
    },
    position="hidden",
)

# =====================================================================
# Role-based top navigation
# =====================================================================
public_nav = [home, departments, about]

role = current_role()
role_nav = []
if role == "patient":
    role_nav = [
        p_dashboard,
        p_appointments,
        p_assistant,
        p_requests,
    ]
elif role == "staff":
    # Appointments is merged into the Operations page (staff/dashboard.py),
    # which renders it as a section — one entry, no duplicate nav target.
    role_nav = [s_dashboard, s_reminders, s_analytics, s_predictions]
elif role == "doctor":
    role_nav = [d_dashboard, d_appointments]
elif role == "admin":
    role_nav = [a_dashboard, a_management, a_analytics, a_audit, a_predictions]

render_navbar(
    public_nav=public_nav,
    role_nav=role_nav,
    login_page=login,
    role=role,
    profile_page=p_profile if role == "patient" else None,
    home_page=home,
)

# =====================================================================
# Run the selected page (errors are never shown raw)
# =====================================================================
try:
    nav.run()
except Exception as exc:  # noqa: BLE001 — production UX: never leak tracebacks
    st.session_state["_last_error"] = f"{type(exc).__name__}: {exc}"
    st.switch_page("pages/system/error_page.py")

# =====================================================================
# Footer
# =====================================================================
render_footer(
    footer_pages={
        "home": home,
        "departments": departments,
        "about": about,
        "help": help_page,
        "contact": contact,
        "legal": legal,
    }
)
