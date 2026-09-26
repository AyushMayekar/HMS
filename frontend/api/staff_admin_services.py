"""
Staff and Admin API service modules.
"""
from __future__ import annotations

from typing import Any, Optional

from frontend.api.client import APIResponse, get_api_client
from frontend.api.endpoints import (
    ADMIN_AUDIT_LOGS,
    STAFF_APPOINTMENTS_CHECK_IN,
    STAFF_APPOINTMENTS_GET,
    STAFF_APPOINTMENTS_LIST,
    STAFF_APPOINTMENTS_NO_SHOW,
    STAFF_APPOINTMENTS_SERVICE_END,
    STAFF_APPOINTMENTS_SERVICE_START,
    STAFF_REMINDERS_CREATE,
    STAFF_REMINDERS_LIST,
    ADMIN_USERS_CREATE_STAFF,
    ADMIN_USERS_GET,
    ADMIN_USERS_LIST,
    ADMIN_USERS_UPDATE,
    DEPARTMENTS_CREATE,
    DEPARTMENTS_LIST,
    DEPARTMENTS_UPDATE,
    DOCTORS_CREATE,
    DOCTORS_LIST,
    DOCTORS_UPDATE,
)


class StaffAppointmentService:
    """Service for staff appointment operations."""

    def __init__(self, client: Any = None):
        self.client = client or get_api_client()

    def list(
        self,
        status: Optional[str] = None,
        department_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> APIResponse:
        """List all appointments (staff/admin scope)."""
        params = {"limit": limit, "offset": offset}
        if status:
            params["appointment_status"] = status
        if department_id:
            params["department_id"] = department_id
        return self.client.get(STAFF_APPOINTMENTS_LIST, params=params)

    def get(self, appointment_id: str) -> APIResponse:
        """Get a single appointment by ID."""
        endpoint = STAFF_APPOINTMENTS_GET.format(appointment_id=appointment_id)
        return self.client.get(endpoint)

    def check_in(self, appointment_id: str) -> APIResponse:
        """Check in a patient."""
        endpoint = STAFF_APPOINTMENTS_CHECK_IN.format(appointment_id=appointment_id)
        return self.client.post(endpoint)

    def start_service(self, appointment_id: str) -> APIResponse:
        """Start service for an appointment."""
        endpoint = STAFF_APPOINTMENTS_SERVICE_START.format(appointment_id=appointment_id)
        return self.client.post(endpoint)

    def end_service(self, appointment_id: str) -> APIResponse:
        """End service for an appointment."""
        endpoint = STAFF_APPOINTMENTS_SERVICE_END.format(appointment_id=appointment_id)
        return self.client.post(endpoint)

    def mark_no_show(self, appointment_id: str) -> APIResponse:
        """Mark an appointment as no-show."""
        endpoint = STAFF_APPOINTMENTS_NO_SHOW.format(appointment_id=appointment_id)
        return self.client.post(endpoint)


class StaffReminderService:
    """Service for staff reminder operations."""

    def __init__(self, client: Any = None):
        self.client = client or get_api_client()

    def create(
        self,
        appointment_id: str,
        reminder_type: str = "in_app",
        hours_before_appointment: float = 24.0,
        message: str = "",
    ) -> APIResponse:
        """Create a reminder for an appointment."""
        endpoint = STAFF_REMINDERS_CREATE.format(appointment_id=appointment_id)
        payload = {
            "reminder_type": reminder_type,
            "hours_before_appointment": hours_before_appointment,
            "message": message,
        }
        return self.client.post(endpoint, json_data=payload)

    def list(self, limit: int = 50, offset: int = 0) -> APIResponse:
        """List all reminders."""
        return self.client.get(STAFF_REMINDERS_LIST, params={"limit": limit, "offset": offset})


class AdminUserService:
    """Service for admin user management."""

    def __init__(self, client: Any = None):
        self.client = client or get_api_client()

    def list(
        self,
        role: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> APIResponse:
        """List all users."""
        params = {"limit": limit, "offset": offset}
        if role:
            params["role"] = role
        if status:
            params["status_filter"] = status
        return self.client.get(ADMIN_USERS_LIST, params=params)

    def get(self, user_id: str) -> APIResponse:
        """Get a single user by ID."""
        endpoint = ADMIN_USERS_GET.format(user_id=user_id)
        return self.client.get(endpoint)

    def update(self, user_id: str, role: Optional[str] = None, status: Optional[str] = None) -> APIResponse:
        """Update a user's role or status."""
        endpoint = ADMIN_USERS_UPDATE.format(user_id=user_id)
        payload = {}
        if role:
            payload["role"] = role
        if status:
            payload["status"] = status
        return self.client.patch(endpoint, json_data=payload)

    def create_staff(
        self,
        full_name: str,
        email: str,
        phone: Optional[str] = None,
        role: str = "staff",
    ) -> APIResponse:
        """Create a staff/admin user.

        Phone is optional — it is omitted from the request when empty so
        the backend never receives an empty-string value it would reject.
        Sign-in for the new account happens via the emailed 8-digit OTP
        (no password field exists by design).
        """
        params: dict[str, Any] = {
            "full_name": full_name,
            "email": email,
            "role": role,
        }
        if phone:
            params["phone"] = phone
        return self.client.post(ADMIN_USERS_CREATE_STAFF, params=params)


class AuditLogService:
    """Service for the admin audit-log viewer."""

    def __init__(self, client: Any = None):
        self.client = client or get_api_client()

    def list(self, limit: int = 50, offset: int = 0) -> APIResponse:
        """List audit logs, most recent first."""
        return self.client.get(ADMIN_AUDIT_LOGS, params={"limit": limit, "offset": offset})


class DepartmentAdminService:
    """Service for department management (admin)."""

    def __init__(self, client: Any = None):
        self.client = client or get_api_client()

    def list(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> APIResponse:
        """List all departments."""
        params = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        return self.client.get(DEPARTMENTS_LIST, params=params)

    def create(
        self,
        name: str,
        description: str,
        information: str,
        status: str = "active",
    ) -> APIResponse:
        """Create a department."""
        payload = {
            "name": name,
            "description": description,
            "information": information,
            "status": status,
        }
        return self.client.post(DEPARTMENTS_CREATE, json_data=payload)

    def update(
        self,
        department_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        information: Optional[str] = None,
        status: Optional[str] = None,
    ) -> APIResponse:
        """Update a department."""
        endpoint = DEPARTMENTS_UPDATE.format(department_id=department_id)
        payload = {}
        if name is not None:
            payload["name"] = name
        if description is not None:
            payload["description"] = description
        if information is not None:
            payload["information"] = information
        if status is not None:
            payload["status"] = status
        return self.client.patch(endpoint, json_data=payload)


class DoctorAdminService:
    """Service for doctor management (admin)."""

    def __init__(self, client: Any = None):
        self.client = client or get_api_client()

    def list(
        self,
        department_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> APIResponse:
        """List all doctors."""
        params = {"limit": limit, "offset": offset}
        if department_id:
            params["department_id"] = department_id
        if status:
            params["status"] = status
        return self.client.get(DOCTORS_LIST, params=params)

    def create(
        self,
        department_id: str,
        full_name: str,
        specialization: str,
        experience_years: int,
        status: str = "active",
        slot_schedule: Optional[dict] = None,
    ) -> APIResponse:
        """Create a doctor, optionally generating its bookable slots.

        ``slot_schedule`` is only sent when supplied, so requests without it
        behave exactly as before this option existed.
        """
        payload = {
            "department_id": department_id,
            "full_name": full_name,
            "specialization": specialization,
            "experience_years": experience_years,
            "status": status,
        }
        if slot_schedule is not None:
            payload["slot_schedule"] = slot_schedule
        return self.client.post(DOCTORS_CREATE, json_data=payload)

    def update(
        self,
        doctor_id: str,
        department_id: Optional[str] = None,
        full_name: Optional[str] = None,
        specialization: Optional[str] = None,
        experience_years: Optional[int] = None,
        status: Optional[str] = None,
    ) -> APIResponse:
        """Update a doctor."""
        endpoint = DOCTORS_UPDATE.format(doctor_id=doctor_id)
        payload = {}
        if department_id is not None:
            payload["department_id"] = department_id
        if full_name is not None:
            payload["full_name"] = full_name
        if specialization is not None:
            payload["specialization"] = specialization
        if experience_years is not None:
            payload["experience_years"] = experience_years
        if status is not None:
            payload["status"] = status
        return self.client.patch(endpoint, json_data=payload)