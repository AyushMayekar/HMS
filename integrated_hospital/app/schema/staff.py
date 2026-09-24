from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class CreateReminderRequest(BaseModel):
    reminder_type: Literal["email", "in_app"] = "in_app"
    hours_before_appointment: float = Field(default=24.0, ge=0, description="Hours before appointment")
    message: str = Field(min_length=1, max_length=500, description="Reminder message")


class StaffUpdateAppointmentRequest(BaseModel):
    appointment_status: Literal["booked", "completed", "cancelled", "no_show"] | None = None
    notes: str | None = Field(default=None, max_length=500)


class StaffCheckInRequest(BaseModel):
    """No request body needed - check-in is an action."""
    pass


class StaffServiceStartRequest(BaseModel):
    """No request body needed - service start is an action."""
    pass


class StaffServiceEndRequest(BaseModel):
    """No request body needed - service end is an action."""
    pass
