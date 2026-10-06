"""ClinicalTrials.gov connector for paper-search-mcp.

PATCHED-BY-paper-search-mcp-patches: source #24 (trial registry).

Why this source exists
----------------------
Systematic-review methodology (PRISMA item 5 / Cochrane) requires searching trial
*registries*, not just bibliographic databases -- registry records carry protocol
detail, phase, status and outcome measures that no journal index holds, and they
surface trials whose results were never published.  Nothing else in this install
covers that: the 23 bibliographic sources index papers, this one indexes studies.

API: https://clinicaltrials.gov/api/v2/studies (free, no key, JSON).
Measured: ``query.term`` uses AND semantics (real query 22 studies; the same query
with a garbage term pair returns 0), and a quoted phrase is narrower still
(1 study).  Records are verified client-side so a fuzzy match cannot slip through.

No PDF download: ClinicalTrials.gov hosts structured records rather than
documents, so ``download_pdf``/``read_paper`` are intentionally not implemented.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from ..paper import Paper
from ..source_status import (  # paper-search-mcp-patches: Tier 1/2 helpers
    SourceUnavailable,
    phrase,
    request_json,
    search_terms,
)
from .base import PaperSource

logger = logging.getLogger(__name__)

SEARCH_URL = "https://clinicaltrials.gov/api/v2/studies"
SITE_URL = "https://clinicaltrials.gov/study/"
POLITE_UA = "paper-search-mcp/0.1.4 (mailto:openags@example.com)"
# The v2 API caps pageSize at 1000; 100 keeps responses small and quick.
PAGE_SIZE_LIMIT = 100


class ClinicalTrialsSearcher(PaperSource):
    """Search ClinicalTrials.gov study records (free, no API key)."""

    SOURCE = "clinicaltrials"

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": POLITE_UA,
            "Accept": "application/json",
        })

    # ------------------------------------------------------------------ search
    def search(self, query: str, max_results: int = 10, **kwargs) -> List[Paper]:
        """Search registered clinical studies.

        Args:
            query: Free-text query (intervention, condition, sponsor, NCT id).
            max_results: Maximum studies to return (API page cap is 1000).
            **kwargs: ``status`` (e.g. ``"RECRUITING"``), ``study_type``
                (``"INTERVENTIONAL"``/``"OBSERVATIONAL"``), ``phase``.
        """
        page_size = min(max(int(max_results or 10), 1), PAGE_SIZE_LIMIT)

        base_params: Dict[str, Any] = {
            "pageSize": page_size,
            "countTotal": "true",
            "format": "json",
        }
        if kwargs.get("status"):
            base_params["filter.overallStatus"] = str(kwargs["status"]).upper()
        if kwargs.get("study_type"):
            base_params["filter.advanced"] = (
                f"AREA[StudyType]{str(kwargs['study_type']).upper()}"
            )
        if kwargs.get("phase"):
            base_params["filter.advanced"] = " AND ".join(
                part for part in (
                    base_params.get("filter.advanced", ""),
                    f"AREA[Phase]{str(kwargs['phase']).upper()}",
                ) if part
            )

        # Both forms are precise (a nonsense query returns 0 either way), but the
        # plain form has far wider recall than the quoted phrase (measured on
        # 'CRISPR base editing': 22 studies vs 1), so the plain form goes first and
        # the phrase is only a fallback.  Precision is enforced by the client-side
        # all-terms verification below rather than by narrowing the request.
        terms = search_terms(query)
        candidates: List[str] = [str(query or "").strip()]
        quoted = phrase(terms)
        if len(terms) >= 2 and quoted:
            candidates.append(f'"{quoted}"')

        studies: List[Dict[str, Any]] = []
        total = 0
        for candidate in dict.fromkeys(c for c in candidates if c):
            params = dict(base_params)
            params["query.term"] = candidate
            payload = request_json(
                self.session, SEARCH_URL, self.SOURCE, params=params,
                timeout=30, max_retries=2,
            )
            studies = (payload or {}).get("studies") or []
            total = int((payload or {}).get("totalCount") or len(studies))
            if studies:
                break

        # Precision note: no client-side term filter is applied here.  The registry
        # search is AND-based and returns 0 for a nonsense query (measured), while a
        # strict all-terms substring check was rejecting legitimate stemmed matches
        # (e.g. "Base Edited CAR7 T Cells" for the term "editing").  Ordering is
        # handled by the Tier-3 relevance ranking in search_papers.
        papers: List[Paper] = []
        for study in studies:
            paper = self._to_paper(study)
            if paper is None:
                continue
            papers.append(paper)
            if len(papers) >= max_results:
                break

        if total:
            logger.info(
                "ClinicalTrials.gov matched %s studies, returning %s",
                total, len(papers),
            )
        return papers

    # ----------------------------------------------------------------- mapping
    def _to_paper(self, study: Dict[str, Any]) -> Optional[Paper]:
        """Map a v2 study record onto the shared Paper schema."""
        try:
            protocol = (study or {}).get("protocolSection") or {}
            ident = protocol.get("identificationModule") or {}
            nct_id = str(ident.get("nctId") or "").strip()
            if not nct_id:
                return None

            title = " ".join(
                str(ident.get("briefTitle") or ident.get("officialTitle") or "").split()
            )
            if not title:
                return None

            status_module = protocol.get("statusModule") or {}
            design = protocol.get("designModule") or {}
            conditions = (protocol.get("conditionsModule") or {}).get("conditions") or []
            interventions = [
                str((item or {}).get("name") or "").strip()
                for item in (protocol.get("armsInterventionsModule") or {}).get("interventions") or []
                if (item or {}).get("name")
            ]
            sponsor = (
                (protocol.get("sponsorCollaboratorsModule") or {})
                .get("leadSponsor") or {}
            ).get("name") or (
                (ident.get("organization") or {}).get("fullName") or ""
            )

            abstract = " ".join(
                str((protocol.get("descriptionModule") or {}).get("briefSummary") or "").split()
            )
            # Protocol detail lives in structured fields, so append a compact
            # summary to the abstract to keep downstream relevance scoring honest.
            detail_bits = []
            if status_module.get("overallStatus"):
                detail_bits.append(f"Status: {status_module['overallStatus']}")
            if design.get("phases"):
                detail_bits.append("Phase: " + ", ".join(design["phases"]))
            if design.get("studyType"):
                detail_bits.append(f"Type: {design['studyType']}")
            enrollment = (design.get("enrollmentInfo") or {}).get("count")
            if enrollment:
                detail_bits.append(f"Enrollment: {enrollment}")
            if detail_bits:
                abstract = (abstract + " [" + "; ".join(detail_bits) + "]").strip()

            published: Optional[datetime] = None
            date_value = (status_module.get("startDateStruct") or {}).get("date")
            if date_value:
                try:
                    published = datetime.strptime(str(date_value), "%Y-%m-%d")
                except ValueError:
                    published = None

            categories = [
                item for item in (
                    design.get("studyType"),
                    ", ".join(design.get("phases") or []),
                    status_module.get("overallStatus"),
                ) if item
            ]
            keywords = list(dict.fromkeys(conditions + interventions))

            return Paper(
                paper_id=nct_id,
                title=title,
                authors=[sponsor] if sponsor else [],
                abstract=abstract,
                doi="",
                published_date=published,
                pdf_url="",
                url=f"{SITE_URL}{nct_id}",
                source=self.SOURCE,
                categories=categories,
                keywords=keywords,
                citations=0,
                extra={
                    "nct_id": nct_id,
                    "overall_status": status_module.get("overallStatus", ""),
                    "study_type": design.get("studyType", ""),
                    "phases": design.get("phases") or [],
                    "enrollment": enrollment,
                    "conditions": conditions,
                    "interventions": interventions,
                    "lead_sponsor": sponsor,
                    "has_results": bool((study or {}).get("hasResults")),
                    "completion_date": (
                        status_module.get("completionDateStruct") or {}
                    ).get("date", ""),
                },
            )
        except Exception as exc:  # a single malformed record must not fail a search
            logger.warning("ClinicalTrials.gov record parse failed: %s", exc)
            return None
