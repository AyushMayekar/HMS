"""
RAG document ingestion.
Index and re-index knowledge documents with chunking and embedding.

Safety rules:
- The canonical document is chunked and embedded BEFORE any stored row is
  touched, and the new generation of rows is upserted BEFORE older rows are
  pruned. A failed embedding or insert therefore never destroys a previously
  valid index (no delete-then-insert window).
- chunk_id is a deterministic UUID (uuid5 of document_id + chunk_index): it
  satisfies the document_chunks.chunk_id UUID primary key, is stable across
  runs and hosts, and makes re-indexing idempotent — the same rows are merged
  in place instead of duplicated.
- Full re-index isolates failures per document: one failing document cannot
  abort (or corrupt) the rest of the knowledge base.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from supabase import Client

from app.config.rag import SOURCE_DOCUMENTS_TABLE, EMBEDDINGS_TABLE
from app.rag.chunking import chunk_document
from app.rag.embeddings import embeddings
from app.utils.logger import log_info, log_error

INSERT_BATCH_SIZE = 50

# Fixed namespace so chunk ids are identical on every run and every host.
CHUNK_ID_NAMESPACE = uuid5(NAMESPACE_URL, "integrated_hospital/document_chunks")


def _chunk_id(document_id: str, chunk_index: int) -> str:
    """Deterministic UUID for a chunk (document_chunks.chunk_id is UUID PK)."""
    return str(uuid5(CHUNK_ID_NAMESPACE, f"{document_id}:{chunk_index}"))


def _current_chunk_ids(supabase: Client, document_id: str) -> list[str]:
    """Snapshot of stored chunk ids for a document, taken before any mutation."""
    res = (
        supabase
        .table(EMBEDDINGS_TABLE)
        .select("chunk_id")
        .eq("document_id", document_id)
        .execute()
    )
    return [row["chunk_id"] for row in (res.data or [])]


def _delete_chunk_ids(supabase: Client, chunk_ids: list[str]) -> None:
    """Delete specific chunk rows in small batches."""
    for start in range(0, len(chunk_ids), INSERT_BATCH_SIZE):
        (
            supabase
            .table(EMBEDDINGS_TABLE)
            .delete()
            .in_("chunk_id", chunk_ids[start:start + INSERT_BATCH_SIZE])
            .execute()
        )


def delete_document_chunks(*, document_id: str, supabase: Client) -> None:
    """Remove all stored chunks belonging to a document."""
    supabase.table(EMBEDDINGS_TABLE).delete().eq("document_id", document_id).execute()


def index_document(*, document_id: str, supabase: Client) -> dict[str, Any]:
    """Index or re-index one knowledge-base document.

    Ordering: fetch -> snapshot stored ids -> chunk -> embed -> upsert new
    rows -> prune rows no longer belonging to the document. Every destructive
    step runs only AFTER its replacement is safely stored, so a failure at any
    earlier point leaves the previous index fully intact.
    """
    # 1. Fetch the canonical document
    doc_res = (
        supabase
        .table(SOURCE_DOCUMENTS_TABLE)
        .select("*")
        .eq("document_id", document_id)
        .execute()
    )

    if not doc_res.data:
        return {"success": False, "error": "Document not found"}

    document = doc_res.data[0]
    title = document.get("title", "")
    content = document.get("content", "") or ""
    category = document.get("category", "")
    version = document.get("version", 1)
    status = document.get("status", "draft")

    # 2. Snapshot stored ids BEFORE any mutation (basis for pruning later)
    current_ids = _current_chunk_ids(supabase, document_id)

    # 3. Chunk the canonical content
    chunks = chunk_document(content)

    if not chunks:
        # Canonical content is empty: the index must become empty as well.
        if current_ids:
            _delete_chunk_ids(supabase, current_ids)
            log_info(
                "Empty document: stored chunks removed",
                document_id=document_id,
                chunks_removed=len(current_ids),
            )
        return {"success": True, "chunks_indexed": 0, "chunks_removed": len(current_ids)}

    # 4. Embed BEFORE touching any stored row (failure -> previous index intact)
    chunk_texts = [c["content"] for c in chunks]
    embeddings_list = embeddings.embed_documents(chunk_texts)

    if len(embeddings_list) != len(chunks):
        return {
            "success": False,
            "error": f"Embedding count mismatch: got {len(embeddings_list)} embeddings for {len(chunks)} chunks",
        }

    # 5. Build records with deterministic UUID chunk ids
    now_iso = datetime.now(timezone.utc).isoformat()
    records = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings_list)):
        records.append({
            "chunk_id": _chunk_id(document_id, chunk["chunk_index"]),
            "document_id": document_id,
            "chunk_index": chunk["chunk_index"],
            "content": chunk["content"],
            "embedding": embedding,
            # Spec 6.11: created_at is Required on chunk rows.
            "created_at": now_iso,
            "metadata": {
                "title": title,
                "category": category,
                "version": version,
                "status": status,
            },
        })

    # 6. Store the new generation FIRST (idempotent upsert on the chunk_id PK).
    #    Any failure here leaves the previous rows untouched.
    for start in range(0, len(records), INSERT_BATCH_SIZE):
        batch = records[start:start + INSERT_BATCH_SIZE]
        (
            supabase
            .table(EMBEDDINGS_TABLE)
            .upsert(batch, on_conflict="chunk_id")
            .execute()
        )

    # 7. Only after EVERY new row is stored, prune rows of older generations
    #    (shrunk tails, seed-era random ids, partial earlier runs).
    new_ids = {r["chunk_id"] for r in records}
    stale_ids = [cid for cid in current_ids if cid not in new_ids]
    if stale_ids:
        try:
            _delete_chunk_ids(supabase, stale_ids)
        except Exception as exc:
            log_error(
                "New chunks stored but stale-chunk pruning failed",
                document_id=document_id,
                exception_type=type(exc).__name__,
            )
            return {
                "success": False,
                "chunks_indexed": len(records),
                "error": (
                    "New chunks stored, but stale chunks could not be removed; "
                    f"retry indexing. ({str(exc)[:200]})"
                ),
            }

    log_info(
        "Document indexed",
        document_id=document_id,
        chunks=len(records),
        stale_removed=len(stale_ids),
    )
    return {"success": True, "chunks_indexed": len(records), "chunks_removed": len(stale_ids)}


def reindex_all_documents(*, supabase: Client) -> dict[str, Any]:
    """Re-index all published knowledge-base documents.

    Safe to run repeatedly: each document merges its own chunks (no growth,
    no duplicates). Failures are collected per document instead of aborting
    the whole run, and a failing document keeps its previous index.
    """
    doc_res = (
        supabase
        .table(SOURCE_DOCUMENTS_TABLE)
        .select("document_id")
        .eq("status", "published")
        .execute()
    )

    documents = doc_res.data or []
    if not documents:
        return {
            "success": True,
            "documents_indexed": 0,
            "total_chunks": 0,
            "failed_documents": [],
        }

    total_chunks = 0
    indexed = 0
    failed: list[dict[str, str]] = []

    for doc in documents:
        document_id = doc["document_id"]
        try:
            result = index_document(document_id=document_id, supabase=supabase)
        except Exception as exc:
            log_error(
                "Knowledge document reindex failed",
                document_id=document_id,
                exception_type=type(exc).__name__,
            )
            failed.append({"document_id": document_id, "error": str(exc)[:300]})
            continue

        if not result.get("success"):
            failed.append({"document_id": document_id, "error": str(result.get("error"))[:300]})
            continue

        indexed += 1
        total_chunks += result.get("chunks_indexed", 0)

    log_info(
        "Knowledge base reindexed",
        documents=len(documents),
        documents_indexed=indexed,
        failed=len(failed),
        total_chunks=total_chunks,
    )
    return {
        "success": not failed,
        "documents_indexed": indexed,
        "total_chunks": total_chunks,
        "failed_documents": failed,
    }
