"""
RAG service.
Knowledge retrieval operations for the AI assistant.

Retrieval receives the caller's user-scoped (RLS) Supabase client so
published-only visibility is enforced per caller.
"""
from __future__ import annotations

from typing import Any

from supabase import Client

from app.config.rag import (
    DEFAULT_MATCH_THRESHOLD,
    DEFAULT_TOP_K,
)
from app.config.settings import get_supabase_admin_client
from app.rag.ingestion import reindex_all_documents
from app.rag.retriever import retrieve_context
from app.utils.logger import log_info


# ============================================================
# Retrieval (used by AI Agent and RAG API)
# ============================================================

def search_knowledge(
    supabase: Client,
    query: str,
    top_k: int = DEFAULT_TOP_K,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> list[dict[str, Any]]:
    """Search the hospital knowledge base."""
    query = query.strip()
    if not query:
        return []

    result = retrieve_context(supabase=supabase, query=query, top_k=top_k, threshold=threshold)
    return result.get("results", [])


def retrieve_knowledge_context(
    supabase: Client,
    query: str,
    top_k: int = DEFAULT_TOP_K,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> dict[str, Any]:
    """Retrieve knowledge for an application or agent workflow."""
    query = query.strip()
    if not query:
        return {"results": [], "context": ""}

    return retrieve_context(supabase=supabase, query=query, top_k=top_k, threshold=threshold)


# ============================================================
# Indexing (admin) - for RAG API reindex endpoint
# ============================================================

def reindex_knowledge_base(*, actor_id: str, actor_role: str) -> dict[str, Any]:
    """Re-index the complete hospital knowledge base (published documents only).

    This is used by the RAG API /rag/reindex endpoint.
    For full ingestion (all documents), use the ingest_knowledge_base.py script.
    """
    admin_supabase = get_supabase_admin_client()

    result = reindex_all_documents(supabase=admin_supabase)

    log_info(
        "Knowledge base reindexed via RAG API",
        actor_id=actor_id,
        actor_role=actor_role,
        documents_indexed=result.get("documents_indexed", 0),
        total_chunks=result.get("total_chunks", 0),
        failed=len(result.get("failed_documents") or []),
    )
    return result
