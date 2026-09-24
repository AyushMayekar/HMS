"""
Main FastAPI application.
Meridian Care Hospital Management API.
"""
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.users import router as users_router
from app.api.agent import router as agent_router
from app.api.rag import router as rag_router
from app.api.departments import router as departments_router
from app.api.doctors import router as doctors_router
from app.api.catalog import router as catalog_router
from app.api.patient_appointments import router as patient_appointments_router
from app.api.patient_payments import router as patient_payments_router
from app.api.patient_feedback import router as patient_feedback_router
from app.api.patient_reminders import router as patient_reminders_router
from app.api.patient_admin_requests import router as patient_admin_requests_router
from app.api.staff_appointments import router as staff_appointments_router
from app.api.staff_reminders import router as staff_reminders_router
from app.api.admin_users import router as admin_users_router
from app.api.admin_audit_logs import router as admin_audit_logs_router
from app.api.analytics import router as analytics_router
from app.api.predictions import router as predictions_router
from app.api.jobs import router as jobs_router
from app.utils.exceptions import AppException
from app.utils.logger import log_error, log_info, log_warning


app = FastAPI(
    title="Meridian Care Hospital API",
    version="1.0.0",
    description="AI-Enabled Hospital Management System API",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# REQUEST ID MIDDLEWARE
# ============================================================

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = str(uuid4())
    request.state.request_id = request_id

    log_info(
        "Request started",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )

    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        log_info(
            "Request completed",
            request_id=request_id,
            status_code=response.status_code,
        )

        return response

    except Exception:
        log_error("Unhandled request exception", request_id=request_id)
        raise


# ============================================================
# EXCEPTION HANDLERS
# ============================================================

@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    request_id = getattr(request.state, "request_id", "unknown")

    log_error(
        "Application exception",
        request_id=request_id,
        error_code=exc.error_code,
        status_code=exc.status_code,
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "code": exc.error_code,
                "message": exc.message,
            },
            "request_id": request_id,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", "unknown")

    log_warning("Request validation failed", request_id=request_id, path=request.url.path)

    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Some of the provided information is invalid.",
            },
            "request_id": request_id,
        },
    )


@app.exception_handler(Exception)
async def unexpected_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unknown")

    log_error(
        "Unexpected server error",
        request_id=request_id,
        exception_type=type(exc).__name__,
    )

    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Something went wrong on our side. Please try again later.",
            },
            "request_id": request_id,
        },
    )


# ============================================================
# ROUTER REGISTRATION
# ============================================================

# Authentication
app.include_router(auth_router, prefix="/api/v1/auth")

# User profile
app.include_router(users_router, prefix="/api/v1")

# AI Agent
app.include_router(agent_router, prefix="/api/v1")

# Knowledge base / RAG (search only, no admin management)
app.include_router(rag_router, prefix="/api/v1")

# Catalog (read-only reference data)
app.include_router(catalog_router, prefix="/api/v1")

# Departments (CRUD)
app.include_router(departments_router, prefix="/api/v1")

# Doctors (CRUD)
app.include_router(doctors_router, prefix="/api/v1")

# Patient endpoints
app.include_router(patient_appointments_router, prefix="/api/v1")
app.include_router(patient_payments_router, prefix="/api/v1")
app.include_router(patient_feedback_router, prefix="/api/v1")
app.include_router(patient_reminders_router, prefix="/api/v1")
app.include_router(patient_admin_requests_router, prefix="/api/v1")

# Staff endpoints
app.include_router(staff_appointments_router, prefix="/api/v1")
app.include_router(staff_reminders_router, prefix="/api/v1")

# Admin endpoints
app.include_router(admin_users_router, prefix="/api/v1")
app.include_router(admin_audit_logs_router, prefix="/api/v1")

# Analytics and predictions
app.include_router(analytics_router, prefix="/api/v1")
app.include_router(predictions_router, prefix="/api/v1")
app.include_router(jobs_router)
