"""
Database client utilities.
Provides typed access to Supabase clients for different contexts.
"""
from supabase import Client

from app.config.settings import (
    get_supabase_client,
    get_supabase_admin_client,
    get_authenticated_supabase_client,
)

__all__ = [
    "get_supabase_client",
    "get_supabase_admin_client",
    "get_authenticated_supabase_client",
    "Client",
]