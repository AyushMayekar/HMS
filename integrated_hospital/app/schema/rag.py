from pydantic import BaseModel, Field


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(default=4, ge=1, le=20)
    threshold: float = Field(default=0.7, ge=0.0, le=1.0)


class KnowledgeSearchResult(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    category: str | None = None
    version: int | None = None
    content: str
    similarity: float


class KnowledgeSearchResponse(BaseModel):
    results: list[KnowledgeSearchResult]
    context: str
