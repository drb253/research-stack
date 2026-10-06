"""MCP Server for Multi-Provider Academic Search.

Exposes tools for regex-powered literature search, author lookup,
and multi-criteria filtering across multiple providers
(Semantic Scholar, Crossref, OpenAlex, PubMed).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastmcp import FastMCP
from fastmcp import Context as MCPContext

from . import api
from .models import FilterConfig, apply_filters, apply_regex_filter
from .names import author_match_diagnostic, filter_by_author
from .providers import get_provider, list_providers
from .quality import (
    filter_usable_records,
    quality_summary,
    rank_by_relevance,
)

logger = logging.getLogger(__name__)

mcp = FastMCP("academic-search")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _actual_query(prov: Any, query: str, search_type: str) -> str:
    """Return the query string the provider will actually act on.

    For Semantic Scholar a DOI is resolved directly against the
    ``/paper/DOI:`` endpoint instead of being searched as keywords, so
    reporting the keyword transformation of a DOI is misleading --
    ``build_extended_query("10.1126/science.add8643")`` yields
    ``"science. add"``, which is not what was used.
    """
    normalizer = getattr(prov, "normalize_identifier", None)
    if callable(normalizer):
        normalized = normalizer(query)
        if normalized.startswith("DOI:"):
            return normalized
    return api.build_extended_query(query, search_type)


def _split_csv(value: Optional[str]) -> Optional[list[str]]:
    """Split a comma-separated string into a trimmed list, or return None."""
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts if parts else None


def _build_filter_config(
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    open_access_only: bool = False,
    has_pdf: Optional[bool] = None,
    journal: Optional[str] = None,
    exclude_journals: Optional[str] = None,
    publication_types: Optional[str] = None,
    exclude_publication_types: Optional[str] = None,
    author: Optional[str] = None,
    min_citation_count: Optional[int] = None,
    max_citation_count: Optional[int] = None,
    has_abstract: Optional[bool] = None,
) -> FilterConfig:
    """Build a FilterConfig from MCP tool parameters."""
    return FilterConfig(
        year_min=year_min,
        year_max=year_max,
        open_access_only=open_access_only,
        has_pdf=has_pdf,
        journal=journal,
        exclude_journals=_split_csv(exclude_journals),
        publication_types=_split_csv(publication_types),
        exclude_publication_types=_split_csv(exclude_publication_types),
        author=author,
        min_citation_count=min_citation_count,
        max_citation_count=max_citation_count,
        has_abstract=has_abstract,
    )


def _filters_dict(
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    open_access_only: bool = False,
    has_pdf: Optional[bool] = None,
    journal: Optional[str] = None,
    exclude_journals: Optional[str] = None,
    publication_types: Optional[str] = None,
    exclude_publication_types: Optional[str] = None,
    author: Optional[str] = None,
    min_citation_count: Optional[int] = None,
    max_citation_count: Optional[int] = None,
    has_abstract: Optional[bool] = None,
) -> dict[str, Any]:
    """Build the filters_applied metadata dict."""
    return {
        "year_min": year_min,
        "year_max": year_max,
        "open_access_only": open_access_only,
        "has_pdf": has_pdf,
        "journal": journal,
        "exclude_journals": _split_csv(exclude_journals),
        "publication_types": _split_csv(publication_types),
        "exclude_publication_types": _split_csv(exclude_publication_types),
        "author": author,
        "min_citation_count": min_citation_count,
        "max_citation_count": max_citation_count,
        "has_abstract": has_abstract,
    }


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def build_extended_query(
    query: str,
    search_type: str = "limited",
    provider: str = "semantic_scholar",
    ctx: MCPContext | None = None,
) -> dict[str, str]:
    """Preview how a regex query is transformed for a given provider's API.

    Args:
        query: A regex pattern.
        search_type:
            - ``"limited"``: terms joined with AND (space-separated).
            - ``"extended"``: terms joined with OR (space-separated
              for Semantic Scholar which lacks native OR support).
        provider: The API provider to preview the query for
            (``"semantic_scholar"``, ``"crossref"``, ``"openalex"``,
            ``"pubmed"``).  Default: ``"semantic_scholar"``.

    Returns:
        A dict with the original query, the transformed query, and the
        search type.
    """
    prov = get_provider(provider)
    # For Semantic Scholar we use the regex-aware transformation;
    # for other providers the "extended" query is just the raw query.
    if provider == "semantic_scholar":
        extended = api.build_extended_query(query, search_type)
    else:
        extended = query

    return {
        "original_query": query,
        "extended_query": extended,
        "search_type": search_type,
        "provider": provider,
    }


@mcp.tool()
def search_papers(
    query: str,
    search_type: str = "limited",
    fields: str = api.DEFAULT_FIELDS,
    max_retrieval: int = 10_000,
    regex_filter: Optional[str] = None,
    regex_search_fields: str = "title,abstract",
    match_mode: str = "any",
    limit: int = 50,
    provider: str = "semantic_scholar",
    min_relevance: Optional[float] = None,
    exclude_incomplete: bool = True,
    rank_by_score: bool = True,
    allow_initial_match: bool = True,
    allow_surname_only: bool = True,
    ctx: MCPContext | None = None,
    # --- Post-hoc filter parameters ---
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    open_access_only: bool = False,
    has_pdf: Optional[bool] = None,
    journal: Optional[str] = None,
    exclude_journals: Optional[str] = None,
    publication_types: Optional[str] = None,
    exclude_publication_types: Optional[str] = None,
    author: Optional[str] = None,
    min_citation_count: Optional[int] = None,
    max_citation_count: Optional[int] = None,
    has_abstract: Optional[bool] = None,
) -> dict[str, Any]:
    """Search for papers with regex filtering and optional post-hoc filters.

    Supports multiple providers: Semantic Scholar (default), Crossref,
    OpenAlex, and PubMed.

    When using Semantic Scholar as the provider and the query is a DOI
    (e.g. ``"10.1037/a0028860"``), the paper is fetched directly by DOI
    rather than via keyword search.  This is useful when you already
    know the paper's identifier.

    Args:
        query: Search query sent to the API provider.  For Semantic
            Scholar, a bare DOI (like ``"10.1037/a0028860"``) triggers
            direct DOI lookup.
        search_type:
            - ``"limited"`` (AND) or ``"extended"`` (OR) for the API query.
        fields: Comma-separated Semantic Scholar field names (SS only).
        max_retrieval: Max papers to fetch from the API.
        regex_filter: Optional regex pattern for post-filtering results
            across *all* providers.  When provided, only papers whose
            ``regex_search_fields`` match the pattern are returned.
        regex_search_fields: Comma-separated field names to apply regex
            against (default: ``"title,abstract"``).
        match_mode:
            - ``"any"``: paper kept if *any* regex field matches (OR).
            - ``"all"``: paper kept only if *all* regex fields match (AND).
        limit: Max number of papers to return in the response.
        provider: API provider to use.  Options:
            ``"semantic_scholar"``, ``"crossref"``, ``"openalex"``,
            ``"pubmed"``.  Default: ``"semantic_scholar"``.
        min_relevance: Fraction (0.0-1.0) of the query's terms a record must
            contain.  ``None`` (default) applies ``1.0`` for the Crossref
            provider -- which has no semantic ranking and otherwise returns
            loose term-overlap matches such as "denture base" for the query
            "base editing" -- and ``0.0`` (disabled) for every other
            provider.
        exclude_incomplete: Drop records with no year, authors, abstract,
            identifier and citations (default ``True``).  The dropped count
            is reported as ``total_dropped_incomplete``.
        rank_by_score: Order results by query-term overlap, then metadata
            completeness, then citations (default ``True``).
        allow_initial_match: Allow ``J. Doudna`` to satisfy the author filter
            ``"Jennifer Doudna"`` (default ``True``).  Set ``False`` to
            require an exact given-name match.
        allow_surname_only: Allow a surname-only author filter
            (``"Doudna"``) to match any given-name rendering.

        **Post-hoc filter parameters:**
        year_min: Minimum publication year (inclusive).
        year_max: Maximum publication year (inclusive).
        open_access_only: Only return open-access papers.
        has_pdf: ``True`` = only papers with a PDF link; ``False`` = only
            without; ``None`` = no filter.
        journal: Case-insensitive substring match on journal name.
        exclude_journals: Comma-separated journal names to exclude.
        publication_types: Comma-separated publication types to include
            (e.g. ``"JournalArticle,Review"``).
        exclude_publication_types: Comma-separated publication types to
            exclude (e.g. ``"Conference"``).
        author: Case-insensitive substring match on any author name.
        min_citation_count: Minimum citation count (inclusive).
        max_citation_count: Maximum citation count (inclusive).
        has_abstract: ``True`` = only papers with an abstract; ``False``
            = only without; ``None`` = no filter.

    Returns:
        A dict with metadata (query, counts, filter info) and the
        ``papers`` list.
    """
    prov = get_provider(provider)
    filters = _build_filter_config(
        year_min=year_min,
        year_max=year_max,
        open_access_only=open_access_only,
        has_pdf=has_pdf,
        journal=journal,
        exclude_journals=exclude_journals,
        publication_types=publication_types,
        exclude_publication_types=exclude_publication_types,
        author=author,
        min_citation_count=min_citation_count,
        max_citation_count=max_citation_count,
        has_abstract=has_abstract,
    )

    # Build progress callback from context (if available)
    def _report_progress(current: int, total: int, msg: str) -> None:
        if ctx is not None:
            ctx.report_progress(current, total, msg)

    # A relevance gate only helps where the provider cannot rank semantically;
    # Crossref is the provider that needs it.
    if min_relevance is None:
        effective_min_relevance = 1.0 if provider == "crossref" else 0.0
    else:
        effective_min_relevance = min_relevance

    # Build the extended query (only relevant for Semantic Scholar)
    if provider == "semantic_scholar":
        extended_query = _actual_query(prov, query, search_type)
        papers, meta = prov.search(
            query=query,
            max_retrieval=max_retrieval,
            limit=limit,
            fields=fields,
            search_type=search_type,
            filters=filters,
            progress_callback=_report_progress,
        )
    else:
        extended_query = query
        search_kwargs: dict[str, Any] = {
            "query": query,
            "max_retrieval": max_retrieval,
            "limit": limit,
            "filters": filters,
            "progress_callback": _report_progress,
        }
        if provider == "crossref":
            search_kwargs["min_relevance"] = effective_min_relevance
        papers, meta = prov.search(**search_kwargs)

    # Apply regex post-filtering (all providers, when regex_filter is set)
    if regex_filter:
        rsf = [f.strip() for f in regex_search_fields.split(",")]
        papers = apply_regex_filter(papers, regex_filter, fields=rsf, match_mode=match_mode)
        meta["total_after_regex"] = len(papers)
    else:
        meta.setdefault("total_after_regex", len(papers))

    # Apply the author filter with part-aware name matching, so that
    # "Jennifer Doudna" also matches "Jennifer A. Doudna" and "J. Doudna".
    matched_author_names: list[str] = []
    if author:
        papers, matched_author_names = filter_by_author(
            papers,
            author,
            allow_initial_match=allow_initial_match,
            allow_surname_only=allow_surname_only,
        )

    # Drop records carrying essentially no metadata: they used to be returned
    # verbatim and could sit at the top of the result list.
    dropped_incomplete = 0
    if exclude_incomplete:
        papers, dropped_incomplete = filter_usable_records(papers)
        meta["total_dropped_incomplete"] = dropped_incomplete
    if rank_by_score:
        papers = rank_by_relevance(papers, query)
    papers = papers[:limit]

    # Some provider/filter combinations cannot work and used to fail silently
    # by returning an empty list. Say so instead of looking like "no results".
    filter_notes: list[str] = []
    if provider == "crossref" and open_access_only:
        filter_notes.append(
            "The Crossref API does not expose open-access status "
            "(isOpenAccess is always false for this provider), so "
            "open_access_only=True removes every result. Use provider="
            "'semantic_scholar' or 'openalex' for open-access filtering."
        )
    dropped_irrelevant = meta.get("total_dropped_irrelevant")
    if dropped_irrelevant and meta.get("total_from_api"):
        ratio = dropped_irrelevant / meta["total_from_api"]
        if ratio >= 0.8:
            filter_notes.append(
                f"{dropped_irrelevant} of {meta['total_from_api']} Crossref "
                f"records were removed by the relevance gate "
                f"(min_relevance={meta.get('min_relevance')}). Lower "
                "min_relevance if you expected more results; Crossref's own "
                "ranking puts weak term-overlap matches near the top."
            )

    return {
        "original_query": query,
        "extended_query": extended_query,
        "provider": provider,
        "total_from_api": meta.get("total_from_api", len(papers)),
        "total_after_regex_filter": meta.get("total_after_regex", len(papers)),
        "total_after_filters": meta.get("total_after_filters", len(papers)),
        "total_dropped_incomplete": meta.get("total_dropped_incomplete", 0),
        "returned_count": len(papers),
        "limit": limit,
        "matched_author_names": matched_author_names,
        "quality": quality_summary(
            papers, None if extended_query.startswith("DOI:") else query
        ),
        "filter_notes": filter_notes,
        "filters_applied": _filters_dict(
            year_min=year_min,
            year_max=year_max,
            open_access_only=open_access_only,
            has_pdf=has_pdf,
            journal=journal,
            exclude_journals=exclude_journals,
            publication_types=publication_types,
            exclude_publication_types=exclude_publication_types,
            author=author,
            min_citation_count=min_citation_count,
            max_citation_count=max_citation_count,
            has_abstract=has_abstract,
        ),
        "papers": papers,
    }



@mcp.tool()
def search_by_author(
    author_name: str,
    search_type: str = "limited",
    fields: str = api.DEFAULT_FIELDS,
    max_retrieval: int = 10_000,
    limit: int = 50,
    provider: str = "semantic_scholar",
    allow_initial_match: bool = True,
    allow_surname_only: bool = True,
    exclude_incomplete: bool = True,
    ctx: MCPContext | None = None,
    # --- Post-hoc filter parameters ---
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    open_access_only: bool = False,
    has_pdf: Optional[bool] = None,
    journal: Optional[str] = None,
    exclude_journals: Optional[str] = None,
    publication_types: Optional[str] = None,
    exclude_publication_types: Optional[str] = None,
    min_citation_count: Optional[int] = None,
    max_citation_count: Optional[int] = None,
    has_abstract: Optional[bool] = None,
) -> dict[str, Any]:
    """Search for papers by a specific author name.

    Supports multiple providers: Semantic Scholar (default), Crossref,
    OpenAlex, and PubMed.

    Args:
        author_name: The author's name (e.g. ``"Yoshua Bengio"``).
        search_type:
            - ``"limited"`` (AND) or ``"extended"`` (OR) for the API query.
        fields: Comma-separated Semantic Scholar field names (SS only).
        max_retrieval: Max papers to fetch from the API.
        limit: Max number of papers to return.
        provider: API provider to use.  Options:
            ``"semantic_scholar"``, ``"crossref"``, ``"openalex"``,
            ``"pubmed"``.  Default: ``"semantic_scholar"``.

        **Post-hoc filter parameters:**
        year_min: Minimum publication year (inclusive).
        year_max: Maximum publication year (inclusive).
        open_access_only: Only return open-access papers.
        has_pdf: ``True`` = only papers with a PDF link; ``False`` = only
            without; ``None`` = no filter.
        journal: Case-insensitive substring match on journal name.
        publication_types: Comma-separated publication types to include
            (e.g. ``"JournalArticle,Review"``).
        min_citation_count: Minimum citation count (inclusive).
        max_citation_count: Maximum citation count (inclusive).
        has_abstract: ``True`` = only papers with an abstract; ``False``
            = only without; ``None`` = no filter.

    Returns:
        A dict with metadata and the ``papers`` list.
    """
    prov = get_provider(provider)
    filters = _build_filter_config(
        year_min=year_min,
        year_max=year_max,
        open_access_only=open_access_only,
        has_pdf=has_pdf,
        journal=journal,
        exclude_journals=exclude_journals,
        publication_types=publication_types,
        exclude_publication_types=exclude_publication_types,
        author=None,  # Author filter is handled by search_by_author itself
        min_citation_count=min_citation_count,
        max_citation_count=max_citation_count,
        has_abstract=has_abstract,
    )

    def _report_progress(current: int, total: int, msg: str) -> None:
        if ctx is not None:
            ctx.report_progress(current, total, msg)

    if provider == "semantic_scholar":
        extended_query = api.build_extended_query(author_name, search_type)
        papers, meta = prov.search_by_author(
            author_name=author_name,
            max_retrieval=max_retrieval,
            limit=limit,
            fields=fields,
            search_type=search_type,
            filters=filters,
            allow_initial_match=allow_initial_match,
            allow_surname_only=allow_surname_only,
            progress_callback=_report_progress,
        )
    elif provider == "pubmed":
        # PubMed has native [au] field support
        extended_query = f"{author_name}[au]"
        papers, meta = prov.search_by_author(
            author_name=author_name,
            max_retrieval=max_retrieval,
            limit=limit,
            filters=filters,
            progress_callback=_report_progress,
        )
    else:
        extended_query = author_name
        author_kwargs: dict[str, Any] = {
            "author_name": author_name,
            "max_retrieval": max_retrieval,
            "limit": limit,
            "filters": filters,
            "progress_callback": _report_progress,
        }
        if provider == "crossref":
            author_kwargs["allow_initial_match"] = allow_initial_match
            author_kwargs["allow_surname_only"] = allow_surname_only
        papers, meta = prov.search_by_author(**author_kwargs)

    total_from_api = meta.get("total_from_api", len(papers))
    total_after_author = meta.get("total_after_author_filter", len(papers))

    # Drop records with essentially no metadata before returning them.
    dropped_incomplete = 0
    if exclude_incomplete:
        papers, dropped_incomplete = filter_usable_records(papers)

    # A silent empty list used to read as "this author has no papers"; always
    # say why the search came back empty when the provider had candidates.
    diagnostic = None
    if not papers:
        diagnostic = author_match_diagnostic(
            author_name,
            papers,
            total_from_api,
            candidate_names=meta.get("candidate_name_sample"),
        )

    return {
        "author_name": author_name,
        "provider": provider,
        "extended_query": extended_query,
        "total_from_api": total_from_api,
        "total_after_author_filter": total_after_author,
        "total_after_filters": meta.get("total_after_filters", len(papers)),
        "total_dropped_incomplete": dropped_incomplete,
        "returned_count": len(papers),
        "limit": limit,
        "matched_author_names": meta.get("matched_author_names", []),
        "quality": quality_summary(papers),
        "diagnostic": diagnostic,
        "filters_applied": _filters_dict(
            year_min=year_min,
            year_max=year_max,
            open_access_only=open_access_only,
            has_pdf=has_pdf,
            journal=journal,
            exclude_journals=exclude_journals,
            publication_types=publication_types,
            exclude_publication_types=exclude_publication_types,
            min_citation_count=min_citation_count,
            max_citation_count=max_citation_count,
            has_abstract=has_abstract,
        ),
        "papers": papers,
    }



@mcp.tool()
def explore_citations(
    seed_paper_id: str,
    num_steps: int = 30,
    max_depth: Optional[int] = None,
    direction_choice: str = "random",
    bias: str = "random",
    candidates_per_step: int = 100,
    stop_similarity: Optional[float] = None,
    provider: str = "semantic_scholar",
    ctx: MCPContext | None = None,
    # --- Post-hoc filter parameters ---
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    open_access_only: bool = False,
    journal: Optional[str] = None,
    exclude_journals: Optional[str] = None,
    publication_types: Optional[str] = None,
    exclude_publication_types: Optional[str] = None,
    min_citation_count: Optional[int] = None,
    max_citation_count: Optional[int] = None,
    has_abstract: Optional[bool] = None,
) -> dict[str, Any]:
    """Walk the citation graph from a seed paper using a random walk.

    Starting from a seed paper, this tool takes steps through the
    citation graph — following references (backward) or citations
    (forward) — recording edges and backtracking on dead ends.
    Cross-edges to already visited papers are discovered passively.

    Only Semantic Scholar is supported (it has the only public
    citation-graph API among the four providers).

    Args:
        seed_paper_id: Any supported paper identifier.  Accepted forms are a
            Semantic Scholar paper id (40-char SHA), a Semantic Scholar paper
            URL, a DOI in any spelling (``"10.1037/a0028860"``,
            ``"doi:10.1037/..."``, ``"https://doi.org/10.1037/..."``), an
            arXiv id (``"2006.10256"`` or ``"arXiv:2006.10256"``), a PMID
            (``"32939066"`` or ``"PMID:32939066"``) or a ``CorpusId``.  The
            identifier is normalised and resolved internally to a Semantic
            Scholar paper id before the walk starts.
        num_steps: Maximum number of walk steps (default: 30).
        max_depth: Maximum hop distance from seed before forced
            backtrack (``None`` = unlimited, default).
        direction_choice: How to pick direction at each step:
            ``\"random\"`` (default), ``\"forward\"`` (citations),
            ``\"backward\"`` (references), or ``\"alternating\"``.
        bias: How to pick which candidate to visit next:
            ``\"random\"`` (default), ``\"top_cited\"``, ``\"bottom_cited\"``,
            or ``\"most_similar\"`` (most textually similar to seed paper).
        candidates_per_step: Number of candidates to fetch per API
            call (default: 100, max: 1000).
        stop_similarity: If set (0.0–1.0), stop exploring a branch
            when the candidate's text similarity to the seed paper
            falls below this threshold.  Uses TF cosine similarity
            (no external dependencies).
        provider: API provider (only ``\"semantic_scholar\"``).

        **Post-hoc filter parameters** (applied to candidates at
        each step):
        year_min: Minimum publication year (inclusive).
        year_max: Maximum publication year (inclusive).
        open_access_only: Only follow open-access papers.
        journal: Case-insensitive substring match on journal name.
        exclude_journals: Comma-separated journal names to exclude.
        publication_types: Comma-separated publication types to include.
        exclude_publication_types: Comma-separated publication types
            to exclude.
        min_citation_count: Minimum citation count (inclusive).
        max_citation_count: Maximum citation count (inclusive).
        has_abstract: ``True`` = only papers with an abstract; ``False``
            = only without; ``None`` = no filter.

    Returns:
        A dict with ``seed_paper_id``, ``papers`` (dict of paperId ->
        metadata), ``edges`` (list of ``{source, target, type}``),
        ``path`` (list of paperIds in visit order), and ``stats``
        (steps_completed, unique_papers_visited, backtracks,
        dead_ends, cross_edges_found, pruned_by_filters,
        api_calls_made).
    """
    if provider != "semantic_scholar":
        raise ValueError(
            "Citation graph exploration is only available for Semantic Scholar. "
            "Other providers lack citation-graph APIs."
        )

    prov = get_provider(provider)
    filters = _build_filter_config(
        year_min=year_min,
        year_max=year_max,
        open_access_only=open_access_only,
        journal=journal,
        exclude_journals=exclude_journals,
        publication_types=publication_types,
        exclude_publication_types=exclude_publication_types,
        min_citation_count=min_citation_count,
        max_citation_count=max_citation_count,
        has_abstract=has_abstract,
    )

    def _report_progress(current: int, total: int, msg: str) -> None:
        if ctx is not None:
            ctx.report_progress(current, total, msg)

    result = prov.explore_citations(
        seed_paper_id=seed_paper_id,
        num_steps=num_steps,
        max_depth=max_depth,
        direction_choice=direction_choice,
        bias=bias,
        candidates_per_step=candidates_per_step,
        stop_similarity=stop_similarity,
        filters=filters if filters.is_active() else None,
        progress_callback=_report_progress,
    )

    result["filters_applied"] = _filters_dict(
        year_min=year_min,
        year_max=year_max,
        open_access_only=open_access_only,
        journal=journal,
        exclude_journals=exclude_journals,
        publication_types=publication_types,
        exclude_publication_types=exclude_publication_types,
        min_citation_count=min_citation_count,
        max_citation_count=max_citation_count,
        has_abstract=has_abstract,
    )
    return result


@mcp.tool()
def get_paper_stats(
    query: str,
    search_type: str = "limited",
    fields: str = api.DEFAULT_FIELDS,
    max_retrieval: int = 10_000,
    provider: str = "semantic_scholar",
    ctx: MCPContext | None = None,
) -> dict[str, Any]:
    """Fetch papers and compute statistics (data availability, authors, years).

    Args:
        query: Search query sent to the API provider.
        search_type:
            - ``"limited"`` (AND) or ``"extended"`` (OR).
        fields: Comma-separated Semantic Scholar field names (SS only).
        max_retrieval: Max papers to fetch from the API.
        provider: API provider to use.  Options:
            ``"semantic_scholar"``, ``"crossref"``, ``"openalex"``,
            ``"pubmed"``.  Default: ``"semantic_scholar"``.

    Returns:
        A dict with ``total_papers``, ``field_availability``, ``authors``,
        and ``publication_year``.
    """
    prov = get_provider(provider)

    def _report_progress(current: int, total: int, msg: str) -> None:
        if ctx is not None:
            ctx.report_progress(current, total, msg)

    if provider == "semantic_scholar":
        extended_query = _actual_query(prov, query, search_type)
        papers, _ = prov.search(
            query=query,
            max_retrieval=max_retrieval,
            limit=max_retrieval,
            fields=fields,
            search_type=search_type,
            progress_callback=_report_progress,
        )
    else:
        extended_query = query
        papers, _ = prov.search(
            query=query,
            max_retrieval=max_retrieval,
            limit=max_retrieval,
            progress_callback=_report_progress,
        )

    # Compute stats using the existing stats module
    from .stats import compute_stats

    result = compute_stats(papers)
    result["original_query"] = query
    result["extended_query"] = extended_query
    result["provider"] = provider
    # Add the completeness view alongside the raw field-availability counts:
    # missing year/authors/abstract is normal on every provider, and a record
    # missing *all* of them is junk rather than merely sparse.
    _, dropped = filter_usable_records(papers)
    result["usable_records"] = len(papers) - dropped
    result["unusable_records"] = dropped
    result["quality"] = quality_summary(papers)
    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the MCP server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    mcp.run()


if __name__ == "__main__":
    main()
