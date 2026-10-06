# paper_search_mcp/server.py
from typing import List, Dict, Optional, Any
import asyncio
import os
import logging
import re
import time
import httpx
from mcp.server.fastmcp import FastMCP
from .config import get_env, ncbi_eutils_params  # patched: E-utilities key
from .academic_platforms.arxiv import ArxivSearcher
from .academic_platforms.pubmed import PubMedSearcher
from .academic_platforms.biorxiv import BioRxivSearcher
from .academic_platforms.medrxiv import MedRxivSearcher
from .academic_platforms.google_scholar import GoogleScholarSearcher
from .academic_platforms.iacr import IACRSearcher
from .academic_platforms.semantic import SemanticSearcher
from .academic_platforms.crossref import CrossRefSearcher
from .academic_platforms.openalex import OpenAlexSearcher
from .academic_platforms.pmc import PMCSearcher
from .academic_platforms.core import CORESearcher
from .academic_platforms.europepmc import EuropePMCSearcher
from .academic_platforms.sci_hub import SciHubFetcher
from .academic_platforms.dblp import DBLPSearcher
from .academic_platforms.openaire import OpenAiresearcher
from .academic_platforms.citeseerx import CiteSeerXSearcher
from .academic_platforms.doaj import DOAJSearcher
from .academic_platforms.base_search import BASESearcher
from .academic_platforms.unpaywall import UnpaywallResolver, UnpaywallSearcher
from .academic_platforms.zenodo import ZenodoSearcher
from .academic_platforms.plos import PLOSSearcher
from .academic_platforms.jstage import JStageSearcher
from .academic_platforms.figshare import FigshareSearcher
from .academic_platforms.chemrxiv import ChemRxivSearcher
from .academic_platforms.datacite import DataCiteSearcher
from .academic_platforms.whoris import WhoIrisSearcher
from .academic_platforms.osf import OSFSearcher
from .academic_platforms.clinicaltrials import ClinicalTrialsSearcher
from .academic_platforms.bookshelf import BookshelfSearcher
from .academic_platforms.ictrp import ICTRPSearcher
from .academic_platforms.ctis import CTISSearcher
from .academic_platforms.hal import HALSearcher
from .academic_platforms.ssrn import SSRNSearcher
from .utils import extract_doi
from .query_planning import (  # paper-search-mcp-patches: Tier 3/4/5
    band_summary,
    mesh_terms,
    query_variants,
    rank_papers,
    route_sources,
)
from .retraction import check_retraction as _check_retraction_impl  # Tier 6
from .citation import (  # Tier 8/9
    format_citations as _format_citations_impl,
    paper_dict as _doi_paper_dict,
    resolve_doi_metadata as _resolve_doi_metadata,
)
from .source_status import (  # paper-search-mcp-patches: Tier 1
    SOURCE_EMPTY,
    SOURCE_OK,
    SOURCE_UNAVAILABLE,
    SourceUnavailable,
    split_markers,
    unavailable_marker,
)

# from .academic_platforms.hub import SciHubSearcher
from .paper import Paper

# Initialize MCP server
mcp = FastMCP("paper_search_server")
logger = logging.getLogger(__name__)

# Instances of searchers
arxiv_searcher = ArxivSearcher()
pubmed_searcher = PubMedSearcher()
biorxiv_searcher = BioRxivSearcher()
medrxiv_searcher = MedRxivSearcher()
google_scholar_searcher = GoogleScholarSearcher()
iacr_searcher = IACRSearcher()
semantic_searcher = SemanticSearcher()
crossref_searcher = CrossRefSearcher()
openalex_searcher = OpenAlexSearcher()
pmc_searcher = PMCSearcher()
core_searcher = CORESearcher()
europepmc_searcher = EuropePMCSearcher()
dblp_searcher = DBLPSearcher()
openaire_searcher = OpenAiresearcher()
citeseerx_searcher = CiteSeerXSearcher()
doaj_searcher = DOAJSearcher()
base_searcher = BASESearcher()
unpaywall_resolver = UnpaywallResolver()
unpaywall_searcher = UnpaywallSearcher(resolver=unpaywall_resolver)
zenodo_searcher = ZenodoSearcher()
plos_searcher = PLOSSearcher()
jstage_searcher = JStageSearcher()
figshare_searcher = FigshareSearcher()
chemrxiv_searcher = ChemRxivSearcher()
datacite_searcher = DataCiteSearcher()
whoris_searcher = WhoIrisSearcher()
osf_searcher = OSFSearcher()
clinicaltrials_searcher = ClinicalTrialsSearcher()
bookshelf_searcher = BookshelfSearcher()
ictrp_searcher = ICTRPSearcher()
ctis_searcher = CTISSearcher()
hal_searcher = HALSearcher()
ssrn_searcher = SSRNSearcher()
# scihub_searcher = SciHubSearcher()


# Asynchronous helper to adapt synchronous searchers
# Runs blocking requests-based calls in a thread pool to avoid blocking the event loop.
async def async_search(searcher, query: str, max_results: int, **kwargs) -> List[Dict]:
    """Run a synchronous searcher off the event loop.

    Tier 1 (paper-search-mcp-patches): a connector that cannot be reached now
    yields an availability marker instead of an empty list, so "the source is
    rate-limited / down" is never reported as "no such literature exists".
    """
    try:
        if 'year' in kwargs:
            papers = await asyncio.to_thread(searcher.search, query, max_results=max_results, year=kwargs['year'])
        elif kwargs:
            papers = await asyncio.to_thread(searcher.search, query, max_results=max_results, **kwargs)
        else:
            papers = await asyncio.to_thread(searcher.search, query, max_results=max_results)
    except SourceUnavailable as exc:
        logger.warning("%s", exc)
        return unavailable_marker(exc)
    return [paper.to_dict() for paper in papers]


ALL_SOURCES = [
    "arxiv",
    "pubmed",
    "biorxiv",
    "medrxiv",
    "google_scholar",
    "iacr",
    "semantic",
    "crossref",
    "openalex",
    "pmc",
    "core",
    "europepmc",
    "dblp",
    "openaire",
    "citeseerx",
    "doaj",
    "base",
    "zenodo",
    "hal",
    "ssrn",
    "unpaywall",
]

# Retired sources: verified upstream-broken, so search_papers never fans out
# to them and their MCP tools are unregistered before the server starts.
RETIRED_SOURCES = {"dblp", "base", "citeseerx", "google_scholar"}


# Sources added by paper-search-mcp-patches (all verified free, no API key).
ALL_SOURCES = ALL_SOURCES + [
    "plos", "jstage", "figshare", "datacite", "whoris", "osf", "clinicaltrials",
    "bookshelf", "ictrp", "ctis", "chemrxiv",
]

# Tier 1: de-duplicate. Two earlier patches appended the same names, so
# search_papers fanned out twice to identical sources and reported them twice.
ALL_SOURCES = list(dict.fromkeys(ALL_SOURCES))


def _is_active_source(source: str) -> bool:
    return source not in RETIRED_SOURCES


# ---------------------------------------------------------------------------
# Optional paid-platform connectors (disabled by default)
# Set PAPER_SEARCH_MCP_IEEE_API_KEY / PAPER_SEARCH_MCP_ACM_API_KEY to activate
# (legacy IEEE_API_KEY / ACM_API_KEY are also supported).
# ---------------------------------------------------------------------------
_ieee_api_key = get_env("IEEE_API_KEY", "")
_acm_api_key = get_env("ACM_API_KEY", "")

if _ieee_api_key:
    from .academic_platforms.ieee import IEEESearcher
    ieee_searcher = IEEESearcher()
    ALL_SOURCES.append("ieee")
    logger.info("IEEE Xplore enabled via configured environment key.")
else:
    ieee_searcher = None

if _acm_api_key:
    from .academic_platforms.acm import ACMSearcher
    acm_searcher = ACMSearcher()
    ALL_SOURCES.append("acm")
    logger.info("ACM Digital Library enabled via configured environment key.")
else:
    acm_searcher = None

# ---------------------------------------------------------------------------
# Keyed publisher connectors (free keys; enabled when the key is present)
# Set PAPER_SEARCH_MCP_SPRINGER_NATURE_API_KEY / PAPER_SEARCH_MCP_ELSEVIER_API_KEY
# (legacy SPRINGER_NATURE_API_KEY / ELSEVIER_API_KEY also work).
#
# Springer Nature -- Meta API for search plus the Open Access API for full text.
#   Free plan: 500 hits/day, 100 hits/min, enforced inside the connector.
# Elsevier -- Scopus/ScienceDirect search and abstracts with a free key; full
#   text additionally needs an institutional entitlement token.
# ---------------------------------------------------------------------------
_springer_api_key = (
    get_env("SPRINGER_NATURE_API_KEY", "")
    or get_env("SPRINGER_NATURE_META_API_KEY", "")
    or get_env("SPRINGER_NATURE_OPENACCESS_API_KEY", "")
)
_elsevier_api_key = get_env("ELSEVIER_API_KEY", "")

if _springer_api_key:
    from .academic_platforms.springer import SpringerNatureSearcher
    springer_searcher = SpringerNatureSearcher()
    ALL_SOURCES.append("springer")
    logger.info("Springer Nature enabled via configured environment key.")
else:
    springer_searcher = None

if _elsevier_api_key:
    from .academic_platforms.elsevier import ElsevierSearcher
    elsevier_searcher = ElsevierSearcher()
    ALL_SOURCES.append("elsevier")
    logger.info("Elsevier (Scopus) enabled via configured environment key.")
else:
    elsevier_searcher = None


def _parse_sources(sources: str) -> List[str]:
    if not sources or sources.strip().lower() == "all":
        return [source for source in ALL_SOURCES if _is_active_source(source)]

    normalized = [part.strip().lower() for part in sources.split(",") if part.strip()]
    return [
        source for source in normalized
        if source in ALL_SOURCES and _is_active_source(source)
    ]


def _paper_unique_key(paper: Dict[str, Any]) -> str:
    doi = (paper.get("doi") or "").strip().lower()
    if doi:
        return f"doi:{doi}"

    title = (paper.get("title") or "").strip().lower()
    authors = (paper.get("authors") or "").strip().lower()
    if title:
        return f"title:{title}|authors:{authors}"

    paper_id = (paper.get("paper_id") or "").strip().lower()
    return f"id:{paper_id}"


def _dedupe_papers(papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for paper in papers:
        key = _paper_unique_key(paper)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(paper)

    return deduped


def _safe_filename(filename_hint: str, default: str = "paper") -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", filename_hint).strip("._")
    if not safe:
        return default
    return safe[:120]


async def _download_from_url(pdf_url: str, save_path: str, filename_hint: str = "paper") -> Optional[str]:
    if not pdf_url:
        return None

    os.makedirs(save_path, exist_ok=True)
    output_name = f"{_safe_filename(filename_hint)}.pdf"
    output_path = os.path.join(save_path, output_name)

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            response = await client.get(pdf_url)

        if response.status_code >= 400 or not response.content:
            return None

        content_type = (response.headers.get("content-type") or "").lower()
        is_pdf = "pdf" in content_type or response.content.startswith(b"%PDF") or pdf_url.lower().endswith(".pdf")
        if not is_pdf:
            logger.warning("Resolved URL is not a PDF candidate: %s (content-type=%s)", pdf_url, content_type)
            return None

        with open(output_path, "wb") as file_obj:
            file_obj.write(response.content)

        return output_path
    except Exception as exc:
        logger.warning("Direct URL download failed for %s: %s", pdf_url, exc)
        return None


async def _try_repository_fallback(doi: str, title: str, save_path: str) -> tuple[Optional[str], str]:
    repository_searchers = [
        ("openaire", openaire_searcher),
        ("core", core_searcher),
        ("europepmc", europepmc_searcher),
        ("pmc", pmc_searcher),
    ]

    query_candidates = [(doi or "").strip(), (title or "").strip()]
    query_candidates = [candidate for candidate in query_candidates if candidate]
    if not query_candidates:
        return None, "no DOI/title provided for repository fallback"

    repository_errors: List[str] = []

    for repo_name, searcher in repository_searchers:
        for query in query_candidates:
            try:
                papers = await asyncio.to_thread(searcher.search, query, max_results=3)
            except Exception as exc:
                repository_errors.append(f"{repo_name}:{exc}")
                continue

            if not papers:
                continue

            for paper in papers:
                pdf_url = str(getattr(paper, "pdf_url", "") or "").strip()
                if not pdf_url:
                    continue

                raw_paper_id = getattr(paper, "paper_id", "")
                paper_id = str(raw_paper_id or query).strip()
                downloaded = await _download_from_url(pdf_url, save_path, f"{repo_name}_{paper_id}")
                if downloaded:
                    return downloaded, ""

    return None, "; ".join(repository_errors)


#: paper-search-mcp-patches: per-source wall-clock budget for a fan-out.
#:
#: Measured 2026-09-29: there was no bound at all, and several connectors retry
#: internally (DataCite 3 x 30s, figshare/jstage/osf/plos 3 attempts, biorxiv
#: max_retries), so one stalled source held the whole call open until the MCP
#: client's 300s timeout and the caller received nothing at all.  A source that
#: exceeds its budget is reported as unavailable instead, which is the honest
#: answer, and every other source's results still come through.
PER_SOURCE_TIMEOUT = 45.0

#: Total wall-clock budget for one search_papers call, across query variants.
GLOBAL_BUDGET = 150.0


async def _await_source(name: str, coro: Any, timeout: float) -> Any:
    """Await one source, turning a timeout into a SourceUnavailable marker."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        return SourceUnavailable(name, f"timed out after {timeout:.0f}s")


#: Tier 9: a DOI as the ENTIRE query -- ``10.<registrant>/<suffix>``, nothing else.
_DOI_QUERY_RE = re.compile(r"^10\.\d{4,9}/\S+$")


def _doi_query(query: str) -> str:
    """The DOI when the whole query is one, else ''.

    Strict on purpose: ``normalize_doi`` strips resolver prefixes but validates
    nothing, so text that merely *contains* a DOI must not take this path.
    """
    text = str(query or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/",
                   "http://dx.doi.org/", "doi:", "DOI:"):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()
            break
    return text if _DOI_QUERY_RE.match(text) else ""


async def _search_by_doi(
    doi: str, sources: str, max_results_per_source: int
) -> Dict[str, Any]:
    """Resolve a DOI-shaped query exactly, instead of fuzzy keyword-matching it.

    Measured 2026-09-29: the DOI-shaped nonsense query
    ``10.9999/nonexistent.doi.xyz`` returned 6 irrelevant papers from the keyword
    fan-out (semantic, figshare and whoris match digits-and-slashes fuzzily),
    whereas a real DOI resolves exactly at Crossref.  So a query that *is* a DOI
    goes to the DOI resolvers and the 30-engine fan-out is skipped -- precision by
    construction rather than by ranking.
    """
    source_status: Dict[str, Dict[str, Any]] = {}
    errors: Dict[str, str] = {}
    papers: List[Dict[str, Any]] = []

    def _unavailable(name: str, exc: Exception) -> None:
        source_status[name] = {
            "status": SOURCE_UNAVAILABLE,
            "source": name,
            "http_status": getattr(exc, "http_status", None),
            "retry_after": getattr(exc, "retry_after", None),
            "message": str(getattr(exc, "message", "") or exc)[:200],
        }
        errors[name] = source_status[name]["message"]

    # Crossref -- the DOI registration agency, so this is the record of authority.
    try:
        message = await asyncio.to_thread(_resolve_doi_metadata, doi)
        papers.append(_doi_paper_dict(doi, message))
        source_status["crossref"] = {
            "status": SOURCE_OK, "source": "crossref", "returned": 1,
        }
    except Exception as exc:  # noqa: BLE001 -- never silently empty
        _unavailable("crossref", exc)

    # Unpaywall -- an exact DOI resolver, so it can say where the PDF is free.
    if papers:
        try:
            pdf_url = await asyncio.to_thread(
                unpaywall_resolver.resolve_best_pdf_url, papers[0]["doi"]
            )
            if pdf_url:
                papers[0]["pdf_url"] = pdf_url
            source_status["unpaywall"] = {
                "status": SOURCE_OK,
                "source": "unpaywall",
                "returned": 1,
                "message": ("open-access copy found" if pdf_url
                            else "no open-access copy"),
            }
        except Exception as exc:  # noqa: BLE001
            _unavailable("unpaywall", exc)

    unavailable = {
        name: entry for name, entry in source_status.items()
        if entry.get("status") == SOURCE_UNAVAILABLE
    }
    result: Dict[str, Any] = {
        "query": doi,
        "query_type": "doi",
        "doi": doi,
        "queries_used": [doi],
        "sources_requested": sources,
        "sources_used": list(source_status),
        "source_results": {
            name: entry.get("returned", 0) for name, entry in source_status.items()
        },
        "source_status": source_status,
        "sources_unavailable": unavailable,
        "errors": errors,
        "papers": papers,
        "total": len(papers),
        "raw_total": len(papers),
        "relevance_bands": {},
        "routing_note": (
            "The query is a DOI, so it was resolved exactly at the DOI registries "
            "and the keyword fan-out was skipped: a DOI-shaped string fuzzy-matches "
            "irrelevant records in some search engines."
        ),
    }
    if unavailable:
        result["warning"] = (
            "%d DOI resolver(s) unavailable (%s); the DOI may still resolve at "
            "https://doi.org/%s"
            % (len(unavailable), ", ".join(sorted(unavailable)), doi)
        )
    return result


def _build_task_map(
    selected_sources: List[str],
    query: str,
    max_results_per_source: int,
    year: Optional[str],
) -> Dict[str, Any]:
    """Map source name -> search coroutine for one query.

    Tier 1 fix (paper-search-mcp-patches): the six sources added by these patches
    (plos, jstage, figshare, datacite, whoris, osf) were missing from the old
    inline chain, so ``sources="all"`` silently skipped them even though they
    were listed in ALL_SOURCES.
    """
    task_map: Dict[str, Any] = {}
    for source in selected_sources:
        if source == "arxiv":
            task_map[source] = search_arxiv(query, max_results_per_source)
        elif source == "pubmed":
            task_map[source] = search_pubmed(query, max_results_per_source)
        elif source == "biorxiv":
            task_map[source] = search_biorxiv(query, max_results_per_source)
        elif source == "medrxiv":
            task_map[source] = search_medrxiv(query, max_results_per_source)
        elif source == "google_scholar":
            task_map[source] = search_google_scholar(query, max_results_per_source)
        elif source == "iacr":
            task_map[source] = search_iacr(query, max_results_per_source, fetch_details=False)
        elif source == "semantic":
            task_map[source] = search_semantic(query, year=year, max_results=max_results_per_source)
        elif source == "crossref":
            task_map[source] = search_crossref(query, max_results=max_results_per_source)
        elif source == "openalex":
            task_map[source] = search_openalex(query, max_results_per_source)
        elif source == "pmc":
            task_map[source] = search_pmc(query, max_results_per_source)
        elif source == "core":
            task_map[source] = search_core(query, max_results_per_source)
        elif source == "europepmc":
            task_map[source] = search_europepmc(query, max_results_per_source)
        elif source == "dblp":
            task_map[source] = search_dblp(query, max_results_per_source)
        elif source == "openaire":
            task_map[source] = search_openaire(query, max_results_per_source)
        elif source == "citeseerx":
            task_map[source] = search_citeseerx(query, max_results_per_source)
        elif source == "doaj":
            task_map[source] = search_doaj(query, max_results_per_source)
        elif source == "base":
            task_map[source] = search_base(query, max_results_per_source)
        elif source == "zenodo":
            task_map[source] = search_zenodo(query, max_results_per_source)
        elif source == "hal":
            task_map[source] = search_hal(query, max_results_per_source)
        elif source == "ssrn":
            task_map[source] = search_ssrn(query, max_results_per_source)
        elif source == "unpaywall":
            task_map[source] = search_unpaywall(query, max_results_per_source)
        elif source == "plos":
            task_map[source] = search_plos(query, max_results_per_source)
        elif source == "jstage":
            task_map[source] = search_jstage(query, max_results_per_source)
        elif source == "figshare":
            task_map[source] = search_figshare(query, max_results_per_source)
        elif source == "chemrxiv":
            task_map[source] = search_chemrxiv(query, max_results_per_source)
        elif source == "datacite":
            task_map[source] = search_datacite(query, max_results_per_source)
        elif source == "whoris":
            task_map[source] = search_whoris(query, max_results_per_source)
        elif source == "osf":
            task_map[source] = search_osf(query, max_results_per_source)
        elif source == "clinicaltrials":
            task_map[source] = search_clinicaltrials(query, max_results_per_source)
        elif source == "bookshelf":
            task_map[source] = search_bookshelf(query, max_results_per_source)
        elif source == "ictrp":
            task_map[source] = search_ictrp(query, max_results_per_source)
        elif source == "ctis":
            task_map[source] = search_ctis(query, max_results_per_source)
        elif source == "ieee":
            if ieee_searcher is not None:
                task_map[source] = async_search(ieee_searcher, query, max_results_per_source)
        elif source == "acm":
            if acm_searcher is not None:
                task_map[source] = async_search(acm_searcher, query, max_results_per_source)
        elif source == "springer":
            if springer_searcher is not None:
                task_map[source] = async_search(springer_searcher, query, max_results_per_source)
        elif source == "elsevier":
            if elsevier_searcher is not None:
                task_map[source] = async_search(elsevier_searcher, query, max_results_per_source)
    return task_map


@mcp.tool()
async def search_papers(
    query: str,
    max_results_per_source: int = 5,
    sources: str = "all",
    year: Optional[str] = None,
    rank: bool = True,
    expand: bool = False,
) -> Dict[str, Any]:
    """Unified top-level search across all configured academic platforms.

    Tier 1 (paper-search-mcp-patches): per-source ``source_status`` distinguishes
    "unavailable" (rate-limited / down) from "empty" (genuinely no matches), so a
    failed lookup is never mistaken for absent literature.

    Tier 3: results are ranked against the query (title 2.0x, abstract 1.0x,
    metadata 0.5x, phrase/all-terms bonuses) and banded high/medium/low.

    Tier 5: pass ``sources="auto"`` to route sources by topic domain.

    Tier 9: when the whole query is a DOI, it is resolved exactly at Crossref (plus
    Unpaywall for an open-access copy) and the keyword fan-out is skipped, because a
    DOI-shaped string fuzzy-matches irrelevant records in some engines.  Such a
    result carries ``query_type: "doi"`` and a ``routing_note``.

    Args:
        query: Search query string.
        max_results_per_source: Max results to fetch from each selected source.
        sources: Comma-separated source names, 'all', or 'auto' (domain routing).
        year: Optional year filter for Semantic Scholar only.
        rank: Rank merged results by relevance to the query (default True).
        expand: Also query an expanded form (all-terms variant + MeSH terms).

    Returns:
        Aggregated dictionary with per-source stats, per-source status, ranked
        papers, relevance bands and the queries actually issued.
    """
    # Tier 9: a query that IS a DOI is resolved exactly, not fuzzy-matched.
    doi = _doi_query(query)
    if doi:
        return await _search_by_doi(doi, sources, max_results_per_source)

    # Tier 4: optional query expansion (variants + free MeSH vocabulary).
    queries: List[str] = [query]
    if expand:
        variants = [
            item["query"] for item in query_variants(query)
            if item["kind"] == "all_terms"
        ]
        queries.extend(variants[:1])
        mesh = mesh_terms(query)
        if mesh:
            queries.append(mesh[0])
    queries = list(dict.fromkeys(q.strip() for q in queries if q and q.strip()))

    # Tier 5: source routing ("auto").
    routing: Optional[Dict[str, Any]] = None
    if sources and sources.strip().lower() == "auto":
        routing = route_sources(
            query,
            all_sources=ALL_SOURCES,
            retired_sources=sorted(RETIRED_SOURCES),
        )
        selected_sources = [
            source for source in routing["sources"]
            if source in ALL_SOURCES and _is_active_source(source)
        ]
    else:
        selected_sources = _parse_sources(sources)
    selected_sources = list(dict.fromkeys(selected_sources))

    if not selected_sources:
        return {
            "query": query,
            "queries_used": queries,
            "sources_requested": sources,
            "sources_used": [],
            "source_results": {},
            "source_status": {},
            "errors": {"sources": "No valid sources selected."},
            "papers": [],
            "total": 0,
        }

    source_status: Dict[str, Dict[str, Any]] = {}
    errors: Dict[str, str] = {}
    merged_papers: List[Dict[str, Any]] = []

    deadline = time.monotonic() + GLOBAL_BUDGET

    for run_query in queries:
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            # Out of budget: report the rest as unavailable rather than hanging.
            break
        per_source_timeout = max(1.0, min(PER_SOURCE_TIMEOUT, remaining))

        task_map = _build_task_map(
            selected_sources, run_query, max_results_per_source, year
        )
        if not task_map:
            break

        source_names = list(task_map.keys())
        # Every source is bounded, so the gather itself is bounded: one slow or
        # internally-retrying source can no longer consume the whole budget.
        source_outputs = await asyncio.gather(
            *(
                _await_source(name, coro, per_source_timeout)
                for name, coro in task_map.items()
            ),
            return_exceptions=True,
        )

        for source_name, output in zip(source_names, source_outputs):
            if isinstance(output, Exception):
                if isinstance(output, SourceUnavailable):
                    source_status[source_name] = output.to_dict()
                else:
                    source_status[source_name] = {
                        "status": SOURCE_UNAVAILABLE,
                        "source": source_name,
                        "http_status": None,
                        "retry_after": None,
                        "message": f"{type(output).__name__}: {output}"[:300],
                    }
                errors[source_name] = source_status[source_name].get("message", "")
                continue

            papers, markers = split_markers(output)
            for marker in markers:
                source_status[source_name] = {
                    "status": SOURCE_UNAVAILABLE,
                    "source": source_name,
                    "http_status": marker.get("http_status"),
                    "retry_after": marker.get("retry_after"),
                    "message": marker.get("message", ""),
                }
                errors[source_name] = marker.get("detail") or marker.get("message", "")

            if papers:
                entry = source_status.get(source_name) or {"source": source_name}
                entry["status"] = SOURCE_OK
                entry["returned"] = entry.get("returned", 0) + len(papers)
                source_status[source_name] = entry
            elif source_name not in source_status:
                source_status[source_name] = {
                    "status": SOURCE_EMPTY,
                    "source": source_name,
                    "returned": 0,
                }

            for paper in papers:
                if not paper.get("source"):
                    paper["source"] = source_name
                if run_query != query:
                    paper["matched_query"] = run_query
                merged_papers.append(paper)

    source_results = {
        name: source_status.get(name, {}).get("returned", 0)
        for name in selected_sources
    }

    deduped_papers = _dedupe_papers(merged_papers)
    ranked_papers = rank_papers(deduped_papers, query) if rank else deduped_papers

    unavailable = {
        name: entry for name, entry in source_status.items()
        if entry.get("status") == SOURCE_UNAVAILABLE
    }

    result: Dict[str, Any] = {
        "query": query,
        "queries_used": queries,
        "sources_requested": sources,
        "sources_used": selected_sources,
        "source_results": source_results,
        "source_status": source_status,
        "sources_unavailable": unavailable,
        "errors": errors,
        "papers": ranked_papers,
        "total": len(ranked_papers),
        "raw_total": len(merged_papers),
        "relevance_bands": band_summary(ranked_papers) if rank else {},
    }
    if unavailable:
        # Tier 7: make it impossible to read an unavailable source as "the
        # literature does not exist".  Any caller seeing total=0 must check this
        # before concluding anything.
        result["warning"] = (
            f"{len(unavailable)} of {len(selected_sources)} sources were "
            f"unavailable ({', '.join(sorted(unavailable))}); their absence is "
            "not evidence that no matching literature exists."
        )
    if routing is not None:
        result["routing"] = {
            "domain": routing["domain"],
            "rationale": routing["rationale"],
        }
    return result


# Tool definitions
@mcp.tool()
async def search_arxiv(query: str, max_results: int = 10, sort_by: str = 'relevance', sort_order: str = 'descending') -> List[Dict]:
    """Search academic papers from arXiv.

    Args:
        query: Search query string (e.g., 'machine learning').
        max_results: Maximum number of papers to return (default: 10).
        sort_by: Sort criterion — 'relevance', 'submittedDate', or 'lastUpdatedDate' (default: 'relevance').
        sort_order: Sort direction — 'descending' or 'ascending' (default: 'descending').
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(arxiv_searcher, query, max_results, sort_by=sort_by, sort_order=sort_order)
    return papers if papers else []


@mcp.tool()
async def search_pubmed(query: str, max_results: int = 10, sort: str = 'relevance') -> List[Dict]:
    """Search academic papers from PubMed.

    Args:
        query: Search query string (e.g., 'machine learning').
        max_results: Maximum number of papers to return (default: 10).
        sort: Sort order — 'relevance' or 'pub_date' (default: 'relevance').
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(pubmed_searcher, query, max_results, sort=sort)
    return papers if papers else []


@mcp.tool()
async def search_biorxiv(query: str, max_results: int = 10,
                         category: str = "") -> List[Dict]:
    """Search bioRxiv preprints by keyword, and/or by subject category.

    Keyword search is served by Europe PMC -- the bioRxiv API itself is
    date-interval only and cannot answer a keyword query -- with relevance
    ranking.  A subject category is served by the bioRxiv listing API, the only
    interface that carries and filters the category field: an unrecognised
    category is rejected rather than silently ignored, so a category request
    never returns unfiltered results by accident.  Call biorxiv_categories()
    for the valid values.

    Args:
        query: Keyword query (e.g., 'CRISPR base editing'). May be empty when a
            category alone is wanted.
        max_results: Maximum number of papers to return (default: 10).
        category: Optional subject category (e.g., 'Cancer Biology').
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(
        biorxiv_searcher, query, max_results,
        **({"category": category} if category else {}),
    )
    return papers if papers else []


@mcp.tool()
async def biorxiv_categories() -> Dict:
    """List the bioRxiv and medRxiv subject categories the listing APIs filter on.

    Use these strings as the `category` argument of search_biorxiv /
    search_medrxiv.  Do not guess: the bioRxiv listing API silently ignores a
    category it does not recognise and answers with unfiltered records.
    """
    return {
        "biorxiv": list(biorxiv_searcher.list_categories()),
        "medrxiv": list(medrxiv_searcher.list_categories()),
    }


@mcp.tool()
async def biorxiv_published_version(doi: str) -> Dict:
    """Resolve a bioRxiv preprint DOI to its journal version, when one exists.

    Check this before citing a preprint: when the work has been published, cite
    the journal record instead of the preprint.

    Args:
        doi: Preprint DOI (e.g., '10.1101/2025.09.29.679222').
    Returns:
        Dict with published_doi, published_journal, preprint_doi and
        preprint_title; empty when the preprint has no published version yet.
    """
    try:
        return await asyncio.to_thread(biorxiv_searcher.get_published_version, doi)
    except SourceUnavailable as exc:
        return {"error": exc.to_dict()}


@mcp.tool()
async def search_medrxiv(query: str, max_results: int = 10,
                        category: str = "") -> List[Dict]:
    """Search medRxiv preprints by keyword, and/or by subject category.

    Keyword search is served by Europe PMC -- the medRxiv API itself is
    date-interval only and cannot answer a keyword query -- with relevance
    ranking.  A subject category is served by the medRxiv listing API, the only
    interface that carries and filters the category field: an unrecognised
    category is rejected rather than silently ignored.  Call biorxiv_categories()
    for the valid medRxiv values.

    Args:
        query: Keyword query (e.g., 'COVID-19 vaccine effectiveness'). May be
            empty when a category alone is wanted.
        max_results: Maximum number of papers to return (default: 10).
        category: Optional subject category (e.g., 'Infectious Diseases').
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(
        medrxiv_searcher, query, max_results,
        **({"category": category} if category else {}),
    )
    return papers if papers else []


@mcp.tool()
async def search_google_scholar(query: str, max_results: int = 10) -> List[Dict]:
    """Search academic papers from Google Scholar.

    Args:
        query: Search query string (e.g., 'machine learning').
        max_results: Maximum number of papers to return (default: 10).
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(google_scholar_searcher, query, max_results)
    return papers if papers else []


@mcp.tool()
async def search_iacr(
    query: str, max_results: int = 10, fetch_details: bool = True
) -> List[Dict]:
    """Search academic papers from IACR ePrint Archive.

    Args:
        query: Search query string (e.g., 'cryptography', 'secret sharing').
        max_results: Maximum number of papers to return (default: 10).
        fetch_details: Whether to fetch detailed information for each paper (default: True).
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await asyncio.to_thread(iacr_searcher.search, query, max_results, fetch_details)
    return [paper.to_dict() for paper in papers] if papers else []


@mcp.tool()
async def download_arxiv(paper_id: str, save_path: str = "./downloads") -> str:
    """Download PDF of an arXiv paper.

    Args:
        paper_id: arXiv paper ID (e.g., '2106.12345').
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        Path to the downloaded PDF file.
    """
    return await asyncio.to_thread(arxiv_searcher.download_pdf, paper_id, save_path)


@mcp.tool()
async def download_pubmed(paper_id: str, save_path: str = "./downloads") -> str:
    """Attempt to download PDF of a PubMed paper.

    Args:
        paper_id: PubMed ID (PMID).
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        str: Message indicating that direct PDF download is not supported.
    """
    try:
        return pubmed_searcher.download_pdf(paper_id, save_path)
    except NotImplementedError as e:
        return str(e)


@mcp.tool()
async def download_biorxiv(paper_id: str, save_path: str = "./downloads") -> str:
    """Download PDF of a bioRxiv paper.

    Args:
        paper_id: bioRxiv DOI.
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        Path to the downloaded PDF file.
    """
    return biorxiv_searcher.download_pdf(paper_id, save_path)


@mcp.tool()
async def download_medrxiv(paper_id: str, save_path: str = "./downloads") -> str:
    """Download PDF of a medRxiv paper.

    Args:
        paper_id: medRxiv DOI.
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        Path to the downloaded PDF file.
    """
    return medrxiv_searcher.download_pdf(paper_id, save_path)


@mcp.tool()
async def download_iacr(paper_id: str, save_path: str = "./downloads") -> str:
    """Download PDF of an IACR ePrint paper.

    Args:
        paper_id: IACR paper ID (e.g., '2009/101').
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        Path to the downloaded PDF file.
    """
    return iacr_searcher.download_pdf(paper_id, save_path)


@mcp.tool()
async def read_arxiv_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read and extract text content from an arXiv paper PDF.

    Args:
        paper_id: arXiv paper ID (e.g., '2106.12345').
        save_path: Directory where the PDF is/will be saved (default: './downloads').
    Returns:
        str: The extracted text content of the paper.
    """
    try:
        return arxiv_searcher.read_paper(paper_id, save_path)
    except Exception as e:
        print(f"Error reading paper {paper_id}: {e}")
        return ""


@mcp.tool()
async def read_pubmed_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read and extract text content from a PubMed paper.

    Args:
        paper_id: PubMed ID (PMID).
        save_path: Directory where the PDF would be saved (unused).
    Returns:
        str: Message indicating that direct paper reading is not supported.
    """
    return pubmed_searcher.read_paper(paper_id, save_path)


@mcp.tool()
async def read_pmc_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read the full text of a PubMed Central article.

    Use this to read an article found by search_pmc / pubmed: pass the PMCID
    (e.g. 'PMC13601907') or the bare number.

    Text comes from the JATS XML served by NCBI efetch, which is the reliable
    route: the PMC PDF endpoint answers HTTP 403, while efetch returns the whole
    article in 1-2s (verified: 127,694 chars of body text for PMC13601907). An
    article with no open-access full text raises rather than returning an empty
    document.

    Args:
        paper_id: PMCID (e.g. 'PMC13601907') or bare number.
        save_path: Directory used only by the PDF fallback.
    Returns:
        str: The article's body text.
    """
    return pmc_searcher.read_paper(paper_id, save_path)


@mcp.tool()
async def read_biorxiv_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read and extract text content from a bioRxiv paper PDF.

    Args:
        paper_id: bioRxiv DOI.
        save_path: Directory where the PDF is/will be saved (default: './downloads').
    Returns:
        str: The extracted text content of the paper.
    """
    # No blanket except: a failed read must surface as an error, not as "".  An
    # empty string is indistinguishable from a genuinely empty document.
    return biorxiv_searcher.read_paper(paper_id, save_path)


@mcp.tool()
async def read_medrxiv_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read and extract text content from a medRxiv paper PDF.

    Args:
        paper_id: medRxiv DOI.
        save_path: Directory where the PDF is/will be saved (default: './downloads').
    Returns:
        str: The extracted text content of the paper.
    """
    try:
        return medrxiv_searcher.read_paper(paper_id, save_path)
    except Exception as e:
        print(f"Error reading paper {paper_id}: {e}")
        return ""


@mcp.tool()
async def read_iacr_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read and extract text content from an IACR ePrint paper PDF.

    Args:
        paper_id: IACR paper ID (e.g., '2009/101').
        save_path: Directory where the PDF is/will be saved (default: './downloads').
    Returns:
        str: The extracted text content of the paper.
    """
    try:
        return iacr_searcher.read_paper(paper_id, save_path)
    except Exception as e:
        print(f"Error reading paper {paper_id}: {e}")
        return ""


@mcp.tool()
async def search_semantic(query: str, year: Optional[str] = None, max_results: int = 10) -> List[Dict]:
    """Search academic papers from Semantic Scholar.

    Args:
        query: Search query string (e.g., 'machine learning').
        year: Optional year filter (e.g., '2019', '2016-2020', '2010-', '-2015').
        max_results: Maximum number of papers to return (default: 10).
    Returns:
        List of paper metadata in dictionary format.
    """
    kwargs = {}
    if year is not None:
        kwargs['year'] = year
    papers = await async_search(semantic_searcher, query, max_results, **kwargs)
    return papers if papers else []


@mcp.tool()
async def download_semantic(paper_id: str, save_path: str = "./downloads") -> str:
    """Download PDF of a Semantic Scholar paper.    

    Args:
        paper_id: Semantic Scholar paper ID, Paper identifier in one of the following formats:
            - Semantic Scholar ID (e.g., "649def34f8be52c8b66281af98ae884c09aef38b")
            - DOI:<doi> (e.g., "DOI:10.18653/v1/N18-3011")
            - ARXIV:<id> (e.g., "ARXIV:2106.15928")
            - MAG:<id> (e.g., "MAG:112218234")
            - ACL:<id> (e.g., "ACL:W12-3903")
            - PMID:<id> (e.g., "PMID:19872477")
            - PMCID:<id> (e.g., "PMCID:2323736")
            - URL:<url> (e.g., "URL:https://arxiv.org/abs/2106.15928v1")
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        Path to the downloaded PDF file.
    """ 
    return semantic_searcher.download_pdf(paper_id, save_path)


@mcp.tool()
async def read_semantic_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read and extract text content from a Semantic Scholar paper. 

    Args:
        paper_id: Semantic Scholar paper ID, Paper identifier in one of the following formats:
            - Semantic Scholar ID (e.g., "649def34f8be52c8b66281af98ae884c09aef38b")
            - DOI:<doi> (e.g., "DOI:10.18653/v1/N18-3011")
            - ARXIV:<id> (e.g., "ARXIV:2106.15928")
            - MAG:<id> (e.g., "MAG:112218234")
            - ACL:<id> (e.g., "ACL:W12-3903")
            - PMID:<id> (e.g., "PMID:19872477")
            - PMCID:<id> (e.g., "PMCID:2323736")
            - URL:<url> (e.g., "URL:https://arxiv.org/abs/2106.15928v1")
        save_path: Directory where the PDF is/will be saved (default: './downloads').
    Returns:
        str: The extracted text content of the paper.
    """
    try:
        return semantic_searcher.read_paper(paper_id, save_path)
    except Exception as e:
        print(f"Error reading paper {paper_id}: {e}")
        return ""


@mcp.tool()
async def search_crossref(
    query: str,
    max_results: int = 10,
    filter: Optional[str] = None,
    sort: Optional[str] = None,
    order: Optional[str] = None,
) -> List[Dict]:
    """Search academic papers from CrossRef database.
    
    CrossRef is a scholarly infrastructure organization that provides 
    persistent identifiers (DOIs) for scholarly content and metadata.
    It's one of the largest citation databases covering millions of 
    academic papers, journals, books, and other scholarly content.

    Args:
        query: Search query string (e.g., 'machine learning', 'climate change').
        max_results: Maximum number of papers to return (default: 10, max: 1000).
        filter: CrossRef filter string (e.g., 'has-full-text:true,from-pub-date:2020').
        sort: Sort field ('relevance', 'published', 'updated', 'deposited', etc.).
        order: Sort order ('asc' or 'desc').
    Returns:
        List of paper metadata in dictionary format.
    """
    extra = {k: v for k, v in {'filter': filter, 'sort': sort, 'order': order}.items() if v is not None}
    papers = await async_search(crossref_searcher, query, max_results, **extra)
    return papers if papers else []


@mcp.tool()
async def get_crossref_paper_by_doi(doi: str) -> Dict:
    """Get a specific paper from CrossRef by its DOI.

    Args:
        doi: Digital Object Identifier (e.g., '10.1038/nature12373').
    Returns:
        Paper metadata in dictionary format, or empty dict if not found.
        
    Example:
        get_crossref_paper_by_doi("10.1038/nature12373")
    """
    paper = await asyncio.to_thread(crossref_searcher.get_paper_by_doi, doi)
    return paper.to_dict() if paper else {}


@mcp.tool()
async def download_crossref(paper_id: str, save_path: str = "./downloads") -> str:
    """Attempt to download PDF of a CrossRef paper.

    Args:
        paper_id: CrossRef DOI (e.g., '10.1038/nature12373').
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        str: Message indicating that direct PDF download is not supported.
        
    Note:
        CrossRef is a citation database and doesn't provide direct PDF downloads.
        Use the DOI to access the paper through the publisher's website.
    """
    try:
        return crossref_searcher.download_pdf(paper_id, save_path)
    except NotImplementedError as e:
        return str(e)


@mcp.tool()
async def download_scihub(
    identifier: str,
    save_path: str = "./downloads",
    base_url: str = "https://sci-hub.se",
) -> str:
    """Download paper PDF via Sci-Hub (optional fallback connector).

    Args:
        identifier: DOI, title, PMID, or paper URL.
        save_path: Directory to save the PDF.
        base_url: Sci-Hub mirror URL.
    Returns:
        Downloaded PDF path on success; error message on failure.
    """
    fetcher = SciHubFetcher(base_url=base_url, output_dir=save_path)
    result = await asyncio.to_thread(fetcher.download_pdf, identifier)
    if result:
        return result
    return "Sci-Hub download failed. Try DOI first, then title, or change mirror URL."


@mcp.tool()
async def download_with_fallback(
    source: str,
    paper_id: str,
    doi: str = "",
    title: str = "",
    save_path: str = "./downloads",
    use_scihub: bool = True,
    scihub_base_url: str = "https://sci-hub.se",
) -> str:
    """Try source-native download, OA repositories, Unpaywall, then optional Sci-Hub.

    Args:
        source: Source name (arxiv, biorxiv, medrxiv, iacr, semantic, crossref, pubmed, pmc, core, europepmc, citeseerx, doaj, base, zenodo, hal, ssrn).
        paper_id: Source-native paper identifier.
        doi: Optional DOI used for repository/unpaywall/Sci-Hub fallback.
        title: Optional title used for repository/Sci-Hub fallback when DOI is unavailable.
        save_path: Directory to save downloaded files.
        use_scihub: Whether to fallback to Sci-Hub after OA attempts fail.
        scihub_base_url: Sci-Hub mirror URL for fallback.
    Returns:
        Download path on success or explanatory error message.
    """
    source_name = source.strip().lower()

    primary_downloaders = {
        "arxiv": arxiv_searcher.download_pdf,
        "biorxiv": biorxiv_searcher.download_pdf,
        "medrxiv": medrxiv_searcher.download_pdf,
        "iacr": iacr_searcher.download_pdf,
        "semantic": semantic_searcher.download_pdf,
        "pubmed": pubmed_searcher.download_pdf,
        "crossref": crossref_searcher.download_pdf,
        "pmc": pmc_searcher.download_pdf,
        "core": core_searcher.download_pdf,
        "europepmc": europepmc_searcher.download_pdf,
        "citeseerx": citeseerx_searcher.download_pdf,
        "doaj": doaj_searcher.download_pdf,
        "base": base_searcher.download_pdf,
        "zenodo": zenodo_searcher.download_pdf,
        "hal": hal_searcher.download_pdf,
        "ssrn": ssrn_searcher.download_pdf,
    }

    attempt_errors: List[str] = []
    primary_error = ""
    if source_name in primary_downloaders:
        try:
            primary_result = await asyncio.to_thread(primary_downloaders[source_name], paper_id, save_path)
            if isinstance(primary_result, str) and os.path.exists(primary_result):
                return primary_result
            if isinstance(primary_result, str) and primary_result:
                primary_error = primary_result
        except Exception as exc:
            primary_error = str(exc)
            logger.warning("Primary download failed for %s/%s: %s", source_name, paper_id, exc)
    else:
        primary_error = f"Unsupported source '{source_name}' for primary download."

    if primary_error:
        attempt_errors.append(f"primary: {primary_error}")

    repository_result, repository_error = await _try_repository_fallback(doi, title, save_path)
    if repository_result:
        return repository_result
    if repository_error:
        attempt_errors.append(f"repositories: {repository_error}")

    normalized_doi = (doi or "").strip()
    if normalized_doi:
        unpaywall_url = await asyncio.to_thread(unpaywall_resolver.resolve_best_pdf_url, normalized_doi)
        if unpaywall_url:
            unpaywall_result = await _download_from_url(unpaywall_url, save_path, f"unpaywall_{normalized_doi}")
            if unpaywall_result:
                return unpaywall_result
            attempt_errors.append("unpaywall: resolved OA URL but download failed")
        else:
            attempt_errors.append("unpaywall: no OA URL found (or PAPER_SEARCH_MCP_UNPAYWALL_EMAIL/UNPAYWALL_EMAIL missing)")
    else:
        attempt_errors.append("unpaywall: DOI not provided")

    if not use_scihub:
        return "Download failed after OA fallback chain. Details: " + " | ".join(attempt_errors)

    fallback_identifier = (doi or "").strip() or (title or "").strip() or paper_id
    fetcher = SciHubFetcher(base_url=scihub_base_url, output_dir=save_path)
    fallback_result = await asyncio.to_thread(fetcher.download_pdf, fallback_identifier)
    if fallback_result:
        return fallback_result

    return "Download failed after OA fallback chain and Sci-Hub fallback. Details: " + " | ".join(attempt_errors)


@mcp.tool()
async def read_crossref_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Attempt to read and extract text content from a CrossRef paper.

    Args:
        paper_id: CrossRef DOI (e.g., '10.1038/nature12373').
        save_path: Directory where the PDF is/will be saved (default: './downloads').
    Returns:
        str: Message indicating that direct paper reading is not supported.
        
    Note:
        CrossRef is a citation database and doesn't provide direct paper content.
        Use the DOI to access the paper through the publisher's website.
    """
    return crossref_searcher.read_paper(paper_id, save_path)


@mcp.tool()
async def search_openalex(query: str, max_results: int = 10) -> List[Dict]:
    """Search academic papers from OpenAlex.

    Args:
        query: Search query string (e.g., 'machine learning').
        max_results: Maximum number of papers to return (default: 10).
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(openalex_searcher, query, max_results)
    return papers if papers else []


@mcp.tool()
async def search_pmc(query: str, max_results: int = 10) -> List[Dict]:
    """Search academic papers from PubMed Central (PMC).

    Args:
        query: Search query string (e.g., 'machine learning').
        max_results: Maximum number of papers to return (default: 10).
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(pmc_searcher, query, max_results)
    return papers if papers else []


@mcp.tool()
async def search_core(query: str, max_results: int = 10) -> List[Dict]:
    """Search academic papers from CORE.

    Args:
        query: Search query string (e.g., 'machine learning').
        max_results: Maximum number of papers to return (default: 10).
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(core_searcher, query, max_results)
    return papers if papers else []


@mcp.tool()
async def search_europepmc(query: str, max_results: int = 10) -> List[Dict]:
    """Search academic papers from Europe PMC.

    Args:
        query: Search query string (e.g., 'machine learning').
        max_results: Maximum number of papers to return (default: 10).
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(europepmc_searcher, query, max_results)
    return papers if papers else []


@mcp.tool()
async def search_dblp(query: str, max_results: int = 10) -> List[Dict]:
    """Search academic papers from dblp computer science bibliography.

    Args:
        query: Search query string (e.g., 'machine learning').
        max_results: Maximum number of papers to return (default: 10).
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(dblp_searcher, query, max_results)
    return papers if papers else []


@mcp.tool()
async def search_openaire(query: str, max_results: int = 10) -> List[Dict]:
    """Search academic papers from OpenAIRE European Open Access infrastructure.

    Args:
        query: Search query string (e.g., 'machine learning').
        max_results: Maximum number of papers to return (default: 10).
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(openaire_searcher, query, max_results)
    return papers if papers else []


@mcp.tool()
async def search_citeseerx(query: str, max_results: int = 10) -> List[Dict]:
    """Search academic papers from CiteSeerX digital library.

    Args:
        query: Search query string (e.g., 'machine learning').
        max_results: Maximum number of papers to return (default: 10).
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(citeseerx_searcher, query, max_results)
    return papers if papers else []


@mcp.tool()
async def search_doaj(query: str, max_results: int = 10) -> List[Dict]:
    """Search academic papers from DOAJ (Directory of Open Access Journals).

    Args:
        query: Search query string (e.g., 'machine learning').
        max_results: Maximum number of papers to return (default: 10).
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(doaj_searcher, query, max_results)
    return papers if papers else []


@mcp.tool()
async def search_base(query: str, max_results: int = 10) -> List[Dict]:
    """Search academic papers from BASE (Bielefeld Academic Search Engine).

    Args:
        query: Search query string (e.g., 'machine learning').
        max_results: Maximum number of papers to return (default: 10).
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(base_searcher, query, max_results)
    return papers if papers else []


@mcp.tool()
async def search_zenodo(query: str, max_results: int = 10) -> List[Dict]:
    """Search academic papers from Zenodo open repository.

    Args:
        query: Search query string (e.g., 'machine learning').
        max_results: Maximum number of papers to return (default: 10).
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(zenodo_searcher, query, max_results)
    return papers if papers else []


@mcp.tool()
async def search_hal(query: str, max_results: int = 10) -> List[Dict]:
    """Search academic papers from HAL open archive.

    Args:
        query: Search query string (e.g., 'machine learning').
        max_results: Maximum number of papers to return (default: 10).
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(hal_searcher, query, max_results)
    return papers if papers else []


@mcp.tool()
async def search_ssrn(query: str, max_results: int = 10) -> List[Dict]:
    """Search metadata records from SSRN.

    Note: SSRN connector is metadata-only and does not support direct PDF download.

    Args:
        query: Search query string (e.g., 'machine learning').
        max_results: Maximum number of papers to return (default: 10).
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(ssrn_searcher, query, max_results)
    return papers if papers else []


@mcp.tool()
async def search_unpaywall(query: str, max_results: int = 10) -> List[Dict]:
    """Lookup a DOI via Unpaywall and return OA metadata.

    Unpaywall is DOI-centric and does not support generic keyword search.
    This tool extracts the first DOI from `query` and returns at most one record.

    Args:
        query: DOI string or text containing a DOI.
        max_results: Kept for API consistency; Unpaywall returns max 1 record.
    Returns:
        List with one paper metadata dict when DOI is resolvable, else empty list.
    """
    papers = await async_search(unpaywall_searcher, query, max_results)
    return papers if papers else []


@mcp.tool()
async def read_dblp_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Attempt to read and extract text content from a dblp paper.

    Note: dblp doesn't provide direct paper content access.
    This function returns an informative message.

    Args:
        paper_id: dblp paper identifier.
        save_path: Directory where the PDF would be saved (unused).
    Returns:
        str: Message indicating that direct paper reading is not supported.
    """
    return dblp_searcher.read_paper(paper_id, save_path)


@mcp.tool()
async def download_dblp(paper_id: str, save_path: str = "./downloads") -> str:
    """Download PDF for a paper from dblp.

    Note: dblp doesn't provide direct PDF access.
    This function returns an informative message.

    Args:
        paper_id: dblp paper identifier.
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        str: Message indicating that direct PDF download is not supported.
    """
    return dblp_searcher.download_pdf(paper_id, save_path)


@mcp.tool()
async def read_openaire_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Attempt to read and extract text content from an OpenAIRE paper.

    Args:
        paper_id: OpenAIRE paper identifier.
        save_path: Directory where the PDF is/will be saved (default: './downloads').
    Returns:
        str: Extracted text or error message.
    """
    return openaire_searcher.read_paper(paper_id, save_path)


@mcp.tool()
async def download_openaire(paper_id: str, save_path: str = "./downloads") -> str:
    """Download PDF for a paper from OpenAIRE.

    Args:
        paper_id: OpenAIRE paper identifier.
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        str: Path to downloaded PDF or error message.
    """
    return openaire_searcher.download_pdf(paper_id, save_path)


@mcp.tool()
async def read_citeseerx_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read and extract text content from a CiteSeerX paper.

    Args:
        paper_id: CiteSeerX paper identifier.
        save_path: Directory where the PDF is/will be saved (default: './downloads').
    Returns:
        str: Extracted text or fallback abstract/error message.
    """
    return citeseerx_searcher.read_paper(paper_id, save_path)


@mcp.tool()
async def download_citeseerx(paper_id: str, save_path: str = "./downloads") -> str:
    """Download PDF for a paper from CiteSeerX.

    Args:
        paper_id: CiteSeerX paper identifier.
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        str: Path to downloaded PDF or error message.
    """
    return citeseerx_searcher.download_pdf(paper_id, save_path)


@mcp.tool()
async def read_doaj_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read and extract text content from a DOAJ paper.

    Args:
        paper_id: DOAJ paper identifier.
        save_path: Directory where the PDF is/will be saved (default: './downloads').
    Returns:
        str: Extracted text content.
    """
    return doaj_searcher.read_paper(paper_id, save_path)


@mcp.tool()
async def download_doaj(paper_id: str, save_path: str = "./downloads") -> str:
    """Download PDF for a paper from DOAJ.

    Args:
        paper_id: DOAJ paper identifier.
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        str: Path to downloaded PDF.
    """
    return doaj_searcher.download_pdf(paper_id, save_path)


@mcp.tool()
async def read_base_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read and extract text content from a BASE paper.

    Args:
        paper_id: BASE paper identifier.
        save_path: Directory where the PDF is/will be saved (default: './downloads').
    Returns:
        str: Extracted text content.
    """
    return base_searcher.read_paper(paper_id, save_path)


@mcp.tool()
async def download_base(paper_id: str, save_path: str = "./downloads") -> str:
    """Download PDF for a paper from BASE.

    Args:
        paper_id: BASE paper identifier.
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        str: Path to downloaded PDF.
    """
    return base_searcher.download_pdf(paper_id, save_path)


@mcp.tool()
async def read_zenodo_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read and extract text content from a Zenodo paper.

    Args:
        paper_id: Zenodo paper identifier.
        save_path: Directory where the PDF is/will be saved (default: './downloads').
    Returns:
        str: Extracted text content.
    """
    return zenodo_searcher.read_paper(paper_id, save_path)


@mcp.tool()
async def download_zenodo(paper_id: str, save_path: str = "./downloads") -> str:
    """Download PDF for a paper from Zenodo.

    Args:
        paper_id: Zenodo paper identifier.
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        str: Path to downloaded PDF.
    """
    return zenodo_searcher.download_pdf(paper_id, save_path)


@mcp.tool()
async def read_hal_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read and extract text content from a HAL paper.

    Args:
        paper_id: HAL paper identifier.
        save_path: Directory where the PDF is/will be saved (default: './downloads').
    Returns:
        str: Extracted text content.
    """
    return hal_searcher.read_paper(paper_id, save_path)


@mcp.tool()
async def download_hal(paper_id: str, save_path: str = "./downloads") -> str:
    """Download PDF for a paper from HAL.

    Args:
        paper_id: HAL paper identifier.
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        str: Path to downloaded PDF.
    """
    return hal_searcher.download_pdf(paper_id, save_path)


@mcp.tool()
async def read_ssrn_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read paper content from SSRN.

    Note: SSRN connector is metadata-only and read is not supported.

    Args:
        paper_id: SSRN paper identifier.
        save_path: Directory where the PDF is/will be saved (unused).
    Returns:
        str: Error message from metadata-only SSRN connector.
    """
    return ssrn_searcher.read_paper(paper_id, save_path)


@mcp.tool()
async def download_ssrn(paper_id: str, save_path: str = "./downloads") -> str:
    """Download PDF for a paper from SSRN.

    Note: SSRN connector is metadata-only and download is not supported.

    Args:
        paper_id: SSRN paper identifier.
        save_path: Directory to save the PDF (unused).
    Returns:
        str: Error message from metadata-only SSRN connector.
    """
    return ssrn_searcher.download_pdf(paper_id, save_path)


@mcp.tool()
async def read_openalex_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Attempt to read and extract text content from an OpenAlex paper.

    Args:
        paper_id: OpenAlex paper ID.
        save_path: Directory where the PDF is/will be saved (default: './downloads').
    Returns:
        str: Message indicating that direct paper reading is not supported natively.
    """
    return openalex_searcher.read_paper(paper_id, save_path)


@mcp.tool()
async def download_openalex(paper_id: str, save_path: str = "./downloads") -> str:
    """Download PDF for a paper from OpenAlex.

    Args:
        paper_id: OpenAlex paper ID.
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        str: Error message, typically OpenAlex relies on extracted pdf_url instead of direct downloads.
    """
    return await asyncio.to_thread(openalex_searcher.download_pdf, paper_id, save_path)


# ---------------------------------------------------------------------------
# Optional IEEE Xplore tools — registered only when API key is set
# ---------------------------------------------------------------------------
if ieee_searcher is not None:
    @mcp.tool()
    async def search_ieee(query: str, max_results: int = 10) -> List[Dict]:
        """Search IEEE Xplore for papers.  Requires PAPER_SEARCH_MCP_IEEE_API_KEY (or IEEE_API_KEY).

        Args:
            query: Search query string.
            max_results: Maximum number of results (default: 10).
        Returns:
            List of paper dicts from IEEE Xplore.
        """
        return await async_search(ieee_searcher, query, max_results)

    @mcp.tool()
    async def download_ieee(paper_id: str, save_path: str = "./downloads") -> str:
        """Download a PDF from IEEE Xplore.  Requires PAPER_SEARCH_MCP_IEEE_API_KEY (or IEEE_API_KEY) and institutional access.

        Args:
            paper_id: IEEE Xplore paper identifier.
            save_path: Directory to save the PDF (default: './downloads').
        Returns:
            str: Path to saved PDF or error message.
        """
        return await asyncio.to_thread(ieee_searcher.download_pdf, paper_id, save_path)

    @mcp.tool()
    async def read_ieee_paper(paper_id: str, save_path: str = "./downloads") -> str:
        """Download and read an IEEE Xplore paper.  Requires PAPER_SEARCH_MCP_IEEE_API_KEY (or IEEE_API_KEY).

        Args:
            paper_id: IEEE Xplore paper identifier.
            save_path: Directory where the PDF is/will be saved (default: './downloads').
        Returns:
            str: Extracted text content.
        """
        return ieee_searcher.read_paper(paper_id, save_path)


# ---------------------------------------------------------------------------
# Optional ACM Digital Library tools — registered only when API key is set
# ---------------------------------------------------------------------------
if acm_searcher is not None:
    @mcp.tool()
    async def search_acm(query: str, max_results: int = 10) -> List[Dict]:
        """Search ACM Digital Library for papers.  Requires PAPER_SEARCH_MCP_ACM_API_KEY (or ACM_API_KEY).

        Args:
            query: Search query string.
            max_results: Maximum number of results (default: 10).
        Returns:
            List of paper dicts from ACM DL.
        """
        return await async_search(acm_searcher, query, max_results)

    @mcp.tool()
    async def download_acm(paper_id: str, save_path: str = "./downloads") -> str:
        """Download a PDF from ACM Digital Library.  Requires PAPER_SEARCH_MCP_ACM_API_KEY (or ACM_API_KEY) and institutional access.

        Args:
            paper_id: ACM DL paper identifier.
            save_path: Directory to save the PDF (default: './downloads').
        Returns:
            str: Path to saved PDF or error message.
        """
        return await asyncio.to_thread(acm_searcher.download_pdf, paper_id, save_path)

    @mcp.tool()
    async def read_acm_paper(paper_id: str, save_path: str = "./downloads") -> str:
        """Download and read an ACM Digital Library paper.  Requires PAPER_SEARCH_MCP_ACM_API_KEY (or ACM_API_KEY).

        Args:
            paper_id: ACM DL paper identifier.
            save_path: Directory where the PDF is/will be saved (default: './downloads').
        Returns:
            str: Extracted text content.
        """
        return acm_searcher.read_paper(paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_plos(query: str, max_results: int = 10) -> List[Dict]:
    """Search PLOS open-access journals (PLOS ONE, Biology, Genetics, Medicine...).

    Args:
        query: Search query string (e.g., 'CRISPR base editing').
        max_results: Maximum number of papers to return (default: 10).
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(plos_searcher, query, max_results)
    return papers if papers else []


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_jstage(query: str, max_results: int = 10) -> List[Dict]:
    """Search J-STAGE, the aggregator of Japanese academic journals.

    Args:
        query: Search query string (e.g., 'CRISPR base editing').
        max_results: Maximum number of papers to return (default: 10).
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(jstage_searcher, query, max_results)
    return papers if papers else []


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_figshare(query: str, max_results: int = 10) -> List[Dict]:
    """Search figshare research outputs (articles, figures, datasets, theses).

    Each hit is enriched from the article detail endpoint so authors and
    abstracts are populated (the search payload alone omits them).

    Args:
        query: Search query string (e.g., 'CRISPR base editing').
        max_results: Maximum number of items to return (default: 10).
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(figshare_searcher, query, max_results)
    return papers if papers else []


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_chemrxiv(query: str, max_results: int = 10) -> List[Dict]:
    """Search ChemRxiv chemistry preprints.

    ChemRxiv is isolated through Crossref using its registered DOI prefix
    10.26434 with type posted-content, so every hit is an actual ChemRxiv
    preprint (the Crossref ``from-publisher`` filter does not exist and the
    upstream connector failed on it).

    Args:
        query: Search query string (e.g., 'catalysis', 'organic synthesis').
        max_results: Maximum number of items to return (default: 10).
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(chemrxiv_searcher, query, max_results)
    return papers if papers else []


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_datacite(query: str, max_results: int = 10) -> List[Dict]:
    """Search DataCite DOIs for datasets, software, theses and other outputs.

    Args:
        query: Search query string (e.g., 'CRISPR dataset').
        max_results: Maximum number of records to return (default: 10).
    Returns:
        List of record metadata in dictionary format.
    """
    papers = await async_search(datacite_searcher, query, max_results)
    return papers if papers else []


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_whoris(query: str, max_results: int = 10) -> List[Dict]:
    """Search WHO IRIS, the World Health Organization institutional repository.

    Args:
        query: Search query string (e.g., 'malaria guidelines').
        max_results: Maximum number of records to return (default: 10).
    Returns:
        List of record metadata in dictionary format.
    """
    papers = await async_search(whoris_searcher, query, max_results)
    return papers if papers else []


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def convert_paper_ids(ids: str, email: str = "") -> Dict:
    """Convert between PMID, PMCID, DOI and MID via the NCBI PMC ID Converter.

    Args:
        ids: One or more comma-separated identifiers (e.g., '38909984,PMC10909955').
        email: Optional contact email (NCBI asks for it; tool name is sent always).
    Returns:
        Dictionary with a 'records' list containing the resolved identifier sets.
    """

    def _run() -> Dict:
        params = {"ids": ids, "format": "json", "tool": "paper-search-mcp"}
        _ncbi_key = get_env("NCBI_API_KEY", "").strip()
        if _ncbi_key:
            params["api_key"] = _ncbi_key
        if email:
            params["email"] = email
        response = httpx.get(
            "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/",
            params=params, timeout=30,
        )
        response.raise_for_status()
        return response.json()

    return await asyncio.to_thread(_run)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_citation_metrics(pmids: str) -> Dict:
    """Get citation metrics (counts, RCR) for PMIDs via NIH iCite.

    Args:
        pmids: One or more comma-separated PubMed IDs (e.g., '38909984,38308006').
    Returns:
        Dictionary with a 'data' list of per-PMID citation metrics.
    """

    def _run() -> Dict:
        response = httpx.get(
            "https://icite.od.nih.gov/api/pubs", params={"pmids": pmids}, timeout=30
        )
        response.raise_for_status()
        return response.json()

    return await asyncio.to_thread(_run)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_citing_articles(doi: str, limit: int = 50) -> List[Dict]:
    """List papers that cite a DOI, using the OpenCitations Index (citation graph).

    Args:
        doi: The cited DOI (e.g., '10.1038/s41586-021-03534-y').
        limit: Maximum number of citing records to return (default: 50).
    Returns:
        List of citation records, each with 'citing' and 'cited' identifiers.
    """

    def _run() -> List[Dict]:
        response = httpx.get(
            f"https://api.opencitations.net/index/v2/citations/doi:{doi}",
            timeout=45, follow_redirects=True,
        )
        response.raise_for_status()
        data = response.json() or []
        return data[: max(limit, 1)]

    return await asyncio.to_thread(_run)


@mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": True})
async def download_plos(paper_id: str, save_path: str = "./downloads") -> str:
    """Download a PDF from PLOS.

    Args:
        paper_id: plos identifier as returned by search_plos.
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        Path to the downloaded PDF. Raises with an explicit reason when the
        record carries no PDF (figshare/DataCite/WHO IRIS are not PDF-only).
    """
    return await asyncio.to_thread(plos_searcher.download_pdf, paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def read_plos_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read and extract text from a PLOS PDF.

    Args:
        paper_id: plos identifier as returned by search_plos.
        save_path: Directory where the PDF is/will be saved.
    Returns:
        Extracted text content.
    """
    return await asyncio.to_thread(plos_searcher.read_paper, paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": True})
async def download_jstage(paper_id: str, save_path: str = "./downloads") -> str:
    """Download a PDF from J-STAGE.

    Args:
        paper_id: jstage identifier as returned by search_jstage.
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        Path to the downloaded PDF. Raises with an explicit reason when the
        record carries no PDF (figshare/DataCite/WHO IRIS are not PDF-only).
    """
    return await asyncio.to_thread(jstage_searcher.download_pdf, paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def read_jstage_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read and extract text from a J-STAGE PDF.

    Args:
        paper_id: jstage identifier as returned by search_jstage.
        save_path: Directory where the PDF is/will be saved.
    Returns:
        Extracted text content.
    """
    return await asyncio.to_thread(jstage_searcher.read_paper, paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": True})
async def download_figshare(paper_id: str, save_path: str = "./downloads") -> str:
    """Download a PDF from figshare.

    Args:
        paper_id: figshare identifier as returned by search_figshare.
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        Path to the downloaded PDF. Raises with an explicit reason when the
        record carries no PDF (figshare/DataCite/WHO IRIS are not PDF-only).
    """
    return await asyncio.to_thread(figshare_searcher.download_pdf, paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def read_figshare_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read and extract text from a figshare PDF.

    Args:
        paper_id: figshare identifier as returned by search_figshare.
        save_path: Directory where the PDF is/will be saved.
    Returns:
        Extracted text content.
    """
    return await asyncio.to_thread(figshare_searcher.read_paper, paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": True})
async def download_datacite(paper_id: str, save_path: str = "./downloads") -> str:
    """Download a PDF from DataCite.

    Args:
        paper_id: datacite identifier as returned by search_datacite.
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        Path to the downloaded PDF. Raises with an explicit reason when the
        record carries no PDF (figshare/DataCite/WHO IRIS are not PDF-only).
    """
    return await asyncio.to_thread(datacite_searcher.download_pdf, paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def read_datacite_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read and extract text from a DataCite PDF.

    Args:
        paper_id: datacite identifier as returned by search_datacite.
        save_path: Directory where the PDF is/will be saved.
    Returns:
        Extracted text content.
    """
    return await asyncio.to_thread(datacite_searcher.read_paper, paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": True})
async def download_whoris(paper_id: str, save_path: str = "./downloads") -> str:
    """Download a PDF from WHO IRIS.

    Args:
        paper_id: whoris identifier as returned by search_whoris.
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        Path to the downloaded PDF. Raises with an explicit reason when the
        record carries no PDF (figshare/DataCite/WHO IRIS are not PDF-only).
    """
    return await asyncio.to_thread(whoris_searcher.download_pdf, paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def read_whoris_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read and extract text from a WHO IRIS PDF.

    Args:
        paper_id: whoris identifier as returned by search_whoris.
        save_path: Directory where the PDF is/will be saved.
    Returns:
        Extracted text content.
    """
    return await asyncio.to_thread(whoris_searcher.read_paper, paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_osf(query: str, max_results: int = 10) -> List[Dict]:
    """Search OSF Preprints (SocArXiv, PsyArXiv, EdArXiv, MetaArXiv...) via SHARE.

    Results are filtered so every query term appears in the title, abstract or
    tags, because SHARE ranks with OR semantics.

    Args:
        query: Search query string (e.g., 'CRISPR base editing').
        max_results: Maximum number of preprints to return (default: 10).
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(osf_searcher, query, max_results)
    return papers if papers else []


@mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": True})
async def download_osf(paper_id: str, save_path: str = "./downloads") -> str:
    """Download a preprint file from OSF (https://osf.io/<guid>/download).

    Args:
        paper_id: OSF guid, DOI (10.31219/osf.io/<guid>) or OSF URL.
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        Path to the downloaded PDF.
    """
    return await asyncio.to_thread(osf_searcher.download_pdf, paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def read_osf_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read and extract text from an OSF preprint PDF.

    Args:
        paper_id: OSF guid, DOI (10.31219/osf.io/<guid>) or OSF URL.
        save_path: Directory where the PDF is/will be saved.
    Returns:
        Extracted text content.
    """
    return await asyncio.to_thread(osf_searcher.read_paper, paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_annotations(article_ids: str, annotation_type: str = "") -> List[Dict]:
    """Fetch Europe PMC text-mined annotations for specific articles.

    Args:
        article_ids: Comma-separated NCBI-prefixed IDs, e.g. 'PMC:3890998,MED:38909984'.
            The 'PMC:'/'MED:' prefix is REQUIRED (a bare ID returns HTTP 400).
        annotation_type: Optional filter, e.g. 'Gene_Proteins', 'Diseases',
            'Chemicals', 'Organisms', 'Gene_Ontology'.
    Returns:
        List of annotation records returned by the Europe PMC annotations API.
    """

    def _run() -> List[Dict]:
        params = {"articleIds": article_ids, "format": "JSON"}
        if annotation_type:
            params["type"] = annotation_type
        response = httpx.get(
            "https://www.ebi.ac.uk/europepmc/annotations_api/annotationsByArticleIds",
            params=params, timeout=45, follow_redirects=True,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else [data]

    return await asyncio.to_thread(_run)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def plan_search_query(query: str, domain: str = "") -> Dict[str, Any]:
    """Plan a search: query variants, free MeSH expansion and source routing.

    Tier 4/5 (paper-search-mcp-patches). Run this before a broad sweep to see
    which query forms and which sources are most likely to answer a topic, then
    call search_papers with sources="auto" and expand=True to apply it.

    Args:
        query: The topic to plan for (e.g. 'CRISPR base editing in mice').
        domain: Optional domain override, e.g. 'biomedical', 'cryptography',
            'preprints', 'datasets_software', 'policy_public_health'.
    Returns:
        Query variants (phrase -> all-terms -> morphological -> raw), MeSH terms,
        the detected domain, recommended sources and a rationale.
    """

    def _run() -> Dict[str, Any]:
        variants = query_variants(query)
        mesh = mesh_terms(query)
        routing = route_sources(
            query,
            domain=domain or None,
            all_sources=ALL_SOURCES,
            retired_sources=sorted(RETIRED_SOURCES),
        )
        return {
            "query": query,
            "query_variants": variants,
            "mesh_terms": mesh,
            "domain": routing["domain"],
            "recommended_sources": routing["sources"],
            "rationale": routing["rationale"],
            "hint": (
                "search_papers(sources='auto', expand=True) applies this routing "
                "and unions the expanded queries."
            ),
        }

    return await asyncio.to_thread(_run)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def check_retraction(doi: str, title: str = "") -> Dict[str, Any]:
    """Check whether a DOI has been retracted (free: OpenAlex + Crossref).

    Tier 6 (paper-search-mcp-patches). ``is_retracted`` stays False unless a
    source positively says otherwise, and every failed lookup appears in
    ``sources_unavailable`` so a transport failure is never read as a clean
    record.

    Args:
        doi: DOI in any form ('10.1038/...', 'https://doi.org/10.1038/...',
            'doi:10.1038/...').
        title: Optional title, used to search Crossref retraction notices.
    Returns:
        Retraction verdict with per-source evidence and notice records.
    """
    return await asyncio.to_thread(_check_retraction_impl, doi, title)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_related_articles(pmid: str, max_results: int = 10) -> Dict[str, Any]:
    """Find PubMed articles related to a PMID (NCBI elink, free).

    Combines PubMed's "similar articles" and citation relationships -- the fastest
    way to expand from one known paper to its whole neighbourhood. Uses your NCBI
    API key (10 req/s instead of 3).

    Args:
        pmid: PubMed ID, e.g. '38909984'.
        max_results: Maximum related PMIDs to return (default: 10).
    Returns:
        Dictionary with 'related_pmids', 'total_related' and the 'link_sets' that
        produced them.
    """

    def _run() -> Dict[str, Any]:
        params = {
            "dbfrom": "pubmed",
            "db": "pubmed",
            "id": str(pmid).strip(),
            "retmode": "json",
            "cmd": "neighbor_score",
            **ncbi_eutils_params(),
        }
        response = httpx.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi",
            params=params, timeout=30, follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()

        related: List[str] = []
        link_sets: List[str] = []
        for linkset in payload.get("linksets") or []:
            for linksetdb in (linkset or {}).get("linksetdbs") or []:
                raw_links = (linksetdb or {}).get("links") or []
                # elink returns [{"id": "38909984", "score": 123}] per link set.
                ids = [
                    str(link.get("id") if isinstance(link, dict) else link)
                    for link in raw_links
                    if (link.get("id") if isinstance(link, dict) else link)
                ]
                if ids:
                    link_sets.append(
                        f"{(linksetdb or {}).get('linkname', '?')} ({len(ids)})"
                    )
                    related.extend(ids)
        deduped = list(dict.fromkeys(related))
        return {
            "pmid": str(pmid).strip(),
            "related_pmids": deduped[:max_results],
            "total_related": len(deduped),
            "link_sets": link_sets,
        }

    return await asyncio.to_thread(_run)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_mesh_details(term: str) -> Dict[str, Any]:
    """Resolve a term to MeSH descriptors and synonyms (free, NCBI key aware).

    Entry-term aware, so lay phrasing resolves correctly
    (e.g. 'heart attack' -> Myocardial Infarction).

    Args:
        term: Term to resolve, e.g. 'heart attack', 'gene therapy'.
    Returns:
        Dictionary with 'descriptors', each carrying label, mesh_ui, synonyms and
        scope note.
    """

    def _run() -> Dict[str, Any]:
        search = httpx.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={"db": "mesh", "term": term, "retmax": 5, "retmode": "json",
                    **ncbi_eutils_params()},
            timeout=30, follow_redirects=True,
        )
        search.raise_for_status()
        ids = ((search.json().get("esearchresult") or {}).get("idlist")) or []
        if not ids:
            return {"query": term, "descriptors": []}

        summary = httpx.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
            params={"db": "mesh", "id": ",".join(ids), "retmode": "json",
                    **ncbi_eutils_params()},
            timeout=30, follow_redirects=True,
        )
        summary.raise_for_status()
        result = summary.json().get("result") or {}

        descriptors: List[Dict[str, Any]] = []
        for uid in ids:
            record = result.get(str(uid)) or {}
            if not isinstance(record, dict):
                continue
            # Skip qualifiers/subheadings (recordtype "qualifier" / MeSH UI "Q..."):
            # their ds_meshterms are entry terms of a subheading, not descriptors.
            # Measured, "screening" otherwise returned the subheading "diagnosis"
            # (Q000175) presented as a descriptor -- copying it into a search
            # strategy is wrong, because a subheading is not a MeSH descriptor.
            if str(record.get("ds_recordtype", "")).lower() == "qualifier":
                continue
            if str(record.get("ds_meshui", "")).upper().startswith("Q"):
                continue
            mesh_terms = record.get("ds_meshterms") or []
            if not mesh_terms:
                continue
            descriptors.append({
                "label": mesh_terms[0],
                "synonyms": mesh_terms[1:],
                "mesh_ui": record.get("ds_meshui", ""),
                "scope_note": record.get("ds_scopenote", ""),
                "year_introduced": record.get("ds_yearintroduced", ""),
            })
        return {"query": term, "descriptors": descriptors}

    return await asyncio.to_thread(_run)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_clinicaltrials(
    query: str,
    max_results: int = 10,
    status: str = "",
    study_type: str = "",
    phase: str = "",
) -> List[Dict]:
    """Search ClinicalTrials.gov registered studies (free, no API key).

    Trial registries are a required part of systematic-review searching (PRISMA),
    because registry records carry protocol detail, phase and status that journal
    indexes do not, and they surface studies whose results were never published.

    Args:
        query: Free-text query (intervention, condition, sponsor or NCT id).
        max_results: Maximum studies to return (default: 10).
        status: Optional overall status filter, e.g. 'RECRUITING', 'COMPLETED'.
        study_type: Optional 'INTERVENTIONAL' or 'OBSERVATIONAL'.
        phase: Optional phase filter, e.g. 'PHASE3'.
    Returns:
        Study records in the shared paper schema; ``extra`` carries the NCT id,
        status, phases, enrollment, conditions and whether results exist.
    """
    papers = await async_search(
        clinicaltrials_searcher, query, max_results,
        status=status, study_type=study_type, phase=phase,
    )
    return papers if papers else []


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_bookshelf(query: str, max_results: int = 10) -> List[Dict]:
    """Search NCBI Bookshelf: books, reports, guidelines and textbook chapters.

    Bookshelf carries full-text reference literature that no journal index holds
    (GeneReviews, StatPearls, NCI PDQ summaries, WHO/NCBI reports, methods
    monographs). Uses your NCBI API key. In-book tables/figures are filtered out.

    Args:
        query: Free-text query; PubMed-style field tags work, e.g.
            'base editing[Title]'.
        max_results: Maximum documents to return (default: 10).
    Returns:
        Documents in the shared paper schema; ``extra`` carries record_type,
        book_title, publisher and the Bookshelf accessions.
    """
    papers = await async_search(bookshelf_searcher, query, max_results)
    return papers if papers else []


@mcp.tool()
async def bookshelf_locate_table(query: str, max_results: int = 10) -> List[Dict]:
    """Locate a specific table or figure inside an NCBI Bookshelf book.

    Use this when a write-up must cite a particular table -- for example the
    repeat-size thresholds in a GeneReviews table -- rather than the chapter as a
    whole.  search_bookshelf deliberately filters tables/figures out as discovery
    noise, so they are unreachable through it.

    Each result carries the table's exact title, its book and chapter accessions
    and the precise Bookshelf URL for that table.

    Limitation (measured): NCBI answers automated requests for Bookshelf HTML
    with a reCAPTCHA challenge page (HTTP 200 plus a challenge), so the table's
    *contents* cannot be retrieved programmatically.  The citation is exact; the
    row data must be read in a browser or sourced to the primary literature.

    Args:
        query: Terms identifying the table, e.g. 'Table 1 spinocerebellar ataxia'.
        max_results: Maximum records to return (default: 10).
    Returns:
        Table/figure records; ``extra`` carries record_type, book_accession,
        chapter_accession, full_text_available and full_text_note.
    """
    try:
        papers = await asyncio.to_thread(
            bookshelf_searcher.search_floats, query, max_results
        )
    except SourceUnavailable as exc:
        return [exc.to_dict()]
    return papers if papers else []


@mcp.tool()
async def search_springer(query: str, max_results: int = 10) -> List[Dict]:
    """Search Springer Nature via the official Meta API.

    Requires SPRINGER_NATURE_API_KEY (free key from dev.springernature.com).
    Search covers all Springer Nature content: journals, books and chapters.
    Free plan limits, enforced by the connector: **500 hits/day, 100 hits/min** —
    when the quota is exhausted the tool reports it rather than returning nothing.
    Use keyed_source_status() to see the remaining allowance.

    Args:
        query: Keyword query (e.g., 'CRISPR base editing').
        max_results: Maximum records to return (default: 10, max 100).
    Returns:
        List of paper metadata in dictionary format.
    """
    if springer_searcher is None:
        return [{
            "error": "unavailable",
            "source": "springer",
            "message": "Springer Nature is not configured: set "
                       "SPRINGER_NATURE_API_KEY in ~/.config/paper-search-mcp/.env",
        }]
    return await async_search(springer_searcher, query, max_results)


@mcp.tool()
async def search_elsevier(query: str, max_results: int = 10) -> List[Dict]:
    """Search Elsevier's Scopus index (free API key).

    Requires ELSEVIER_API_KEY (free key from dev.elsevier.com). A free key covers
    **search and abstracts only** — retrieving full text of subscribed articles
    needs an institutional entitlement token (ELSEVIER_INSTTOKEN); see
    keyed_source_status(). Scopus adds conference proceedings and non-OA journal
    coverage that OpenAlex/Crossref handle thinly.

    Args:
        query: Keyword query (e.g., 'CRISPR base editing').
        max_results: Maximum records to return (default: 10, max 25).
    Returns:
        List of paper metadata in dictionary format.
    """
    if elsevier_searcher is None:
        return [{
            "error": "unavailable",
            "source": "elsevier",
            "message": "Elsevier is not configured: set ELSEVIER_API_KEY in "
                       "~/.config/paper-search-mcp/.env",
        }]
    return await async_search(elsevier_searcher, query, max_results)


@mcp.tool()
async def read_springer_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read the full text of a Springer Nature open-access article.

    Pass the article DOI. Text comes from the Open Access API's JATS output, so no
    PDF parsing and no bot wall are involved. A non-open-access article raises
    rather than returning an empty document.

    Args:
        paper_id: Article DOI (e.g. '10.1038/s41586-020-2649-2').
        save_path: Unused; the API returns XML directly.
    Returns:
        str: The article's body text.
    """
    if springer_searcher is None:
        raise RuntimeError(
            "Springer Nature is not configured: set SPRINGER_NATURE_API_KEY"
        )
    return await asyncio.to_thread(springer_searcher.read_paper, paper_id, save_path)


@mcp.tool()
async def keyed_source_status() -> Dict:
    """Preflight for the keyed publisher sources: what does each key permit?

    Returns Springer Nature's remaining daily allowance and Elsevier's access
    report (whether the key works and whether an entitlement token is present).
    Use this before a big sweep, and to explain why a keyed source returns little.
    """
    status: Dict[str, Any] = {}
    if springer_searcher is not None:
        status["springer"] = springer_searcher.quota_status()
    else:
        status["springer"] = {
            "configured": False,
            "message": "set SPRINGER_NATURE_API_KEY to enable",
        }

    if elsevier_searcher is not None:
        status["elsevier"] = await asyncio.to_thread(elsevier_searcher.check_access)
    else:
        status["elsevier"] = {
            "configured": False,
            "message": "set ELSEVIER_API_KEY to enable",
        }
    return status


@mcp.tool()
async def export_citations(dois: str, format: str = "bibtex",
                           check_retractions: bool = True) -> Dict:
    """Export DOI-verified citations in BibTeX, RIS or plain text.

    Use this to build a reference list from results you intend to cite. Each DOI
    is resolved at Crossref -- the registration agency -- so authors, journal,
    year, volume and pages come from the authoritative record rather than a
    search summary. Every entry is also checked for retraction (OpenAlex
    ``is_retracted`` plus Crossref notices): retracted works are marked
    ``[RETRACTED]`` / ``note = {RETRACTED}`` and listed in ``retracted``, because
    citing a retracted paper silently is the most damaging citation error there is.

    Args:
        dois: One or more DOIs, separated by commas/spaces/semicolons.
        format: 'bibtex' (default), 'ris', or 'text'.
        check_retractions: Check each DOI for retraction (default True).
    Returns:
        Dict with ``citations`` (the rendered string), ``entries`` (per-DOI
        metadata incl. ``cite_key`` and ``retracted``), ``retracted``,
        ``retraction_unverified`` and ``unavailable`` -- DOIs that could not be
        resolved are reported, never silently dropped.
    """
    try:
        return await asyncio.to_thread(
            _format_citations_impl, dois, format, check_retractions
        )
    except ValueError as exc:
        return {"error": "invalid_request", "message": str(exc)}


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_ictrp(query: str, max_results: int = 10) -> List[Dict]:
    """Search the WHO ICTRP aggregator across ~20 trial registries (free).

    ICTRP is the WHO's international trial-registry platform and covers
    ClinicalTrials.gov, ISRCTN, ChiCTR, CTRI, JPRN, DRKS, ANZCTR and more behind
    one search -- the cross-registry sweep a systematic review needs.

    Args:
        query: Query; explicit operators work best (e.g. 'malaria AND treatment').
            A multi-term query is ANDed and progressively relaxed internally.
        max_results: Maximum trials to return (default: 10).
    Returns:
        Trial records in the shared paper schema; ``extra`` carries the trial_id,
        registry name, recruitment status and registration date.
    """
    papers = await async_search(ictrp_searcher, query, max_results)
    return papers if papers else []


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_ctis(
    query: str,
    max_results: int = 10,
    status: str = "",
    medical_condition: str = "",
    sponsor: str = "",
    product_name: str = "",
    trial_phase: str = "",
) -> List[Dict]:
    """Search EU CTIS, the mandatory EU/EEA trial registry since 2022 (free).

    Complements ClinicalTrials.gov and WHO ICTRP with EU-specific trials; the
    record carries the CT number, status, conditions and trial region.

    Args:
        query: Free text (title, product, condition or sponsor).
        max_results: Maximum trials to return (default: 10).
        status: Optional status filter, e.g. 'AUTHORISED', 'ONGOING'.
        medical_condition: Optional condition filter.
        sponsor: Optional sponsor filter.
        product_name: Optional investigational-product filter.
        trial_phase: Optional phase filter, e.g. 'PHASE3'.
    Returns:
        Trial records in the shared paper schema.
    """
    papers = await async_search(
        ctis_searcher, query, max_results,
        status=status, medical_condition=medical_condition, sponsor=sponsor,
        product_name=product_name, trial_phase=trial_phase,
    )
    return papers if papers else []


# MCP tools belonging to retired sources; unregistered at import time so a
# client can never call them.
RETIRED_TOOL_NAMES = (
    "search_google_scholar",
    "search_dblp", "read_dblp_paper", "download_dblp",
    "search_base", "read_base_paper", "download_base",
    "search_citeseerx", "read_citeseerx_paper", "download_citeseerx",
)


def _unregister_retired_tools() -> None:
    """Drop MCP tools for retired sources (idempotent, never fatal)."""
    for _tool_name in RETIRED_TOOL_NAMES:
        try:
            mcp.remove_tool(_tool_name)
        except Exception:
            continue


_unregister_retired_tools()


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
