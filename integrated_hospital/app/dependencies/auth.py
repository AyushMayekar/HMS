"""
Authentication and authorization dependencies.
Provides FastAPI dependencies for JWT validation, role checks, and profile loading.
The backend is authoritative for identity and authorization.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client

from app.config.settings import get_supabase_client, get_supabase_admin_client
from app.utils.logger import log_error


security = HTTPBearer(auto_error=False)


@dataclass
class AuthContext:
    """Authenticated user context derived from JWT."""
    user: object
    access_token: str
    profile: dict | None = None


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> AuthContext:
    """
    Authenticate the request using the Supabase access token.
    Derives user identity from the JWT - never trusts client-supplied user_id.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = credentials.credentials

    try:
        supabase = get_supabase_client()
        response = supabase.auth.get_user(access_token)
        user = response.user

        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired access token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return AuthContext(
            user=user,
            access_token=access_token,
        )

    except HTTPException:
        raise

    except Exception:
        log_error("JWT validation failed", exception_type="auth_error")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _load_profile(auth: AuthContext) -> AuthContext:
    """Load and validate the user's application profile from the database."""
    if auth.profile is not None:
        return auth

    supabase = get_supabase_admin_client()

    try:
        response = (
            supabase
            .table("profiles")
            .select("*")
            .eq("user_id", auth.user.id)
            .single()
            .execute()
        )
        profile = response.data

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user profile could not be verified.",
        ) from exc

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user profile not found.",
        )

    if profile.get("status") != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive or pending approval.",
        )

    auth.profile = profile
    return auth


def get_current_profile(
    auth: AuthContext = Depends(get_current_user),
) -> AuthContext:
    """Load the authenticated user's profile and verify account is active."""
    return _load_profile(auth)


def require_admin(
    auth: AuthContext = Depends(get_current_profile),
) -> AuthContext:
    """Require admin role."""
    if auth.profile.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required.",
        )
    return auth


def require_staff(
    auth: AuthContext = Depends(get_current_profile),
) -> AuthContext:
    """Require staff role."""
    if auth.profile.get("role") != "staff":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff privileges required.",
        )
    return auth


def require_staff_or_admin(
    auth: AuthContext = Depends(get_current_profile),
) -> AuthContext:
    """Require staff or admin role."""
    if auth.profile.get("role") not in {"staff", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff or Admin privileges required.",
        )
    return auth


def require_patient(
    auth: AuthContext = Depends(get_current_profile),
) -> AuthContext:
    """Require patient role."""
    if auth.profile.get("role") != "patient":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Patient privileges required.",
        )
    return auth


def get_authenticated_supabase_client(
    auth: AuthContext = Depends(get_current_user),
) -> Client:
    """
    Create a per-request Supabase client carrying the user's JWT.
    Database queries made with this client are evaluated by Supabase RLS
    as the authenticated user.
    """
    supabase = get_supabase_client()
    supabase.postgrest.auth(auth.access_token)
    return supabase
