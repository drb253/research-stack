"""PubMed provider.

Wraps the NCBI E-utilities API (``eutils.ncbi.nlm.nih.gov/entrez/eutils``)
and normalises output to match the Semantic Scholar paper schema.

Note: PubMed uses a two-step process:
1. ``esearch.fcgi`` — get matching PubMed IDs
2. ``efetch.fcgi`` — fetch details for those IDs (in XML, parsed here)

PubMed has limited OA metadata compared to OpenAlex/Semantic Scholar.
"""

from __future__ import annotations

import logging
import os
import time
import xml.etree.ElementTree as ET
from typing import Any, Optional

import requests

from ..models import apply_filters, FilterConfig
from .base import BaseProvider, ProgressCallback
from . import register_provider

logger = logging.getLogger(__name__)

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
API_DELAY = 0.35  # NCBI requests ≤3/sec without an API key
MAX_RETRIES = 3


@register_provider("pubmed")
class PubMedProvider(BaseProvider):
    """Provider for the NCBI PubMed E-utilities."""

    provider_name = "pubmed"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or os.environ.get("NCBI_API_KEY")
        self.tool = "SemanticScholarRegexMCP"
        self.email = os.environ.get("NCBI_EMAIL", "mcp@example.com")

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
        """Search PubMed for papers matching *query*."""
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
        """Search PubMed for papers by a specific author.

        Uses the PubMed ``[au]`` field tag for more precise author queries.
        """
        # Use PubMed's author field tag for more precise queries
        pubmed_query = f"{author_name}[au]"
        papers = self._fetch_all(pubmed_query, max_retrieval, progress_callback=progress_callback)
        meta = {"total_from_api": len(papers)}

        # Post-filter on authors list for accuracy
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
        """Fetch papers from PubMed using esearch + efetch."""
        # Step 1: Search for IDs
        all_pmids: list[str] = []
        retstart = 0
        retmax = 500  # NCBI max per page

        while retstart < max_retrieval:
            search_params: dict[str, Any] = {
                "db": "pubmed",
                "term": query,
                "retmax": min(retmax, max_retrieval - retstart),
                "retstart": retstart,
                "retmode": "json",
                "tool": self.tool,
                "email": self.email,
            }
            if self.api_key:
                search_params["api_key"] = self.api_key

            search_data = self._request_with_retry(ESEARCH_URL, search_params)
            if search_data is None:
                break

            esearch_result = search_data.get("esearchresult", {})
            ids = esearch_result.get("idlist", [])
            total_count_str = esearch_result.get("count", "0")
            try:
                total_count = int(total_count_str)
            except (ValueError, TypeError):
                total_count = 0

            if not ids:
                break

            all_pmids.extend(ids)
            retstart += len(ids)

            # Report progress during ID search
            if progress_callback is not None:
                progress_callback(retstart, min(max_retrieval, total_count), f"Searching PubMed IDs...")

            if retstart >= total_count or retstart >= max_retrieval:
                break

            if API_DELAY > 0:
                time.sleep(API_DELAY)

        if not all_pmids:
            logger.info("No PubMed IDs found for query.")
            return []

        # Step 2: Fetch details for all PMIDs (in batches of 100)
        papers: list[dict[str, Any]] = []
        batch_size = 100
        total_to_fetch = len(all_pmids)

        for i in range(0, total_to_fetch, batch_size):
            batch = all_pmids[i : i + batch_size]
            fetch_params: dict[str, Any] = {
                "db": "pubmed",
                "id": ",".join(batch),
                "retmode": "xml",
                "rettype": "abstract",
                "tool": self.tool,
                "email": self.email,
            }
            if self.api_key:
                fetch_params["api_key"] = self.api_key

            # Report progress during fetch
            if progress_callback is not None:
                progress_callback(i + len(batch), total_to_fetch, f"Fetching PubMed details...")

            xml_text = self._request_with_retry_text(EFETCH_URL, fetch_params)
            if xml_text:
                batch_papers = self._parse_pubmed_xml(xml_text)
                papers.extend(batch_papers)

            if i + batch_size < len(all_pmids) and API_DELAY > 0:
                time.sleep(API_DELAY)

        logger.info("Retrieved %d papers from PubMed.", len(papers))
        return papers

    @staticmethod
    def _parse_pubmed_xml(xml_text: str) -> list[dict[str, Any]]:
        """Parse PubMed XML efetch response into paper dicts."""
        papers: list[dict[str, Any]] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.warning("Failed to parse PubMed XML: %s", e)
            return papers

        for article_elem in root.findall(".//PubmedArticle"):
            try:
                paper = _parse_single_article(article_elem)
                if paper:
                    papers.append(paper)
            except Exception as e:
                logger.debug("Skipping malformed PubMed article: %s", e)
                continue

        return papers

    @staticmethod
    def _request_with_retry(
        url: str,
        params: dict[str, Any],
        max_retries: int = MAX_RETRIES,
    ) -> Optional[dict]:
        """Make a GET request expecting JSON, with retry logic."""
        for attempt in range(1, max_retries + 1):
            try:
                r = requests.get(url, params=params, timeout=30)
                r.raise_for_status()
                return r.json()
            except requests.exceptions.Timeout:
                logger.warning("PubMed timeout (attempt %d/%d).", attempt, max_retries)
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else "unknown"
                logger.warning("PubMed HTTP %s (attempt %d/%d).", status, attempt, max_retries)
                if status == 429:
                    time.sleep(5 * attempt)
                elif status in (400, 404):
                    return None
            except requests.exceptions.ConnectionError:
                logger.warning("PubMed connection error (attempt %d/%d).", attempt, max_retries)
            except Exception:
                logger.exception("Unexpected PubMed error (attempt %d/%d).", attempt, max_retries)

            if attempt < max_retries:
                time.sleep(2 ** attempt)
        return None

    @staticmethod
    def _request_with_retry_text(
        url: str,
        params: dict[str, Any],
        max_retries: int = MAX_RETRIES,
    ) -> Optional[str]:
        """Make a GET request expecting text, with retry logic."""
        for attempt in range(1, max_retries + 1):
            try:
                r = requests.get(url, params=params, timeout=30)
                r.raise_for_status()
                return r.text
            except requests.exceptions.Timeout:
                logger.warning("PubMed timeout (attempt %d/%d).", attempt, max_retries)
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else "unknown"
                logger.warning("PubMed HTTP %s (attempt %d/%d).", status, attempt, max_retries)
                if status in (400, 404):
                    return None
            except requests.exceptions.ConnectionError:
                logger.warning("PubMed connection error (attempt %d/%d).", attempt, max_retries)
            except Exception:
                logger.exception("Unexpected PubMed error (attempt %d/%d).", attempt, max_retries)

            if attempt < max_retries:
                time.sleep(2 ** attempt)
        return None


def _parse_single_article(article_elem: ET.Element) -> Optional[dict[str, Any]]:
    """Parse a single PubmedArticle XML element into a paper dict."""
    medline = article_elem.find(".//MedlineCitation")
    if medline is None:
        return None

    # PMID
    pmid: Optional[str] = None
    pmid_elem = medline.find("PMID")
    if pmid_elem is not None:
        pmid = pmid_elem.text

    article = medline.find("Article")
    if article is None:
        return None

    # Title
    title: str = ""
    title_elem = article.find("ArticleTitle")
    if title_elem is not None:
        title = "".join(title_elem.itertext())

    # Abstract
    abstract: Optional[str] = None
    abstract_elem = article.find("Abstract")
    if abstract_elem is not None:
        parts: list[str] = []
        for label in abstract_elem.iter():
            if label.text and label.text.strip():
                parts.append(label.text.strip())
        abstract = " ".join(parts) if parts else None

    # Authors
    authors: list[dict[str, str]] = []
    author_list = article.find("AuthorList")
    if author_list is not None:
        for author_elem in author_list.findall("Author"):
            last = author_elem.find("LastName")
            fore = author_elem.find("ForeName")
            if last is not None or fore is not None:
                name = f"{fore.text if fore is not None else ''} {last.text if last is not None else ''}".strip()
                if name:
                    authors.append({"name": name})

    # Journal
    journal: Optional[str] = None
    journal_elem = article.find("Journal")
    if journal_elem is not None:
        title_elem = journal_elem.find("Title")
        if title_elem is not None:
            journal = title_elem.text

    # Year
    year: Optional[int] = None
    if journal_elem is not None:
        jissue = journal_elem.find("JournalIssue")
        if jissue is not None:
            pub_date = jissue.find("PubDate")
            if pub_date is not None:
                year_elem = pub_date.find("Year")
                if year_elem is not None:
                    try:
                        year = int(year_elem.text)
                    except (ValueError, TypeError):
                        pass

    # Publicaton date
    pub_date_str: Optional[str] = None
    if journal_elem is not None:
        jissue = journal_elem.find("JournalIssue")
        if jissue is not None:
            pub_date = jissue.find("PubDate")
            if pub_date is not None:
                parts = []
                for tag in ("Year", "Month", "Day"):
                    elem = pub_date.find(tag)
                    if elem is not None and elem.text:
                        parts.append(elem.text)
                if parts:
                    pub_date_str = "-".join(parts)

    # DOI from ArticleIdList
    doi: Optional[str] = None
    article_ids = article_elem.findall(".//ArticleId")
    for aid in article_ids:
        if aid.get("IdType") == "doi" and aid.text:
            doi = aid.text
            break

    # Publication types
    pub_types: list[str] = []
    pub_type_list = article.find("PublicationTypeList")
    if pub_type_list is not None:
        for pt in pub_type_list.findall("PublicationType"):
            if pt.text:
                pub_types.append(pt.text)

    return {
        "paperId": f"PMID:{pmid}" if pmid else None,
        "externalIds": (
            {"DOI": doi, "PubMed": pmid} if doi else {"PubMed": pmid}
        ) if pmid else {},
        "title": title,
        "year": year,
        "referenceCount": None,  # PubMed efetch doesn't include reference count
        "citationCount": None,   # PubMed efetch doesn't include citation count
        "isOpenAccess": False,   # Limited OA info without additional API calls
        "openAccessPdf": None,
        "publicationTypes": pub_types,
        "publicationDate": pub_date_str,
        "journal": journal,
        "authors": authors,
        "abstract": abstract,
        "source_provider": "pubmed",
    }
