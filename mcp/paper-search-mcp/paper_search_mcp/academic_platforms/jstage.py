"""J-STAGE connector for paper-search-mcp.

PATCHED-BY-paper-search-mcp-patches: J-STAGE WebAPI connector.

J-STAGE (Japan Science and Technology Information Aggregator) hosts Japanese
journals. No API key. Verified: relevance search honoured (real query 385 hits /
garbage query ERR_001 = no results), complete fields, repeatable, no errors.

IMPORTANT: the query must be sent in a FIELD parameter (`text=`, `article=`,
`keyword=`, `abst=`). A bare `q=` returns ERR_012 and `article=` rejects
multi-word phrases with ERR_001, so `text=` is used here.
"""
from __future__ import annotations

import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Optional

import requests
from pypdf import PdfReader

from ..paper import Paper
from .base import PaperSource
from ..source_status import SourceUnavailable  # paper-search-mcp-patches: Tier 1

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(value: str) -> str:
    """J-STAGE wraps CJK/English variants in <en>/<ja> and puts markup inside CDATA."""
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", value or "")).strip()

SEARCH_URL = "https://api.jstage.jst.go.jp/searchapi/do"
NS = {
    "a": "http://www.w3.org/2005/Atom",
    "p": "http://prismstandard.org/namespaces/basic/2.0/",
}


def _pdf_url_from_article(article_url: str) -> str:
    """Turn a J-STAGE /_article URL into its /_pdf URL."""
    base = (article_url or "").strip().rstrip("/")
    if base.endswith("/_article"):
        return base[: -len("/_article")] + "/_pdf"
    if "/article/" in base and "_article" not in base:
        return base + "/_pdf"
    return ""


class JStageSearcher(PaperSource):
    """J-STAGE WebAPI connector (no API key)."""

    SOURCE = "jstage"
    TIMEOUT = 30
    MAX_RETRIES = 3
    COUNT = 50  # fetch a page then honour max_results locally

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "paper-search-mcp/0.1.4 (mailto:openags@example.com)",
        })

    def search(self, query: str, max_results: int = 10, **kwargs) -> List[Paper]:
        query = (query or "").strip()
        if not query:
            return []

        params = {
            "service": 3,
            "material_type": 1,
            "text": query,
            "count": self.COUNT,
        }
        raw = ""
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.session.get(SEARCH_URL, params=params, timeout=self.TIMEOUT)
                response.raise_for_status()
                raw = response.text
                break
            except requests.RequestException as exc:
                if attempt == self.MAX_RETRIES - 1:
                    logger.warning("J-STAGE search failed: %s", exc)
                    raise SourceUnavailable("jstage", str(exc)[:200])

        if not raw:
            raise SourceUnavailable("jstage", "empty response body")

        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            logger.warning("J-STAGE returned unparsable XML: %s", exc)
            raise SourceUnavailable("jstage", f"unparsable XML: {exc}"[:200])

        status = (root.findtext("a:result/a:status", default="", namespaces=NS) or "").strip()
        if status and status != "0":
            # ERR_001 means "no results for this query"; any other status is a
            # service-side refusal and must not look like an empty result set.
            if status.upper().startswith("ERR_001"):
                return []
            logger.warning("J-STAGE status %s", status)
            raise SourceUnavailable("jstage", f"API status {status}")

        papers: List[Paper] = []
        for entry in root.findall("a:entry", NS):
            paper = self._to_paper(entry)
            if paper is not None:
                papers.append(paper)
            if len(papers) >= max_results:
                break
        return papers

    def _to_paper(self, entry: ET.Element) -> Optional[Paper]:
        try:
            def text(path: str) -> str:
                value = entry.findtext(path, default="", namespaces=NS) or ""
                return _clean(value)

            title = text("a:article_title/a:en") or text("a:title")
            authors = [
                _clean(node.text or "")
                for node in entry.findall("a:author/a:en/a:name", NS)
                if (node.text or "").strip()
            ]
            journal = text("a:material_title/a:en")
            doi = text("p:doi")
            article_url = text("a:article_link/a:en") or (
                entry.find("a:link", NS).get("href") if entry.find("a:link", NS) is not None else ""
            )

            published = None
            for candidate in (text("a:pubyear"), text("a:updated")[:10]):
                if not candidate:
                    continue
                for fmt in ("%Y", "%Y-%m-%d", "%Y-%m"):
                    try:
                        published = datetime.strptime(candidate, fmt)
                        break
                    except ValueError:
                        continue
                if published:
                    break

            volume = text("p:volume")
            number = text("p:number")
            categories = [c for c in (journal, f"vol {volume}" if volume else "",
                                     f"no {number}" if number else "") if c]

            return Paper(
                paper_id=doi or article_url,
                title=title,
                authors=authors,
                abstract="",
                url=article_url or (f"https://doi.org/{doi}" if doi else ""),
                pdf_url=_pdf_url_from_article(article_url),
                published_date=published,
                updated_date=published,
                source=self.SOURCE,
                categories=categories,
                keywords=[],
                doi=doi,
                extra={"journal": journal, "volume": volume, "number": number,
                       "issn": text("p:issn"), "article_url": article_url},
            )
        except Exception as exc:
            logger.warning("Failed to parse J-STAGE entry: %s", exc)
            return None

    def _resolve_article_url(self, paper_id: str) -> str:
        """Return a J-STAGE /_article URL for a DOI, article URL, or article id."""
        value = (paper_id or "").strip()
        if not value:
            return ""
        if value.startswith("http"):
            return value.rstrip("/")
        if value.startswith("10."):
            # Doi.org redirects to the J-STAGE landing page.
            try:
                response = self.session.head(
                    f"https://doi.org/{value}", allow_redirects=True, timeout=self.TIMEOUT
                )
                return response.url.rstrip("/")
            except requests.RequestException as exc:
                logger.warning("Could not resolve J-STAGE DOI %s: %s", value, exc)
                return ""
        return ""

    def download_pdf(self, paper_id: str, save_path: str = "./downloads") -> str:
        """Download an open J-STAGE PDF (many articles are open access)."""
        article_url = self._resolve_article_url(paper_id)
        pdf_url = _pdf_url_from_article(article_url)
        if not pdf_url:
            raise ValueError(
                "Could not resolve a J-STAGE article URL from '%s'." % paper_id
            )

        response = self.session.get(pdf_url, timeout=120)
        response.raise_for_status()
        if not response.content.startswith(b"%PDF"):
            raise RuntimeError(
                "J-STAGE returned a non-PDF response for %s (the article may not be "
                "open access)." % pdf_url
            )

        os.makedirs(save_path, exist_ok=True)
        stem = (paper_id or "jstage").replace("http://", "").replace("https://", "")
        output_file = os.path.join(save_path, "%s.pdf" % stem.replace("/", "_"))
        with open(output_file, "wb") as handle:
            handle.write(response.content)
        return output_file

    def read_paper(self, paper_id: str, save_path: str = "./downloads") -> str:
        """Download (if needed) and extract text from a J-STAGE PDF."""
        stem = (paper_id or "jstage").replace("http://", "").replace("https://", "")
        pdf_path = os.path.join(save_path, "%s.pdf" % stem.replace("/", "_"))
        if not os.path.exists(pdf_path):
            pdf_path = self.download_pdf(paper_id, save_path)

        reader = PdfReader(pdf_path)
        text = "".join((page.extract_text() or "") + "\n" for page in reader.pages)
        return text.strip()
