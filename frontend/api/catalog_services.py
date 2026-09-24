"""
Catalog, Agent, and RAG API service modules.
"""
from __future__ import annotations

from typing import Any, Optional

from frontend.api.client import APIResponse, get_api_client
from frontend.api.endpoints import (
    CATALOG_AVAILABILITY,
    CATALOG_DEPARTMENTS,
    CATALOG_DOCTORS,
    AGENT_CHAT,
    RAG_SEARCH,
    RAG_REINDEX,
)


class CatalogService:
    """Service for catalog operations (departments, doctors, availability)."""

    def __init__(self, client: Any = None):
        self.client = client or get_api_client()

    def departments(self) -> APIResponse:
        """List active departments."""
        return self.client.get(CATALOG_DEPARTMENTS)

    def doctors(self, department_id: Optional[str] = None) -> APIResponse:
        """List active doctors."""
        params = {}
        if department_id:
            params["department_id"] = department_id
        return self.client.get(CATALOG_DOCTORS, params=params)

    def availability(
        self,
        department_id: Optional[str] = None,
        doctor_id: Optional[str] = None,
        slot_date: Optional[str] = None,
    ) -> APIResponse:
        """List available slots."""
        params = {}
        if department_id:
            params["department_id"] = department_id
        if doctor_id:
            params["doctor_id"] = doctor_id
        if slot_date:
            params["slot_date"] = slot_date
        return self.client.get(CATALOG_AVAILABILITY, params=params)


class AgentService:
    """Service for AI Agent chat operations."""

    def __init__(self, client: Any = None):
        self.client = client or get_api_client()

    def chat(self, query: str, thread_id: Optional[str] = None) -> APIResponse:
        """Chat with the AI agent.

        Unlike the rest of the API the agent endpoint returns its payload at
        the top level (``{success, response, request_id, thread_id,
        interrupt}``) instead of a ``data`` envelope, so the body is
        normalised here:

        ``data = {"response": str, "interrupt": dict|None, "thread_id": str}``

        ``interrupt`` is set while the agent is waiting for details, a choice,
        or a confirmation; passing the returned ``thread_id`` back on the next
        call resumes that conversation. Agent calls run with the longer agent
        timeout because they invoke an LLM.
        """
        from frontend.config import CONFIG

        payload: dict[str, Any] = {"query": query}
        if thread_id:
            payload["thread_id"] = thread_id

        response = self.client.post(
            AGENT_CHAT,
            json_data=payload,
            timeout=CONFIG.agent_timeout,
        )
        if not response.success:
            # Transport/HTTP failure: error_code and error_message are already
            # populated by the client.
            return response

        body = response.raw if isinstance(response.raw, dict) else {}

        if body.get("success") is False:
            # 200 with an in-band failure — the assistant's own message is the
            # most useful thing to show the user.
            return APIResponse(
                success=False,
                error_code="AGENT_ERROR",
                error_message=body.get("response")
                or "The assistant could not complete that request. Please try again.",
                request_id=response.request_id,
                status_code=response.status_code,
            )

        return APIResponse(
            success=True,
            data={
                "response": body.get("response"),
                "interrupt": body.get("interrupt"),
                "thread_id": body.get("thread_id"),
            },
            request_id=response.request_id,
            status_code=response.status_code,
        )


class RAGService:
    """Service for RAG/Knowledge Base operations."""

    def __init__(self, client: Any = None):
        self.client = client or get_api_client()

    def search(self, query: str, top_k: int = 4) -> APIResponse:
        """Search the knowledge base."""
        params = {"query": query, "top_k": top_k}
        return self.client.get(RAG_SEARCH, params=params)

    def reindex(self) -> APIResponse:
        """Reindex the knowledge base (admin only)."""
        return self.client.post(RAG_REINDEX)
