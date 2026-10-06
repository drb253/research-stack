"""PLOS connector for paper-search-mcp.

PATCHED-BY-paper-search-mcp-patches: PLOS Search API connector.

PLOS journals are fully open access, so metadata and PDFs are free with no API
key.  Tier 2: the query is issued as a phrase-first ladder
(everything:"..." -> everything:(a AND b) -> everything:<q>), because the
quoted-phrase form alone returned 0 hits whenever the phrase was not literal.
Tier 1: an unreachable PLOS raises SourceUnavailable instead of returning [].
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
from ..source_status import (  # paper-search-mcp-patches: Tier 1/2 helpers
    and_query,
    phrase,
    search_ladder,
    search_terms,
)
from .base import PaperSource

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.plos.org/search"

# PLOS DOI journal codes -> journals.plos.org URL slug (needed for the PDF link)
JOURNAL_SLUGS = {
    "pbio": "plosbiology",
    "pone": "plosone",
    "pcbi": "ploscompbiol",
    "pgen": "plosgenetics",
    "pmed": "plosmedicine",
    "ppat": "plospathogens",
    "pntd": "plosntds",
    "pdig": "plosdigitalhealth",
    "pwat": "ploswater",
    "pclm": "plosclimate",
    "pgph": "plosglobalpublichealth",
}
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", str(value))).strip()


def plos_pdf_url(doi: str) -> str:
    """Printable-PDF URL for a PLOS DOI ("" when the journal code is unknown)."""
    match = re.match(r"10\.1371/journal\.([a-z]+)\.", doi or "")
    slug = JOURNAL_SLUGS.get(match.group(1)) if match else None
    if not slug:
        return ""
    return f"https://journals.plos.org/{slug}/article/file?id={doi}&type=printable"


class PLOSSearcher(PaperSource):
    """PLOS Search API connector (open access, no API key)."""

    SOURCE = "plos"
    TIMEOUT = 30
    MAX_RETRIES = 3

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "paper-search-mcp/0.1.4 (mailto:openags@example.com)",
            "Accept": "application/json",
        })

    def search(self, query: str, max_results: int = 10, **kwargs) -> List[Paper]:
        # Tier 1/2 (paper-search-mcp-patches): phrase-first ladder with an AND
        # fallback. Measured: the quoted phrase is precise but returned 0 for
        # three of the user's queries (the phrase was not literal), while the
        # pure AND mode matched 5,923 loosely -- so escalate phrase -> AND -> raw.
        terms = search_terms(query)
        ladder: List[tuple] = []
        if len(terms) >= 2:
            ladder.append(("phrase", f'everything:"{phrase(terms)}"'))
            ladder.append(("AND", f"everything:({and_query(terms)})"))
        ladder.append(("raw", f"everything:{query}"))

        fields = ("id,doi,title_display,author_display,publication_date,"
                  "abstract,journal,article_type,subject")
        attempts: List[tuple] = []
        for label, query_string in ladder:
            attempts.append((label, {
                "q": query_string,
                "wt": "json",
                "rows": min(max(max_results, 1), 100),
                "fl": fields,
            }))

        docs, _label = search_ladder(
            "plos",
            self.session,
            SEARCH_URL,
            attempts,
            lambda payload: (payload.get("response") or {}).get("docs") or [],
            timeout=self.TIMEOUT,
        )
        logger.info("PLOS query mode '%s' for: %s", _label, query)

        papers: List[Paper] = []
        for doc in docs:
            paper = self._to_paper(doc)
            if paper is not None:
                papers.append(paper)
        return papers[:max_results]

    def _to_paper(self, doc: Dict[str, Any]) -> Optional[Paper]:
        try:
            doi = _clean(doc.get("doi")) or _clean(doc.get("id"))
            published = None
            raw = _clean(doc.get("publication_date"))
            if raw:
                try:
                    published = datetime.strptime(raw[:10], "%Y-%m-%d")
                except ValueError:
                    published = None

            authors = [_clean(a) for a in (doc.get("author_display") or []) if _clean(a)]
            subjects = [_clean(s) for s in (doc.get("subject") or []) if _clean(s)]
            journal = _clean(doc.get("journal"))
            article_type = _clean(doc.get("article_type"))

            return Paper(
                paper_id=doi,
                title=_clean(doc.get("title_display")),
                authors=authors,
                abstract=_clean(doc.get("abstract")),
                url=f"https://doi.org/{doi}" if doi else "",
                pdf_url=plos_pdf_url(doi),
                published_date=published,
                updated_date=published,
                source=self.SOURCE,
                categories=[c for c in (journal, article_type) if c],
                keywords=[],
                doi=doi,
                extra={"journal": journal, "article_type": article_type,
                       "subjects": subjects[:8]},
            )
        except Exception as exc:
            logger.warning("Failed to parse PLOS record: %s", exc)
            return None

    def download_pdf(self, paper_id: str, save_path: str = "./downloads") -> str:
        """Download the open-access PDF for a PLOS DOI."""
        doi = (paper_id or "").strip()
        pdf_url = plos_pdf_url(doi)
        if not pdf_url:
            raise ValueError(
                "No PLOS PDF URL could be derived from '%s'. Pass a PLOS DOI of the "
                "form 10.1371/journal.<journal>.<id>." % paper_id
            )

        response = self.session.get(pdf_url, timeout=90)
        response.raise_for_status()
        if not response.content.startswith(b"%PDF"):
            raise RuntimeError("PLOS returned a non-PDF response for %s" % doi)

        os.makedirs(save_path, exist_ok=True)
        output_file = os.path.join(save_path, "%s.pdf" % doi.replace("/", "_"))
        with open(output_file, "wb") as handle:
            handle.write(response.content)
        return output_file

    def read_paper(self, paper_id: str, save_path: str = "./downloads") -> str:
        """Download (if needed) and extract text from a PLOS PDF."""
        pdf_path = os.path.join(save_path, "%s.pdf" % (paper_id or "").replace("/", "_"))
        if not os.path.exists(pdf_path):
            pdf_path = self.download_pdf(paper_id, save_path)

        reader = PdfReader(pdf_path)
        text = "".join((page.extract_text() or "") + "\n" for page in reader.pages)
        return text.strip()
