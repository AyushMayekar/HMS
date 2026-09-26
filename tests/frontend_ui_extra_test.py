"""Supplementary UI smoke test for pages the main harness does not cover."""
from __future__ import annotations

import os
import sys
import urllib.request
import json

from dotenv import load_dotenv

load_dotenv(dotenv_path=".env", override=False)
from pathlib import Path  # noqa: E402
from supabase import create_client  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
APP_PATH = str(ROOT / "frontend" / "app.py")
BASE = os.getenv("BASE_URL", "http://127.0.0.1:8000") + "/api/v1"

ACCOUNTS = {
    "patient": "sufiyanhattar@gmail.com",
    "staff": "shaikharif190104@gmail.com",
    "admin": "shaikharif6190@gmail.com",
}
RESULTS = []


def api(method, path, token=None, body=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def login(email):
    _, body = api("POST", "/auth/request-otp", body={"email": email})
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    link = sb.auth.admin.generate_link({"type": "magiclink", "email": email})
    otp = link.properties.email_otp
    status, body = api("POST", "/auth/verify-otp", body={"email": email, "otp": otp})
    if status != 200:
        raise RuntimeError(f"login failed: {status} {body}")
    data = body["data"]
    user_raw, profile, session = data["user"], data["profile"], data["session"]
    return session["access_token"], {
        "user_id": user_raw["id"],
        "email": user_raw["email"],
        "full_name": profile.get("full_name"),
        "role": profile.get("role", "patient"),
        "status": profile.get("status", "active"),
        "phone": profile.get("phone"),
    }


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  -- {detail}" if detail and not cond else ""))


def app_for(role):
    token, user = login(ACCOUNTS[role])
    app = AppTest.from_file(APP_PATH, default_timeout=300)
    app.session_state["mc_auth"] = {
        "logged_in": True,
        "user": user,
        "otp_pending_email": None,
        "otp_pending_signup": False,
    }
    app.session_state["mc_access_token"] = token
    return app.run()


def goto(app, page):
    app.switch_page(page)
    app.run()
    return app


def no_exc(app):
    return [e.value for e in app.exception]


def texts(app):
    parts = []
    for attr in ("markdown", "caption", "info", "success", "error", "write", "title", "subheader", "metric"):
        try:
            parts += [m.value for m in getattr(app, attr)]
        except Exception:
            pass
    return " ".join(str(p) for p in parts)


def main():
    # ---------- Staff: ONE reminder workflow, on the Reminders page ----------
    s = app_for("staff")
    check("staff app boots", not no_exc(s), str(no_exc(s)))
    goto(s, "pages/staff/dashboard.py")
    check("staff unified dashboard renders", not no_exc(s), str(no_exc(s)))
    check("staff dashboard has no duplicate reminder panel",
          not any(b.label == "Open reminder actions" for b in s.button),
          f"buttons={[b.label for b in s.button]}")
    check("staff dashboard shows department grouping", "visit(s) in this department" in texts(s) or "No appointments" in texts(s))

    goto(s, "pages/staff/appointments.py")
    check("staff appointments renders with pagination", not no_exc(s) and "Showing" in texts(s), str(no_exc(s)))

    goto(s, "pages/staff/reminders.py")
    check("staff reminders page renders", not no_exc(s), str(no_exc(s)))
    check("staff reminders is the single prediction surface",
          sum(1 for b in s.button if b.label == "Predict Selected") == 1,
          f"buttons={[b.label for b in s.button]}")

    goto(s, "pages/staff/predictions.py")
    check("staff predictions renders", not no_exc(s), str(no_exc(s)))
    check("forecasting no longer hosts no-show scoring",
          not any(t.label == "No-Show Scoring" for t in s.tabs),
          f"tabs={[t.label for t in s.tabs]}")

    # ---------- Admin: merged management + audit logs ----------
    a = app_for("admin")
    check("admin app boots", not no_exc(a), str(no_exc(a)))
    goto(a, "pages/admin/management.py")
    check("admin management page renders", not no_exc(a), str(no_exc(a)))
    t = texts(a)
    check("admin management shows Users section", "Accounts" in t or "Create Staff" in t, t[:200])

    radios = list(a.radio)
    if radios:
        radios[0].set_value("Departments").run()
        check("admin management switches to Departments",
              not no_exc(a) and "All Departments" in texts(a), str(no_exc(a)))
        radios = list(a.radio)
        radios[0].set_value("Doctors").run()
        check("admin management switches to Doctors",
              not no_exc(a) and "All Doctors" in texts(a), str(no_exc(a)))

    goto(a, "pages/admin/audit_logs.py")
    audit_txt = texts(a)
    check("admin audit logs renders", not no_exc(a) and ("Page" in audit_txt or "Showing" in audit_txt or "audit" in audit_txt.lower()),
          f"exc={no_exc(a)} text={audit_txt[:200]}")

    goto(a, "pages/admin/analytics.py")
    check("admin analytics renders (shared tabs)", not no_exc(a), str(no_exc(a)))

    # ---------- Patient ----------
    p = app_for("patient")
    check("patient app boots", not no_exc(p), str(no_exc(p)))
    goto(p, "pages/patient/dashboard.py")
    pt = texts(p)
    check("patient dashboard has no Quick Book", "Quick Book" not in pt)
    check("patient dashboard has no Requests section", "Support Requests" not in pt)
    check("patient dashboard renders departments", "Hospital Departments" in pt, str(no_exc(p)))

    goto(p, "pages/patient/appointments.py")
    at = texts(p)
    check("patient appointments renders booking + links", not no_exc(p) and "Book New Appointment" in at, str(no_exc(p)))
    registry = p.session_state["_mc_pages"]
    link_ok = all(registry.get(k) is not None for k in ("patient_history", "patient_feedback", "patient_payments"))
    check("patient appointments wires History/Feedback/Payments page links", link_ok)

    # Reminders & requests panel on the patient dashboard loads on demand.
    goto(p, "pages/patient/dashboard.py")
    toggles = [b for b in p.button if b.label == ""]
    if toggles:
        toggles[-1].click()
        p.run()
        check("patient dashboard status panel opens without errors",
              not no_exc(p), str(no_exc(p)))
    else:
        check("patient dashboard status panel opens without errors", False, "no toggle button found")

    failed = [n for n, ok in RESULTS if not ok]
    print("\n=== RESULT:", "ALL PASS" if not failed else f"{len(failed)} FAILED -> {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
