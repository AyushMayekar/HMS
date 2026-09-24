"""
Embedding model configuration.
Uses OpenAI-compatible embedding API.
"""
import os
import httpx
from langchain_openai import OpenAIEmbeddings
from app.config.rag import EMBEDDING_DIMENSION
from dotenv import load_dotenv

load_dotenv()

http_client = httpx.Client(verify=False)

embeddings = OpenAIEmbeddings(
    base_url=os.getenv("LLM_BASE_URL"),
    api_key=os.getenv("LLM_API_KEY"),
    model=os.getenv("EMBEDDING_MODEL", "azure/genailab-maas-text-embedding-3-large"),
    http_client=http_client,
    dimensions=EMBEDDING_DIMENSION,
)
