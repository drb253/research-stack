"""OpenAlex provider.

Wraps the OpenAlex REST API (``api.openalex.org/works``) and normalises
output to match the Semantic Scholar paper schema.  OpenAlex uses an
inverted index for abstracts (reconstructed here) and has excellent
open-access metadata.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import requests

from ..models import apply_filters, FilterConfig, reconstruct_openalex_abstract
from .base import BaseProvider, ProgressCallback
from . import register_provider

logger = logging.getLogger(__name__)

API_DELAY = 0.5  # OpenAlex has no strict rate limit, but be polite
MAX_RETRIES = 3


@register_provider("openalex")
class OpenAlexProvider(BaseProvider):
    """Provider for the OpenAlex API."""

    provider_name = "openalex"

    def __init__(self, email: Optional[str] = None) -> None:
        self.base_url = "https://api.openalex.org/works"
        self.email = email or os.environ.get("OPENALEX_EMAIL", "mcp@example.com")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        max_retrieval: int = 10_000,
        limit: int = 50,
        filters: Optional[FilterConfig] = None,
        progress_callback: ProgressCallback = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Search OpenAlex for papers matching *query*."""
        # Don't fetch more than needed: cap by limit with a buffer for filtering
        if filters and filters.is_active():
            effective_max = min(max_retrieval, max(limit * 5, 500))
        else:
            effective_max = min(max_retrieval, max(limit, 100))
        papers = self._fetch_all(query, effective_max, progress_callback=progress_callback)
        meta = {"total_from_api": len(papers), "total_after_regex": len(papers)}

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
        progress_callback: ProgressCallback = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Search OpenAlex for papers by a specific author."""
        papers = self._fetch_all(author_name, max_retrieval, progress_callback=progress_callback)
        meta = {"total_from_api": len(papers)}

        # Post-filter to ensure the author is in the authors list
        target = author_name.lower()
        author_filtered: list[dict[str, Any]] = []
        for paper in papers:
            authors = paper.get("authors", [])
            if not isinstance(authors, list):
                continue
            for a in authors:
                name = a.get("name", "") if isinstance(a, dict) else str(a)
                if target in name.lower():
                    author_filtered.append(paper)
                    break
        meta["total_after_author_filter"] = len(author_filtered)

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
        """Paginate through the OpenAlex API using cursor-based pagination."""
        params: dict[str, Any] = {
            "search": query,
            "per-page": 100,
            "mailto": self.email,
            "cursor": "*",
        }

        papers: list[dict[str, Any]] = []
        retrieved = 0

        while retrieved < max_retrieval:
            data = self._request_with_retry(self.base_url, params)
            if data is None:
                break

            meta = data.get("meta", {})
            next_cursor = meta.get("next_cursor")
            items = data.get("results", [])

            for item in items:
                papers.append(self._standardize(item))
                retrieved += 1
                if retrieved >= max_retrieval:
                    break

            # Report progress after each page
            if progress_callback is not None:
                progress_callback(retrieved, max_retrieval, f"Fetching from OpenAlex...")

            if not next_cursor or retrieved >= max_retrieval:
                break

            params["cursor"] = next_cursor
            if API_DELAY > 0:
                time.sleep(API_DELAY)

        logger.info("Retrieved %d papers from OpenAlex.", retrieved)
        return papers

    @staticmethod
    def _standardize(item: dict[str, Any]) -> dict[str, Any]:
        """Normalise an OpenAlex work item to the common paper schema."""
        # Reconstruct abstract from inverted index
        abstract_text = reconstruct_openalex_abstract(
            item.get("abstract_inverted_index")
        )

        # Extract authors
        authors: list[dict[str, str]] = []
        for a in item.get("authorships", []):
            author_obj = a.get("author")
            if author_obj:
                name = author_obj.get("display_name")
                if name:
                    authors.append({"name": name})

        # Open Access info
        is_oa = item.get("is_oa", False)
        open_access_pdf: Optional[dict[str, str]] = None
        best_oa = item.get("best_oa_location")
        if best_oa:
            pdf_url = best_oa.get("pdf_url")
            if pdf_url:
                open_access_pdf = {"url": pdf_url, "status": "open"}

        # Journal
        journal: Optional[str] = None
        primary_location = item.get("primary_location")
        if primary_location:
            source = primary_location.get("source")
            if source:
                journal = source.get("display_name")

        # DOI
        doi_raw: Optional[str] = item.get("doi")
        doi: Optional[str] = None
        if doi_raw and isinstance(doi_raw, str):
            doi = doi_raw.replace("https://doi.org/", "").lower()

        # Publication type
        pub_type = item.get("type")
        publication_types: list[str] = [pub_type] if pub_type else []

        return {
            "paperId": item.get("id"),  # OpenAlex ID (e.g. "W12345")
            "externalIds": {"DOI": doi} if doi else {},
            "title": item.get("display_name", ""),
            "year": item.get("publication_year"),
            "referenceCount": item.get("referenced_works_count"),
            "citationCount": item.get("cited_by_count"),
            "isOpenAccess": is_oa,
            "openAccessPdf": open_access_pdf,
            "publicationTypes": publication_types,
            "publicationDate": item.get("publication_date"),
            "journal": journal,
            "authors": authors,
            "abstract": abstract_text if abstract_text else None,
            "source_provider": "openalex",
        }

    @staticmethod
    def _request_with_retry(
        url: str,
        params: dict[str, Any],
        max_retries: int = MAX_RETRIES,
    ) -> Optional[dict]:
        """Make a GET request with retry logic."""
        for attempt in range(1, max_retries + 1):
            try:
                r = requests.get(url, params=params, timeout=30)
                r.raise_for_status()
                return r.json()
            except requests.exceptions.Timeout:
                logger.warning("OpenAlex timeout (attempt %d/%d).", attempt, max_retries)
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else "unknown"
                logger.warning("OpenAlex HTTP %s (attempt %d/%d).", status, attempt, max_retries)
                if status == 429:
                    time.sleep(5 * attempt)
                elif status in (400, 404):
                    return None
            except requests.exceptions.ConnectionError:
                logger.warning("OpenAlex connection error (attempt %d/%d).", attempt, max_retries)
            except Exception:
                logger.exception("Unexpected OpenAlex error (attempt %d/%d).", attempt, max_retries)

            if attempt < max_retries:
                time.sleep(2 ** attempt)
        return None
