"""NCBI Bookshelf connector for paper-search-mcp.

PATCHED-BY-paper-search-mcp-patches: source #25 (monographs, reports, chapters).

Why this source exists
----------------------
NCBI Bookshelf hosts full-text biomedical **books, reports, guidelines and
textbooks** -- material no journal index carries.  It is where GeneReviews,
StatPearls, WHO/NCBI reports, NCI PDQ summaries and methods monographs live, so
it covers reference/protocol literature the other 24 sources cannot reach.

API: E-utilities ``db=books`` (free; uses your NCBI API key, 10 req/s vs 3).
Measured: a real query matches 573 records and a nonsense query returns 0.

Record granularity: ``db=books`` also indexes in-book **tables and figures**,
which are noise for literature discovery, so those record types are filtered out.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

import requests

from ..config import ncbi_eutils_params
from ..paper import Paper
from ..source_status import (  # paper-search-mcp-patches: Tier 1/7
    SourceUnavailable,
    assert_not_botwall,
    assert_usable_bytes,
    request_json,
    search_terms,
)
from .base import PaperSource

logger = logging.getLogger(__name__)

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
SITE_URL = "https://www.ncbi.nlm.nih.gov/books/"

#: In-book float/figure records: not documents, so they are skipped.
_SKIP_TYPES = frozenset({"table", "figure"})

#: Record types that represent an actual document, preferred in this order.
_DOCUMENT_TYPES = ("book", "chapter", "part", "section", "collection", "other")


class BookshelfSearcher(PaperSource):
    """Search NCBI Bookshelf (free; uses NCBI_API_KEY when configured)."""

    SOURCE = "bookshelf"
    TIMEOUT = 30

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "paper-search-mcp/0.1.4 (mailto:openags@example.com)",
            "Accept": "application/json",
        })

    def search(self, query: str, max_results: int = 10, **kwargs) -> List[Paper]:
        """Search Bookshelf for books, chapters, reports and guidelines.

        Args:
            query: Free-text query (supports PubMed-style field tags, e.g.
                ``"base editing"[Title]``).
            max_results: Maximum documents to return (default: 10).
        """
        wanted = min(max(int(max_results or 10), 1), 100)
        # Over-fetch, because table/figure records are dropped below.
        retmax = min(max(wanted * 4, 20), 200)

        # Tier 2 ladder (measured on 'CRISPR base editing'):
        #   t1[Title] AND t2[Title] -> 7 records   (precise)
        #   t1 AND t2 AND t3        -> 138 records (balanced)
        #   raw query               -> 573 records (Bookshelf's default is loose)
        # A nonsense query returns 0 at every rung.
        terms = search_terms(query)
        candidates: List[str] = []
        if len(terms) >= 2:
            candidates.append(" AND ".join(f"{term}[Title]" for term in terms))
            candidates.append(" AND ".join(terms))
        candidates.append(str(query or "").strip())

        ids: List[str] = []
        for candidate in dict.fromkeys(c for c in candidates if c):
            search = request_json(
                self.session,
                ESEARCH_URL,
                self.SOURCE,
                params={"db": "books", "term": candidate, "retmax": retmax,
                        "retmode": "json", **ncbi_eutils_params()},
                timeout=self.TIMEOUT,
                max_retries=2,
            )
            ids = ((search or {}).get("esearchresult") or {}).get("idlist") or []
            if ids:
                logger.info("Bookshelf query mode %r -> %s ids", candidate[:60], len(ids))
                break

        if not ids:
            return []

        summary = request_json(
            self.session,
            ESUMMARY_URL,
            self.SOURCE,
            params={"db": "books", "id": ",".join(str(i) for i in ids),
                    "retmode": "json", **ncbi_eutils_params()},
            timeout=self.TIMEOUT,
            max_retries=2,
        )
        result = (summary or {}).get("result") or {}

        # Keep the API's own relevance order: promoting whole books above chapters
        # measurably hurt query fit (a book that merely mentions the terms outranks
        # the chapter that is actually about them).  Only non-documents are dropped.
        papers: List[Paper] = []
        for uid in ids:
            paper = self._to_paper(result.get(str(uid)))
            if paper is None:
                continue
            papers.append(paper)
            if len(papers) >= wanted:
                break
        logger.info("Bookshelf returned %s documents for: %s", len(papers), query)
        return papers

    def search_floats(self, query: str, max_results: int = 10,
                      kinds: Tuple[str, ...] = ("table", "figure")) -> List[Paper]:
        """Locate in-book tables and figures, e.g. a GeneReviews evidence table.

        ``search()`` deliberately drops these as discovery noise, but a table is
        exactly what has to be cited when it carries the data -- for example the
        repeat-size thresholds in a GeneReviews table.  This returns citable
        records (exact title, book/chapter accessions, precise Bookshelf URL)
        without requesting the bot-walled HTML.

        Verified 2026-09-29: ``"Table 1"[Title] AND spinocerebellar`` matches 27
        records, and esummary returns the table title with its NBK accession
        (e.g. "Table 5. Recommended Surveillance ...", accession NBK1184).
        """
        wanted = min(max(int(max_results or 10), 1), 100)
        retmax = min(max(wanted * 4, 20), 200)
        wanted_types = {str(kind).lower() for kind in kinds}

        terms = search_terms(query)
        candidates: List[str] = []
        if terms:
            candidates.append(" AND ".join(f"{term}[Title]" for term in terms))
            candidates.append(" AND ".join(terms))
        candidates.append(str(query or "").strip())

        ids: List[str] = []
        result: Dict[str, Any] = {}
        for candidate in dict.fromkeys(c for c in candidates if c):
            search = request_json(
                self.session,
                ESEARCH_URL,
                self.SOURCE,
                params={"db": "books", "term": candidate, "retmax": retmax,
                        "retmode": "json", **ncbi_eutils_params()},
                timeout=self.TIMEOUT,
                max_retries=2,
            )
            ids = ((search or {}).get("esearchresult") or {}).get("idlist") or []
            if not ids:
                continue

            summary = request_json(
                self.session,
                ESUMMARY_URL,
                self.SOURCE,
                params={"db": "books", "id": ",".join(str(i) for i in ids),
                        "retmode": "json", **ncbi_eutils_params()},
                timeout=self.TIMEOUT,
                max_retries=2,
            )
            result = (summary or {}).get("result") or {}
            # Stop as soon as a rung produced the record type that was asked for.
            if any(
                str((result.get(str(uid)) or {}).get("rtype") or "").lower()
                in wanted_types
                for uid in ids
            ):
                break

        papers: List[Paper] = []
        for uid in ids:
            record = result.get(str(uid))
            if not isinstance(record, dict):
                continue
            if str(record.get("rtype") or "").lower() not in wanted_types:
                continue
            paper = self._to_float_paper(record)
            if paper is None:
                continue
            papers.append(paper)
            if len(papers) >= wanted:
                break
        logger.info("Bookshelf returned %s tables/figures for: %s", len(papers), query)
        return papers

    @staticmethod
    def _to_float_paper(record: Dict[str, Any]) -> Optional[Paper]:
        """A citable table/figure record (the type ``search()`` filters out)."""
        accession = str(record.get("accessionid") or "").strip()
        title = " ".join(str(record.get("title") or "").split())
        if not accession or not title:
            return None

        # 'rid' identifies the float itself, so it gives the exact table URL.
        rid = str(record.get("rid") or "").strip()
        url = f"{SITE_URL}{rid}/" if rid else f"{SITE_URL}{accession}/"

        published: Optional[datetime] = None
        pubdate = str(record.get("pubdate") or "").strip()
        for fmt in ("%Y/%m/%d %H:%M", "%Y/%m/%d", "%Y-%m-%d", "%Y"):
            try:
                published = datetime.strptime(pubdate[:len(pubdate)], fmt)
                break
            except ValueError:
                continue

        return Paper(
            paper_id=rid or accession,
            title=title,
            authors=[],
            abstract="",
            doi="",
            published_date=published,
            pdf_url="",
            url=url,
            source="bookshelf",
            categories=[str(record.get("rtype") or "").lower()],
            keywords=[],
            citations=0,
            extra={
                "record_type": str(record.get("rtype") or "").lower(),
                "bookshelf_id": str(record.get("uid", "")),
                "book_accession": record.get("bookaccessionid", ""),
                "chapter_accession": record.get("chapteraccessionid", ""),
                "full_text_available": False,
                "full_text_note": (
                    "NCBI Bookshelf answers automated requests for its HTML with "
                    "a reCAPTCHA challenge (HTTP 200 plus a challenge page), so "
                    "this table's contents must be read in a browser; the "
                    "citation above is exact."
                ),
            },
        )

    def read_chapter(self, accession: str) -> str:
        """Bookshelf chapter text, or a truthful report that it is bot-walled.

        Measured 2026-09-29: ``/books/NBK1116/`` answers HTTP 200 carrying
        "<title>Checking your browser - reCAPTCHA</title>".  A scraper that only
        checks the status code reads that as success and extracts nothing, so the
        block is detected explicitly and raised as unavailability -- never
        returned as an empty document.
        """
        accession = str(accession or "").strip()
        if not accession:
            raise ValueError("Invalid accession: accession is empty")

        response = self.session.get(f"{SITE_URL}{accession}/", timeout=self.TIMEOUT)
        assert_not_botwall(self.SOURCE, response.text, response.status_code)
        if response.status_code != 200:
            raise SourceUnavailable(
                self.SOURCE,
                f"Bookshelf chapter unavailable (HTTP {response.status_code})",
                http_status=response.status_code,
            )

        stripped = re.sub(
            r"<script.*?</script>|<style.*?</style>", " ", response.text,
            flags=re.S | re.I,
        )
        text = " ".join(re.sub(r"<[^>]+>", " ", stripped).split())
        assert_usable_bytes(
            self.SOURCE, text.encode("utf-8"), 500, label="chapter text"
        )
        return text

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _parse_bookinfo(raw: Any) -> Dict[str, str]:
        """Pull the parent book's title/authors/publisher from the XML fragment."""
        info: Dict[str, str] = {}
        if not raw:
            return info
        try:
            root = ET.fromstring(f"<root>{raw}</root>")
        except ET.ParseError:
            info["book_title"] = " ".join(re.sub(r"<[^>]+>", " ", str(raw)).split())[:300]
            return info

        wanted = {"title": "book_title", "booktitle": "book_title",
                  "author": "authors", "authors": "authors",
                  "publisher": "publisher", "year": "year"}
        for element in root.iter():
            key = wanted.get(str(element.tag).lower())
            if not key or info.get(key):
                continue
            text = " ".join("".join(element.itertext()).split())
            if text:
                info[key] = text[:300]
        return info

    def _to_paper(self, record: Any) -> Optional[Paper]:
        if not isinstance(record, dict):
            return None

        record_type = str(record.get("rtype") or "").lower()
        if record_type in _SKIP_TYPES:
            return None

        accession = str(record.get("accessionid") or "").strip()
        title = " ".join(str(record.get("title") or "").split())
        if not accession or not title:
            return None

        book = self._parse_bookinfo(record.get("bookinfo"))
        authors = [name.strip() for name in re.split(r"[;,]\s*", book.get("authors", ""))
                   if name.strip()]
        if not authors and book.get("book_title"):
            authors = [book["book_title"]]

        published: Optional[datetime] = None
        pubdate = str(record.get("pubdate") or "").strip()
        for fmt in ("%Y/%m/%d %H:%M", "%Y/%m/%d", "%Y-%m-%d", "%Y"):
            try:
                published = datetime.strptime(pubdate[:len(pubdate)], fmt)
                break
            except ValueError:
                continue

        abstract = " ".join(str(record.get("text") or "").split())[:2000]
        if not abstract and book.get("book_title"):
            abstract = f"Part of: {book['book_title']}"

        return Paper(
            paper_id=accession,
            title=title,
            authors=authors,
            abstract=abstract,
            doi="",
            published_date=published,
            pdf_url="",
            url=f"{SITE_URL}{accession}/",
            source=self.SOURCE,
            categories=[item for item in (record_type, book.get("book_title")) if item],
            keywords=[book["book_title"]] if book.get("book_title") else [],
            citations=0,
            extra={
                "record_type": record_type,
                "book_title": book.get("book_title", ""),
                "publisher": book.get("publisher", ""),
                "book_accession": record.get("bookaccessionid", ""),
                "chapter_accession": record.get("chapteraccessionid", ""),
                "bookshelf_id": str(record.get("uid", "")),
            },
        )
