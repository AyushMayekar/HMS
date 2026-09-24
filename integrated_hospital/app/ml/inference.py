"""
ML inference utilities.
Model loading, feature building, and prediction helpers.
"""
from __future__ import annotations

import os
from typing import Any

from app.config.settings import get_settings
from app.utils.logger import log_error, log_info


def load_model(model_name: str) -> Any | None:
    """
    Load a saved sklearn model artifact from disk.

    Artifacts shipped with the app are ``.pkl`` (joblib) files under
    ``settings.ml_model_path`` (defaults to ``app/ml/models``). A ``.joblib``
    extension is tried as a fallback for locally trained variants.
    Returns None if the model is not available.
    """
    settings = get_settings()
    candidates = [
        os.path.join(settings.ml_model_path, f"{model_name}.pkl"),
        os.path.join(settings.ml_model_path, f"{model_name}.joblib"),
    ]
    model_path = next((p for p in candidates if os.path.exists(p)), None)

    if model_path is None:
        log_info(f"Model file not found: {candidates[0]} - using fallback")
        return None

    try:
        import joblib
        model = joblib.load(model_path)
        log_info(f"Model loaded successfully: {model_name}")
        return model
    except Exception as exc:
        log_error(f"Failed to load model: {model_name}", exception_type=type(exc).__name__)
        return None


def prepare_features_for_model(
    features: dict[str, Any],
    feature_names: list[str],
) -> dict[str, Any]:
    """Prepare feature dictionary for model input, selecting only required features."""
    return {k: features.get(k, 0) for k in feature_names}
