"""
Offline numerical verification harness for the ML/analytics integration.

Runs WITHOUT a network database: it backs the service layer with a
PostgREST-compatible in-memory fake seeded from the Param_v4 deterministic
dataset (Database_Setup/*.csv) — the same fact table the model artifacts were
trained on. This lets us verify REAL numbers end to end:

  A. artifact ground truth (threshold, feature lists)
  B. no-show builder fidelity vs stored training rows + probability parity
  C. falsy-value regression (hour=0 / booked_count=0 preserved)
  D. bed-demand feature fidelity + prediction parity (incl. occupancy 0-100)
  E. patient-flow feature fidelity + prediction parity
  F. booking / check-in waiting-time fidelity + lifecycle gates
  G. PARAM_V4 occupancy scale bug: effect size on predictions
  H. PARAM_V4 row-sum aggregation inflation evidence
  I. analytics resample date bug (old) vs fix (new)
  J. full service-layer smoke: all 4 predict paths + batch job idempotency
  K. risk-queue (analytics) ML path + prediction_logs writes

Usage:
    python numerical_harness.py            # from integrated_hospital/ or tests/
Exit code 0 iff every check passes.
"""
from __future__ import annotations

import sys
import json
import warnings
from datetime import datetime, timezone, timedelta, date as date_type
from functools import lru_cache
from pathlib import Path

warnings.filterwarnings("ignore")

import joblib
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                    # integrated_hospital/
sys.path.insert(0, str(ROOT))

CSV_DIR = ROOT.parent / "Param_v4" / "Database_Setup"
MODELS = ROOT / "app" / "ml" / "models"

import app.services.prediction_service as ps          # noqa: E402
import app.services.analytics_service as an           # noqa: E402
from app.services.prediction_service import (         # noqa: E402
    NO_SHOW_BOOLEAN_FEATURES,
    NO_SHOW_CATEGORICAL_FEATURES,
    NO_SHOW_NUMERIC_FEATURES,
    BOOKING_WAITING_CATEGORICAL_FEATURES,
    BOOKING_WAITING_NUMERIC_FEATURES,
    WAITING_TIME_CATEGORICAL_FEATURES,
    WAITING_TIME_NUMERIC_FEATURES,
    BED_DEMAND_CATEGORICAL_FEATURES,
    BED_DEMAND_NUMERIC_FEATURES,
    PATIENT_FLOW_CATEGORICAL_FEATURES,
    PATIENT_FLOW_NUMERIC_FEATURES,
    build_no_show_features,
    build_booking_waiting_features,
    build_waiting_time_features,
    build_bed_demand_features,
    build_patient_flow_features,
    _prepare_dataframe,
    get_no_show_threshold,
    run_no_show_prediction_job,
    predict_no_show,
    predict_waiting_time,
    predict_booking_waiting_time,
    predict_bed_demand,
    predict_patient_flow,
)


# ---------------------------------------------------------------------------
# Minimal PostgREST-compatible fake (only the operators this app uses)
# ---------------------------------------------------------------------------

TIME_COLS = {
    "scheduled_start", "scheduled_end", "booked_at", "actual_checkin_time",
    "actual_service_start", "actual_service_end", "created_at", "updated_at",
}


@lru_cache(maxsize=None)
def _ts(value):
    """Parse to naive UTC datetime (app convention: naive == UTC).

    lru_cache: FakeQuery._matches calls this per row per predicate over the
    8,000-row table; uncached pd.to_datetime format-guessing made each query
    take seconds and stalled the harness (values are hashable scalars:
    str/None/float from the JSON-normalized records).
    """
    try:
        t = pd.to_datetime(value, errors="coerce", utc=True)
    except (TypeError, ValueError):
        return None
    if pd.isna(t):
        return None
    return t.tz_convert(None)


class _Result:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count if count is not None else len(data)


class FakeQuery:
    def __init__(self, owner, table_name):
        self.owner = owner
        self.table_name = table_name
        self.predicates = []          # (op, col, val)
        self._order = None            # (col, desc)
        self._limit = None
        self._range = None            # (lo, hi) inclusive, PostgREST-style
        self._cols = None
        self._count = False

    # -- chainables ---------------------------------------------------------
    def select(self, *cols, count=None):
        flat = []
        for c in cols:
            flat.extend([p.strip() for p in str(c).split(",") if p.strip()])
        self._cols = None if flat == ["*"] else flat
        self._count = count == "exact"
        return self

    def eq(self, col, val):       self.predicates.append(("eq", col, val));  return self
    def neq(self, col, val):      self.predicates.append(("neq", col, val)); return self
    def gt(self, col, val):       self.predicates.append(("gt", col, val));  return self
    def gte(self, col, val):      self.predicates.append(("gte", col, val)); return self
    def lt(self, col, val):       self.predicates.append(("lt", col, val));  return self
    def lte(self, col, val):      self.predicates.append(("lte", col, val)); return self
    def in_(self, col, vals):
        self.predicates.append(("in", col, list(vals)))
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, lo, hi):
        """PostgREST Range: inclusive [lo, hi] window (what _fetch_all_rows
        uses to page past the production 1,000-row cap)."""
        self._range = (int(lo), int(hi))
        return self

    # -- execution ----------------------------------------------------------
    def _matches(self, row):
        for op, col, val in self.predicates:
            cell = row.get(col)
            if op == "eq":
                if cell != val and not (isinstance(cell, float) and isinstance(val, (int, float)) and cell == val):
                    if str(cell) != str(val):
                        return False
            elif op == "neq":
                if cell == val:
                    return False
            elif op == "in":
                if cell not in val:
                    return False
            else:  # gt/gte/lt/ltc on possibly-temporal columns
                if col in TIME_COLS:
                    a, b = _ts(cell), _ts(val)
                    if a is None or b is None:
                        return False
                else:
                    a, b = cell, val
                    if a is None:
                        return False
                if op == "gt" and not (a > b):  return False
                if op == "gte" and not (a >= b): return False
                if op == "lt" and not (a < b):  return False
                if op == "lte" and not (a <= b): return False
        return True

    def execute(self):
        rows = self.owner.tables.get(self.table_name, [])
        out = [r for r in rows if self._matches(r)]
        if self._order:
            col, desc = self._order
            out = sorted(out, key=lambda r: (r.get(col) is None, str(r.get(col)) or ""),
                         reverse=desc)
        if self._limit is not None:
            out = out[: self._limit]
        if self._range is not None:
            lo, hi = self._range
            out = out[lo: hi + 1]
        count = len(out)
        if self._cols is not None:
            out = [{c: r.get(c) for c in self._cols} for r in out]
        # null-clean like JSON
        out = [{k: (None if (isinstance(v, float) and pd.isna(v)) else v)
                for k, v in r.items()} for r in out]
        return _Result(out, count if self._count else None)

    def insert(self, payload):
        self.owner.tables.setdefault(self.table_name, []).append(dict(payload))
        return _Result([payload])


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeQuery(self, name)


def load_csv_tables():
    appt = pd.read_csv(CSV_DIR / "appointments.csv")
    doctors = pd.read_csv(CSV_DIR / "doctors.csv")
    profiles = pd.read_csv(CSV_DIR / "profiles.csv")

    def records(df):
        return json.loads(df.to_json(orient="records"))

    appt_recs = records(appt)
    departments = {}
    for r in appt_recs:
        departments.setdefault(r.get("department_name"), r.get("department_id"))
    return {
        "appointments": appt_recs,
        "doctors": records(doctors),
        "profiles": records(profiles),
        "departments": [{"name": k, "department_id": v} for k, v in departments.items()],
        "prediction_logs": [],
    }, appt


# ---------------------------------------------------------------------------
# Check bookkeeping
# ---------------------------------------------------------------------------

RESULTS = []


def check(section, name, ok, detail=""):
    RESULTS.append((section, name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(ok)


def section(title):
    print(f"\n== {title} ==")


def main():
    fake = FakeSupabase(load_csv_tables()[0])
    csv = load_csv_tables()[1]

    # Route every DB access in the service layer to the fake.
    ps.get_supabase_admin_client = lambda: fake
    an.get_supabase_admin_client = lambda: fake

    no_show = joblib.load(MODELS / "no_show_pipeline.pkl")
    bed_model = joblib.load(MODELS / "bed_demand_model.pkl")
    flow_model = joblib.load(MODELS / "patient_flow_model.pkl")
    booking_model = joblib.load(MODELS / "booking_waiting_model.pkl")
    checkin_model = joblib.load(MODELS / "checkin_waiting_model.pkl")

    now = datetime.now(timezone.utc)
    today = now.date()

    # ---------------- A. ground truth ----------------
    section("A. Artifact ground truth")
    thr = get_no_show_threshold()
    check("A", "threshold == 0.2 (saved artifact, not 0.5)", abs(thr - 0.2) < 1e-9, f"{thr:.4f}")
    for label, m, expect in [
        ("no_show", no_show, 21),
        ("bed", bed_model, 13),
        ("flow", flow_model, 11),
        ("booking", booking_model, 12),
        ("checkin", checkin_model, 14),
    ]:
        n = len(m.feature_names_in_)
        check("A", f"{label} feature count == {expect}", n == expect, f"got {n}")

    # ---------------- B. no-show fidelity ----------------
    section("B. No-show: builder fidelity + probability parity (n=500)")
    sample = csv.sample(500, random_state=7)
    max_feat = 0.0
    max_prob = 0.0
    cat_mm = 0
    for row in sample.to_dict("records"):
        f = build_no_show_features(row)
        for c in NO_SHOW_NUMERIC_FEATURES:
            max_feat = max(max_feat, abs(float(f[c]) - float(row[c])))
        for c in NO_SHOW_CATEGORICAL_FEATURES:
            if str(f[c]) != str(row[c]):
                cat_mm += 1
        p_int = float(no_show.predict_proba(
            _prepare_dataframe(f, NO_SHOW_NUMERIC_FEATURES,
                               NO_SHOW_CATEGORICAL_FEATURES, NO_SHOW_BOOLEAN_FEATURES))[0, 1])
        ref = {c: row[c] for c in NO_SHOW_NUMERIC_FEATURES + NO_SHOW_CATEGORICAL_FEATURES}
        ref["reminder_sent"] = bool(row["reminder_sent"])
        ref["reminder_hours_before"] = row["reminder_hours_before"]
        p_ref = float(no_show.predict_proba(pd.DataFrame([ref]))[0, 1])
        max_prob = max(max_prob, abs(p_int - p_ref))
    check("B", "feature values == stored training rows",
          max_feat == 0.0 and cat_mm == 0,
          f"max_diff={max_feat:.3e}, cat_mismatch={cat_mm}/3000")
    check("B", "probability parity vs direct artifact frame",
          max_prob < 1e-12, f"max_diff={max_prob:.3e}")

    # threshold effect
    ref_frame = []
    for row in sample.to_dict("records"):
        ref = {c: row[c] for c in NO_SHOW_NUMERIC_FEATURES + NO_SHOW_CATEGORICAL_FEATURES}
        ref["reminder_sent"] = bool(row["reminder_sent"])
        ref["reminder_hours_before"] = row["reminder_hours_before"]
        ref_frame.append(ref)
    probs = no_show.predict_proba(pd.DataFrame(ref_frame))[:, 1]
    pos_02 = int((probs >= thr).sum())
    pos_05 = int((probs >= 0.5).sum())
    check("B", "saved threshold 0.2 flags far more at-risk than the 0.5 bug",
          pos_02 > pos_05, f"positives@0.2={pos_02}/500 vs @0.5={pos_05}/500")

    # ---------------- C. falsy regression ----------------
    section("C. Falsy-value regression (None-safe defaults)")
    f0 = build_no_show_features({"appointment_hour": 0, "slot_booked_count": 0,
                                 "slot_capacity": 0, "lead_time_hours": 0})
    check("C", "appointment_hour=0 preserved", f0["appointment_hour"] == 0)
    check("C", "slot_booked_count=0 preserved", f0["slot_booked_count"] == 0)
    check("C", "slot_capacity=0 preserved", f0["slot_capacity"] == 0)
    f_none = build_no_show_features({"appointment_hour": None})
    check("C", "None still gets the documented default (12)", f_none["appointment_hour"] == 12)

    # ---------------- D. bed demand ----------------
    section("D. Bed-demand: feature fidelity vs stored snapshots + parity")
    dept_days = csv.assign(_d=csv.scheduled_start.str[:10])
    past = dept_days[dept_days._d <= str(today)]
    bed_sample = past.sample(min(300, len(past)), random_state=3)
    bed_feat_fail = []
    bed_pred_max = 0.0
    for r in bed_sample.to_dict("records"):
        tgt = date_type.fromisoformat(r["_d"])
        feats, missing = build_bed_demand_features(r["department_name"], tgt)
        if missing:
            bed_feat_fail.append((r["department_name"], missing))
            continue
        # ground truth: latest past dept row from the CSV (same rule as builder)
        dept_past = past[past.department_name == r["department_name"]].sort_values("scheduled_start")
        snap = dept_past.iloc[-1]
        gt_ok = (
            float(feats["total_beds"]) == float(snap.total_beds)
            and float(feats["occupied_beds"]) == float(snap.occupied_beds)
            and float(feats["occupancy_rate"]) == float(snap.occupancy_rate)
            and float(feats["admissions_last_24h"]) == float(snap.admissions_last_24h)
            and float(feats["discharges_last_24h"]) == float(snap.discharges_last_24h)
            and float(feats["arrivals_last_24h"]) == float(snap.arrivals_last_24h)
            and float(feats["completed_last_24h"]) == float(snap.completed_last_24h)
            and float(feats["beds_demand_last_7d_avg"]) == float(snap.beds_demand_last_7d_avg)
            and float(feats["patient_flow_last_7d_avg"]) == float(snap.patient_flow_last_7d_avg)
            and float(feats["appointment_weekday"]) == float(tgt.weekday())
            and float(feats["appointment_month"]) == float(tgt.month)
            and float(feats["department_scheduled_today"]) == float(
                len(past[(past.department_name == r["department_name"]) & (past._d == r["_d"])]))
        )
        if not gt_ok:
            bed_feat_fail.append((r["department_name"], "value mismatch"))
            continue
        # prediction parity: builder frame vs ground-truth frame
        gt_frame = {
            "total_beds": float(snap.total_beds), "occupied_beds": float(snap.occupied_beds),
            "occupancy_rate": float(snap.occupancy_rate),
            "admissions_last_24h": float(snap.admissions_last_24h),
            "discharges_last_24h": float(snap.discharges_last_24h),
            "arrivals_last_24h": float(snap.arrivals_last_24h),
            "completed_last_24h": float(snap.completed_last_24h),
            "department_scheduled_today": feats["department_scheduled_today"],
            "beds_demand_last_7d_avg": float(snap.beds_demand_last_7d_avg),
            "patient_flow_last_7d_avg": float(snap.patient_flow_last_7d_avg),
            "appointment_weekday": float(tgt.weekday()),
            "appointment_month": float(tgt.month),
            "department_name": r["department_name"],
        }
        p_int = float(bed_model.predict(_prepare_dataframe(
            feats, BED_DEMAND_NUMERIC_FEATURES, BED_DEMAND_CATEGORICAL_FEATURES))[0])
        p_gt = float(bed_model.predict(pd.DataFrame([gt_frame])[
            BED_DEMAND_NUMERIC_FEATURES + BED_DEMAND_CATEGORICAL_FEATURES])[0])
        bed_pred_max = max(bed_pred_max, abs(p_int - p_gt))
    check("D", "features == stored ground truth (snapshot + calendar + count)",
          not bed_feat_fail, f"failures={bed_feat_fail[:3]} (n={len(bed_sample)})")
    check("D", "prediction parity vs ground-truth frame",
          bed_pred_max < 1e-12, f"max_diff={bed_pred_max:.3e}")
    occ_bad = [f for _, f in bed_feat_fail if "value mismatch" in str(f)]
    check("D", "occupancy_rate on training scale (20-100 percent)",
          all(20 <= float(build_bed_demand_features(d, today)[0].get("occupancy_rate") or 0) <= 100
              for d in csv.department_name.unique()),
          "checked all departments")

    # ---------------- E. patient flow ----------------
    section("E. Patient-flow: feature fidelity + parity")
    flow_fail = []
    flow_pred_max = 0.0
    flow_sample = past.sample(min(300, len(past)), random_state=5)
    for r in flow_sample.to_dict("records"):
        tgt = date_type.fromisoformat(r["_d"])
        feats, missing = build_patient_flow_features(r["department_name"], tgt)
        if missing:
            flow_fail.append((r["department_name"], missing))
            continue
        dept_past = past[past.department_name == r["department_name"]].sort_values("scheduled_start")
        snap = dept_past.iloc[-1]
        day_rows = past[(past.department_name == r["department_name"]) & (past._d == r["_d"])]
        gt_hour = round(day_rows.appointment_hour.mean())
        gt_ok = (
            float(feats["arrivals_last_24h"]) == float(snap.arrivals_last_24h)
            and float(feats["completed_last_24h"]) == float(snap.completed_last_24h)
            and float(feats["avg_wait_last_24h"]) == float(snap.avg_wait_last_24h)
            and float(feats["patient_flow_last_7d_avg"]) == float(snap.patient_flow_last_7d_avg)
            and float(feats["department_active_doctors"]) == float(snap.department_active_doctors)
            and float(feats["department_active_staff"]) == float(snap.department_active_staff)
            and float(feats["department_scheduled_today"]) == float(len(day_rows))
            and int(feats["appointment_weekday"]) == tgt.weekday()
            and int(feats["appointment_month"]) == tgt.month
            and int(feats["appointment_hour"]) == gt_hour
        )
        if not gt_ok:
            flow_fail.append((r["department_name"], "value mismatch"))
            continue
        gt_frame = dict(feats)
        p_int = float(flow_model.predict(_prepare_dataframe(
            feats, PATIENT_FLOW_NUMERIC_FEATURES, PATIENT_FLOW_CATEGORICAL_FEATURES))[0])
        p_gt = float(flow_model.predict(pd.DataFrame([gt_frame])[
            PATIENT_FLOW_NUMERIC_FEATURES + PATIENT_FLOW_CATEGORICAL_FEATURES])[0])
        flow_pred_max = max(flow_pred_max, abs(p_int - p_gt))
    check("E", "features == stored ground truth (snapshot + calendar + count + hour)",
          not flow_fail, f"failures={flow_fail[:3]} (n={len(flow_sample)})")
    check("E", "prediction parity",
          flow_pred_max < 1e-12, f"max_diff={flow_pred_max:.3e}")

    # ---------------- F. booking / check-in ----------------
    section("F. Booking / check-in waiting-time fidelity + lifecycle gates")
    book_sample = past.sample(300, random_state=11)
    book_fail = 0
    book_pred_max = 0.0
    for r in book_sample.to_dict("records"):
        f = build_booking_waiting_features(r)
        for c in BOOKING_WAITING_NUMERIC_FEATURES:
            if float(f[c]) != float(r[c]):
                book_fail += 1
        if str(f["department_name"]) != str(r["department_name"]):
            book_fail += 1
        p_int = float(booking_model.predict(_prepare_dataframe(
            f, BOOKING_WAITING_NUMERIC_FEATURES, BOOKING_WAITING_CATEGORICAL_FEATURES))[0])
        ref = {c: r[c] for c in BOOKING_WAITING_NUMERIC_FEATURES}
        ref["department_name"] = r["department_name"]
        p_ref = float(booking_model.predict(pd.DataFrame([ref])[
            BOOKING_WAITING_NUMERIC_FEATURES + BOOKING_WAITING_CATEGORICAL_FEATURES])[0])
        book_pred_max = max(book_pred_max, abs(p_int - p_ref))
    check("F", "booking features == stored training rows",
          book_fail == 0, f"mismatches={book_fail}/{300 * 12}")
    check("F", "booking probability parity",
          book_pred_max < 1e-12, f"max_diff={book_pred_max:.3e}")

    checkin_fail = 0
    for r in book_sample.to_dict("records"):
        f = build_waiting_time_features(r)
        for c in WAITING_TIME_NUMERIC_FEATURES:
            if float(f[c]) != float(r[c]):
                checkin_fail += 1
    check("F", "check-in features == stored training rows",
          checkin_fail == 0, f"mismatches={checkin_fail}/{300 * 14}")

    # booking model must NOT need queue columns; check-in model DOES need them
    check("F", "booking feature set excludes queue columns",
          not ({"queue_length_at_checkin", "patients_ahead_at_checkin"} & set(BOOKING_WAITING_NUMERIC_FEATURES)))
    check("F", "check-in feature set includes queue columns",
          {"queue_length_at_checkin", "patients_ahead_at_checkin"} <= set(WAITING_TIME_NUMERIC_FEATURES))

    # ---------------- G. Param_v4 occupancy scale bug ----------------
    section("G. PARAM_V4 occupancy scale bug: effect size (percent vs fraction)")
    r = past[past.department_name == "Cardiology"].iloc[-1]
    tgt = date_type.fromisoformat(str(today))
    feats, missing = build_bed_demand_features("Cardiology", tgt)
    base = dict(feats)
    pct_pred = float(bed_model.predict(_prepare_dataframe(
        base, BED_DEMAND_NUMERIC_FEATURES, BED_DEMAND_CATEGORICAL_FEATURES))[0])
    frac = dict(base)
    frac["occupancy_rate"] = float(base["occupancy_rate"]) / 100.0
    frac_pred = float(bed_model.predict(_prepare_dataframe(
        frac, BED_DEMAND_NUMERIC_FEATURES, BED_DEMAND_CATEGORICAL_FEATURES))[0])
    delta_pct = abs(pct_pred - frac_pred) / max(abs(pct_pred), 1e-9) * 100
    check("G", "feeding 0-1 fraction materially distorts the prediction",
          delta_pct > 1, f"percent={pct_pred:.2f} beds vs fraction={frac_pred:.2f} beds "
                         f"({delta_pct:.1f}% relative error) — PARAM_V4 BUG scale")

    # ---------------- H. row-sum inflation ----------------
    section("H. PARAM_V4 row-sum aggregation inflation")
    dcol = csv.scheduled_start.str[:10]
    tmp = pd.DataFrame({"date": dcol, "dept": csv.department_name,
                        "lab": csv.next_day_bed_demand})
    row_sum = tmp.groupby("date")["lab"].sum()
    dept_first = tmp.groupby(["date", "dept"])["lab"].first().groupby("date").sum()
    infl = (row_sum / dept_first).replace([float("inf")], pd.NA).dropna()
    check("H", "row-wise sum inflates the hospital daily total",
          infl.mean() > 1.5,
          f"mean inflation x{infl.mean():.2f} "
          f"(rows/day avg {len(tmp) / tmp.date.nunique():.1f} vs 7 departments) — PARAM_V4 BUG")
    # department view: same label summed over that department's rows
    card = tmp[tmp.dept == "Cardiology"]
    card_row = card.groupby("date")["lab"].sum()
    card_true = card.groupby("date")["lab"].first()
    check("H", "department-view row sum inflates by that day's row count",
          (card_row / card_true).mean() > 1.5,
          f"mean inflation x{(card_row / card_true).mean():.2f}")

    # ---------------- I. resample date bug ----------------
    section("I. Analytics resample: object-date bug (old) vs datetime fix (new)")
    daily_old = tmp.groupby("date")["lab"].sum().reset_index()   # date = python date objects
    try:
        daily_old.set_index("date")["lab"].resample("ME").sum()
        old_raises = False
        old_err = ""
    except Exception as exc:
        old_raises = True
        old_err = type(exc).__name__
    daily_new = daily_old.copy()
    daily_new["date"] = pd.to_datetime(daily_new["date"])
    try:
        out = daily_new.set_index("date")["lab"].resample("ME").sum()
        new_ok = len(out) > 0
    except Exception as exc:
        new_ok = False
        new_err = type(exc).__name__
    check("I", "old code (object date) raises on resample",
          old_raises, old_err or "did NOT raise")
    check("I", "fixed code (datetime date) resamples successfully",
          new_ok)

    # ---------------- J. full service layer ----------------
    section("J. Service-layer smoke via fake DB (all predict paths + job)")
    # J1: no-show for a booked future appointment
    future_booked = csv[(csv.appointment_status == "booked")
                        & (csv.scheduled_start > str(now.replace(tzinfo=None)))
                        & (csv.scheduled_start <= str((now + timedelta(hours=24)).replace(tzinfo=None)))]
    j1 = predict_no_show(str(future_booked.iloc[0].appointment_id)) if len(future_booked) else None
    check("J", "predict_no_show runs with ML model + writes prediction_logs",
          j1 is not None and j1.get("prediction_status") == "success"
          and j1.get("model_version_id") == "v1.0"
          and isinstance(j1.get("prediction", {}).get("no_show_probability"), float),
          json.dumps({k: j1.get(k) for k in ("prediction_status", "model_version_id")}) if j1 else "no window rows")

    # J2: booking-time prediction for a not-yet-checked-in appointment
    pre = csv[(csv.appointment_status == "booked")
              & (csv.actual_checkin_time.isna())]
    j2 = predict_booking_waiting_time(str(pre.iloc[0].appointment_id))
    check("J", "predict_booking_waiting_time succeeds (pre-check-in)",
          j2.get("prediction_status") == "success"
          and isinstance(j2.get("prediction", {}).get("predicted_wait_minutes"), float),
          f"wait={j2.get('prediction', {}).get('predicted_wait_minutes')}")

    # J3: booking model must refuse after check-in (lifecycle gate)
    checked_in = csv[csv.actual_checkin_time.notna() & csv.actual_service_end.isna()]
    j3 = predict_booking_waiting_time(str(checked_in.iloc[0].appointment_id))
    check("J", "booking model refuses after check-in (lifecycle gate)",
          j3.get("success") is False and "check-in" in str(j3.get("error", "")),
          str(j3.get("error", ""))[:80])

    # J4: check-in waiting-time for a checked-in appointment
    j4 = predict_waiting_time(str(checked_in.iloc[0].appointment_id))
    check("J", "predict_waiting_time runs at check-in",
          j4.get("prediction_status") in ("success", "insufficient_data"),
          f"status={j4.get('prediction_status')}, "
          f"wait={(j4.get('prediction') or {}).get('predicted_wait_minutes')}")

    # J5: batch job (window + idempotency)
    job1 = run_no_show_prediction_job()
    job2 = run_no_show_prediction_job()
    check("J", "job scores the 24h window",
          job1.get("eligible", 0) > 0 and job1.get("scored", 0) > 0,
          f"eligible={job1.get('eligible')} scored={job1.get('scored')} failed={job1.get('failed')}")
    check("J", "job is idempotent on immediate re-run",
          job2.get("scored") == 0
          and job2.get("skipped_existing") == job2.get("eligible"),
          f"2nd run: scored={job2.get('scored')} skipped={job2.get('skipped_existing')} "
          f"eligible={job2.get('eligible')}")

    # J6/J7: forecasts
    j6 = predict_bed_demand(today + timedelta(days=1))
    n_pred_6 = len(j6.get("predictions", []))
    check("J", "bed-demand forecast returns per-department predictions",
          j6.get("prediction_status") == "success" and n_pred_6 >= 5
          and all("department_name" in p and "predicted_bed_demand" in p
                  for p in j6["predictions"]),
          f"n={n_pred_6}, insufficient={len(j6.get('insufficient', []))}")
    j7 = predict_patient_flow(today + timedelta(days=1))
    n_pred_7 = len(j7.get("predictions", []))
    check("J", "patient-flow forecast returns per-department predictions",
          j7.get("prediction_status") == "success" and n_pred_7 >= 5
          and all("department_name" in p and "predicted_patient_flow" in p
                  for p in j7["predictions"]),
          f"n={n_pred_7}, insufficient={len(j7.get('insufficient', []))}")

    logs = fake.tables["prediction_logs"]
    types = {}
    for row in logs:
        types[row.get("prediction_type")] = types.get(row.get("prediction_type"), 0) + 1
    check("J", "prediction_logs populated across inference types",
          types.get("no_show", 0) >= 1 and types.get("booking_waiting_time", 0) >= 1
          and types.get("bed_demand", 0) >= 1 and types.get("patient_flow", 0) >= 1,
          json.dumps(types))

    # ---------------- K. risk queue ----------------
    section("K. Risk queue (analytics) ML path")
    try:
        rq = an.get_no_show_risk_queue()
        rows = rq.get("appointments", [])
        ml_rows = [r for r in rows if isinstance(r.get("no_show_probability"), (int, float))]
        check("K", "risk queue returns rows with ML probabilities",
              len(rows) > 0 and len(ml_rows) > 0,
              f"rows={len(rows)} ml_scored={len(ml_rows)} high={rq.get('high_risk_count')}")
        check("K", "risk queue agrees with saved 0.2 threshold semantics",
              all(r.get("risk_level") in ("low", "medium", "high") for r in ml_rows))
    except Exception as exc:
        check("K", "risk queue runs", False, f"{type(exc).__name__}: {exc}")

    # ---------------- summary ----------------
    passed = sum(1 for *_, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n{'=' * 60}\nHARNESS RESULT: {passed}/{total} checks passed"
          + ("" if passed == total else f", {total - passed} FAILED"))
    print("=" * 60)
    report = {
        "generated_at": now.isoformat(),
        "passed": passed,
        "total": total,
        "checks": [{"section": s, "name": n, "status": "pass" if ok else "fail",
                    "detail": d} for s, n, ok, d in RESULTS],
    }
    out = HERE / "numerical_harness_report.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"report: {out}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
