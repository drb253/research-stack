"""Data models for normalized paper representation across providers.

All providers normalize their output to match this schema, which is
designed to mirror Semantic Scholar's paper JSON format for backward
compatibility with existing filters and statistics code.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Filter configuration (moved from api.py)
# ---------------------------------------------------------------------------


@dataclass
class FilterConfig:
    """Post-hoc filtering criteria for search results.

    All fields are optional — only non-``None`` values are applied.
    """

    year_min: Optional[int] = None
    year_max: Optional[int] = None
    open_access_only: bool = False
    has_pdf: Optional[bool] = None
    journal: Optional[str] = None          # case-insensitive substring match
    exclude_journals: Optional[list[str]] = None
    publication_types: Optional[list[str]] = None   # e.g. ["JournalArticle", "Review"]
    exclude_publication_types: Optional[list[str]] = None
    author: Optional[str] = None            # case-insensitive substring match on any author
    min_citation_count: Optional[int] = None
    max_citation_count: Optional[int] = None
    has_abstract: Optional[bool] = None

    def is_active(self) -> bool:
        """Return True if at least one filter is set."""
        return any(
            v is not None and v is not False and v != []
            for v in [
                self.year_min, self.year_max,
                True if self.open_access_only else None,
                self.has_pdf,
                self.journal, self.exclude_journals,
                self.publication_types, self.exclude_publication_types,
                self.author,
                self.min_citation_count, self.max_citation_count,
                self.has_abstract,
            ]
        )


# ---------------------------------------------------------------------------
# Post-hoc filter application (moved from api.py)
# ---------------------------------------------------------------------------


def apply_filters(
    papers: list[dict[str, Any]],
    filters: FilterConfig,
) -> list[dict[str, Any]]:
    """Apply post-hoc filters to a list of papers.

    Each paper retains its original dict shape; no keys are added.

    Args:
        papers: List of paper dicts from the API.
        filters: A :class:`FilterConfig` instance.

    Returns:
        Filtered list of paper dicts.
    """
    if not filters.is_active():
        return papers

    filtered: list[dict[str, Any]] = []
    for paper in papers:
        if _paper_passes(paper, filters):
            filtered.append(paper)

    return filtered


def _journal_name(journal_val: Any) -> Optional[str]:
    """Extract a journal name string from a journal value.

    Handles both Semantic Scholar format (``{"name": "Nature", ...}``)
    and other providers that store journal as a plain string.
    """
    if isinstance(journal_val, str):
        return journal_val
    if isinstance(journal_val, dict):
        name = journal_val.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _paper_passes(paper: dict[str, Any], f: FilterConfig) -> bool:
    """Check whether a single paper passes all active filters."""

    # --- Year range ---
    year = paper.get("year")
    if year is not None and isinstance(year, (int, float)):
        if f.year_min is not None and year < f.year_min:
            return False
        if f.year_max is not None and year > f.year_max:
            return False

    # --- Open access ---
    if f.open_access_only:
        if not paper.get("isOpenAccess"):
            return False

    # --- Has PDF ---
    if f.has_pdf is not None:
        has_pdf = bool(paper.get("openAccessPdf"))
        if has_pdf != f.has_pdf:
            return False

    # --- Journal (case-insensitive substring) ---
    if f.journal is not None:
        journal_val = _journal_name(paper.get("journal"))
        if journal_val is None:
            return False
        if f.journal.lower() not in journal_val.lower():
            return False

    # --- Exclude journals ---
    if f.exclude_journals:
        journal_val = _journal_name(paper.get("journal"))
        if journal_val is not None:
            for excl in f.exclude_journals:
                if excl.lower() in journal_val.lower():
                    return False

    # --- Publication types ---
    if f.publication_types:
        pt = paper.get("publicationTypes", [])
        if not isinstance(pt, list):
            return False
        if not any(ptype in pt for ptype in f.publication_types):
            return False

    # --- Exclude publication types ---
    if f.exclude_publication_types:
        pt = paper.get("publicationTypes", [])
        if isinstance(pt, list):
            if any(xtype in pt for xtype in f.exclude_publication_types):
                return False

    # --- Author (case-insensitive substring match on any author) ---
    if f.author is not None:
        authors = paper.get("authors", [])
        if not isinstance(authors, list):
            return False
        target = f.author.lower()
        matched = False
        for a in authors:
            name = a.get("name", "") if isinstance(a, dict) else str(a)
            if target in name.lower():
                matched = True
                break
        if not matched:
            return False

    # --- Citation count range ---
    cc = paper.get("citationCount")
    if cc is not None and isinstance(cc, (int, float)):
        if f.min_citation_count is not None and cc < f.min_citation_count:
            return False
        if f.max_citation_count is not None and cc > f.max_citation_count:
            return False

    # --- Has abstract ---
    if f.has_abstract is not None:
        abstract = paper.get("abstract")
        has_it = bool(abstract and isinstance(abstract, str) and abstract.strip())
        if has_it != f.has_abstract:
            return False

    return True


# ---------------------------------------------------------------------------
# Regex post-filtering (universal, no longer Semantic Scholar-only)
# ---------------------------------------------------------------------------


def apply_regex_filter(
    papers: list[dict[str, Any]],
    pattern: str,
    fields: Optional[list[str]] = None,
    match_mode: str = "any",
) -> list[dict[str, Any]]:
    """Filter papers by applying a regex pattern to specified text fields.

    Each matching paper gets a ``_regex_matches`` key added with per-field
    match booleans.

    Args:
        papers: List of paper dicts.
        pattern: A Python regex pattern (compiled with ``re.IGNORECASE``).
        fields: List of field names to search (default: ``[\"title\", \"abstract\"]``).
        match_mode:
            - ``\"any\"``: paper kept if *any* field matches (OR).
            - ``\"all\"``: paper kept only if *all* fields match (AND).

    Returns:
        Filtered list of paper dicts, each with ``_regex_matches`` added.
    """
    if not pattern:
        return papers

    fields = fields or ["title", "abstract"]
    filtered: list[dict[str, Any]] = []
    for paper in papers:
        field_matches: dict[str, bool] = {}
        for field_name in fields:
            value = paper.get(field_name)
            if value and isinstance(value, str):
                field_matches[field_name] = bool(
                    re.search(pattern, value, re.IGNORECASE)
                )
            else:
                field_matches[field_name] = False

        keep = (
            all(field_matches.values())
            if match_mode == "all"
            else any(field_matches.values())
        )
        if keep:
            paper_copy = dict(paper)
            paper_copy["_regex_matches"] = field_matches
            filtered.append(paper_copy)

    return filtered


# ---------------------------------------------------------------------------
# DOI / title normalization utilities
# ---------------------------------------------------------------------------


def normalize_doi(doi: Optional[str]) -> Optional[str]:
    """Normalise a DOI for deduplication."""
    if not isinstance(doi, str):
        return None
    return (
        doi.replace("https://doi.org/", "")
        .replace("http://dx.doi.org/", "")
        .strip()
        .lower()
    )


def normalize_title(title: Optional[str]) -> str:
    """Normalise a title for deduplication (lowercase, alphanumeric only)."""
    if not isinstance(title, str):
        return ""
    return re.sub(r"[\W_]+", "", title.lower())


# ---------------------------------------------------------------------------
# OpenAlex abstract reconstruction
# ---------------------------------------------------------------------------


def reconstruct_openalex_abstract(inverted_index: Optional[dict]) -> str:
    """Reconstruct readable abstract text from an OpenAlex inverted index.

    OpenAlex stores abstracts as an inverted index to save space. This
    function reconstructs the original text.

    Args:
        inverted_index: The OpenAlex ``abstract_inverted_index`` dict,
            e.g. ``{"word": [0, 3], "another": [1, 4]}``.

    Returns:
        The reconstructed abstract string, or an empty string on failure.
    """
    if not inverted_index:
        return ""
    try:
        length = max(max(positions) for positions in inverted_index.values()) + 1
        abstract_list = [""] * length
        for word, positions in inverted_index.items():
            for pos in positions:
                abstract_list[pos] = word
        return " ".join(abstract_list)
    except (ValueError, TypeError, KeyError):
        return ""


# ---------------------------------------------------------------------------
# Simple TF text similarity (no external dependencies)
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Lowercase, split on whitespace, keep only alphabetic tokens >= 2 chars."""
    return [t for t in re.findall(r'\b[a-z]+\b', text.lower()) if len(t) >= 2]


def simple_text_similarity(text1: str, text2: str) -> float:
    """Cosine similarity of term-frequency vectors between two texts.

    Pure Python implementation, no external dependencies.  Uses TF-only
    vectors (no IDF) because it's designed for pairwise comparisons.

    Args:
        text1: First text string.
        text2: Second text string.

    Returns:
        A float in ``[0.0, 1.0]`` where 1.0 means identical TF vectors.
        Returns 0.0 if either text is empty or has no valid tokens.
    """
    tokens1 = _tokenize(text1)
    tokens2 = _tokenize(text2)

    if not tokens1 or not tokens2:
        return 0.0

    vocab = set(tokens1) | set(tokens2)
    vec1 = Counter(tokens1)
    vec2 = Counter(tokens2)

    dot_product = sum(vec1.get(w, 0) * vec2.get(w, 0) for w in vocab)
    norm1 = math.sqrt(sum(v ** 2 for v in vec1.values()))
    norm2 = math.sqrt(sum(v ** 2 for v in vec2.values()))

    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot_product / (norm1 * norm2)


def get_paper_text_for_similarity(paper: dict[str, Any]) -> str:
    """Extract the best available text from a paper for similarity comparison.

    Priority: ``abstract`` > ``tldr.text`` > ``title``.

    Args:
        paper: A paper dict (normalised schema).

    Returns:
        The best available text, or an empty string if none found.
    """
    abstract = paper.get("abstract")
    if abstract and isinstance(abstract, str) and abstract.strip():
        return abstract.strip()

    tldr = paper.get("tldr")
    if tldr and isinstance(tldr, dict):
        tldr_text = tldr.get("text") or tldr.get("tldr")
        if tldr_text and isinstance(tldr_text, str) and tldr_text.strip():
            return tldr_text.strip()

    title = paper.get("title")
    if title and isinstance(title, str) and title.strip():
        return title.strip()

    return ""
