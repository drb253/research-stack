"""Free retraction check for a DOI (Tier 6).

PATCHED-BY-paper-search-mcp-patches: retraction flagging via OpenAlex + Crossref.

Both endpoints are free and key-free.  OpenAlex indexes ``is_retracted`` on its
works (and ``type: "retraction"`` for notices); Crossref exposes ``update-to``
and ``relation.is-retracted-by`` edges carrying ``type: retraction``.  Each
source is queried independently and any unavailable source is reported as such
rather than being read as "not retracted" -- that distinction matters most
exactly here.

Verified against the retracted Lancet COVID-19 paper
(10.1016/S0140-6736(20)31324-6).
"""
from __future__ import annotations

import logging
import urllib.parse
from typing import Any, Dict, List, Optional

from .source_status import SourceUnavailable, request_json

logger = logging.getLogger(__name__)

OPENALEX_WORK_URL = "https://api.openalex.org/works/doi:"
CROSSREF_WORK_URL = "https://api.crossref.org/works/"
CROSSREF_SEARCH_URL = "https://api.crossref.org/works"
POLITE_UA = "paper-search-mcp/0.1.4 (mailto:openags@example.com)"


def normalize_doi(doi: str) -> str:
    """Strip any resolver prefix and surrounding whitespace from a DOI."""
    text = str(doi or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/",
                   "http://dx.doi.org/", "doi:", "DOI:"):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):]
    return text.strip().strip("/")


def _session():
    import requests

    session = requests.Session()
    session.headers.update({"User-Agent": POLITE_UA, "Accept": "application/json"})
    return session


def _openalex_params() -> Dict[str, str]:
    import os

    params: Dict[str, str] = {}
    api_key = str(os.environ.get("OPENALEX_API_KEY", "") or "").strip()
    if api_key:
        params["api_key"] = api_key
    mailto = str(os.environ.get("OPENALEX_EMAIL", "") or "").strip()
    if mailto:
        params["mailto"] = mailto
    return params


def check_retraction(doi: str, title: str = "", timeout: float = 25) -> Dict[str, Any]:
    """Report whether ``doi`` has been retracted, and on whose evidence.

    ``is_retracted`` stays False unless a source positively says otherwise, and
    every failed lookup is recorded in ``sources_unavailable`` so a transport
    failure can never be read as a clean record.
    """
    normalized = normalize_doi(doi)
    if not normalized:
        return {
            "doi": "",
            "is_retracted": False,
            "is_retraction_notice": False,
            "error": "a DOI is required",
            "evidence": [],
            "notices": [],
            "sources_checked": [],
            "sources_unavailable": {},
        }

    session = _session()
    result: Dict[str, Any] = {
        "doi": normalized,
        "is_retracted": False,
        "is_retraction_notice": False,
        "evidence": [],
        "notices": [],
        "sources_checked": [],
        "sources_unavailable": {},
    }

    # ------------------------------------------------------------------ OpenAlex
    try:
        payload = request_json(
            session,
            OPENALEX_WORK_URL + urllib.parse.quote(normalized, safe=""),
            "openalex",
            params=_openalex_params(),
            timeout=timeout,
        )
        work = payload if isinstance(payload, dict) else {}
        result["sources_checked"].append("openalex")

        if work.get("is_retracted"):
            result["is_retracted"] = True
            result["evidence"].append({
                "source": "openalex",
                "field": "is_retracted",
                "work": work.get("id", ""),
                "publication_year": work.get("publication_year"),
            })
        if str(work.get("type") or "").lower() == "retraction":
            result["is_retraction_notice"] = True
            result["evidence"].append({
                "source": "openalex", "field": "type", "value": "retraction",
                "work": work.get("id", ""),
            })
    except SourceUnavailable as exc:
        result["sources_unavailable"]["openalex"] = exc.to_dict()
    except Exception as exc:  # defensive: never break the caller's workflow
        logger.warning("OpenAlex retraction lookup failed: %s", exc)
        result["sources_unavailable"]["openalex"] = {"detail": str(exc)[:200]}

    # ------------------------------------------------------------------ Crossref
    try:
        payload = request_json(
            session,
            CROSSREF_WORK_URL + urllib.parse.quote(normalized, safe=""),
            "crossref",
            timeout=timeout,
        )
        message = (payload or {}).get("message") or {}
        result["sources_checked"].append("crossref")

        if str(message.get("type") or "").lower() == "retraction":
            result["is_retraction_notice"] = True
            result["evidence"].append({"source": "crossref", "field": "type",
                                       "value": "retraction"})

        for update in message.get("update-to") or []:
            if str((update or {}).get("type") or "").lower() == "retraction":
                result["is_retracted"] = True
                result["evidence"].append({
                    "source": "crossref",
                    "field": "update-to",
                    "doi": update.get("DOI", ""),
                    "updated": update.get("updated"),
                })

        for related in ((message.get("relation") or {}).get("is-retracted-by") or []):
            result["is_retracted"] = True
            result["evidence"].append({
                "source": "crossref",
                "field": "relation.is-retracted-by",
                "id": related.get("id", ""),
            })
    except SourceUnavailable as exc:
        result["sources_unavailable"]["crossref"] = exc.to_dict()
    except Exception as exc:
        logger.warning("Crossref retraction lookup failed: %s", exc)
        result["sources_unavailable"]["crossref"] = {"detail": str(exc)[:200]}

    # ------------------------------- Crossref retraction notices (title search)
    try:
        payload = request_json(
            session,
            CROSSREF_SEARCH_URL,
            "crossref",
            params={
                "filter": "update-type:retraction",
                "query.bibliographic": title or normalized,
                "rows": 5,
                "mailto": "openags@example.com",
            },
            timeout=timeout,
        )
        for item in ((payload or {}).get("message") or {}).get("items") or []:
            targets = [normalize_doi(str((u or {}).get("DOI") or "")).lower()
                       for u in (item.get("update-to") or [])]
            notice = {
                "notice_doi": item.get("DOI", ""),
                "title": (item.get("title") or [""])[0],
                "type": item.get("type", ""),
                "targets_this_doi": normalized.lower() in targets,
                "issued": ((item.get("issued") or {}).get("date-parts") or [[None]])[0],
            }
            result["notices"].append(notice)
            if notice["targets_this_doi"]:
                result["is_retracted"] = True
                result["evidence"].append({
                    "source": "crossref",
                    "field": "retraction-notice-search",
                    "notice_doi": notice["notice_doi"],
                })
    except Exception as exc:
        logger.debug("Crossref retraction-notice search failed: %s", exc)

    if result["sources_checked"] and not result["sources_unavailable"]:
        result["status"] = "ok"
    elif result["sources_checked"]:
        result["status"] = "partial"
    else:
        result["status"] = "unavailable"

    return result
