"""
Prediction service.
Handles ML model loading, feature building, and inference for:

- No-show prediction (~24h before appointment; staff-triggered batch job or
  explicit per-appointment request)
- Waiting-time prediction at check-in (queue features exist)
- Booking-time waiting-time prediction (no queue features; historical
  trailing-24h features only — valid at booking)
- Bed-demand forecast (department-level, next-day; historical/calendar features)
- Patient-flow forecast (department-level, next-day; historical/calendar features)

Feature contracts are verified against the trained artifacts themselves
(``Pipeline.feature_names_in_`` of each ``app/ml/models/*.pkl``), which are the
authoritative record of what each model expects at inference time.

Feature-availability policy (PROJECT CONTEXT lifecycle rules):
- Row-stored values are preferred: for the seeded fact table they ARE the
  training-time features (verified: constant per department-day, exact
  formula matches).
- When a row-stored value is NULL (rows created by the live booking flow do
  not persist trailing operational metrics), the value is computed from real
  database history (department-scoped trailing 24h/7d windows).
- If a required feature has no source at all, inference is refused with
  ``prediction_status="insufficient_data"``. Feature values are NEVER
  fabricated to force a prediction.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone, date as date_type
from typing import Any
from uuid import UUID, uuid4

import pandas as pd

from app.config.settings import get_supabase_admin_client, get_settings
from app.ml.inference import load_model
from app.utils.logger import log_info, log_error


# Global model caches (populated lazily; None => artifact unavailable)
_no_show_model = None
_no_show_threshold = None
_waiting_time_model = None
_booking_waiting_model = None
_bed_demand_model = None
_patient_flow_model = None

# Documented re-scoring policy for the no-show job: an appointment already
# successfully scored with the current model version within this interval is
# skipped, so repeated staff triggers of the job stay idempotent
# (PROJECT CONTEXT §9.2: no unlimited duplicate predictions).
NOSHOW_RESCORE_INTERVAL = timedelta(hours=6)

# appointment_hour fallback when a department has no scheduling history at all
# (Param_v4 patient-flow router parity: mean target-hour -> historical mean -> 12).
DEFAULT_APPOINTMENT_HOUR = 12


# ---------------------------------------------------------------------------
# Model / threshold loading (single coherent path via app.ml.inference)
# ---------------------------------------------------------------------------

def _load_no_show_model():
    """Load the no-show prediction pipeline (cached)."""
    global _no_show_model
    if _no_show_model is None:
        _no_show_model = load_model("no_show_pipeline")
        if _no_show_model is not None:
            log_info("No-show model loaded successfully")
    return _no_show_model


def get_no_show_threshold() -> float:
    """
    Load (and cache) the F1-optimized no-show decision threshold saved with the
    model (value: 0.2). Callers must use this accessor — importing the
    ``_no_show_threshold`` global by value captures ``None`` before the load
    happens (that bug made the risk queue silently use 0.5).
    """
    global _no_show_threshold
    if _no_show_threshold is None:
        saved = load_model("no_show_threshold")
        if saved is not None:
            _no_show_threshold = float(saved)
            log_info(f"No-show threshold loaded: {_no_show_threshold}")
        else:
            # Artifact unavailable: documented fallback only.
            _no_show_threshold = 0.5
            log_error("No-show threshold file not found - using 0.5 fallback")
    return _no_show_threshold


def _load_waiting_time_model():
    """Load the check-in waiting-time prediction pipeline (cached)."""
    global _waiting_time_model
    if _waiting_time_model is None:
        _waiting_time_model = load_model("checkin_waiting_model")
        if _waiting_time_model is not None:
            log_info("Check-in waiting-time model loaded successfully")
    return _waiting_time_model


def _load_booking_waiting_model():
    """Load the booking-time waiting-time prediction pipeline (cached)."""
    global _booking_waiting_model
    if _booking_waiting_model is None:
        _booking_waiting_model = load_model("booking_waiting_model")
        if _booking_waiting_model is not None:
            log_info("Booking waiting-time model loaded successfully")
    return _booking_waiting_model


def _load_bed_demand_model():
    """Load the bed-demand forecast pipeline (cached)."""
    global _bed_demand_model
    if _bed_demand_model is None:
        _bed_demand_model = load_model("bed_demand_model")
        if _bed_demand_model is not None:
            log_info("Bed-demand model loaded successfully")
    return _bed_demand_model


def _load_patient_flow_model():
    """Load the patient-flow forecast pipeline (cached)."""
    global _patient_flow_model
    if _patient_flow_model is None:
        _patient_flow_model = load_model("patient_flow_model")
        if _patient_flow_model is not None:
            log_info("Patient-flow model loaded successfully")
    return _patient_flow_model


# ---------------------------------------------------------------------------
# Feature name lists — verified against each artifact's feature_names_in_
# ---------------------------------------------------------------------------

# no_show_pipeline.pkl expects 21 input columns. reminder_sent and
# reminder_hours_before are dropped INSIDE the artifact
# (ColumnTransformer remainder="drop", verified by introspection), so they are
# intentionally not part of the feature frame: reminder state is an
# intervention decision, never a causal input (Blueprint §11.1).
NO_SHOW_NUMERIC_FEATURES = [
    "lead_time_hours",
    "appointment_hour",
    "appointment_weekday",
    "appointment_month",
    "past_appointment_count",
    "past_completed_count",
    "past_no_show_count",
    "past_cancellation_count",
    "past_no_show_rate",
    "slot_capacity",
    "slot_booked_count",
    "slot_utilization_pct",
    "past_avg_payment_delay_days",
]

NO_SHOW_CATEGORICAL_FEATURES = [
    "is_new_patient",
    "payment_required",
    "appointment_type",
    "booking_channel",
    "department_name",
    "payment_status_at_booking",
]

NO_SHOW_BOOLEAN_FEATURES = {"is_new_patient", "payment_required"}

# checkin_waiting_model.pkl — 14 features (queue features exist only at/after
# check-in, hence inference is gated on actual_checkin_time).
WAITING_TIME_NUMERIC_FEATURES = [
    "doctor_experience_years",
    "appointment_hour",
    "appointment_weekday",
    "department_scheduled_today",
    "department_active_doctors",
    "department_active_staff",
    "slot_utilization_pct",
    "queue_length_at_checkin",
    "patients_ahead_at_checkin",
    "avg_wait_last_24h",
    "avg_service_time_last_24h",
    "arrivals_last_24h",
    "completed_last_24h",
]

WAITING_TIME_CATEGORICAL_FEATURES = [
    "department_name",
]

# booking_waiting_model.pkl — 12 features = check-in set MINUS the two queue
# columns (verified by introspection): every feature is available at booking
# from the row or from historical database state, so this model is a valid
# booking/pre-check-in operational model.
BOOKING_WAITING_NUMERIC_FEATURES = [
    "doctor_experience_years",
    "appointment_hour",
    "appointment_weekday",
    "department_scheduled_today",
    "department_active_doctors",
    "department_active_staff",
    "slot_utilization_pct",
    "avg_wait_last_24h",
    "avg_service_time_last_24h",
    "arrivals_last_24h",
    "completed_last_24h",
]

BOOKING_WAITING_CATEGORICAL_FEATURES = [
    "department_name",
]

# bed_demand_model.pkl — 13 features (LinearRegression). NOTE:
# occupancy_rate is a 0-100 PERCENTAGE in training data (verified: mean 59.1,
# occupied/total*100 matches 100% of seed rows).
BED_DEMAND_NUMERIC_FEATURES = [
    "total_beds",
    "occupied_beds",
    "occupancy_rate",
    "admissions_last_24h",
    "discharges_last_24h",
    "arrivals_last_24h",
    "completed_last_24h",
    "department_scheduled_today",
    "beds_demand_last_7d_avg",
    "patient_flow_last_7d_avg",
    "appointment_weekday",
    "appointment_month",
]

BED_DEMAND_CATEGORICAL_FEATURES = [
    "department_name",
]

# patient_flow_model.pkl — 11 features (RandomForestRegressor,
# department_name first in training order).
PATIENT_FLOW_NUMERIC_FEATURES = [
    "department_scheduled_today",
    "arrivals_last_24h",
    "completed_last_24h",
    "appointment_hour",
    "appointment_weekday",
    "appointment_month",
    "patient_flow_last_7d_avg",
    "avg_wait_last_24h",
    "department_active_doctors",
    "department_active_staff",
]

PATIENT_FLOW_CATEGORICAL_FEATURES = [
    "department_name",
]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _d(value: Any, default: Any) -> Any:
    """
    None-safe default that PRESERVES legitimate falsy values.

    Replaces the previous ``x or default`` pattern which silently converted
    appointment_hour 0 (midnight) -> 12, slot_booked_count 0 -> 1 and
    slot_capacity 0 -> 1, feeding the model values different from training.
    """
    return default if value is None else value


def _num(value: Any, default: float) -> float:
    """None-safe numeric coercion that keeps 0."""
    if value is None:
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _as_uuid(value: Any) -> str | None:
    """
    Return ``value`` when it is a real UUID, else None.

    ``prediction_logs.model_version_id`` is a uuid column (verified against
    the live Supabase schema), while the application identifies versions by
    LABEL (``v1.0``, ``rule_based_v1``, ``heuristic_v1``, ``unknown``). Those
    labels made every insert fail with
    ``400 22P02 invalid input syntax for type uuid`` — the column is nullable,
    so we omit it when the value is not a UUID and keep the label inside the
    json payload (``prediction`` / ``input_snapshot``) where it is readable.
    The label is also echoed in the API response, so no information is lost.
    """
    if value is None:
        return None
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None


def _stored_model_version(row: dict[str, Any]) -> str | None:
    """
    Version label of a stored ``prediction_logs`` row.

    The uuid column cannot hold labels (``v1.0`` …), so ``_log_prediction``
    embeds the label in ``prediction.model_version``; that is what the no-show
    job's idempotency check compares against. Falls back to the uuid column
    for rows written by other paths.
    """
    raw = row.get("prediction")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = None
    if isinstance(raw, dict) and raw.get("model_version"):
        return str(raw.get("model_version"))
    value = row.get("model_version_id")
    return str(value) if value is not None else None


def _json_payload(value: Any) -> Any:
    """
    ``prediction_logs.prediction`` is a TEXT column while the application
    builds dicts. Serialize explicitly so the stored value is a JSON string
    the readers already parse (``reminder_service`` does ``json.loads`` when
    the value is a str) instead of relying on PostgREST coercion.
    """
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, default=str)
    return value


def _log_prediction(admin_supabase, result: dict[str, Any], features: dict[str, Any]) -> None:
    """
    Persist an inference event to prediction_logs (best-effort).

    The version LABEL (``v1.0`` …) is stored inside ``prediction.model_version``
    because ``model_version_id`` is a uuid column that cannot hold labels; the
    no-show job's idempotency check reads it back from there.
    """
    try:
        pred_id = result.get("prediction_id") or str(uuid4())
        result["prediction_id"] = pred_id

        prediction = result.get("prediction")
        if isinstance(prediction, dict) and "model_version" not in prediction:
            prediction = {**prediction, "model_version": result.get("model_version_id")}

        payload = {
            "prediction_id": pred_id,
            "model_version_id": _as_uuid(result.get("model_version_id")),
            "prediction_type": result.get("prediction_type", "unknown"),
            "entity_type": result.get("entity_type", "appointment"),
            "entity_id": result.get("entity_id"),
            "input_snapshot": features,
            "prediction": _json_payload(prediction),
            "confidence": result.get("confidence"),
            "prediction_status": result.get("prediction_status", "failed"),
            "predicted_at": result.get("predicted_at"),
        }
        admin_supabase.table("prediction_logs").insert(payload).execute()
    except Exception as exc:
        if not globals().get("_mc_pred_log_warned"):
            globals()["_mc_pred_log_warned"] = True
            from app.utils.logger import log_warning
            log_warning(
                "Prediction log write skipped (prediction_logs table unavailable)",
                exception_type=type(exc).__name__,
            )


def _dept_trailing_metrics(department_name: str, window_end: datetime | None = None) -> dict[str, Any]:
    """
    Compute real department-scoped trailing-24h operational metrics from
    appointment history. Used only when a row's stored snapshot value is NULL
    (rows created by the live booking flow do not persist these columns).

    Semantics mirror the training data (all these columns are per
    department-day snapshots; verified against the seed dataset):
      - arrivals_last_24h       : check-ins in [end-24h, end) (count is real
                                  even when 0)
      - completed_last_24h      : service ends in [end-24h, end)
      - avg_wait_last_24h       : mean actual_wait_minutes of those check-ins
                                  (None when no evidence)
      - avg_service_time_last_24h: mean service duration minutes of those
                                  completions (None when no evidence)
    Windows are anchored at "now" so only genuinely past events are used.
    """
    admin_supabase = get_supabase_admin_client()
    end = window_end or datetime.now(timezone.utc)
    start = end - timedelta(hours=24)

    checkin_rows = (
        admin_supabase.table("appointments")
        .select("actual_wait_minutes")
        .eq("department_name", department_name)
        .gte("actual_checkin_time", start.isoformat())
        .lt("actual_checkin_time", end.isoformat())
        .execute()
    )
    completed_rows = (
        admin_supabase.table("appointments")
        .select("actual_service_start", "actual_service_end")
        .eq("department_name", department_name)
        .gte("actual_service_end", start.isoformat())
        .lt("actual_service_end", end.isoformat())
        .execute()
    )

    checkins = checkin_rows.data or []
    completions = completed_rows.data or []

    waits = [
        float(r["actual_wait_minutes"])
        for r in checkins
        if r.get("actual_wait_minutes") is not None
    ]
    services = []
    for r in completions:
        s, e = r.get("actual_service_start"), r.get("actual_service_end")
        if s and e:
            try:
                dur = (datetime.fromisoformat(e.replace("Z", "+00:00"))
                       - datetime.fromisoformat(s.replace("Z", "+00:00"))).total_seconds() / 60.0
                if dur >= 0:
                    services.append(dur)
            except ValueError:
                continue

    return {
        "arrivals_last_24h": len(checkins),
        "completed_last_24h": len(completions),
        "avg_wait_last_24h": (round(sum(waits) / len(waits), 2) if waits else None),
        "avg_service_time_last_24h": (round(sum(services) / len(services), 2) if services else None),
    }


# Per-department-day snapshot columns persisted on the fact table (Blueprint
# §4.2 "Queue / operational state" group).
DEPT_SNAPSHOT_FIELDS = [
    "department_id",
    "total_beds",
    "occupied_beds",
    "occupancy_rate",
    "admissions_last_24h",
    "discharges_last_24h",
    "beds_demand_last_7d_avg",
    "patient_flow_last_7d_avg",
    "arrivals_last_24h",
    "completed_last_24h",
    "avg_wait_last_24h",
    "avg_service_time_last_24h",
    "department_active_doctors",
    "department_active_staff",
    "appointment_hour",
]


def _dept_latest_snapshot(department_name: str) -> dict[str, Any]:
    """
    Most recent PAST department row's stored operational snapshot.

    All snapshot columns are constant per department-day in the training data
    (verified), so the latest row with scheduled_start <= now holds the most
    recent genuinely-known values in exact training-feature form. Rows created
    by the live booking flow carry NULLs for these columns, so we scan
    backwards for the last non-null value per field. Future-dated rows are
    excluded — using them would read information that does not exist yet.
    """
    admin_supabase = get_supabase_admin_client()
    now = datetime.now(timezone.utc)
    rows = (
        admin_supabase.table("appointments")
        .select(", ".join(DEPT_SNAPSHOT_FIELDS))
        .eq("department_name", department_name)
        .lte("scheduled_start", now.isoformat())
        .order("scheduled_start", desc=True)
        .limit(300)
        .execute()
    )
    snapshot: dict[str, Any] = {f: None for f in DEPT_SNAPSHOT_FIELDS}
    for row in rows.data or []:
        for field in DEPT_SNAPSHOT_FIELDS:
            if snapshot[field] is None and row.get(field) is not None:
                snapshot[field] = row[field]
    return snapshot


def _count_dept_scheduled_on(department_name: str, target: date_type) -> int:
    """Live count of appointments for the department on the target date.

    Training semantics: department_scheduled_today == the department-day row
    count (verified: exact match on 100% of seed rows). Bookings for a future
    date are known facts, so this is available at forecast time.
    """
    admin_supabase = get_supabase_admin_client()
    res = (
        admin_supabase.table("appointments")
        .select("appointment_id", count="exact")
        .eq("department_name", department_name)
        .gte("scheduled_start", f"{target.isoformat()}T00:00:00")
        .lt("scheduled_start", f"{target.isoformat()}T23:59:59")
        .execute()
    )
    return int(res.count or 0)


def _resolve_missing(features: dict[str, Any], numeric_features: list[str]) -> list[str]:
    """Names of required numeric features that ended up with no source."""
    return [col for col in numeric_features if features.get(col) is None]


def _prepare_dataframe(
    features: dict[str, Any],
    numeric_features: list[str],
    categorical_features: list[str],
    boolean_features: set[str] | None = None,
) -> pd.DataFrame:
    """
    Build the single-row DataFrame for a pipeline.

    Pipelines select columns by NAME from DataFrames (empirically verified:
    19-col, 21-col and shuffled orders all produce identical predictions), so
    ordering here is organizational, not semantic. Values are cast to training
    dtypes: numerics -> float, booleans -> bool, categories -> str.
    """
    boolean_features = boolean_features or set()
    row: dict[str, Any] = {}
    for col in numeric_features:
        val = features.get(col)
        row[col] = float(val) if val is not None else 0.0
    for col in categorical_features:
        val = features.get(col)
        if col in boolean_features:
            row[col] = bool(val) if val is not None else False
        else:
            row[col] = str(val) if val is not None else "unknown"
    return pd.DataFrame([row])


# ---------------------------------------------------------------------------
# Feature builders
# ---------------------------------------------------------------------------

def build_no_show_features(appointment: dict[str, Any]) -> dict[str, Any]:
    """
    Build no-show prediction features from appointment data.
    Only pre-outcome information available ~24h before the appointment.

    reminder_sent is deliberately excluded (intervention, not an input —
    Blueprint §11.1); actual check-in/service/feedback fields are never used.
    """
    features = {
        "lead_time_hours": _num(appointment.get("lead_time_hours"), 0),
        "appointment_hour": _d(appointment.get("appointment_hour"), 12),
        "appointment_weekday": _d(appointment.get("appointment_weekday"), 0),
        "appointment_month": _d(appointment.get("appointment_month"), 1),
        "past_appointment_count": _num(appointment.get("past_appointment_count"), 0),
        "past_completed_count": _num(appointment.get("past_completed_count"), 0),
        "past_no_show_count": _num(appointment.get("past_no_show_count"), 0),
        "past_cancellation_count": _num(appointment.get("past_cancellation_count"), 0),
        "past_no_show_rate": _num(appointment.get("past_no_show_rate"), 0),
        "slot_capacity": _num(appointment.get("slot_capacity"), 1),
        "slot_booked_count": _num(appointment.get("slot_booked_count"), 1),
        "slot_utilization_pct": _num(appointment.get("slot_utilization_pct"), 0),
        "past_avg_payment_delay_days": _num(appointment.get("past_avg_payment_delay_days"), 0),
        "is_new_patient": _d(appointment.get("is_new_patient"), True),
        "payment_required": _d(appointment.get("payment_required"), True),
        "appointment_type": _d(appointment.get("appointment_type"), "new_visit"),
        "booking_channel": _d(appointment.get("booking_channel"), "form"),
        "department_name": _d(appointment.get("department_name"), "Unknown"),
        "payment_status_at_booking": _d(appointment.get("payment_status_at_booking"), "pending"),
    }
    return features


def _fill_trailing_features(
    appointment: dict[str, Any],
    features: dict[str, Any],
    trailing_fields: list[str],
) -> None:
    """
    Fill trailing-24h features in-place: row-stored value first (exact
    training feature for seeded rows), real DB-derived value when the row is
    NULL (live booking rows), left as None when there is no source.
    """
    needs_compute = any(appointment.get(f) is None for f in trailing_fields)
    trailing: dict[str, Any] | None = None
    if needs_compute:
        try:
            trailing = _dept_trailing_metrics(appointment.get("department_name") or "Unknown")
        except Exception as exc:
            log_error("Trailing metric computation failed", exception_type=type(exc).__name__)
            trailing = None

    for f in trailing_fields:
        row_val = appointment.get(f)
        if row_val is not None:
            features[f] = row_val
        elif trailing is not None and trailing.get(f) is not None:
            features[f] = trailing[f]
        else:
            features[f] = None  # no source — inference will be refused


def build_waiting_time_features(appointment: dict[str, Any]) -> dict[str, Any]:
    """
    Build check-in waiting-time features (14 features).
    Queue features come from the check-in operation; trailing operational
    features prefer the row snapshot and fall back to real DB history.
    """
    features: dict[str, Any] = {
        "doctor_experience_years": _d(appointment.get("doctor_experience_years"), 0),
        "appointment_hour": _d(appointment.get("appointment_hour"), 12),
        "appointment_weekday": _d(appointment.get("appointment_weekday"), 0),
        "department_scheduled_today": _d(appointment.get("department_scheduled_today"), 0),
        "department_active_doctors": _d(appointment.get("department_active_doctors"), 0),
        "department_active_staff": _d(appointment.get("department_active_staff"), 0),
        "slot_utilization_pct": _num(appointment.get("slot_utilization_pct"), 0),
        "queue_length_at_checkin": _d(appointment.get("queue_length_at_checkin"), 0),
        "patients_ahead_at_checkin": _d(appointment.get("patients_ahead_at_checkin"), 0),
        "department_name": _d(appointment.get("department_name"), "Unknown"),
    }
    _fill_trailing_features(
        appointment,
        features,
        ["avg_wait_last_24h", "avg_service_time_last_24h", "arrivals_last_24h", "completed_last_24h"],
    )
    return features


def build_booking_waiting_features(appointment: dict[str, Any]) -> dict[str, Any]:
    """
    Build booking-time waiting-time features (12 features — no queue columns).

    Everything here is available at booking: schedule/department context is
    written by the booking flow, and the trailing operational metrics are
    derived from historical database state (never from the future).
    """
    features: dict[str, Any] = {
        "doctor_experience_years": _d(appointment.get("doctor_experience_years"), 0),
        "appointment_hour": _d(appointment.get("appointment_hour"), 12),
        "appointment_weekday": _d(appointment.get("appointment_weekday"), 0),
        "department_scheduled_today": _d(appointment.get("department_scheduled_today"), 0),
        "department_active_doctors": _d(appointment.get("department_active_doctors"), 0),
        "department_active_staff": _d(appointment.get("department_active_staff"), 0),
        "slot_utilization_pct": _num(appointment.get("slot_utilization_pct"), 0),
        "department_name": _d(appointment.get("department_name"), "Unknown"),
    }
    _fill_trailing_features(
        appointment,
        features,
        ["avg_wait_last_24h", "avg_service_time_last_24h", "arrivals_last_24h", "completed_last_24h"],
    )
    return features


def build_bed_demand_features(department_name: str, target: date_type) -> tuple[dict[str, Any], list[str]]:
    """
    Build department-level bed-demand forecast features for ``target``.

    Returns (features, missing_fields). All values are historical or
    calendar-derived:
      - bed/occupancy/admissions/discharges/7d-averages: latest past
        department snapshot (stored training features); occupancy_rate is
        recomputed as a percentage (0-100) if only bed counts exist —
        Param_v4's router computed a 0-1 fraction here, a train/serve scale
        mismatch (PARAM_V4 BUG).
      - arrivals/completed: stored snapshot, else real trailing-24h DB counts.
      - department_scheduled_today: live count for the target date.
      - weekday/month: calendar facts of the target date.
    """
    snapshot = _dept_latest_snapshot(department_name)

    features: dict[str, Any] = {
        "department_name": department_name,
        "appointment_weekday": float(target.weekday()),
        "appointment_month": float(target.month),
        "department_scheduled_today": float(_count_dept_scheduled_on(department_name, target)),
    }

    # Bed/occupancy block
    total_beds = snapshot.get("total_beds")
    occupied_beds = snapshot.get("occupied_beds")
    occupancy_rate = snapshot.get("occupancy_rate")
    if occupancy_rate is None and total_beds not in (None, 0) and occupied_beds is not None:
        # Training scale is 0-100 percent (verified against seed data).
        occupancy_rate = round(float(occupied_beds) / float(total_beds) * 100.0, 2)
    features["total_beds"] = float(total_beds) if total_beds is not None else None
    features["occupied_beds"] = float(occupied_beds) if occupied_beds is not None else None
    features["occupancy_rate"] = float(occupancy_rate) if occupancy_rate is not None else None

    for field in ("admissions_last_24h", "discharges_last_24h",
                  "beds_demand_last_7d_avg", "patient_flow_last_7d_avg"):
        value = snapshot.get(field)
        features[field] = float(value) if value is not None else None

    # arrivals/completed: stored snapshot else real trailing-24h DB counts
    # a count of 0 from a successful window query is real evidence, not a
    # fabricated default — only None means "no source".
    trailing: dict[str, Any] = {}
    if snapshot.get("arrivals_last_24h") is None or snapshot.get("completed_last_24h") is None:
        try:
            trailing = _dept_trailing_metrics(department_name)
        except Exception:
            trailing = {}

    for field in ("arrivals_last_24h", "completed_last_24h"):
        stored = snapshot.get(field)
        if stored is not None:
            features[field] = float(stored)
        elif trailing.get(field) is not None:
            features[field] = float(trailing[field])
        else:
            features[field] = None

    missing = _resolve_missing(features, BED_DEMAND_NUMERIC_FEATURES)
    return features, missing


def build_patient_flow_features(department_name: str, target: date_type) -> tuple[dict[str, Any], list[str]]:
    """
    Build department-level patient-flow forecast features for ``target``.

    Returns (features, missing_fields).
      - appointment_hour: mean scheduled hour of the target-date department
        bookings (Param_v4 router parity), else department historical mean,
        else DEFAULT_APPOINTMENT_HOUR.
      - patient_flow_last_7d_avg: stored snapshot, else mean of distinct
        department-day next-day-flow labels over the trailing 7 days, else
        mean daily appointment count (real history).
      - avg_wait / doctors / staff: stored snapshot, else computed from real
        sources; no fabrication.
    """
    snapshot = _dept_latest_snapshot(department_name)
    admin_supabase = get_supabase_admin_client()
    now = datetime.now(timezone.utc)

    features: dict[str, Any] = {
        "department_name": department_name,
        "appointment_weekday": float(target.weekday()),
        "appointment_month": float(target.month),
        "department_scheduled_today": float(_count_dept_scheduled_on(department_name, target)),
    }

    # --- appointment_hour: mean hour of target-date bookings, else history ---
    target_rows = (
        admin_supabase.table("appointments")
        .select("appointment_hour")
        .eq("department_name", department_name)
        .gte("scheduled_start", f"{target.isoformat()}T00:00:00")
        .lt("scheduled_start", f"{target.isoformat()}T23:59:59")
        .limit(500)
        .execute()
    )
    hours = [float(r["appointment_hour"]) for r in (target_rows.data or [])
             if r.get("appointment_hour") is not None]
    if not hours and snapshot.get("appointment_hour") is not None:
        hours = [float(snapshot["appointment_hour"])]
    if not hours:
        hist = (
            admin_supabase.table("appointments")
            .select("appointment_hour")
            .eq("department_name", department_name)
            .lte("scheduled_start", now.isoformat())
            .order("scheduled_start", desc=True)
            .limit(300)
            .execute()
        )
        hours = [float(r["appointment_hour"]) for r in (hist.data or [])
                 if r.get("appointment_hour") is not None]
    features["appointment_hour"] = (
        round(sum(hours) / len(hours)) if hours else float(DEFAULT_APPOINTMENT_HOUR)
    )

    # --- arrivals / completed ---
    if snapshot.get("arrivals_last_24h") is not None:
        features["arrivals_last_24h"] = float(snapshot["arrivals_last_24h"])
    if snapshot.get("completed_last_24h") is not None:
        features["completed_last_24h"] = float(snapshot["completed_last_24h"])
    if features.get("arrivals_last_24h") is None or features.get("completed_last_24h") is None:
        try:
            trailing = _dept_trailing_metrics(department_name)
        except Exception:
            trailing = {}
        if features.get("arrivals_last_24h") is None and trailing.get("arrivals_last_24h") is not None:
            features["arrivals_last_24h"] = float(trailing["arrivals_last_24h"])
        if features.get("completed_last_24h") is None and trailing.get("completed_last_24h") is not None:
            features["completed_last_24h"] = float(trailing["completed_last_24h"])

    # --- patient_flow_last_7d_avg: stored, else label mean, else count mean ---
    flow7d = snapshot.get("patient_flow_last_7d_avg")
    if flow7d is not None:
        features["patient_flow_last_7d_avg"] = float(flow7d)
    else:
        week_start = (now - timedelta(days=7))
        label_rows = (
            admin_supabase.table("appointments")
            .select("scheduled_start", "next_day_patient_flow")
            .eq("department_name", department_name)
            .gte("scheduled_start", week_start.isoformat())
            .lte("scheduled_start", now.isoformat())
            .limit(2000)
            .execute()
        )
        labels_by_day: dict[str, float] = {}
        counts_by_day: dict[str, int] = {}
        for r in label_rows.data or []:
            day = (r.get("scheduled_start") or "")[:10]
            if not day:
                continue
            counts_by_day[day] = counts_by_day.get(day, 0) + 1
            if r.get("next_day_patient_flow") is not None and day not in labels_by_day:
                labels_by_day[day] = float(r["next_day_patient_flow"])
        if labels_by_day:
            features["patient_flow_last_7d_avg"] = round(
                sum(labels_by_day.values()) / len(labels_by_day), 2)
        elif counts_by_day:
            features["patient_flow_last_7d_avg"] = round(
                sum(counts_by_day.values()) / len(counts_by_day), 2)
        else:
            features["patient_flow_last_7d_avg"] = None

    # --- avg_wait_last_24h ---
    if snapshot.get("avg_wait_last_24h") is not None:
        features["avg_wait_last_24h"] = float(snapshot["avg_wait_last_24h"])
    else:
        try:
            trailing = _dept_trailing_metrics(department_name)
            features["avg_wait_last_24h"] = (
                float(trailing["avg_wait_last_24h"])
                if trailing.get("avg_wait_last_24h") is not None else None)
        except Exception:
            features["avg_wait_last_24h"] = None

    # --- active doctors / staff: stored, else computed from live catalogs ---
    if snapshot.get("department_active_doctors") is not None:
        features["department_active_doctors"] = float(snapshot["department_active_doctors"])
    if snapshot.get("department_active_staff") is not None:
        features["department_active_staff"] = float(snapshot["department_active_staff"])
    if features.get("department_active_doctors") is None or features.get("department_active_staff") is None:
        try:
            department_id = snapshot.get("department_id")
            if department_id is None:
                dept_res = (
                    admin_supabase.table("departments")
                    .select("department_id").eq("name", department_name).execute()
                )
                department_id = (dept_res.data or [{}])[0].get("department_id")
            if features.get("department_active_doctors") is None and department_id:
                doc_res = (
                    admin_supabase.table("doctors")
                    .select("doctor_id", count="exact")
                    .eq("department_id", department_id)
                    .eq("status", "active").execute()
                )
                features["department_active_doctors"] = float(doc_res.count or 0)
            if features.get("department_active_staff") is None:
                staff_res = (
                    admin_supabase.table("profiles")
                    .select("user_id", count="exact")
                    .in_("role", ["staff", "admin"])
                    .eq("status", "active").execute()
                )
                features["department_active_staff"] = float(staff_res.count or 0)
        except Exception:
            pass  # resolved to None below if still missing

    missing = _resolve_missing(features, PATIENT_FLOW_NUMERIC_FEATURES)
    return features, missing


# ---------------------------------------------------------------------------
# No-show scoring window (scheduled_start ≈ now + 24h ± tolerance) and the
# capped, explicitly user-triggered prediction batch (selection flow)
# ---------------------------------------------------------------------------

# Deliberately NOT select("*"): the appointments table carries 65 columns and
# this is the query the prediction page runs on every open.
NO_SHOW_ELIGIBLE_COLUMNS = (
    "appointment_id, patient_id, doctor_id, department_id, department_name, "
    "scheduled_start, appointment_status, appointment_type, booking_channel"
)


def _parse_iso(value: Any) -> datetime | None:
    """ISO-8601 -> aware datetime (naive values treated as UTC)."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def no_show_window(
    tolerance_minutes: int | None = None,
    *,
    now: datetime | None = None,
) -> tuple[datetime, datetime, datetime, int]:
    """
    (window_start, window_end, target_time, tolerance_minutes) for 24-hour
    no-show prediction.

    ``target_time = now + 24h`` and the window is ``target ± tolerance``
    (config ``NOSHOW_TOLERANCE_MINUTES``, default 720 minutes / 12h).
    """
    settings = get_settings()
    if tolerance_minutes is None:
        tolerance = int(settings.noshow_tolerance_minutes)
    else:
        tolerance = int(tolerance_minutes)
    tolerance = max(0, tolerance)
    current = now or datetime.now(timezone.utc)
    target = current + timedelta(hours=24)
    return target - timedelta(minutes=tolerance), target + timedelta(minutes=tolerance), target, tolerance


def _is_no_show_eligible(
    appointment: dict[str, Any],
    window_start: datetime,
    window_end: datetime,
) -> bool:
    """Pre-outcome eligibility: still 'booked' and inside the 24h window."""
    if str(appointment.get("appointment_status") or "").lower() != "booked":
        return False
    scheduled = _parse_iso(appointment.get("scheduled_start"))
    return scheduled is not None and window_start <= scheduled <= window_end


def _attach_stored_no_show_state(
    admin_supabase,
    appointments: list[dict[str, Any]],
) -> None:
    """
    Attach the LATEST successful stored no-show prediction and the current
    reminder state to each appointment — read-only, NEVER runs inference.

    This lets the Reminders table show what is already known (probability or
    rule-based risk score, risk level, predicted label, last-scored time,
    reminder state) BEFORE staff press "Predict Selected". Appointments that
    have never been scored simply report ``None`` for every prediction field
    so the UI can say "Not scored yet" instead of inventing a value.
    """
    ids = [a.get("appointment_id") for a in appointments if a.get("appointment_id")]
    if not ids:
        return

    # Latest successful stored prediction per appointment.
    stored_prediction: dict[str, dict[str, Any]] = {}
    try:
        log_res = (
            admin_supabase.table("prediction_logs")
            .select("entity_id, predicted_at, prediction")
            .eq("prediction_type", "no_show")
            .eq("prediction_status", "success")
            .in_("entity_id", ids)
            .execute()
        )
        for entry in log_res.data or []:
            appt_id = entry.get("entity_id")
            if not appt_id:
                continue
            previous = stored_prediction.get(appt_id)
            if previous is None or str(entry.get("predicted_at") or "") > str(previous.get("predicted_at") or ""):
                stored_prediction[appt_id] = entry
    except Exception:
        stored_prediction = {}

    # Latest reminder row per appointment (real reminder state).
    reminder_by_appointment: dict[str, dict[str, Any]] = {}
    try:
        rem_res = (
            admin_supabase.table("reminders")
            .select("appointment_id, reminder_type, sent_at, created_at")
            .in_("appointment_id", ids)
            .order("created_at", desc=True)
            .limit(500)
            .execute()
        )
        for rem in rem_res.data or []:
            appt_id = rem.get("appointment_id")
            if appt_id and appt_id not in reminder_by_appointment:
                reminder_by_appointment[appt_id] = rem
    except Exception:
        reminder_by_appointment = {}

    for appointment in appointments:
        appt_id = appointment.get("appointment_id")
        entry = stored_prediction.get(appt_id)

        prediction: Any = entry.get("prediction") if entry else None
        if isinstance(prediction, str):
            try:
                prediction = json.loads(prediction)
            except (TypeError, ValueError):
                prediction = None
        if not isinstance(prediction, dict):
            prediction = None

        appointment["stored_prediction"] = prediction
        if prediction is None:
            appointment["no_show_probability"] = None
            appointment["risk_level"] = None
            appointment["predicted_no_show"] = None
            appointment["last_scored_at"] = None
        else:
            # Rule-based rows carry ``risk_score`` only — ``.get`` leaves the
            # probability None rather than fabricating a percentage.
            appointment["no_show_probability"] = prediction.get("no_show_probability")
            appointment["risk_level"] = prediction.get("risk_level")
            appointment["predicted_no_show"] = prediction.get("no_show")
            appointment["last_scored_at"] = entry.get("predicted_at") if entry else None

        reminder = reminder_by_appointment.get(appt_id) or {}
        appointment["reminder_id"] = reminder.get("reminder_id")
        appointment["reminder_type"] = reminder.get("reminder_type")
        appointment["reminder_sent_at"] = reminder.get("sent_at") or reminder.get("created_at")
        appointment["reminder_sent"] = bool(reminder)


def list_no_show_eligible(
    tolerance_minutes: int | None = None,
    *,
    limit: int = 100,
) -> dict[str, Any]:
    """
    Appointments eligible for no-show prediction RIGHT NOW:
    ``appointment_status = 'booked'`` and ``scheduled_start`` inside
    ``[now + 24h - tolerance, now + 24h + tolerance]``.

    Read-only by contract: NO inference runs here, so opening the Reminders
    page costs one bounded window query, three name lookups and two small
    state lookups (stored predictions + reminders) — independent of how many
    appointments the table holds.
    """
    from app.services.staff_appointment_service import _enrich_appointments

    admin_supabase = get_supabase_admin_client()
    window_start, window_end, target, tolerance = no_show_window(tolerance_minutes)

    rows = (
        admin_supabase.table("appointments")
        .select(NO_SHOW_ELIGIBLE_COLUMNS)
        .eq("appointment_status", "booked")
        .gte("scheduled_start", window_start.isoformat())
        .lte("scheduled_start", window_end.isoformat())
        .order("scheduled_start")
        .limit(max(1, int(limit)))
        .execute()
    )
    appointments = _enrich_appointments(admin_supabase, rows.data or [])
    _attach_stored_no_show_state(admin_supabase, appointments)

    return {
        "target_time": target.isoformat(),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "tolerance_minutes": tolerance,
        "max_batch": max(1, int(get_settings().noshow_max_batch)),
        "appointments": appointments,
        "total": len(appointments),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def run_no_show_for_ids(appointment_ids: list[str]) -> dict[str, Any]:
    """
    Run the EXISTING no-show inference for an explicit, capped selection.

    Enforced here (authoritative — the frontend mirrors these rules):
      * 1 .. ``NOSHOW_MAX_BATCH`` (default 10) UNIQUE ids per action;
      * every id must exist, still be ``booked`` and still sit inside the
        24h ± tolerance window at the moment of the click.

    Nothing runs on page load; only this call performs inference.
    """
    from app.utils.exceptions import InvalidOperationError

    settings = get_settings()
    max_batch = max(1, int(settings.noshow_max_batch))

    ids = list(dict.fromkeys(
        str(a).strip() for a in (appointment_ids or []) if str(a).strip()
    ))
    if not ids:
        raise InvalidOperationError(
            "No appointments selected. Select at least one appointment to predict."
        )
    if len(ids) > max_batch:
        raise InvalidOperationError(
            f"A maximum of {max_batch} appointments can be predicted at once. "
            f"You selected {len(ids)}. Deselect {len(ids) - max_batch} "
            "appointment(s) and try again."
        )

    admin_supabase = get_supabase_admin_client()
    window_start, window_end, _target, _tolerance = no_show_window()

    selected = (
        admin_supabase.table("appointments")
        .select("appointment_id, scheduled_start, appointment_status, department_name")
        .in_("appointment_id", ids)
        .execute()
    )
    found = {r.get("appointment_id"): r for r in (selected.data or [])}

    missing = [i for i in ids if i not in found]
    if missing:
        raise InvalidOperationError(
            "Selected appointment(s) no longer exist: " + ", ".join(missing[:5])
        )

    ineligible = [i for i in ids if not _is_no_show_eligible(found[i], window_start, window_end)]
    if ineligible:
        raise InvalidOperationError(
            "These appointments are no longer eligible for 24-hour no-show "
            "prediction (they must still be 'booked' and fall inside the "
            f"{window_start.isoformat()} – {window_end.isoformat()} window). "
            f"Refresh the list. Affected: {', '.join(ineligible[:5])}"
        )

    executed: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    predicted_at = datetime.now(timezone.utc).isoformat()

    for appointment_id in ids:
        try:
            result = predict_no_show(appointment_id)
        except Exception as exc:
            log_error(f"Batch no-show prediction failed for {appointment_id}",
                      exception_type=type(exc).__name__)
            failed.append({"appointment_id": appointment_id, "error": str(exc)})
            continue

        if result.get("prediction_status") == "failed":
            failed.append({
                "appointment_id": appointment_id,
                "error": result.get("error_message") or "Prediction failed",
            })
            continue

        item = dict(found[appointment_id])
        item["prediction"] = result.get("prediction")
        item["prediction_status"] = result.get("prediction_status")
        item["model_version_id"] = result.get("model_version_id")
        item["prediction_id"] = result.get("prediction_id")
        item["predicted_at"] = result.get("predicted_at")
        executed.append(item)

    log_info(
        "No-show prediction batch completed",
        requested=len(ids),
        executed=len(executed),
        failed=len(failed),
    )

    return {
        "executed": executed,
        "failed": failed,
        "requested": len(ids),
        "max_batch": max_batch,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "predicted_at": predicted_at,
    }


# ---------------------------------------------------------------------------
# Inference — no-show
# ---------------------------------------------------------------------------

def predict_no_show(appointment_id: str) -> dict[str, Any]:
    """
    Run no-show prediction for an eligible appointment (~24h window job or
    explicit staff request). Features are strictly pre-outcome.
    """
    admin_supabase = get_supabase_admin_client()

    appt_res = admin_supabase.table("appointments").select("*").eq("appointment_id", appointment_id).execute()
    if not appt_res.data:
        return {"success": False, "error": "Appointment not found"}

    appointment = appt_res.data[0]
    features = build_no_show_features(appointment)

    model = _load_no_show_model()

    prediction_result = {
        "prediction_type": "no_show",
        "entity_type": "appointment",
        "entity_id": appointment_id,
        "input_snapshot": features,
        "predicted_at": datetime.now(timezone.utc).isoformat(),
    }

    if model is not None:
        try:
            feature_df = _prepare_dataframe(
                features,
                NO_SHOW_NUMERIC_FEATURES,
                NO_SHOW_CATEGORICAL_FEATURES,
                NO_SHOW_BOOLEAN_FEATURES,
            )

            probability = float(model.predict_proba(feature_df)[0, 1])

            # Saved F1-optimized threshold (0.2), never a silent 0.5 default.
            threshold = get_no_show_threshold()
            no_show_class = int(probability >= threshold)

            prediction_result["prediction"] = {
                "no_show": bool(no_show_class),
                "no_show_probability": round(probability, 4),
                "risk_level": "high" if probability > 0.6 else "medium" if probability > 0.3 else "low",
                "threshold_used": float(threshold),
            }
            prediction_result["confidence"] = round(probability, 4)
            prediction_result["prediction_status"] = "success"
            prediction_result["model_version_id"] = get_settings().ml_no_show_model_version

        except Exception as exc:
            log_error(f"No-show prediction failed for {appointment_id}", exception_type=type(exc).__name__)
            prediction_result["prediction_status"] = "failed"
            prediction_result["error_message"] = str(exc)
    else:
        # Artifact unavailable: documented rule-based fallback (Blueprint
        # §14.2 — continue non-ML workflow, clearly indicate model version).
        risk_score = 0
        past_rate = _num(appointment.get("past_no_show_rate"), 0)
        if past_rate > 0.3:
            risk_score += 30
        elif past_rate > 0.15:
            risk_score += 15

        if _num(appointment.get("lead_time_hours"), 0) > 168:
            risk_score += 15

        if not appointment.get("reminder_sent"):
            risk_score += 5

        prediction_result["prediction"] = {
            "no_show": risk_score >= 30,
            "risk_level": "high" if risk_score >= 40 else "medium" if risk_score >= 20 else "low",
            "risk_score": risk_score,
        }
        prediction_result["confidence"] = None
        prediction_result["prediction_status"] = "success"
        prediction_result["model_version_id"] = "rule_based_v1"

    _log_prediction(admin_supabase, prediction_result, features)

    log_info("No-show prediction completed", appointment_id=appointment_id, result=prediction_result["prediction"])
    return prediction_result


# ---------------------------------------------------------------------------
# Inference — waiting time (check-in)
# ---------------------------------------------------------------------------

def predict_waiting_time(appointment_id: str) -> dict[str, Any]:
    """
    Run waiting-time prediction at check-in.
    Requires queue and operational features (gated on actual_checkin_time).
    """
    admin_supabase = get_supabase_admin_client()

    appt_res = admin_supabase.table("appointments").select("*").eq("appointment_id", appointment_id).execute()
    if not appt_res.data:
        return {"success": False, "error": "Appointment not found"}

    appointment = appt_res.data[0]

    if not appointment.get("actual_checkin_time"):
        return {"success": False, "error": "Waiting-time prediction requires check-in first."}

    features = build_waiting_time_features(appointment)

    model = _load_waiting_time_model()

    prediction_result = {
        "prediction_type": "waiting_time",
        "entity_type": "appointment",
        "entity_id": appointment_id,
        "input_snapshot": features,
        "predicted_at": datetime.now(timezone.utc).isoformat(),
    }

    missing = _resolve_missing(features, WAITING_TIME_NUMERIC_FEATURES)
    if missing:
        # No source for required features — refuse rather than fabricate.
        prediction_result["prediction"] = None
        prediction_result["confidence"] = None
        prediction_result["prediction_status"] = "insufficient_data"
        prediction_result["error_message"] = f"Missing features without data source: {', '.join(missing)}"
        prediction_result["model_version_id"] = get_settings().ml_waiting_time_model_version
        _log_prediction(admin_supabase, prediction_result, features)
        return prediction_result

    if model is not None:
        try:
            feature_df = _prepare_dataframe(
                features,
                WAITING_TIME_NUMERIC_FEATURES,
                WAITING_TIME_CATEGORICAL_FEATURES,
            )

            prediction = float(model.predict(feature_df)[0])

            prediction_result["prediction"] = {
                "predicted_wait_minutes": round(max(0.0, prediction), 2),
            }
            prediction_result["confidence"] = None
            prediction_result["prediction_status"] = "success"
            prediction_result["model_version_id"] = get_settings().ml_waiting_time_model_version

        except Exception as exc:
            log_error(f"Waiting-time prediction failed for {appointment_id}", exception_type=type(exc).__name__)
            prediction_result["prediction_status"] = "failed"
            prediction_result["error_message"] = str(exc)
    else:
        # Fallback heuristic: patients ahead x recent average service time.
        patients_ahead = _num(appointment.get("patients_ahead_at_checkin"), 0)
        avg_service = _num(appointment.get("avg_service_time_last_24h"), 15)
        estimated_wait = patients_ahead * (avg_service or 15)

        prediction_result["prediction"] = {
            "predicted_wait_minutes": round(estimated_wait, 2),
        }
        prediction_result["confidence"] = None
        prediction_result["prediction_status"] = "success"
        prediction_result["model_version_id"] = "heuristic_v1"

    _log_prediction(admin_supabase, prediction_result, features)

    log_info("Waiting-time prediction completed", appointment_id=appointment_id)
    return prediction_result


# ---------------------------------------------------------------------------
# Inference — waiting time (booking / pre-check-in)
# ---------------------------------------------------------------------------

def predict_booking_waiting_time(appointment_id: str) -> dict[str, Any]:
    """
    Booking-time waiting-time prediction.

    Uses the booking_waiting_model artifact: the check-in feature set minus the
    queue columns, so it is valid BEFORE check-in. Trailing operational
    features are resolved from row snapshot or real DB history — never from
    the future.
    """
    admin_supabase = get_supabase_admin_client()

    appt_res = admin_supabase.table("appointments").select("*").eq("appointment_id", appointment_id).execute()
    if not appt_res.data:
        return {"success": False, "error": "Appointment not found"}

    appointment = appt_res.data[0]

    if appointment.get("actual_checkin_time"):
        # Lifecycle correctness: once checked in, the check-in model applies.
        return {
            "success": False,
            "error": "Patient already checked in; use the check-in waiting-time prediction.",
        }

    features = build_booking_waiting_features(appointment)
    model = _load_booking_waiting_model()

    prediction_result = {
        "prediction_type": "booking_waiting_time",
        "entity_type": "appointment",
        "entity_id": appointment_id,
        "input_snapshot": features,
        "predicted_at": datetime.now(timezone.utc).isoformat(),
    }

    missing = _resolve_missing(features, BOOKING_WAITING_NUMERIC_FEATURES)
    if missing:
        prediction_result["prediction"] = None
        prediction_result["confidence"] = None
        prediction_result["prediction_status"] = "insufficient_data"
        prediction_result["error_message"] = f"Missing features without data source: {', '.join(missing)}"
        prediction_result["model_version_id"] = get_settings().ml_waiting_time_model_version
        _log_prediction(admin_supabase, prediction_result, features)
        return prediction_result

    if model is not None:
        try:
            feature_df = _prepare_dataframe(
                features,
                BOOKING_WAITING_NUMERIC_FEATURES,
                BOOKING_WAITING_CATEGORICAL_FEATURES,
            )
            prediction = float(model.predict(feature_df)[0])
            prediction_result["prediction"] = {
                "predicted_wait_minutes": round(max(0.0, prediction), 2),
            }
            prediction_result["confidence"] = None
            prediction_result["prediction_status"] = "success"
            prediction_result["model_version_id"] = get_settings().ml_waiting_time_model_version
        except Exception as exc:
            log_error(f"Booking waiting-time prediction failed for {appointment_id}",
                      exception_type=type(exc).__name__)
            prediction_result["prediction_status"] = "failed"
            prediction_result["error_message"] = str(exc)
    else:
        # Documented fallback: department's recent average wait.
        recent_wait = features.get("avg_wait_last_24h")
        prediction_result["prediction"] = {
            "predicted_wait_minutes": round(float(recent_wait or 0), 2),
        }
        prediction_result["confidence"] = None
        prediction_result["prediction_status"] = "success"
        prediction_result["model_version_id"] = "heuristic_v1"

    _log_prediction(admin_supabase, prediction_result, features)

    log_info("Booking waiting-time prediction completed", appointment_id=appointment_id)
    return prediction_result


# ---------------------------------------------------------------------------
# Inference — booking-time waiting preview (no appointment yet)
# ---------------------------------------------------------------------------

def predict_booking_waiting_preview(
    *,
    doctor_id: str,
    scheduled_start: str,
    availability_id: str | None = None,
) -> dict[str, Any]:
    """
    Booking-time waiting-time preview for a slot BEFORE an appointment
    exists (spec §10.3 / §20). Reuses historical appointment/waiting-time
    data — no new model and no invented values.

    Selection tiers (first non-empty wins; the basis string always names
    the tier actually used and the real sample size):
      1. this doctor, same weekday, similar slot load
         (slot utilization within ±20 points of the requested slot),
      2. this doctor, same weekday,
      3. this doctor, any weekday,
      4. department, same weekday,
      5. department, any weekday,
      6. none => 0.0 with an honest "insufficient history" basis.

    The current booked load of the requested availability slot
    (booked_count/slot_capacity, +1 for this booking) feeds tier 1 and is
    reported in the basis.
    """
    admin_supabase = get_supabase_admin_client()
    from app.utils.exceptions import (
        AvailabilityNotFoundError,
        DoctorNotFoundError,
        InvalidOperationError,
    )

    doc_res = (
        admin_supabase.table("doctors")
        .select("doctor_id, full_name, department_id, status")
        .eq("doctor_id", doctor_id)
        .execute()
    )
    if not doc_res.data:
        raise DoctorNotFoundError(doctor_id)
    doctor = doc_res.data[0]

    try:
        start_dt = datetime.fromisoformat(str(scheduled_start).replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidOperationError("scheduled_start must be an ISO-8601 datetime.") from exc
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)

    department_id = doctor.get("department_id")
    department_name = None
    if department_id:
        dept_res = (
            admin_supabase.table("departments")
            .select("name")
            .eq("department_id", department_id)
            .execute()
        )
        if dept_res.data:
            department_name = dept_res.data[0].get("name")

    # Current booked load of the requested slot (real availability row).
    slot_utilization_pct: float | None = None
    slot_load_basis = "slot load unknown (no availability slot provided)"
    if availability_id:
        slot_res = (
            admin_supabase.table("doctor_availability")
            .select("*")
            .eq("availability_id", availability_id)
            .execute()
        )
        if not slot_res.data:
            raise AvailabilityNotFoundError(availability_id)
        slot = slot_res.data[0]
        if slot.get("doctor_id") and slot.get("doctor_id") != doctor_id:
            raise InvalidOperationError("The availability slot does not belong to the specified doctor.")
        capacity = float(slot.get("slot_capacity") or 0)
        booked = float(slot.get("booked_count") or 0)
        if capacity > 0:
            # +1 — the load this booking would create (same invariant as the
            # booking flow's slot_utilization_pct feature).
            slot_utilization_pct = round((booked + 1) / capacity * 100.0, 2)
        slot_load_basis = f"current slot load {int(booked)}/{int(capacity)} booked"

    now = datetime.now(timezone.utc)

    def _collect_waits(query) -> list[dict[str, Any]]:
        """Past appointments with a recorded actual wait (real history only)."""
        rows = query.limit(1000).execute().data or []
        collected: list[dict[str, Any]] = []
        for r in rows:
            wait = r.get("actual_wait_minutes")
            if wait is None:
                continue
            try:
                dt = datetime.fromisoformat(str(r.get("scheduled_start")).replace("Z", "+00:00"))
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt > now:
                continue
            util = r.get("slot_utilization_pct")
            collected.append({
                "weekday": dt.weekday(),
                "wait": float(wait),
                "util": float(util) if util is not None else None,
            })
        return collected

    doctor_waits = _collect_waits(
        admin_supabase.table("appointments")
        .select("scheduled_start, actual_wait_minutes, slot_utilization_pct")
        .eq("doctor_id", doctor_id)
        .lte("scheduled_start", now.isoformat())
        .order("scheduled_start", desc=True)
    )

    target_weekday = start_dt.weekday()
    chosen: list[dict[str, Any]] = []
    tier: str | None = None

    if slot_utilization_pct is not None:
        band = [
            w for w in doctor_waits
            if w["weekday"] == target_weekday
            and w["util"] is not None
            and abs(w["util"] - slot_utilization_pct) <= 20
        ]
        if band:
            chosen, tier = band, "similar-slot"
    if not chosen:
        same_weekday = [w for w in doctor_waits if w["weekday"] == target_weekday]
        if same_weekday:
            chosen, tier = same_weekday, "same-weekday"
    if not chosen and doctor_waits:
        chosen, tier = doctor_waits, "doctor-history"
    if not chosen and department_name:
        dept_waits = _collect_waits(
            admin_supabase.table("appointments")
            .select("scheduled_start, actual_wait_minutes, slot_utilization_pct")
            .eq("department_name", department_name)
            .lte("scheduled_start", now.isoformat())
            .order("scheduled_start", desc=True)
        )
        dept_same_weekday = [w for w in dept_waits if w["weekday"] == target_weekday]
        if dept_same_weekday:
            chosen, tier = dept_same_weekday, "department-same-weekday"
        elif dept_waits:
            chosen, tier = dept_waits, "department-history"

    if not chosen:
        return {
            "predicted_waiting_min": 0.0,
            "label": "Not enough data yet",
            "basis": (
                "insufficient history: no recorded waiting times for this "
                f"doctor or department yet; {slot_load_basis}"
            ),
        }

    value = round(sum(w["wait"] for w in chosen) / len(chosen), 1)
    n = len(chosen)
    weekday_name = start_dt.strftime("%A")
    doctor_label = doctor.get("full_name") or "this doctor"
    tier_text = {
        "similar-slot": f"average recorded wait for {doctor_label} on {weekday_name}s at a similar slot load (n={n} appointments)",
        "same-weekday": f"average recorded wait for {doctor_label} on {weekday_name}s (n={n} appointments)",
        "doctor-history": f"average recorded wait for {doctor_label} on any day (n={n} appointments)",
        "department-same-weekday": f"average recorded {department_name} department wait on {weekday_name}s (n={n} appointments; no doctor-specific history yet)",
        "department-history": f"average recorded {department_name} department wait on any day (n={n} appointments; no doctor-specific history yet)",
    }[tier]

    return {
        "predicted_waiting_min": value,
        "label": f"≈ {value:g} min",
        "basis": f"{tier_text}; {slot_load_basis}",
    }


# ---------------------------------------------------------------------------
# Inference — department-level forecasts
# ---------------------------------------------------------------------------

def _forecast_departments() -> list[dict[str, Any]]:
    """Distinct departments present in the appointment fact table (with ids)."""
    admin_supabase = get_supabase_admin_client()
    # Paginate: PostgREST caps responses at 1,000 rows, so the previous
    # .limit(5000) still returned only the first 1,000 rows and could miss
    # departments that appear later in the table. Same paging pattern as
    # analytics_service._fetch_all_rows (not imported here to avoid an
    # import cycle: analytics imports this module).
    seen: dict[str, str] = {}
    offset, page_size = 0, 1000
    forecast_rows: list[dict[str, Any]] = []
    while True:
        page = (
            admin_supabase.table("appointments")
            .select("department_name, department_id")
            .order("appointment_id")  # unique key -> stable, disjoint pages
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = page.data or []
        forecast_rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    for row in forecast_rows:
        name = row.get("department_name")
        if name and name not in seen:
            seen[name] = row.get("department_id") or ""
    return [{"department_name": n, "department_id": i} for n, i in seen.items()]


def predict_bed_demand(target_date: date_type) -> dict[str, Any]:
    """
    Department-level next-day bed-demand forecast (Param_v4 endpoint contract):
    {target_date, predictions: [{department_name, predicted_bed_demand}]}.
    Departments whose required features have no data source are reported in
    `insufficient` instead of being predicted with fabricated values.
    """
    admin_supabase = get_supabase_admin_client()
    model = _load_bed_demand_model()

    result: dict[str, Any] = {
        "prediction_type": "bed_demand",
        "target_date": target_date.isoformat(),
        "predicted_at": datetime.now(timezone.utc).isoformat(),
        "predictions": [],
        "insufficient": [],
        "model_version_id": "bed_demand_v1.0",
    }

    if model is None:
        result["error_message"] = (
            "The forecast model artifact is unavailable; showing the stored "
            "7-day average forecast instead."
        )
        # Documented non-ML fallback: latest stored dept-day label per dept.
        for dept in _forecast_departments():
            snapshot = _dept_latest_snapshot(dept["department_name"])
            stored = snapshot.get("beds_demand_last_7d_avg")
            if stored is not None:
                result["predictions"].append({
                    "department_name": dept["department_name"],
                    "predicted_bed_demand": round(float(stored), 2),
                    "source": "stored_7d_avg",
                })
        result["prediction_status"] = "fallback" if result["predictions"] else "failed"
        return result

    for dept in _forecast_departments():
        name = dept["department_name"]
        features, missing = build_bed_demand_features(name, target_date)
        if missing:
            result["insufficient"].append({"department_name": name, "missing": missing})
            continue
        try:
            feature_df = _prepare_dataframe(
                features, BED_DEMAND_NUMERIC_FEATURES, BED_DEMAND_CATEGORICAL_FEATURES)
            prediction = max(0.0, float(model.predict(feature_df)[0]))
            pred_value = round(prediction, 2)
            result["predictions"].append({
                "department_name": name,
                "predicted_bed_demand": pred_value,
            })
            _log_prediction(admin_supabase, {
                "prediction_type": "bed_demand",
                "entity_type": "department",
                "entity_id": dept["department_id"] or None,
                "predicted_at": result["predicted_at"],
                "prediction": {"predicted_bed_demand": pred_value,
                               "department_name": name,
                               "target_date": target_date.isoformat()},
                "confidence": None,
                "prediction_status": "success",
                "model_version_id": result["model_version_id"],
            }, features)
        except Exception as exc:
            log_error(f"Bed-demand prediction failed for {name}", exception_type=type(exc).__name__)
            result["insufficient"].append({"department_name": name,
                                           "missing": [f"prediction_error: {type(exc).__name__}"]})

    result["prediction_status"] = "success" if result["predictions"] else "insufficient_data"
    return result


def predict_patient_flow(target_date: date_type) -> dict[str, Any]:
    """
    Department-level next-day patient-flow forecast (Param_v4 endpoint
    contract): {target_date, predictions: [{department_name,
    predicted_patient_flow}]} with `insufficient` for data-less departments.
    """
    admin_supabase = get_supabase_admin_client()
    model = _load_patient_flow_model()

    result: dict[str, Any] = {
        "prediction_type": "patient_flow",
        "target_date": target_date.isoformat(),
        "predicted_at": datetime.now(timezone.utc).isoformat(),
        "predictions": [],
        "insufficient": [],
        "model_version_id": "patient_flow_v1.0",
    }

    if model is None:
        result["error_message"] = (
            "The forecast model artifact is unavailable; showing the stored "
            "7-day average forecast instead."
        )
        for dept in _forecast_departments():
            snapshot = _dept_latest_snapshot(dept["department_name"])
            stored = snapshot.get("patient_flow_last_7d_avg")
            if stored is not None:
                result["predictions"].append({
                    "department_name": dept["department_name"],
                    "predicted_patient_flow": round(float(stored), 2),
                    "source": "stored_7d_avg",
                })
        result["prediction_status"] = "fallback" if result["predictions"] else "failed"
        return result

    for dept in _forecast_departments():
        name = dept["department_name"]
        features, missing = build_patient_flow_features(name, target_date)
        if missing:
            result["insufficient"].append({"department_name": name, "missing": missing})
            continue
        try:
            feature_df = _prepare_dataframe(
                features, PATIENT_FLOW_NUMERIC_FEATURES, PATIENT_FLOW_CATEGORICAL_FEATURES)
            prediction = max(0.0, float(model.predict(feature_df)[0]))
            pred_value = round(prediction, 2)
            result["predictions"].append({
                "department_name": name,
                "predicted_patient_flow": pred_value,
            })
            _log_prediction(admin_supabase, {
                "prediction_type": "patient_flow",
                "entity_type": "department",
                "entity_id": dept["department_id"] or None,
                "predicted_at": result["predicted_at"],
                "prediction": {"predicted_patient_flow": pred_value,
                               "department_name": name,
                               "target_date": target_date.isoformat()},
                "confidence": None,
                "prediction_status": "success",
                "model_version_id": result["model_version_id"],
            }, features)
        except Exception as exc:
            log_error(f"Patient-flow prediction failed for {name}", exception_type=type(exc).__name__)
            result["insufficient"].append({"department_name": name,
                                           "missing": [f"prediction_error: {type(exc).__name__}"]})

    result["prediction_status"] = "success" if result["predictions"] else "insufficient_data"
    return result


# ---------------------------------------------------------------------------
# No-show batch job (staff-triggered, idempotent — PROJECT CONTEXT §9)
# ---------------------------------------------------------------------------

def run_no_show_prediction_job() -> dict[str, Any]:
    """
    Score every appointment in the 24h prediction window:
        scheduled_start > NOW() AND scheduled_start <= NOW() + 24h
        AND appointment_status = 'booked'

    Idempotency: appointments already scored successfully with the current
    model version within NOSHOW_RESCORE_INTERVAL are skipped, so repeated
    staff triggers do not flood prediction_logs (deliberate re-scoring policy,
    PROJECT CONTEXT §9.2).
    """
    admin_supabase = get_supabase_admin_client()
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=24)
    model_version = get_settings().ml_no_show_model_version

    eligible_res = (
        admin_supabase.table("appointments")
        .select("appointment_id")
        .eq("appointment_status", "booked")
        .gt("scheduled_start", now.isoformat())
        .lte("scheduled_start", horizon.isoformat())
        .order("scheduled_start")
        .execute()
    )
    eligible_ids = [r["appointment_id"] for r in (eligible_res.data or []) if r.get("appointment_id")]

    job_result: dict[str, Any] = {
        "job": "no_show_predictions",
        "window_start": now.isoformat(),
        "window_end": horizon.isoformat(),
        "eligible": len(eligible_ids),
        "scored": 0,
        "skipped_existing": 0,
        "failed": 0,
        "results": [],
    }
    if not eligible_ids:
        return job_result

    # Discover existing recent predictions for idempotency.
    already_scored: set[str] = set()
    rescore_cutoff = now - NOSHOW_RESCORE_INTERVAL
    try:
        logs_res = (
            admin_supabase.table("prediction_logs")
            .select("entity_id, predicted_at, model_version_id, prediction_status, prediction")
            .eq("prediction_type", "no_show")
            .in_("entity_id", eligible_ids)
            .execute()
        )
        for row in logs_res.data or []:
            if (row.get("prediction_status") == "success"
                    and _stored_model_version(row) == model_version):
                try:
                    predicted_at = datetime.fromisoformat(
                        str(row.get("predicted_at")).replace("Z", "+00:00"))
                    if predicted_at.tzinfo is None:
                        predicted_at = predicted_at.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                if predicted_at >= rescore_cutoff:
                    already_scored.add(str(row.get("entity_id")))
    except Exception as exc:
        log_error("No-show job idempotency lookup failed", exception_type=type(exc).__name__)

    for appointment_id in eligible_ids:
        if appointment_id in already_scored:
            job_result["skipped_existing"] += 1
            job_result["results"].append({
                "appointment_id": appointment_id,
                "status": "skipped_existing",
            })
            continue

        prediction = predict_no_show(appointment_id)
        status = prediction.get("prediction_status")
        if status == "success":
            job_result["scored"] += 1
            job_result["results"].append({
                "appointment_id": appointment_id,
                "status": "scored",
                "no_show_probability": prediction.get("prediction", {}).get("no_show_probability"),
                "risk_level": prediction.get("prediction", {}).get("risk_level"),
                "model_version_id": prediction.get("model_version_id"),
            })
        else:
            job_result["failed"] += 1
            job_result["results"].append({
                "appointment_id": appointment_id,
                "status": "failed",
                "error": prediction.get("error_message"),
            })

    log_info(
        "No-show prediction job completed",
        eligible=job_result["eligible"],
        scored=job_result["scored"],
        skipped_existing=job_result["skipped_existing"],
        failed=job_result["failed"],
    )
    return job_result
