"""
Frontend configuration for Meridian Care Hospital Management System.
Centralized configuration for API endpoints, hospital identity, and application settings.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass(frozen=True)
class HospitalIdentity:
    """Single source of truth for hospital identity across the application."""
    name: str = "Meridian Care Multispecialty Hospital"
    short_name: str = "Meridian Care"
    tagline: str = "Connected care for patients, clinicians, and hospital operations"
    address: str = "12 Harmony Avenue, Riverside Medical District, Bengaluru 560001"
    phone: str = "+91 80 4000 1066"
    emergency: str = "1800-000-1066"
    care_desk: str = "24×7 Care Desk"
    email: str = "care@meridiancare.health"
    website: str = "https://meridiancare.health"
    disclaimer: str = (
        "Meridian Care provides hospital information, appointment management, "
        "and administrative services. Content on this platform is not a "
        "substitute for professional medical advice, diagnosis, or treatment."
    )
    # OS emojis render differently per platform (color on Windows, mono on
    # many Linux setups). The Material shortcode is bundled with Streamlit
    # and renders identically everywhere; logo_emoji is kept only for
    # contexts that still reference it.
    logo_emoji: str = "🏥"
    logo_icon: str = ":material/local_hospital:"


@dataclass(frozen=True)
class AppConfig:
    """Application configuration loaded from environment."""
    api_base_url: str = os.getenv("BASE_URL", "http://127.0.0.1:8000")
    api_version: str = "v1"
    request_timeout: int = int(os.getenv("REQUEST_TIMEOUT", "30"))
    hospital_timezone: str = os.getenv("HOSPITAL_TIMEZONE", "Asia/Kolkata")

    # Streamlit configuration
    page_title: str = "Meridian Care Hospital"
    page_icon: str = "🏥"
    layout: str = "wide"
    initial_sidebar_state: str = "collapsed"

    # Feature flags
    enable_analytics_cache: bool = True
    analytics_cache_ttl: int = 60  # seconds

    # LLM-backed agent calls are much slower than plain CRUD calls, so they
    # get their own budget (the backend test suite uses the same 90s).
    agent_timeout: int = int(os.getenv("AGENT_TIMEOUT", "90"))


# Singleton instances
HOSPITAL = HospitalIdentity()
CONFIG = AppConfig()

# API endpoint prefixes
API_PREFIX = f"/api/{CONFIG.api_version}"

# Role constants
ROLE_PATIENT = "patient"
ROLE_STAFF = "staff"
ROLE_ADMIN = "admin"
VALID_ROLES = {ROLE_PATIENT, ROLE_STAFF, ROLE_ADMIN}

# Appointment status constants
APPOINTMENT_STATUSES = {
    "booked": "Booked",
    "confirmed": "Confirmed",
    "arrived": "Arrived",
    "in_consultation": "In Consultation",
    "completed": "Completed",
    "cancelled": "Cancelled",
    "no_show": "No Show",
}

# Payment status constants
PAYMENT_STATUSES = {
    "pending": "Pending",
    "paid": "Paid",
    "failed": "Failed",
    "refunded": "Refunded",
}

# Admin request status constants
REQUEST_STATUSES = {
    "pending": "Pending",
    "in_progress": "In Progress",
    "resolved": "Resolved",
    "rejected": "Rejected",
}

# Admin request categories
REQUEST_CATEGORIES = [
    "refund",
    "appointment_issue",
    "account_issue",
    "admin_requirement",
    "general_support",
    "billing_dispute",
    "medical_records",
    "insurance_claim",
]

# Feedback channels
FEEDBACK_CHANNELS = ["form", "email", "in_app", "phone", "kiosk"]

# Color palette (matching theme.py from streamlit_app_latest2)
COLORS = {
    "navy": "#0B3C5D",
    "teal": "#0D9488",
    "teal_soft": "#E6F7F5",
    "canvas": "#F4F7FA",
    "surface": "#FFFFFF",
    "text": "#0F172A",
    "muted": "#475569",
    "border": "#E2E8F0",
    "danger": "#B91C1C",
    "success": "#047857",
    "warning": "#B45309",
}

# Status pill classes
STATUS_PILL_CLASSES = {
    "booked": "mc-pill-info",
    "confirmed": "mc-pill-info",
    "arrived": "mc-pill-teal",
    "in_consultation": "mc-pill-teal",
    "completed": "mc-pill-success",
    "cancelled": "mc-pill-neutral",
    "no_show": "mc-pill-danger",
    "pending": "mc-pill-warning",
    "paid": "mc-pill-success",
    "failed": "mc-pill-danger",
    "refunded": "mc-pill-info",
    "in_progress": "mc-pill-info",
    "resolved": "mc-pill-success",
    "rejected": "mc-pill-danger",
    "draft": "mc-pill-neutral",
    "review": "mc-pill-warning",
    "published": "mc-pill-success",
    "archived": "mc-pill-neutral",
    "active": "mc-pill-success",
    "inactive": "mc-pill-neutral",
}