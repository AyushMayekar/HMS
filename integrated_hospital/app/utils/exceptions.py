"""
Application exceptions.
All expected business errors inherit from AppException.
The global exception handler in main.py converts these to safe JSON responses.
"""
from __future__ import annotations


class AppException(Exception):
    """Base exception for expected application errors."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        error_code: str = "INTERNAL_ERROR",
    ):
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        super().__init__(message)


# ============================================================
# Auth errors
# ============================================================

class InvalidOTPError(AppException):
    def __init__(self):
        super().__init__(
            message="The OTP is invalid or has expired.",
            status_code=401,
            error_code="INVALID_OTP",
        )


class OTPDeliveryError(AppException):
    def __init__(self):
        super().__init__(
            message="We could not send the OTP right now. Please try again later.",
            status_code=503,
            error_code="OTP_DELIVERY_FAILED",
        )


class ProfileNotFoundError(AppException):
    def __init__(self):
        super().__init__(
            message="Your account profile could not be found. Please contact support.",
            status_code=404,
            error_code="PROFILE_NOT_FOUND",
        )


class AccountAlreadyExistsError(AppException):
    def __init__(self):
        super().__init__(
            message="An account with this email already exists. Please sign in instead.",
            status_code=409,
            error_code="ACCOUNT_ALREADY_EXISTS",
        )


class SignupError(AppException):
    def __init__(self):
        super().__init__(
            message="We could not start your registration. Please try again later.",
            status_code=503,
            error_code="SIGNUP_FAILED",
        )


class ProfileCreationError(AppException):
    def __init__(self):
        super().__init__(
            message="Your email was verified, but we could not complete your account setup. Please contact support.",
            status_code=500,
            error_code="PROFILE_CREATION_FAILED",
        )


class UserCreationError(AppException):
    def __init__(self):
        super().__init__(
            message="The account could not be created. Please try again later.",
            status_code=500,
            error_code="USER_CREATION_FAILED",
        )


# ============================================================
# Authorization errors
# ============================================================

class ForbiddenError(AppException):
    def __init__(self, message: str = "You do not have permission to perform this action."):
        super().__init__(
            message=message,
            status_code=403,
            error_code="FORBIDDEN",
        )


# ============================================================
# Appointment errors
# ============================================================

class AppointmentNotFoundError(AppException):
    def __init__(self, appointment_id: str = ""):
        super().__init__(
            message=f"Appointment '{appointment_id}' not found." if appointment_id else "Appointment not found.",
            status_code=404,
            error_code="APPOINTMENT_NOT_FOUND",
        )


class AvailabilityNotFoundError(AppException):
    def __init__(self, availability_id: str = ""):
        super().__init__(
            message=f"Availability slot '{availability_id}' not found." if availability_id else "Availability slot not found.",
            status_code=404,
            error_code="AVAILABILITY_NOT_FOUND",
        )


class DoctorNotFoundError(AppException):
    def __init__(self, doctor_id: str = ""):
        super().__init__(
            message=f"Doctor '{doctor_id}' not found." if doctor_id else "Doctor not found.",
            status_code=404,
            error_code="DOCTOR_NOT_FOUND",
        )


class MedicineNotFoundError(AppException):
    def __init__(self, medicine_id: str = ""):
        super().__init__(
            message=f"Medicine '{medicine_id}' not found." if medicine_id else "Medicine not found.",
            status_code=404,
            error_code="MEDICINE_NOT_FOUND",
        )


class DiagnosticTestNotFoundError(AppException):
    def __init__(self, test_id: str = ""):
        super().__init__(
            message=f"Diagnostic test '{test_id}' not found." if test_id else "Diagnostic test not found.",
            status_code=404,
            error_code="DIAGNOSTIC_TEST_NOT_FOUND",
        )


class SlotUnavailableError(AppException):
    def __init__(self, message: str = "The selected time slot is not available."):
        super().__init__(
            message=message,
            status_code=409,
            error_code="SLOT_UNAVAILABLE",
        )


class InvalidOperationError(AppException):
    def __init__(self, message: str = "This operation is not allowed."):
        super().__init__(
            message=message,
            status_code=422,
            error_code="INVALID_OPERATION",
        )


class AppointmentInPastError(AppException):
    """Raised when a lifecycle action is attempted after the scheduled start."""

    def __init__(self, message: str | None = None):
        super().__init__(
            message=message or (
                "This appointment's scheduled time is in the past, "
                "so check-in / no-show actions are no longer allowed."
            ),
            status_code=409,
            error_code="CONFLICT",
        )


# ============================================================
# Payment errors
# ============================================================

class PaymentNotFoundError(AppException):
    def __init__(self, payment_id: str = ""):
        super().__init__(
            message=f"Payment '{payment_id}' not found." if payment_id else "Payment not found.",
            status_code=404,
            error_code="PAYMENT_NOT_FOUND",
        )


class PaymentSimulationError(AppException):
    def __init__(self, message: str = "Payment simulation failed. Please try again."):
        super().__init__(
            message=message,
            status_code=500,
            error_code="PAYMENT_SIMULATION_FAILED",
        )


# ============================================================
# Feedback errors
# ============================================================

class FeedbackNotFoundError(AppException):
    def __init__(self, feedback_id: str = ""):
        super().__init__(
            message=f"Feedback '{feedback_id}' not found." if feedback_id else "Feedback not found.",
            status_code=404,
            error_code="FEEDBACK_NOT_FOUND",
        )


class DuplicateFeedbackError(AppException):
    def __init__(self):
        super().__init__(
            message="You have already submitted feedback for this appointment.",
            status_code=409,
            error_code="DUPLICATE_FEEDBACK",
        )


# ============================================================
# Admin request errors
# ============================================================

class AdminRequestNotFoundError(AppException):
    def __init__(self, request_id: str = ""):
        super().__init__(
            message=f"Admin request '{request_id}' not found." if request_id else "Admin request not found.",
            status_code=404,
            error_code="ADMIN_REQUEST_NOT_FOUND",
        )


# ============================================================
# Department errors
# ============================================================

class DepartmentNotFoundError(AppException):
    def __init__(self, department_id: str = ""):
        super().__init__(
            message=f"Department '{department_id}' not found." if department_id else "Department not found.",
            status_code=404,
            error_code="DEPARTMENT_NOT_FOUND",
        )


# ============================================================
# Knowledge base errors
# ============================================================

class DocumentNotFoundError(AppException):
    def __init__(self, document_id: str = ""):
        super().__init__(
            message=f"Knowledge document '{document_id}' not found." if document_id else "Knowledge document not found.",
            status_code=404,
            error_code="DOCUMENT_NOT_FOUND",
        )


class KnowledgeIndexingError(AppException):
    def __init__(self, document_id: str = ""):
        super().__init__(
            message=(
                f"Indexing failed for knowledge document '{document_id}'. Please retry indexing."
                if document_id
                else "Knowledge indexing failed. Please retry indexing."
            ),
            status_code=503,
            error_code="KNOWLEDGE_INDEXING_FAILED",
        )


# ============================================================
# ML errors
# ============================================================

class ModelNotAvailableError(AppException):
    def __init__(self, model_name: str = "ML model"):
        super().__init__(
            message=f"{model_name} is currently unavailable. Please try again later.",
            status_code=503,
            error_code="MODEL_NOT_AVAILABLE",
        )


class PredictionError(AppException):
    def __init__(self, message: str = "Prediction could not be generated."):
        super().__init__(
            message=message,
            status_code=500,
            error_code="PREDICTION_ERROR",
        )
