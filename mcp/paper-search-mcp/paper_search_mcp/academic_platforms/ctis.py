"""EU CTIS connector for paper-search-mcp.

PATCHED-BY-paper-search-mcp-patches: source #27 (EU trial registry).

Why this source exists
----------------------
The EU Clinical Trials Information System (CTIS) is the mandatory registry for
clinical trials in the EU/EEA since January 2022, so it holds trials that exist in
no other index here -- including the sponsor, member states, phase and status a
systematic review's registry sweep needs.

Contract (discovered from the site's own browser requests; not publicly documented):
    POST https://euclinicaltrials.eu/ctis-public-api/search
    {"pagination": {"page": 1, "size": 20},          <- page is 1-BASED
     "sort": {"property": "decisionDate", "direction": "DESC"},
     "searchCriteria": { ...all criteria keys, null unless set... }}

The 1-based page was the trap: with ``page: 0`` the endpoint answers HTTP 200 with
``totalRecords: 0`` for *every* query, which reads as "no trials match".
Verified with page=1: ``CRISPR`` -> 15 trials, ``gene therapy`` -> 75,
``zzzqqq xylophone nonexistent`` -> 0.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from ..paper import Paper
from ..source_status import SourceUnavailable
from .base import PaperSource

logger = logging.getLogger(__name__)

SEARCH_URL = "https://euclinicaltrials.eu/ctis-public-api/search"
SITE_URL = "https://euclinicaltrials.eu/ctis-public-api/retrieve/"
POLITE_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

#: Every criteria key the SPA sends.  The API tolerates missing keys, but the site
#: sends the full null-filled shape, so we mirror it.
CRITERIA_KEYS = (
    "containAll", "containAny", "containNot", "title", "number", "status",
    "medicalCondition", "sponsor", "endPoint", "productName", "productRole",
    "populationType", "orphanDesignation", "msc", "ageGroupCode",
    "therapeuticAreaCode", "trialPhaseCode", "sponsorTypeCode", "gender",
    "protocolCode", "rareDisease", "pip", "haveOrphanDesignation",
    "hasStudyResults", "hasClinicalStudyReport", "isLowIntervention",
    "hasSeriousBreach", "hasUnexpectedEvent", "hasUrgentSafetyMeasure",
    "isTransitioned", "eudraCtCode", "trialRegion", "vulnerablePopulation",
    "mscStatus",
)


class CTISSearcher(PaperSource):
    """Search EU CTIS (free public API, no key)."""

    SOURCE = "ctis"
    TIMEOUT = 45

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": POLITE_UA,
            "Accept": "application/json",
        })

    def search(self, query: str, max_results: int = 10, **kwargs) -> List[Paper]:
        """Search EU CTIS registered trials.

        Args:
            query: Free text (trial title, product, condition, sponsor).
            max_results: Maximum trials to return (default: 10; API page cap 100).
            **kwargs: ``status``, ``medical_condition``, ``sponsor``,
                ``product_name``, ``trial_phase`` (e.g. ``"PHASE3"``).
        """
        wanted = min(max(int(max_results or 10), 1), 100)

        criteria: Dict[str, Any] = {key: None for key in CRITERIA_KEYS}
        criteria["containAll"] = str(query or "").strip() or None
        for kwarg, key in (("status", "status"),
                           ("medical_condition", "medicalCondition"),
                           ("sponsor", "sponsor"),
                           ("product_name", "productName"),
                           ("trial_phase", "trialPhaseCode")):
            value = kwargs.get(kwarg)
            if value:
                criteria[key] = value

        body = self._post({
            # page is 1-based; page=0 silently yields zero records.
            "pagination": {"page": 1, "size": wanted},
            "sort": {"property": "decisionDate", "direction": "DESC"},
            "searchCriteria": criteria,
        })

        records = (body or {}).get("data") or []
        total = ((body or {}).get("pagination") or {}).get("totalRecords", 0)

        papers: List[Paper] = []
        for record in records:
            paper = self._to_paper(record)
            if paper is not None:
                papers.append(paper)
            if len(papers) >= wanted:
                break

        logger.info("CTIS matched %s trials, returning %s", total, len(papers))
        return papers

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST the search payload, distinguishing failure from an empty result."""
        try:
            response = self.session.post(
                SEARCH_URL, json=payload, timeout=self.TIMEOUT)
        except requests.RequestException as exc:
            raise SourceUnavailable("ctis", f"search failed: {exc}"[:200])

        if response.status_code != 200:
            raise SourceUnavailable(
                "ctis", f"search returned {response.status_code}", response.status_code)

        try:
            body = response.json()
        except ValueError as exc:
            raise SourceUnavailable("ctis", f"unparsable JSON: {exc}"[:200])

        # A valid response always carries the pagination envelope; without it we
        # cannot tell "no matches" from a silently different response shape.
        if not isinstance(body, dict) or "pagination" not in body:
            raise SourceUnavailable("ctis", "response missing the pagination envelope")
        return body

    def _to_paper(self, record: Dict[str, Any]) -> Optional[Paper]:
        if not isinstance(record, dict):
            return None
        ct_number = str(record.get("ctNumber") or "").strip()
        title = " ".join(str(record.get("ctTitle") or "").split())
        if not ct_number or not title:
            return None

        conditions = record.get("conditions") or []
        if isinstance(conditions, str):
            conditions = [conditions]
        status = str(record.get("ctStatus") or "")

        published: Optional[datetime] = None
        for key in ("decisionDate", "decisionDateOverall", "lastUpdated"):
            value = record.get(key)
            if not value:
                continue
            try:
                published = datetime.fromisoformat(str(value)[:10])
                break
            except ValueError:
                continue

        return Paper(
            paper_id=ct_number,
            title=title,
            authors=[],
            abstract=" ".join(part for part in (
                f"EU CTIS trial {ct_number}.",
                f"Status: {status}." if status else "",
                f"Conditions: {', '.join(str(c) for c in conditions[:4])}."
                if conditions else "",
            ) if part),
            doi="",
            published_date=published,
            pdf_url="",
            url=f"{SITE_URL}{ct_number}",
            source=self.SOURCE,
            categories=[status] if status else [],
            keywords=[str(c) for c in conditions[:6]],
            citations=0,
            extra={
                "ct_number": ct_number,
                "status": status,
                "conditions": conditions,
                "sponsor": record.get("sponsor") or "",
                "products": record.get("productName") or [],
                "trial_region": record.get("trialRegion") or [],
            },
        )
