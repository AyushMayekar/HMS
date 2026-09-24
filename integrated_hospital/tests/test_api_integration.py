#!/usr/bin/env python3
"""
Integrated Hospital API - Integration Test Suite
=================================================

Tests the real running FastAPI server (Meridian Care Hospital API) over HTTP,
the same way Swagger UI does, using a developer-supplied Supabase access token
as the Bearer token.

Configuration (environment variables):
    BASE_URL / API_BASE_URL     default: http://127.0.0.1:8000
    API_ACCESS_TOKEN            Supabase access token (otherwise interactive prompt)
    REQUEST_TIMEOUT             seconds, default 30 (agent/LLM calls use 90)
    PATIENT_ACCESS_TOKEN        optional extra token (patient role) for cross-role runs
    STAFF_ACCESS_TOKEN          optional extra token (staff role)
    ADMIN_ACCESS_TOKEN          optional extra token (admin role)

Usage:
    API_ACCESS_TOKEN=<token> python integrated_hospital/tests/test_api_integration.py

Output:
    - Human readable PASS / FAIL / SKIPPED log
    - api_test_manifest.json   discovered API surface + test status
    - api_test_report.json     full machine-readable results + created record IDs

Exit codes:
    0 = all executed tests passed (skips allowed)
    1 = one or more unexpected failures
    2 = catastrophic setup failure (server unreachable / token rejected)

The access token is NEVER printed or written to any file (only masked).
Database persistence is NOT verified by this script; the developer verifies
created/updated records manually in Supabase using the IDs in the report.
"""
from __future__ import annotations

import getpass
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
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
AGENT_TIMEOUT = 90.0  # LLM calls can be slow

API = "/api/v1"
RUN_TS = datetime.now(timezone.utc)
RUN_TAG = str(int(RUN_TS.timestamp()))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = os.path.join(SCRIPT_DIR, "api_test_manifest.json")
REPORT_PATH = os.path.join(SCRIPT_DIR, "api_test_report.json")

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
    mutation: Optional[dict] = None
    request_id: Optional[str] = None
    elapsed_ms: int = 0


RESULTS: list[TestResult] = []
MUTATIONS: list[dict] = []
COUNTER = {"n": 0}

# Cached reference data discovered through the API
CTX: dict[str, Any] = {
    "role": None,
    "user_id": None,
    "email": None,
    "departments": [],
    "doctors": [],
    "slots": [],            # available slots with capacity
    "slots_by_doctor": {},
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
    mutation: Optional[dict] = None,
    request_id: Optional[str] = None,
    elapsed_ms: int = 0,
) -> TestResult:
    COUNTER["n"] += 1
    idx = COUNTER["n"]
    r = TestResult(
        index=idx, name=name, method=method, path=path, status=status,
        http_status=http_status, expected=expected, category=category,
        message=message, mutation=mutation, request_id=request_id,
        elapsed_ms=elapsed_ms,
    )
    RESULTS.append(r)
    if mutation:
        MUTATIONS.append(mutation)

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

    if ok and not message:
        message = ""

    record(name, method, path, "PASS" if ok else "FAIL",
           http_status=status, expected=str(expect_any or expect),
           category=category, message=message, request_id=rid, elapsed_ms=elapsed)
    return ok, body


def expect_success_flag(body: Any, _headers: Optional[dict] = None) -> tuple[bool, str]:
    """Validator: successful responses use {success: true, data: ...}."""
    if not isinstance(body, dict):
        return False, f"expected object, got {type(body).__name__}"
    if body.get("success") is not True:
        return False, f"success != true ({str(body)[:200]})"
    return True, ""


def expect_error_shape(body: Any, _headers: Optional[dict] = None) -> tuple[bool, str]:
    """Validator for expected error responses.
    Accepts AppException shape {success:false, error:{code,message}} or
    FastAPI HTTPException shape {detail: ...} (used by auth dependencies)."""
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
# TEST MANIFEST - full discovered API surface (59 endpoints)
# ============================================================

def build_manifest() -> list[dict]:
    """Endpoint inventory derived from integrated_hospital/app/api/*.py route definitions."""
    AUTH_ANY = "Bearer token (any active role)"
    AUTH_PATIENT = "Bearer token, role=patient"
    AUTH_STAFF = "Bearer token, role in {staff, admin}"
    AUTH_ADMIN = "Bearer token, role=admin"
    PUBLIC = "none"

    m = [
        # --- Authentication (public) ---
        dict(endpoint="POST /api/v1/auth/request-otp", method="POST", authentication=PUBLIC, roles="public",
             input_requirements="body {email}", expected_success_status=200,
             test_name="auth_request_otp_validation_only", execution_order=1, dependencies="",
             mutation=False, status="SKIPPED",
             note="Happy path sends real email OTP; only request validation (422) is exercised."),
        dict(endpoint="POST /api/v1/auth/verify-otp", method="POST", authentication=PUBLIC, roles="public",
             input_requirements="body {email, otp(6-8 digits)}", expected_success_status=200,
             test_name="auth_verify_otp_validation_only", execution_order=2, dependencies="",
             mutation=False, status="SKIPPED",
             note="Happy path requires a real emailed OTP; auth is manual by design. Only validation (422) exercised."),
        dict(endpoint="POST /api/v1/auth/signup", method="POST", authentication=PUBLIC, roles="public",
             input_requirements="body {full_name, email, phone(digits), date_of_birth, gender}", expected_success_status=200,
             test_name="auth_signup_validation_only", execution_order=3, dependencies="",
             mutation=False, status="SKIPPED",
             note="Happy path sends real signup OTP email and may create accounts; only validation (422) exercised."),
        dict(endpoint="POST /api/v1/auth/verify-signup-otp", method="POST", authentication=PUBLIC, roles="public",
             input_requirements="body {email, otp(6-8 digits)}", expected_success_status=200,
             test_name="auth_verify_signup_otp_validation_only", execution_order=4, dependencies="",
             mutation=False, status="SKIPPED",
             note="Happy path creates auth user + profile; requires real OTP. Only validation (422) exercised."),
        dict(endpoint="GET /api/v1/auth/me", method="GET", authentication=PUBLIC, roles="public",
             input_requirements="none (auth parameter is unused placeholder)", expected_success_status=200,
             test_name="auth_me_public_placeholder", execution_order=0, dependencies="",
             mutation=False, status="SKIPPED",
             note="Placeholder route with no authentication dependency; returns static message."),

        # --- Users ---
        dict(endpoint="GET /api/v1/users/me", method="GET", authentication=AUTH_ANY, roles="patient|staff|admin",
             input_requirements="Authorization header", expected_success_status=200,
             test_name="users_me_profile", execution_order=5, dependencies="valid access token",
             mutation=False, status="SKIPPED",
             note="Also used for negative auth tests (missing/invalid token -> 401) and role detection."),

        # --- AI Agent ---
        dict(endpoint="POST /api/v1/agent/chat", method="POST", authentication=AUTH_ANY, roles="patient|staff|admin",
             input_requirements="body {query: 1-2000 chars}; depends on LLM gateway availability",
             expected_success_status=200,
             test_name="agent_chat", execution_order=40, dependencies="LLM API (LLM_BASE_URL/LLM_API_KEY)",
             mutation=False, status="SKIPPED",
             note="Structural validation only: {success, response, request_id}. Model wording not asserted."),

        # --- RAG / Knowledge base ---
        dict(endpoint="GET /api/v1/rag/search", method="GET", authentication=AUTH_ANY, roles="patient|staff|admin",
             input_requirements="query (1-500 chars), top_k (1-20); depends on embedding API",
             expected_success_status=200,
             test_name="rag_search", execution_order=15, dependencies="embedding API",
             mutation=False, status="SKIPPED",
             note="Also validates 422 for missing query."),
        dict(endpoint="POST /api/v1/rag/reindex", method="POST", authentication=AUTH_ADMIN, roles="admin",
             input_requirements="Authorization header", expected_success_status=200,
             test_name="rag_reindex", execution_order=30, dependencies="knowledge_documents table, embedding API",
             mutation=True, status="SKIPPED",
             note="Rebuilds embeddings (document_chunks)."),


        # --- Catalog ---
        dict(endpoint="GET /api/v1/catalog/departments", method="GET", authentication=AUTH_ANY, roles="patient|staff|admin",
             input_requirements="none", expected_success_status=200,
             test_name="catalog_departments", execution_order=8, dependencies="",
             mutation=False, status="SKIPPED"),
        dict(endpoint="GET /api/v1/catalog/doctors", method="GET", authentication=AUTH_ANY, roles="patient|staff|admin",
             input_requirements="optional department_id", expected_success_status=200,
             test_name="catalog_doctors", execution_order=9, dependencies="",
             mutation=False, status="SKIPPED"),
        dict(endpoint="GET /api/v1/catalog/availability", method="GET", authentication=AUTH_ANY, roles="patient|staff|admin",
             input_requirements="optional department_id, doctor_id, slot_date", expected_success_status=200,
             test_name="catalog_availability", execution_order=10, dependencies="",
             mutation=False, status="SKIPPED",
             note="Source of real doctor_id/availability_id for booking; no availability-creation endpoint exists in the API."),

        # --- Departments ---
        dict(endpoint="GET /api/v1/departments", method="GET", authentication=AUTH_ANY, roles="patient|staff|admin",
             input_requirements="optional status, limit(1-200), offset", expected_success_status=200,
             test_name="departments_list", execution_order=11, dependencies="",
             mutation=False, status="SKIPPED"),
        dict(endpoint="GET /api/v1/departments/{department_id}", method="GET", authentication=AUTH_ANY, roles="patient|staff|admin",
             input_requirements="department_id UUID", expected_success_status=200,
             test_name="departments_get", execution_order=12, dependencies="existing department",
             mutation=False, status="SKIPPED",
             note="Also negative: random UUID -> 404 DEPARTMENT_NOT_FOUND."),
        dict(endpoint="POST /api/v1/departments", method="POST", authentication=AUTH_ADMIN, roles="admin",
             input_requirements="body {name, description, information, status?}", expected_success_status=201,
             test_name="departments_create", execution_order=21, dependencies="admin role",
             mutation=True, status="SKIPPED",
             note="Creates an obviously-labeled test department (public.departments). No DELETE endpoint exists; record left for manual cleanup."),
        dict(endpoint="PATCH /api/v1/departments/{department_id}", method="PATCH", authentication=AUTH_ADMIN, roles="admin",
             input_requirements="department_id UUID + partial body", expected_success_status=200,
             test_name="departments_update", execution_order=23, dependencies="departments_create",
             mutation=True, status="SKIPPED"),

        # --- Doctors ---
        dict(endpoint="GET /api/v1/doctors", method="GET", authentication=AUTH_ANY, roles="patient|staff|admin",
             input_requirements="optional department_id, status, limit, offset", expected_success_status=200,
             test_name="doctors_list", execution_order=13, dependencies="",
             mutation=False, status="SKIPPED"),
        dict(endpoint="GET /api/v1/doctors/{doctor_id}", method="GET", authentication=AUTH_ANY, roles="patient|staff|admin",
             input_requirements="doctor_id UUID", expected_success_status=200,
             test_name="doctors_get", execution_order=14, dependencies="existing doctor",
             mutation=False, status="SKIPPED",
             note="Also negative: random UUID -> 404 DOCTOR_NOT_FOUND."),
        dict(endpoint="POST /api/v1/doctors", method="POST", authentication=AUTH_ADMIN, roles="admin",
             input_requirements="body {department_id, full_name, specialization, experience_years(0-50), status?}",
             expected_success_status=201,
             test_name="doctors_create", execution_order=25, dependencies="admin role, department (created in run)",
             mutation=True, status="SKIPPED",
             note="Creates an obviously-labeled test doctor (public.doctors). No DELETE endpoint; record left for manual cleanup."),
        dict(endpoint="PATCH /api/v1/doctors/{doctor_id}", method="PATCH", authentication=AUTH_ADMIN, roles="admin",
             input_requirements="doctor_id UUID + partial body", expected_success_status=200,
             test_name="doctors_update", execution_order=27, dependencies="doctors_create",
             mutation=True, status="SKIPPED"),

        # --- Patient appointments ---
        dict(endpoint="POST /api/v1/patient/appointments", method="POST", authentication=AUTH_PATIENT, roles="patient",
             input_requirements="body {doctor_id, availability_id, reason?}; slot must belong to doctor, be available, have capacity",
             expected_success_status=201,
             test_name="patient_appointments_book", execution_order=16, dependencies="patient role, active doctor, available slot from /catalog/availability",
             mutation=True, status="SKIPPED",
             note="Also negatives: unknown doctor -> 404; slot/doctor mismatch -> 422."),
        dict(endpoint="GET /api/v1/patient/appointments", method="GET", authentication=AUTH_PATIENT, roles="patient",
             input_requirements="optional appointment_status, limit, offset", expected_success_status=200,
             test_name="patient_appointments_list", execution_order=17, dependencies="patient role",
             mutation=False, status="SKIPPED"),
        dict(endpoint="GET /api/v1/patient/appointments/{appointment_id}", method="GET", authentication=AUTH_PATIENT, roles="patient",
             input_requirements="own appointment_id UUID", expected_success_status=200,
             test_name="patient_appointments_get", execution_order=18, dependencies="booked appointment",
             mutation=False, status="SKIPPED",
             note="Also negative: random UUID -> 404."),
        dict(endpoint="PATCH /api/v1/patient/appointments/{appointment_id}/reschedule", method="PATCH",
             authentication=AUTH_PATIENT, roles="patient",
             input_requirements="body {new_availability_id}; new slot must belong to SAME doctor, available, capacity",
             expected_success_status=200,
             test_name="patient_appointments_reschedule", execution_order=29, dependencies="booked appointment + 2nd available slot for same doctor",
             mutation=True, status="SKIPPED",
             note="Also negatives: other doctor's slot -> 422; cancelled appointment -> 422."),
        dict(endpoint="POST /api/v1/patient/appointments/{appointment_id}/cancel", method="POST",
             authentication=AUTH_PATIENT, roles="patient",
             input_requirements="own appointment_id; optional body {reason}", expected_success_status=200,
             test_name="patient_appointments_cancel", execution_order=36, dependencies="appointment created in this run",
             mutation=True, status="SKIPPED",
             note="Application implements cancellation (status -> cancelled), not physical deletion."),

        # --- Patient payments ---
        dict(endpoint="POST /api/v1/patient/payments", method="POST", authentication=AUTH_PATIENT, roles="patient",
             input_requirements="body {appointment_id, amount>0, currency?, payment_method: upi|card|cash, insurance_used?, claim_required?}",
             expected_success_status=201,
             test_name="patient_payments_create", execution_order=19, dependencies="patient role, own non-cancelled appointment",
             mutation=True, status="SKIPPED",
             note="Payment outcome is randomly simulated (90% success); test asserts record creation, not success status."),
        dict(endpoint="GET /api/v1/patient/payments", method="GET", authentication=AUTH_PATIENT, roles="patient",
             input_requirements="limit, offset", expected_success_status=200,
             test_name="patient_payments_list", execution_order=20, dependencies="patient role",
             mutation=False, status="SKIPPED"),
        dict(endpoint="GET /api/v1/patient/payments/{payment_id}", method="GET", authentication=AUTH_PATIENT, roles="patient",
             input_requirements="own payment_id UUID", expected_success_status=200,
             test_name="patient_payments_get", execution_order=21, dependencies="payment created in this run",
             mutation=False, status="SKIPPED",
             note="Also negative: random UUID -> 404."),

        # --- Patient feedback ---
        dict(endpoint="POST /api/v1/patient/feedback", method="POST", authentication=AUTH_PATIENT, roles="patient",
             input_requirements="body {appointment_id, rating 1-5, comment?, feedback_channel?}; appointment must be COMPLETED and owned, no prior feedback",
             expected_success_status=201,
             test_name="patient_feedback_submit", execution_order=32, dependencies="completed appointment (staff lifecycle) + no duplicate",
             mutation=True, status="SKIPPED",
             note="If no completed appointment is available: negative test (booked appointment -> 422) runs instead."),
        dict(endpoint="GET /api/v1/patient/feedback", method="GET", authentication=AUTH_PATIENT, roles="patient",
             input_requirements="limit, offset", expected_success_status=200,
             test_name="patient_feedback_list", execution_order=33, dependencies="patient role",
             mutation=False, status="SKIPPED"),
        dict(endpoint="GET /api/v1/patient/feedback/{feedback_id}", method="GET", authentication=AUTH_PATIENT, roles="patient",
             input_requirements="own feedback_id UUID", expected_success_status=200,
             test_name="patient_feedback_get", execution_order=34, dependencies="existing feedback (else random-UUID 404 negative)",
             mutation=False, status="SKIPPED"),

        # --- Patient reminders ---
        dict(endpoint="GET /api/v1/patient/reminders", method="GET", authentication=AUTH_PATIENT, roles="patient",
             input_requirements="limit, offset", expected_success_status=200,
             test_name="patient_reminders_list", execution_order=31, dependencies="patient role",
             mutation=False, status="SKIPPED",
             note="Read-only for patients; reminder creation is staff-only."),

        # --- Patient admin requests ---
        dict(endpoint="POST /api/v1/patient/admin-requests", method="POST", authentication=AUTH_PATIENT, roles="patient",
             input_requirements="QUERY params: category, description (required); appointment_id?, payment_id? (optional, must be owned)",
             expected_success_status=201,
             test_name="patient_admin_requests_create", execution_order=22, dependencies="patient role",
             mutation=True, status="SKIPPED",
             note="Parameters are query parameters (no request body in route definition). Creates public.admin_requests row."),
        dict(endpoint="GET /api/v1/patient/admin-requests", method="GET", authentication=AUTH_PATIENT, roles="patient",
             input_requirements="optional status, limit, offset", expected_success_status=200,
             test_name="patient_admin_requests_list", execution_order=23, dependencies="patient role",
             mutation=False, status="SKIPPED"),
        dict(endpoint="GET /api/v1/patient/admin-requests/{request_id}", method="GET", authentication=AUTH_PATIENT, roles="patient",
             input_requirements="own request_id UUID", expected_success_status=200,
             test_name="patient_admin_requests_get", execution_order=24, dependencies="request created in this run",
             mutation=False, status="SKIPPED",
             note="Also negative: random UUID -> 404."),

        # --- Staff appointments ---
        dict(endpoint="GET /api/v1/staff/appointments", method="GET", authentication=AUTH_STAFF, roles="staff|admin",
             input_requirements="optional appointment_status, department_id, limit, offset", expected_success_status=200,
             test_name="staff_appointments_list", execution_order=25, dependencies="staff/admin role",
             mutation=False, status="SKIPPED"),
        dict(endpoint="GET /api/v1/staff/appointments/{appointment_id}", method="GET", authentication=AUTH_STAFF, roles="staff|admin",
             input_requirements="appointment_id UUID", expected_success_status=200,
             test_name="staff_appointments_get", execution_order=26, dependencies="existing appointment",
             mutation=False, status="SKIPPED",
             note="Also negative: random UUID -> 404."),
        dict(endpoint="POST /api/v1/staff/appointments/{appointment_id}/check-in", method="POST",
             authentication=AUTH_STAFF, roles="staff|admin",
             input_requirements="appointment with status=booked", expected_success_status=200,
             test_name="staff_appointments_check_in", execution_order=27, dependencies="a booked appointment",
             mutation=True, status="SKIPPED",
             note="MUTATES an existing appointment (sets actual_checkin_time). With a single staff token no appointment can be created in-run, so the soonest booked appointment found via the API is used; before/after is reported."),
        dict(endpoint="POST /api/v1/staff/appointments/{appointment_id}/service-start", method="POST",
             authentication=AUTH_STAFF, roles="staff|admin",
             input_requirements="checked-in appointment", expected_success_status=200,
             test_name="staff_appointments_service_start", execution_order=28, dependencies="check-in",
             mutation=True, status="SKIPPED"),
        dict(endpoint="POST /api/v1/staff/appointments/{appointment_id}/service-end", method="POST",
             authentication=AUTH_STAFF, roles="staff|admin",
             input_requirements="appointment with actual_service_start", expected_success_status=200,
             test_name="staff_appointments_service_end", execution_order=30, dependencies="service-start",
             mutation=True, status="SKIPPED",
             note="Sets appointment_status=completed and actual_wait_minutes."),
        dict(endpoint="POST /api/v1/staff/appointments/{appointment_id}/no-show", method="POST",
             authentication=AUTH_STAFF, roles="staff|admin",
             input_requirements="appointment with status=booked", expected_success_status=200,
             test_name="staff_appointments_no_show", execution_order=31, dependencies="second booked appointment (else negative transition test)",
             mutation=True, status="SKIPPED",
             note="Positive test needs a 2nd booked appointment (uses the one booked in-run when both patient+staff tokens are supplied); otherwise invalid-transition negative (completed -> 422) runs."),

        # --- Staff reminders ---
        dict(endpoint="POST /api/v1/staff/reminders/{appointment_id}", method="POST", authentication=AUTH_STAFF, roles="staff|admin",
             input_requirements="appointment_id + body {reminder_type: email|in_app, hours_before_appointment>=0, message 1-500}",
             expected_success_status=201,
             test_name="staff_reminders_create", execution_order=32, dependencies="existing appointment",
             mutation=True, status="SKIPPED",
             note="Also negative: random appointment UUID -> 404."),
        dict(endpoint="GET /api/v1/staff/reminders", method="GET", authentication=AUTH_STAFF, roles="staff|admin",
             input_requirements="limit, offset", expected_success_status=200,
             test_name="staff_reminders_list", execution_order=33, dependencies="staff/admin role",
             mutation=False, status="SKIPPED"),

        # --- Admin users ---
        dict(endpoint="GET /api/v1/admin/users", method="GET", authentication=AUTH_ADMIN, roles="admin",
             input_requirements="optional role, status, limit, offset", expected_success_status=200,
             test_name="admin_users_list", execution_order=34, dependencies="admin role",
             mutation=False, status="SKIPPED"),
        dict(endpoint="GET /api/v1/admin/users/{user_id}", method="GET", authentication=AUTH_ADMIN, roles="admin",
             input_requirements="user_id UUID", expected_success_status=200,
             test_name="admin_users_get", execution_order=35, dependencies="admin role, own user_id from /users/me",
             mutation=False, status="SKIPPED",
             note="Also negative: random UUID -> 404 (known suspect: service uses .single() which may surface 500 - exposed as FAIL if so)."),
        dict(endpoint="PATCH /api/v1/admin/users/{user_id}", method="PATCH", authentication=AUTH_ADMIN, roles="admin",
             input_requirements="user_id UUID + body {role?: patient|staff|admin, status?: active|inactive}; self-demotion blocked",
             expected_success_status=200,
             test_name="admin_users_update", execution_order=36, dependencies="admin role; uses idempotent no-op status=active on own profile",
             mutation=True, status="SKIPPED",
             note="Run with own user_id and current status to avoid altering other accounts."),
        dict(endpoint="POST /api/v1/admin/users", method="POST", authentication=AUTH_ADMIN, roles="admin",
             input_requirements="QUERY params: full_name, email, phone (required), role (default staff)",
             expected_success_status=201,
             test_name="admin_users_create", execution_order=37, dependencies="admin role, unique email",
             mutation=True, status="SKIPPED",
             note="Creates profile-only row in public.profiles (service documents that auth user is NOT created). No DELETE endpoint; identifiable test email left for manual cleanup."),

        # --- Analytics ---
        dict(endpoint="GET /api/v1/analytics/appointments", method="GET", authentication=AUTH_STAFF, roles="staff|admin",
             input_requirements="optional department_id, days 1-365", expected_success_status=200,
             test_name="analytics_appointments", execution_order=38, dependencies="staff/admin role, appointment data",
             mutation=False, status="SKIPPED",
             note="Also negative: days=0 -> 422."),
        dict(endpoint="GET /api/v1/analytics/no-show-risk", method="GET", authentication=AUTH_STAFF, roles="staff|admin",
             input_requirements="none", expected_success_status=200,
             test_name="analytics_no_show_risk", execution_order=39, dependencies="staff/admin role",
             mutation=False, status="SKIPPED"),

        # --- Predictions ---
        dict(endpoint="POST /api/v1/predictions/no-show/{appointment_id}", method="POST", authentication=AUTH_STAFF, roles="staff|admin",
             input_requirements="appointment_id UUID", expected_success_status=200,
             test_name="predictions_no_show", execution_order=39, dependencies="existing appointment; ML model optional (rule-based fallback)",
             mutation=True, status="SKIPPED",
             note="Writes public.prediction_logs row."),
        dict(endpoint="POST /api/v1/predictions/waiting-time/{appointment_id}", method="POST", authentication=AUTH_STAFF, roles="staff|admin",
             input_requirements="appointment_id with actual_checkin_time (check-in first)", expected_success_status=200,
             test_name="predictions_waiting_time", execution_order=29, dependencies="check-in (staff lifecycle)",
             mutation=True, status="SKIPPED",
             note="Writes public.prediction_logs row."),
    ]
    return m


MANIFEST = build_manifest()
MANIFEST_BY_TEST = {e["test_name"]: e for e in MANIFEST}


def sync_manifest_status() -> None:
    """Map executed results onto the manifest."""
    for r in RESULTS:
        entry = None
        for e in MANIFEST:
            if e["test_name"] == r.name:
                entry = e
                break
        if entry is None:
            # negative-only tests attach to their endpoint by suffix
            for e in MANIFEST:
                if r.name.startswith(e["test_name"].split("_")[0]):
                    pass
        else:
            if r.status == "FAIL":
                entry["status"] = "FAILED"
            elif r.status == "SKIPPED":
                entry["status"] = "SKIPPED"
            elif entry["status"] != "FAILED":
                entry["status"] = "TESTED"
    # Role-gated endpoints explicitly skipped get ROLE_REQUIRED
    for r in RESULTS:
        if r.status == "SKIPPED" and r.category == "ROLE_REQUIRED":
            for e in MANIFEST:
                if e["test_name"] == r.name:
                    e["status"] = "ROLE_REQUIRED"
    for e in MANIFEST:
        if e["status"] == "SKIPPED" and e.get("note") and "ROLE_REQUIRED" in e.get("note", ""):
            e["status"] = "ROLE_REQUIRED"


def role_skip_if_not(api: ApiClient, required_roles: set[str], name: str, method: str, path: str) -> bool:
    if CTX["role"] in required_roles:
        return False
    skip(name, method, path,
         f"requires role in {sorted(required_roles)}; provided token role='{CTX['role']}'",
         status="ROLE_REQUIRED")
    return True


# ============================================================
# PHASES
# ============================================================

def phase_reachability(api_public: ApiClient) -> bool:
    """Public endpoint + server reachability. Returns False on catastrophic failure."""
    print("\n--- Phase 1: server reachability & public auth endpoints ---")
    status, body, err, _, _ = api_public.request("GET", f"{API}/auth/me")
    if err:
        print(f"\nFATAL: cannot reach FastAPI server at {BASE_URL} ({err}).")
        print("Start it first, e.g.:")
        print("  cd integrated_hospital && uvicorn app.main:app --host 127.0.0.1 --port 8000")
        return False

    # validation-only tests (no real OTP emails are triggered)
    check(api_public, "auth_request_otp_validation_only", "POST", f"{API}/auth/request-otp",
          json_body={"email": "not-an-email"}, expect=422,
          validate=expect_error_shape)
    check(api_public, "auth_verify_otp_validation_only", "POST", f"{API}/auth/verify-otp",
          json_body={"email": "tester@example.com", "otp": "abcdef"}, expect=422,
          validate=expect_error_shape)
    check(api_public, "auth_signup_validation_only", "POST", f"{API}/auth/signup",
          json_body={"full_name": "", "email": "x", "phone": "abc", "date_of_birth": "", "gender": ""},
          expect=422, validate=expect_error_shape)
    check(api_public, "auth_verify_signup_otp_validation_only", "POST", f"{API}/auth/verify-signup-otp",
          json_body={"email": "x", "otp": "xyz"}, expect=422, validate=expect_error_shape)
    check(api_public, "auth_me_public_placeholder", "GET", f"{API}/auth/me", expect=200)
    return True


def phase_identity(api: ApiClient) -> bool:
    """Auth negatives + role detection. Returns False if token unusable (catastrophic)."""
    print("\n--- Phase 2: authentication checks & role detection ---")

    check(api, "users_me_missing_token", "GET", f"{API}/users/me", token=None, expect=401,
          validate=expect_error_shape)
    check(api, "users_me_invalid_token", "GET", f"{API}/users/me",
          token="invalid-token-for-negative-test", expect=401, validate=expect_error_shape)

    def validate_profile(body: Any, headers: dict) -> tuple[bool, str]:
        ok, msg = expect_success_flag(body)
        if not ok:
            return ok, msg
        data = body.get("data") or {}
        if not data.get("user_id"):
            return False, "data.user_id missing"
        if data.get("role") not in {"patient", "staff", "admin"}:
            return False, f"unexpected role: {data.get('role')}"
        if data.get("status") != "active":
            return False, f"profile status is {data.get('status')}, expected active"
        CTX["role"] = data["role"]
        CTX["user_id"] = data["user_id"]
        CTX["email"] = data.get("email")
        return True, f"role={data['role']}"

    ok, body = check(api, "users_me_profile", "GET", f"{API}/users/me", expect=200,
                     validate=validate_profile)
    if not ok:
        print("\nFATAL: provided access token was rejected or profile is not active.")
        print("Obtain a fresh token via the application's OTP login flow and retry.")
        return False
    print(f"\n  Token accepted. Detected role: {CTX['role']}  user_id: {CTX['user_id']}")
    return True


def phase_reference_reads(api: ApiClient) -> None:
    """Read-only reference data, cached for later phases. Any authenticated role."""
    print("\n--- Phase 3: reference/catalog reads (any role) ---")

    def v_departments(body, _):
        ok, msg = expect_success_flag(body)
        if not ok:
            return ok, msg
        if not isinstance(body.get("data"), list):
            return False, "data is not a list"
        CTX["departments"] = body["data"]
        return True, f"total={body.get('total')}"

    def v_doctors(body, _):
        ok, msg = expect_success_flag(body)
        if not ok:
            return ok, msg
        CTX["doctors"] = body.get("data") or []
        return True, f"total={body.get('total')}"

    def v_availability(body, _):
        ok, msg = expect_success_flag(body)
        if not ok:
            return ok, msg
        slots = body.get("data") or []
        active_doc_ids = {d.get("doctor_id") for d in CTX["doctors"]}
        usable = [
            s for s in slots
            if s.get("status") == "available"
            and (s.get("booked_count") or 0) < (s.get("slot_capacity") or 1)
            and (not active_doc_ids or s.get("doctor_id") in active_doc_ids)
        ]
        CTX["slots"] = usable
        by_doc: dict[str, list] = {}
        for s in usable:
            by_doc.setdefault(s["doctor_id"], []).append(s)
        CTX["slots_by_doctor"] = by_doc
        return True, f"available_slots={len(usable)} (of {len(slots)} returned)"

    check(api, "catalog_departments", "GET", f"{API}/catalog/departments", expect=200,
          validate=lambda b, h: (expect_success_flag(b) if isinstance(b.get("data"), list) else (False, "data not a list")))
    check(api, "catalog_doctors", "GET", f"{API}/catalog/doctors", expect=200, validate=v_doctors)

    # department-filtered variant (only if we have a department)
    if CTX["departments"]:
        check(api, "catalog_doctors_filtered", "GET", f"{API}/catalog/doctors",
              params={"department_id": CTX["departments"][0]["department_id"]}, expect=200)

    check(api, "catalog_availability", "GET", f"{API}/catalog/availability", expect=200,
          validate=v_availability)

    check(api, "departments_list", "GET", f"{API}/departments",
          params={"status": "active", "limit": 50}, expect=200, validate=v_departments)

    if CTX["departments"]:
        dept_id = CTX["departments"][0]["department_id"]
        check(api, "departments_get", "GET", f"{API}/departments/{dept_id}", expect=200,
              validate=lambda b, h: (True, "") if (isinstance(b, dict) and (b.get("data") or {}).get("department_id") == dept_id) else (False, "department_id mismatch"))
    else:
        skip("departments_get", "GET", f"{API}/departments/{{id}}", "no departments returned by list endpoint")
    check(api, "departments_get_not_found", "GET", f"{API}/departments/{INVALID_UUID}", expect=404,
          validate=expect_error_shape)

    check(api, "doctors_list", "GET", f"{API}/doctors", params={"limit": 50}, expect=200)
    if CTX["doctors"]:
        doc_id = CTX["doctors"][0]["doctor_id"]
        check(api, "doctors_get", "GET", f"{API}/doctors/{doc_id}", expect=200,
              validate=lambda b, h: (True, "") if (isinstance(b, dict) and (b.get("data") or {}).get("doctor_id") == doc_id) else (False, "doctor_id mismatch"))
    else:
        skip("doctors_get", "GET", f"{API}/doctors/{{id}}", "no doctors returned by list endpoint")
    check(api, "doctors_get_not_found", "GET", f"{API}/doctors/{INVALID_UUID}", expect=404,
          validate=expect_error_shape)

    # RAG search (needs embedding API; failure is a real integration result)
    check(api, "rag_search", "GET", f"{API}/rag/search",
          params={"query": "appointment booking", "top_k": 3}, expect=200, timeout=60,
          validate=lambda b, h: (expect_success_flag(b) if isinstance(b, dict) else (False, "not an object")))
    check(api, "rag_search_validation", "GET", f"{API}/rag/search", params={"query": ""}, expect=422,
          validate=expect_error_shape)


def cross_role_negatives(api: ApiClient) -> None:
    """Verify the provided token is REJECTED on endpoints of other roles."""
    print("\n--- Phase 9: authorization boundaries (403 checks) ---")
    role = CTX["role"]
    if role != "staff" and role != "admin":
        check(api, "rbac_patient_denied_staff_list", "GET", f"{API}/staff/appointments", expect=403,
              validate=expect_error_shape)
    if role != "admin":
        check(api, "rbac_denied_admin_users", "GET", f"{API}/admin/users", expect=403,
              validate=expect_error_shape)
        check(api, "rbac_denied_department_create", "POST", f"{API}/departments",
              json_body={"name": "x", "description": "x", "information": "x"}, expect=403,
              validate=expect_error_shape)
    if role != "patient":
        check(api, "rbac_denied_patient_payments", "GET", f"{API}/patient/payments", expect=403,
              validate=expect_error_shape)
    if role == "patient":
        check(api, "rbac_patient_denied_rag_reindex", "POST", f"{API}/rag/reindex", expect=403,
              validate=expect_error_shape)
    if role == "staff":
        check(api, "rbac_staff_denied_user_create", "POST", f"{API}/admin/users",
              params={"full_name": "x", "email": "x@example.com", "phone": "1234567890"}, expect=403,
              validate=expect_error_shape)


def phase_agent(api: ApiClient) -> None:
    print("\n--- Phase 8: AI agent endpoint ---")

    def v_chat(body, headers):
        if not isinstance(body, dict):
            return False, "not an object"
        if not isinstance(body.get("success"), bool):
            return False, "success is not bool"
        if not isinstance(body.get("response"), str) or not body.get("response"):
            return False, "response missing/empty"
        if not isinstance(body.get("request_id"), str) or not body.get("request_id"):
            return False, "request_id missing"
        return True, f"response_len={len(body['response'])}"

    check(api, "agent_chat", "POST", f"{API}/agent/chat",
          json_body={"query": "What are the hospital visiting hours?"}, expect=200,
          timeout=AGENT_TIMEOUT, validate=v_chat)
    check(api, "agent_chat_validation", "POST", f"{API}/agent/chat", json_body={"query": ""}, expect=422)


def section_admin(api: ApiClient, token: str) -> None:
    """Admin-only CRUD lifecycle. Runs only with an admin token."""
    if role_skip_if_not(api, {"admin"}, "departments_create", "POST", f"{API}/departments"):
        # still mark the rest of the admin block ROLE_REQUIRED
        for nm, meth, pth in [
            ("rag_reindex", "POST", f"{API}/rag/reindex"),
            ("doctors_create", "POST", f"{API}/doctors"),
            ("doctors_update", "PATCH", f"{API}/doctors/{{id}}"),
            ("departments_update", "PATCH", f"{API}/departments/{{id}}"),
            ("admin_users_list", "GET", f"{API}/admin/users"),
            ("admin_users_get", "GET", f"{API}/admin/users/{{user_id}}"),
            ("admin_users_update", "PATCH", f"{API}/admin/users/{{user_id}}"),
            ("admin_users_create", "POST", f"{API}/admin/users"),
        ]:
            skip(nm, meth, pth, f"requires admin role; provided token role='{CTX['role']}'", status="ROLE_REQUIRED")
        return

    print("\n--- Phase 4: admin CRUD lifecycle ---")

    dept_name = f"API Test Dept {RUN_TAG}"
    dept_payload = {
        "name": dept_name,
        "description": f"Created by API integration test {RUN_TAG}. Safe to delete.",
        "information": "Automated integration test record. Safe to delete from public.departments.",
        "status": "active",
    }
    created: dict[str, Any] = {}

    def v_dept_created(body, _):
        ok, msg = expect_success_flag(body)
        if not ok:
            return ok, msg
        d = body.get("data") or {}
        if d.get("name") != dept_payload["name"]:
            return False, "name mismatch"
        if d.get("status") != "active":
            return False, "status mismatch"
        created["department_id"] = d.get("department_id")
        return True, f"department_id={d.get('department_id')}"

    ok, _ = check(api, "departments_create", "POST", f"{API}/departments",
                  json_body=dept_payload, expect=201, token=token, validate=v_dept_created)
    if ok and created.get("department_id"):
        MUTATIONS.append({
            "resource": "department", "endpoint": "POST /api/v1/departments", "method": "POST",
            "id": created["department_id"], "supabase_table": "public.departments",
            "identifying_fields": {"name": dept_name},
            "note": "No DELETE endpoint exists; remove manually if desired.",
        })

    dept_id = created.get("department_id")
    if dept_id:
        check(api, "departments_get_created", "GET", f"{API}/departments/{dept_id}", token=token, expect=200,
              validate=lambda b, h: (True, "") if (b.get("data") or {}).get("name") == dept_name else (False, "name mismatch"))

        new_desc = f"Updated by API integration test {RUN_TAG}. Safe to delete."
        def v_dept_updated(body, _):
            okk, msg = expect_success_flag(body)
            if not okk:
                return okk, msg
            d = body.get("data") or {}
            if d.get("description") != new_desc:
                return False, "description not updated"
            return True, ""
        check(api, "departments_update", "PATCH", f"{API}/departments/{dept_id}",
              token=token, json_body={"description": new_desc}, expect=200, validate=v_dept_updated)
    else:
        skip("departments_get_created", "GET", f"{API}/departments/{{id}}", "department was not created")
        skip("departments_update", "PATCH", f"{API}/departments/{{id}}", "department was not created")

    # ---- doctors ----
    doctor_full_name = f"API Test Doctor {RUN_TAG}"
    if dept_id:
        doctor_payload = {
            "department_id": dept_id,
            "full_name": doctor_full_name,
            "specialization": "General Medicine",
            "experience_years": 5,
            "status": "active",
        }
        def v_doc_created(body, _):
            okk, msg = expect_success_flag(body)
            if not okk:
                return okk, msg
            d = body.get("data") or {}
            if d.get("full_name") != doctor_full_name:
                return False, "full_name mismatch"
            if d.get("department_id") != dept_id:
                return False, "department_id mismatch"
            created["doctor_id"] = d.get("doctor_id")
            return True, f"doctor_id={d.get('doctor_id')}"
        dok, _ = check(api, "doctors_create", "POST", f"{API}/doctors", token=token,
                       json_body=doctor_payload, expect=201, validate=v_doc_created)
        if dok and created.get("doctor_id"):
            MUTATIONS.append({
                "resource": "doctor", "endpoint": "POST /api/v1/doctors", "method": "POST",
                "id": created["doctor_id"], "supabase_table": "public.doctors",
                "identifying_fields": {"full_name": doctor_full_name, "department_id": dept_id},
                "note": "No DELETE endpoint exists; remove manually if desired.",
            })
        doc_id = created.get("doctor_id")
        if doc_id:
            check(api, "doctors_get_created", "GET", f"{API}/doctors/{doc_id}", token=token, expect=200,
                  validate=lambda b, h: (True, "") if (b.get("data") or {}).get("doctor_id") == doc_id else (False, "doctor_id mismatch"))
            new_spec = "General Medicine (API test updated)"
            def v_doc_updated(body, _):
                okk, msg = expect_success_flag(body)
                if not okk:
                    return okk, msg
                return ((body.get("data") or {}).get("specialization") == new_spec, "specialization not updated")
            check(api, "doctors_update", "PATCH", f"{API}/doctors/{doc_id}", token=token,
                  json_body={"specialization": new_spec, "experience_years": 6}, expect=200,
                  validate=v_doc_updated)
        else:
            skip("doctors_get_created", "GET", f"{API}/doctors/{{id}}", "doctor was not created")
            skip("doctors_update", "PATCH", f"{API}/doctors/{{id}}", "doctor was not created")
    else:
        skip("doctors_create", "POST", f"{API}/doctors", "department was not created")
        skip("doctors_get_created", "GET", f"{API}/doctors/{{id}}", "department was not created")
        skip("doctors_update", "PATCH", f"{API}/doctors/{{id}}", "department was not created")

    # ---- admin users ----
    def v_users_list(body, _):
        okk, msg = expect_success_flag(body)
        if not okk:
            return okk, msg
        if not isinstance(body.get("data"), list):
            return False, "data not a list"
        return True, f"total={body.get('total')}"
    check(api, "admin_users_list", "GET", f"{API}/admin/users", token=token,
          params={"limit": 10}, expect=200, validate=v_users_list)

    own_id = CTX["user_id"]
    check(api, "admin_users_get", "GET", f"{API}/admin/users/{own_id}", token=token, expect=200,
          validate=lambda b, h: (True, "") if (b.get("data") or {}).get("user_id") == own_id else (False, "user_id mismatch"))

    # negative: missing profile. NOTE: service uses PostgREST .single(), which raises
    # on zero rows -> likely surfaces as 500 instead of 404 (bug exposed here).
    check(api, "admin_users_get_not_found", "GET", f"{API}/admin/users/{INVALID_UUID}",
          token=token, expect=404,
          validate=expect_error_shape)

    # idempotent self-update (status set to its current value)
    check(api, "admin_users_update", "PATCH", f"{API}/admin/users/{own_id}", token=token,
          json_body={"status": "active"}, expect=200,
          validate=lambda b, h: (True, "") if (b.get("data") or {}).get("status") == "active" else (False, "status mismatch"))

    staff_email = f"api.test.staff.{RUN_TAG}@example.com"
    def v_user_created(body, _):
        okk, msg = expect_success_flag(body)
        if not okk:
            return okk, msg
        d = body.get("data") or {}
        if d.get("email") != staff_email:
            return False, "email mismatch"
        if d.get("role") != "staff":
            return False, "role mismatch"
        created["staff_user_id"] = d.get("user_id")
        return True, f"user_id={d.get('user_id')}"
    uok, _ = check(api, "admin_users_create", "POST", f"{API}/admin/users", token=token,
                   params={"full_name": f"API Test Staff {RUN_TAG}", "email": staff_email,
                           "phone": "9876543210", "role": "staff"},
                   expect=201, validate=v_user_created)
    if uok and created.get("staff_user_id"):
        MUTATIONS.append({
            "resource": "profile (staff user)", "endpoint": "POST /api/v1/admin/users", "method": "POST",
            "id": created["staff_user_id"], "supabase_table": "public.profiles",
            "identifying_fields": {"email": staff_email, "role": "staff"},
            "note": "Profile-only row (no auth user). Service has no deactivation/delete route; remove manually if desired.",
        })
        check(api, "admin_users_get_created", "GET", f"{API}/admin/users/{created['staff_user_id']}",
              token=token, expect=200,
              validate=lambda b, h: (True, "") if (b.get("data") or {}).get("email") == staff_email else (False, "email mismatch"))
    else:
        skip("admin_users_get_created", "GET", f"{API}/admin/users/{{user_id}}", "staff user was not created")

    # ---- knowledge base (admin KB management) ----
    # Uses a DRAFT document end-to-end so no embedding API call is required;
    # the draft lifecycle proves create/read/update/delete + index gating.
    kb_title = f"API Test KB {RUN_TAG}"
    kb_content = (
        f"Automated integration test knowledge document {RUN_TAG}. Safe to delete. "
        "This document stays in draft status, so no embedding or indexing runs."
    )
    kb_payload = {
        "title": kb_title,
        "category": "administrative",
        "content": kb_content,
        "status": "draft",
    }

    def v_kb_list(body, _):
        okk, msg = expect_success_flag(body)
        if not okk:
            return okk, msg
        if not isinstance(body.get("data"), list):
            return False, "data not a list"
        return True, f"total={body.get('total')}"


    # /knowledge/reindex wraps the SAME service function as /rag/reindex
    # (executed next); skipping avoids a second full embedding pass over the KB.

    # ---- RAG reindex (admin, mutates embeddings) ----
    # Validator corrected to expect_success_flag: the endpoint's envelope is
    # {success, data}; expect_error_shape could never pass on a successful run.
    check(api, "rag_reindex", "POST", f"{API}/rag/reindex", token=token, expect=200, timeout=120,
          validate=expect_success_flag)
    # record it as a mutation (id unknown - derived data)
    if RESULTS and RESULTS[-1].status == "PASS":
        MUTATIONS.append({
            "resource": "knowledge embeddings", "endpoint": "POST /api/v1/rag/reindex", "method": "POST",
            "id": "(derived)", "supabase_table": "public.document_chunks",
            "identifying_fields": {}, "note": "Embeddings rebuilt for all published documents.",
        })


def section_patient(api: ApiClient, token: str, extra_appointment_id: Optional[str] = None) -> None:
    """Patient-role workflow: book -> read -> pay -> admin request -> reschedule -> feedback -> cancel."""
    if role_skip_if_not(api, {"patient"}, "patient_appointments_book", "POST", f"{API}/patient/appointments"):
        for nm, meth, pth in [
            ("patient_appointments_list", "GET", f"{API}/patient/appointments"),
            ("patient_appointments_get", "GET", f"{API}/patient/appointments/{{id}}"),
            ("patient_appointments_reschedule", "PATCH", f"{API}/patient/appointments/{{id}}/reschedule"),
            ("patient_appointments_cancel", "POST", f"{API}/patient/appointments/{{id}}/cancel"),
            ("patient_payments_create", "POST", f"{API}/patient/payments"),
            ("patient_payments_list", "GET", f"{API}/patient/payments"),
            ("patient_payments_get", "GET", f"{API}/patient/payments/{{payment_id}}"),
            ("patient_feedback_submit", "POST", f"{API}/patient/feedback"),
            ("patient_feedback_list", "GET", f"{API}/patient/feedback"),
            ("patient_feedback_get", "GET", f"{API}/patient/feedback/{{feedback_id}}"),
            ("patient_reminders_list", "GET", f"{API}/patient/reminders"),
            ("patient_admin_requests_create", "POST", f"{API}/patient/admin-requests"),
            ("patient_admin_requests_list", "GET", f"{API}/patient/admin-requests"),
            ("patient_admin_requests_get", "GET", f"{API}/patient/admin-requests/{{request_id}}"),
        ]:
            skip(nm, meth, pth, f"requires patient role; provided token role='{CTX['role']}'", status="ROLE_REQUIRED")
        return

    print("\n--- Phase 5: patient workflow (book -> read -> pay -> request -> reschedule -> feedback -> cancel) ---")

    p = {"token": token}
    created: dict[str, Any] = {}

    # list first (also gives us existing completed appointments for feedback)
    def v_appt_list(body, _):
        okk, msg = expect_success_flag(body)
        if not okk:
            return okk, msg
        if not isinstance(body.get("data"), list):
            return False, "data not a list"
        created["existing_appointments"] = body["data"]
        return True, f"total={body.get('total')}"

    check(api, "patient_appointments_list", "GET", f"{API}/patient/appointments", expect=200,
          params={"limit": 100}, **p, validate=v_appt_list)

    # ---------- BOOK ----------
    booking_ok = False
    slots_by_doc = CTX.get("slots_by_doctor") or {}
    book_doc_id = book_slot = None
    # prefer a doctor with 2+ slots so reschedule can be tested
    for did, slots in sorted(slots_by_doc.items(), key=lambda kv: -len(kv[1])):
        if slots:
            book_doc_id, book_slot = did, slots[0]
            break

    if book_slot:
        reason = f"API integration test {RUN_TAG} - safe record"
        def v_booked(body, _):
            okk, msg = expect_success_flag(body)
            if not okk:
                return okk, msg

            d = body.get("data") or {}

            if not d.get("appointment_id"):
                return False, "appointment_id missing"

            if d.get("appointment_status") != "booked":
                return False, f"status={d.get('appointment_status')}, expected booked"

            if d.get("patient_id") != CTX["user_id"]:
                return False, "patient_id is not the token owner"

            expected_start = f"{book_slot['slot_date']}T{book_slot['start_time']}"

            actual_start = d.get("scheduled_start")

            try:
                from datetime import datetime

                expected_dt = datetime.fromisoformat(expected_start)
                actual_dt = datetime.fromisoformat(actual_start)

                if expected_dt.tzinfo is None and actual_dt.tzinfo is not None:
                    expected_dt = expected_dt.replace(tzinfo=actual_dt.tzinfo)

                if actual_dt != expected_dt:
                    return False, (
                        f"scheduled_start={actual_start}, "
                        f"expected {expected_start}"
                    )
            except (TypeError, ValueError) as exc:
                return False, (
                    f"invalid scheduled_start datetime: "
                    f"{actual_start!r} ({exc})"
                )

            created["appointment_id"] = d["appointment_id"]
            created["availability_id"] = book_slot["availability_id"]

            return True, f"appointment_id={d['appointment_id']}"
        booking_ok, _ = check(api, "patient_appointments_book", "POST", f"{API}/patient/appointments",
                              json_body={"doctor_id": book_doc_id,
                                         "availability_id": book_slot["availability_id"],
                                         "reason": reason},
                              expect=201, **p, validate=v_booked)
        if booking_ok:
            MUTATIONS.append({
                "resource": "appointment", "endpoint": "POST /api/v1/patient/appointments", "method": "POST",
                "id": created["appointment_id"], "supabase_table": "public.appointments",
                "identifying_fields": {
                    "doctor_id": book_doc_id,
                    "availability_id": book_slot["availability_id"],
                    "scheduled_start": f"{book_slot['slot_date']}T{book_slot['start_time']}",
                    "reason": reason,
                },
                "note": "Created by test run; ends this run with status=cancelled (cancel test).",
            })
            # slot booked_count was incremented
            MUTATIONS.append({
                "resource": "availability slot (booked_count++)", "endpoint": "POST /api/v1/patient/appointments",
                "method": "POST", "id": book_slot["availability_id"],
                "supabase_table": "public.doctor_availability",
                "identifying_fields": {"booked_count_before": book_slot.get("booked_count")},
                "note": "booked_count incremented by booking; cancel does NOT decrement it in current implementation.",
            })

        # negatives for booking
        check(api, "patient_appointments_book_unknown_doctor", "POST", f"{API}/patient/appointments",
              json_body={"doctor_id": INVALID_UUID, "availability_id": INVALID_UUID},
              expect=404, **p, validate=expect_error_shape)
        # slot/doctor mismatch (needs a second slot belonging to another doctor)
        other_slot = None
        for did, slots in slots_by_doc.items():
            if did != book_doc_id and slots:
                other_slot = slots[0]
                break
        if other_slot:
            check(api, "patient_appointments_book_slot_mismatch", "POST", f"{API}/patient/appointments",
                  json_body={"doctor_id": book_doc_id, "availability_id": other_slot["availability_id"]},
                  expect=422, **p, validate=expect_error_shape)
        else:
            skip("patient_appointments_book_slot_mismatch", "POST", f"{API}/patient/appointments",
                 "needs an available slot belonging to a different doctor")
        check(api, "patient_appointments_book_validation", "POST", f"{API}/patient/appointments",
              json_body={}, expect=422, **p, validate=expect_error_shape)
    else:
        skip("patient_appointments_book", "POST", f"{API}/patient/appointments",
             "DEPENDENCY: no available slot with capacity returned by GET /catalog/availability, "
             "and the API exposes no availability-creation endpoint (CreateAvailabilityRequest schema exists "
             "but no route uses it). Seed doctor_availability rows to enable booking tests.")
        skip("patient_appointments_book_unknown_doctor", "POST", f"{API}/patient/appointments", "booking prerequisite missing")
        skip("patient_appointments_book_slot_mismatch", "POST", f"{API}/patient/appointments", "booking prerequisite missing")
        skip("patient_appointments_book_validation", "POST", f"{API}/patient/appointments", "booking prerequisite missing")

    appt_id = created.get("appointment_id")

    # ---------- READ ----------
    if appt_id:
        check(api, "patient_appointments_list_after_book", "GET", f"{API}/patient/appointments",
              expect=200, params={"limit": 100}, **p,
              validate=lambda b, h: (True, "") if any(a.get("appointment_id") == appt_id for a in b.get("data", []))
              else (False, "created appointment not in list"))

        def v_appt_get(body, _):
            d = body.get("data") or {}
            if d.get("appointment_id") != appt_id:
                return False, "appointment_id mismatch"
            if "doctor" not in d or not d.get("doctor"):
                return False, "doctor enrichment missing"
            if "department" not in d or not d.get("department"):
                return False, "department enrichment missing"
            return True, ""
        check(api, "patient_appointments_get", "GET", f"{API}/patient/appointments/{appt_id}",
              expect=200, **p, validate=v_appt_get)
    else:
        existing = created.get("existing_appointments") or []
        if existing:
            appt_id = existing[0].get("appointment_id")
            created["read_target_appointment_id"] = appt_id
            check(api, "patient_appointments_get", "GET", f"{API}/patient/appointments/{appt_id}",
                  expect=200, **p,
                  validate=lambda b, h: (True, "") if (b.get("data") or {}).get("appointment_id") == appt_id
                  else (False, "appointment_id mismatch"))
        else:
            skip("patient_appointments_get", "GET", f"{API}/patient/appointments/{{id}}",
                 "no appointment available (booking skipped and patient has none)")
    check(api, "patient_appointments_get_not_found", "GET", f"{API}/patient/appointments/{INVALID_UUID}",
          expect=404, **p, validate=expect_error_shape)

    # ---------- PAYMENTS ----------
    pay_target = appt_id
    if pay_target:
        pay_payload = {
            "appointment_id": pay_target, "amount": 500.0, "currency": "INR",
            "payment_method": "upi", "insurance_used": False, "claim_required": False,
        }
        def v_payment(body, _):
            okk, msg = expect_success_flag(body)
            if not okk:
                return okk, msg
            d = body.get("data") or {}
            if not d.get("payment_id"):
                return False, "payment_id missing"
            if d.get("appointment_id") != pay_target:
                return False, "appointment_id mismatch"
            created["payment_id"] = d["payment_id"]
            created["payment_simulated_status"] = d.get("status")
            return True, f"payment_id={d['payment_id']} (simulated status={d.get('status')})"
        pok, _ = check(api, "patient_payments_create", "POST", f"{API}/patient/payments",
                       json_body=pay_payload, expect=201, **p, validate=v_payment)
        if pok:
            MUTATIONS.append({
                "resource": "payment", "endpoint": "POST /api/v1/patient/payments", "method": "POST",
                "id": created["payment_id"], "supabase_table": "public.payments",
                "identifying_fields": {"appointment_id": pay_target, "amount": 500.0,
                                       "simulated_status": created.get("payment_simulated_status")},
                "note": "Simulated payment; outcome is random (90% success).",
            })
        check(api, "patient_payments_list", "GET", f"{API}/patient/payments", expect=200, **p,
              validate=lambda b, h: (True, "") if any(
                  x.get("payment_id") == created.get("payment_id") for x in b.get("data", []))
              else (False, "created payment not in list"))
        if created.get("payment_id"):
            check(api, "patient_payments_get", "GET", f"{API}/patient/payments/{created['payment_id']}",
                  expect=200, **p,
                  validate=lambda b, h: (True, "") if (b.get("data") or {}).get("payment_id") == created["payment_id"]
                  else (False, "payment_id mismatch"))
        else:
            skip("patient_payments_get", "GET", f"{API}/patient/payments/{{payment_id}}", "payment was not created")
        # negative: payment for someone else's/nonexistent appointment
        check(api, "patient_payments_create_unknown_appointment", "POST", f"{API}/patient/payments",
              json_body={"appointment_id": INVALID_UUID, "amount": 100.0, "payment_method": "card"},
              expect=404, **p, validate=expect_error_shape)
        # validation negative
        check(api, "patient_payments_create_validation", "POST", f"{API}/patient/payments",
              json_body={"appointment_id": pay_target, "amount": -5, "payment_method": "bitcoin"},
              expect=422, **p, validate=expect_error_shape)
    else:
        skip("patient_payments_create", "POST", f"{API}/patient/payments",
             "no appointment available to pay for (booking skipped and patient has none)")
        skip("patient_payments_list", "GET", f"{API}/patient/payments", "payment prerequisite missing")
        skip("patient_payments_get", "GET", f"{API}/patient/payments/{{payment_id}}", "payment prerequisite missing")
        skip("patient_payments_create_unknown_appointment", "POST", f"{API}/patient/payments", "payment prerequisite missing")
        skip("patient_payments_create_validation", "POST", f"{API}/patient/payments", "payment prerequisite missing")

    # ---------- ADMIN REQUEST (query params, no body) ----------
    req_params: dict[str, Any] = {
        "category": "appointment_issue",
        "description": f"API integration test request {RUN_TAG}. Safe to resolve/close.",
    }
    if appt_id:
        req_params["appointment_id"] = appt_id

    def v_req_created(body, _):
        okk, msg = expect_success_flag(body)
        if not okk:
            return okk, msg
        d = body.get("data") or {}
        if not d.get("request_id"):
            return False, "request_id missing"
        if d.get("status") != "pending":
            return False, f"status={d.get('status')}, expected pending"
        created["admin_request_id"] = d["request_id"]
        return True, f"request_id={d['request_id']}"

    rok, _ = check(api, "patient_admin_requests_create", "POST", f"{API}/patient/admin-requests",
                   params=req_params, expect=201, **p, validate=v_req_created)
    if rok:
        MUTATIONS.append({
            "resource": "admin request", "endpoint": "POST /api/v1/patient/admin-requests", "method": "POST",
            "id": created["admin_request_id"], "supabase_table": "public.admin_requests",
            "identifying_fields": {"category": "appointment_issue",
                                   "description": req_params["description"],
                                   "appointment_id": appt_id},
            "note": "Starts in status=pending; no patient-side update/delete route exists.",
        })
    check(api, "patient_admin_requests_list", "GET", f"{API}/patient/admin-requests",
          expect=200, **p,
          validate=lambda b, h: (True, "") if any(
              x.get("request_id") == created.get("admin_request_id") for x in b.get("data", []))
          else (False, "created request not in list"))
    if created.get("admin_request_id"):
        check(api, "patient_admin_requests_get", "GET",
              f"{API}/patient/admin-requests/{created['admin_request_id']}",
              expect=200, **p,
              validate=lambda b, h: (True, "") if (b.get("data") or {}).get("request_id") == created["admin_request_id"]
              else (False, "request_id mismatch"))
    else:
        skip("patient_admin_requests_get", "GET", f"{API}/patient/admin-requests/{{request_id}}",
             "admin request was not created")
    check(api, "patient_admin_requests_get_not_found", "GET", f"{API}/patient/admin-requests/{INVALID_UUID}",
          expect=404, **p, validate=expect_error_shape)

    # ---------- REMINDERS (read-only for patients) ----------
    check(api, "patient_reminders_list", "GET", f"{API}/patient/reminders", expect=200, **p,
          validate=lambda b, h: (True, "") if isinstance(b.get("data"), list) else (False, "data not a list"))

    # ---------- RESCHEDULE ----------
    if booking_ok and appt_id:
        same_doc_slots = [s for s in (CTX.get("slots_by_doctor", {}).get(book_doc_id) or [])
                          if s["availability_id"] != book_slot["availability_id"]]
        if same_doc_slots:
            target_slot = same_doc_slots[0]
            new_start = f"{target_slot['slot_date']}T{target_slot['start_time']}"

            def v_rescheduled(body, _):
                okk, msg = expect_success_flag(body)
                if not okk:
                    return okk, msg

                d = body.get("data") or {}

                actual_start = d.get("scheduled_start")

                try:
                    from datetime import datetime

                    expected_dt = datetime.fromisoformat(new_start)
                    actual_dt = datetime.fromisoformat(actual_start)

                    # API returns timezone-aware ISO datetime (+00:00),
                    # while the test slot value may be timezone-naive.
                    if expected_dt.tzinfo is None and actual_dt.tzinfo is not None:
                        expected_dt = expected_dt.replace(tzinfo=actual_dt.tzinfo)

                    if actual_dt != expected_dt:
                        return False, (
                            f"scheduled_start={actual_start}, "
                            f"expected {new_start}"
                        )

                except (TypeError, ValueError) as exc:
                    return False, (
                        f"invalid scheduled_start datetime: "
                        f"{actual_start!r} ({exc})"
                    )

                if d.get("appointment_status") != "booked":
                    return False, "status not booked after reschedule"

                return True, f"new start={actual_start}"
            srok, _ = check(api, "patient_appointments_reschedule", "PATCH",
                            f"{API}/patient/appointments/{appt_id}/reschedule",
                            json_body={"new_availability_id": target_slot["availability_id"]},
                            expect=200, **p, validate=v_rescheduled)
            if srok:
                MUTATIONS.append({
                    "resource": "appointment (rescheduled)", "endpoint": "PATCH /api/v1/patient/appointments/{id}/reschedule",
                    "method": "PATCH", "id": appt_id, "supabase_table": "public.appointments",
                    "identifying_fields": {"new_availability_id": target_slot["availability_id"],
                                           "scheduled_start": new_start},
                    "note": "Slot booked_count incremented on the new slot.",
                })
        else:
            skip("patient_appointments_reschedule", "PATCH", f"{API}/patient/appointments/{{id}}/reschedule",
                 "DEPENDENCY: needs a 2nd available slot with capacity belonging to the SAME doctor "
                 f"(doctor_id={book_doc_id}); only one such slot exists")
    else:
        skip("patient_appointments_reschedule", "PATCH", f"{API}/patient/appointments/{{id}}/reschedule",
             "requires an appointment booked during this run")

    # ---------- FEEDBACK ----------
    existing_appts = created.get("existing_appointments") or []
    completed = [a for a in existing_appts if a.get("appointment_status") == "completed"]
    fb_list_ok, fb_body = check(api, "patient_feedback_list", "GET", f"{API}/patient/feedback",
                                expect=200, **p,
                                validate=lambda b, h: (True, "") if isinstance(b.get("data"), list)
                                else (False, "data not a list"))
    existing_fb = (fb_body or {}).get("data") or [] if fb_list_ok else []

    if completed:
        target_completed = completed[0]
        dup = any(f.get("appointment_id") == target_completed["appointment_id"] for f in existing_fb)
        if not dup:
            def v_fb(body, _):
                okk, msg = expect_success_flag(body)
                if not okk:
                    return okk, msg
                d = body.get("data") or {}
                if not d.get("feedback_id"):
                    return False, "feedback_id missing"
                if d.get("appointment_id") != target_completed["appointment_id"]:
                    return False, "appointment_id mismatch"
                if d.get("rating") != 5:
                    return False, "rating mismatch"
                created["feedback_id"] = d["feedback_id"]
                return True, f"feedback_id={d['feedback_id']}"
            fbok, _ = check(api, "patient_feedback_submit", "POST", f"{API}/patient/feedback",
                            json_body={"appointment_id": target_completed["appointment_id"], "rating": 5,
                                       "comment": f"API integration test {RUN_TAG}", "feedback_channel": "form"},
                            expect=201, **p, validate=v_fb)
            if fbok:
                MUTATIONS.append({
                    "resource": "feedback", "endpoint": "POST /api/v1/patient/feedback", "method": "POST",
                    "id": created["feedback_id"], "supabase_table": "public.feedback",
                    "identifying_fields": {"appointment_id": target_completed["appointment_id"], "rating": 5},
                    "note": "Also sets satisfaction_score on the appointment.",
                })
        else:
            # duplicate is a well-defined negative (409)
            check(api, "patient_feedback_submit_duplicate", "POST", f"{API}/patient/feedback",
                  json_body={"appointment_id": target_completed["appointment_id"], "rating": 4},
                  expect=409, **p, validate=expect_error_shape)
            skip("patient_feedback_submit", "POST", f"{API}/patient/feedback",
                 "completed appointment already has feedback; duplicate (409) negative tested instead")
    else:
        # No completed appointment: prove the documented constraint on our own booked appt
        if booking_ok and appt_id:
            check(api, "patient_feedback_submit_requires_completed", "POST", f"{API}/patient/feedback",
                  json_body={"appointment_id": appt_id, "rating": 5}, expect=422, **p,
                  validate=expect_error_shape)
        else:
            skip("patient_feedback_submit_requires_completed", "POST", f"{API}/patient/feedback",
                 "no appointment available to prove the completed-only constraint")
        skip("patient_feedback_submit", "POST", f"{API}/patient/feedback",
             "DEPENDENCY: requires a COMPLETED appointment owned by this patient. A patient token cannot complete "
             "appointments (staff endpoints required). Run with PATIENT_ACCESS_TOKEN + STAFF_ACCESS_TOKEN together, "
             "or use a patient account that has a completed appointment without prior feedback.")

    if existing_fb:
        check(api, "patient_feedback_get", "GET", f"{API}/patient/feedback/{existing_fb[0]['feedback_id']}",
              expect=200, **p,
              validate=lambda b, h: (True, "") if (b.get("data") or {}).get("feedback_id") == existing_fb[0]["feedback_id"]
              else (False, "feedback_id mismatch"))
    elif created.get("feedback_id"):
        check(api, "patient_feedback_get", "GET", f"{API}/patient/feedback/{created['feedback_id']}",
              expect=200, **p,
              validate=lambda b, h: (True, "") if (b.get("data") or {}).get("feedback_id") == created["feedback_id"]
              else (False, "feedback_id mismatch"))
    else:
        check(api, "patient_feedback_get_not_found", "GET", f"{API}/patient/feedback/{INVALID_UUID}",
              expect=404, **p, validate=expect_error_shape)
        skip("patient_feedback_get", "GET", f"{API}/patient/feedback/{{feedback_id}}",
             "no feedback row exists for this patient (random-UUID 404 negative ran instead)")

    # ---------- CANCEL (only the appointment created by this run) ----------
    if booking_ok and created.get("appointment_id"):
        cid = created["appointment_id"]
        def v_cancelled(body, _):
            okk, msg = expect_success_flag(body)
            if not okk:
                return okk, msg
            d = body.get("data") or {}
            if d.get("appointment_status") != "cancelled":
                return False, f"status={d.get('appointment_status')}, expected cancelled"
            return True, ""
        cok, _ = check(api, "patient_appointments_cancel", "POST", f"{API}/patient/appointments/{cid}/cancel",
                       json_body={"reason": f"API integration test cleanup {RUN_TAG}"},
                       expect=200, **p, validate=v_cancelled)
        if cok:
            MUTATIONS.append({
                "resource": "appointment (cancelled)", "endpoint": "POST /api/v1/patient/appointments/{id}/cancel",
                "method": "POST", "id": cid, "supabase_table": "public.appointments",
                "identifying_fields": {"appointment_status": "cancelled"},
                "note": "Final state of the test-created appointment after this run.",
            })
            check(api, "patient_appointments_get_after_cancel", "GET", f"{API}/patient/appointments/{cid}",
                  expect=200, **p,
                  validate=lambda b, h: (True, "") if (b.get("data") or {}).get("appointment_status") == "cancelled"
                  else (False, "status not cancelled"))
            # invalid transitions after cancel
            check(api, "patient_appointments_reschedule_after_cancel", "PATCH",
                  f"{API}/patient/appointments/{cid}/reschedule",
                  json_body={"new_availability_id": book_slot["availability_id"] if book_slot else INVALID_UUID},
                  expect=422, **p, validate=expect_error_shape)
            if created.get("payment_id") is None:
                check(api, "patient_payments_create_after_cancel", "POST", f"{API}/patient/payments",
                      json_body={"appointment_id": cid, "amount": 100.0, "payment_method": "cash"},
                      expect=422, **p, validate=expect_error_shape)
        else:
            skip("patient_appointments_get_after_cancel", "GET", f"{API}/patient/appointments/{{id}}", "cancel failed")
            skip("patient_appointments_reschedule_after_cancel", "PATCH",
                 f"{API}/patient/appointments/{{id}}/reschedule", "cancel failed")
    else:
        skip("patient_appointments_cancel", "POST", f"{API}/patient/appointments/{{id}}/cancel",
             "only appointments created by this run are cancelled (data safety); booking was skipped")
        skip("patient_appointments_get_after_cancel", "GET", f"{API}/patient/appointments/{{id}}", "cancel skipped")
        skip("patient_appointments_reschedule_after_cancel", "PATCH",
             f"{API}/patient/appointments/{{id}}/reschedule", "cancel skipped")


def section_staff(api: ApiClient, token: str, preferred_appointment_id: Optional[str] = None) -> None:
    """Staff/admin workflow: list/get + full visit lifecycle + predictions + reminders + analytics."""
    if role_skip_if_not(api, {"staff", "admin"}, "staff_appointments_list", "GET", f"{API}/staff/appointments"):
        for nm, meth, pth in [
            ("staff_appointments_get", "GET", f"{API}/staff/appointments/{{id}}"),
            ("staff_appointments_check_in", "POST", f"{API}/staff/appointments/{{id}}/check-in"),
            ("staff_appointments_service_start", "POST", f"{API}/staff/appointments/{{id}}/service-start"),
            ("staff_appointments_service_end", "POST", f"{API}/staff/appointments/{{id}}/service-end"),
            ("staff_appointments_no_show", "POST", f"{API}/staff/appointments/{{id}}/no-show"),
            ("staff_reminders_create", "POST", f"{API}/staff/reminders/{{appointment_id}}"),
            ("staff_reminders_list", "GET", f"{API}/staff/reminders"),
            ("analytics_appointments", "GET", f"{API}/analytics/appointments"),
            ("analytics_no_show_risk", "GET", f"{API}/analytics/no-show-risk"),
            ("predictions_no_show", "POST", f"{API}/predictions/no-show/{{appointment_id}}"),
            ("predictions_waiting_time", "POST", f"{API}/predictions/waiting-time/{{appointment_id}}"),
        ]:
            skip(nm, meth, pth, f"requires staff/admin role; provided token role='{CTX['role']}'", status="ROLE_REQUIRED")
        return

    print("\n--- Phase 6: staff workflow (visit lifecycle, predictions, reminders, analytics) ---")
    p = {"token": token}

    all_appts: list[dict] = []

    def v_staff_list(body, _):
        okk, msg = expect_success_flag(body)
        if not okk:
            return okk, msg
        if not isinstance(body.get("data"), list):
            return False, "data not a list"
        nonlocal all_appts
        all_appts = body["data"]
        return True, f"total={body.get('total')}"

    list_ok, _ = check(api, "staff_appointments_list", "GET", f"{API}/staff/appointments",
                       params={"limit": 100}, expect=200, **p, validate=v_staff_list)

    booked = sorted([a for a in all_appts if a.get("appointment_status") == "booked"],
                    key=lambda a: a.get("scheduled_start") or "")
    completed_or_cancelled = [a for a in all_appts
                              if a.get("appointment_status") in ("completed", "cancelled", "no_show")]

    # pick lifecycle target: prefer appointment created in this run (multi-token runs), else soonest booked
    lifecycle = None
    if preferred_appointment_id:
        lifecycle = next((a for a in all_appts if a.get("appointment_id") == preferred_appointment_id
                          and a.get("appointment_status") == "booked"), None)
    if lifecycle is None and booked:
        lifecycle = booked[0]

    if lifecycle:
        lid = lifecycle["appointment_id"]
        before_state = {
            "appointment_status": lifecycle.get("appointment_status"),
            "actual_checkin_time": lifecycle.get("actual_checkin_time"),
            "actual_service_start": lifecycle.get("actual_service_start"),
            "actual_service_end": lifecycle.get("actual_service_end"),
            "scheduled_start": lifecycle.get("scheduled_start"),
            "patient_id": lifecycle.get("patient_id"),
        }
        MUTATIONS.append({
            "resource": "appointment (staff lifecycle)", "endpoint": "staff check-in/service/no-show flow",
            "method": "POST", "id": lid, "supabase_table": "public.appointments",
            "identifying_fields": before_state,
            "note": "Existing appointment driven through check-in -> service-start -> service-end "
                    "(final status=completed). Verify before/after in Supabase.",
        })
    else:
        lid = None

    # GET single + 404 negative
    if lid:
        check(api, "staff_appointments_get", "GET", f"{API}/staff/appointments/{lid}", expect=200, **p,
              validate=lambda b, h: (True, "") if (b.get("data") or {}).get("appointment_id") == lid
              else (False, "appointment_id mismatch"))
    elif all_appts:
        lid_any = all_appts[0]["appointment_id"]
        check(api, "staff_appointments_get", "GET", f"{API}/staff/appointments/{lid_any}", expect=200, **p,
              validate=lambda b, h: (True, "") if (b.get("data") or {}).get("appointment_id") == lid_any
              else (False, "appointment_id mismatch"))
    else:
        skip("staff_appointments_get", "GET", f"{API}/staff/appointments/{{id}}", "no appointments exist")
    check(api, "staff_appointments_get_not_found", "GET", f"{API}/staff/appointments/{INVALID_UUID}",
          expect=404, **p, validate=expect_error_shape)

    # ---------- VISIT LIFECYCLE ----------
    lifecycle_ok = False
    if lid and lifecycle:
        def v_checkin(body, _):
            okk, msg = expect_success_flag(body)
            if not okk:
                return okk, msg
            d = body.get("data") or {}
            if not d.get("actual_checkin_time"):
                return False, "actual_checkin_time not set"
            return True, f"checkin={d.get('actual_checkin_time')}"
        iok, _ = check(api, "staff_appointments_check_in", "POST",
                       f"{API}/staff/appointments/{lid}/check-in", expect=200, **p, validate=v_checkin)

        if iok:
            # waiting-time prediction right after check-in (its documented eligibility point)
            def v_wt(body, _):
                if not isinstance(body, dict) or body.get("success") is not True:
                    return False, f"success != true ({body})"
                d = body.get("data") or {}
                if d.get("success") is False:
                    return False, f"service error: {d.get('error')}"
                if d.get("prediction_type") != "waiting_time":
                    return False, "prediction_type mismatch"
                if d.get("prediction_status") not in ("success", "failed"):
                    return False, f"prediction_status={d.get('prediction_status')}"
                if d.get("prediction_status") == "success" and "prediction" not in d:
                    return False, "prediction payload missing"
                return True, f"status={d.get('prediction_status')} model={d.get('model_version_id')}"
            wok, wbody = check(api, "predictions_waiting_time", "POST",
                               f"{API}/predictions/waiting-time/{lid}", expect=200, **p, validate=v_wt)
            if wok:
                pred_id = (wbody.get("data") or {}).get("prediction_id")
                MUTATIONS.append({
                    "resource": "prediction log", "endpoint": "POST /api/v1/predictions/waiting-time/{id}",
                    "method": "POST", "id": pred_id, "supabase_table": "public.prediction_logs",
                    "identifying_fields": {"entity_id": lid, "prediction_type": "waiting_time"},
                    "note": "",
                })

            def v_start(body, _):
                okk, msg = expect_success_flag(body)
                if not okk:
                    return okk, msg
                d = body.get("data") or {}
                if not d.get("actual_service_start"):
                    return False, "actual_service_start not set"
                return True, ""
            sok, _ = check(api, "staff_appointments_service_start", "POST",
                           f"{API}/staff/appointments/{lid}/service-start", expect=200, **p, validate=v_start)

            if sok:
                def v_end(body, _):
                    okk, msg = expect_success_flag(body)
                    if not okk:
                        return okk, msg
                    d = body.get("data") or {}
                    if d.get("appointment_status") != "completed":
                        return False, f"status={d.get('appointment_status')}, expected completed"
                    if d.get("actual_service_end") is None:
                        return False, "actual_service_end not set"
                    return True, f"wait_minutes={d.get('actual_wait_minutes')}"
                eok, _ = check(api, "staff_appointments_service_end", "POST",
                               f"{API}/staff/appointments/{lid}/service-end", expect=200, **p, validate=v_end)
                lifecycle_ok = eok
                if eok:
                    # invalid transition after completion
                    check(api, "staff_appointments_no_show_after_complete", "POST",
                          f"{API}/staff/appointments/{lid}/no-show", expect=422, **p,
                          validate=expect_error_shape)

                # no-show prediction works for any appointment
                def v_ns(body, _):
                    if not isinstance(body, dict) or body.get("success") is not True:
                        return False, f"success != true ({body})"
                    d = body.get("data") or {}
                    if d.get("success") is False:
                        return False, f"service error: {d.get('error')}"
                    if d.get("prediction_type") != "no_show":
                        return False, "prediction_type mismatch"
                    if d.get("prediction_status") not in ("success", "failed"):
                        return False, f"prediction_status={d.get('prediction_status')}"
                    if "prediction" not in d:
                        return False, "prediction payload missing"
                    return True, f"status={d.get('prediction_status')} model={d.get('model_version_id')}"
                nsk, nsbody = check(api, "predictions_no_show", "POST",
                                    f"{API}/predictions/no-show/{lid}", expect=200, **p, validate=v_ns)
                if nsk:
                    MUTATIONS.append({
                        "resource": "prediction log", "endpoint": "POST /api/v1/predictions/no-show/{id}",
                        "method": "POST", "id": (nsbody.get("data") or {}).get("prediction_id"),
                        "supabase_table": "public.prediction_logs",
                        "identifying_fields": {"entity_id": lid, "prediction_type": "no_show"},
                        "note": "",
                    })
            else:
                skip("staff_appointments_service_end", "POST", f"{API}/staff/appointments/{{id}}/service-end",
                     "service-start failed")
                skip("staff_appointments_no_show_after_complete", "POST",
                     f"{API}/staff/appointments/{{id}}/no-show", "service-start failed")
                skip("predictions_no_show", "POST", f"{API}/predictions/no-show/{{appointment_id}}",
                     "service-start failed")
        else:
            for nm, meth, pth in [
                ("predictions_waiting_time", "POST", f"{API}/predictions/waiting-time/{{appointment_id}}"),
                ("staff_appointments_service_start", "POST", f"{API}/staff/appointments/{{id}}/service-start"),
                ("staff_appointments_service_end", "POST", f"{API}/staff/appointments/{{id}}/service-end"),
                ("staff_appointments_no_show_after_complete", "POST", f"{API}/staff/appointments/{{id}}/no-show"),
                ("predictions_no_show", "POST", f"{API}/predictions/no-show/{{appointment_id}}"),
            ]:
                skip(nm, meth, pth, "check-in failed")
    else:
        skip("staff_appointments_check_in", "POST", f"{API}/staff/appointments/{{id}}/check-in",
             "DEPENDENCY: no 'booked' appointment exists to drive through the visit lifecycle "
             "(staff token cannot book appointments; patient endpoints require role=patient)")
        for nm, meth, pth in [
            ("predictions_waiting_time", "POST", f"{API}/predictions/waiting-time/{{appointment_id}}"),
            ("staff_appointments_service_start", "POST", f"{API}/staff/appointments/{{id}}/service-start"),
            ("staff_appointments_service_end", "POST", f"{API}/staff/appointments/{{id}}/service-end"),
            ("predictions_no_show", "POST", f"{API}/predictions/no-show/{{appointment_id}}"),
        ]:
            skip(nm, meth, pth, "no booked appointment available for lifecycle")

    # ---------- NO-SHOW positive on a second booked appointment ----------
    second_booked = next((a for a in booked if a.get("appointment_id") != lid), None)
    if second_booked:
        def v_ns_pos(body, _):
            okk, msg = expect_success_flag(body)
            if not okk:
                return okk, msg
            d = body.get("data") or {}
            if d.get("appointment_status") != "no_show":
                return False, f"status={d.get('appointment_status')}, expected no_show"
            if d.get("no_show_target") is not True:
                return False, "no_show_target not set"
            return True, ""
        nok, _ = check(api, "staff_appointments_no_show", "POST",
                       f"{API}/staff/appointments/{second_booked['appointment_id']}/no-show",
                       expect=200, **p, validate=v_ns_pos)
        if nok:
            MUTATIONS.append({
                "resource": "appointment (no_show)", "endpoint": "POST /api/v1/staff/appointments/{id}/no-show",
                "method": "POST", "id": second_booked["appointment_id"],
                "supabase_table": "public.appointments",
                "identifying_fields": {"appointment_status": "no_show"},
                "note": "Existing booked appointment was marked no-show to exercise the transition.",
            })
    elif lifecycle_ok:
        skip("staff_appointments_no_show", "POST", f"{API}/staff/appointments/{{id}}/no-show",
             "DEPENDENCY: needs a SECOND 'booked' appointment (the only one found was consumed by the "
             "check-in -> completed lifecycle). Invalid-transition negative ran instead.")
    else:
        # at minimum test the invalid-transition negative on a non-booked appointment
        if completed_or_cancelled:
            tgt = completed_or_cancelled[0]
            check(api, "staff_appointments_no_show_invalid_state", "POST",
                  f"{API}/staff/appointments/{tgt['appointment_id']}/no-show", expect=422, **p,
                  validate=expect_error_shape)
        skip("staff_appointments_no_show", "POST", f"{API}/staff/appointments/{{id}}/no-show",
             "DEPENDENCY: no second 'booked' appointment available for the positive no-show transition")

    # ---------- REMINDERS ----------
    reminder_target = lid or (all_appts[0]["appointment_id"] if all_appts else None)

    if reminder_target:
        reminder_id = None

        def v_rem(body, _):
            nonlocal_reminder = None

            okk, msg = expect_success_flag(body)
            if not okk:
                return okk, msg

            d = body.get("data") or {}

            if not d.get("reminder_id"):
                return False, "reminder_id missing"

            if d.get("appointment_id") != reminder_target:
                return False, "appointment_id mismatch"

            if d.get("status") != "sent":
                return False, f"status={d.get('status')}"

            return True, f"reminder_id={d['reminder_id']}"

        remok, _ = check(
            api,
            "staff_reminders_create",
            "POST",
            f"{API}/staff/reminders/{reminder_target}",
            json_body={
                "reminder_type": "in_app",
                "hours_before_appointment": 24,
                "message": f"API integration test reminder {RUN_TAG}",
            },
            expect=201,
            **p,
            validate=v_rem,
        )

        if remok:
            # Extract the ID from the actual response after validation.
            # This avoids relying on the undefined `created` dictionary.
            reminder_response = api.last_response_json if hasattr(api, "last_response_json") else None

            if isinstance(reminder_response, dict):
                reminder_data = reminder_response.get("data") or {}
                reminder_id = reminder_data.get("reminder_id")

            if reminder_id:
                MUTATIONS.append({
                    "resource": "reminder",
                    "endpoint": "POST /api/v1/staff/reminders/{appointment_id}",
                    "method": "POST",
                    "id": reminder_id,
                    "supabase_table": "public.reminders",
                    "identifying_fields": {
                        "appointment_id": reminder_target
                    },
                    "note": "Also sets reminder_sent=true on the appointment.",
                })

        check(
            api,
            "staff_reminders_create_unknown_appointment",
            "POST",
            f"{API}/staff/reminders/{INVALID_UUID}",
            json_body={"message": "test"},
            expect=404,
            **p,
            validate=expect_error_shape,
        )

    else:
        skip(
            "staff_reminders_create",
            "POST",
            f"{API}/staff/reminders/{{appointment_id}}",
            "DEPENDENCY: no appointment exists to attach the reminder to",
        )

        skip(
            "staff_reminders_create_unknown_appointment",
            "POST",
            f"{API}/staff/reminders/{{appointment_id}}",
            "no appointment exists",
        )


    def v_rem_list(body, _):
        okk, msg = expect_success_flag(body)
        if not okk:
            return okk, msg

        data = body.get("data")

        if not isinstance(data, list):
            return False, f"data not a list: {type(data).__name__}"

        if reminder_id and not any(
            r.get("reminder_id") == reminder_id
            for r in data
            if isinstance(r, dict)
        ):
            return False, "created reminder not in list"

        return True, f"total={body.get('total')}"


    check(
        api,
        "staff_reminders_list",
        "GET",
        f"{API}/staff/reminders",
        params={"limit": 100},
        expect=200,
        **p,
        validate=v_rem_list,
    )

    # ---------- ANALYTICS ----------
    def v_analytics(body, _):
        okk, msg = expect_success_flag(body)
        if not okk:
            return okk, msg
        d = body.get("data")
        if not isinstance(d, dict):
            return False, "data not an object"
        if "total_appointments" not in d and "total" not in d and "status_counts" not in d:
            # shape is implementation-defined; require it be a non-empty dict of KPIs
            if not d:
                return False, "empty analytics payload"
        return True, f"keys={sorted(list(d.keys()))[:6]}"
    check(api, "analytics_appointments", "GET", f"{API}/analytics/appointments",
          params={"days": 30}, expect=200, **p, validate=v_analytics)
    check(api, "analytics_appointments_department", "GET", f"{API}/analytics/appointments",
          params={"days": 7, **({"department_id": all_appts[0]["department_id"]}
                                if all_appts and all_appts[0].get("department_id") else {})},
          expect=200, **p)
    check(api, "analytics_appointments_validation", "GET", f"{API}/analytics/appointments",
          params={"days": 0}, expect=422, **p, validate=expect_error_shape)

    def v_risk(body, _):
        okk, msg = expect_success_flag(body)
        if not okk:
            return okk, msg

        data = body.get("data")

        if isinstance(data, list):
            return True, f"queue_size={len(data)}"

        if isinstance(data, dict):
            if not data:
                return False, "data is an empty object"

            return True, f"keys={sorted(list(data.keys()))[:6]}"

        return False, f"unexpected data type: {type(data).__name__}"


    check(
        api,
        "analytics_no_show_risk",
        "GET",
        f"{API}/analytics/no-show-risk",
        expect=200,
        **p,
        validate=v_risk,
    )
    check(api, "analytics_no_show_risk", "GET", f"{API}/analytics/no-show-risk", expect=200, **p,
          validate=v_risk)

    # no-show prediction fallback (if lifecycle never ran)
    if not any(r.name == "predictions_no_show" and r.status != "SKIPPED" for r in RESULTS):
        if all_appts:
            check(api, "predictions_no_show", "POST",
                  f"{API}/predictions/no-show/{all_appts[0]['appointment_id']}",
                  expect=200, **p,
                  validate=lambda b, h: (True, "") if (isinstance(b, dict) and b.get("success") is True
                                                       and (b.get("data") or {}).get("prediction_type") == "no_show")
                  else (False, "unexpected prediction payload"))
        else:
            skip("predictions_no_show", "POST", f"{API}/predictions/no-show/{{appointment_id}}",
                 "no appointment exists")


# ============================================================
# REPORTING
# ============================================================

def write_manifest() -> None:
    sync_manifest_status()
    payload = {
        "generated_at": RUN_TS.isoformat(),
        "base_url": BASE_URL,
        "detected_role": CTX.get("role"),
        "endpoint_count": len(MANIFEST),
        "endpoints": MANIFEST,
    }
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def write_report(started_at: datetime, token: str, catastrophic: bool = False) -> dict:
    passed = sum(1 for r in RESULTS if r.status == "PASS")
    failed = sum(1 for r in RESULTS if r.status == "FAIL")
    skipped = sum(1 for r in RESULTS if r.status == "SKIPPED")
    report = {
        "suite": "Integrated Hospital API integration tests",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "started_at": started_at.isoformat(),
        "base_url": BASE_URL,
        "authentication": {
            "method": "Bearer (Supabase access token)",
            "token_masked": mask_token(token),
            "detected_role": CTX.get("role"),
            "user_id": CTX.get("user_id"),
            "email": CTX.get("email"),
        },
        "summary": {"pass": passed, "fail": failed, "skipped": skipped, "total": len(RESULTS)},
        "catastrophic_failure": catastrophic,
        "mutations_to_verify_in_supabase": MUTATIONS,
        "results": [asdict(r) for r in RESULTS],
        "notes": [
            "The full access token is intentionally not stored anywhere in this report.",
            "Database persistence is NOT verified by this script; verify the listed IDs manually in Supabase.",
        ],
    }
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    return report


def print_summary(report: dict) -> None:
    s = report["summary"]
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"PASS:    {s['pass']}")
    print(f"FAIL:    {s['fail']}")
    print(f"SKIPPED: {s['skipped']}")
    print(f"TOTAL:   {s['total']}")
    print("=" * 60)

    if MUTATIONS:
        print()
        print("RECORDS TO VERIFY MANUALLY IN SUPABASE")
        print("-" * 60)
        for m in MUTATIONS:
            ident = ", ".join(f"{k}={v}" for k, v in (m.get("identifying_fields") or {}).items())
            print(f"  [{m['resource']}] id={m.get('id')}")
            print(f"      table: {m.get('supabase_table')}  endpoint: {m.get('endpoint')}")
            if ident:
                print(f"      fields: {ident}")
            if m.get("note"):
                print(f"      note: {m['note']}")

    failures = [r for r in RESULTS if r.status == "FAIL"]
    if failures:
        print()
        print("FAILURES")
        print("-" * 60)
        for r in failures:
            print(f"  [{r.index:02d}] {r.method} {r.path}")
            print(f"       expected={r.expected} actual={r.http_status} category={r.category}")
            print(f"       {r.message[:300]}")

    role_skips = [r for r in RESULTS if r.status == "SKIPPED" and r.category == "ROLE_REQUIRED"]
    if role_skips:
        print()
        print(f"ROLE-DEPENDENT SKIPS ({len(role_skips)}) - provide a matching token to run these:")
        print("-" * 60)
        for r in role_skips:
            print(f"  {r.method} {r.path} - {r.message}")

    dep_skips = [r for r in RESULTS if r.status == "SKIPPED" and r.category != "ROLE_REQUIRED"]
    if dep_skips:
        print()
        print(f"OTHER SKIPS ({len(dep_skips)})")
        print("-" * 60)
        for r in dep_skips:
            print(f"  {r.method} {r.path}")
            print(f"      {r.message[:240]}")

    print()
    print(f"Manifest: {MANIFEST_PATH}")
    print(f"Report:   {REPORT_PATH}")


# ============================================================
# MAIN
# ============================================================

def resolve_token() -> Optional[str]:
    token = os.getenv("API_ACCESS_TOKEN") or os.getenv("ACCESS_TOKEN")
    if token:
        return token.strip()
    if not sys.stdin.isatty():
        print("FATAL: no token. Set API_ACCESS_TOKEN=<token> when running non-interactively.")
        return None
    print("No API_ACCESS_TOKEN found. Paste the Supabase access token below.")
    print("(input is hidden; the token is never printed or saved)")
    try:
        token = getpass.getpass("Access token: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    return token or None


def main() -> int:
    started = datetime.now(timezone.utc)
    print("=" * 60)
    print("INTEGRATED HOSPITAL API TEST")
    print("=" * 60)
    print(f"Base URL: {BASE_URL}")

    token = resolve_token()
    if not token:
        print("FATAL: no access token provided.")
        return 2
    print("Authentication: PROVIDED")
    print(f"Token: {mask_token(token)}")
    print(f"Timeout: {REQUEST_TIMEOUT:.0f}s (agent calls: {AGENT_TIMEOUT:.0f}s)")

    api = ApiClient(BASE_URL, token, REQUEST_TIMEOUT)
    public_api = ApiClient(BASE_URL, None, REQUEST_TIMEOUT)

    catastrophic = False
    try:
        if not phase_reachability(public_api):
            write_manifest()
            write_report(started, token, catastrophic=True)
            return 2
        if not phase_identity(api):
            write_manifest()
            write_report(started, token, catastrophic=True)
            return 2

        phase_reference_reads(api)

        # Role-based sections. Additional tokens widen coverage beyond the primary role.
        extra_tokens = {
            "patient": os.getenv("PATIENT_ACCESS_TOKEN"),
            "staff": os.getenv("STAFF_ACCESS_TOKEN"),
            "admin": os.getenv("ADMIN_ACCESS_TOKEN"),
        }
        ran_roles = {CTX["role"]}

        # primary-token sections
        primary = CTX["role"]
        if primary == "admin":
            section_admin(api, token)
        if primary in ("staff", "admin"):
            section_staff(api, token, preferred_appointment_id=None)
        if primary == "patient":
            section_patient(api, token)

        # optional extra tokens (dedup against roles already run)
        for role_name in ("patient", "staff", "admin"):
            t = extra_tokens.get(role_name)
            if not t or role_name in ran_roles:
                continue
            print(f"\n### Additional {role_name} token provided - running {role_name}-scoped tests ###")
            # role detection for the extra token (best effort)
            st, body, err, _, _ = api.request("GET", f"{API}/users/me", token=t)
            if err or st != 200 or not isinstance(body, dict) or body.get("success") is not True:
                print(f"  WARNING: extra {role_name} token rejected (status={st}); skipping that section.")
                continue
            extra_role = (body.get("data") or {}).get("role")
            if extra_role != role_name:
                print(f"  WARNING: token role is '{extra_role}', expected '{role_name}'; skipping.")
                continue
            saved_role, saved_uid = CTX["role"], CTX["user_id"]
            CTX["role"], CTX["user_id"] = extra_role, (body.get("data") or {}).get("user_id")
            try:
                if role_name == "patient":
                    section_patient(api, t)
                else:
                    if role_name == "admin":
                        section_admin(api, t)
                    section_staff(api, t)
            finally:
                CTX["role"], CTX["user_id"] = saved_role, saved_uid
            ran_roles.add(role_name)

        cross_role_negatives(api)
        phase_agent(api)

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        write_manifest()
        write_report(started, token)
        return 1
    except Exception:
        print("\nUNHANDLED ERROR IN TEST HARNESS:")
        traceback.print_exc()
        write_manifest()
        write_report(started, token, catastrophic=True)
        return 2

    report = write_report(started, token)
    print_summary(report)

    if report["catastrophic_failure"]:
        return 2
    return 1 if report["summary"]["fail"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
