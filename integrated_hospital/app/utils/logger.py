"""
Structured logging utilities.
Logs are written to stdout with structured fields.
In production, logs should be collected by a log aggregator.
"""
import json
import logging
import sys
from datetime import datetime, timezone


logger = logging.getLogger("hospital_api")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)


def _log(level: str, message: str, **kwargs):
    """Write a structured log entry."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "message": message,
    }
    if kwargs:
        entry["data"] = kwargs

    logger.log(
        getattr(logging, level.upper(), logging.INFO),
        json.dumps(entry, default=str),
    )


def log_info(message: str, **kwargs):
    _log("info", message, **kwargs)


def log_warning(message: str, **kwargs):
    _log("warning", message, **kwargs)


def log_error(message: str, **kwargs):
    _log("error", message, **kwargs)


def log_debug(message: str, **kwargs):
    _log("debug", message, **kwargs)
