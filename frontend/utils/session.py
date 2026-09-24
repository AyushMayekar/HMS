"""
Session management utilities for the Streamlit frontend.
Handles authentication state, token storage, and user context.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import streamlit as st

from frontend.config import ROLE_ADMIN, ROLE_DOCTOR, ROLE_PATIENT, ROLE_STAFF, VALID_ROLES


@dataclass
class UserProfile:
    """User profile information from backend."""
    user_id: str
    email: str
    full_name: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    phone: Optional[str] = None

    @property
    def is_patient(self) -> bool:
        return self.role == ROLE_PATIENT

    @property
    def is_staff(self) -> bool:
        return self.role == ROLE_STAFF

    @property
    def is_doctor(self) -> bool:
        return self.role == ROLE_DOCTOR

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def display_name(self) -> str:
        return self.full_name or self.email.split("@")[0].title()

    @property
    def role_label(self) -> str:
        return (self.role or "user").title()


# Session state keys
SESSION_AUTH = "mc_auth"
SESSION_USER = "mc_user"
SESSION_TOKEN = "mc_access_token"
SESSION_REFRESH = "mc_refresh_token"
SESSION_EXPIRY = "mc_token_expiry"


def init_session_state() -> None:
    """Initialize session state with defaults."""
    if SESSION_AUTH not in st.session_state:
        st.session_state[SESSION_AUTH] = {
            "logged_in": False,
            "user": None,
            "otp_pending_email": None,
            "otp_pending_signup": False,
        }
    if SESSION_TOKEN not in st.session_state:
        st.session_state[SESSION_TOKEN] = None
    if SESSION_REFRESH not in st.session_state:
        st.session_state[SESSION_REFRESH] = None
    if SESSION_EXPIRY not in st.session_state:
        st.session_state[SESSION_EXPIRY] = None


def is_authenticated() -> bool:
    """Check if user is authenticated."""
    init_session_state()
    auth = st.session_state.get(SESSION_AUTH, {})
    return auth.get("logged_in", False) and st.session_state.get(SESSION_TOKEN) is not None


def current_user() -> Optional[UserProfile]:
    """Get current user profile."""
    init_session_state()
    auth = st.session_state.get(SESSION_AUTH, {})
    user_data = auth.get("user")
    if user_data:
        return UserProfile(**user_data)
    return None


def current_role() -> Optional[str]:
    """Get current user role."""
    user = current_user()
    return user.role if user else None


def require_role(allowed_roles: list[str]) -> UserProfile:
    """Require specific role; stop execution if not authorized."""
    init_session_state()

    if not is_authenticated():
        _render_sign_in_required()
        st.stop()

    user = current_user()
    if not user or user.role not in allowed_roles:
        st.switch_page("pages/system/access_denied.py")
        st.stop()

    return user


def _render_sign_in_required() -> None:
    """Friendly sign-in gate for pages that need authentication."""
    registry = st.session_state.get("_mc_pages", {})
    st.markdown(
        """
        <div style="
            text-align: center;
            padding: 3rem;
            background: var(--mc-surface, #FFFFFF);
            border: 1px solid var(--mc-border, #E2E8F0);
            border-radius: 12px;
            margin: 2rem auto;
            max-width: 520px;
        ">
            <h2 style="color: var(--mc-navy, #0B3C5D); margin-bottom: 0.75rem;">Sign in to continue</h2>
            <p style="color: var(--mc-text, #1E293B);">
                This area is available to signed-in patients, staff, doctors, and administrators.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    login_page = registry.get("login")
    if login_page:
        st.page_link(login_page, label="Go to Sign In", icon=":material/login:")
    else:
        st.error("Please sign in to access this page.")


def get_access_token() -> Optional[str]:
    """Get current access token."""
    return st.session_state.get(SESSION_TOKEN)


def set_auth_state(
    logged_in: bool,
    user: Optional[dict] = None,
    access_token: Optional[str] = None,
    refresh_token: Optional[str] = None,
    expires_at: Optional[int] = None,
    otp_pending_email: Optional[str] = None,
    otp_pending_signup: bool = False,
) -> None:
    """Set authentication state in session."""
    init_session_state()

    st.session_state[SESSION_AUTH] = {
        "logged_in": logged_in,
        "user": user,
        "otp_pending_email": otp_pending_email,
        "otp_pending_signup": otp_pending_signup,
    }

    if access_token:
        st.session_state[SESSION_TOKEN] = access_token
    if refresh_token:
        st.session_state[SESSION_REFRESH] = refresh_token
    if expires_at:
        st.session_state[SESSION_EXPIRY] = expires_at


def clear_auth_state() -> None:
    """Clear all authentication state."""
    init_session_state()
    st.session_state[SESSION_AUTH] = {
        "logged_in": False,
        "user": None,
        "otp_pending_email": None,
        "otp_pending_signup": False,
    }
    st.session_state[SESSION_TOKEN] = None
    st.session_state[SESSION_REFRESH] = None
    st.session_state[SESSION_EXPIRY] = None


def login_user(
    user_data: dict,
    access_token: str,
    refresh_token: str,
    expires_at: int,
) -> None:
    """Log in a user with token data."""
    set_auth_state(
        logged_in=True,
        user=user_data,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
    )


def logout() -> None:
    """Log out the current user."""
    clear_auth_state()


def set_otp_pending(email: str, is_signup: bool = False) -> None:
    """Set OTP pending state."""
    init_session_state()
    auth = st.session_state[SESSION_AUTH]
    auth["otp_pending_email"] = email
    auth["otp_pending_signup"] = is_signup
    st.session_state[SESSION_AUTH] = auth


def clear_otp_pending() -> None:
    """Clear OTP pending state."""
    init_session_state()
    auth = st.session_state[SESSION_AUTH]
    auth["otp_pending_email"] = None
    auth["otp_pending_signup"] = False
    st.session_state[SESSION_AUTH] = auth


def get_otp_pending() -> tuple[Optional[str], bool]:
    """Get OTP pending email and signup flag."""
    init_session_state()
    auth = st.session_state.get(SESSION_AUTH, {})
    return auth.get("otp_pending_email"), auth.get("otp_pending_signup", False)