"""
API client for communicating with the Meridian Care backend.
Handles authentication, token management, and HTTP requests.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urljoin

import requests

from frontend.config import API_PREFIX, CONFIG
from frontend.utils.session import get_access_token


@dataclass
class APIResponse:
    """Standardized API response wrapper."""
    success: bool
    data: Any = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    request_id: Optional[str] = None
    status_code: int = 200
    # Full decoded JSON body. Most endpoints wrap their payload in ``data``;
    # a few (the AI agent) return it at the top level, so callers that need
    # those fields read ``raw`` instead.
    raw: Any = None

    @classmethod
    def from_response(cls, response: requests.Response) -> "APIResponse":
        """Create APIResponse from requests.Response."""
        request_id = response.headers.get("X-Request-ID")
        try:
            payload = response.json()
        except json.JSONDecodeError:
            payload = {}

        if response.status_code >= 400:
            error = payload.get("error", {})
            # FastAPI's HTTPException responses use ``detail`` instead of the
            # structured ``error`` object.
            message = error.get("message") or payload.get("detail") \
                or f"Request failed with status {response.status_code}"
            return cls(
                success=False,
                error_code=error.get("code", f"HTTP_{response.status_code}"),
                error_message=message,
                request_id=request_id or payload.get("request_id"),
                status_code=response.status_code,
                raw=payload,
            )

        return cls(
            success=payload.get("success", True),
            data=payload.get("data"),
            request_id=request_id or payload.get("request_id"),
            status_code=response.status_code,
            raw=payload,
        )

    def raise_for_error(self) -> "APIResponse":
        """Raise an exception if the response indicates an error."""
        if not self.success:
            raise APIError(self.error_code, self.error_message, self.request_id, self.status_code)
        return self


class APIError(Exception):
    """API error with structured information."""
    def __init__(
        self,
        code: Optional[str],
        message: Optional[str],
        request_id: Optional[str] = None,
        status_code: int = 500,
    ):
        self.code = code
        self.message = message
        self.request_id = request_id
        self.status_code = status_code
        super().__init__(f"[{code}] {message}")


class APIClient:
    """HTTP client for the Meridian Care API with token management."""

    def __init__(self, base_url: str = None, timeout: int = None):
        self.base_url = base_url or CONFIG.api_base_url
        self.timeout = timeout or CONFIG.request_timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def _get_auth_header(self) -> dict[str, str]:
        """Get authorization header from session state."""
        token = get_access_token()
        if token:
            return {"Authorization": f"Bearer {token}"}
        return {}

    def _request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[dict] = None,
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
        timeout: Optional[int] = None,
    ) -> APIResponse:
        """Make an HTTP request with authentication."""
        url = urljoin(self.base_url, f"{API_PREFIX}{endpoint}")

        request_headers = self._get_auth_header()
        if headers:
            request_headers.update(headers)

        try:
            response = self.session.request(
                method=method,
                url=url,
                json=json_data,
                params=params,
                headers=request_headers,
                timeout=timeout or self.timeout,
            )
        except requests.exceptions.Timeout:
            return APIResponse(
                success=False,
                error_code="TIMEOUT",
                error_message="Request timed out. Please try again.",
                status_code=408,
            )
        except requests.exceptions.ConnectionError:
            return APIResponse(
                success=False,
                error_code="CONNECTION_ERROR",
                error_message="Unable to connect to the server. Please check your connection.",
                status_code=503,
            )
        except requests.exceptions.RequestException as e:
            return APIResponse(
                success=False,
                error_code="REQUEST_ERROR",
                error_message=f"Request failed: {str(e)}",
                status_code=500,
            )

        return APIResponse.from_response(response)

    # Convenience methods
    def get(self, endpoint: str, params: Optional[dict] = None, timeout: Optional[int] = None) -> APIResponse:
        return self._request("GET", endpoint, params=params, timeout=timeout)

    def post(
        self,
        endpoint: str,
        json_data: Optional[dict] = None,
        params: Optional[dict] = None,
        timeout: Optional[int] = None,
    ) -> APIResponse:
        return self._request("POST", endpoint, json_data=json_data, params=params, timeout=timeout)

    def patch(self, endpoint: str, json_data: Optional[dict] = None) -> APIResponse:
        return self._request("PATCH", endpoint, json_data=json_data)

    def delete(self, endpoint: str, json_data: Optional[dict] = None) -> APIResponse:
        return self._request("DELETE", endpoint, json_data=json_data)


# Singleton client instance
_client: Optional[APIClient] = None


def get_api_client() -> APIClient:
    """Get or create the singleton API client."""
    global _client
    if _client is None:
        _client = APIClient()
    return _client


def set_api_client(client: APIClient) -> None:
    """Set a custom API client (useful for testing)."""
    global _client
    _client = client