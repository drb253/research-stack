"""DataCite connector for paper-search-mcp.

PATCHED-BY-paper-search-mcp-patches: DataCite REST API connector.

DataCite registers DOIs for datasets, software, theses and other research
outputs (complementing Zenodo).  No API key; a polite-pool User-Agent is sent.
Tier 2: queries are scoped to titles.title (plus resource-type-id=text first),
because the bare query= form returned 827 records with an off-topic top hit
while titles.title:(a AND b) returned 404 with an on-target top-3.
Tier 1: an unreachable DataCite raises SourceUnavailable instead of [].
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from pypdf import PdfReader

from ..paper import Paper
from ..source_status import (  # paper-search-mcp-patches: Tier 1/2 helpers
    field_and,
    search_ladder,
    search_terms,
)
from .base import PaperSource

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.datacite.org/dois"
POLITE_UA = "paper-search-mcp/0.1.4 (mailto:openags@example.com)"


def _first(value) -> str:
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else ""
    return str(value or "")


def _abstract(attributes: Dict[str, Any]) -> str:
    descriptions = [d for d in (attributes.get("descriptions") or []) if isinstance(d, dict)]
    for entry in descriptions:
        if (entry.get("descriptionType") or "").lower() == "abstract" and entry.get("description"):
            return " ".join(str(entry["description"]).split())
    for entry in descriptions:
        if entry.get("description"):
            return " ".join(str(entry["description"]).split())
    return ""


class DataCiteSearcher(PaperSource):
    """DataCite REST API connector (no API key)."""

    SOURCE = "datacite"
    TIMEOUT = 30
    MAX_RETRIES = 3

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": POLITE_UA, "Accept": "application/json"})

    def search(self, query: str, max_results: int = 10, **kwargs) -> List[Paper]:
        # Tier 1/2 (paper-search-mcp-patches): field-scoped ladder + availability.
        # Measured: the bare "query=" matched 827 records with an irrelevant top
        # hit, while titles.title + resource-type-id=text gave 404 with an
        # on-target top-3.
        terms = search_terms(query)
        ladder: List[tuple] = []
        if len(terms) >= 2:
            ladder.append(("title AND text-only", {
                "query": field_and("titles.title", terms),
                "resource-type-id": "text",
            }))
            ladder.append(("title AND", {"query": field_and("titles.title", terms)}))
        ladder.append(("raw", {"query": query}))

        attempts: List[tuple] = []
        for label, extra in ladder:
            params: Dict[str, Any] = {"page[size]": min(max(max_results, 1), 100)}
            params.update(extra)
            attempts.append((label, params))

        records, _label = search_ladder(
            "datacite",
            self.session,
            SEARCH_URL,
            attempts,
            lambda payload: payload.get("data") or [],
            timeout=self.TIMEOUT,
        )
        logger.info("DataCite query mode '%s' for: %s", _label, query)

        papers: List[Paper] = []
        for record in records:
            paper = self._to_paper(record)
            if paper is not None:
                papers.append(paper)
            if len(papers) >= max_results:
                break
        return papers

    def _to_paper(self, record: Dict[str, Any]) -> Optional[Paper]:
        try:
            attributes = record.get("attributes") or {}
            doi = str(attributes.get("doi") or record.get("id") or "").strip()

            authors = [
                " ".join(str(c.get("name")).split())
                for c in (attributes.get("creators") or [])
                if isinstance(c, dict) and c.get("name")
            ]

            published = None
            year = attributes.get("publicationYear")
            if year:
                try:
                    published = datetime(int(year), 1, 1)
                except (TypeError, ValueError):
                    published = None

            titles = [t.get("title") for t in (attributes.get("titles") or [])
                      if isinstance(t, dict) and t.get("title")]
            types = attributes.get("types") or {}
            resource_type = str(types.get("resourceTypeGeneral") or "") if isinstance(types, dict) else ""
            subjects = [str(s.get("subject")) for s in (attributes.get("subjects") or [])
                        if isinstance(s, dict) and s.get("subject")]
            content_url = str(attributes.get("contentUrl") or "").strip()

            return Paper(
                paper_id=doi,
                title=_first(titles),
                authors=authors,
                abstract=_abstract(attributes),
                url=str(attributes.get("url") or (f"https://doi.org/{doi}" if doi else "")).strip(),
                pdf_url=content_url if content_url.lower().endswith(".pdf") else "",
                published_date=published,
                updated_date=published,
                source=self.SOURCE,
                categories=[resource_type] if resource_type else [],
                keywords=subjects[:8],
                citations=int(attributes.get("citationCount") or 0),
                doi=doi,
                extra={"publisher": attributes.get("publisher") or "",
                       "resource_type": resource_type, "content_url": content_url},
            )
        except Exception as exc:
            logger.warning("Failed to parse DataCite record: %s", exc)
            return None

    def download_pdf(self, paper_id: str, save_path: str = "./downloads") -> str:
        """Download a DataCite file when the record exposes one directly.

        DataCite registers datasets and software as often as articles, so a
        missing file is reported explicitly instead of silently succeeding.
        """
        doi = (paper_id or "").strip()
        if not doi:
            raise ValueError("A DataCite DOI is required.")

        content_url = ""
        try:
            response = self.session.get(
                f"{SEARCH_URL}/{requests.utils.quote(doi, safe='')}", timeout=self.TIMEOUT
            )
            if response.status_code == 200:
                attributes = (response.json().get("data") or {}).get("attributes") or {}
                content_url = str(attributes.get("contentUrl") or "").strip()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("DataCite record lookup failed for %s: %s", doi, exc)

        if not content_url:
            raise ValueError(
                "DataCite record %s has no contentUrl, so no file can be downloaded "
                "(datasets/software are often link-only). Use the landing URL instead." % doi
            )

        response = self.session.get(content_url, timeout=120)
        response.raise_for_status()
        if not response.content.startswith(b"%PDF"):
            raise RuntimeError("DataCite contentUrl for %s is not a PDF (%s)." % (doi, content_url))

        os.makedirs(save_path, exist_ok=True)
        output_file = os.path.join(save_path, "%s.pdf" % doi.replace("/", "_"))
        with open(output_file, "wb") as handle:
            handle.write(response.content)
        return output_file

    def read_paper(self, paper_id: str, save_path: str = "./downloads") -> str:
        """Download (if needed) and extract text from a DataCite PDF."""
        pdf_path = os.path.join(save_path, "%s.pdf" % (paper_id or "").replace("/", "_"))
        if not os.path.exists(pdf_path):
            pdf_path = self.download_pdf(paper_id, save_path)

        reader = PdfReader(pdf_path)
        text = "".join((page.extract_text() or "") + "\n" for page in reader.pages)
        return text.strip()
