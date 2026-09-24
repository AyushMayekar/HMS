"""
Analytics and Predictions API service modules.
"""
from __future__ import annotations

from typing import Any, Optional

from frontend.api.client import APIResponse, get_api_client
from frontend.api.endpoints import (
    ANALYTICS_APPOINTMENTS,
    ANALYTICS_BED_DEMAND,
    ANALYTICS_BED_DEMAND_DEPT,
    ANALYTICS_BILLING,
    ANALYTICS_BOOKING_CHANNEL,
    ANALYTICS_NO_SHOW,
    ANALYTICS_NO_SHOW_RISK,
    ANALYTICS_PATIENT_FLOW,
    ANALYTICS_PATIENT_FLOW_DEPT,
    ANALYTICS_SATISFACTION,
    ANALYTICS_WAITING_TIME,
    PREDICTIONS_BED_DEMAND,
    PREDICTIONS_BOOKING_WAITING_TIME,
    PREDICTIONS_NO_SHOW,
    PREDICTIONS_PATIENT_FLOW,
    PREDICTIONS_WAITING_TIME,
)


class AnalyticsService:
    """Service for analytics operations (staff/admin)."""

    def __init__(self, client: Any = None):
        self.client = client or get_api_client()

    def appointments(
        self,
        department_id: Optional[str] = None,
        days: int = 30,
    ) -> APIResponse:
        """Get appointment analytics."""
        params = {"days": days}
        if department_id:
            params["department_id"] = department_id
        return self.client.get(ANALYTICS_APPOINTMENTS, params=params)

    def no_show_risk(self) -> APIResponse:
        """Get no-show risk queue."""
        return self.client.get(ANALYTICS_NO_SHOW_RISK)

    def bed_demand(
        self,
        department_id: Optional[str] = None,
        view_by: str = "Month",
        range_index: int = 0,
    ) -> APIResponse:
        """Get bed demand analytics."""
        params = {"view_by": view_by, "range_index": range_index}
        if department_id:
            params["department_id"] = department_id
        return self.client.get(ANALYTICS_BED_DEMAND, params=params)

    def bed_demand_department(
        self,
        department_name: str,
        view_by: str = "Month",
        range_index: int = 0,
    ) -> APIResponse:
        """Get bed demand analytics for a specific department."""
        endpoint = ANALYTICS_BED_DEMAND_DEPT.format(department_name=department_name)
        params = {"view_by": view_by, "range_index": range_index}
        return self.client.get(endpoint, params=params)

    def patient_flow(
        self,
        department_id: Optional[str] = None,
        view_by: str = "Month",
        range_index: int = 0,
    ) -> APIResponse:
        """Get patient flow analytics."""
        params = {"view_by": view_by, "range_index": range_index}
        if department_id:
            params["department_id"] = department_id
        return self.client.get(ANALYTICS_PATIENT_FLOW, params=params)

    def patient_flow_department(
        self,
        department_name: str,
        view_by: str = "Month",
        range_index: int = 0,
    ) -> APIResponse:
        """Get patient flow analytics for a specific department."""
        endpoint = ANALYTICS_PATIENT_FLOW_DEPT.format(department_name=department_name)
        params = {"view_by": view_by, "range_index": range_index}
        return self.client.get(endpoint, params=params)

    def billing(
        self,
        department_id: Optional[str] = None,
        days: int = 30,
    ) -> APIResponse:
        """Get billing analytics."""
        params = {"days": days}
        if department_id:
            params["department_id"] = department_id
        return self.client.get(ANALYTICS_BILLING, params=params)

    def satisfaction(
        self,
        department_id: Optional[str] = None,
        days: int = 30,
    ) -> APIResponse:
        """Get satisfaction analytics."""
        params = {"days": days}
        if department_id:
            params["department_id"] = department_id
        return self.client.get(ANALYTICS_SATISFACTION, params=params)

    def booking_channel(
        self,
        department_id: Optional[str] = None,
        view_by: str = "Month",
        range_index: int = 0,
    ) -> APIResponse:
        """Get booking channel analytics."""
        params = {"view_by": view_by, "range_index": range_index}
        if department_id:
            params["department_id"] = department_id
        return self.client.get(ANALYTICS_BOOKING_CHANNEL, params=params)

    def no_show(
        self,
        department_id: Optional[str] = None,
        days: int = 30,
    ) -> APIResponse:
        """Get no-show historical analytics."""
        params = {"days": days}
        if department_id:
            params["department_id"] = department_id
        return self.client.get(ANALYTICS_NO_SHOW, params=params)

    def waiting_time(
        self,
        department_id: Optional[str] = None,
        days: int = 30,
    ) -> APIResponse:
        """Get waiting time analytics."""
        params = {"days": days}
        if department_id:
            params["department_id"] = department_id
        return self.client.get(ANALYTICS_WAITING_TIME, params=params)


class PredictionsService:
    """Service for ML prediction operations (staff/admin)."""

    def __init__(self, client: Any = None):
        self.client = client or get_api_client()

    def no_show(self, appointment_id: str) -> APIResponse:
        """Predict no-show for an appointment."""
        endpoint = PREDICTIONS_NO_SHOW.format(appointment_id=appointment_id)
        return self.client.post(endpoint)

    def waiting_time(self, appointment_id: str) -> APIResponse:
        """Predict waiting time at check-in."""
        endpoint = PREDICTIONS_WAITING_TIME.format(appointment_id=appointment_id)
        return self.client.post(endpoint)

    def booking_waiting_time(self, appointment_id: str) -> APIResponse:
        """Predict waiting time at booking (pre-check-in)."""
        endpoint = PREDICTIONS_BOOKING_WAITING_TIME.format(appointment_id=appointment_id)
        return self.client.post(endpoint)

    def bed_demand(self, target_date: Optional[str] = None) -> APIResponse:
        """Forecast bed demand for departments."""
        payload = {}
        if target_date:
            payload["target_date"] = target_date
        return self.client.post(PREDICTIONS_BED_DEMAND, json_data=payload)

    def patient_flow(self, target_date: Optional[str] = None) -> APIResponse:
        """Forecast patient flow for departments."""
        payload = {}
        if target_date:
            payload["target_date"] = target_date
        return self.client.post(PREDICTIONS_PATIENT_FLOW, json_data=payload)