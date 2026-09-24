"""
Login/Signup page — passwordless OTP sign-in and patient registration.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

import streamlit as st

from frontend.components.navbar import page_head
from frontend.api.services import AuthService
from frontend.utils.states import display_api_error
from frontend.utils.session import (
    set_otp_pending,
    clear_otp_pending,
    get_otp_pending,
    login_user,
    is_authenticated,
)

# ---------------------------------------------------------------------------
# Validation rules (UI-level; the API validates again on submit)
# ---------------------------------------------------------------------------
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
MIN_DOB = date(1900, 1, 1)
MAX_AGE_YEARS = 120
CODE_LENGTH = 8

_COOKIE_DISMISS_KEY = "_mc_cookie_notice_dismissed"


def _email_error(value) -> Optional[str]:
    value = (value or "").strip()
    if not value:
        return "Enter your email address."
    if not EMAIL_RE.match(value):
        return "That doesn't look like a valid email address (e.g. you@example.com)."
    return None


def _name_error(value) -> Optional[str]:
    value = (value or "").strip()
    if not value:
        return "Enter your full name."
    if len(value) < 2:
        return "Full name must be at least 2 characters."
    return None


def _phone_error(value) -> Optional[str]:
    value = (value or "").strip()
    if not value:
        return "Enter your phone number."
    if not value.isdigit():
        return "Use digits only — no spaces, dashes, or country code."
    if not 10 <= len(value) <= 15:
        return "Enter a phone number of 10 to 15 digits."
    return None


def _dob_error(value: Optional[date]) -> Optional[str]:
    if value is None:
        return "Select your date of birth."
    today = date.today()
    if value > today:
        return "Date of birth cannot be in the future."
    if value < MIN_DOB:
        return "Please enter a plausible date of birth."
    if today.year - value.year > MAX_AGE_YEARS:
        return "Please enter a plausible date of birth."
    return None


def _code_error(value) -> Optional[str]:
    value = (value or "").strip()
    if not value:
        return f"Enter the {CODE_LENGTH}-digit code we emailed you."
    if len(value) != CODE_LENGTH or not value.isdigit():
        return f"The code must be exactly {CODE_LENGTH} digits."
    return None


def _as_date(raw) -> Optional[date]:
    """Normalize st.date_input output (date, empty tuple, or None)."""
    if isinstance(raw, (tuple, list)):
        return raw[0] if raw else None
    if isinstance(raw, date):
        return raw
    return None


# ---------------------------------------------------------------------------
# Auth-flow helpers
# ---------------------------------------------------------------------------
def _begin_otp(email: str, is_signup: bool) -> None:
    """Enter the code-verification screen with a clean slate."""
    st.session_state.pop("otp_input", None)
    st.session_state.pop("otp_show_errors", None)
    st.session_state["_otp_flash"] = True
    set_otp_pending(email, is_signup=is_signup)


def _start_over() -> None:
    """Return from code verification to the Sign In / Sign Up tabs."""
    clear_otp_pending()
    st.session_state.pop("otp_input", None)
    st.session_state.pop("otp_show_errors", None)


def _render_cookie_notice() -> None:
    """Non-blocking essential-cookie notice for the authentication flow."""
    if st.session_state.get(_COOKIE_DISMISS_KEY):
        return
    text_col, action_col = st.columns([6, 1], gap="small", vertical_alignment="center")
    with text_col:
        st.info(
            "Privacy note: this site uses essential session cookies only, so we can "
            "keep you signed in securely. No advertising or tracking cookies are used. "
            "See Privacy & Terms in the footer for full details."
        )
    with action_col:
        if st.button(
            "Dismiss",
            key="cookie_notice_dismiss",
            width="stretch",
            help="Hide this notice for the rest of your session",
        ):
            st.session_state[_COOKIE_DISMISS_KEY] = True
            st.rerun()


# ---------------------------------------------------------------------------
# Page entry
# ---------------------------------------------------------------------------
def render() -> None:
    # Redirect signed-in users to their workspace
    if is_authenticated():
        from frontend.utils.session import current_role
        landing = {
            "patient": "pages/patient/dashboard.py",
            "staff": "pages/staff/dashboard.py",
            "doctor": "pages/doctor/dashboard.py",
            "admin": "pages/admin/dashboard.py",
        }.get(current_role(), "pages/public/home.py")
        st.switch_page(landing)

    page_head(
        "Sign In / Sign Up",
        "Access your patient portal or create a new account — passwordless, using an "
        f"{CODE_LENGTH}-digit code sent to your email.",
    )

    _render_cookie_notice()

    otp_email, is_signup = get_otp_pending()

    if otp_email:
        # Code verification screen
        render_otp_verification(otp_email, is_signup)
    else:
        # Main sign in / sign up screen
        render_login_signup()


def render_login_signup() -> None:
    """Render the sign-in / sign-up tabs with consistent styling."""
    tab1, tab2 = st.tabs(["Sign In", "Sign Up"])

    auth = AuthService()

    # ------------------------------------------------------------------
    # SIGN IN
    # ------------------------------------------------------------------
    with tab1:
        st.write(
            f"Enter the email address registered with us and we'll send an "
            f"**{CODE_LENGTH}-digit code** — no password to remember."
        )

        email = st.text_input(
            "Email address",
            key="si_email",
            placeholder="you@example.com",
        )
        si_err = (
            _email_error(st.session_state.get("si_email"))
            if st.session_state.get("si_show_errors")
            else None
        )
        if si_err:
            st.warning(si_err)
        st.caption("Don't have an account? Use the Sign Up tab to create one.")

        if st.button(
            "Send 8-digit code",
            key="si_submit",
            type="primary",
            width="stretch",
        ):
            err = _email_error(email)
            if err:
                st.session_state["si_show_errors"] = True
                st.rerun()
            st.session_state["si_show_errors"] = False
            clean_email = (email or "").strip().lower()
            with st.spinner("Sending your 8-digit code..."):
                response = auth.request_otp(clean_email)
            if response.success:
                _begin_otp(clean_email, is_signup=False)
                st.rerun()
            else:
                display_api_error(response)

    # ------------------------------------------------------------------
    # SIGN UP
    # ------------------------------------------------------------------
    with tab2:
        st.write(
            "Create a patient account. Staff and administrator accounts are "
            "created by hospital administrators."
        )
        show_errors = bool(st.session_state.get("su_show_errors"))

        col1, col2 = st.columns(2, gap="large")

        with col1:
            full_name = st.text_input(
                "Full name", key="su_name", placeholder="e.g. Ananya Rao"
            )
            err_name = _name_error(full_name) if show_errors else None
            if err_name:
                st.warning(err_name)

            signup_email = st.text_input(
                "Email address", key="su_email", placeholder="you@example.com"
            )
            err_email = _email_error(signup_email) if show_errors else None
            if err_email:
                st.warning(err_email)
            else:
                st.caption(f"We'll email an {CODE_LENGTH}-digit code here to verify it.")

            phone = st.text_input(
                "Phone number", key="su_phone", placeholder="9876543210"
            )
            err_phone = _phone_error(phone) if show_errors else None
            if err_phone:
                st.warning(err_phone)
            else:
                st.caption("Digits only — used for appointment and account updates.")

        with col2:
            dob_raw = st.date_input(
                "Date of birth",
                key="su_dob",
                value=None,
                min_value=MIN_DOB,
                max_value=date.today(),
                format="YYYY-MM-DD",
                help="Select your date of birth — it cannot be in the future.",
            )
            dob = _as_date(dob_raw)
            err_dob = _dob_error(dob) if show_errors else None
            if err_dob:
                st.warning(err_dob)
            else:
                st.caption("Under 18? A parent or guardian must consent to use this platform.")

            gender = st.selectbox(
                "Gender",
                ["Male", "Female", "Other", "Prefer not to say"],
                key="su_gender",
            )
            st.caption("Used only for your patient profile.")

        if st.button(
            "Create account",
            key="su_submit",
            type="primary",
            width="stretch",
        ):
            fresh_errors = {
                "name": _name_error(full_name),
                "email": _email_error(signup_email),
                "phone": _phone_error(phone),
                "dob": _dob_error(dob),
            }
            if any(fresh_errors.values()):
                st.session_state["su_show_errors"] = True
                st.rerun()
            st.session_state["su_show_errors"] = False

            clean_email = (signup_email or "").strip().lower()
            with st.spinner("Creating your account..."):
                response = auth.signup(
                    full_name=(full_name or "").strip(),
                    email=clean_email,
                    phone=(phone or "").strip(),
                    date_of_birth=dob.strftime("%Y-%m-%d") if dob else "",
                    gender=gender,
                )
            if response.success:
                _begin_otp(clean_email, is_signup=True)
                st.rerun()
            else:
                display_api_error(response)


def render_otp_verification(email: str, is_signup: bool) -> None:
    """Render the code verification screen."""
    auth = AuthService()

    purpose = "create your account" if is_signup else "sign in"
    verify_label = "Verify & create account" if is_signup else "Verify & sign in"

    if st.session_state.pop("_otp_flash", False):
        st.success(
            f"We sent an {CODE_LENGTH}-digit code to **{email}**. "
            f"Enter it below to {purpose}."
        )
    else:
        st.info(
            f"Enter the **{CODE_LENGTH}-digit code** we sent to **{email}** "
            f"to {purpose}."
        )

    otp = st.text_input(
        "8-digit code",
        key="otp_input",
        placeholder="12345678",
        max_chars=CODE_LENGTH,
        help=f"Exactly {CODE_LENGTH} digits, exactly as emailed to you.",
    )
    otp_err = (
        _code_error(st.session_state.get("otp_input"))
        if st.session_state.get("otp_show_errors")
        else None
    )
    if otp_err:
        st.warning(otp_err)
    else:
        st.caption(
            f"The code is {CODE_LENGTH} digits long. Didn't get it? Check your "
            "spam folder or resend below."
        )

    col1, col2 = st.columns(2, gap="medium")
    with col1:
        verify_clicked = st.button(
            verify_label, key="otp_verify", type="primary", width="stretch"
        )
    with col2:
        resend_clicked = st.button(
            "Resend code", key="otp_resend", width="stretch"
        )

    # on_click callbacks run before the script, so session cleanup here is safe
    # even though the code input widget was instantiated above.
    st.button(
        "Start over — back to Sign In / Sign Up",
        key="otp_back",
        width="stretch",
        on_click=_start_over,
    )

    if resend_clicked:
        with st.spinner("Sending a new 8-digit code..."):
            response = auth.request_otp(email)
        if response.success:
            st.success(f"We sent a new {CODE_LENGTH}-digit code to **{email}**.")
        else:
            display_api_error(response)

    if verify_clicked:
        err = _code_error(otp)
        if err:
            st.session_state["otp_show_errors"] = True
            st.rerun()
        st.session_state["otp_show_errors"] = False

        code = (otp or "").strip()
        with st.spinner("Verifying your code..."):
            if is_signup:
                response = auth.verify_signup_otp(email, code)
            else:
                response = auth.verify_otp(email, code)

        if not response.success:
            display_api_error(response)
            return

        data = response.data or {}
        user = data.get("user") or {}
        profile = data.get("profile") or {}
        session = data.get("session") or {}

        if not user.get("id") or not session.get("access_token"):
            st.error(
                "We couldn't complete sign-in just now. Please request a new "
                "8-digit code and try again."
            )
            return

        user_data = {
            "user_id": user.get("id"),
            "email": user.get("email", email),
            "full_name": profile.get("full_name"),
            "role": profile.get("role", "patient"),
            "status": profile.get("status", "active"),
            "phone": profile.get("phone"),
        }

        login_user(
            user_data=user_data,
            access_token=session.get("access_token"),
            refresh_token=session.get("refresh_token"),
            expires_at=session.get("expires_at"),
        )

        clear_otp_pending()
        st.session_state["_show_welcome_toast"] = True
        if is_signup:
            st.success("Account created and verified — taking you to your dashboard...")
        else:
            st.success("Code verified — signing you in...")
        st.rerun()


if __name__ == "__main__":
    render()
