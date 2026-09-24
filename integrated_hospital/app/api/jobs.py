"""
Internal job API routes.

POST /internal/jobs/no-show-predictions — staff/admin-triggered batch scoring
of the 24h no-show prediction window (PROJECT CONTEXT §9). Protected: this is
not an ordinary public application route. The same service function can be
called by an external scheduler later; behavior stays identical.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.dependencies.auth import AuthContext, require_staff_or_admin
from app.services.prediction_service import run_no_show_prediction_job

router = APIRouter(
    prefix="/internal/jobs",
    tags=["Internal Jobs"],
)


@router.post("/no-show-predictions", status_code=status.HTTP_200_OK,
             summary="Score the 24h no-show prediction window")
def no_show_predictions_job(
    auth: AuthContext = Depends(require_staff_or_admin),
):
    """
    Find booked appointments scheduled within the next 24 hours, build their
    pre-outcome feature vectors, run the versioned no-show model, and write
    prediction_logs. Idempotent: appointments scored with the current model
    version inside the re-scoring interval are skipped.
    """
    result = run_no_show_prediction_job()
    return {"success": True, "data": result}
