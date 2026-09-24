"""
RAG retriever.
Vector similarity search against Supabase pgvector.
"""
from __future__ import annotations

from typing import Any

from supabase import Client

from app.config.rag import (
    DEFAULT_MATCH_THRESHOLD,
    DEFAULT_TOP_K,
    EMBEDDINGS_TABLE,
    MATCH_FUNCTION,
    RETRIEVAL_MAX_RESULTS,
    SOURCE_DOCUMENTS_TABLE,
)
from app.rag.embeddings import embeddings
from app.utils.logger import log_info

# Generic English words that would otherwise make almost any chunk "match"
# a keyword fallback query (e.g. "the", "what") and pollute the LLM context.
_KEYWORD_STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
    "her", "was", "one", "our", "out", "who", "how", "why", "when", "what",
    "does", "did", "this", "that", "with", "from", "have", "has", "been",
    "were", "they", "them", "his", "she", "its", "you", "any", "may",
}

# Minimum share of query terms a chunk must contain to be used as context.
_MIN_KEYWORD_SCORE = 0.34


def _keyword_search(
    supabase: Client,
    query: str,
    top_k: int,
) -> list[dict[str, Any]]:
    """
    Fallback used when the embedding service is unavailable: a real keyword
    match over published knowledge chunks (never fabricated content), ranked
    by query-term overlap and returned in the same shape as vector results.
    """
    import re

    terms = [t for t in re.findall(r"[a-z0-9']{3,}", query.lower()) if t not in _KEYWORD_STOPWORDS]
    if not terms:
        return []
    terms = list(dict.fromkeys(terms))[:8]

    try:
        or_filter = ",".join(f"content.ilike.%{term}%" for term in terms)
        response = (
            supabase
            .table(EMBEDDINGS_TABLE)
            .select("chunk_id, document_id, content")
            .or_(or_filter)
            .limit(200)
            .execute()
        )
        rows = response.data or []

        docs: dict[str, Any] = {}
        doc_ids = sorted({r["document_id"] for r in rows if r.get("document_id")})
        if doc_ids:
            doc_res = (
                supabase
                .table(SOURCE_DOCUMENTS_TABLE)
                .select("document_id, title, category, version")
                .in_("document_id", doc_ids)
                .execute()
            )
            docs = {d["document_id"]: d for d in (doc_res.data or [])}
    except Exception as exc:
        from app.utils.logger import log_warning
        log_warning("Knowledge keyword search failed", exception_type=type(exc).__name__)
        return []

    scored: list[dict[str, Any]] = []
    for row in rows:
        content = row.get("content") or ""
        if not content:
            continue
        haystack = content.lower()
        hits = sum(1 for term in terms if term in haystack)
        if not hits or (hits / len(terms)) < _MIN_KEYWORD_SCORE:
            continue
        doc = docs.get(row.get("document_id")) or {}
        scored.append({
            "chunk_id": row.get("chunk_id"),
            "document_id": row.get("document_id"),
            "title": doc.get("title"),
            "category": doc.get("category"),
            "version": doc.get("version"),
            "content": content,
            "similarity": round(hits / len(terms), 3),
        })
    scored.sort(key=lambda item: item["similarity"], reverse=True)
    return scored[:top_k]


def retrieve(
    supabase: Client,
    query: str,
    top_k: int = DEFAULT_TOP_K,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> list[dict[str, Any]]:
    """
    Retrieve the most relevant published knowledge chunks
    for a query using vector similarity search.
    """
    query = query.strip()
    if not query:
        return []

    top_k = min(max(top_k, 1), RETRIEVAL_MAX_RESULTS)

    try:
        query_embedding = embeddings.embed_query(query)
    except Exception as exc:
        # Embedding service unavailable (e.g. credential RBAC denial):
        # degrade to a real keyword search instead of failing the request.
        from app.utils.logger import log_warning
        log_warning(
            "Embedding service unavailable; using keyword search",
            exception_type=type(exc).__name__,
        )
        rows = _keyword_search(supabase=supabase, query=query, top_k=top_k)
        log_info("knowledge:retrieval", mode="keyword(embed_unavailable)", query=query, hits=len(rows))
        return rows

    # The RPC can fail for reasons the caller cannot fix (RLS denial, a
    # missing/deployed-late function, a bad threshold type). Never let that
    # escape as a 500/\"assistant unavailable\" — degrade to keyword search.
    try:
        response = (
            supabase
            .rpc(
                MATCH_FUNCTION,
                {
                    "query_embedding": query_embedding,
                    "match_threshold": threshold,
                    "match_count": top_k,
                },
            )
            .execute()
        )
        rows = response.data or []
    except Exception as exc:
        from app.utils.logger import log_warning
        log_warning(
            "Vector search failed; using keyword search",
            exception_type=type(exc).__name__,
        )
        rows = _keyword_search(supabase=supabase, query=query, top_k=top_k)
        log_info("knowledge:retrieval", mode="keyword(rpc_failed)", query=query, hits=len(rows))
        return rows

    if rows:
        log_info(
            "knowledge:retrieval",
            mode="vector",
            query=query,
            threshold=threshold,
            top_k=top_k,
            hits=len(rows),
            top_similarity=rows[0].get("similarity"),
        )
        return rows

    # Nothing cleared the similarity threshold: a too-strict threshold would
    # otherwise hand the LLM an empty context and it would claim no knowledge.
    rows = _keyword_search(supabase=supabase, query=query, top_k=top_k)
    log_info(
        "knowledge:retrieval",
        mode="keyword(no_vector_hits)",
        query=query,
        threshold=threshold,
        hits=len(rows),
    )
    return rows


def build_context(results: list[dict[str, Any]]) -> str:
    """Convert retrieved chunks into formatted context for the LLM."""
    if not results:
        return ""

    sections: list[str] = []

    for index, result in enumerate(results, start=1):
        title = result.get("title") or "Hospital Knowledge"
        category = result.get("category")
        version = result.get("version")
        content = (result.get("content") or "").strip()

        if not content:
            continue

        source_label = title
        if category:
            source_label += f" | Category: {category}"
        if version is not None:
            source_label += f" | Version: {version}"

        sections.append(
            f"[Source {index}: {source_label}]\n{content}"
        )

    return "\n\n".join(sections)


def retrieve_context(
    supabase: Client,
    query: str,
    top_k: int = DEFAULT_TOP_K,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> dict[str, Any]:
    """Retrieve relevant knowledge chunks and return both raw results and formatted context."""
    query = query.strip()
    if not query:
        return {"results": [], "context": ""}

    results = retrieve(supabase=supabase, query=query, top_k=top_k, threshold=threshold)

    return {
        "results": results,
        "context": build_context(results),
    }
