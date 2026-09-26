"""
Staff Forecasting page — automatic next-day department forecasts.

No-show scoring deliberately does NOT live here: it belongs to the single
Staff Reminders workflow (``frontend/pages/staff/reminders.py``). This page
is only about forecasting.
"""
from __future__ import annotations

from datetime import timedelta

import streamlit as st

from frontend.components.navbar import page_head, section_title, breadcrumb
from frontend.components.ui import loading
from frontend.components.analytics import hospital_now, render_forecast, render_recommendations
from frontend.utils.session import require_role, current_user
from frontend.utils.states import display_api_error
from frontend.api.analytics_services import PredictionsService


def render():
    page_head(
        "Forecasting",
        "Automatic next-day forecasts of bed demand and patient flow for every department.",
        noindex=True,
    )
    require_role(["staff"])
    current_user()

    breadcrumb(["Staff", "Forecasting"])
    (_forecasts,) = st.tabs(["Department Forecasts"])
    with _forecasts:
        render_forecast_tab()


def render_forecast_tab() -> None:
    """
    Next-day (predefined) department forecasts: bed demand and patient flow.

    Shared with the admin portal — the target date is always tomorrow in the
    hospital's local time and both forecasts load automatically when the page
    renders; no date picker or run button is involved.
    """
    service = PredictionsService()
    target = hospital_now().date() + timedelta(days=1)

    st.info(
        f"Forecasting for **{target:%A, %d %B %Y}**: tomorrow in the hospital's local time. "
        "Both forecasts below load automatically whenever this page is opened."
    )

    tab_bed, tab_flow = st.tabs(["Bed Demand", "Patient Flow"])

    # ---------- Bed demand ----------
    with tab_bed:
        section_title(
            f"Expected bed demand by department on {target:%d %b %Y}",
            "How many beds each department is expected to need tomorrow. Values are bed counts "
            "estimated from historical occupancy; read the bars as 'beds to keep available' per "
            "department. Departments without enough history are listed separately instead of "
            "being given an invented number.",
        )
        with loading("Loading the next-day bed-demand forecast..."):
            res = service.bed_demand(target_date=target.isoformat())
        _render_forecast_result(
            res,
            metric_label="Bed demand",
            y_label="Expected beds",
            how_to_read=(
                "How to read this: each bar is the forecast number of beds for one department on "
                "the forecast date; the table below repeats the exact values."
            ),
        )

    # ---------- Patient flow ----------
    with tab_flow:
        section_title(
            f"Expected patient flow by department on {target:%d %b %Y}",
            "How many patient visits each department is expected to receive tomorrow. Values are "
            "visit counts estimated from historical arrival patterns, read them as 'patients to "
            "prepare for' per department. Departments without enough history are listed separately "
            "instead of being given an invented number.",
        )
        with loading("Loading the next-day patient-flow forecast..."):
            res = service.patient_flow(target_date=target.isoformat())
        _render_forecast_result(
            res,
            metric_label="Patient flow",
            y_label="Expected patient visits",
            how_to_read=(
                "How to read this: each bar is the forecast number of patient visits for one "
                "department on the forecast date; the table below repeats the exact values."
            ),
        )

    render_recommendations("Recommendations")


def _render_forecast_result(res, *, metric_label: str, y_label: str, how_to_read: str) -> None:
    """Display a forecast response with consistent success/error handling.

    A "failed"/"fallback" status still carries real forecast rows when the ML
    artifact is missing (documented stored-7-day-average fallback), so the
    forecast is rendered with a notice instead of being hidden behind an error.
    """
    if not res.success:
        display_api_error(res)
        return

    data = res.data or {}
    status = data.get("prediction_status")
    predictions = data.get("predictions") or []

    if data.get("success") is False or (status == "failed" and not predictions):
        st.error(
            data.get("error_message")
            or data.get("error")
            or "The forecast could not be produced for this date. Please try again later."
        )
        return

    if status in ("failed", "fallback") and predictions:
        st.info(
            data.get("error_message")
            or "The forecast model is unavailable, so the stored 7-day average is "
               "shown instead (the Source column marks these rows)."
        )

    render_forecast(
        data,
        metric_label,
        y_label=y_label,
        how_to_read=how_to_read,
    )


if __name__ == "__main__":
    render()
