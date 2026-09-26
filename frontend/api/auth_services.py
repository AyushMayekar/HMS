"""
Authentication API service module.
"""
from __future__ import annotations

from typing import Any, Optional

from frontend.api.client import APIResponse, get_api_client
from frontend.api.endpoints import (
    AUTH_LOGOUT,
    AUTH_ME,
    AUTH_REQUEST_OTP,
    AUTH_SIGNUP,
    AUTH_VERIFY_OTP,
    AUTH_VERIFY_SIGNUP_OTP,
)


class AuthService:
    """Service for authentication operations."""

    def __init__(self, client: Any = None):
        self.client = client or get_api_client()

    def request_otp(self, email: str) -> APIResponse:
        """Request an OTP for login."""
        payload = {"email": email}
        return self.client.post(AUTH_REQUEST_OTP, json_data=payload)

    def verify_otp(self, email: str, otp: str) -> APIResponse:
        """Verify OTP and return session."""
        payload = {"email": email, "otp": otp}
        return self.client.post(AUTH_VERIFY_OTP, json_data=payload)

    def signup(
        self,
        full_name: str,
        email: str,
        phone: str,
        date_of_birth: str,
        gender: str,
    ) -> APIResponse:
        """Start registration by sending signup OTP."""
        payload = {
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "date_of_birth": date_of_birth,
            "gender": gender,
        }
        return self.client.post(AUTH_SIGNUP, json_data=payload)

    def verify_signup_otp(self, email: str, otp: str) -> APIResponse:
        """Verify signup OTP and create account."""
        payload = {"email": email, "otp": otp}
        return self.client.post(AUTH_VERIFY_SIGNUP_OTP, json_data=payload)

    def get_me(self) -> APIResponse:
        """Get current user profile."""
        return self.client.get(AUTH_ME)

    def logout(self) -> APIResponse:
        """Revoke the current session server-side (refresh token)."""
        return self.client.post(AUTH_LOGOUT)