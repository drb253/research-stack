"""Backward-compatible API module.

Re-exports all public functions and classes from the refactored
``models`` and ``providers`` modules.  Existing code that does
``from . import api`` or ``from .api import fetch_all_papers``
continues to work unchanged.
"""

from __future__ import annotations

from .models import (
    FilterConfig,
    apply_filters,
    apply_regex_filter,
    normalize_doi,
    normalize_title,
    reconstruct_openalex_abstract,
)
from .providers import get_provider, list_providers

# Create a singleton provider instance for wrapper functions below.
from .providers.semantic_scholar import SemanticScholarProvider, DEFAULT_FIELDS

_SEMANTIC_SCHOLAR = SemanticScholarProvider()


def build_extended_query(query: str, search_type: str = "limited") -> str:
    """Transform a regex query for the Semantic Scholar API.

    Wraps :meth:`SemanticScholarProvider._build_extended_query`.
    """
    return _SEMANTIC_SCHOLAR._build_extended_query(query, search_type)


def fetch_all_papers(
    extended_query: str,
    fields: str = DEFAULT_FIELDS,
    max_retrieval: int = 10_000_000,
    api_delay: float = 0.5,
) -> list[dict]:
    """Fetch papers from the Semantic Scholar bulk API.

    Wraps :meth:`SemanticScholarProvider._fetch_all`.
    """
    return _SEMANTIC_SCHOLAR._fetch_all(extended_query, fields, max_retrieval)


def apply_regex_filter(
    papers: list[dict],
    query: str,
    regex_search_fields: list[str],
    match_mode: str = "any",
) -> list[dict]:
    """Filter papers by applying the original regex to specified fields.

    Wraps :func:`models.apply_regex_filter`.
    """
    return _apply_regex_filter(papers, query, regex_search_fields, match_mode)

# Local alias to avoid import shadowing
from .models import apply_regex_filter as _apply_regex_filter  # noqa: E402


__all__ = [
    "FilterConfig",
    "apply_filters",
    "apply_regex_filter",
    "build_extended_query",
    "DEFAULT_FIELDS",
    "fetch_all_papers",
    "get_provider",
    "list_providers",
    "normalize_doi",
    "normalize_title",
    "reconstruct_openalex_abstract",
]
