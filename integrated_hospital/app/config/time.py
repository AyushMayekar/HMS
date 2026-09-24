from datetime import datetime
from zoneinfo import ZoneInfo

from app.config.settings import get_settings


def get_current_datetime_context() -> str:
    """Get formatted current date/time context for the LLM."""
    settings = get_settings()
    now = datetime.now(ZoneInfo(settings.hospital_timezone))

    return (
        f"Current date: {now.strftime('%Y-%m-%d')} "
        f"({now.strftime('%d %B %Y')})\n"
        f"Current time: {now.strftime('%I:%M %p')}\n"
        f"Timezone: {settings.hospital_timezone}"
    )


def get_current_datetime() -> datetime:
    """Get current datetime in hospital timezone."""
    settings = get_settings()
    return datetime.now(ZoneInfo(settings.hospital_timezone))