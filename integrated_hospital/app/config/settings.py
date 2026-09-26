import os
from functools import lru_cache
from dotenv import load_dotenv
from supabase import Client, create_client
from pydantic import BaseModel
from typing import Optional

load_dotenv()


class Settings(BaseModel):
    # LLM Configuration
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://genailab.tcs.in")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "genailab-maas-gpt-5.4")
    llm_model_fallback: str = os.getenv("LLM_MODEL_FALLBACK", "genailab-maas-gpt-5.4-mini")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "azure/genailab-maas-text-embedding-3-large")
    embedding_dimension: int = int(os.getenv("EMBEDDING_DIMENSION", "1536"))

    # Supabase Configuration
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_key: str = os.getenv("SUPABASE_KEY", "")
    supabase_service_role_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    # RAG Configuration
    rag_source_documents_table: str = os.getenv("RAG_SOURCE_DOCUMENTS_TABLE", "knowledge_documents")
    rag_embeddings_table: str = os.getenv("RAG_EMBEDDINGS_TABLE", "document_chunks")
    rag_match_function: str = os.getenv("RAG_MATCH_FUNCTION", "match_knowledge_documents")
    rag_chunk_size: int = int(os.getenv("RAG_CHUNK_SIZE", "1000"))
    rag_chunk_overlap: int = int(os.getenv("RAG_CHUNK_OVERLAP", "150"))
    rag_top_k: int = int(os.getenv("RAG_TOP_K", "4"))
    rag_match_threshold: float = float(os.getenv("RAG_MATCH_THRESHOLD", "0.70"))
    rag_retrieval_max_results: int = 10

    # Hospital Configuration
    hospital_timezone: str = os.getenv("HOSPITAL_TIMEZONE", "Asia/Kolkata")

    # ML Configuration
    # Default resolves package-relative to app/ml/models so model loading does
    # not depend on the process working directory. ML_MODEL_PATH env var still
    # overrides when explicitly set to a real directory.
    ml_model_path: str = os.getenv("ML_MODEL_PATH") or os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "ml", "models")
    )
    ml_no_show_model_version: str = os.getenv("ML_NO_SHOW_MODEL_VERSION", "v1.0")
    ml_waiting_time_model_version: str = os.getenv("ML_WAITING_TIME_MODEL_VERSION", "v1.0")

    # No-show scoring window (§16 / capstone selection flow): predictions are
    # offered ~24h before the appointment, inside a configurable tolerance
    # band, and only for an explicit user selection. The default band is
    # ±12h (i.e. 12–36h before the visit) so a real day's worth of
    # appointments is actually offered; NOSHOW_TOLERANCE_MINUTES overrides it.
    noshow_tolerance_minutes: int = int(os.getenv("NOSHOW_TOLERANCE_MINUTES", "720"))
    # Hard cap per "Predict Selected" action — enforced in the API/service
    # (authoritative) and mirrored in the frontend.
    noshow_max_batch: int = int(os.getenv("NOSHOW_MAX_BATCH", "10"))

    # SMTP Configuration (for real emails if needed)
    brevo_smtp: Optional[str] = os.getenv("BREVO_SMTP")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_supabase_client() -> Client:
    """Get standard Supabase client (anon key)."""
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in environment")
    return create_client(settings.supabase_url, settings.supabase_key)


def get_supabase_admin_client() -> Client:
    """Get admin Supabase client (service role key) for bypassing RLS."""
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in environment")
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def get_authenticated_supabase_client(access_token: str) -> Client:
    """Get Supabase client authenticated with user's JWT for RLS enforcement."""
    settings = get_settings()
    client = create_client(settings.supabase_url, settings.supabase_key)
    client.postgrest.auth(access_token)
    return client