"""
Document chunking utilities.
Splits documents into chunks for embedding and retrieval.
"""
from __future__ import annotations

from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config.rag import CHUNK_SIZE, CHUNK_OVERLAP


def chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks."""
    if not text or not text.strip():
        return []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks = splitter.split_text(text.strip())
    return [chunk for chunk in chunks if chunk.strip()]


def chunk_document(content: str) -> list[dict[str, Any]]:
    """Chunk document content with indices."""
    chunks = chunk_text(content)

    return [
        {
            "chunk_index": index,
            "content": chunk,
        }
        for index, chunk in enumerate(chunks)
    ]
