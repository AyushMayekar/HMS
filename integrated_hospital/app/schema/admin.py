from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class AdminUpdateUserRequest(BaseModel):
    role: Literal["patient", "staff", "admin"] | None = None
    status: Literal["active", "inactive"] | None = None


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


class CreateDoctorRequest(BaseModel):
    department_id: str = Field(min_length=1)
    full_name: str = Field(min_length=1, max_length=100)
    specialization: str = Field(min_length=1, max_length=100)
    experience_years: int = Field(ge=0, le=50)
    status: Literal["active", "inactive"] = "active"


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
