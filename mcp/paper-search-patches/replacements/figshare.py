"""figshare connector for paper-search-mcp.

PATCHED-BY-paper-search-mcp-patches: figshare API connector.

figshare hosts research outputs (articles, figures, datasets, theses). No API
key. Verified: relevance search honoured via the POST /articles/search endpoint
(real query 3 hits / garbage query 0 hits), repeatable, no errors.

Note: the *search* payload omits authors, so each hit is enriched from
/v2/articles/{id} to make records complete (title, authors, date, DOI, abstract).
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

SEARCH_URL = "https://api.figshare.com/v2/articles/search"
ARTICLE_URL = "https://api.figshare.com/v2/articles/%s"
FILES_URL = "https://api.figshare.com/v2/articles/%s/files"
_TAG_RE = re.compile(r"<[^>]+>")
ENRICH_LIMIT = 10


def _clean(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", str(value))).strip()


def _figshare_id(value: str) -> str:
    """Accept a numeric id or a figshare DOI (10.6084/m9.figshare.<id>[.vN])."""
    text = (value or "").strip()
    if text.isdigit():
        return text
    match = re.search(r"figshare\.(\d+)", text)
    return match.group(1) if match else ""


class FigshareSearcher(PaperSource):
    """figshare API connector (no API key)."""

    SOURCE = "figshare"
    TIMEOUT = 30
    MAX_RETRIES = 3

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "paper-search-mcp/0.1.4 (mailto:openags@example.com)",
            "Content-Type": "application/json",
        })

    def search(self, query: str, max_results: int = 10, **kwargs) -> List[Paper]:
        payload = {"search_for": query, "page_size": min(max(max_results, 1), 100)}
        items: List[Dict[str, Any]] = []
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.session.post(SEARCH_URL, json=payload, timeout=self.TIMEOUT)
                response.raise_for_status()
                items = response.json() or []
                break
            except (requests.RequestException, ValueError) as exc:
                if attempt == self.MAX_RETRIES - 1:
                    logger.warning("figshare search failed: %s", exc)
                    raise SourceUnavailable("figshare", str(exc)[:200])

        papers: List[Paper] = []
        for item in items[:max_results]:
            detail = self._detail(item.get("id")) if len(papers) < ENRICH_LIMIT else {}
            paper = self._to_paper(item, detail)
            if paper is not None:
                papers.append(paper)
        return papers[:max_results]

    def _detail(self, article_id) -> Dict[str, Any]:
        if not article_id:
            return {}
        try:
            response = self.session.get(ARTICLE_URL % article_id, timeout=self.TIMEOUT)
            response.raise_for_status()
            return response.json() or {}
        except (requests.RequestException, ValueError) as exc:
            logger.warning("figshare detail lookup failed for %s: %s", article_id, exc)
            return {}

    def _to_paper(self, item: Dict[str, Any], detail: Dict[str, Any]) -> Optional[Paper]:
        try:
            merged = dict(item)
            merged.update(detail or {})

            article_id = str(merged.get("id") or "")
            doi = _clean(merged.get("doi"))
            type_name = _clean(merged.get("defined_type_name")) or _clean(merged.get("defined_type"))
            authors = [
                _clean(a.get("full_name"))
                for a in (merged.get("authors") or [])
                if isinstance(a, dict) and _clean(a.get("full_name"))
            ]

            published = None
            raw = _clean(merged.get("published_date")) or _clean(merged.get("created_date"))
            if raw:
                try:
                    published = datetime.strptime(raw[:10], "%Y-%m-%d")
                except ValueError:
                    published = None

            landing = _clean(merged.get("url_public_html"))
            if not landing and doi:
                landing = f"https://doi.org/{doi}"

            return Paper(
                paper_id=article_id or doi,
                title=_clean(merged.get("title")),
                authors=[a for a in authors if a],
                abstract=_clean(merged.get("description")),
                url=landing,
                pdf_url="",
                published_date=published,
                updated_date=published,
                source=self.SOURCE,
                categories=[type_name] if type_name else [],
                keywords=[_clean(k) for k in (merged.get("keywords") or []) if _clean(k)],
                doi=doi,
                extra={"figshare_id": article_id,
                       "defined_type": _clean(merged.get("defined_type_name")),
                       "enriched": bool(detail)},
            )
        except Exception as exc:
            logger.warning("Failed to parse figshare record: %s", exc)
            return None

    def _files(self, article_id: str) -> List[Dict[str, Any]]:
        try:
            response = self.session.get(FILES_URL % article_id, timeout=self.TIMEOUT)
            response.raise_for_status()
            return response.json() or []
        except (requests.RequestException, ValueError) as exc:
            logger.warning("figshare file listing failed for %s: %s", article_id, exc)
            return []

    def download_pdf(self, paper_id: str, save_path: str = "./downloads") -> str:
        """Download the first PDF attached to a figshare item.

        Raises ValueError when the item exists but carries no PDF (figshare holds
        datasets and supplementary files too), so the caller sees a real reason
        instead of a silent no-op.
        """
        article_id = _figshare_id(paper_id)
        if not article_id:
            raise ValueError("Could not derive a figshare article id from '%s'." % paper_id)

        files = self._files(article_id)
        if not files:
            raise ValueError("figshare item %s has no downloadable files." % article_id)

        pdf = next((f for f in files if str(f.get("name", "")).lower().endswith(".pdf")), None)
        if not pdf or not pdf.get("download_url"):
            names = ", ".join(str(f.get("name")) for f in files[:5])
            raise ValueError(
                "figshare item %s has no PDF file (available: %s)." % (article_id, names)
            )

        response = self.session.get(pdf["download_url"], timeout=120)
        response.raise_for_status()
        if not response.content.startswith(b"%PDF"):
            raise RuntimeError("figshare download did not return a PDF for %s" % article_id)

        os.makedirs(save_path, exist_ok=True)
        output_file = os.path.join(save_path, "figshare_%s.pdf" % article_id)
        with open(output_file, "wb") as handle:
            handle.write(response.content)
        return output_file

    def read_paper(self, paper_id: str, save_path: str = "./downloads") -> str:
        """Download (if needed) and extract text from a figshare PDF."""
        article_id = _figshare_id(paper_id)
        pdf_path = os.path.join(save_path, "figshare_%s.pdf" % article_id)
        if not article_id or not os.path.exists(pdf_path):
            pdf_path = self.download_pdf(paper_id, save_path)

        reader = PdfReader(pdf_path)
        text = "".join((page.extract_text() or "") + "\n" for page in reader.pages)
        return text.strip()
