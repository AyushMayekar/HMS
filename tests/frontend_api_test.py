"""
End-to-end API test harness for the Meridian Care frontend.

Exercises the exact backend endpoints that each frontend page calls, for all
three roles, and prints a pass/fail summary. Run from the repo root:

    .venv/bin/python tests/frontend_api_test.py
"""
from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
import json

from dotenv import load_dotenv

load_dotenv(dotenv_path=".env", override=False)
from supabase import create_client  # noqa: E402

BASE = os.getenv("BASE_URL", "http://127.0.0.1:8000") + "/api/v1"

# Accounts with a confirmed auth user AND a matching profile row.
TEST_ACCOUNTS = {
    "patient": "sufiyanhattar@gmail.com",
    "staff": "shaikharif190104@gmail.com",
    "admin": "shaikharif6190@gmail.com",
}

RESULTS: list[tuple[str, bool, str]] = []


def api(method: str, path: str, token: str | None = None, body=None, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode()), dict(resp.headers)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw), dict(e.headers)
        except json.JSONDecodeError:
            return e.code, {"raw": raw}, dict(e.headers)
    except Exception as e:  # noqa: BLE001
        return 0, {"error": f"{type(e).__name__}: {e}"}, {}


def check(name: str, cond: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  -- {detail}" if detail and not cond else ""))
    return bool(cond)


def login(email: str) -> str | None:
    """Complete the real OTP login flow using an admin-generated OTP."""
    status, body, _ = api("POST", "/auth/request-otp", body={"email": email})
    if status != 200:
        return None
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    link = sb.auth.admin.generate_link({"type": "magiclink", "email": email})
    otp = link.properties.email_otp
    status, body, _ = api("POST", "/auth/verify-otp", body={"email": email, "otp": otp})
    if status != 200:
        print(f"  verify-otp failed: {status} {body}")
        return None
    return (body.get("data") or {}).get("session", {}).get("access_token")


def main() -> int:
    # ---------- Auth ----------
    tokens = {}
    for role, email in TEST_ACCOUNTS.items():
        tok = login(email)
        tokens[role] = tok
        check(f"login ({role}: {email})", bool(tok))

        status, body, headers = api("GET", "/users/me", token=tok)
        me = (body.get("data") or {}) if isinstance(body, dict) else {}
        check(
            f"GET /users/me ({role})",
            status == 200 and me.get("role") == role,
            f"status={status} role={me.get('role')}",
        )

    # Bad OTP must return the standard error envelope.
    status, body, _ = api("POST", "/auth/verify-otp",
                          body={"email": TEST_ACCOUNTS["patient"], "otp": "000000"})
    check("verify-otp rejects bad OTP with error envelope",
          status >= 400 and isinstance(body, dict) and body.get("success") is False,
          f"status={status} body={json.dumps(body)[:160]}")

    p, s, a = tokens["patient"], tokens["staff"], tokens["admin"]
    if not all([p, s, a]):
        print("Aborting: logins failed.")
        return 1

    # ---------- Patient pages ----------
    status, body, _ = api("GET", "/patient/appointments", token=p, params={"limit": 5})
    data = body.get("data") or {}
    appts = data.get("appointments", data) if isinstance(data, dict) else data
    check("patient appointments list", status == 200, f"status={status}")

    status, body, _ = api("GET", "/patient/payments", token=p, params={"limit": 5})
    check("patient payments list", status == 200, f"status={status}")

    status, body, _ = api("GET", "/patient/feedback", token=p, params={"limit": 5})
    check("patient feedback list", status == 200, f"status={status}")

    status, body, _ = api("GET", "/patient/admin-requests", token=p, params={"limit": 5})
    check("patient admin-requests list", status == 200, f"status={status}")

    status, body, _ = api("GET", "/patient/reminders", token=p, params={"limit": 5})
    check("patient reminders list", status == 200, f"status={status}")

    # Create an admin request (frontend create path). Backend returns 201.
    status, body, _ = api("POST", "/patient/admin-requests", token=p,
                          params={"category": "administrative",
                                  "description": "Frontend integration test request"})
    check("create admin request", status in (200, 201) and (body.get("success") is True),
          f"status={status} {json.dumps(body)[:160]}")

    # ---------- Catalog (public pages + booking) ----------
    status, body, _ = api("GET", "/catalog/departments", token=p)
    check("catalog departments", status == 200 and len(body.get("data") or []) > 0,
          f"status={status} n={len(body.get('data') or [])}")

    status, body, _ = api("GET", "/catalog/doctors", token=p)
    check("catalog doctors", status == 200 and len(body.get("data") or []) > 0,
          f"status={status} n={len(body.get('data') or [])}")

    status, body, _ = api("GET", "/catalog/availability", token=p)
    check("catalog availability", status == 200, f"status={status}")

    # ---------- Agent ----------
    status, body, _ = api("POST", "/agent/chat", token=p,
                          body={"query": "What departments do you have?"})
    check("agent chat (informational intent)",
          status == 200 and (body.get("success") is True or body.get("response")),
          f"status={status} {json.dumps(body)[:160]}")

    # ---------- Staff pages ----------
    status, body, _ = api("GET", "/staff/appointments", token=s,
                          params={"limit": 5, "appointment_status": "booked"})
    check("staff appointments list", status == 200, f"status={status}")

    status, body, _ = api("GET", "/staff/reminders", token=s, params={"limit": 5})
    check("staff reminders list", status == 200, f"status={status}")

    # Reminder create — the write path used by the staff Reminders page.
    status, body, _ = api("GET", "/staff/appointments", token=s,
                          params={"limit": 50, "appointment_status": "booked"})
    rem_data = (body.get("data") or {})
    rem_appts = rem_data.get("appointments", rem_data) if isinstance(rem_data, dict) else rem_data
    today = "2026-09-23"
    future_appt = next(
        (x for x in (rem_appts or []) if (x.get("scheduled_start") or "")[:10] >= today),
        None,
    )
    if future_appt:
        status, body, _ = api(
            "POST", f"/staff/reminders/{future_appt['appointment_id']}", token=s,
            body={"reminder_type": "in_app", "hours_before_appointment": 24.0,
                  "message": "A friendly reminder about your upcoming appointment."},
        )
        check("create in-app reminder (Reminders page write path)",
              status in (200, 201) and body.get("success") is True,
              f"status={status} {json.dumps(body)[:160]}")
    else:
        check("create in-app reminder (Reminders page write path)", False, "no future booked appointment")

    # ---------- Analytics (staff + admin pages) ----------
    for path in (
        "/analytics/appointments?days=30",
        "/analytics/billing?days=30",
        "/analytics/satisfaction?days=30",
        "/analytics/no-show?days=30",
        "/analytics/no-show-risk",
        "/analytics/waiting-time?days=30",
        "/analytics/booking-channel?days=30",
    ):
        status, body, _ = api("GET", path, token=s)
        check(f"analytics {path.split('?')[0]} (staff)", status == 200, f"status={status}")

    status, body, _ = api("GET", "/analytics/appointments?days=30", token=a)
    check("analytics appointments (admin)", status == 200, f"status={status}")

    # ---------- Predictions (staff + admin pages) ----------
    # Pick a booked, not-yet-checked-in appointment to score (read-only ML call).
    status, body, _ = api("GET", "/staff/appointments", token=s,
                          params={"limit": 20, "appointment_status": "booked"})
    staff_data = body.get("data") or {}
    appts = staff_data.get("appointments", staff_data) if isinstance(staff_data, dict) else staff_data
    appt_id = None
    if isinstance(appts, list):
        for a_appt in appts:
            if not a_appt.get("actual_checkin_time"):
                appt_id = a_appt.get("appointment_id")
                break
    check("prediction target appointment found", bool(appt_id), f"appt={appt_id}")

    if appt_id:
        status, body, _ = api("POST", f"/predictions/no-show/{appt_id}", token=s)
        check("prediction no-show", status == 200, f"status={status} {json.dumps(body)[:160]}")

        status, body, _ = api("POST", f"/predictions/waiting-time/{appt_id}", token=s)
        check("prediction waiting-time", status == 200, f"status={status}")

    status, body, _ = api("POST", "/predictions/bed-demand", token=s,
                          body={"target_date": "2026-09-24"})
    check("prediction bed-demand forecast", status == 200, f"status={status} {json.dumps(body)[:160]}")

    status, body, _ = api("POST", "/predictions/patient-flow", token=s,
                          body={"target_date": "2026-09-24"})
    check("prediction patient-flow forecast", status == 200, f"status={status}")

    # ---------- Admin pages ----------
    status, body, _ = api("GET", "/admin/users", token=a, params={"limit": 5})
    check("admin users list", status == 200, f"status={status}")

    status, body, _ = api("GET", "/departments", token=a, params={"limit": 5})
    check("departments list (admin)", status == 200, f"status={status}")

    status, body, _ = api("GET", "/doctors", token=a, params={"limit": 5})
    check("doctors list (admin)", status == 200, f"status={status}")

    status, body, _ = api("GET", "/knowledge/documents", token=a, params={"limit": 5})
    check("knowledge documents list", status == 200, f"status={status}")

    # RAG search (knowledge page reindex is write-heavy; search proves RAG works).
    status, body, _ = api("GET", "/rag/search", token=a, params={"query": "visiting hours", "top_k": 3})
    check("rag search", status == 200, f"status={status}")

    # ---------- Role enforcement ----------
    status, body, _ = api("GET", "/admin/users", token=p, params={"limit": 5})
    check("role gate: patient blocked from admin users", status == 403,
          f"status={status}")

    status, body, _ = api("GET", "/admin/users")
    check("auth gate: no token rejected", status in (401, 403), f"status={status}")

    # ---------- Summary ----------
    failed = [r for r in RESULTS if not r[1]]
    print("\n" + "=" * 70)
    print(f"TOTAL: {len(RESULTS)}  PASS: {len(RESULTS) - len(failed)}  FAIL: {len(failed)}")
    for name, ok, detail in failed:
        print(f"  FAILED: {name}  {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    import urllib.parse  # noqa: E402  (used in api())
    sys.exit(main())