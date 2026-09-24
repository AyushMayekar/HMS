"""
Analytics service.
Live analytics computed from current database state.
KPIs and charts for staff/admin dashboards.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app.config.settings import get_settings, get_supabase_admin_client
from app.services.prediction_service import (
    NO_SHOW_BOOLEAN_FEATURES,
    NO_SHOW_CATEGORICAL_FEATURES,
    NO_SHOW_NUMERIC_FEATURES,
    _load_no_show_model,
    _log_prediction,
    _prepare_dataframe,
    build_no_show_features,
    get_no_show_threshold,
)
from app.utils.logger import log_info, log_warning


def _fetch_all_rows(query_builder, page_size: int = 1000) -> list[dict[str, Any]]:
    """
    Fetch every row of an already-filtered Supabase/PostgREST query, page by
    page, returning one flat list of row dicts.

    Why this exists: PostgREST caps a single response at ``db-max-rows``
    (Supabase default: 1000). A plain ``.execute()`` therefore SILENTLY
    truncates large tables — the appointments table has 8,003 rows but
    analytics received only the first 1,000, computing every KPI/chart on
    ~12.5% of the data (with date holes). Same for payments (3,344) and
    feedback (2,609).

    - Pages with ``.range(offset, offset + page_size - 1)`` on the SAME
      builder, so every filter (and ordering) already applied is preserved.
    - Stops as soon as a page returns fewer than ``page_size`` rows (zero
      rows -> empty list, handled naturally).
    - Callers must add a deterministic ``.order(<unique column>)`` so pages
      are disjoint (PostgREST gives no ordering guarantee without one).
    """
    rows: list[dict[str, Any]] = []
    offset = 0
    pages = 0
    # Safety net only (1M rows): protects against a server that ignores
    # .range() returning full pages forever. Never reached with real data.
    max_pages = 1000
    while pages < max_pages:
        page = query_builder.range(offset, offset + page_size - 1).execute()
        batch = page.data or []
        rows.extend(batch)
        pages += 1
        if len(batch) < page_size:
            break
        offset += page_size
    else:
        log_warning("_fetch_all_rows hit page guard - .range() possibly ignored",
                    pages=pages, rows=len(rows))
    if pages > 1:
        # One summary line per paginated read - enough visibility, no noise.
        log_info("paginated fetch complete", rows=len(rows), pages=pages,
                 page_size=page_size)
    return rows


def _fetch_appointments_dataframe(
    admin_supabase,
    *,
    department_id: str | None = None,
    days: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Fetch appointments from Supabase and return as DataFrame with parsed dates.

    Uses _fetch_all_rows so the DataFrame contains the COMPLETE filtered
    result set, not just PostgREST's first 1,000 rows. Filters are unchanged.
    """
    query = (
        admin_supabase.table("appointments")
        .select("*")
        .order("appointment_id")  # unique key -> stable, disjoint pages
    )

    if department_id:
        query = query.eq("department_id", department_id)

    if days:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        query = query.gte("created_at", cutoff)
    elif start_date:
        query = query.gte("scheduled_start", start_date)
    if end_date:
        query = query.lte("scheduled_start", end_date)

    appointments = _fetch_all_rows(query)

    if not appointments:
        return pd.DataFrame()

    df = pd.DataFrame(appointments)

    # Parse datetime columns
    for col in ["scheduled_start", "booked_at", "actual_checkin_time", "actual_service_start", "actual_service_end"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # Add date column for grouping
    if "scheduled_start" in df.columns:
        df["date"] = df["scheduled_start"].dt.date

    return df


def get_appointment_analytics(
    *,
    department_id: str | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """
    Compute appointment analytics from current DB data.
    Returns KPIs, status distribution, department breakdown, and trend data.
    """
    admin_supabase = get_supabase_admin_client()

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    query = (
        admin_supabase
        .table("appointments")
        .select("*")
        .gte("created_at", cutoff)
        .order("appointment_id")  # unique key -> stable, disjoint pages
    )

    if department_id:
        query = query.eq("department_id", department_id)

    appointments = _fetch_all_rows(query)

    total = len(appointments)

    # Status distribution
    status_counts: dict[str, int] = {}
    for appt in appointments:
        status = appt.get("appointment_status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    completed = status_counts.get("completed", 0)
    no_shows = status_counts.get("no_show", 0)
    cancelled = status_counts.get("cancelled", 0)
    booked = status_counts.get("booked", 0)

    completion_rate = (completed / total * 100) if total > 0 else 0
    no_show_rate = (no_shows / total * 100) if total > 0 else 0
    cancellation_rate = (cancelled / total * 100) if total > 0 else 0

    # Department breakdown
    dept_counts: dict[str, int] = {}
    for appt in appointments:
        dept = appt.get("department_name", "Unknown")
        dept_counts[dept] = dept_counts.get(dept, 0) + 1

    # Daily trend (last N days)
    daily_trend: dict[str, int] = {}
    for appt in appointments:
        day = appt.get("created_at", "")[:10]
        daily_trend[day] = daily_trend.get(day, 0) + 1

    # Booking channel breakdown
    channel_counts: dict[str, int] = {}
    for appt in appointments:
        channel = appt.get("booking_channel", "unknown")
        channel_counts[channel] = channel_counts.get(channel, 0) + 1

    # Average wait time (from completed appointments)
    wait_times = [
        appt["actual_wait_minutes"]
        for appt in appointments
        if appt.get("actual_wait_minutes") is not None
        and appt.get("appointment_status") == "completed"
    ]
    avg_wait = sum(wait_times) / len(wait_times) if wait_times else None

    # Payment analytics (paginated: the payments table has 3,344 rows,
    # beyond the 1,000-row PostgREST response cap)
    payments_query = (
        admin_supabase.table("payments")
        .select("*")
        .gte("created_at", cutoff)
        .order("payment_id")  # unique key -> stable, disjoint pages
    )
    payments = _fetch_all_rows(payments_query)
    successful_payments = [p for p in payments if p.get("status") == "success"]
    total_revenue = sum(p.get("amount", 0) for p in successful_payments)
    # Divide by the number of SUCCESSFUL payments; the previous guard checked
    # `if payments`, which raised ZeroDivisionError whenever payments existed
    # but none had status == "success".
    avg_payment = (total_revenue / len(successful_payments)) if successful_payments else 0

    log_info("Appointment analytics computed", days=days, total_appointments=total)

    return {
        "summary": {
            "total_appointments": total,
            "completed": completed,
            "no_shows": no_shows,
            "cancelled": cancelled,
            "booked": booked,
            "completion_rate": round(completion_rate, 2),
            "no_show_rate": round(no_show_rate, 2),
            "cancellation_rate": round(cancellation_rate, 2),
            "average_wait_minutes": round(avg_wait, 2) if avg_wait is not None else None,
        },
        "status_distribution": status_counts,
        "department_breakdown": dept_counts,
        "channel_breakdown": channel_counts,
        "daily_trend": dict(sorted(daily_trend.items())),
        "payment_summary": {
            "total_revenue": round(total_revenue, 2),
            "average_payment": round(avg_payment, 2),
            "total_payments": len(payments),
        },
        "period_days": days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_no_show_risk_queue() -> dict[str, Any]:
    """
    Get upcoming appointments with no-show risk predictions.
    Returns list of high-risk appointments for staff review.
    Uses the ML model when available, falls back to rule-based scoring.
    """
    admin_supabase = get_supabase_admin_client()

    now = datetime.now(timezone.utc)
    window_end = (now + timedelta(hours=48)).isoformat()

    # Get upcoming booked appointments
    # Business scope unchanged: booked appointments scheduled in the upcoming
    # 48h window. Paginated because a wide window can exceed the 1,000-row
    # PostgREST response cap. Ordered by the unique appointment_id so pages
    # are disjoint, then re-sorted by scheduled_start to preserve the exact
    # previous ordering (the risk_score sort below is a stable sort, so tie
    # order matches the old single-page result).
    risk_query = (
        admin_supabase
        .table("appointments")
        .select("*")
        .eq("appointment_status", "booked")
        .gte("scheduled_start", now.isoformat())
        .lte("scheduled_start", window_end)
        .order("appointment_id")
    )
    appointments = _fetch_all_rows(risk_query)
    appointments.sort(key=lambda r: str(r.get("scheduled_start") or ""))

    # Try to load ML model
    model = _load_no_show_model()
    # Use the ACCESSOR — importing the `_no_show_threshold` global by value
    # captured None and silently forced a 0.5 threshold here while
    # predict_no_show used the saved 0.2, splitting the two code paths.
    threshold = get_no_show_threshold()

    # prediction_logs dedup set: the risk queue re-scores on every GET, so we
    # avoid writing duplicate log rows inside the re-scoring interval
    # (PROJECT CONTEXT §9.2 idempotency) while still returning fresh scores.
    try:
        existing_logs = (
            admin_supabase.table("prediction_logs")
            .select("entity_id, predicted_at, model_version_id, prediction_status")
            .eq("prediction_type", "no_show")
            .in_("entity_id", [a.get("appointment_id") for a in appointments])
            .execute()
        ) if appointments else None
    except Exception:
        existing_logs = None
    rescore_cutoff = now - timedelta(hours=6)
    logged_recently: set[str] = set()
    for row in (existing_logs.data if existing_logs else []) or []:
        if row.get("prediction_status") == "success":
            try:
                predicted_at = datetime.fromisoformat(str(row.get("predicted_at")).replace("Z", "+00:00"))
                if predicted_at.tzinfo is None:
                    predicted_at = predicted_at.replace(tzinfo=timezone.utc)
                if predicted_at >= rescore_cutoff:
                    logged_recently.add(str(row.get("entity_id")))
            except ValueError:
                continue

    risk_queue = []
    for appt in appointments:
        # Build features for ML model
        features = build_no_show_features(appt)
        probability = None

        if model is not None:
            try:
                feature_df = _prepare_dataframe(
                    features,
                    NO_SHOW_NUMERIC_FEATURES,
                    NO_SHOW_CATEGORICAL_FEATURES,
                    NO_SHOW_BOOLEAN_FEATURES,
                )
                probability = float(model.predict_proba(feature_df)[0, 1])
                no_show_class = int(probability >= threshold)

                risk_level = "high" if probability > 0.6 else "medium" if probability > 0.3 else "low"
                risk_score = int(probability * 100)
                risk_factors = []

                # Add human-readable risk factors based on key features
                past_rate = appt.get("past_no_show_rate", 0) or 0
                if past_rate > 0.3:
                    risk_factors.append("High past no-show rate")
                elif past_rate > 0.15:
                    risk_factors.append("Moderate past no-show rate")

                lead_time = appt.get("lead_time_hours", 0) or 0
                if lead_time > 168:
                    risk_factors.append("Long lead time (>7 days)")
                elif lead_time > 72:
                    risk_factors.append("Moderate lead time (>3 days)")

                if appt.get("is_new_patient"):
                    risk_factors.append("New patient")

                past_cancellations = appt.get("past_cancellation_count", 0) or 0
                if past_cancellations > 3:
                    risk_factors.append("Multiple past cancellations")

                # Note: reminder_sent is NOT used as a risk factor per project requirements
                # (it's an intervention, not a predictive feature)

            except Exception as exc:
                log_info(f"ML prediction failed for {appt.get('appointment_id')}, using fallback", exception_type=type(exc).__name__)
                # Fall through to rule-based
                model = None

        if model is None:
            # Fallback: rule-based scoring (without reminder_sent as a feature)
            risk_score = 0
            risk_factors = []

            past_rate = appt.get("past_no_show_rate", 0) or 0
            if past_rate > 0.3:
                risk_score += 30
                risk_factors.append("High past no-show rate")
            elif past_rate > 0.15:
                risk_score += 15
                risk_factors.append("Moderate past no-show rate")

            past_cancellations = appt.get("past_cancellation_count", 0) or 0
            if past_cancellations > 3:
                risk_score += 20
                risk_factors.append("Multiple past cancellations")

            lead_time = appt.get("lead_time_hours", 0) or 0
            if lead_time > 168:  # > 7 days
                risk_score += 15
                risk_factors.append("Long lead time (>7 days)")
            elif lead_time > 72:  # > 3 days
                risk_score += 8
                risk_factors.append("Moderate lead time (>3 days)")

            if appt.get("is_new_patient"):
                risk_score += 10
                risk_factors.append("New patient")

            # Note: reminder_sent is deliberately excluded as a risk factor
            # per project requirements (it's an intervention, not a predictive feature)

            if risk_score >= 40:
                risk_level = "high"
            elif risk_score >= 20:
                risk_level = "medium"
            else:
                risk_level = "low"

        risk_queue.append({
            "appointment_id": appt.get("appointment_id"),
            "patient_id": appt.get("patient_id"),
            "department_name": appt.get("department_name"),
            "scheduled_start": appt.get("scheduled_start"),
            "risk_level": risk_level,
            "risk_score": risk_score,
            "risk_factors": risk_factors,
            "reminder_sent": appt.get("reminder_sent", False),
            "past_no_show_rate": appt.get("past_no_show_rate", 0) or 0,
            "no_show_probability": probability if model is not None else None,
        })

        # Log this inference event to prediction_logs (ML monitoring/audit —
        # Blueprint §4.1), skipping appointments already logged successfully
        # within the re-scoring interval so dashboard polling can't flood the
        # table (§9.2 idempotency).
        appt_id = appt.get("appointment_id")
        if appt_id and appt_id not in logged_recently:
            logged_recently.add(appt_id)
            _log_prediction(admin_supabase, {
                "prediction_type": "no_show",
                "entity_type": "appointment",
                "entity_id": appt_id,
                "predicted_at": datetime.now(timezone.utc).isoformat(),
                "prediction": {
                    "no_show_probability": probability,
                    "risk_level": risk_level,
                    "risk_score": risk_score,
                    "risk_factors": risk_factors,
                },
                "confidence": probability,
                "prediction_status": "success",
                "model_version_id": (
                    get_settings().ml_no_show_model_version
                    if model is not None else "rule_based_v1"
                ),
            }, features)

    # Sort by risk score descending
    risk_queue.sort(key=lambda x: x["risk_score"], reverse=True)

    return {
        "appointments": risk_queue,
        "total": len(risk_queue),
        "high_risk_count": sum(1 for r in risk_queue if r["risk_level"] == "high"),
        "medium_risk_count": sum(1 for r in risk_queue if r["risk_level"] == "medium"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_bed_demand_analytics(
    *,
    department_id: str | None = None,
    view_by: str = "Month",
    range_index: int = 0,
) -> dict[str, Any]:
    """
    Bed demand analytics using next_day_bed_demand from appointments.
    Returns time-series data for dashboard charts (JSON, not images).
    """
    admin_supabase = get_supabase_admin_client()
    df = _fetch_appointments_dataframe(admin_supabase, department_id=department_id)

    if df.empty or "next_day_bed_demand" not in df.columns:
        return {"message": "No bed demand data available.", "data": []}

    # Filter rows with valid bed demand data
    df = df.dropna(subset=["next_day_bed_demand", "date"])
    if df.empty:
        return {"message": "No bed demand data available.", "data": []}

    # Aggregate by date.
    # next_day_bed_demand is constant PER DEPARTMENT-DAY (verified: nunique==1
    # for all 2,430 seed department-days), so summing raw rows multiplies the
    # true value by each department's row count for that date — the Param_v4
    # row-sum behavior (PARAM_V4 BUG). Take each department-day's single value
    # first, then sum across departments for the hospital total.
    daily = (df.groupby(["date", "department_name"])["next_day_bed_demand"]
             .first()
             .groupby("date")
             .sum()
             .reset_index())
    daily.columns = ["date", "bed_demand"]
    # Group keys are datetime.date objects; convert to datetime64 so
    # Series.resample() works (object-dated index raised TypeError: 500).
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values("date")

    # Apply view_by grouping
    if view_by == "Week":
        daily = daily.set_index("date")["bed_demand"].resample("W").sum().reset_index()
    elif view_by == "Month":
        daily = daily.set_index("date")["bed_demand"].resample("ME").sum().reset_index()
    elif view_by == "Year":
        daily = daily.set_index("date")["bed_demand"].resample("YE").sum().reset_index()
    # Day: no resampling needed

    daily = daily.sort_values("date").reset_index(drop=True)

    # Apply range_index (paging: 6 periods per page)
    end = len(daily) - (range_index * 6)
    start = max(0, end - 6)
    if end <= 0 or start >= len(daily):
        return {"message": "No data available for this range.", "data": []}

    selected = daily.iloc[start:end].copy()
    selected["date_str"] = selected["date"].astype(str)

    # Format labels based on view_by
    if view_by in ("Day", "Week"):
        selected["label"] = pd.to_datetime(selected["date"]).dt.strftime("%d %b")
    elif view_by == "Month":
        selected["label"] = pd.to_datetime(selected["date"]).dt.strftime("%b %Y")
    else:
        selected["label"] = pd.to_datetime(selected["date"]).dt.strftime("%Y")

    return {
        "view_by": view_by,
        "range_index": range_index,
        "data": selected[["label", "bed_demand"]].to_dict("records"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_department_bed_demand_analytics(
    *,
    department_name: str,
    view_by: str = "Month",
    range_index: int = 0,
) -> dict[str, Any]:
    """Bed demand analytics for a specific department."""
    admin_supabase = get_supabase_admin_client()
    df = _fetch_appointments_dataframe(admin_supabase)

    if df.empty or "next_day_bed_demand" not in df.columns:
        return {"message": "No bed demand data available.", "data": []}

    df = df[df["department_name"] == department_name].copy()
    df = df.dropna(subset=["next_day_bed_demand", "date"])
    if df.empty:
        return {"message": f"No bed demand data available for {department_name}.", "data": []}

    # Department view: rows are already filtered to one department, and the
    # value is constant per department-day — first() yields the true daily
    # value; sum() would inflate it by the day's row count (PARAM_V4 BUG).
    daily = df.groupby("date")["next_day_bed_demand"].first().reset_index()
    daily.columns = ["date", "bed_demand"]
    daily["date"] = pd.to_datetime(daily["date"])  # enable Series.resample
    daily = daily.sort_values("date")

    if view_by == "Week":
        daily = daily.set_index("date")["bed_demand"].resample("W").sum().reset_index()
    elif view_by == "Month":
        daily = daily.set_index("date")["bed_demand"].resample("ME").sum().reset_index()
    elif view_by == "Year":
        daily = daily.set_index("date")["bed_demand"].resample("YE").sum().reset_index()

    daily = daily.sort_values("date").reset_index(drop=True)

    end = len(daily) - (range_index * 6)
    start = max(0, end - 6)
    if end <= 0 or start >= len(daily):
        return {"message": "No data available for this range.", "data": []}

    selected = daily.iloc[start:end].copy()
    if view_by in ("Day", "Week"):
        selected["label"] = pd.to_datetime(selected["date"]).dt.strftime("%d %b")
    elif view_by == "Month":
        selected["label"] = pd.to_datetime(selected["date"]).dt.strftime("%b %Y")
    else:
        selected["label"] = pd.to_datetime(selected["date"]).dt.strftime("%Y")

    return {
        "department_name": department_name,
        "view_by": view_by,
        "range_index": range_index,
        "data": selected[["label", "bed_demand"]].to_dict("records"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_patient_flow_analytics(
    *,
    department_id: str | None = None,
    view_by: str = "Month",
    range_index: int = 0,
) -> dict[str, Any]:
    """
    Patient flow analytics using next_day_patient_flow from appointments.
    Returns time-series data for dashboard charts.
    """
    admin_supabase = get_supabase_admin_client()
    df = _fetch_appointments_dataframe(admin_supabase, department_id=department_id)

    if df.empty or "next_day_patient_flow" not in df.columns:
        return {"message": "No patient flow data available.", "data": []}

    df = df.dropna(subset=["next_day_patient_flow", "date"])
    if df.empty:
        return {"message": "No patient flow data available.", "data": []}

    # Hospital total: one value per department-day first (constant label —
    # row-wise sum inflates by row count, PARAM_V4 BUG), then sum departments.
    daily = (df.groupby(["date", "department_name"])["next_day_patient_flow"]
             .first()
             .groupby("date")
             .sum()
             .reset_index())
    daily.columns = ["date", "patient_flow"]
    daily["date"] = pd.to_datetime(daily["date"])  # enable Series.resample
    daily = daily.sort_values("date")

    if view_by == "Week":
        daily = daily.set_index("date")["patient_flow"].resample("W").sum().reset_index()
    elif view_by == "Month":
        daily = daily.set_index("date")["patient_flow"].resample("ME").sum().reset_index()
    elif view_by == "Year":
        daily = daily.set_index("date")["patient_flow"].resample("YE").sum().reset_index()

    daily = daily.sort_values("date").reset_index(drop=True)

    end = len(daily) - (range_index * 6)
    start = max(0, end - 6)
    if end <= 0 or start >= len(daily):
        return {"message": "No data available for this range.", "data": []}

    selected = daily.iloc[start:end].copy()
    if view_by in ("Day", "Week"):
        selected["label"] = pd.to_datetime(selected["date"]).dt.strftime("%d %b")
    elif view_by == "Month":
        selected["label"] = pd.to_datetime(selected["date"]).dt.strftime("%b %Y")
    else:
        selected["label"] = pd.to_datetime(selected["date"]).dt.strftime("%Y")

    return {
        "view_by": view_by,
        "range_index": range_index,
        "data": selected[["label", "patient_flow"]].to_dict("records"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_department_patient_flow_analytics(
    *,
    department_name: str,
    view_by: str = "Month",
    range_index: int = 0,
) -> dict[str, Any]:
    """Patient flow analytics for a specific department."""
    admin_supabase = get_supabase_admin_client()
    df = _fetch_appointments_dataframe(admin_supabase)

    if df.empty or "next_day_patient_flow" not in df.columns:
        return {"message": "No patient flow data available.", "data": []}

    df = df[df["department_name"] == department_name].copy()
    df = df.dropna(subset=["next_day_patient_flow", "date"])
    if df.empty:
        return {"message": f"No patient flow data available for {department_name}.", "data": []}

    # Department view: constant per department-day — first(), not sum().
    daily = df.groupby("date")["next_day_patient_flow"].first().reset_index()
    daily.columns = ["date", "patient_flow"]
    daily["date"] = pd.to_datetime(daily["date"])  # enable Series.resample
    daily = daily.sort_values("date")

    if view_by == "Week":
        daily = daily.set_index("date")["patient_flow"].resample("W").sum().reset_index()
    elif view_by == "Month":
        daily = daily.set_index("date")["patient_flow"].resample("ME").sum().reset_index()
    elif view_by == "Year":
        daily = daily.set_index("date")["patient_flow"].resample("YE").sum().reset_index()

    daily = daily.sort_values("date").reset_index(drop=True)

    end = len(daily) - (range_index * 6)
    start = max(0, end - 6)
    if end <= 0 or start >= len(daily):
        return {"message": "No data available for this range.", "data": []}

    selected = daily.iloc[start:end].copy()
    if view_by in ("Day", "Week"):
        selected["label"] = pd.to_datetime(selected["date"]).dt.strftime("%d %b")
    elif view_by == "Month":
        selected["label"] = pd.to_datetime(selected["date"]).dt.strftime("%b %Y")
    else:
        selected["label"] = pd.to_datetime(selected["date"]).dt.strftime("%Y")

    return {
        "department_name": department_name,
        "view_by": view_by,
        "range_index": range_index,
        "data": selected[["label", "patient_flow"]].to_dict("records"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_billing_analytics(
    *,
    department_id: str | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """
    Billing/payment analytics from appointments and payments tables.
    Returns JSON data for dashboard charts.
    """
    admin_supabase = get_supabase_admin_client()

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Fetch appointments with billing data (paginated: unfiltered appointments
    # exceed the 1,000-row PostgREST response cap)
    query = (
        admin_supabase.table("appointments")
        .select("*")
        .gte("created_at", cutoff)
        .order("appointment_id")  # unique key -> stable, disjoint pages
    )
    if department_id:
        query = query.eq("department_id", department_id)
    appointments = _fetch_all_rows(query)

    # Fetch payments (paginated: 3,344 rows > 1,000-row response cap)
    payments_query = (
        admin_supabase.table("payments")
        .select("*")
        .gte("created_at", cutoff)
        .order("payment_id")  # unique key -> stable, disjoint pages
    )
    payments = _fetch_all_rows(payments_query)

    if not appointments and not payments:
        return {"message": "No billing data available.", "data": {}}

    df_appt = pd.DataFrame(appointments) if appointments else pd.DataFrame()
    df_pay = pd.DataFrame(payments) if payments else pd.DataFrame()

    # 1. Outstanding receivables by payment status
    if not df_appt.empty:
        totals = df_appt.groupby("payment_status_at_booking")["invoice_amount"].sum().sort_values(ascending=False)
        receivables = [{"status": k, "total_amount": round(float(v), 2)} for k, v in totals.items()]
    else:
        receivables = []

    # 2. Pending payments by insurance/claim category
    pending_data = []
    if not df_appt.empty:
        pending = df_appt[df_appt["payment_status_at_booking"] == "pending"].copy()
        if not pending.empty:
            def label_category(row):
                if not row.get("insurance_used", False):
                    return "Self-pay"
                if row.get("claim_required", False):
                    return "Insured, claim required"
                return "Insured, no claim"
            pending["category"] = pending.apply(label_category, axis=1)
            summary = pending.groupby("category").agg(
                total_pending=("invoice_amount", "sum"),
                avg_delay_days=("billing_delay_days", "mean"),
                n_bills=("appointment_id", "count")
            ).reindex(["Self-pay", "Insured, no claim", "Insured, claim required"])
            summary = summary.dropna(subset=["total_pending"])
            pending_data = [
                {
                    "category": k,
                    "total_pending": round(float(v["total_pending"]), 2),
                    "avg_delay_days": round(float(v["avg_delay_days"]), 2) if pd.notna(v["avg_delay_days"]) else None,
                    "bill_count": int(v["n_bills"]),
                }
                for k, v in summary.iterrows()
            ]

    # 3. Average billing delay by insurance x claim
    delay_data = []
    if not df_appt.empty:
        grouped = df_appt.groupby(["insurance_used", "claim_required"])["billing_delay_days"].mean().reset_index()
        for _, row in grouped.iterrows():
            label = f"{'Insured' if row['insurance_used'] else 'Uninsured'}\n{'Claim req.' if row['claim_required'] else 'No claim'}"
            delay_data.append({
                "label": label,
                "insurance_used": bool(row["insurance_used"]),
                "claim_required": bool(row["claim_required"]),
                "avg_delay_days": round(float(row["billing_delay_days"]), 2) if pd.notna(row["billing_delay_days"]) else None,
            })

    # 4. Monthly revenue trend
    revenue_data = []
    if not df_appt.empty and "scheduled_start" in df_appt.columns:
        _ts = pd.to_datetime(df_appt["scheduled_start"])
        if getattr(_ts.dt, "tz", None) is not None:
            _ts = _ts.dt.tz_localize(None)
        df_appt["month"] = _ts.dt.to_period("M").astype(str)
        monthly = df_appt.groupby("month")["invoice_amount"].sum().sort_index()
        revenue_data = [{"month": k, "total_revenue": round(float(v), 2)} for k, v in monthly.items()]

    # 5. Billing delay distribution
    delay_dist = []
    if not df_appt.empty:
        billed = df_appt[df_appt["invoice_amount"] > 0]
        delays = billed["billing_delay_days"].dropna()
        if not delays.empty:
            hist, bins = np.histogram(delays, bins=30)
            delay_dist = [{"bin_start": round(bins[i], 2), "bin_end": round(bins[i+1], 2), "count": int(hist[i])} for i in range(len(hist))]

    return {
        "receivables_by_status": receivables,
        "pending_by_category": pending_data,
        "delay_by_insurance_claim": delay_data,
        "monthly_revenue": revenue_data,
        "delay_distribution": delay_dist,
        "period_days": days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_satisfaction_analytics(
    *,
    department_id: str | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """
    Patient satisfaction analytics from appointments feedback.
    """
    admin_supabase = get_supabase_admin_client()

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    query = (
        admin_supabase.table("appointments")
        .select("*")
        .gte("created_at", cutoff)
        .order("appointment_id")  # unique key -> stable, disjoint pages
    )
    if department_id:
        query = query.eq("department_id", department_id)
    # Paginated: the 1,000-row PostgREST response cap silently truncated the
    # dataset these formulas run on (appointments table has 8,003 rows).
    # Filters and aggregation logic are unchanged.
    appointments = _fetch_all_rows(query)

    if not appointments:
        return {"message": "No satisfaction data available.", "data": {}}

    df = pd.DataFrame(appointments)

    # Average satisfaction score
    satisfaction_scores = df["satisfaction_score"].dropna()
    avg_satisfaction = float(satisfaction_scores.mean()) if not satisfaction_scores.empty else None

    # Satisfaction by department
    dept_satisfaction = []
    if "department_name" in df.columns:
        dept_sat = df.groupby("department_name")["satisfaction_score"].mean().sort_values(ascending=False)
        dept_satisfaction = [{"department": k, "avg_score": round(float(v), 2)} for k, v in dept_sat.items() if pd.notna(v)]

    # Satisfaction vs wait time
    wait_sat = []
    if "actual_wait_minutes" in df.columns:
        wait_sat_df = df.dropna(subset=["actual_wait_minutes", "satisfaction_score"])
        if not wait_sat_df.empty:
            wait_sat = wait_sat_df[["actual_wait_minutes", "satisfaction_score"]].to_dict("records")

    # Satisfaction vs billing delay
    bill_sat = []
    if "billing_delay_days" in df.columns:
        bill_sat_df = df.dropna(subset=["billing_delay_days", "satisfaction_score"])
        if not bill_sat_df.empty:
            bill_sat = bill_sat_df[["billing_delay_days", "satisfaction_score"]].to_dict("records")

    # Distribution
    dist = []
    if not satisfaction_scores.empty:
        hist, bins = np.histogram(satisfaction_scores, bins=5, range=(1, 5))
        dist = [{"score_range": f"{bins[i]:.1f}-{bins[i+1]:.1f}", "count": int(hist[i])} for i in range(len(hist))]

    return {
        "average_satisfaction": round(avg_satisfaction, 2) if avg_satisfaction else None,
        "by_department": dept_satisfaction,
        "vs_wait_time": wait_sat[:100],  # limit for payload size
        "vs_billing_delay": bill_sat[:100],
        "distribution": dist,
        "period_days": days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_booking_channel_analytics(
    *,
    department_id: str | None = None,
    view_by: str = "Month",
    range_index: int = 0,
) -> dict[str, Any]:
    """
    Booking channel analytics (form, ai_agent, staff).
    Returns distribution and time trend data.
    """
    admin_supabase = get_supabase_admin_client()
    df = _fetch_appointments_dataframe(admin_supabase, department_id=department_id)

    if df.empty or "booking_channel" not in df.columns:
        return {"message": "No booking channel data available.", "data": {}}

    # 1. Distribution
    channel_dist = df["booking_channel"].value_counts()
    distribution = [{"channel": k, "count": int(v)} for k, v in channel_dist.items()]

    # 2. Time trend
    if "date" in df.columns:
        daily = df.groupby(["date", "booking_channel"]).size().reset_index(name="count")
        daily = daily.sort_values("date")

        if view_by == "Week":
            daily["period"] = pd.to_datetime(daily["date"]).dt.to_period("W").astype(str)
        elif view_by == "Month":
            daily["period"] = pd.to_datetime(daily["date"]).dt.to_period("M").astype(str)
        elif view_by == "Year":
            daily["period"] = pd.to_datetime(daily["date"]).dt.to_period("Y").astype(str)
        else:
            daily["period"] = daily["date"].astype(str)

        trend = daily.groupby(["period", "booking_channel"])["count"].sum().reset_index()
        trend = trend.sort_values("period")

        end = len(trend["period"].unique()) - (range_index * 6)
        start = max(0, end - 6)
        periods = sorted(trend["period"].unique())
        if end <= 0 or start >= len(periods):
            trend_data = []
        else:
            selected_periods = periods[start:end]
            trend_data = trend[trend["period"].isin(selected_periods)].to_dict("records")
    else:
        trend_data = []

    return {
        "distribution": distribution,
        "trend": trend_data,
        "view_by": view_by,
        "range_index": range_index,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_no_show_analytics(
    *,
    department_id: str | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """
    No-show analytics from historical appointments.
    Returns lead-time analysis, reminder impact, department comparison.
    """
    admin_supabase = get_supabase_admin_client()

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    query = (
        admin_supabase.table("appointments")
        .select("*")
        .gte("created_at", cutoff)
        .order("appointment_id")  # unique key -> stable, disjoint pages
    )
    if department_id:
        query = query.eq("department_id", department_id)
    # Paginated: the 1,000-row PostgREST response cap silently truncated the
    # dataset these formulas run on (appointments table has 8,003 rows).
    # Filters and aggregation logic are unchanged.
    appointments = _fetch_all_rows(query)

    if not appointments:
        return {"message": "No no-show data available.", "data": {}}

    df = pd.DataFrame(appointments)

    # Filter to completed + no_show (exclude booked/cancelled for rate calc)
    df_outcome = df[df["appointment_status"].isin(["completed", "no_show"])].copy()

    # 1. No-show rate by booking lead time (spec §21).
    # Lead time = scheduled_start - booked_at (the REAL booking-to-visit gap);
    # the stored lead_time_hours feature column is only a fallback for rows
    # without booked_at (it is often NULL on live-booking rows). The rate is
    # no_show appointments / ALL appointments in the bucket, so every bucket
    # reflects the actual data (including buckets with no no-shows and empty
    # buckets, which are reported with count 0 and an honest null rate).
    lead_time_data: list[dict[str, Any]] = []
    bucket_labels = ["<6h", "6-24h", "24-48h", "2-7d", "7+d"]
    if "scheduled_start" in df.columns:
        scheduled = pd.to_datetime(df["scheduled_start"], errors="coerce", utc=True)
        if "booked_at" in df.columns:
            booked = pd.to_datetime(df["booked_at"], errors="coerce", utc=True)
        else:
            booked = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns, UTC]")
        lead_hours = (scheduled - booked).dt.total_seconds() / 3600.0
        if "lead_time_hours" in df.columns:
            stored_lead = pd.to_numeric(df["lead_time_hours"], errors="coerce")
            lead_hours = lead_hours.where(lead_hours.notna(), stored_lead)

        if "appointment_status" in df.columns:
            is_no_show = df["appointment_status"].eq("no_show")
        elif "no_show_target" in df.columns:
            is_no_show = df["no_show_target"].fillna(False).astype(bool)
        else:
            is_no_show = pd.Series(False, index=df.index)

        bucket = pd.cut(
            lead_hours,
            bins=[-1, 6, 24, 48, 168, float("inf")],
            labels=bucket_labels,
            include_lowest=True,
        )
        analysis = pd.DataFrame({"lead_time_bucket": bucket, "no_show": is_no_show, "lead_time": lead_hours})
        analysis = analysis[analysis["lead_time_bucket"].notna()]

        for label in bucket_labels:
            group = analysis[analysis["lead_time_bucket"] == label]
            total = int(len(group))
            no_shows = int(group["no_show"].sum())
            lead_time_data.append({
                "lead_time_bucket": label,
                # null for empty buckets — no data, not a fabricated 0%.
                "no_show_rate_pct": round(no_shows / total * 100, 1) if total else None,
                "total": total,
                "no_shows": no_shows,
                "avg_lead_time_hours": round(float(group["lead_time"].mean()), 1) if total else None,
            })

    # 2. No-show rate by reminder status
    reminder_data = []
    if "reminder_sent" in df_outcome.columns and "no_show_target" in df_outcome.columns:
        df_rm = df_outcome.dropna(subset=["reminder_sent", "no_show_target"]).copy()
        if not df_rm.empty:
            df_rm["reminder_sent"] = df_rm["reminder_sent"].astype(bool)
            rm_rate = df_rm.groupby("reminder_sent")["no_show_target"].mean().mul(100).reindex([False, True])
            reminder_data = [
                {"reminder_sent": False, "no_show_rate_pct": round(float(rm_rate.get(False, 0)), 1)},
                {"reminder_sent": True, "no_show_rate_pct": round(float(rm_rate.get(True, 0)), 1)},
            ]

    # 3. No-show rate by department
    dept_data = []
    if "department_name" in df_outcome.columns and "no_show_target" in df_outcome.columns:
        df_dept = df_outcome.dropna(subset=["department_name", "no_show_target"]).copy()
        if not df_dept.empty:
            dept_rate = df_dept.groupby("department_name")["no_show_target"].mean().mul(100).sort_values(ascending=False)
            dept_data = [{"department": k, "no_show_rate_pct": round(float(v), 1)} for k, v in dept_rate.items()]

    return {
        "by_lead_time": lead_time_data,
        "by_reminder": reminder_data,
        "by_department": dept_data,
        "period_days": days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_waiting_time_analytics(
    *,
    department_id: str | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """
    Waiting time analytics from completed appointments.
    """
    admin_supabase = get_supabase_admin_client()

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    query = (
        admin_supabase.table("appointments")
        .select("*")
        .gte("created_at", cutoff)
        .order("appointment_id")  # unique key -> stable, disjoint pages
    )
    if department_id:
        query = query.eq("department_id", department_id)
    # Paginated: the 1,000-row PostgREST response cap silently truncated the
    # dataset these formulas run on (appointments table has 8,003 rows).
    # Filters and aggregation logic are unchanged.
    appointments = _fetch_all_rows(query)

    if not appointments:
        return {"message": "No waiting time data available.", "data": {}}

    df = pd.DataFrame(appointments)
    completed = df[df["appointment_status"] == "completed"].copy()

    wait_times = completed["actual_wait_minutes"].dropna()
    avg_wait = float(wait_times.mean()) if not wait_times.empty else None

    # By department
    dept_wait = []
    if "department_name" in completed.columns:
        dept = completed.groupby("department_name")["actual_wait_minutes"].mean().sort_values(ascending=False)
        dept_wait = [{"department": k, "avg_wait_minutes": round(float(v), 1)} for k, v in dept.items() if pd.notna(v)]

    # By hour
    hour_wait = []
    if "appointment_hour" in completed.columns:
        hour = completed.groupby("appointment_hour")["actual_wait_minutes"].mean().sort_index()
        hour_wait = [{"hour": int(k), "avg_wait_minutes": round(float(v), 1)} for k, v in hour.items() if pd.notna(v)]

    # Distribution
    dist = []
    if not wait_times.empty:
        hist, bins = np.histogram(wait_times, bins=20)
        dist = [{"bin_start": round(bins[i], 1), "bin_end": round(bins[i+1], 1), "count": int(hist[i])} for i in range(len(hist))]

    return {
        "average_wait_minutes": round(avg_wait, 1) if avg_wait else None,
        "by_department": dept_wait,
        "by_hour": hour_wait,
        "distribution": dist,
        "period_days": days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
