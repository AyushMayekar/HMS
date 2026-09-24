"""
RAG API routes.
Knowledge base search and management.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from supabase import Client

from app.dependencies.auth import AuthContext, get_current_profile, get_authenticated_supabase_client, require_admin
from app.services.rag_service import search_knowledge, reindex_knowledge_base

router = APIRouter(
    prefix="/rag",
    tags=["Knowledge Base"],
)


@router.get("/search", status_code=status.HTTP_200_OK, summary="Search knowledge base")
def search_knowledge_endpoint(
    query: str = Query(..., min_length=1, max_length=500),
    top_k: int = Query(default=4, ge=1, le=20),
    auth: AuthContext = Depends(get_current_profile),
    supabase: Client = Depends(get_authenticated_supabase_client),
):
    """Search the hospital knowledge base using vector similarity."""
    results = search_knowledge(supabase=supabase, query=query, top_k=top_k)
    return {"success": True, "data": results}


@router.post("/reindex", status_code=status.HTTP_200_OK, summary="Reindex knowledge base")
def reindex_endpoint(
    auth: AuthContext = Depends(require_admin),
):
    """Re-index all published knowledge documents (admin only). Safe to run repeatedly."""
    result = reindex_knowledge_base(actor_id=auth.user.id, actor_role="admin")
    return {"success": not result.get("failed_documents"), "data": result}
