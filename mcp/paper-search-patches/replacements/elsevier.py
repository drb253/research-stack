"""Elsevier (Scopus / ScienceDirect) connector for paper-search-mcp.

PATCHED-BY-paper-search-mcp-patches: source #29 (metadata search).

What a **free** Elsevier API key does and does not buy, stated plainly:

  * Covered: the Scopus and ScienceDirect **search** APIs, plus article abstract
    retrieval.  These return metadata -- title, abstract, authors, journal, DOI,
    citation count.
  * NOT covered: the full text of a subscribed article.  That needs an
    institutional entitlement token (``insttoken``) from a subscribing library,
    which a free key does not carry.  :meth:`ElsevierSearcher.get_fulltext`
    therefore reports "entitlement required" instead of pretending to work, and
    :meth:`check_access` lets a caller verify all of this up front.

Verified against live keys on 2026-09-29:

  * Scopus search **works with a free key** (``TITLE-ABS-KEY(crispr AND editing)``
    returned 200 with 39,979 total results).
  * Abstract retrieval works with a free key (``content/abstract/doi/...``
    returned 200).
  * ScienceDirect search/retrieval answers **HTTP 401 AUTHORIZATION_ERROR**
    ("the requestor is not authorized to access the requested view or fields"),
    i.e. a valid key without institutional entitlement.  Those endpoints are
    therefore never used for search.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from ..config import get_env
from ..paper import Paper
from ..source_status import SourceUnavailable, request_json
from .base import PaperSource

logger = logging.getLogger(__name__)

SCOPUS_SEARCH_URL = "https://api.elsevier.com/content/search/scopus"
SCIENCEDIRECT_SEARCH_URL = "https://api.elsevier.com/content/search/sciencedirect"
ABSTRACT_URL = "https://api.elsevier.com/content/abstract/doi"
ARTICLE_URL = "https://api.elsevier.com/content/article/doi"

#: Conservative pacing; Elsevier publishes per-key rate limits, so stay well under.
MIN_INTERVAL_SECONDS = 0.5

_LAST_CALL = [0.0]


class ElsevierSearcher(PaperSource):
    """Scopus / ScienceDirect metadata search (free key; entitlement optional)."""

    SOURCE = "elsevier"
    TIMEOUT = 30

    def __init__(self) -> None:
        self.api_key = (
            get_env("ELSEVIER_API_KEY", "") or get_env("ELSEVIER_APIKEY", "")
        ).strip()
        self.insttoken = get_env("ELSEVIER_INSTTOKEN", "").strip()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "paper-search-mcp/0.1.4 (mailto:openags@example.com)",
            "Accept": "application/json",
        })

    def is_configured(self) -> bool:
        """True only when a non-empty Elsevier API key is available."""
        return bool(self.api_key)

    def _headers(self, accept_json: bool = True) -> Dict[str, str]:
        headers = {
            "X-ELS-APIKey": self.api_key,
            "Accept": "application/json" if accept_json else "text/xml",
        }
        if self.insttoken:
            headers["X-ELS-Insttoken"] = self.insttoken
        return headers

    def _get(self, url: str, params: Dict[str, Any], accept_json: bool = True) -> Any:
        """GET with retries and precise 401/403 reporting."""
        if not self.api_key:
            raise SourceUnavailable(
                self.SOURCE,
                "no API key. Set ELSEVIER_API_KEY in ~/.config/paper-search-mcp/.env "
                "(free key: dev.elsevier.com)",
            )

        wait = MIN_INTERVAL_SECONDS - (time.monotonic() - _LAST_CALL[0])
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL[0] = time.monotonic()

        try:
            payload = request_json(
                self.session, url, self.SOURCE,
                params=params,
                headers=self._headers(accept_json),
                timeout=self.TIMEOUT,
                accept_json=accept_json,
            )
        except SourceUnavailable as exc:
            if exc.http_status in (401, 403):
                # Verified 2026-09-29: Scopus search/abstract answer
                # 'APIKEY_INVALID' when the key itself is bad, whereas the
                # ScienceDirect endpoints answer 401 'AUTHORIZATION_ERROR' when
                # the key is valid but the account has no entitlement.  Mapping
                # by endpoint keeps those two causes distinguishable.
                entitled_scope = url.startswith(
                    (SCIENCEDIRECT_SEARCH_URL, ARTICLE_URL)
                )
                if entitled_scope:
                    raise SourceUnavailable(
                        self.SOURCE,
                        "this ScienceDirect view needs an institutional "
                        "entitlement token (set ELSEVIER_INSTTOKEN); a free key "
                        "is not entitled",
                        http_status=exc.http_status,
                    ) from exc
                raise SourceUnavailable(
                    self.SOURCE,
                    "API key rejected by Elsevier (set ELSEVIER_API_KEY)",
                    http_status=exc.http_status,
                ) from exc
            raise

        # Scopus can also answer 200 with a service-error envelope.
        if isinstance(payload, dict) and "service-error" in payload:
            detail = payload.get("service-error") or {}
            status = (detail.get("status") or {}) if isinstance(detail, dict) else {}
            raise SourceUnavailable(
                self.SOURCE,
                "Elsevier service error: %s" % (
                    status.get("statusText") or status.get("statusCode") or "unknown"
                ),
                http_status=200,
            )
        return payload


    # ------------------------------------------------------------------ search
    def search(self, query: str, max_results: int = 10, **kwargs) -> List[Paper]:
        """Search Scopus, most precise query first.

        Args:
            query: Keyword query (e.g. 'CRISPR base editing').
            max_results: Maximum records to return (Scopus pages of max 25).
        """
        wanted = min(max(int(max_results or 10), 1), 25)
        terms = [t for t in re.split(r"\s+", (query or "").strip()) if t]
        if not terms:
            return []

        and_expr = " AND ".join(terms)
        ladder = []
        if len(terms) >= 2:
            ladder.append(("title-abs-key AND", "TITLE-ABS-KEY(%s)" % and_expr))
            ladder.append(("title-abs-key phrase", 'TITLE-ABS-KEY("%s")' % " ".join(terms)))
        ladder.append(("all-fields", "ALL(%s)" % and_expr))

        errors: List[SourceUnavailable] = []
        for label, expression in ladder:
            try:
                payload = self._get(
                    SCOPUS_SEARCH_URL,
                    {"query": expression, "count": wanted},
                )
            except SourceUnavailable as exc:
                errors.append(exc)
                logger.warning("Scopus rung '%s' unavailable: %s", label, exc)
                continue

            papers = self._parse_scopus(payload, wanted)
            if papers:
                logger.info("Scopus rung '%s' returned %s papers for: %s",
                            label, len(papers), query)
                return papers

        # Every rung answered but produced nothing: a real empty result.  If any
        # rung *failed*, the failure wins -- an error is not "no such literature".
        if errors:
            raise errors[0]
        return []

    def _parse_scopus(self, payload: Any, wanted: int) -> List[Paper]:
        results = (payload or {}).get("search-results") or {}
        entries = results.get("entry") or []
        if isinstance(entries, dict):
            entries = [entries]

        papers: List[Paper] = []
        for entry in entries:
            paper = self._to_paper(entry)
            if paper is None:
                continue
            papers.append(paper)
            if len(papers) >= wanted:
                break
        return papers

    def _to_paper(self, entry: Any) -> Optional[Paper]:
        """Map one Scopus search entry to a Paper."""
        if not isinstance(entry, dict):
            return None

        title = " ".join(str(entry.get("dc:title") or "").split())
        if not title:
            return None

        doi = str(entry.get("prism:doi") or "").strip()
        url = str(entry.get("prism:url") or "").strip()
        if not url and doi:
            url = f"https://doi.org/{doi}"

        creator = entry.get("dc:creator")
        authors = [" ".join(str(creator).split())] if creator else []

        published = None
        raw_date = str(entry.get("prism:coverDate") or "").strip()
        for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
            try:
                published = datetime.strptime(raw_date[:len(raw_date)], fmt)
                break
            except ValueError:
                continue

        try:
            citations = int(str(entry.get("citedby-count") or "0"))
        except ValueError:
            citations = 0

        journal = " ".join(str(entry.get("prism:publicationName") or "").split())
        abstract = " ".join(str(entry.get("dc:description") or "").split())
        if journal and not abstract:
            abstract = f"Published in: {journal}"

        return Paper(
            paper_id=doi or str(entry.get("dc:identifier") or "") or url or title,
            title=title,
            authors=authors,
            abstract=abstract,
            doi=doi,
            published_date=published,
            pdf_url="",
            url=url,
            source=self.SOURCE,
            categories=[journal] if journal else [],
            keywords=[],
            citations=citations,
            extra={
                "journal": journal,
                "scopus_id": str(entry.get("dc:identifier") or ""),
                "content_type": str(entry.get("subtypeDescription") or ""),
                "open_access": str(
                    entry.get("openaccessFlag") or entry.get("openaccess") or ""
                ).strip().lower() in ("true", "1", "yes"),
                "entitlement": bool(self.insttoken),
            },
        )

    # ------------------------------------------------------ abstracts / full text
    def get_abstract(self, doi: str) -> Dict[str, Any]:
        """Scopus abstract record for one DOI (metadata only)."""
        doi = str(doi or "").strip()
        if not doi:
            raise ValueError("Invalid doi: doi is empty")

        payload = self._get(
            f"{ABSTRACT_URL}/{doi}", {"httpAccept": "application/json"}
        )
        record = (payload or {}).get("abstracts-retrieval-response") or {}
        return record if isinstance(record, dict) else {}

    def get_fulltext(self, doi: str) -> str:
        """ScienceDirect full text -- requires institutional entitlement.

        A **free** API key does not carry entitlement, so this reports the
        requirement instead of returning an empty document.  Set
        ``ELSEVIER_INSTTOKEN`` if your library provides one.
        """
        doi = str(doi or "").strip()
        if not doi:
            raise ValueError("Invalid doi: doi is empty")

        if not self.insttoken:
            raise SourceUnavailable(
                self.SOURCE,
                "full text requires an institutional entitlement token: set "
                "ELSEVIER_INSTTOKEN. A free API key covers search and abstracts only",
            )

        response = self._get(
            f"{ARTICLE_URL}/{doi}", {"httpAccept": "text/xml"}, accept_json=False
        )
        xml = response.text
        assert_usable_bytes(
            self.SOURCE, response.content, 500, label="Elsevier article XML"
        )
        # Elsevier's full-text XML is not JATS, so take the body generically.
        match = re.search(r"<body[^>]*>(.*?)</body>", xml, re.S | re.I)
        text = match.group(1) if match else xml
        text = " ".join(re.sub(r"<[^>]+>", " ", text).split())
        assert_usable_bytes(
            self.SOURCE, text.encode("utf-8"), 500, label="Elsevier body text"
        )
        return text

    def read_paper(self, paper_id: str, save_path: str = "./downloads") -> str:
        """Full text for a DOI; see :meth:`get_fulltext` for the entitlement rule."""
        return self.get_fulltext(paper_id)

    def check_access(self) -> Dict[str, Any]:
        """Preflight: what does this key actually permit?

        Probes Scopus with a one-record query and reports whether an entitlement
        token is present, so the boundary can be explained rather than guessed at
        when results look thin.
        """
        status: Dict[str, Any] = {
            "configured": self.is_configured(),
            "entitlement_token": bool(self.insttoken),
            "scopus_search": False,
            "full_text": bool(self.insttoken),
            "message": "",
        }
        if not self.is_configured():
            status["message"] = "no API key configured (set ELSEVIER_API_KEY)"
            return status

        try:
            payload = self._get(SCOPUS_SEARCH_URL, {"query": "ALL(crispr)", "count": 1})
            total = ((payload or {}).get("search-results") or {}).get(
                "opensearch:totalResults"
            )
            status["scopus_search"] = True
            status["message"] = "Scopus search OK (totalResults=%s)%s" % (
                total,
                ""
                if self.insttoken
                else "; no entitlement token, so full text is unavailable",
            )
        except SourceUnavailable as exc:
            status["message"] = str(exc)[:220]
        return status
