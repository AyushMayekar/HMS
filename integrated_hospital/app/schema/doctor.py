from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class CreatePrescriptionRequest(BaseModel):
    """
    Doctor-supplied prescription fields.

    doctor_id, patient_id, unit_charge and total_amount are deliberately
    absent: they are derived by the server from the authenticated profile,
    the appointment and the medicines catalog.
    """

    medicine_id: str = Field(min_length=1, description="UUID of the medicine in the catalog")
    quantity: int = Field(ge=1, le=1000, description="Quantity to dispense")
    dosage: str = Field(min_length=1, max_length=100, description="Dose per intake, e.g. '1 tablet'")
    frequency: str = Field(min_length=1, max_length=100, description="e.g. 'twice daily'")
    duration_days: int = Field(ge=1, le=365, description="Treatment length in days")
    instructions: str | None = Field(default=None, max_length=500, description="Optional patient instructions")


class CreateDiagnosticOrderRequest(BaseModel):
    """
    Doctor-supplied diagnostic order fields.

    doctor_id, patient_id, unit_charge and total_amount are derived by the
    server from the authenticated profile, the appointment and the
    diagnostic_tests catalog.
    """

    test_id: str = Field(min_length=1, description="UUID of the test in the catalog")
    quantity: int = Field(default=1, ge=1, le=100, description="Number of units of this test")
    priority: Literal["routine", "urgent", "stat"] = Field(
        default="routine",
        description="Order priority",
    )
    notes: str | None = Field(default=None, max_length=500, description="Optional clinical notes")
