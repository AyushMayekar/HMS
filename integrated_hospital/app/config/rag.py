import os


# Supabase tables
SOURCE_DOCUMENTS_TABLE = os.getenv("RAG_SOURCE_DOCUMENTS_TABLE", "knowledge_documents")
EMBEDDINGS_TABLE = os.getenv("RAG_EMBEDDINGS_TABLE", "document_chunks")
MATCH_FUNCTION = os.getenv("RAG_MATCH_FUNCTION", "match_knowledge_documents")

# Chunking
CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "150"))

# Embeddings
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "azure/genailab-maas-text-embedding-3-large")
EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "1536"))

# Retrieval
DEFAULT_TOP_K = int(os.getenv("RAG_TOP_K", "4"))
# Relevant chunks for this embedding model score ~0.42-0.59, so a 0.70
# default silently returned zero context. Keep this aligned with .env.
DEFAULT_MATCH_THRESHOLD = float(os.getenv("RAG_MATCH_THRESHOLD", "0.40"))
RETRIEVAL_MAX_RESULTS = 10