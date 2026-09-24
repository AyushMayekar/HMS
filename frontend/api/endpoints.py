"""
API endpoint definitions for the Meridian Care backend.
All endpoints are defined here as constants for easy maintenance.
"""
from __future__ import annotations

# Authentication
AUTH_REQUEST_OTP = "/auth/request-otp"
AUTH_VERIFY_OTP = "/auth/verify-otp"
AUTH_SIGNUP = "/auth/signup"
AUTH_VERIFY_SIGNUP_OTP = "/auth/verify-signup-otp"
AUTH_ME = "/users/me"

# Catalog (read-only reference data)
CATALOG_DEPARTMENTS = "/catalog/departments"
CATALOG_DOCTORS = "/catalog/doctors"
CATALOG_AVAILABILITY = "/catalog/availability"

# Departments (CRUD)
DEPARTMENTS_LIST = "/departments"
DEPARTMENTS_GET = "/departments/{department_id}"
DEPARTMENTS_CREATE = "/departments"
DEPARTMENTS_UPDATE = "/departments/{department_id}"

# Doctors (CRUD)
DOCTORS_LIST = "/doctors"
DOCTORS_GET = "/doctors/{doctor_id}"
DOCTORS_CREATE = "/doctors"
DOCTORS_UPDATE = "/doctors/{doctor_id}"

# Patient Appointments
PATIENT_APPOINTMENTS_BOOK = "/patient/appointments"
PATIENT_APPOINTMENTS_LIST = "/patient/appointments"
PATIENT_APPOINTMENTS_GET = "/patient/appointments/{appointment_id}"
PATIENT_APPOINTMENTS_RESCHEDULE = "/patient/appointments/{appointment_id}/reschedule"
PATIENT_APPOINTMENTS_CANCEL = "/patient/appointments/{appointment_id}/cancel"

# Patient Payments
PATIENT_PAYMENTS_CREATE = "/patient/payments"
PATIENT_PAYMENTS_LIST = "/patient/payments"
PATIENT_PAYMENTS_GET = "/patient/payments/{payment_id}"

# Patient Feedback
PATIENT_FEEDBACK_SUBMIT = "/patient/feedback"
PATIENT_FEEDBACK_LIST = "/patient/feedback"
PATIENT_FEEDBACK_GET = "/patient/feedback/{feedback_id}"

# Patient Admin Requests
PATIENT_ADMIN_REQUESTS_CREATE = "/patient/admin-requests"
PATIENT_ADMIN_REQUESTS_LIST = "/patient/admin-requests"
PATIENT_ADMIN_REQUESTS_GET = "/patient/admin-requests/{request_id}"

# Patient Reminders
PATIENT_REMINDERS_LIST = "/patient/reminders"

# Staff Appointments
STAFF_APPOINTMENTS_LIST = "/staff/appointments"
STAFF_APPOINTMENTS_GET = "/staff/appointments/{appointment_id}"
STAFF_APPOINTMENTS_CHECK_IN = "/staff/appointments/{appointment_id}/check-in"
STAFF_APPOINTMENTS_SERVICE_START = "/staff/appointments/{appointment_id}/service-start"
STAFF_APPOINTMENTS_SERVICE_END = "/staff/appointments/{appointment_id}/service-end"
STAFF_APPOINTMENTS_NO_SHOW = "/staff/appointments/{appointment_id}/no-show"

# Staff Reminders
STAFF_REMINDERS_CREATE = "/staff/reminders/{appointment_id}"
STAFF_REMINDERS_LIST = "/staff/reminders"

# Doctor clinical workflow
DOCTOR_PROFILE = "/doctor/profile"
DOCTOR_APPOINTMENTS_LIST = "/doctor/appointments"
DOCTOR_APPOINTMENTS_GET = "/doctor/appointments/{appointment_id}"
DOCTOR_START_SERVICE = "/doctor/appointments/{appointment_id}/start-service"
DOCTOR_END_SERVICE = "/doctor/appointments/{appointment_id}/end-service"
DOCTOR_PRESCRIPTIONS_CREATE = "/doctor/appointments/{appointment_id}/prescriptions"
DOCTOR_DIAGNOSTIC_ORDERS_CREATE = "/doctor/appointments/{appointment_id}/diagnostic-orders"
DOCTOR_MEDICINES = "/doctor/medicines"
DOCTOR_DIAGNOSTIC_TESTS = "/doctor/diagnostic-tests"

# Admin Users
ADMIN_USERS_LIST = "/admin/users"
ADMIN_USERS_GET = "/admin/users/{user_id}"
ADMIN_USERS_UPDATE = "/admin/users/{user_id}"
ADMIN_USERS_CREATE_STAFF = "/admin/users"

# Analytics
ANALYTICS_APPOINTMENTS = "/analytics/appointments"
ANALYTICS_NO_SHOW_RISK = "/analytics/no-show-risk"
ANALYTICS_BED_DEMAND = "/analytics/bed-demand"
ANALYTICS_BED_DEMAND_DEPT = "/analytics/bed-demand/department/{department_name}"
ANALYTICS_PATIENT_FLOW = "/analytics/patient-flow"
ANALYTICS_PATIENT_FLOW_DEPT = "/analytics/patient-flow/department/{department_name}"
ANALYTICS_BILLING = "/analytics/billing"
ANALYTICS_SATISFACTION = "/analytics/satisfaction"
ANALYTICS_BOOKING_CHANNEL = "/analytics/booking-channel"
ANALYTICS_NO_SHOW = "/analytics/no-show"
ANALYTICS_WAITING_TIME = "/analytics/waiting-time"

# Predictions
PREDICTIONS_NO_SHOW = "/predictions/no-show/{appointment_id}"
PREDICTIONS_WAITING_TIME = "/predictions/waiting-time/{appointment_id}"
PREDICTIONS_BOOKING_WAITING_TIME = "/predictions/waiting-time/booking/{appointment_id}"
PREDICTIONS_BOOKING_WAITING_TIME_PREVIEW = "/predictions/waiting-time/booking-preview"
PREDICTIONS_BED_DEMAND = "/predictions/bed-demand"
PREDICTIONS_PATIENT_FLOW = "/predictions/patient-flow"

# Admin audit logs
ADMIN_AUDIT_LOGS = "/admin/audit-logs"

# AI Agent
AGENT_CHAT = "/agent/chat"

# RAG / Knowledge Base
RAG_SEARCH = "/rag/search"
RAG_REINDEX = "/rag/reindex"


def format_endpoint(template: str, **kwargs: str) -> str:
    """Format an endpoint template with path parameters."""
    return template.format(**kwargs)