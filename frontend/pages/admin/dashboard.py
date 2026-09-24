"""
Admin Dashboard page (§25.4, §18.1, §19.1).

Hospital-wide KPIs and the platform snapshot.
The former bottom "Admin Actions" section has been removed.
"""
import streamlit as st

from frontend.components.navbar import page_head, section_title, breadcrumb
from frontend.utils.session import require_role, current_user
from frontend.utils.states import display_api_error
from frontend.api.analytics_services import AnalyticsService
from frontend.api.staff_admin_services import AdminUserService
from frontend.api.catalog_services import CatalogService


def _as_list(data, key: str) -> list:
    """Defensively extract a list from an API payload (list or {key: [...]})."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        items = data.get(key)
        if isinstance(items, list):
            return items
    return []


def render():
    page_head(
        "Admin Overview",
        "Hospital-wide governance — usage, users, departments and doctors.",
        noindex=True,
    )
    require_role(["admin"])
    current_user()

    breadcrumb(["Admin", "Overview"])

    analytics = AnalyticsService()

    # ---------- KPI row ----------
    section_title(
        "Hospital Performance — Last 30 Days",
        "Live operational metrics for the rolling 30-day window across every department.",
    )
    appt_res = analytics.appointments(days=30)
    if not appt_res.success:
        display_api_error(appt_res)
    else:
        summary = (appt_res.data or {}).get("summary") or {}
        payment = (appt_res.data or {}).get("payment_summary") or {}
        avg_wait = summary.get("average_wait_minutes")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Appointments (30d)", summary.get("total_appointments", 0))
        k2.metric("Completion rate", f"{summary.get('completion_rate', 0):.1f}%")
        k3.metric(
            "Avg. wait",
            f"{avg_wait} min" if avg_wait is not None else "—",
        )
        k4.metric("Revenue (INR)", f"{payment.get('total_revenue', 0):,.0f}")
        st.caption(
            "Completion rate is the share of booked appointments that were "
            "completed; average wait is measured from check-in to consultation."
        )

    st.divider()

    # ---------- Users / departments / doctors summary ----------
    section_title(
        "Platform Snapshot",
        "Registered accounts and catalog size across the hospital.",
    )
    users_res = AdminUserService().list(limit=200)
    dept_res = CatalogService().departments()
    docs_res = CatalogService().doctors()

    snapshot_failed = False
    for res, label in ((users_res, "users"), (dept_res, "departments"), (docs_res, "doctors")):
        if not res.success:
            display_api_error(res)
            snapshot_failed = True

    if not snapshot_failed:
        users = _as_list(users_res.data, "users")
        departments = _as_list(dept_res.data, "departments")
        doctors = _as_list(docs_res.data, "doctors")

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Users", len(users))
        c2.metric("Patients", sum(1 for u in users if isinstance(u, dict) and u.get("role") == "patient"))
        c3.metric("Staff", sum(1 for u in users if isinstance(u, dict) and u.get("role") == "staff"))
        c4.metric("Departments", len(departments))
        c5.metric("Doctors", len(doctors))

        st.page_link(
            "pages/admin/audit_logs.py",
            label="Audit logs",
            icon=":material/receipt_long:",
            help="Review the hospital-wide audit trail of privileged actions.",
        )

    st.divider()


if __name__ == "__main__":
    render()
