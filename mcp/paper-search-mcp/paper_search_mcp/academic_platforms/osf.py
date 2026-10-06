"""OSF Preprints connector for paper-search-mcp.

PATCHED-BY-paper-search-mcp-patches: SHARE (share.osf.io) search connector.

OSF Preprints hosts SocArXiv, PsyArXiv, EdArXiv, MetaArXiv and more. The OSF
REST API itself only supports field filters, so keyword search runs against
SHARE, the OSF-run aggregator whose Elasticsearch index covers those servers.
No API key.

SHARE ranks with OR semantics, so results are filtered to those whose title,
description or tags contain EVERY query term; a query with no such record
returns nothing rather than unrelated papers. Verified: real query 10/10 kept
and relevant, garbage query -> 0.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from pypdf import PdfReader

from ..paper import Paper
from .base import PaperSource
from ..source_status import SourceUnavailable  # paper-search-mcp-patches: Tier 1

logger = logging.getLogger(__name__)

SEARCH_URL = "https://share.osf.io/api/v2/search/creativeworks/_search"
OSF_DOWNLOAD = "https://osf.io/%s/download"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
EMPTY_ABSTRACT = "no abstract available"


def _osf_guid(value: str) -> str:
    """Extract an OSF guid from a DOI (10.31219/osf.io/<guid>), URL, or bare guid."""
    text = (value or "").strip()
    if not text:
        return ""
    match = re.search(r"osf\.io/(?:download/)?([a-z0-9]{5,})", text, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    if re.fullmatch(r"[a-z0-9]{5}", text, re.IGNORECASE):
        return text.lower()
    return ""


def _matches_terms(source: Dict[str, Any], terms: List[str]) -> bool:
    haystack = " ".join([
        str(source.get("title") or ""),
        str(source.get("description") or ""),
        " ".join(str(t) for t in (source.get("tags") or [])),
        " ".join(str(s) for s in (source.get("subjects") or [])),
    ]).lower().replace("-", " ")
    return all(term in haystack for term in terms)


class OSFSearcher(PaperSource):
    """OSF Preprints connector backed by the SHARE search API (no API key)."""

    SOURCE = "osf"
    TIMEOUT = 30
    MAX_RETRIES = 3

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def search(self, query: str, max_results: int = 10, **kwargs) -> List[Paper]:
        terms = [t for t in re.split(r"\s+", (query or "").strip().lower().replace("-", " ")) if t]
        if not terms:
            return []

        params = {"q": query, "size": min(max(max_results * 4, 25), 100)}
        hits: List[Dict[str, Any]] = []
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.session.get(SEARCH_URL, params=params, timeout=self.TIMEOUT)
                response.raise_for_status()
                hits = response.json().get("hits", {}).get("hits", []) or []
                break
            except (requests.RequestException, ValueError) as exc:
                if attempt == self.MAX_RETRIES - 1:
                    logger.warning("OSF/SHARE search failed: %s", exc)
                    raise SourceUnavailable("osf", str(exc)[:200])

        papers: List[Paper] = []
        for hit in hits:
            source = hit.get("_source") or {}
            if not _matches_terms(source, terms):
                continue
            paper = self._to_paper(source)
            if paper is not None:
                papers.append(paper)
            if len(papers) >= max_results:
                break
        return papers

    def _to_paper(self, source: Dict[str, Any]) -> Optional[Paper]:
        try:
            doi = ""
            guid = ""
            landing = ""
            for identifier in (source.get("identifiers") or []):
                text = str(identifier)
                if "doi.org/" in text and not doi:
                    doi = text.split("doi.org/", 1)[1].strip()
                if "osf.io/" in text and not landing:
                    landing = text.strip()
                    guid = _osf_guid(text)
            if not guid:
                guid = _osf_guid(str(source.get("id") or ""))

            published = None
            raw = str(source.get("date_published") or source.get("date") or "")[:10]
            if raw:
                try:
                    published = datetime.strptime(raw, "%Y-%m-%d")
                except ValueError:
                    published = None

            description = " ".join(str(source.get("description") or "").split())
            if description.lower().startswith(EMPTY_ABSTRACT):
                description = ""

            contributors = [
                " ".join(str(c).split())
                for c in (source.get("contributors") or []) if str(c).strip()
            ]
            subjects = [str(s) for s in (source.get("subjects") or []) if str(s).strip()]

            return Paper(
                paper_id=doi or guid or str(source.get("id") or ""),
                title=" ".join(str(source.get("title") or "").split()),
                authors=contributors,
                abstract=description,
                url=landing or (f"https://doi.org/{doi}" if doi else ""),
                pdf_url=OSF_DOWNLOAD % guid if guid else "",
                published_date=published,
                updated_date=published,
                source=self.SOURCE,
                categories=[str(source.get("type") or "preprint")],
                keywords=[str(t) for t in (source.get("tags") or [])][:8],
                doi=doi,
                extra={"osf_guid": guid, "type": source.get("type") or "",
                       "sources": source.get("sources") or [], "subjects": subjects[:6],
                       "retracted": bool(source.get("retracted") or source.get("withdrawn"))},
            )
        except Exception as exc:
            logger.warning("Failed to parse OSF/SHARE record: %s", exc)
            return None

    def download_pdf(self, paper_id: str, save_path: str = "./downloads") -> str:
        """Download an OSF preprint file via https://osf.io/<guid>/download."""
        guid = _osf_guid(paper_id)
        if not guid:
            raise ValueError("Could not derive an OSF guid from '%s'." % paper_id)

        response = requests.get(
            OSF_DOWNLOAD % guid, timeout=120, headers={"User-Agent": BROWSER_UA},
            allow_redirects=True,
        )
        response.raise_for_status()
        if not response.content.startswith(b"%PDF"):
            raise RuntimeError(
                "OSF file for guid %s is not a PDF (the preprint may supply only "
                "supplementary files)." % guid
            )

        os.makedirs(save_path, exist_ok=True)
        output_file = os.path.join(save_path, "osf_%s.pdf" % guid)
        with open(output_file, "wb") as handle:
            handle.write(response.content)
        return output_file

    def read_paper(self, paper_id: str, save_path: str = "./downloads") -> str:
        """Download (if needed) and extract text from an OSF PDF."""
        guid = _osf_guid(paper_id)
        pdf_path = os.path.join(save_path, "osf_%s.pdf" % guid)
        if not guid or not os.path.exists(pdf_path):
            pdf_path = self.download_pdf(paper_id, save_path)

        reader = PdfReader(pdf_path)
        text = "".join((page.extract_text() or "") + "\n" for page in reader.pages)
        return text.strip()
