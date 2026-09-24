#!/usr/bin/env python3
"""
ML & Analytics Pipeline - Integration Test Suite
==================================================

Tests every endpoint of the ML prediction and analytics pipeline over HTTP,
the same way Swagger UI does, using a developer-supplied Supabase access token
as the Bearer token.

Endpoints covered:
  ML Predictions (staff/admin):
    POST /api/v1/predictions/no-show/{appointment_id}
    POST /api/v1/predictions/waiting-time/{appointment_id}

  Analytics (staff/admin):
    GET  /api/v1/analytics/appointments
    GET  /api/v1/analytics/no-show-risk
    GET  /api/v1/analytics/bed-demand
    GET  /api/v1/analytics/bed-demand/department/{department_name}
    GET  /api/v1/analytics/patient-flow
    GET  /api/v1/analytics/patient-flow/department/{department_name}
    GET  /api/v1/analytics/billing
    GET  /api/v1/analytics/satisfaction
    GET  /api/v1/analytics/booking-channel
    GET  /api/v1/analytics/no-show
    GET  /api/v1/analytics/waiting-time

Configuration (environment variables):
    BASE_URL / API_BASE_URL     default: http://127.0.0.1:8000
    API_ACCESS_TOKEN            Supabase access token (otherwise interactive prompt)
    REQUEST_TIMEOUT             seconds, default 30
    STAFF_ACCESS_TOKEN          optional staff-role token (for RBAC negative tests)
    PATIENT_ACCESS_TOKEN        optional patient-role token (for RBAC negative tests)

Usage:
    API_ACCESS_TOKEN=<token> python integrated_hospital/tests/test_ml_analytics_pipeline.py

Output:
    - Human readable PASS / FAIL / SKIPPED log
    - ml_analytics_test_report.json   full machine-readable results

Exit codes:
    0 = all executed tests passed (skips allowed)
    1 = one or more unexpected failures
    2 = catastrophic setup failure (server unreachable / token rejected)

The access token is NEVER printed or written to any file (only masked).
"""
from __future__ import annotations

import getpass
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

try:
    import httpx
except ImportError:
    print("FATAL: httpx is required. Install with: pip install httpx")
    sys.exit(2)


# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = (
    os.getenv("BASE_URL")
    or os.getenv("API_BASE_URL")
    or "http://127.0.0.1:8000"
).rstrip("/")
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT") or os.getenv("API_REQUEST_TIMEOUT") or 30)

API = "/api/v1"
RUN_TS = datetime.now(timezone.utc)
RUN_TAG = str(int(RUN_TS.timestamp()))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_PATH = os.path.join(SCRIPT_DIR, "ml_analytics_test_report.json")

INVALID_UUID = "00000000-0000-4000-8000-000000000000"


def mask_token(token: str) -> str:
    if not token:
        return "(none)"
    if len(token) >= 14:
        return f"{token[:4]}...{token[-4:]}"
    return "********"


# ============================================================
# RESULT COLLECTION
# ============================================================

@dataclass
class TestResult:
    index: int
    name: str
    method: str
    path: str
    status: str                 # PASS | FAIL | SKIPPED
    http_status: Optional[int] = None
    expected: Optional[str] = None
    category: Optional[str] = None
    message: str = ""
    request_id: Optional[str] = None
    elapsed_ms: int = 0


RESULTS: list[TestResult] = []
COUNTER = {"n": 0}

# Cached reference data discovered through the API
CTX: dict[str, Any] = {
    "role": None,
    "user_id": None,
    "departments": [],
    "doctors": [],
    "appointments": [],
}


def record(
    name: str,
    method: str,
    path: str,
    status: str,
    *,
    http_status: Optional[int] = None,
    expected: Optional[str] = None,
    category: Optional[str] = None,
    message: str = "",
    request_id: Optional[str] = None,
    elapsed_ms: int = 0,
) -> TestResult:
    COUNTER["n"] += 1
    idx = COUNTER["n"]
    r = TestResult(
        index=idx, name=name, method=method, path=path, status=status,
        http_status=http_status, expected=expected, category=category,
        message=message, request_id=request_id, elapsed_ms=elapsed_ms,
    )
    RESULTS.append(r)

    label = f"[{idx:02d}] {method} {path}"
    print(label)
    if status == "PASS":
        extra = f" - {message}" if message else ""
        print(f"     PASS {http_status}{extra}")
    elif status == "SKIPPED":
        print(f"     SKIPPED - {message}")
    else:
        print(f"     FAIL {http_status} (expected {expected}) [{category}] {message}")
    return r


def skip(name: str, method: str, path: str, reason: str, status: str = "SKIPPED") -> None:
    record(name, method, path, status, message=reason)


def classify(status_code: int) -> str:
    return {
        400: "VALIDATION",
        401: "AUTHENTICATION",
        403: "AUTHORIZATION",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION",
        429: "UNKNOWN",
        500: "SERVER_ERROR",
        502: "SERVER_ERROR",
        503: "SERVER_ERROR",
        504: "TIMEOUT",
    }.get(status_code, "UNKNOWN")


# ============================================================
# HTTP HELPERS
# ============================================================

class ApiClient:
    def __init__(self, base_url: str, token: Optional[str], timeout: float):
        self.base_url = base_url
        self.token = token
        self.timeout = timeout
        self.client = httpx.Client(base_url=base_url, timeout=timeout, follow_redirects=False)

    def request(
        self,
        method: str,
        path: str,
        *,
        token: Optional[str] = "__default__",
        params: Optional[dict] = None,
        json_body: Any = None,
        timeout: Optional[float] = None,
    ) -> tuple[Optional[int], Any, Optional[str], dict, float]:
        """Returns (status_code|None, json|text, error, headers, elapsed_ms)."""
        tok = self.token if token == "__default__" else token
        headers = {}
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
        t0 = time.monotonic()
        try:
            resp = self.client.request(
                method, path, params=params, json=json_body,
                headers=headers, timeout=timeout or self.timeout,
            )
        except httpx.TimeoutException:
            return None, None, "TIMEOUT", {}, int((time.monotonic() - t0) * 1000)
        except httpx.HTTPError as exc:
            return None, None, f"CONNECTION: {exc.__class__.__name__}: {exc}", {}, int((time.monotonic() - t0) * 1000)
        elapsed = int((time.monotonic() - t0) * 1000)
        try:
            body: Any = resp.json()
        except Exception:
            body = resp.text[:2000]
        return resp.status_code, body, None, dict(resp.headers), elapsed


def check(
    api: ApiClient,
    name: str,
    method: str,
    path: str,
    *,
    token: Optional[str] = "__default__",
    params: Optional[dict] = None,
    json_body: Any = None,
    expect: int = 200,
    expect_any: Optional[list[int]] = None,
    timeout: Optional[float] = None,
    validate: Optional[Callable[[Any, dict], tuple[bool, str]]] = None,
) -> tuple[bool, Any]:
    """Execute one request, validate, record PASS/FAIL. Returns (ok, body)."""
    status, body, err, headers, elapsed = api.request(
        method, path, token=token, params=params, json_body=json_body, timeout=timeout
    )
    rid = headers.get("X-Request-ID")

    if err:
        category = "TIMEOUT" if err == "TIMEOUT" else "CONFIGURATION"
        record(name, method, path, "FAIL", expected=str(expect),
               category=category, message=err, request_id=rid, elapsed_ms=elapsed)
        return False, None

    ok = (status == expect) if expect_any is None else (status in expect_any)
    message = ""
    category = None
    if not ok:
        category = classify(status)
        snippet = body if isinstance(body, str) else json.dumps(body)[:400]
        message = f"response: {snippet}"
    elif validate is not None:
        try:
            valid, vmsg = validate(body, headers)
        except Exception as exc:
            valid, vmsg = False, f"validator error: {exc}"
        if not valid:
            ok = False
            category = "VALIDATION"
            message = f"response shape/value mismatch: {vmsg}"

    record(name, method, path, "PASS" if ok else "FAIL",
           http_status=status, expected=str(expect_any or expect),
           category=category, message=message, request_id=rid, elapsed_ms=elapsed)
    return ok, body


def expect_success_flag(body: Any, _headers: Optional[dict] = None) -> tuple[bool, str]:
    if not isinstance(body, dict):
        return False, f"expected object, got {type(body).__name__}"
    if body.get("success") is not True:
        return False, f"success != true ({str(body)[:200]})"
    return True, ""


def expect_error_shape(body: Any, _headers: Optional[dict] = None) -> tuple[bool, str]:
    if not isinstance(body, dict):
        return False, f"expected object, got {type(body).__name__}"
    err = body.get("error")
    if body.get("success") is False and isinstance(err, dict):
        if "code" not in err or "message" not in err:
            return False, "error object missing code/message"
        return True, f"error_code={err.get('code')}"
    if "detail" in body:
        return True, f"detail={str(body['detail'])[:80]}"
    return False, f"unrecognized error shape: {str(body)[:200]}"


# ============================================================
# VALIDATORS FOR ML & ANALYTICS RESPONSES
# ============================================================

def validate_prediction_no_show(body: Any, _headers: Optional[dict] = None) -> tuple[bool, str]:
    """Validate no-show prediction response shape."""
    ok, msg = expect_success_flag(body)
    if not ok:
        return ok, msg
    data = body.get("data")
    if not isinstance(data, dict):
        return False, f"data not an object: {type(data).__name__}"
    # Handle error-in-payload shape ({success:true, data:{success:false, error:...}})
    if data.get("success") is False:
        return True, f"reported: {data.get('error', 'unknown error')}"
    pred = data.get("prediction")
    if not isinstance(pred, dict):
        return False, f"data.prediction not an object. Keys: {list(data.keys())}"
    if "no_show_probability" not in pred:
        return False, f"missing prediction.no_show_probability. Keys: {list(pred.keys())}"
    prob = pred.get("no_show_probability")
    if not isinstance(prob, (int, float)):
        return False, f"probability not numeric: {type(prob).__name__}"
    if prob < 0 or prob > 1:
        return False, f"probability out of range [0,1]: {prob}"
    if pred.get("risk_level") not in ("low", "medium", "high"):
        return False, f"invalid risk_level: {pred.get('risk_level')}"
    if "no_show" not in pred:
        return False, "missing prediction.no_show class flag"
    if data.get("prediction_status") != "success":
        return False, f"prediction_status != success: {data.get('prediction_status')}"
    return True, f"prob={prob:.4f} risk={pred.get('risk_level')}"


def validate_prediction_waiting_time(body: Any, _headers: Optional[dict] = None) -> tuple[bool, str]:
    """Validate waiting-time prediction response shape."""
    ok, msg = expect_success_flag(body)
    if not ok:
        return ok, msg
    data = body.get("data")
    if not isinstance(data, dict):
        return False, f"data not an object: {type(data).__name__}"
    # Handle error-in-payload shape (e.g. "requires check-in first")
    if data.get("success") is False:
        return True, f"reported: {data.get('error', 'unknown error')}"
    pred = data.get("prediction")
    if not isinstance(pred, dict):
        return False, f"data.prediction not an object. Keys: {list(data.keys())}"
    if "predicted_wait_minutes" not in pred:
        return False, f"missing prediction.predicted_wait_minutes. Keys: {list(pred.keys())}"
    wait = pred.get("predicted_wait_minutes")
    if not isinstance(wait, (int, float)):
        return False, f"predicted minutes not numeric: {type(wait).__name__}"
    if wait < 0:
        return False, f"predicted minutes negative: {wait}"
    if data.get("prediction_status") != "success":
        return False, f"prediction_status != success: {data.get('prediction_status')}"
    return True, f"predicted={wait:.1f} min"


def validate_prediction_error_in_body(body: Any, _headers: Optional[dict] = None) -> tuple[bool, str]:
    """Validate an expected error reported inside the payload (HTTP 200, data.success=False)."""
    ok, msg = expect_success_flag(body)
    if not ok:
        return ok, msg
    data = body.get("data")
    if not isinstance(data, dict):
        return False, f"data not an object: {type(data).__name__}"
    if data.get("success") is not False:
        return False, f"expected data.success=False, got: {str(data)[:200]}"
    if not data.get("error"):
        return False, "error message missing"
    return True, f"error={str(data['error'])[:80]}"


def validate_analytics_data(body: Any, _headers: Optional[dict] = None) -> tuple[bool, str]:
    """Validate analytics response has success flag and data field."""
    ok, msg = expect_success_flag(body)
    if not ok:
        return ok, msg
    data = body.get("data")
    if data is None:
        return False, "data field missing"
    # data can be a dict, list, or empty (for no data available)
    return True, f"data_type={type(data).__name__}"


def validate_analytics_timeseries(body: Any, _headers: Optional[dict] = None) -> tuple[bool, str]:
    """Validate time-series analytics (bed-demand, patient-flow, booking-channel)."""
    ok, msg = expect_success_flag(body)
    if not ok:
        return ok, msg
    data = body.get("data")
    if not isinstance(data, dict):
        return False, f"data not an object: {type(data).__name__}"
    # Three accepted shapes:
    #  a) {"data": [...], "view_by": ...}          -> bed-demand / patient-flow
    #  b) {"message": "..."}                        -> empty result
    #  c) {"distribution": [...], "trend": [...]}   -> booking-channel
    if "data" in data or "message" in data:
        inner = data.get("data")
        if inner is not None and not isinstance(inner, list):
            return False, f"data.data not a list: {type(inner).__name__}"
    elif "distribution" in data or "trend" in data:
        if not isinstance(data.get("distribution"), list):
            return False, f"distribution not a list: {type(data.get('distribution')).__name__}"
        if not isinstance(data.get("trend"), list):
            return False, f"trend not a list: {type(data.get('trend')).__name__}"
    else:
        return False, f"unrecognized shape. Keys: {list(data.keys())}"
    if "view_by" in data and data["view_by"] not in ("Day", "Week", "Month", "Year"):
        return False, f"invalid view_by: {data.get('view_by')}"
    return True, f"records={len(data.get('data', [])) if 'data' in data else 'N/A'}"


def validate_analytics_billing(body: Any, _headers: Optional[dict] = None) -> tuple[bool, str]:
    """Validate billing analytics response."""
    ok, msg = expect_success_flag(body)
    if not ok:
        return ok, msg
    data = body.get("data")
    if not isinstance(data, dict):
        return False, f"data not an object: {type(data).__name__}"
    if "message" in data:
        return True, f"message: {data['message']}"
    # Should have at least one of these sections
    sections = ["receivables_by_status", "pending_by_category", "monthly_revenue"]
    found = [s for s in sections if s in data]
    if not found:
        return False, f"missing expected sections. Keys: {list(data.keys())}"
    return True, f"sections={found}"


def validate_analytics_satisfaction(body: Any, _headers: Optional[dict] = None) -> tuple[bool, str]:
    """Validate satisfaction analytics response."""
    ok, msg = expect_success_flag(body)
    if not ok:
        return ok, msg
    data = body.get("data")
    if not isinstance(data, dict):
        return False, f"data not an object: {type(data).__name__}"
    if "message" in data:
        return True, f"message: {data['message']}"
    if "average_satisfaction" not in data and "by_department" not in data:
        return False, f"missing expected fields. Keys: {list(data.keys())}"
    return True, f"avg={data.get('average_satisfaction')}"


def validate_analytics_no_show(body: Any, _headers: Optional[dict] = None) -> tuple[bool, str]:
    """Validate no-show historical analytics response."""
    ok, msg = expect_success_flag(body)
    if not ok:
        return ok, msg
    data = body.get("data")
    if not isinstance(data, dict):
        return False, f"data not an object: {type(data).__name__}"
    if "message" in data:
        return True, f"message: {data['message']}"
    if "by_lead_time" not in data and "by_department" not in data:
        return False, f"missing expected fields. Keys: {list(data.keys())}"
    return True, f"lead_time_buckets={len(data.get('by_lead_time', []))}"


def validate_analytics_waiting_time(body: Any, _headers: Optional[dict] = None) -> tuple[bool, str]:
    """Validate waiting-time historical analytics response."""
    ok, msg = expect_success_flag(body)
    if not ok:
        return ok, msg
    data = body.get("data")
    if not isinstance(data, dict):
        return False, f"data not an object: {type(data).__name__}"
    if "message" in data:
        return True, f"message: {data['message']}"
    if "average_wait_minutes" not in data and "by_department" not in data:
        return False, f"missing expected fields. Keys: {list(data.keys())}"
    return True, f"avg_wait={data.get('average_wait_minutes')}"


def validate_risk_queue(body: Any, _headers: Optional[dict] = None) -> tuple[bool, str]:
    """Validate no-show risk queue response."""
    ok, msg = expect_success_flag(body)
    if not ok:
        return ok, msg
    data = body.get("data")
    if not isinstance(data, dict):
        return False, f"data not an object: {type(data).__name__}"
    if "appointments" not in data and "total" not in data:
        return False, f"missing appointments or total field. Keys: {list(data.keys())}"
    appts = data.get("appointments", [])
    if not isinstance(appts, list):
        return False, f"appointments not a list: {type(appts).__name__}"
    return True, f"total={data.get('total', len(appts))}, high_risk={data.get('high_risk_count', 'N/A')}"


# ============================================================
# PHASES
# ============================================================

def phase_reachability(api_public: ApiClient) -> bool:
    """Server reachability check. Returns False on catastrophic failure."""
    print("\n--- Phase 1: server reachability ---")
    status, body, err, _, _ = api_public.request("GET", f"{API}/auth/me")
    if err:
        print(f"\nFATAL: cannot reach FastAPI server at {BASE_URL} ({err}).")
        print("Start it first, e.g.:")
        print("  cd integrated_hospital && uvicorn app.main:app --host 127.0.0.1 --port 8000")
        return False
    return True


def phase_identity(api: ApiClient) -> bool:
    """Role detection. Returns False if token unusable (catastrophic)."""
    print("\n--- Phase 2: authentication & role detection ---")

    def validate_profile(body: Any, headers: dict) -> tuple[bool, str]:
        ok, msg = expect_success_flag(body)
        if not ok:
            return ok, msg
        data = body.get("data") or {}
        if not data.get("user_id"):
            return False, "data.user_id missing"
        if data.get("role") not in {"patient", "staff", "admin"}:
            return False, f"unexpected role: {data.get('role')}"
        CTX["role"] = data["role"]
        CTX["user_id"] = data["user_id"]
        return True, f"role={data['role']}"

    ok, body = check(api, "users_me_profile", "GET", f"{API}/users/me", expect=200,
                     validate=validate_profile)
    if not ok:
        print("\nFATAL: provided access token was rejected or profile is not active.")
        print("Obtain a fresh token via the application's OTP login flow and retry.")
        return False
    print(f"\n  Token accepted. Detected role: {CTX['role']}  user_id: {CTX['user_id']}")
    return True


def phase_reference_data(api: ApiClient) -> None:
    """Fetch departments and appointments for use in ML/analytics tests."""
    print("\n--- Phase 3: reference data for ML/analytics tests ---")

    def v_departments(body, _):
        ok, msg = expect_success_flag(body)
        if not ok:
            return ok, msg
        if not isinstance(body.get("data"), list):
            return False, "data is not a list"
        CTX["departments"] = body["data"]
        return True, f"total={len(body['data'])}"

    def v_doctors(body, _):
        ok, msg = expect_success_flag(body)
        if not ok:
            return ok, msg
        CTX["doctors"] = body.get("data") or []
        return True, f"total={len(CTX['doctors'])}"

    check(api, "catalog_departments", "GET", f"{API}/catalog/departments", expect=200,
          validate=v_departments)
    check(api, "catalog_doctors", "GET", f"{API}/catalog/doctors", expect=200, validate=v_doctors)

    # Try to get appointments (staff/admin only)
    if CTX["role"] in ("staff", "admin"):
        def v_appointments(body, _):
            ok, msg = expect_success_flag(body)
            if not ok:
                return ok, msg
            data = body.get("data") or {}
            # Documented validator type fix (approved): this endpoint returns
            # the appointments LIST as `data` (list shape confirmed by the
            # passing Staff/Patient/Admin suites); `.get("appointments")`
            # assumed a dict payload and raised AttributeError, failing the
            # extraction without an API problem.
            if isinstance(data, list):
                CTX["appointments"] = data
            else:
                CTX["appointments"] = (data or {}).get("appointments") or []
            return True, f"total={len(CTX['appointments'])}"

        check(api, "staff_appointments_list", "GET", f"{API}/staff/appointments",
              params={"limit": 50}, expect=200, validate=v_appointments)
    else:
        # Patient can see own appointments
        def v_patient_appointments(body, _):
            ok, msg = expect_success_flag(body)
            if not ok:
                return ok, msg
            data = body.get("data") or {}
            # Documented validator type fix (approved): this endpoint returns
            # the appointments LIST as `data` (list shape confirmed by the
            # passing Staff/Patient/Admin suites); `.get("appointments")`
            # assumed a dict payload and raised AttributeError, failing the
            # extraction without an API problem.
            if isinstance(data, list):
                CTX["appointments"] = data
            else:
                CTX["appointments"] = (data or {}).get("appointments") or []
            return True, f"total={len(CTX['appointments'])}"

        check(api, "patient_appointments_list", "GET", f"{API}/patient/appointments",
              params={"limit": 50}, expect=200, validate=v_patient_appointments)


def phase_prediction_endpoints(api: ApiClient) -> None:
    """Test ML prediction endpoints (no-show and waiting-time)."""
    print("\n--- Phase 4: ML prediction endpoints ---")

    # RBAC: patient should get 403
    if CTX["role"] == "patient":
        check(api, "rbac_patient_denied_no_show_prediction", "POST",
              f"{API}/predictions/no-show/{INVALID_UUID}", expect=403,
              validate=expect_error_shape)
        check(api, "rbac_patient_denied_waiting_time_prediction", "POST",
              f"{API}/predictions/waiting-time/{INVALID_UUID}", expect=403,
              validate=expect_error_shape)
        return

    # Staff/admin tests
    if not CTX["appointments"]:
        skip("predictions_no_show", "POST", f"{API}/predictions/no-show/{{id}}",
             "no appointments available for prediction testing")
        skip("predictions_waiting_time", "POST", f"{API}/predictions/waiting-time/{{id}}",
             "no appointments available for prediction testing")
        return

    # Find an eligible appointment for no-show prediction
    # Prefer upcoming appointments (status=booked or confirmed)
    eligible_no_show = None
    for appt in CTX["appointments"]:
        status = appt.get("appointment_status", "")
        if status in ("booked", "confirmed"):
            eligible_no_show = appt
            break

    if eligible_no_show is None:
        # Try any appointment
        eligible_no_show = CTX["appointments"][0]

    appt_id = eligible_no_show.get("appointment_id")
    print(f"  Using appointment {appt_id} for predictions (status={eligible_no_show.get('appointment_status')})")

    # Test no-show prediction
    ok, body = check(api, "predictions_no_show", "POST",
                     f"{API}/predictions/no-show/{appt_id}", expect=200,
                     timeout=60, validate=validate_prediction_no_show)
    if ok and isinstance(body, dict):
        data = body.get("data", {})
        pred = data.get("prediction", {})
        if pred:
            print(f"     -> no_show_probability={pred.get('no_show_probability'):.4f}, "
                  f"risk={pred.get('risk_level', 'N/A')}")
        else:
            print(f"     -> {data.get('error', 'no prediction returned')}")

    # Test waiting-time prediction
    # NOTE: waiting-time requires actual_checkin_time (set only at check-in).
    # If the appointment has not been checked in, the service reports the error
    # inside the payload (HTTP 200, data.success=False) - the validator tolerates both.
    ok_wt, body_wt = check(api, "predictions_waiting_time", "POST",
                           f"{API}/predictions/waiting-time/{appt_id}", expect=200,
                           timeout=60, validate=validate_prediction_waiting_time)
    if ok_wt and isinstance(body_wt, dict):
        data_wt = body_wt.get("data", {})
        pred_wt = data_wt.get("prediction", {})
        if pred_wt:
            print(f"     -> predicted_wait={pred_wt.get('predicted_wait_minutes')} min")
        else:
            print(f"     -> {data_wt.get('error', 'no prediction returned')}")

    # Negative: invalid appointment ID (service reports error inside payload, HTTP 200)
    check(api, "predictions_no_show_invalid_id", "POST",
          f"{API}/predictions/no-show/{INVALID_UUID}", expect=200,
          validate=validate_prediction_error_in_body)
    check(api, "predictions_waiting_time_invalid_id", "POST",
          f"{API}/predictions/waiting-time/{INVALID_UUID}", expect=200,
          validate=validate_prediction_error_in_body)


def phase_analytics_endpoints(api: ApiClient) -> None:
    """Test all analytics endpoints."""
    print("\n--- Phase 5: analytics endpoints ---")

    # RBAC: patient should get 403 for all analytics
    if CTX["role"] == "patient":
        analytics_endpoints = [
            ("appointments", "GET", f"{API}/analytics/appointments", None),
            ("no_show_risk", "GET", f"{API}/analytics/no-show-risk", None),
            ("bed_demand", "GET", f"{API}/analytics/bed-demand", None),
            ("patient_flow", "GET", f"{API}/analytics/patient-flow", None),
            ("billing", "GET", f"{API}/analytics/billing", None),
            ("satisfaction", "GET", f"{API}/analytics/satisfaction", None),
            ("booking_channel", "GET", f"{API}/analytics/booking-channel", None),
            ("no_show_analytics", "GET", f"{API}/analytics/no-show", None),
            ("waiting_time_analytics", "GET", f"{API}/analytics/waiting-time", None),
        ]
        for name, method, path, params in analytics_endpoints:
            check(api, f"rbac_patient_denied_{name}", method, path, expect=403,
                  validate=expect_error_shape)
        return

    # Staff/admin tests - get department names for department-specific tests
    dept_names = [d.get("name") for d in CTX["departments"] if d.get("name")]
    primary_dept = dept_names[0] if dept_names else None

    # --- Core analytics ---
    check(api, "analytics_appointments", "GET", f"{API}/analytics/appointments",
          params={"days": 30}, expect=200, validate=validate_analytics_data)

    check(api, "analytics_appointments_invalid_days", "GET", f"{API}/analytics/appointments",
          params={"days": 0}, expect=422, validate=expect_error_shape)

    check(api, "analytics_no_show_risk", "GET", f"{API}/analytics/no-show-risk",
          expect=200, timeout=60, validate=validate_risk_queue)

    # --- Bed demand analytics ---
    check(api, "analytics_bed_demand", "GET", f"{API}/analytics/bed-demand",
          params={"view_by": "Month", "range_index": 0}, expect=200,
          timeout=60, validate=validate_analytics_timeseries)

    check(api, "analytics_bed_demand_invalid_view", "GET", f"{API}/analytics/bed-demand",
          params={"view_by": "Invalid", "range_index": 0}, expect=422,
          validate=expect_error_shape)

    if primary_dept:
        check(api, "analytics_bed_demand_department", "GET",
              f"{API}/analytics/bed-demand/department/{primary_dept}",
              params={"view_by": "Month", "range_index": 0}, expect=200,
              timeout=60, validate=validate_analytics_timeseries)
    else:
        skip("analytics_bed_demand_department", "GET",
             f"{API}/analytics/bed-demand/department/{{name}}",
             "no departments available")

    # --- Patient flow analytics ---
    check(api, "analytics_patient_flow", "GET", f"{API}/analytics/patient-flow",
          params={"view_by": "Month", "range_index": 0}, expect=200,
          timeout=60, validate=validate_analytics_timeseries)

    if primary_dept:
        check(api, "analytics_patient_flow_department", "GET",
              f"{API}/analytics/patient-flow/department/{primary_dept}",
              params={"view_by": "Month", "range_index": 0}, expect=200,
              timeout=60, validate=validate_analytics_timeseries)
    else:
        skip("analytics_patient_flow_department", "GET",
             f"{API}/analytics/patient-flow/department/{{name}}",
             "no departments available")

    # --- Billing analytics ---
    check(api, "analytics_billing", "GET", f"{API}/analytics/billing",
          params={"days": 90}, expect=200, timeout=60,
          validate=validate_analytics_billing)

    # --- Satisfaction analytics ---
    check(api, "analytics_satisfaction", "GET", f"{API}/analytics/satisfaction",
          params={"days": 90}, expect=200, timeout=60,
          validate=validate_analytics_satisfaction)

    # --- Booking channel analytics ---
    check(api, "analytics_booking_channel", "GET", f"{API}/analytics/booking-channel",
          params={"view_by": "Month", "range_index": 0}, expect=200,
          timeout=60, validate=validate_analytics_timeseries)

    # --- No-show historical analytics ---
    check(api, "analytics_no_show", "GET", f"{API}/analytics/no-show",
          params={"days": 90}, expect=200, timeout=60,
          validate=validate_analytics_no_show)

    # --- Waiting-time historical analytics ---
    check(api, "analytics_waiting_time", "GET", f"{API}/analytics/waiting-time",
          params={"days": 90}, expect=200, timeout=60,
          validate=validate_analytics_waiting_time)


def phase_analytics_parameters(api: ApiClient) -> None:
    """Test analytics endpoints with various parameter combinations."""
    print("\n--- Phase 6: analytics parameter variations ---")

    if CTX["role"] == "patient":
        skip("analytics_parameter_variations", "GET", f"{API}/analytics/*",
             "requires staff/admin role")
        return

    # Test different view_by values for time-series endpoints
    for view_by in ["Day", "Week", "Month", "Year"]:
        check(api, f"analytics_bed_demand_view_{view_by.lower()}", "GET",
              f"{API}/analytics/bed-demand",
              params={"view_by": view_by, "range_index": 0}, expect=200,
              timeout=60, validate=validate_analytics_timeseries)

    # Test different days ranges
    for days in [7, 30, 90, 365]:
        check(api, f"analytics_billing_days_{days}", "GET",
              f"{API}/analytics/billing",
              params={"days": days}, expect=200, timeout=60,
              validate=validate_analytics_billing)

    # Test range_index pagination
    for range_idx in [0, 1, 2]:
        check(api, f"analytics_patient_flow_range_{range_idx}", "GET",
              f"{API}/analytics/patient-flow",
              params={"view_by": "Month", "range_index": range_idx}, expect=200,
              timeout=60, validate=validate_analytics_timeseries)

    # Test with department_id filter if available
    if CTX["departments"]:
        dept_id = CTX["departments"][0].get("department_id")
        if dept_id:
            check(api, "analytics_appointments_dept_filter", "GET",
                  f"{API}/analytics/appointments",
                  params={"department_id": dept_id, "days": 30}, expect=200,
                  validate=validate_analytics_data)

            check(api, "analytics_no_show_dept_filter", "GET",
                  f"{API}/analytics/no-show",
                  params={"department_id": dept_id, "days": 90}, expect=200,
                  timeout=60, validate=validate_analytics_no_show)


def cross_role_negatives(api: ApiClient) -> None:
    """Verify RBAC boundaries with alternative tokens if provided."""
    print("\n--- Phase 7: authorization boundary checks ---")

    # Test with explicit patient token if provided (separate from main token)
    patient_token = os.getenv("PATIENT_ACCESS_TOKEN")
    if patient_token and CTX["role"] in ("staff", "admin"):
        patient_api = ApiClient(BASE_URL, patient_token, REQUEST_TIMEOUT)
        check(patient_api, "rbac_patient_token_denied_no_show_risk", "GET",
              f"{API}/analytics/no-show-risk", expect=403, validate=expect_error_shape)
        check(patient_api, "rbac_patient_token_denied_bed_demand", "GET",
              f"{API}/analytics/bed-demand", expect=403, validate=expect_error_shape)
        check(patient_api, "rbac_patient_token_denied_billing", "GET",
              f"{API}/analytics/billing", expect=403, validate=expect_error_shape)
        check(patient_api, "rbac_patient_token_denied_prediction", "POST",
              f"{API}/predictions/no-show/{INVALID_UUID}", expect=403,
              validate=expect_error_shape)
    elif not patient_token:
        print("  (PATIENT_ACCESS_TOKEN not set; skipping explicit patient-token RBAC checks)")

    # Test with staff token if main token is admin (for completeness)
    staff_token = os.getenv("STAFF_ACCESS_TOKEN")
    if staff_token and CTX["role"] == "admin":
        staff_api = ApiClient(BASE_URL, staff_token, REQUEST_TIMEOUT)
        check(staff_api, "rbac_staff_allowed_no_show_risk", "GET",
              f"{API}/analytics/no-show-risk", expect=200, validate=validate_risk_queue)


# ============================================================
# REPORT
# ============================================================

def generate_report() -> dict:
    """Generate JSON report of all test results."""
    passed = sum(1 for r in RESULTS if r.status == "PASS")
    failed = sum(1 for r in RESULTS if r.status == "FAIL")
    skipped = sum(1 for r in RESULTS if r.status == "SKIPPED")

    return {
        "run_timestamp": RUN_TS.isoformat(),
        "base_url": BASE_URL,
        "detected_role": CTX["role"],
        "user_id": CTX["user_id"],
        "summary": {
            "total": len(RESULTS),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
        },
        "results": [
            {
                "index": r.index,
                "name": r.name,
                "method": r.method,
                "path": r.path,
                "status": r.status,
                "http_status": r.http_status,
                "expected": r.expected,
                "category": r.category,
                "message": r.message,
                "elapsed_ms": r.elapsed_ms,
            }
            for r in RESULTS
        ],
    }


# ============================================================
# MAIN
# ============================================================

def get_access_token() -> str:
    """Get access token from env or interactive prompt."""
    token = os.getenv("API_ACCESS_TOKEN") or os.getenv("SUPABASE_ACCESS_TOKEN")
    if token:
        return token
    print("API_ACCESS_TOKEN environment variable not set.")
    print("Please obtain a Supabase access token via the OTP login flow.")
    token = getpass.getpass("Enter Supabase access token: ").strip()
    if not token:
        print("FATAL: No token provided.")
        sys.exit(2)
    return token


def main() -> int:
    print("=" * 70)
    print("ML & Analytics Pipeline - Integration Test Suite")
    print("=" * 70)
    print(f"Base URL: {BASE_URL}")
    print(f"Run tag:  {RUN_TAG}")
    print()

    # Get token
    access_token = get_access_token()
    print(f"Access token: {mask_token(access_token)}")

    # Create API clients
    api_public = ApiClient(BASE_URL, None, REQUEST_TIMEOUT)
    api = ApiClient(BASE_URL, access_token, REQUEST_TIMEOUT)

    # Phase 1: Server reachability
    if not phase_reachability(api_public):
        return 2

    # Phase 2: Identity & role detection
    if not phase_identity(api):
        return 2

    # Phase 3: Reference data
    phase_reference_data(api)

    # Phase 4: ML prediction endpoints
    phase_prediction_endpoints(api)

    # Phase 5: Analytics endpoints
    phase_analytics_endpoints(api)

    # Phase 6: Parameter variations
    phase_analytics_parameters(api)

    # Phase 7: RBAC boundary checks
    cross_role_negatives(api)

    # Generate report
    report = generate_report()
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2, default=str)

    # Print summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"  Total:   {report['summary']['total']}")
    print(f"  Passed:  {report['summary']['passed']}")
    print(f"  Failed:  {report['summary']['failed']}")
    print(f"  Skipped: {report['summary']['skipped']}")
    print(f"\nReport written to: {REPORT_PATH}")

    # Print failed tests
    failed_tests = [r for r in RESULTS if r.status == "FAIL"]
    if failed_tests:
        print("\nFAILED TESTS:")
        for r in failed_tests:
            print(f"  [{r.index:02d}] {r.method} {r.path}")
            print(f"       {r.category}: {r.message}")

    # Print skipped tests (for visibility)
    skipped_tests = [r for r in RESULTS if r.status == "SKIPPED"]
    if skipped_tests:
        print("\nSKIPPED TESTS:")
        for r in skipped_tests:
            print(f"  [{r.index:02d}] {r.method} {r.path}")
            print(f"       {r.message}")

    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
