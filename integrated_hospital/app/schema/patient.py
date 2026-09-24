from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, field_validator


class BookAppointmentRequest(BaseModel):
    doctor_id: str = Field(min_length=1, description="UUID of the doctor")
    availability_id: str = Field(min_length=1, description="UUID of the doctor availability slot")
    reason: str | None = Field(default=None, max_length=500, description="Reason for appointment")


class PatientRescheduleRequest(BaseModel):
    new_availability_id: str = Field(min_length=1, description="Target doctor availability slot UUID")


class PatientCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class CreatePaymentRequest(BaseModel):
    """
    Payment request.

    ``amount`` is intentionally absent: the payable amount is always read
    from the appointment's invoice_amount on the server.
    """

    appointment_id: str = Field(min_length=1, description="UUID of the appointment")
    currency: str = Field(default="INR", description="Currency code")
    payment_method: Literal["upi", "card", "cash"] = "upi"
    insurance_used: bool = Field(default=False, description="Whether insurance is used")
    claim_required: bool = Field(default=False, description="Whether insurance claim is required")


class SubmitFeedbackRequest(BaseModel):
    appointment_id: str = Field(min_length=1, description="UUID of the appointment")
    rating: int = Field(ge=1, le=5, description="Rating from 1 (poor) to 5 (excellent)")
    comment: str | None = Field(default=None, max_length=1000, description="Optional feedback comment")
    feedback_channel: str = Field(default="form", description="Submission channel: form, email, in_app")

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, value: int) -> int:
        if not 1 <= value <= 5:
            raise ValueError("Rating must be between 1 and 5")
        return value
