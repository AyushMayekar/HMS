"""
Admin Forecasting page (§25.2, §18).

Shares the staff forecasting experience (``render_forecast_tab``, documented
as shared with the admin portal): automatic next-day bed-demand and
patient-flow forecasts resolved in the hospital's local time — no date picker,
no forecast-trigger buttons, and descriptive explanations of what is forecast,
for which date, and what the values mean. Pre-appointment / per-appointment
prediction content and waiting-time widgets intentionally do not belong here.
"""
import streamlit as st

from frontend.components.navbar import page_head, breadcrumb
from frontend.utils.session import require_role, current_user

from frontend.pages.staff.predictions import render_forecast_tab


def render():
    page_head(
        "Forecasting",
        "Automatic next-day forecasts of bed demand and patient flow for every department.",
        noindex=True,
    )
    require_role(["admin"])
    current_user()

    breadcrumb(["Admin", "Forecasting"])
    render_forecast_tab()


if __name__ == "__main__":
    render()
