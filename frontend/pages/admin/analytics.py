"""
Admin Analytics page (§25.1).

Shares the full analytics dashboard with staff (analytics endpoints require
staff-or-admin). The staff page exposes ``render_analytics_content`` for this
purpose, so both portals render identical descriptive section titles,
explanations, chart presentation, insight captions and terminology. The only
difference is the page header/breadcrumb context.
"""
import streamlit as st

from frontend.components.navbar import page_head, breadcrumb
from frontend.utils.session import require_role, current_user

from frontend.pages.staff.analytics import render_analytics_content


def render():
    page_head(
        "Hospital Analytics",
        "Operational metrics across appointments, flow, billing, satisfaction, and "
        "ML risk — every section explains what its numbers mean.",
        noindex=True,
    )
    require_role(["admin"])
    current_user()

    breadcrumb(["Admin", "Analytics"])
    render_analytics_content()


if __name__ == "__main__":
    render()
