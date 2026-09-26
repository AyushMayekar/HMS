from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class AdminUpdateUserRequest(BaseModel):
    role: Literal[
        "patient",
        "staff",
        "doctor",
        "admin",
    ] | None = None

    status: Literal[
        "active",
        "inactive",
    ] | None = None

class CreateDepartmentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    information: str = Field(min_length=1, max_length=2000)
    status: Literal["active", "inactive"] = "active"


class UpdateDepartmentRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    information: str | None = None
    status: Literal["active", "inactive"] | None = None


class DoctorSlotSchedule(BaseModel):
    """Optional bookable-slot schedule generated when a doctor is created.

    Ordering/alignment rules are validated here (before any DB write) so an
    invalid schedule can never leave a half-created doctor behind. The
    date-range rules live in ``availability_service.build_availability_rows``
    because they depend on the runtime booking window.
    """

    start_date: date = Field(description="First slot day (YYYY-MM-DD)")
    days: int = Field(default=7, ge=1, le=30, description="Consecutive days to generate")
    start_time: time = Field(default=time(9, 0), description="Daily clinic open (HH:MM)")
    end_time: time = Field(default=time(17, 0), description="Daily clinic close (HH:MM)")
    break_start: time | None = Field(
        default=time(13, 0), description="Break start; null for a continuous day"
    )
    break_end: time | None = Field(
        default=time(14, 0), description="Break end; null for a continuous day"
    )
    slot_minutes: int = Field(default=30, ge=5, le=240, description="Slot length in minutes")
    slot_capacity: int = Field(default=1, ge=1, le=50, description="Patients per slot")

    @staticmethod
    def _minutes(value: time) -> int:
        return value.hour * 60 + value.minute + value.second // 60

    @model_validator(mode="after")
    def _validate_window(self) -> "DoctorSlotSchedule":
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be earlier than end_time.")

        if (self.break_start is None) != (self.break_end is None):
            raise ValueError("break_start and break_end must be provided together, or both be null.")

        windows = [(self.start_time, self.end_time)]
        if self.break_start is not None:
            if not (self.start_time < self.break_start < self.break_end < self.end_time):
                raise ValueError(
                    "The break must sit strictly inside the clinic window "
                    "(start_time < break_start < break_end < end_time)."
                )
            windows = [(self.start_time, self.break_start), (self.break_end, self.end_time)]

        for window_start, window_end in windows:
            window_minutes = self._minutes(window_end) - self._minutes(window_start)
            if window_minutes <= 0:
                raise ValueError("Each daily window must be longer than zero minutes.")
            if window_minutes % self.slot_minutes != 0:
                raise ValueError(
                    f"Window {window_start.strftime('%H:%M')}-{window_end.strftime('%H:%M')} "
                    f"({window_minutes} minutes) must divide evenly into "
                    f"{self.slot_minutes}-minute slots."
                )

        return self


class CreateDoctorRequest(BaseModel):
    department_id: str = Field(min_length=1)
    full_name: str = Field(min_length=1, max_length=100)
    specialization: str = Field(min_length=1, max_length=100)
    experience_years: int = Field(ge=0, le=50)
    status: Literal["active", "inactive"] = "active"
    # Absent/null => no slots are generated (original behaviour, unchanged).
    slot_schedule: DoctorSlotSchedule | None = None


class UpdateDoctorRequest(BaseModel):
    department_id: str | None = None
    full_name: str | None = None
    specialization: str | None = None
    experience_years: int | None = None
    status: Literal["active", "inactive"] | None = None


class CreateAvailabilityRequest(BaseModel):
    doctor_id: str = Field(min_length=1)
    department_id: str = Field(min_length=1)
    slot_date: str = Field(min_length=1, description="Date in YYYY-MM-DD format")
    start_time: str = Field(min_length=1, description="Time in HH:MM format")
    end_time: str = Field(min_length=1, description="Time in HH:MM format")
    slot_capacity: int = Field(default=5, ge=1, le=50)


class AdminResolveRequest(BaseModel):
    status: Literal["in_progress", "resolved", "rejected"]
    resolution: str = Field(min_length=1, max_length=1000)
    assigned_to: str | None = None
