"""Crossref provider.

Wraps the Crossref REST API (``api.crossref.org/works``) and normalises
output to match the Semantic Scholar paper schema.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional

import requests

from ..models import apply_filters, FilterConfig
from ..names import filter_by_author, sample_author_names
from ..quality import rank_by_relevance, relevance_score
from .base import BaseProvider, ProgressCallback
from . import register_provider

logger = logging.getLogger(__name__)

API_DELAY = 0.2
MAX_RETRIES = 3


@register_provider("crossref")
class CrossrefProvider(BaseProvider):
    """Provider for the Crossref REST API."""

    provider_name = "crossref"

    def __init__(self) -> None:
        self.base_url = "https://api.crossref.org/works"
        self.headers = {
            "User-Agent": "SemanticScholarRegexMCP/0.4 (mailto:user@example.com)"
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        max_retrieval: int = 10_000,
        limit: int = 50,
        filters: Optional[FilterConfig] = None,
        min_relevance: float = 0.0,
        progress_callback: ProgressCallback = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Search Crossref for papers matching *query*.

        Args:
            query: Bibliographic search terms.
            max_retrieval: Maximum records to fetch from the API.
            limit: Maximum records to return.
            filters: Optional post-hoc filters.
            min_relevance: Fraction of the query's terms (0.0-1.0) a record
                must contain to be kept.  Crossref has no semantic ranking,
                so a loose term-overlap match such as "denture base" for the
                query "base editing" otherwise reaches the caller.  0.0
                disables the gate.
            progress_callback: Optional progress reporter.
        """
        # Don't fetch more than needed: cap by limit with a buffer for filtering
        if filters and filters.is_active():
            effective_max = min(max_retrieval, max(limit * 5, 500))
        else:
            effective_max = min(max_retrieval, max(limit, 100))
        papers = self._fetch_all(query, effective_max, progress_callback=progress_callback)
        meta: dict[str, Any] = {
            "total_from_api": len(papers),
            "total_after_regex": len(papers),
        }

        # Crossref matches terms loosely across the whole record, so a gate on
        # the query's own terms is what makes the membership usable.
        if min_relevance > 0.0:
            papers = [p for p in papers if relevance_score(query, p) >= min_relevance]
            meta["total_dropped_irrelevant"] = meta["total_from_api"] - len(papers)
            meta["min_relevance"] = min_relevance

        # Rank over the full candidate pool, and always -- independently of the
        # gate.  This method truncates to `limit` before returning, so a ranking
        # applied only by the caller can do no more than permute the records
        # picked here; ranking at this point is what puts the strongest and
        # most complete matches into the slice at all.
        papers = rank_by_relevance(papers, query)

        if filters and filters.is_active():
            papers = apply_filters(papers, filters)
        meta["total_after_filters"] = len(papers)

        return papers[:limit], meta


    def search_by_author(
        self,
        author_name: str,
        max_retrieval: int = 10_000,
        limit: int = 50,
        filters: Optional[FilterConfig] = None,
        allow_initial_match: bool = True,
        allow_surname_only: bool = True,
        progress_callback: ProgressCallback = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Search Crossref for papers by a specific author."""
        papers = self._fetch_all(author_name, max_retrieval, progress_callback=progress_callback)
        meta: dict[str, Any] = {"total_from_api": len(papers)}

        # Part-aware matching: Crossref renders names as "Family, Given",
        # which a literal "given family" substring test never matched.
        author_filtered, matched_names = filter_by_author(
            papers,
            author_name,
            allow_initial_match=allow_initial_match,
            allow_surname_only=allow_surname_only,
        )
        meta["total_after_author_filter"] = len(author_filtered)
        meta["matched_author_names"] = matched_names
        if not author_filtered and papers:
            meta["candidate_name_sample"] = sample_author_names(papers)

        if filters and filters.is_active():
            author_filtered = apply_filters(author_filtered, filters)
        meta["total_after_filters"] = len(author_filtered)

        return author_filtered[:limit], meta


    def get_stats(
        self,
        query: str,
        max_retrieval: int = 10_000,
    ) -> dict[str, Any]:
        """Fetch papers and return metadata about the result set."""
        papers = self._fetch_all(query, max_retrieval)
        return {
            "provider": self.provider_name,
            "query": query,
            "extended_query": query,
            "total_papers": len(papers),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_all(
        self,
        query: str,
        max_retrieval: int = 10_000,
        progress_callback: ProgressCallback = None,
    ) -> list[dict[str, Any]]:
        """Paginate through the Crossref API."""
        params: dict[str, Any] = {
            # query.bibliographic searches title/container/author metadata and
            # is far more precise than the omnibus `query` field, which also
            # matches abstracts, funder text and reference strings.
            "query.bibliographic": query,
            "rows": 100,
            "cursor": "*",
            "sort": "relevance",
            "order": "desc",
        }

        papers: list[dict[str, Any]] = []
        retrieved = 0

        while retrieved < max_retrieval:
            data = self._request_with_retry(self.base_url, params)
            if data is None:
                break

            message = data.get("message", {})
            items = message.get("items", [])
            next_cursor = message.get("next-cursor")

            for item in items:
                papers.append(self._standardize(item))
                retrieved += 1
                if retrieved >= max_retrieval:
                    break

            # Report progress after each page
            if progress_callback is not None:
                progress_callback(retrieved, max_retrieval, f"Fetching from Crossref...")

            if not next_cursor or retrieved >= max_retrieval:
                break

            params["cursor"] = next_cursor
            if API_DELAY > 0:
                time.sleep(API_DELAY)

        logger.info("Retrieved %d papers from Crossref.", retrieved)
        return papers

    @staticmethod
    def _standardize(item: dict[str, Any]) -> dict[str, Any]:
        """Normalise a Crossref work item to the common paper schema."""
        # Clean abstract
        abstract_raw = item.get("abstract", "")
        abstract_clean: Optional[str] = (
            re.sub("<[^<]+?>", "", abstract_raw) if abstract_raw else None
        )

        # Extract the publication year.  Prefer ``issued`` (when the work was
        # published) over ``created`` (when the DOI was deposited) -- those can
        # differ by years for back-deposited content.
        year: Optional[int] = None
        publication_date: Optional[str] = None
        for field in ("issued", "published-print", "published-online", "created"):
            candidate = item.get(field)
            if not isinstance(candidate, dict):
                continue
            date_parts = candidate.get("date-parts") or []
            if date_parts and date_parts[0]:
                parts = [p for p in date_parts[0] if p is not None]
                if parts:
                    year = parts[0]
                    publication_date = "-".join(f"{p:02d}" for p in parts)
                    break

        # Extract authors
        authors: list[dict[str, str]] = []
        for a in item.get("author", []):
            given = a.get("given", "")
            family = a.get("family", "")
            name = f"{given} {family}".strip()
            if name:
                authors.append({"name": name})

        # Journal / container
        container = item.get("container-title", [])
        journal: Optional[str] = container[0] if container else None

        # DOI
        doi: Optional[str] = item.get("DOI")

        # Title
        title_list = item.get("title", [])
        title: str = title_list[0] if title_list else ""

        return {
            "paperId": doi,  # Use DOI as unique ID
            "externalIds": {"DOI": doi} if doi else {},
            "title": title,
            "year": year,
            "referenceCount": item.get("references-count"),
            "citationCount": item.get("is-referenced-by-count"),
            "isOpenAccess": False,  # Crossref doesn't provide OA info
            "openAccessPdf": None,
            "publicationTypes": [item["type"]] if item.get("type") else [],
            "publicationDate": publication_date,
            "journal": journal,
            "authors": authors,
            "abstract": abstract_clean,
            "source_provider": "crossref",
        }

    def _request_with_retry(
        self,
        url: str,
        params: dict[str, Any],
        max_retries: int = MAX_RETRIES,
    ) -> Optional[dict]:
        """Make a GET request with retry logic."""
        for attempt in range(1, max_retries + 1):
            try:
                r = requests.get(
                    url,
                    params=params,
                    headers=self.headers,
                    timeout=30,
                )
                r.raise_for_status()
                return r.json()
            except requests.exceptions.Timeout:
                logger.warning("Crossref timeout (attempt %d/%d).", attempt, max_retries)
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else "unknown"
                logger.warning("Crossref HTTP %s (attempt %d/%d).", status, attempt, max_retries)
                if status == 429:
                    time.sleep(5 * attempt)
                elif status in (400, 404):
                    return None
            except requests.exceptions.ConnectionError:
                logger.warning("Crossref connection error (attempt %d/%d).", attempt, max_retries)
            except Exception:
                logger.exception("Unexpected Crossref error (attempt %d/%d).", attempt, max_retries)

            if attempt < max_retries:
                time.sleep(2 ** attempt)
        return None
