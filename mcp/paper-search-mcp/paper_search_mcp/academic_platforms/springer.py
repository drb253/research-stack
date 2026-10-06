"""Springer Nature connector for paper-search-mcp.

PATCHED-BY-paper-search-mcp-patches: source #28 (metadata search + OA full text).

Two official APIs, both free with one key per account:

  * Meta API        -- ``https://api.springernature.com/meta/v2/json``
                       every Springer Nature record: title, abstract, authors,
                       journal, DOI.
  * Open Access API -- ``https://api.springernature.com/openaccess/jats``
                       the full text of an open-access article **as JATS XML**,
                       the same format the bioRxiv/PMC fixes consume.

Free-plan limits, enforced here: **500 hits/day** and **100 hits/min**.  The daily
counter is persisted so restarting the server cannot reset the quota, and hitting
either limit raises :class:`SourceUnavailable` -- being out of quota is not the same
as the literature not existing.

Verified 2026-09-29 with a bogus key: every path answers HTTP 401 with
``{"status":"Fail","message":"Authentication failed. API key is invalid or missing"}``,
so an unusable key is reported precisely.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from ..config import get_env
from ..paper import Paper
from ..source_status import (
    SourceUnavailable,
    assert_usable_bytes,
    request_json,
)
from .base import PaperSource

logger = logging.getLogger(__name__)

META_URL = "https://api.springernature.com/meta/v2/json"
OPENACCESS_JATS_URL = "https://api.springernature.com/openaccess/jats"

#: Free plan: 100 hits/min -> at least 0.6s between request starts.
MIN_INTERVAL_SECONDS = 0.6
#: Free plan: 500 hits/day.
DAILY_QUOTA = 500
QUOTA_FILE = Path.home() / ".config" / "paper-search-mcp" / "springer_quota.json"

_TAG_RE = re.compile(r"<[^>]+>")

#: Process-wide pacing (the quota belongs to the account, not to one instance).
_LAST_CALL = [0.0]


def _clean_text(value: Any) -> str:
    """Strip markup/entities the Meta API sometimes leaves in fields."""
    if not value:
        return ""
    return " ".join(_TAG_RE.sub("", str(value)).replace("&amp;", "&").split())


def _jats_body(xml: str) -> str:
    """The article body from JATS XML, without front/back matter."""
    text = xml or ""
    match = re.search(r"<body[^>]*>(.*?)</body>", text, re.S | re.I)
    if match:
        text = match.group(1)
    text = re.sub(r"<back[^>]*>.*?</back>", " ", text, flags=re.S | re.I)
    return _clean_text(text)


class _Quota:
    """Persisted 500/day counter, so a restart cannot silently reset the budget.

    The Meta API and the Open Access API are separate products with **separate
    keys and separate 500/day allowances**, so each gets its own counter file.
    """

    def __init__(self, name: str = "meta", path: Optional[Path] = None) -> None:
        self.name = name
        self.path = path or (
            Path.home() / ".config" / "paper-search-mcp"
            / f"springer_quota_{name}.json"
        )

    def _load(self) -> Dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def remaining(self) -> int:
        data = self._load()
        today = datetime.now().strftime("%Y-%m-%d")
        used = int(data.get("used", 0)) if data.get("date") == today else 0
        return max(0, DAILY_QUOTA - used)

    def record(self) -> int:
        """Count one hit and return the remaining allowance."""
        data = self._load()
        today = datetime.now().strftime("%Y-%m-%d")
        used = int(data.get("used", 0)) if data.get("date") == today else 0
        used += 1
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"date": today, "used": used, "limit": DAILY_QUOTA}),
                encoding="utf-8",
            )
        except Exception:
            pass
        return max(0, DAILY_QUOTA - used)


class SpringerNatureSearcher(PaperSource):
    """Springer Nature Meta API + Open Access API (free key, 500 hits/day)."""

    SOURCE = "springer"
    TIMEOUT = 30

    def __init__(self) -> None:
        # The two APIs are separate products and are normally issued separate
        # keys; a single SPRINGER_NATURE_API_KEY still works as a fallback.
        shared = get_env("SPRINGER_NATURE_API_KEY", "").strip()
        self.meta_key = (
            get_env("SPRINGER_NATURE_META_API_KEY", "").strip() or shared
        )
        self.oa_key = (
            get_env("SPRINGER_NATURE_OPENACCESS_API_KEY", "").strip() or shared
        )
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "paper-search-mcp/0.1.4 (mailto:openags@example.com)",
            "Accept": "application/json",
        })
        self.quota_meta = _Quota("meta")
        self.quota_oa = _Quota("openaccess")

    def is_configured(self) -> bool:
        """True when a Meta API key is available (i.e. search is possible)."""
        return bool(self.meta_key)

    def is_oa_configured(self) -> bool:
        """True when an Open Access API key is available (i.e. full text)."""
        return bool(self.oa_key)

    def _quota(self, which: str) -> _Quota:
        return self.quota_meta if which == "meta" else self.quota_oa

    def _require_key(self, which: str = "meta") -> None:
        key = self.meta_key if which == "meta" else self.oa_key
        if not key:
            variable = (
                "SPRINGER_NATURE_META_API_KEY" if which == "meta"
                else "SPRINGER_NATURE_OPENACCESS_API_KEY"
            )
            raise SourceUnavailable(
                self.SOURCE,
                f"no {which} API key. Set {variable} in "
                "~/.config/paper-search-mcp/.env (free keys: dev.springernature.com)",
            )

    def _pace(self, which: str = "meta") -> None:
        """Enforce the per-API 100 hits/min throttle and 500 hits/day quota."""
        quota = self._quota(which)
        if quota.remaining() <= 0:
            raise SourceUnavailable(
                self.SOURCE,
                f"{which} API daily quota exhausted ({DAILY_QUOTA} hits/day on the "
                "free plan); it resets the next day",
            )
        wait = MIN_INTERVAL_SECONDS - (time.monotonic() - _LAST_CALL[0])
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL[0] = time.monotonic()
        quota.record()

    def _get(
        self,
        url: str,
        params: Dict[str, Any],
        which: str = "meta",
        accept_json: bool = True,
    ) -> Any:
        """GET with retries, mapping the API's 401 to a precise message."""
        self._require_key(which)
        self._pace(which)
        key = self.meta_key if which == "meta" else self.oa_key
        try:
            return request_json(
                self.session, url, self.SOURCE,
                params={**params, "api_key": key},
                timeout=self.TIMEOUT,
                accept_json=accept_json,
            )
        except SourceUnavailable as exc:
            if exc.http_status == 401:
                raise SourceUnavailable(
                    self.SOURCE,
                    f"{which} API key rejected by Springer Nature (check "
                    "SPRINGER_NATURE_META_API_KEY / "
                    "SPRINGER_NATURE_OPENACCESS_API_KEY)",
                    http_status=401,
                ) from exc
            raise


    # ------------------------------------------------------------------ search
    def search(self, query: str, max_results: int = 10, **kwargs) -> List[Paper]:
        """Search Springer Nature metadata via the Meta API.

        Args:
            query: Keyword query (e.g. 'CRISPR base editing').
            max_results: Maximum records to return (capped at 100 per request).
        """
        wanted = min(max(int(max_results or 10), 1), 100)
        try:
            payload = self._get(META_URL, {"q": query, "p": wanted})
        except SourceUnavailable as exc:
            # Springer answers a query with no matches with HTTP 404 plus
            # {"apiMessage": "No data was found for the given query."}.  That is
            # an EMPTY RESULT, not an outage: reporting it as unavailable is the
            # inverse of the error this install exists to prevent.  (Measured on
            # a nonsense query, 2026-09-29.)
            detail = f"{getattr(exc, 'message', '') or ''} {exc}".lower()
            if exc.http_status == 404 and (
                "no data" in detail or "not found" in detail or "no result" in detail
            ):
                logger.info(
                    "Springer: no matches for %r (reported as empty, not unavailable)",
                    query,
                )
                return []
            raise

        records: Any = []
        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, dict):
            records = payload.get("records") or []

        terms = [t for t in re.split(r"\s+", (query or "").lower()) if t]
        papers: List[Paper] = []
        for record in records if isinstance(records, list) else []:
            paper = self._to_paper(record)
            if paper is None:
                continue
            # The Meta API matches loosely, so require every term somewhere in the
            # record: a hit must be about the topic, not merely mention it.
            # Keywords are included because Springer records carry a curated
            # 'keyword' list that title+abstract sometimes omit.
            haystack = " ".join(
                [paper.title, paper.abstract] + list(paper.keywords or [])
            ).lower()
            if terms and not all(term in haystack for term in terms):
                continue
            papers.append(paper)
            if len(papers) >= wanted:
                break
        logger.info("Springer returned %s papers for: %s", len(papers), query)
        return papers

    def _to_paper(self, record: Any) -> Paper | None:
        """Map one Meta API record to a Paper, tolerating missing fields."""
        if not isinstance(record, dict):
            return None

        title = _clean_text(record.get("title"))
        if not title:
            return None

        doi = str(record.get("doi") or "").strip()
        # 'url' is a LIST of {format, platform, value} dicts, not a string
        # (verified against a live Meta API response on 2026-09-29).
        url = ""
        raw_url = record.get("url")
        if isinstance(raw_url, list):
            for candidate in raw_url:
                if isinstance(candidate, dict) and candidate.get("value"):
                    url = str(candidate["value"]).strip()
                    if str(candidate.get("format") or "").lower() == "html":
                        break
        elif isinstance(raw_url, str):
            url = raw_url.strip()
        if url.startswith("http://"):
            url = "https://" + url[len("http://"):]
        if not url and doi:
            url = f"https://doi.org/{doi}"

        # creators is a list of {"creator": "Name"}; some records use a plain list.
        authors: List[str] = []
        for creator in record.get("creators") or []:
            if isinstance(creator, dict):
                name = creator.get("creator") or creator.get("name") or ""
            else:
                name = str(creator)
            name = _clean_text(name)
            if name:
                authors.append(name)

        published = None
        for key in ("publicationDate", "onlineDate", "coverDate"):
            raw = str(record.get(key) or "").strip()
            for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
                try:
                    published = datetime.strptime(raw[:len(raw)], fmt)
                    break
                except ValueError:
                    continue
            if published:
                break

        journal = _clean_text(
            record.get("publicationName") or record.get("journal") or ""
        )
        abstract = _clean_text(record.get("abstract") or "")
        if journal and not abstract:
            abstract = f"Published in: {journal}"

        # 'keyword' arrives as a string or a list depending on the record.
        raw_keywords = record.get("keyword") or ""
        if isinstance(raw_keywords, list):
            keywords = [_clean_text(k) for k in raw_keywords if k]
        else:
            keywords = [
                k.strip() for k in re.split(r"[;,]", str(raw_keywords)) if k.strip()
            ]

        return Paper(
            paper_id=doi or url or title,
            title=title,
            authors=authors,
            abstract=abstract,
            doi=doi,
            published_date=published,
            pdf_url="",
            url=url,
            source=self.SOURCE,
            categories=[_clean_text(record.get("contentType") or "")] or [],
            keywords=keywords,
            citations=0,
            extra={
                "journal": journal,
                # 'openaccess' is a JSON bool in the live response, but tolerate
                # a string form too.
                "open_access": str(record.get("openaccess")).strip().lower()
                in ("true", "1", "yes"),
                "content_type": _clean_text(record.get("contentType") or ""),
            },
        )

    # --------------------------------------------------------------- full text
    def get_fulltext(self, doi: str) -> str:
        """The full text of a Springer Nature **open-access** article.

        Uses the Open Access API's ``jats`` output, which returns the complete
        article in JATS XML -- the same shape the bioRxiv and PMC fixes consume,
        so no PDF parsing and no bot wall are involved.  A non-OA article has no
        JATS here and raises, rather than returning an empty document.
        """
        doi = str(doi or "").strip()
        if not doi:
            raise ValueError("Invalid doi: doi is empty")

        response = self._get(
            OPENACCESS_JATS_URL,
            {"q": f"doi:{doi}", "p": 1},
            which="openaccess",
            accept_json=False,
        )
        xml = response.text
        assert_usable_bytes(
            self.SOURCE, response.content, 500, label="Springer OA JATS"
        )

        body = _jats_body(xml)
        if not body:
            raise SourceUnavailable(
                self.SOURCE,
                f"no open-access JATS for {doi} (the Open Access API only serves "
                "open-access articles; use the publisher page for subscribed content)",
            )
        return body

    def read_paper(self, paper_id: str, save_path: str = "./downloads") -> str:
        """Full text via the Open Access API (``save_path`` is unused)."""
        return self.get_fulltext(paper_id)

    def quota_status(self) -> Dict[str, Any]:
        """Remaining allowance per API, for preflight checks.

        The Meta API and the Open Access API are separate products with separate
        keys and separate 500/day allowances, so they are reported separately.
        """
        return {
            "meta": {
                "configured": self.is_configured(),
                "daily_limit": DAILY_QUOTA,
                "remaining_today": self.quota_meta.remaining(),
            },
            "openaccess": {
                "configured": self.is_oa_configured(),
                "daily_limit": DAILY_QUOTA,
                "remaining_today": self.quota_oa.remaining(),
            },
            "min_interval_seconds": MIN_INTERVAL_SECONDS,
        }

