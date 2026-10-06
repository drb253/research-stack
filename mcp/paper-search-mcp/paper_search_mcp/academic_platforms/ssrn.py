"""SSRN (Social Science Research Network) connector for paper-search-mcp.

PATCHED-BY-paper-search-mcp-patches: SSRN search via OpenAlex/Crossref.

SSRN's own web search answers non-browser clients with HTTP 403 (Cloudflare bot
detection), so this connector searches SSRN's indexed metadata instead:

  * OpenAlex, filtered to the SSRN source (ISSN 1556-5068)   -- primary
  * Crossref, filtered to SSRN's DOI prefix (10.2139)        -- fallback

Only publicly available metadata is used (title, authors, year, DOI, citation
count, landing URL).  SSRN abstracts are not published in open metadata, so the
``abstract`` field is usually empty rather than wrong.

PDF download stays best-effort: SSRN requires a browser session for delivery.
"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .base import PaperSource
from ..config import get_env  # paper-search-mcp-patches: OpenAlex key/email
from ..source_status import (  # paper-search-mcp-patches: Tier 1/2 helpers
    SourceUnavailable,
    and_query,
    search_terms,
)
from ..paper import Paper

logger = logging.getLogger(__name__)


def _verify_all_terms(query: str, papers: List[Paper]) -> List[Paper]:
    """Tier 2 precision: keep only records containing every query term.

    OpenAlex/Crossref both match fuzzily, so SSRN's fallback could return
    off-topic records for a query with no real matches (measured: "Justices'
    Forfeiture Ruling" for a garbage query).  Papers with no abstract are judged
    on their title alone.
    """
    terms = [t.lower() for t in search_terms(query)]
    if len(terms) < 2:
        return papers
    keep = []
    for paper in papers:
        haystack = f"{paper.title or ''} {paper.abstract or ''}".lower()
        if all(term in haystack for term in terms):
            keep.append(paper)
    return keep


class SSRNSearcher(PaperSource):
    """SSRN connector backed by the OpenAlex/Crossref metadata indexes.

    Capabilities:
    - **search**: keyword search over SSRN content (via OpenAlex, then Crossref)
    - **download_pdf**: best-effort (SSRN usually requires a browser login)
    - **read_paper**: best-effort (depends on a downloadable PDF)

    No API key required.
    """

    BASE_URL = "https://papers.ssrn.com"
    OPENALEX_URL = "https://api.openalex.org/works"
    CROSSREF_URL = "https://api.crossref.org/works"
    SSRN_ISSN = "1556-5068"
    SSRN_DOI_PREFIX = "10.2139"
    USER_AGENT = (
        "paper-search-mcp/0.1.4 (mailto:openags@example.com; "
        "+https://github.com/openags/paper-search-mcp)"
    )
    _RATE_LIMIT_SECONDS = 1.0  # polite delay between requests

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.USER_AGENT,
                "Accept": "application/json",
            }
        )
        self._last_request_time: float = 0.0

    # ------------------------------------------------------------------
    # PaperSource interface
    # ------------------------------------------------------------------

    def search(self, query: str, max_results: int = 10, **kwargs) -> List[Paper]:
        """Search SSRN content by keyword.

        Args:
            query: Keyword query (e.g., "corporate governance").
            max_results: Maximum number of papers to return.

        Returns:
            List of Paper objects (metadata only).
        """
        papers = self._search_openalex(query, max_results)
        if papers:
            return _verify_all_terms(query, papers)
        return _verify_all_terms(
            query, self._search_crossref(query, max_results)
        )

    # ------------------------------------------------------------------
    # OpenAlex (primary)
    # ------------------------------------------------------------------

    def _search_openalex(self, query: str, max_results: int) -> List[Paper]:
        # Tier 2: a bare search= plus the SSRN ISSN filter matched 5 unrelated
        # records for a garbage query, so scope it to the title as well.
        terms = search_terms(query)
        title_filter = (
            f",title.search:({and_query(terms)})" if len(terms) >= 2 else ""
        )
        params = {
            "search": query,
            "filter": (
                f"primary_location.source.issn:{self.SSRN_ISSN}{title_filter}"
            ),
            # Use the configured key/email: without them OpenAlex rate-limits
            # these requests (measured: HTTP 429 Too Many Requests).
            **({"api_key": get_env("OPENALEX_API_KEY", "").strip()}
               if get_env("OPENALEX_API_KEY", "").strip() else {}),
            **({"mailto": get_env("OPENALEX_EMAIL", "").strip()}
               if get_env("OPENALEX_EMAIL", "").strip() else {}),
            "per-page": min(max(max_results, 1), 200),
            "select": (
                "id,doi,title,publication_date,authorships,"
                "abstract_inverted_index,cited_by_count,primary_location,"
                "best_oa_location,type"
            ),
        }
        try:
            self._throttle()
            response = self.session.get(self.OPENALEX_URL, params=params, timeout=30)
            response.raise_for_status()
            results = response.json().get("results", []) or []
        except (requests.RequestException, ValueError) as exc:
            logger.warning("SSRN OpenAlex search failed: %s", exc)
            raise SourceUnavailable("ssrn", f"OpenAlex: {exc}"[:200])

        papers: List[Paper] = []
        for item in results:
            paper = self._parse_openalex_work(item)
            if paper is not None:
                papers.append(paper)
            if len(papers) >= max_results:
                break
        return papers

    @staticmethod
    def _abstract_from_inverted_index(index: Optional[Dict[str, List[int]]]) -> str:
        """Rebuild an abstract from OpenAlex's inverted index, when present."""
        if not index:
            return ""
        positions = []
        for word, spots in index.items():
            for spot in spots or []:
                positions.append((spot, word))
        positions.sort(key=lambda pair: pair[0])
        return " ".join(word for _, word in positions)

    def _parse_openalex_work(self, item: Dict[str, Any]) -> Optional[Paper]:
        try:
            doi = str(item.get("doi") or "").replace("https://doi.org/", "").strip()

            location = item.get("primary_location") or {}
            landing = str(location.get("landing_page_url") or "").strip()
            if not landing and doi:
                landing = f"https://doi.org/{doi}"

            best_oa = item.get("best_oa_location") or {}
            pdf_url = str(best_oa.get("pdf_url") or "").strip()

            authors: List[str] = []
            for authorship in item.get("authorships") or []:
                name = ((authorship or {}).get("author") or {}).get("display_name")
                if name:
                    authors.append(str(name))

            published = None
            raw_date = item.get("publication_date")
            if raw_date:
                try:
                    published = datetime.strptime(str(raw_date), "%Y-%m-%d")
                except ValueError:
                    published = None

            abstract_id = self._extract_abstract_id(doi) or self._extract_abstract_id(landing)
            paper_id = f"ssrn:{abstract_id}" if abstract_id else (doi or str(item.get("id") or ""))

            return Paper(
                paper_id=paper_id,
                title=str(item.get("title") or "").strip(),
                authors=authors,
                abstract=self._abstract_from_inverted_index(item.get("abstract_inverted_index")),
                url=landing,
                pdf_url=pdf_url,
                published_date=published,
                updated_date=published,
                source="ssrn",
                categories=[str(item.get("type") or "preprint")],
                keywords=[],
                citations=int(item.get("cited_by_count") or 0),
                doi=doi,
                extra={"index": "openalex", "ssrn_abstract_id": abstract_id},
            )
        except Exception as exc:
            logger.warning("Failed to parse SSRN OpenAlex record: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Crossref (fallback)
    # ------------------------------------------------------------------

    def _search_crossref(self, query: str, max_results: int) -> List[Paper]:
        params = {
            # Tier 2: title-scoped Crossref search (see the OpenAlex path).
            "query.title": query,
            "filter": f"prefix:{self.SSRN_DOI_PREFIX}",
            "rows": min(max(max_results, 1), 100),
            "select": "DOI,title,author,published,issued,container-title,abstract,URL,type,publisher",
        }
        try:
            self._throttle()
            response = self.session.get(self.CROSSREF_URL, params=params, timeout=30)
            response.raise_for_status()
            results = response.json().get("message", {}).get("items", []) or []
        except (requests.RequestException, ValueError) as exc:
            logger.warning("SSRN Crossref search failed: %s", exc)
            raise SourceUnavailable("ssrn", f"Crossref: {exc}"[:200])

        papers: List[Paper] = []
        for item in results:
            paper = self._parse_crossref_item(item)
            if paper is not None:
                papers.append(paper)
            if len(papers) >= max_results:
                break
        return papers

    def _parse_crossref_item(self, item: Dict[str, Any]) -> Optional[Paper]:
        try:
            doi = str(item.get("DOI") or "").strip()

            titles = item.get("title") or []
            title = str(titles[0]).strip() if titles else ""

            authors: List[str] = []
            for author in item.get("author") or []:
                if not isinstance(author, dict):
                    continue
                name = " ".join(
                    part for part in (author.get("given"), author.get("family")) if part
                ).strip()
                if name:
                    authors.append(name)

            published = None
            for key in ("published", "issued"):
                parts = ((item.get(key) or {}).get("date-parts") or [[None]])[0]
                if parts and parts[0]:
                    try:
                        year = int(parts[0])
                        month = int(parts[1]) if len(parts) > 1 and parts[1] else 1
                        day = int(parts[2]) if len(parts) > 2 and parts[2] else 1
                        published = datetime(year, month, day)
                    except (ValueError, TypeError):
                        published = None
                if published:
                    break

            landing = str(item.get("URL") or "").strip()
            if not landing and doi:
                landing = f"https://doi.org/{doi}"

            abstract = re.sub(r"<[^>]+>", " ", str(item.get("abstract") or "")).strip()

            abstract_id = self._extract_abstract_id(doi)
            paper_id = f"ssrn:{abstract_id}" if abstract_id else doi
            containers = item.get("container-title") or []

            return Paper(
                paper_id=paper_id,
                title=title,
                authors=authors,
                abstract=abstract,
                url=landing,
                pdf_url="",
                published_date=published,
                updated_date=published,
                source="ssrn",
                categories=[str(item.get("type") or "")],
                keywords=[],
                citations=0,
                doi=doi,
                extra={
                    "index": "crossref",
                    "publisher": item.get("publisher") or "",
                    "container": containers[0] if containers else "",
                    "ssrn_abstract_id": abstract_id,
                },
            )
        except Exception as exc:
            logger.warning("Failed to parse SSRN Crossref record: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        """Enforce a polite per-request rate limit."""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self._RATE_LIMIT_SECONDS:
            time.sleep(self._RATE_LIMIT_SECONDS - elapsed)
        self._last_request_time = time.monotonic()

    @staticmethod
    def _extract_abstract_id(paper_id: str) -> str:
        """Extract the numeric SSRN abstract id from id/url/DOI variants."""
        value = (paper_id or "").strip()
        if not value:
            return ""

        if value.lower().startswith("ssrn:"):
            value = value.split(":", 1)[1]

        if value.isdigit():
            return value

        match = re.search(r"abstract(?:_id)?[=_](\d+)", value)
        if match:
            return match.group(1)

        # DOI form used by OpenAlex/Crossref: 10.2139/ssrn.183908
        match = re.search(r"ssrn\.(\d+)", value, re.IGNORECASE)
        if match:
            return match.group(1)

        return ""

    def _browser_headers(self) -> Dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
        }

    def _resolve_pdf_url(self, abstract_id: str) -> str:
        """Resolve a direct PDF URL from the SSRN abstract page when available."""
        abstract_url = f"{self.BASE_URL}/sol3/papers.cfm?abstract_id={abstract_id}"
        try:
            response = self.session.get(
                abstract_url, timeout=20, headers=self._browser_headers()
            )
            response.raise_for_status()
        except requests.RequestException:
            return ""

        soup = BeautifulSoup(response.text, "html.parser")
        link_candidates = [
            "a[title*='Download PDF' i]",
            "a[href*='Delivery.cfm']",
            "a[href*='.pdf']",
            "a[href*='download']",
            "a[href*='abstract_id=']",
        ]

        for selector in link_candidates:
            for anchor in soup.select(selector):
                href = (anchor.get("href") or "").strip()
                if not href:
                    continue

                candidate = urljoin(self.BASE_URL, href)
                if "delivery.cfm" in candidate.lower() or candidate.lower().endswith(".pdf"):
                    return candidate

        return ""

    def download_pdf(self, paper_id: str, save_path: str = "./downloads") -> str:
        """Download an SSRN PDF when a public direct link is available.

        SSRN generally requires a browser login for PDF delivery, so this stays
        best-effort and returns an explanatory message when it cannot resolve one.

        Args:
            paper_id: SSRN ID in ``ssrn:<id>`` format, raw numeric id, DOI, or URL.
            save_path: Directory to save downloaded PDF.

        Returns:
            Saved PDF path on success, otherwise an explanatory message.
        """
        abstract_id = self._extract_abstract_id(paper_id)
        if not abstract_id:
            return f"Invalid SSRN paper id: {paper_id}"

        pdf_url = self._resolve_pdf_url(abstract_id)
        if not pdf_url:
            return (
                f"No publicly accessible SSRN PDF URL found for {abstract_id}. "
                "SSRN requires a browser login for delivery; open "
                f"{self.BASE_URL}/sol3/papers.cfm?abstract_id={abstract_id} manually."
            )

        os.makedirs(save_path, exist_ok=True)
        output_path = os.path.join(save_path, f"ssrn_{abstract_id}.pdf")

        try:
            response = self.session.get(
                pdf_url, stream=True, timeout=60, headers=self._browser_headers()
            )
            response.raise_for_status()

            content_type = (response.headers.get("content-type") or "").lower()
            first_chunk = next(response.iter_content(chunk_size=1024), b"")
            if "pdf" not in content_type and not first_chunk.startswith(b"%PDF"):
                return (
                    f"Resolved SSRN URL is not a direct PDF ({pdf_url}). "
                    "This likely requires browser login."
                )

            with open(output_path, "wb") as file_obj:
                if first_chunk:
                    file_obj.write(first_chunk)
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        file_obj.write(chunk)
            return output_path
        except requests.RequestException as exc:
            return f"SSRN PDF download failed for {abstract_id}: {exc}"

    def read_paper(self, paper_id: str, save_path: str = "./downloads") -> str:
        """Download and extract text from an SSRN PDF when accessible."""
        pdf_path = self.download_pdf(paper_id, save_path)
        if not pdf_path.endswith(".pdf"):
            return pdf_path

        try:
            from pypdf import PdfReader

            reader = PdfReader(pdf_path)
            text_parts = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)

            if not text_parts:
                return f"SSRN PDF downloaded to {pdf_path}, but no extractable text was found."
            return "\n\n".join(text_parts)
        except Exception as exc:
            return f"SSRN PDF downloaded to {pdf_path}, but text extraction failed: {exc}"
