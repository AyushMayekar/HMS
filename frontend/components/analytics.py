"""
Shared analytics and forecasting UI components for the staff/admin dashboards.

Wording in this module is intentionally role-neutral: both portals render the
same components. Every figure shown here comes from the backend response, and
insight captions are derived strictly from the numbers actually returned.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import pandas as pd
import streamlit as st

from frontend.config import CONFIG
from frontend.components.navbar import empty_state
from frontend.api.catalog_services import CatalogService
from frontend.utils.states import display_api_error, format_datetime

VIEW_BY_OPTIONS = ["Day", "Week", "Month", "Year"]
RANGE_PAGES = 6  # periods per page, mirrors backend paging

# ---------------------------------------------------------------------------
# Shared helpers (time, formatting, severity banding)
# ---------------------------------------------------------------------------

# Session key holding predicted waiting times returned by check-in, so the
# dashboard can show them for the visits that are still active.
PREDICTED_WAITS_KEY = "staff_predicted_waits"

RISK_BAND_LEGEND = (
    "Risk bands — High: above 60% no-show likelihood · "
    "Medium: above 30% up to 60% · Low: up to 30%."
)
RISK_SCORE_LEGEND = (
    "Risk bands (rule-based score — model unavailable for these visits) — "
    "High: 40 or more · Medium: 20–39 · Low: below 20."
)


def hospital_now() -> datetime:
    """Current datetime in the configured hospital timezone."""
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(CONFIG.hospital_timezone)
    except Exception:
        # Fixed-offset fallback: Asia/Kolkata observes no DST.
        tz = (
            timezone(timedelta(hours=5, minutes=30))
            if CONFIG.hospital_timezone == "Asia/Kolkata"
            else timezone.utc
        )
    return datetime.now(tz)


def hospital_today() -> date:
    """Today's date in the configured hospital timezone."""
    return hospital_now().date()


def parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse an ISO timestamp into an aware datetime expressed in the hospital timezone."""
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    local_tz = hospital_now().tzinfo
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=local_tz)
    return dt.astimezone(local_tz)


def is_scheduled_in_past(value: Any) -> bool:
    """True when a scheduled timestamp lies before the current hospital-local time."""
    dt = parse_timestamp(value)
    if dt is None:
        return False
    return dt < hospital_now()


def format_percent(probability: Any, decimals: int = 0) -> str:
    """Format a no-show probability (0–1) — or an already-scaled value — as '72%'."""
    if probability is None:
        return "—"
    try:
        number = float(probability)
    except (TypeError, ValueError):
        return "—"
    if number > 1.0:  # already expressed as a percentage
        return f"{number:.{decimals}f}%"
    return f"{number * 100:.{decimals}f}%"


def resolve_risk_level(item: dict) -> str:
    """Return the severity band for a risk item, deriving it from the value when needed."""
    level = str(item.get("risk_level") or "").lower()
    if level in ("high", "medium", "low"):
        return level
    probability = item.get("no_show_probability")
    if probability is not None:
        try:
            p = float(probability)
        except (TypeError, ValueError):
            return "low"
        if p > 1.0:
            p = p / 100.0
        return "high" if p > 0.6 else "medium" if p > 0.3 else "low"
    return "low"


_PILL_TONES = {
    "high": ("#FEE2E2", "#B91C1C"),
    "medium": ("#FEF3C7", "#B45309"),
    "low": ("#D1FAE5", "#047857"),
    "neutral": ("#F1F5F9", "#334155"),
}


def info_pill(text: str, tone: str = "neutral") -> str:
    """HTML pill markup for a compact status/severity label (no icons)."""
    bg, fg = _PILL_TONES.get(tone, _PILL_TONES["neutral"])
    return (
        f'<span style="background:{bg};color:{fg};padding:0.15rem 0.6rem;'
        f'border-radius:999px;font-size:0.78rem;font-weight:700;">{text}</span>'
    )


def risk_pill(level: str, label: Optional[str] = None) -> str:
    """Severity pill for a no-show risk level (high / medium / low)."""
    level = (level or "neutral").lower()
    if level not in _PILL_TONES:
        level = "neutral"
    return info_pill(label or level.upper(), tone=level)


def chart_section(title: str, explanation: str | None = None) -> None:
    """Chart subheading with a one-line explanation of what the chart shows."""
    st.subheader(title)
    if explanation:
        st.caption(explanation)


def extract_predicted_wait(payload: Any) -> Optional[float]:
    """Best-effort extraction of a predicted waiting time (minutes) from an API payload."""
    if not isinstance(payload, dict):
        return None
    for key in ("predicted_wait_minutes", "predicted_waiting_minutes", "predicted_wait", "waiting_time_minutes"):
        value = payload.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    for nested_key in ("prediction", "waiting_time", "data"):
        value = extract_predicted_wait(payload.get(nested_key))
        if value is not None:
            return value
    return None


def remember_predicted_wait(appointment_id: Any, minutes: Optional[float]) -> None:
    """Cache a predicted waiting time returned at check-in for later display."""
    if minutes is None or not appointment_id:
        return
    st.session_state.setdefault(PREDICTED_WAITS_KEY, {})[str(appointment_id)] = float(minutes)


def get_predicted_wait(appointment_id: Any) -> Optional[float]:
    """Return the waiting time cached at check-in for this appointment, if any."""
    if not appointment_id:
        return None
    return (st.session_state.get(PREDICTED_WAITS_KEY) or {}).get(str(appointment_id))


def department_selector(key_prefix: str = "an") -> tuple[str | None, str | None]:
    """
    Render a department filter control.

    Returns:
        (selected_department_name, selected_department_id) — both None for "All departments".
    """
    catalog = CatalogService()
    res = catalog.departments()
    if not res.success or not res.data:
        return None, None

    departments = res.data
    options = {"All departments": None}
    for d in departments:
        options[d.get("name")] = d.get("department_id")

    label = st.selectbox(
        "Department",
        list(options.keys()),
        key=f"{key_prefix}_dept",
    )
    dept_id = options.get(label)
    return label if label != "All departments" else None, dept_id


def view_by_range_control(
    key_prefix: str = "an",
) -> tuple[str, int]:
    """Render view-by granularity and range paging controls."""
    c1, c2, c3 = st.columns([1.4, 2.4, 1.4])
    with c1:
        view_by = st.selectbox(
            "Group by period",
            VIEW_BY_OPTIONS,
            index=2,
            key=f"{key_prefix}_view_by",
            help="How the trend is aggregated: one point per day, week, month or year.",
        )
    with c3:
        range_index = st.session_state.get(f"{key_prefix}_range_index", 0)
        cA, cB = st.columns(2)
        with cA:
            if st.button("Earlier", key=f"{key_prefix}_range_prev", disabled=range_index <= 0, width="stretch"):
                st.session_state[f"{key_prefix}_range_index"] = range_index - 1
                st.rerun()
        with cB:
            if st.button("Later", key=f"{key_prefix}_range_next", width="stretch"):
                st.session_state[f"{key_prefix}_range_index"] = range_index + 1
                st.rerun()
    st.caption("Use Earlier / Later to page through the available history.")
    return view_by, range_index


def as_frame(data) -> pd.DataFrame | None:
    """Convert list-of-dicts to a DataFrame, returning None when empty."""
    if not data:
        return None
    if not isinstance(data, (list, tuple)):
        return None
    return pd.DataFrame(data)


def render_table_or_empty(data, columns: dict, caption: str | None = None) -> None:
    """Render a DataFrame table with mapped columns, or an empty state."""
    df = as_frame(data)
    if df is None or df.empty:
        empty_state("No data for this selection.", "Try a different range or filter.", icon="")
        return
    present = [c for c in columns if c in df.columns]
    if not present:
        empty_state("No data for this selection.", "Try a different range or filter.", icon="")
        return
    df = df[present].rename(columns={c: columns[c] for c in present})
    st.dataframe(df, width="stretch", hide_index=True)
    if caption:
        st.caption(caption)


def guard_response(response, prefix: str = "") -> bool:
    """Display API error when a response failed; returns True on failure."""
    if not response.success:
        display_api_error(response)
        return True
    return False


# ---------------------------------------------------------------------------
# Appointment analytics
# ---------------------------------------------------------------------------

def render_appointment_analytics(data: dict) -> None:
    """Render appointment KPIs, status distribution, department & channel breakdowns."""
    summary = data.get("summary") or {}
    period = data.get("period_days", 30)
    total = int(summary.get("total_appointments", 0) or 0)
    completed = int(summary.get("completed", 0) or 0)
    no_shows = int(summary.get("no_shows", 0) or 0)
    cancelled = int(summary.get("cancelled", 0) or 0)
    completion_rate = float(summary.get("completion_rate", 0) or 0)
    no_show_rate = float(summary.get("no_show_rate", 0) or 0)
    cancellation_rate = float(summary.get("cancellation_rate", 0) or 0)

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric(f"Appointments booked ({period} days)", f"{total:,}")
    k2.metric("Completed visits", f"{completed:,}")
    k3.metric("No-show visits", f"{no_shows:,}")
    k4.metric(
        "No-show rate",
        f"{no_show_rate:.1f}%",
        help="Share of booked appointments that ended as a no-show.",
    )
    k5.metric(
        "Cancellation rate",
        f"{cancellation_rate:.1f}%",
        help="Share of booked appointments that were cancelled.",
    )
    st.caption(
        f"Of {total:,} appointments booked in the last {period} days, "
        f"{completed:,} ({completion_rate:.1f}%) were completed, "
        f"{no_shows:,} ({no_show_rate:.1f}%) ended as no-shows and "
        f"{cancelled:,} ({cancellation_rate:.1f}%) were cancelled."
    )

    col1, col2 = st.columns(2)
    with col1:
        chart_section(
            "How appointments ended, by status",
            f"Number of appointments currently in each status, for the last {period} days.",
        )
        dist = as_frame([{"status": k, "count": v} for k, v in (data.get("status_distribution") or {}).items()])
        if dist is not None and not dist.empty:
            st.bar_chart(
                dist, x="status", y="count",
                x_label="Appointment status",
                y_label=f"Appointments ({period} days)",
                height=300,
            )
        else:
            st.caption("No status data for this selection.")

    with col2:
        chart_section(
            "Where visits were scheduled, by department",
            f"Number of appointments booked in each department over the last {period} days.",
        )
        dept = as_frame([{"department": k, "count": v} for k, v in (data.get("department_breakdown") or {}).items()])
        if dept is not None and not dept.empty:
            st.bar_chart(
                dept, x="department", y="count",
                x_label="Department",
                y_label=f"Appointments ({period} days)",
                height=300,
            )
        else:
            st.caption("No department data for this selection.")

    col1, col2 = st.columns(2)
    with col1:
        chart_section(
            "How patients booked, by channel",
            f"Appointments created through each booking channel over the last {period} days.",
        )
        ch = as_frame([{"channel": k, "count": v} for k, v in (data.get("channel_breakdown") or {}).items()])
        if ch is not None and not ch.empty:
            st.bar_chart(
                ch, x="channel", y="count",
                x_label="Booking channel",
                y_label=f"Appointments ({period} days)",
                height=300,
            )
        else:
            st.caption("No booking-channel data for this selection.")

    with col2:
        chart_section(
            "Appointments created per day",
            "Number of new appointments booked on each day of the selected window.",
        )
        trend = as_frame([{"date": k, "count": v} for k, v in (data.get("daily_trend") or {}).items()])
        if trend is not None and not trend.empty:
            st.line_chart(
                trend, x="date", y="count",
                x_label="Date the appointment was booked",
                y_label="Appointments booked",
                height=300,
            )
        else:
            st.caption("No daily trend data for this selection.")


# ---------------------------------------------------------------------------
# No-show risk queue
# ---------------------------------------------------------------------------

def render_no_show_risk(data: dict) -> None:
    """Render the upcoming no-show risk queue (role-neutral; shared by staff/admin)."""
    appointments = data.get("appointments") or []
    k1, k2, k3 = st.columns(3)
    k1.metric("Upcoming bookings (next 48 h)", data.get("total", len(appointments)))
    k2.metric("High no-show risk", data.get("high_risk_count", 0))
    k3.metric("Medium no-show risk", data.get("medium_risk_count", 0))

    has_model_scores = any(a.get("no_show_probability") is not None for a in appointments)
    st.caption(RISK_BAND_LEGEND if has_model_scores else RISK_SCORE_LEGEND)

    if not appointments:
        empty_state(
            "No upcoming bookings in the next 48 hours.",
            "The risk queue refreshes continuously as appointments are booked.",
            icon="",
        )
        return

    for appt in appointments:
        with st.container(border=True):
            col1, col2, col3 = st.columns([3, 1.3, 1])
            with col1:
                st.write(f"**{appt.get('department_name') or 'Department not set'}**")
                st.caption(
                    f"{format_datetime(appt.get('scheduled_start'))} · "
                    f"Appointment `#{str(appt.get('appointment_id') or '')[:8]}`"
                )
                factors = appt.get("risk_factors") or []
                if factors:
                    st.caption(" · ".join(str(f) for f in factors))
                if appt.get("reminder_sent"):
                    st.caption("A reminder has already been sent for this visit.")
            with col2:
                probability = appt.get("no_show_probability")
                if probability is not None:
                    st.metric("No-show likelihood", format_percent(probability))
                else:
                    st.metric(
                        "No-show risk score",
                        f"{appt.get('risk_score', 0)}/100",
                        help="Rule-based score — the model could not score this visit.",
                    )
            with col3:
                st.markdown(risk_pill(resolve_risk_level(appt)), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Time-series (bed demand / patient flow)
# ---------------------------------------------------------------------------

def render_timeseries(
    data: dict,
    metric_label: str,
    y_label: str | None = None,
    explanation: str | None = None,
) -> None:
    """Render a labeled time-series chart from {label, <metric>} records."""
    if "message" in data:
        empty_state(data["message"], "Try a different range or granularity.", icon="")
        return

    records = data.get("data") or []
    if not records:
        empty_state("No data for this selection.", "Try a different range or granularity.", icon="")
        return

    df = pd.DataFrame(records)
    x_col = "label"
    y_col = [c for c in df.columns if c != "label"][0]
    view_by = str(data.get("view_by", "")).lower() or "selected"
    axis_y = y_label or metric_label

    chart_section(
        f"{metric_label} over time ({view_by} view)",
        explanation or f"{metric_label} recorded in each {view_by} period for the selected range.",
    )
    st.line_chart(
        df, x=x_col, y=y_col,
        x_label=f"Period (grouped by {view_by})",
        y_label=axis_y,
        height=300,
    )

    render_table_or_empty(
        records,
        columns={"label": "Period", y_col: axis_y},
    )


# ---------------------------------------------------------------------------
# Billing analytics
# ---------------------------------------------------------------------------

def render_billing_analytics(data: dict) -> None:
    if "message" in data:
        empty_state(data["message"], icon="")
        return

    period = data.get("period_days", 30)
    col1, col2 = st.columns(2)
    with col1:
        chart_section(
            "Outstanding amounts by payment status",
            f"Total invoiced amount per payment status over the last {period} days (INR).",
        )
        render_table_or_empty(
            data.get("receivables_by_status") or [],
            columns={"status": "Payment status", "total_amount": "Total invoiced (INR)"},
        )
    with col2:
        chart_section(
            "Pending payments by insurance category",
            "Unpaid bills grouped by whether the visit is self-pay or insured (and if a claim is required).",
        )
        render_table_or_empty(
            data.get("pending_by_category") or [],
            columns={
                "category": "Category",
                "total_pending": "Pending (INR)",
                "bill_count": "Bills",
            },
        )

    col1, col2 = st.columns(2)
    with col1:
        chart_section(
            "Invoiced amount per month",
            "Total value of appointments billed in each month of the selected window (INR).",
        )
        rev = as_frame(data.get("monthly_revenue") or [])
        if rev is not None and not rev.empty:
            st.line_chart(
                rev, x="month", y="total_revenue",
                x_label="Month",
                y_label="Invoiced amount (INR)",
                height=300,
            )
        else:
            st.caption("No monthly billing data for this selection.")
    with col2:
        chart_section(
            "Average billing delay by insurance/claim group",
            "Average days between the visit and billing, grouped by insurance status and claim requirement.",
        )
        render_table_or_empty(
            data.get("delay_by_insurance_claim") or [],
            columns={"label": "Insurance / claim group", "avg_delay_days": "Average delay (days)"},
        )


# ---------------------------------------------------------------------------
# Satisfaction analytics
# ---------------------------------------------------------------------------

def render_satisfaction_analytics(data: dict) -> None:
    if "message" in data:
        empty_state(data["message"], icon="")
        return

    avg = data.get("average_satisfaction")
    st.metric(
        "Average patient satisfaction",
        f"{avg}/5" if avg is not None else "—",
        help="Mean of patient feedback scores recorded for visits in the selected window (1–5 scale).",
    )

    dept = as_frame(data.get("by_department") or [])
    col1, col2 = st.columns(2)
    with col1:
        chart_section(
            "Average satisfaction by department",
            "Mean feedback score (1–5) for each department in the selected window.",
        )
        if dept is not None and not dept.empty:
            st.bar_chart(
                dept, x="department", y="avg_score",
                x_label="Department",
                y_label="Average satisfaction (1–5)",
                height=300,
            )
        else:
            st.caption("No department satisfaction data for this selection.")
    with col2:
        chart_section(
            "How scores are distributed",
            "Number of feedback responses in each score band (1–5 scale).",
        )
        render_table_or_empty(
            data.get("distribution") or [],
            columns={"score_range": "Score range (1–5)", "count": "Responses"},
        )

    col1, col2 = st.columns(2)
    with col1:
        chart_section(
            "Satisfaction versus waiting time",
            "Each dot is one visit: how long the patient waited versus the score they gave.",
        )
        wait = as_frame(data.get("vs_wait_time") or [])
        if wait is not None and not wait.empty:
            st.scatter_chart(
                wait, x="actual_wait_minutes", y="satisfaction_score",
                x_label="Actual wait after check-in (minutes)",
                y_label="Satisfaction score (1–5)",
                height=300,
            )
        else:
            st.caption("No visits have both a wait time and a satisfaction score yet.")
    with col2:
        chart_section(
            "Satisfaction versus billing delay",
            "Each dot is one visit: days until billing versus the score the patient gave.",
        )
        bill = as_frame(data.get("vs_billing_delay") or [])
        if bill is not None and not bill.empty:
            st.scatter_chart(
                bill, x="billing_delay_days", y="satisfaction_score",
                x_label="Billing delay (days)",
                y_label="Satisfaction score (1–5)",
                height=300,
            )
        else:
            st.caption("No visits have both a billing delay and a satisfaction score yet.")

    if dept is not None and len(dept) >= 2:
        top = dept.iloc[0]
        bottom = dept.iloc[-1]
        st.caption(
            f"Highest average satisfaction: {top.get('department')} ({float(top.get('avg_score', 0)):.1f}/5). "
            f"Lowest: {bottom.get('department')} ({float(bottom.get('avg_score', 0)):.1f}/5)."
        )


# ---------------------------------------------------------------------------
# Booking channel analytics
# ---------------------------------------------------------------------------

def render_booking_channel_analytics(data: dict) -> None:
    if "message" in data:
        empty_state(data["message"], icon="")
        return

    view_by = str(data.get("view_by", "")).lower() or "selected"
    col1, col2 = st.columns(2)
    with col1:
        chart_section(
            "Appointments per booking channel",
            "How patients booked their visits: one bar per channel for the selected range.",
        )
        dist = as_frame(data.get("distribution") or [])
        if dist is not None and not dist.empty:
            st.bar_chart(
                dist, x="channel", y="count",
                x_label="Booking channel",
                y_label="Appointments",
                height=300,
            )
        else:
            st.caption("No booking-channel data for this selection.")
    with col2:
        chart_section(
            f"Booking channel mix over time ({view_by} view)",
            "Appointments per channel in each period, so you can see how the mix is shifting.",
        )
        trend = as_frame(data.get("trend") or [])
        if trend is not None and not trend.empty:
            pivot = trend.pivot(index="period", columns="booking_channel", values="count").fillna(0)
            st.line_chart(
                pivot,
                x_label=f"Period (grouped by {view_by})",
                y_label="Appointments",
                height=300,
            )
        else:
            st.caption("No trend data for this selection.")


# ---------------------------------------------------------------------------
# No-show analytics
# ---------------------------------------------------------------------------

# Canonical advance-booking buckets and their display labels.
LEAD_TIME_ORDER = ["<6 h", "6–24 h", "24–48 h", "2–7 d", "7+ d"]
_LEAD_TIME_DISPLAY = {
    "<6h": "<6 h", "<6 h": "<6 h",
    "6-24h": "6–24 h", "6–24 h": "6–24 h",
    "24-48h": "24–48 h", "24–48 h": "24–48 h",
    "2-7d": "2–7 d", "2–7 d": "2–7 d",
    "7+d": "7+ d", "7+ d": "7+ d",
    # pd.cut interval strings for bins (-1, 6], (6, 24], (24, 48], (48, 168], (168, inf]
    "(-1, 6]": "<6 h", "(0, 6]": "<6 h",
    "(6, 24]": "6–24 h",
    "(24, 48]": "24–48 h",
    "(48, 168]": "2–7 d",
    "(168, inf]": "7+ d",
}


def _lead_time_records(records: list) -> list[dict]:
    """Normalize lead-time bucket rows to display labels, in advance-booking order."""
    rows = []
    for record in records or []:
        if not isinstance(record, dict):
            continue
        raw = str(record.get("lead_time_bucket", "")).strip()
        rate = record.get("no_show_rate_pct")
        if rate is None:
            continue
        rows.append({"bucket": _LEAD_TIME_DISPLAY.get(raw, raw), "rate": float(rate)})
    order = {name: index for index, name in enumerate(LEAD_TIME_ORDER)}
    rows.sort(key=lambda row: order.get(row["bucket"], len(order)))
    return rows


def _lead_time_insight(rows: list[dict]) -> str:
    """Insight sentence derived strictly from the lead-time numbers present."""
    if len(rows) < 2:
        return "No-show rates are shown for each advance-booking window; at least two windows are needed for a comparison."
    by_name = {row["bucket"]: row["rate"] for row in rows}
    same_day = by_name.get("<6 h")
    week_plus = by_name.get("7+ d")
    if same_day is not None and week_plus is not None:
        gap = week_plus - same_day
        if abs(gap) >= 3.0:
            if gap > 0:
                return (
                    f"Patients booking more than 7 days ahead no-showed at {week_plus:.1f}% "
                    f"versus {same_day:.1f}% for visits booked less than 6 hours ahead."
                )
            return (
                f"Visits booked less than 6 hours ahead no-showed at {same_day:.1f}% "
                f"versus {week_plus:.1f}% for bookings made more than 7 days ahead."
            )
    rates = [row["rate"] for row in rows]
    lowest = min(rows, key=lambda row: row["rate"])
    highest = max(rows, key=lambda row: row["rate"])
    return (
        f"No-show rates range from {lowest['rate']:.1f}% for visits booked {lowest['bucket']} ahead "
        f"to {highest['rate']:.1f}% for visits booked {highest['bucket']} ahead."
    )


def _reminder_insight(rows: list) -> str:
    """Insight sentence derived strictly from the with/without-reminder numbers present."""
    by_flag = {}
    for row in rows or []:
        if isinstance(row, dict) and row.get("no_show_rate_pct") is not None:
            by_flag[bool(row.get("reminder_sent"))] = float(row["no_show_rate_pct"])
    if True in by_flag and False in by_flag:
        with_reminder = by_flag[True]
        without = by_flag[False]
        gap = with_reminder - without
        if abs(gap) >= 3.0:
            if gap < 0:
                return (
                    f"Visits that received a reminder no-showed at {with_reminder:.1f}%, "
                    f"versus {without:.1f}% for visits without one."
                )
            return (
                f"Visits that received a reminder no-showed at {with_reminder:.1f}%, "
                f"{abs(gap):.1f} points above the {without:.1f}% for visits without one."
            )
        return (
            f"No-show rates are similar with ({with_reminder:.1f}%) and without ({without:.1f}%) a reminder."
        )
    return "Comparison of no-show rates for visits with and without a reminder sent."


def render_no_show_analytics(data: dict) -> None:
    if "message" in data:
        empty_state(data["message"], icon="")
        return

    # ---------- Lead time: how far ahead patients booked ----------
    lead_rows = _lead_time_records(data.get("by_lead_time") or [])
    chart_section(
        "No-show rate by how far in advance patients booked",
        "Each bar is the percentage of visits (completed or no-show) that ended as a no-show, "
        "grouped by the time between booking the appointment and the visit itself.",
    )
    if lead_rows:
        st.bar_chart(
            pd.DataFrame(lead_rows), x="bucket", y="rate",
            x_label="Advance booking time before the visit",
            y_label="No-show rate (%)",
            height=320,
            sort=False,
        )
        st.caption(_lead_time_insight(lead_rows))
        render_table_or_empty(
            lead_rows,
            columns={"bucket": "Advance booking time", "rate": "No-show rate (%)"},
        )
    else:
        empty_state(
            "No advance-booking (lead-time) data for this selection.",
            "Try a longer analysis window.",
            icon="",
        )

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        chart_section(
            "No-show rate: visits with a reminder versus without",
            "Percentage of visits that were no-shows, split by whether a reminder was sent beforehand.",
        )
        reminder_rows = data.get("by_reminder") or []
        display_rows = [
            {
                "reminder": "Reminder sent" if row.get("reminder_sent") else "No reminder",
                "rate": float(row.get("no_show_rate_pct", 0) or 0),
            }
            for row in reminder_rows
            if isinstance(row, dict)
        ]
        if display_rows:
            render_table_or_empty(
                display_rows,
                columns={"reminder": "Reminder", "rate": "No-show rate (%)"},
                caption=_reminder_insight(reminder_rows),
            )
        else:
            st.caption("No reminder comparison data for this selection.")

    with col2:
        chart_section(
            "No-show rate by department",
            "Departments ordered from the highest to the lowest no-show rate in the selected window.",
        )
        dept = as_frame(data.get("by_department") or [])
        if dept is not None and not dept.empty:
            st.bar_chart(
                dept, x="department", y="no_show_rate_pct",
                x_label="Department",
                y_label="No-show rate (%)",
                height=300,
            )
            if len(dept) >= 1:
                top = dept.iloc[0]
                st.caption(
                    f"{top.get('department')} had the highest no-show rate at {float(top.get('no_show_rate_pct', 0)):.1f}%."
                )
        else:
            st.caption("No department no-show data for this selection.")


# ---------------------------------------------------------------------------
# Waiting time analytics
# ---------------------------------------------------------------------------

def render_waiting_time_analytics(data: dict) -> None:
    if "message" in data:
        empty_state(data["message"], icon="")
        return

    avg = data.get("average_wait_minutes")
    st.metric(
        "Average wait after check-in",
        f"{avg} min" if avg is not None else "—",
        help="Mean time from patient check-in to service start, across completed visits.",
    )

    dept = as_frame(data.get("by_department") or [])
    hour = as_frame(data.get("by_hour") or [])

    col1, col2 = st.columns(2)
    with col1:
        chart_section(
            "How long patients waited, by department",
            "Average time from check-in to service start for completed visits in each department.",
        )
        if dept is not None and not dept.empty:
            st.bar_chart(
                dept, x="department", y="avg_wait_minutes",
                x_label="Department",
                y_label="Average wait (minutes)",
                height=300,
            )
        else:
            st.caption("No department wait data for this selection.")
    with col2:
        chart_section(
            "How long patients waited, by hour of the visit",
            "Average time from check-in to service start for visits starting in each hour of the day.",
        )
        if hour is not None and not hour.empty:
            st.bar_chart(
                hour, x="hour", y="avg_wait_minutes",
                x_label="Hour of the visit (0–23)",
                y_label="Average wait (minutes)",
                height=300,
            )
        else:
            st.caption("No hourly wait data for this selection.")

    chart_section(
        "Distribution of waiting times",
        "Number of completed visits falling into each wait-time band, from check-in to service start.",
    )
    dist = as_frame(data.get("distribution") or [])
    if dist is not None and not dist.empty:
        dist = dist.copy()
        dist["band"] = [
            f"{float(lo):g}–{float(hi):g} min"
            for lo, hi in zip(dist.get("bin_start", []), dist.get("bin_end", []))
        ]
        st.bar_chart(
            dist, x="band", y="count",
            x_label="Wait time after check-in (minutes)",
            y_label="Completed visits",
            height=320,
            sort=False,
        )
    else:
        st.caption("No wait-time distribution for this selection.")

    if hour is not None and len(hour) >= 2:
        peak = hour.loc[hour["avg_wait_minutes"].idxmax()]
        trough = hour.loc[hour["avg_wait_minutes"].idxmin()]
        st.caption(
            f"Waits were longest around {int(peak['hour']):02d}:00 "
            f"({float(peak['avg_wait_minutes']):.0f} min on average) and shortest around "
            f"{int(trough['hour']):02d}:00 ({float(trough['avg_wait_minutes']):.0f} min)."
        )


# ---------------------------------------------------------------------------
# Forecast rendering (next-day, department level)
# ---------------------------------------------------------------------------

def render_forecast(
    data: dict,
    metric_label: str,
    y_label: str | None = None,
    how_to_read: str | None = None,
) -> None:
    """Render a department-level forecast returned by the forecasting endpoints."""
    if not data:
        empty_state(
            "No forecast available for this date.",
            "The forecasting service returned no data.",
            icon="",
        )
        return

    target = data.get("target_date") or "—"
    st.caption(
        f"Forecast date: **{target}** · produced {format_datetime(data.get('predicted_at'))} · "
        f"model version {data.get('model_version_id') or '—'}"
    )
    if how_to_read:
        st.caption(how_to_read)

    predictions = data.get("predictions") or []
    insufficient = data.get("insufficient") or []
    axis_y = y_label or metric_label

    if not predictions:
        empty_state(
            "No forecast available.",
            "The model reported insufficient data for every department.",
            icon="",
        )
    else:
        df = pd.DataFrame(predictions)
        value_cols = [c for c in df.columns if c not in ("department_name", "source")]
        if not value_cols:
            empty_state(
                "No forecast available.",
                "The model returned no numeric forecast values.",
                icon="",
            )
            return
        y_col = value_cols[0]
        chart_section(
            f"Expected {metric_label.lower()} by department, for {target}",
            "One bar per department: the forecast value for the target date. "
            "Departments without enough history are listed separately below.",
        )
        st.bar_chart(
            df, x="department_name", y=y_col,
            x_label="Department",
            y_label=axis_y,
            height=340,
        )

        if len(df) >= 2:
            top = df.loc[df[y_col].idxmax()]
            bottom = df.loc[df[y_col].idxmin()]
            st.caption(
                f"Highest: {top.get('department_name')} at {float(top[y_col]):.0f} {axis_y.lower()}; "
                f"lowest: {bottom.get('department_name')} at {float(bottom[y_col]):.0f} {axis_y.lower()}."
            )

        render_table_or_empty(
            predictions,
            columns={"department_name": "Department", y_col: axis_y, "source": "Source"},
        )

    if insufficient:
        with st.expander(f"Departments with insufficient data ({len(insufficient)})"):
            st.caption(
                "These departments do not have enough historical records to produce a reliable "
                "forecast for this date — no values are shown rather than estimated ones."
            )
            for item in insufficient:
                st.write(f"**{item.get('department_name')}**")
                missing = item.get("missing") or []
                st.caption(", ".join(str(m) for m in missing) if missing else "Missing features")
