"""
Input validators for the AI agent tools.
These validate user-provided values before passing to services.
"""
import re
from datetime import datetime, date


def validate_book_appointment(
    department: str,
    appointment_date: str,
    appointment_time: str,
) -> dict:
    """Validate appointment booking inputs from the AI agent."""

    if not department or not department.strip():
        return {
            "valid": False,
            "field": "department",
            "message": "Hospital department is required.",
        }

    if not appointment_date or not appointment_date.strip():
        return {
            "valid": False,
            "field": "appointment_date",
            "message": "Appointment date is required.",
        }

    if not appointment_time or not appointment_time.strip():
        return {
            "valid": False,
            "field": "appointment_time",
            "message": "Appointment time is required.",
        }

    # Reject vague time periods
    if appointment_time.lower().strip() in {
        "morning",
        "afternoon",
        "evening",
        "night",
    }:
        return {
            "valid": False,
            "field": "appointment_time",
            "message": (
                "A specific appointment time is required. "
                "For example, 7 PM or 19:00."
            ),
        }

    return {
        "valid": True,
        "message": "",
    }


def validate_admin_request(
    category: str,
    description: str,
) -> dict:
    """Validate admin request inputs from the AI agent."""

    valid_categories = {
        "refund",
        "appointment_issue",
        "account_issue",
        "admin_requirement",
        "general_support",
    }

    if not category or not category.strip():
        return {
            "valid": False,
            "field": "category",
            "message": "Request category is required.",
        }

    if category.lower().strip() not in valid_categories:
        return {
            "valid": False,
            "field": "category",
            "message": f"Invalid category. Must be one of: {', '.join(sorted(valid_categories))}",
        }

    if not description or not description.strip():
        return {
            "valid": False,
            "field": "description",
            "message": "Request description is required.",
        }

    if len(description.strip()) < 10:
        return {
            "valid": False,
            "field": "description",
            "message": "Description must be at least 10 characters long.",
        }

    return {
        "valid": True,
        "message": "",
    }


def parse_appointment_date(date_str: str) -> date | None:
    """Try to parse a date string in various formats."""
    formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d, %Y",
        "%b %d, %Y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue

    return None


def parse_appointment_time(time_str: str) -> str | None:
    """
    Try to parse a time string. Returns normalized HH:MM format.
    Accepts formats like "19:00", "7:00 PM", "7 PM", "1900", etc.
    """
    time_str = time_str.strip()

    # Try 24h format: HH:MM
    match = re.match(r"^(\d{1,2}):(\d{2})$", time_str)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"

    # Try 12h format: H:MM AM/PM or H AM/PM
    match = re.match(
        r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm|AM|PM)$",
        time_str,
    )
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or "0")
        period = match.group(3).lower()

        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0

        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"

    # Try 4-digit no separator: 1900
    match = re.match(r"^(\d{4})$", time_str)
    if match:
        hour = int(time_str[:2])
        minute = int(time_str[2:])
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"

    return None
