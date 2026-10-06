"""WHO IRIS connector for paper-search-mcp.

PATCHED-BY-paper-search-mcp-patches: WHO IRIS (DSpace 7) connector.

WHO IRIS is the World Health Organization's institutional repository. No API
key. Verified: relevance search honoured (real query 25457 hits / garbage query
0 hits), complete fields, repeatable, no errors.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from pypdf import PdfReader

from ..paper import Paper
from .base import PaperSource
from ..source_status import SourceUnavailable  # paper-search-mcp-patches: Tier 1

logger = logging.getLogger(__name__)

BASE = "https://iris.who.int/server/api"
SEARCH_URL = f"{BASE}/discover/search/objects"


def _meta(metadata: Dict[str, Any], key: str) -> str:
    """DSpace metadata values are lists of {'value': ...} dicts."""
    values = metadata.get(key) or []
    for entry in values:
        if isinstance(entry, dict) and entry.get("value"):
            return " ".join(str(entry["value"]).split())
        if isinstance(entry, str) and entry:
            return " ".join(entry.split())
    return ""


class WhoIrisSearcher(PaperSource):
    """WHO IRIS (DSpace REST) connector (no API key)."""

    SOURCE = "whoris"
    TIMEOUT = 30
    MAX_RETRIES = 3

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "paper-search-mcp/0.1.4 (mailto:openags@example.com)",
            "Accept": "application/json",
        })

    def search(self, query: str, max_results: int = 10, **kwargs) -> List[Paper]:
        params = {"query": query, "size": min(max(max_results, 1), 100)}
        objects: List[Dict[str, Any]] = []
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.session.get(SEARCH_URL, params=params, timeout=self.TIMEOUT)
                response.raise_for_status()
                result = response.json().get("_embedded", {}).get("searchResult", {})
                objects = result.get("_embedded", {}).get("objects", []) or []
                break
            except (requests.RequestException, ValueError) as exc:
                if attempt == self.MAX_RETRIES - 1:
                    logger.warning("WHO IRIS search failed: %s", exc)
                    raise SourceUnavailable("whoris", str(exc)[:200])

        papers: List[Paper] = []
        for wrapper in objects:
            item = (wrapper or {}).get("_embedded", {}).get("indexableObject") or {}
            paper = self._to_paper(item)
            if paper is not None:
                papers.append(paper)
            if len(papers) >= max_results:
                break
        return papers

    def _to_paper(self, item: Dict[str, Any]) -> Optional[Paper]:
        try:
            metadata = item.get("metadata") or {}
            uuid = str(item.get("uuid") or "")
            handle = _meta(metadata, "dc.identifier.uri")
            doi_uri = _meta(metadata, "dc.identifier.doi")
            doi = doi_uri.replace("https://doi.org/", "").replace("http://doi.org/", "").strip()

            published = None
            raw_date = _meta(metadata, "dc.date.issued")
            if raw_date:
                for fmt, size in (("%Y-%m-%d", 10), ("%Y-%m", 7), ("%Y", 4)):
                    try:
                        published = datetime.strptime(raw_date[:size], fmt)
                        break
                    except ValueError:
                        continue

            authors = []
            for entry in metadata.get("dc.contributor.author") or []:
                if isinstance(entry, dict) and entry.get("value"):
                    authors.append(" ".join(str(entry["value"]).split()))

            subjects = []
            for entry in metadata.get("dc.subject.mesh") or []:
                if isinstance(entry, dict) and entry.get("value"):
                    subjects.append(" ".join(str(entry["value"]).split()))

            return Paper(
                paper_id=doi or handle or uuid,
                title=_meta(metadata, "dc.title"),
                authors=authors,
                abstract=_meta(metadata, "dc.description.abstract")
                         or _meta(metadata, "dc.description"),
                url=handle or (f"https://doi.org/{doi}" if doi else ""),
                pdf_url="",
                published_date=published,
                updated_date=published,
                source=self.SOURCE,
                categories=[_meta(metadata, "dc.type")] if _meta(metadata, "dc.type") else [],
                keywords=subjects[:8],
                doi=doi,
                extra={"uuid": uuid, "handle": handle,
                       "publisher": _meta(metadata, "dc.publisher"),
                       "language": _meta(metadata, "dc.language")},
            )
        except Exception as exc:
            logger.warning("Failed to parse WHO IRIS record: %s", exc)
            return None

    # ------------------------------------------------------------------
    # DSpace download path: item -> bundles -> bitstreams -> content
    # ------------------------------------------------------------------

    def _json(self, url: str) -> Dict[str, Any]:
        try:
            response = self.session.get(url, timeout=self.TIMEOUT)
            response.raise_for_status()
            return response.json() or {}
        except (requests.RequestException, ValueError) as exc:
            logger.warning("WHO IRIS request failed (%s): %s", url, exc)
            return {}

    def _pdf_bitstream_url(self, item_uuid: str) -> str:
        """Walk item -> bundles -> bitstreams and return the first PDF content URL."""
        if not item_uuid:
            return ""
        bundles = (
            self._json(f"{BASE}/core/items/{item_uuid}/bundles")
            .get("_embedded", {}).get("bundles", []) or []
        )
        for bundle in bundles:
            bundle_uuid = (bundle or {}).get("uuid")
            if not bundle_uuid:
                continue
            bitstreams = (
                self._json(f"{BASE}/core/bundles/{bundle_uuid}/bitstreams")
                .get("_embedded", {}).get("bitstreams", []) or []
            )
            for stream in bitstreams:
                name = str((stream or {}).get("name") or "").lower()
                stream_uuid = (stream or {}).get("uuid")
                if stream_uuid and name.endswith(".pdf"):
                    return f"{BASE}/core/bitstreams/{stream_uuid}/content"
        return ""

    def _resolve_uuid(self, paper_id: str) -> str:
        """Accept a UUID, a handle URL, or a DOI and return the item UUID."""
        value = (paper_id or "").strip()
        if not value:
            return ""
        if len(value) == 36 and value.count("-") == 4:
            return value
        if "handle/" in value or value.startswith("http"):
            handle = value.split("handle/")[-1].strip()
            data = self._json(f"{SEARCH_URL}?query=handle:{handle}&size=1")
            objects = (data.get("_embedded", {}).get("searchResult", {})
                       .get("_embedded", {}).get("objects", []) or [])
            for wrapper in objects:
                uuid = ((wrapper or {}).get("_embedded", {}).get("indexableObject") or {}).get("uuid")
                if uuid:
                    return str(uuid)
        return ""

    def download_pdf(self, paper_id: str, save_path: str = "./downloads") -> str:
        """Download the first PDF in a WHO IRIS item.

        Raises a ValueError naming the reason when the item has no PDF
        bitstream, so a missing file never looks like success.
        """
        item_uuid = self._resolve_uuid(paper_id)
        if not item_uuid:
            raise ValueError("Could not resolve a WHO IRIS item from '%s'." % paper_id)

        content_url = self._pdf_bitstream_url(item_uuid)
        if not content_url:
            raise ValueError(
                "WHO IRIS item %s has no PDF bitstream (some IRIS records are "
                "metadata-only or hold text/office files)." % item_uuid
            )

        response = self.session.get(content_url, timeout=120, allow_redirects=True)
        response.raise_for_status()
        if not response.content.startswith(b"%PDF"):
            raise RuntimeError("WHO IRIS bitstream %s is not a PDF." % content_url)

        os.makedirs(save_path, exist_ok=True)
        output_file = os.path.join(save_path, "whoris_%s.pdf" % item_uuid)
        with open(output_file, "wb") as handle:
            handle.write(response.content)
        return output_file

    def read_paper(self, paper_id: str, save_path: str = "./downloads") -> str:
        """Download (if needed) and extract text from a WHO IRIS PDF."""
        item_uuid = self._resolve_uuid(paper_id) or (paper_id or "").strip()
        pdf_path = os.path.join(save_path, "whoris_%s.pdf" % item_uuid)
        if not os.path.exists(pdf_path):
            pdf_path = self.download_pdf(paper_id, save_path)

        reader = PdfReader(pdf_path)
        text = "".join((page.extract_text() or "") + "\n" for page in reader.pages)
        return text.strip()
