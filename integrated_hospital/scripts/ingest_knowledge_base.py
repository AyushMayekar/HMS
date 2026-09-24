#!/usr/bin/env python3
"""
Knowledge Base Ingestion Script.

Simple, on-demand script to rebuild the entire knowledge base index:
1. Deletes ALL existing document chunks
2. Re-chunks and embeds ALL knowledge documents (regardless of status)

Usage:
    python -m integrated_hospital.scripts.ingest_knowledge_base
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root is in path
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from supabase import Client
from app.config.rag import SOURCE_DOCUMENTS_TABLE, EMBEDDINGS_TABLE
from app.config.settings import get_supabase_admin_client
from app.rag.chunking import chunk_document
from app.rag.embeddings import embeddings
from app.utils.logger import log_info, log_error


INSERT_BATCH_SIZE = 50


def delete_all_chunks(supabase: Client) -> int:
    """Delete all document chunks from the embeddings table."""
    log_info("Deleting all existing document chunks...")
    
    # First, get count
    count_res = (
        supabase
        .table(EMBEDDINGS_TABLE)
        .select("chunk_id", count="exact")
        .execute()
    )
    total = count_res.count or 0
    
    if total == 0:
        log_info("No chunks to delete.")
        return 0
    
    # Delete in batches
    deleted = 0
    while True:
        res = (
            supabase
            .table(EMBEDDINGS_TABLE)
            .select("chunk_id")
            .limit(INSERT_BATCH_SIZE)
            .execute()
        )
        if not res.data:
            break
        chunk_ids = [row["chunk_id"] for row in res.data]
        supabase.table(EMBEDDINGS_TABLE).delete().in_("chunk_id", chunk_ids).execute()
        deleted += len(chunk_ids)
        log_info(f"Deleted batch of {len(chunk_ids)} chunks (total: {deleted})")
    
    log_info(f"All chunks deleted. Total: {deleted}")
    return deleted


def ingest_all_documents(supabase: Client) -> dict:
    """Ingest all knowledge documents into the vector index."""
    log_info("Fetching all knowledge documents...")
    
    doc_res = (
        supabase
        .table(SOURCE_DOCUMENTS_TABLE)
        .select("*")
        .execute()
    )
    
    documents = doc_res.data or []
    if not documents:
        log_info("No knowledge documents found.")
        return {
            "success": True,
            "documents_processed": 0,
            "total_chunks": 0,
            "failed_documents": [],
        }
    
    log_info(f"Found {len(documents)} knowledge documents to ingest.")
    
    total_chunks = 0
    processed = 0
    failed: list[dict[str, str]] = []
    
    for doc in documents:
        document_id = doc["document_id"]
        title = doc.get("title", "")
        content = doc.get("content", "") or ""
        category = doc.get("category", "")
        version = doc.get("version", 1)
        status = doc.get("status", "draft")
        
        log_info(f"Processing document: {title} ({document_id})")
        
        try:
            # Chunk the document
            chunks = chunk_document(content)
            
            if not chunks:
                log_info(f"Document '{title}' has no content, skipping.")
                processed += 1
                continue
            
            # Embed chunks
            chunk_texts = [c["content"] for c in chunks]
            embeddings_list = embeddings.embed_documents(chunk_texts)
            
            if len(embeddings_list) != len(chunks):
                raise ValueError(
                    f"Embedding count mismatch: {len(embeddings_list)} embeddings for {len(chunks)} chunks"
                )
            
            # Build records with deterministic chunk IDs
            from datetime import datetime, timezone
            from uuid import NAMESPACE_URL, uuid5
            
            CHUNK_ID_NAMESPACE = uuid5(NAMESPACE_URL, "integrated_hospital/document_chunks")
            
            def _chunk_id(doc_id: str, chunk_index: int) -> str:
                return str(uuid5(CHUNK_ID_NAMESPACE, f"{doc_id}:{chunk_index}"))
            
            now_iso = datetime.now(timezone.utc).isoformat()
            records = []
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings_list)):
                records.append({
                    "chunk_id": _chunk_id(document_id, chunk["chunk_index"]),
                    "document_id": document_id,
                    "chunk_index": chunk["chunk_index"],
                    "content": chunk["content"],
                    "embedding": embedding,
                    "created_at": now_iso,
                    "metadata": {
                        "title": title,
                        "category": category,
                        "version": version,
                        "status": status,
                    },
                })
            
            # Upsert in batches
            for start in range(0, len(records), INSERT_BATCH_SIZE):
                batch = records[start:start + INSERT_BATCH_SIZE]
                (
                    supabase
                    .table(EMBEDDINGS_TABLE)
                    .upsert(batch, on_conflict="chunk_id")
                    .execute()
                )
            
            total_chunks += len(records)
            processed += 1
            log_info(f"Indexed '{title}': {len(records)} chunks")
            
        except Exception as exc:
            log_error(
                "Failed to ingest document",
                document_id=document_id,
                title=title,
                exception_type=type(exc).__name__,
                error=str(exc)[:300],
            )
            failed.append({"document_id": document_id, "title": title, "error": str(exc)[:300]})
    
    log_info(
        "Knowledge base ingestion complete",
        documents_processed=processed,
        total_chunks=total_chunks,
        failed=len(failed),
    )
    
    return {
        "success": len(failed) == 0,
        "documents_processed": processed,
        "total_chunks": total_chunks,
        "failed_documents": failed,
    }


def main() -> int:
    """Main entry point."""
    print("=" * 60)
    print("Knowledge Base Ingestion Script")
    print("=" * 60)
    print("This will:")
    print("  1. Delete ALL existing document chunks")
    print("  2. Re-chunk and embed ALL knowledge documents")
    print("=" * 60)
    
    # Confirm
    response = input("\nProceed? [y/N]: ").strip().lower()
    if response != "y":
        print("Aborted.")
        return 0
    
    supabase = get_supabase_admin_client()
    
    # Step 1: Delete all chunks
    print("\n[1/2] Deleting existing chunks...")
    delete_all_chunks(supabase)
    
    # Step 2: Ingest all documents
    print("\n[2/2] Ingesting all knowledge documents...")
    result = ingest_all_documents(supabase)
    
    print("\n" + "=" * 60)
    print("INGESTION COMPLETE")
    print("=" * 60)
    print(f"Documents processed: {result['documents_processed']}")
    print(f"Total chunks created: {result['total_chunks']}")
    print(f"Failed documents: {len(result['failed_documents'])}")
    
    if result["failed_documents"]:
        print("\nFailed documents:")
        for f in result["failed_documents"]:
            print(f"  - {f['title']} ({f['document_id']}): {f['error']}")
        return 1
    
    print("\nSuccess!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
