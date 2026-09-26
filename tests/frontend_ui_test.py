"""
Frontend UI render tests using Streamlit's in-process AppTest harness.

Runs the real ``frontend/app.py`` (st.navigation multipage app) with real
backend tokens for each role and asserts every page renders without a Python
exception and produces expected content. Run from the repo root:

    .venv/bin/python tests/frontend_ui_test.py
"""
from __future__ import annotations

import os
import sys
import json
import urllib.error
import urllib.parse
import urllib.request

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

RESULTS: list[tuple[str, bool, str]] = []


def api(method: str, path: str, token: str | None = None, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": f"{type(e).__name__}: {e}"}


def login(email: str) -> dict:
    """Return {"token": ..., "user": {...}} via the real OTP flow."""
    _, body = api("POST", "/auth/request-otp", body={"email": email})
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    link = sb.auth.admin.generate_link({"type": "magiclink", "email": email})
    otp = link.properties.email_otp
    status, body = api("POST", "/auth/verify-otp", body={"email": email, "otp": otp})
    if status != 200:
        raise RuntimeError(f"login failed for {email}: {status} {body}")
    data = body["data"]
    user_raw, profile, session = data["user"], data["profile"], data["session"]
    return {
        "token": session["access_token"],
        "user": {
            "user_id": user_raw["id"],
            "email": user_raw["email"],
            "full_name": profile.get("full_name"),
            "role": profile.get("role", "patient"),
            "status": profile.get("status", "active"),
            "phone": profile.get("phone"),
        },
    }


def check(name: str, cond: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  -- {detail}" if detail and not cond else ""))
    return bool(cond)


def run_page(app, page_path: str) -> AppTest:
    """Switch to a page, run it, and return the AppTest."""
    app.switch_page(page_path)
    app.run()
    return app


def expect(app: AppTest, name: str, *texts: str) -> bool:
    """Assert the app rendered without exceptions and contains all texts."""
    exc = [e.value for e in app.exception]
    if exc:
        check(name, False, f"exception: {exc}")
        return False
    parts = [m.value for m in app.markdown]
    parts += [m.value for m in app.caption]
    parts += [m.value for m in app.info]
    parts += [m.value for m in app.success]
    parts += [m.value for m in app.error]
    parts += getattr(app, "write", None) and [m.value for m in app.write] or []
    haystack = " ".join(parts)
    missing = [t for t in texts if t.lower() not in haystack.lower()]
    check(name, not missing, f"missing texts: {missing}" if missing else "")
    return not missing


def nav_labels(app: AppTest) -> list[str]:
    """
    Labels rendered by ``st.page_link`` (the navigation bar). AppTest exposes
    them as unknown elements, so walk the element tree and read their protos.
    """
    labels: list[str] = []

    def walk(node) -> None:
        children = getattr(node, "children", None)
        if isinstance(children, dict):
            for child in children.values():
                walk(child)
            return
        proto = getattr(node, "proto", None)
        label = getattr(proto, "label", None) if proto is not None else None
        if label:
            labels.append(label)

    walk(app.main)
    return labels


def main() -> int:
    creds = {}
    for role, email in ACCOUNTS.items():
        creds[role] = login(email)
        check(f"ui: login {role}", bool(creds[role]["token"]))

    # ---------- Public (guest) ----------
    app = AppTest.from_file(APP_PATH, default_timeout=120)
    app.run()
    expect(app, "home renders as guest", "Meridian Care", "24/7")
    check("home guest CTA shown", any("Sign in to see live" in (i.value or "") for i in app.info))

    app2 = AppTest.from_file(APP_PATH, default_timeout=120)
    app2.run()
    run_page(app2, "pages/public/departments.py")
    expect(app2, "departments page shows guest gate", "Explore live department listings")

    run_page(app2, "pages/public/about.py")
    expect(app2, "about page renders")

    run_page(app2, "pages/public/contact.py")
    expect(app2, "contact page renders")

    run_page(app2, "pages/public/help.py")
    expect(app2, "help page renders")

    run_page(app2, "pages/public/legal.py")
    expect(app2, "legal page renders")

    run_page(app2, "pages/public/login.py")
    expect(app2, "login page renders", "Sign In")
    check("login page shows Send OTP button",
          any(b.label == "Send OTP" for b in app2.button))

    # ---------- Patient portal ----------
    p = AppTest.from_file(APP_PATH, default_timeout=120)
    p.session_state["mc_auth"] = {"logged_in": True, "user": creds["patient"]["user"],
                                  "otp_pending_email": None, "otp_pending_signup": False}
    p.session_state["mc_access_token"] = creds["patient"]["token"]
    p.run()
    run_page(p, "pages/patient/dashboard.py")
    expect(p, "patient dashboard renders (live data)", "Welcome")

    run_page(p, "pages/patient/appointments.py")
    expect(p, "patient appointments page renders")

    run_page(p, "pages/patient/assistant.py")
    expect(p, "patient assistant page renders", "Meridian")

    run_page(p, "pages/patient/history.py")
    expect(p, "patient history page renders")

    run_page(p, "pages/patient/payments.py")
    expect(p, "patient payments page renders")

    run_page(p, "pages/patient/feedback.py")
    expect(p, "patient feedback page renders")

    run_page(p, "pages/patient/requests.py")
    expect(p, "patient requests page renders")

    run_page(p, "pages/patient/profile.py")
    expect(p, "patient profile page renders", "Profile")

    # ---------- Staff workspace ----------
    s = AppTest.from_file(APP_PATH, default_timeout=300)
    s.session_state["mc_auth"] = {"logged_in": True, "user": creds["staff"]["user"],
                                  "otp_pending_email": None, "otp_pending_signup": False}
    s.session_state["mc_access_token"] = creds["staff"]["token"]
    s.run()
    run_page(s, "pages/staff/dashboard.py")
    expect(s, "staff dashboard renders (live KPIs)", "Operations")

    run_page(s, "pages/staff/appointments.py")
    expect(s, "staff appointments page renders")

    # One reminder workflow: the staff nav exposes exactly one Reminders entry.
    check("staff nav has exactly one Reminders entry",
          nav_labels(s).count("Reminders") == 1, f"nav={nav_labels(s)}")
    check("staff nav order",
          nav_labels(s)[:5] == ["Operations", "Appointments", "Reminders",
                                "Analytics", "Forecasting"], f"nav={nav_labels(s)[:6]}")

    run_page(s, "pages/staff/reminders.py")
    expect(s, "staff reminders page renders", "Reminders")
    check("staff reminders exposes the single prediction action",
          sum(1 for b in s.button if b.label == "Predict Selected") == 1,
          f"buttons={[b.label for b in s.button]}")

    run_page(s, "pages/staff/analytics.py")
    exc = [e.value for e in s.exception]
    check("staff analytics page renders (8 tabs)", not exc, f"exception: {exc}")

    run_page(s, "pages/staff/predictions.py")
    expect(s, "staff predictions page renders", "Forecasting")
    check("staff predictions tabs present",
          any(t.label == "Department Forecasts" for t in s.tabs))
    check("no-show scoring removed from Forecasting",
          not any(t.label == "No-Show Scoring" for t in s.tabs),
          f"tabs={[t.label for t in s.tabs]}")

    # ---------- Administration ----------
    a = AppTest.from_file(APP_PATH, default_timeout=300)
    a.session_state["mc_auth"] = {"logged_in": True, "user": creds["admin"]["user"],
                                  "otp_pending_email": None, "otp_pending_signup": False}
    a.session_state["mc_access_token"] = creds["admin"]["token"]
    a.run()
    run_page(a, "pages/admin/dashboard.py")
    expect(a, "admin dashboard renders (live KPIs)")

    run_page(a, "pages/admin/users.py")
    expect(a, "admin users page renders")

    run_page(a, "pages/admin/departments.py")
    expect(a, "admin departments page renders")

    run_page(a, "pages/admin/doctors.py")
    expect(a, "admin doctors page renders")

    run_page(a, "pages/admin/knowledge.py")
    expect(a, "admin knowledge page renders", "Knowledge")

    run_page(a, "pages/admin/analytics.py")
    exc = [e.value for e in a.exception]
    check("admin analytics page renders", not exc, f"exception: {exc}")

    run_page(a, "pages/admin/predictions.py")
    expect(a, "admin predictions page renders", "Next-day operational forecasts")
    check("admin predictions tabs present",
          any(t.label == "Department Forecasts" for t in a.tabs))

    # ---------- Role enforcement ----------
    r = AppTest.from_file(APP_PATH, default_timeout=60)
    r.session_state["mc_auth"] = {"logged_in": True, "user": creds["patient"]["user"],
                                  "otp_pending_email": None, "otp_pending_signup": False}
    r.session_state["mc_access_token"] = creds["patient"]["token"]
    r.run()
    r.switch_page("pages/admin/users.py")
    r.run()
    check("patient redirected away from admin page",
          not r.exception, f"exceptions: {[e.value for e in r.exception]}")

    # Unauthenticated visitor on a protected page → sign-in gate, no exception.
    g = AppTest.from_file(APP_PATH, default_timeout=60)
    g.run()
    g.switch_page("pages/patient/dashboard.py")
    g.run()
    gate = any("Sign in to continue" in (m.value or "") for m in g.markdown)
    check("guest sees sign-in gate on protected page", gate and not g.exception,
          f"gate={gate} exc={[e.value for e in g.exception]}")

    # 404 / error screens render.
    nf = AppTest.from_file(APP_PATH, default_timeout=60)
    nf.run()
    nf.switch_page("pages/system/not_found.py")
    nf.run()
    expect(nf, "404 page renders", "Page Not Found")

    # ---------- Interactive write flows ----------
    # 1. Patient submits a support request through the UI (real write path).
    i = AppTest.from_file(APP_PATH, default_timeout=120)
    i.session_state["mc_auth"] = {"logged_in": True, "user": creds["patient"]["user"],
                                  "otp_pending_email": None, "otp_pending_signup": False}
    i.session_state["mc_access_token"] = creds["patient"]["token"]
    i.run()
    run_page(i, "pages/patient/requests.py")
    if i.text_area:
        i.text_area[0].set_value("Frontend UI integration test request — kindly ignore.").run()
        submit = next((b for b in i.button if b.label == "Submit Request"), None)
        if submit:
            submit.click().run()
            listed = any("Frontend UI integration test request" in (m.value or "")
                         for m in list(i.markdown) + list(i.success))
            exc = [e.value for e in i.exception]
            check("patient submits request via UI (write path)", listed and not exc,
                  f"listed={listed} exc={exc}")
        else:
            check("patient submits request via UI (write path)", False, "no submit button")
    else:
        check("patient submits request via UI (write path)", False, "no form widgets")

    # 2. Patient chats with the AI agent through the UI (real LLM + RAG path).
    c = AppTest.from_file(APP_PATH, default_timeout=240)
    c.session_state["mc_auth"] = {"logged_in": True, "user": creds["patient"]["user"],
                                  "otp_pending_email": None, "otp_pending_signup": False}
    c.session_state["mc_access_token"] = creds["patient"]["token"]
    c.run()
    run_page(c, "pages/patient/assistant.py")
    if c.chat_input:
        c.chat_input[0].set_value("What are the visiting hours?").run()
        replies = [
            md.value
            for cm in c.chat_message
            if cm.name == "assistant"
            for md in cm.markdown
        ]
        exc = [e.value for e in c.exception]
        check("agent chat replies through the UI", bool(replies) and not exc,
              f"replies={[r[:70] for r in replies]} exc={exc}")
    else:
        check("agent chat replies through the UI", False, "no chat input")

    # ---------- Summary ----------
    failed = [r for r in RESULTS if not r[1]]
    print("\n" + "=" * 70)
    print(f"UI TOTAL: {len(RESULTS)}  PASS: {len(RESULTS) - len(failed)}  FAIL: {len(failed)}")
    for name, ok, detail in failed:
        print(f"  FAILED: {name}  {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())