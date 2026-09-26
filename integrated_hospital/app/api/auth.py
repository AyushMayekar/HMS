"""
Authentication API routes.
OTP-based login and signup via Supabase Auth.
"""
import httpx
from fastapi import APIRouter, Request, status

from app.config.settings import get_settings
from app.schema.auth import (
    RequestOTPRequest,
    VerifyOTPRequest,
    VerifySignupOTPRequest,
    SignupRequest,
)
from app.services.auth_service import (
    send_login_otp,
    send_signup_otp,
    verify_login_otp,
    verify_signup_otp,
)


router = APIRouter(
    prefix="",
    tags=["Authentication"],
)


@router.post("/request-otp", status_code=status.HTTP_200_OK)
def request_otp(payload: RequestOTPRequest, request: Request):
    """Request an OTP for login."""
    request_id = request.state.request_id

    send_login_otp(email=str(payload.email), request_id=request_id)

    return {
        "success": True,
        "message": "A one-time password has been sent to your email address.",
        "request_id": request_id,
    }


@router.post("/verify-otp", status_code=status.HTTP_200_OK)
def verify_otp(payload: VerifyOTPRequest, request: Request):
    """Verify OTP and return authenticated session."""
    request_id = request.state.request_id

    result = verify_login_otp(
        email=str(payload.email),
        otp=payload.otp,
        request_id=request_id,
    )

    user = result["user"]
    session = result["session"]
    profile = result["profile"]

    return {
        "success": True,
        "message": "Authentication successful.",
        "request_id": request_id,
        "data": {
            "user": {"id": user.id, "email": user.email},
            "profile": {
                "user_id": profile["user_id"],
                "full_name": profile.get("full_name"),
                "role": profile.get("role"),
                "status": profile.get("status"),
            },
            "session": {
                "access_token": session.access_token,
                "refresh_token": session.refresh_token,
                "expires_at": session.expires_at,
            },
        },
    }


@router.post("/signup", status_code=status.HTTP_200_OK)
def signup(payload: SignupRequest, request: Request):
    """Start registration by sending signup OTP."""
    request_id = request.state.request_id

    send_signup_otp(
        full_name=payload.full_name,
        email=str(payload.email),
        phone=payload.phone,
        date_of_birth=payload.date_of_birth,
        gender=payload.gender,
        request_id=request_id,
    )

    return {
        "success": True,
        "message": "Your registration has started. A one-time password has been sent to your email address.",
        "request_id": request_id,
    }


@router.post("/verify-signup-otp", status_code=status.HTTP_200_OK)
def verify_signup_otp_endpoint(payload: VerifySignupOTPRequest, request: Request):
    """Verify signup OTP, create auth user and application profile."""
    request_id = request.state.request_id

    result = verify_signup_otp(
        email=str(payload.email),
        otp=payload.otp,
        request_id=request_id,
    )

    user = result["user"]
    session = result["session"]
    profile = result["profile"]

    return {
        "success": True,
        "message": "Account created successfully.",
        "request_id": request_id,
        "data": {
            "user": {"id": user.id, "email": user.email},
            "profile": {
                "user_id": profile["user_id"],
                "full_name": profile.get("full_name"),
                "role": profile.get("role"),
                "status": profile.get("status"),
            },
            "session": {
                "access_token": session.access_token,
                "refresh_token": session.refresh_token,
                "expires_at": session.expires_at,
            },
        },
    }


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout(request: Request):
    """Revoke the caller's Supabase session.

    Access tokens are stateless JWTs and cannot be revoked before they expire,
    so this invalidates the session's *refresh* token (scope=global) instead —
    that is what stops a signed-out session being renewed.

    Always reports success: the frontend clears its own session state
    independently, so an unreachable Supabase never blocks signing out.
    """
    request_id = request.state.request_id
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else ""

    revoked = False
    if token:
        try:
            settings = get_settings()
            if settings.supabase_url:
                httpx.post(
                    f"{settings.supabase_url.rstrip('/')}/auth/v1/logout",
                    params={"scope": "global"},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10.0,
                )
                revoked = True
        except Exception:
            # Best effort — local sign-out must never depend on this.
            revoked = False

    return {
        "success": True,
        "message": "You have been signed out.",
        "request_id": request_id,
        "data": {"revoked": revoked},
    }


@router.get("/me", status_code=status.HTTP_200_OK)
def get_me(request: Request, auth=None):
    """Return authenticated user profile and role."""
    # This is a placeholder - actual implementation uses dependency injection
    return {"message": "Use authenticated endpoint"}
