"""
Authentication service.
Handles OTP-based login/signup via Supabase Auth.
Profile creation happens ONLY after OTP verification.
"""
from supabase_auth.errors import AuthApiError
from datetime import datetime, timezone

from app.config.settings import get_supabase_client, get_supabase_admin_client
from app.utils.exceptions import (
    InvalidOTPError,
    OTPDeliveryError,
    ProfileCreationError,
    ProfileNotFoundError,
    SignupError,
)
from app.utils.logger import log_error, log_info, log_warning


def mask_email(email: str) -> str:
    """Mask email for safe logging."""
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = "*" * len(local)
    else:
        masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked_local}@{domain}"


# ============================================================
# LOGIN
# ============================================================

def send_login_otp(email: str, request_id: str) -> None:
    """Request an OTP for an existing user."""
    masked_email = mask_email(email)
    log_info("OTP request started", request_id=request_id, email=masked_email)

    supabase = get_supabase_client()

    try:
        response = supabase.auth.sign_in_with_otp({
            "email": email,
            "options": {"should_create_user": False},
        })
    except AuthApiError as exc:
        log_error("Supabase OTP request failed", request_id=request_id, email=masked_email)
        raise OTPDeliveryError() from exc

    if response is None:
        log_error("Supabase returned empty OTP response", request_id=request_id, email=masked_email)
        raise OTPDeliveryError()

    log_info("OTP sent successfully", request_id=request_id, email=masked_email)


def verify_login_otp(email: str, otp: str, request_id: str) -> dict:
    """Verify OTP and return authenticated session with profile."""
    masked_email = mask_email(email)
    log_info("OTP verification started", request_id=request_id, email=masked_email)

    supabase = get_supabase_client()

    try:
        response = supabase.auth.verify_otp({
            "email": email,
            "token": otp,
            "type": "email",
        })
    except AuthApiError as exc:
        log_warning("OTP verification rejected", request_id=request_id, email=masked_email)
        raise InvalidOTPError() from exc

    session = response.session
    user = response.user

    if not session or not user:
        log_warning("OTP verification returned no session", request_id=request_id, email=masked_email)
        raise InvalidOTPError()

    supabase.auth.set_session(session.access_token, session.refresh_token)

    log_info("OTP verification successful", request_id=request_id, user_id=user.id)

    # Load application profile
    try:
        profile_response = (
            supabase
            .table("profiles")
            .select("*")
            .eq("user_id", user.id)
            .single()
            .execute()
        )
    except Exception as exc:
        log_error("Profile lookup failed", request_id=request_id, user_id=user.id)
        raise ProfileNotFoundError() from exc

    profile = profile_response.data

    if not profile:
        log_error("Authenticated user has no application profile", request_id=request_id, user_id=user.id)
        raise ProfileNotFoundError()

    log_info("Application profile loaded", request_id=request_id, user_id=user.id, role=profile.get("role"))

    return {
        "user": user,
        "session": session,
        "profile": profile,
    }


# ============================================================
# SIGNUP
# ============================================================

def send_signup_otp(
    *,
    full_name: str,
    email: str,
    phone: str,
    date_of_birth: str,
    gender: str,
    request_id: str,
) -> None:
    """Request an OTP for new user registration."""
    masked_email = mask_email(email)
    log_info("Signup OTP request started", request_id=request_id, email=masked_email)

    supabase = get_supabase_client()

    try:
        response = supabase.auth.sign_in_with_otp({
            "email": email,
            "options": {
                "should_create_user": True,
                "data": {
                    "full_name": full_name,
                    "phone": phone,
                    "date_of_birth": date_of_birth,
                    "gender": gender,
                },
            },
        })
    except AuthApiError as exc:
        log_error("Supabase signup OTP request failed", request_id=request_id, email=masked_email)
        raise SignupError() from exc

    if response is None:
        log_error("Supabase returned empty signup OTP response", request_id=request_id, email=masked_email)
        raise SignupError()

    log_info("Signup OTP sent successfully", request_id=request_id, email=masked_email)


def verify_signup_otp(*, email: str, otp: str, request_id: str) -> dict:
    """Verify signup OTP, create auth user, and create application profile."""
    masked_email = mask_email(email)
    log_info("Signup OTP verification started", request_id=request_id, email=masked_email)

    supabase = get_supabase_client()

    try:
        response = supabase.auth.verify_otp({
            "email": email,
            "token": otp,
            "type": "email",
        })
    except AuthApiError as exc:
        log_warning("Signup OTP verification rejected", request_id=request_id, email=masked_email)
        raise InvalidOTPError() from exc

    session = response.session
    user = response.user

    if not session or not user:
        log_warning("Signup OTP verification returned no session", request_id=request_id, email=masked_email)
        raise InvalidOTPError()

    log_info("Signup OTP verification successful", request_id=request_id, user_id=user.id)

    # Extract registration metadata
    metadata = user.user_metadata or {}
    full_name = metadata.get("full_name")
    phone = metadata.get("phone")
    date_of_birth = metadata.get("date_of_birth")
    gender = metadata.get("gender")

    if not all([full_name, phone, date_of_birth, gender]):
        log_error("Verified signup user is missing registration metadata", request_id=request_id, user_id=user.id)
        raise ProfileCreationError()

    # Create application profile (patient role only via public signup)
    admin_supabase = get_supabase_admin_client()

    try:
        now = datetime.now(timezone.utc)
        profile_response = (
            admin_supabase
            .table("profiles")
            .insert({
                "user_id": user.id,
                "full_name": full_name,
                "email": user.email,
                "role": "patient",
                "phone": phone,
                "date_of_birth": date_of_birth,
                "gender": gender,
                "status": "active",
                "registered_at": now.isoformat(),
            })
            .execute()
        )
    except Exception as exc:
        log_error("Profile creation failed after signup verification", request_id=request_id, user_id=user.id)
        raise ProfileCreationError() from exc

    profile = profile_response.data

    if not profile:
        log_error("Profile creation returned no data", request_id=request_id, user_id=user.id)
        raise ProfileCreationError()

    log_info("Patient profile created successfully", request_id=request_id, user_id=user.id, role="patient")

    return {
        "user": user,
        "session": session,
        "profile": profile[0] if isinstance(profile, list) else profile,
    }
