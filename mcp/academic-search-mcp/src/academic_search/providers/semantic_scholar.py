"""Semantic Scholar provider.

Wraps the Semantic Scholar bulk search API
(``graph/v1/paper/search/bulk``) with retry logic, rate limiting, and
regex-based post-filtering.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Optional
from urllib.parse import quote

import requests

from ..models import (
    apply_filters,
    FilterConfig,
    get_paper_text_for_similarity,
    simple_text_similarity,
)
from ..names import filter_by_author, sample_author_names
from .base import BaseProvider, ProgressCallback
from . import register_provider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_FIELDS = (
    "externalIds,authors,title,year,publicationDate,abstract,"
    "publicationTypes,journal,referenceCount,citationCount,"
    "isOpenAccess,openAccessPdf"
)

CITATION_GRAPH_FIELDS = (
    "externalIds,authors,title,year,publicationDate,abstract,"
    "publicationTypes,journal,referenceCount,citationCount,"
    "isOpenAccess,openAccessPdf"
)

API_DELAY = 3.0
MAX_RETRIES = 5


def _api_headers() -> dict[str, str]:
    """Build request headers, adding the Semantic Scholar API key if set.

    Unauthenticated Semantic Scholar traffic shares a small global rate-limit
    pool, which is the cause of the intermittent 429 responses seen during
    citation walks.  Setting ``S2_API_KEY`` in the server environment moves
    requests onto the caller's own quota and makes the flakiness go away.
    """
    headers = {"User-Agent": "academic-search-mcp/0.8.0+local1"}
    api_key = os.environ.get("S2_API_KEY") or os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key.strip()
    return headers



# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


@register_provider("semantic_scholar")
class SemanticScholarProvider(BaseProvider):
    """Provider for the Semantic Scholar bulk search API."""

    provider_name = "semantic_scholar"

    def __init__(self) -> None:
        self.base_url = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
        # Response cache for graph endpoints: (paper_id, direction) -> list of candidate dicts
        self._graph_cache: dict[tuple[str, str], Optional[dict]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        max_retrieval: int = 10_000,
        limit: int = 50,
        fields: str = DEFAULT_FIELDS,
        search_type: str = "limited",
        filters: Optional[FilterConfig] = None,
        progress_callback: ProgressCallback = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Search Semantic Scholar.

        Note: Regex post-filtering is now handled in ``server.py`` so it
        applies uniformly across all providers.

        Returns:
            Tuple of (papers_list, metadata_dict).
        """
        # If the query looks like a DOI, resolve it directly
        if self._is_doi(query):
            doi = self._normalize_doi(query)
            url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{quote(doi)}?fields={fields}"
            time.sleep(API_DELAY)
            data = self._request_with_retry(url)
            papers = [data] if data and data.get("paperId") else []
            extended_query = doi
            meta = {
                "total_from_api": len(papers),
                "total_after_regex": len(papers),
                "total_after_filters": len(papers),
            }
            return papers[:limit], meta

        extended_query = self._build_extended_query(query, search_type)

        # Cap fetch to avoid wasting API calls when limit is small
        if filters and filters.is_active():
            effective_max = min(max_retrieval, max(limit * 5, 500))
        else:
            effective_max = min(max_retrieval, max(limit, 100))

        papers = self._fetch_all(extended_query, fields, effective_max, progress_callback=progress_callback)
        meta = {"total_from_api": len(papers), "total_after_regex": len(papers)}

        if filters and filters.is_active():
            papers = apply_filters(papers, filters)
        meta["total_after_filters"] = len(papers)

        return papers[:limit], meta

    def search_by_author(
        self,
        author_name: str,
        max_retrieval: int = 10_000,
        limit: int = 50,
        fields: str = DEFAULT_FIELDS,
        search_type: str = "limited",
        filters: Optional[FilterConfig] = None,
        allow_initial_match: bool = True,
        allow_surname_only: bool = True,
        progress_callback: ProgressCallback = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Search for papers by a specific author."""
        extended_query = self._build_extended_query(author_name, search_type)

        papers = self._fetch_all(extended_query, fields, max_retrieval, progress_callback=progress_callback)
        meta = {"total_from_api": len(papers)}

        # Post-filter by author name using part-aware matching, so that
        # "Jennifer Doudna" also matches "Jennifer A. Doudna" and "J. Doudna".
        # A literal substring test matched none of those and silently
        # returned an empty result.
        author_filtered, matched_names = filter_by_author(
            papers,
            author_name,
            allow_initial_match=allow_initial_match,
            allow_surname_only=allow_surname_only,
        )
        meta["total_after_author_filter"] = len(author_filtered)
        meta["matched_author_names"] = matched_names
        if not author_filtered and papers:
            # Capture why nothing matched, so the caller is never handed a
            # bare empty list with no explanation.
            meta["candidate_name_sample"] = sample_author_names(papers)


        if filters and filters.is_active():
            author_filtered = apply_filters(author_filtered, filters)
        meta["total_after_filters"] = len(author_filtered)

        return author_filtered[:limit], meta

    # ------------------------------------------------------------------
    # Citation graph exploration (random walk)
    # ------------------------------------------------------------------

    def explore_citations(
        self,
        seed_paper_id: str,
        num_steps: int = 30,
        max_depth: Optional[int] = None,
        direction_choice: str = "random",
        bias: str = "random",
        candidates_per_step: int = 100,
        stop_similarity: Optional[float] = None,
        filters: Optional[FilterConfig] = None,
        progress_callback: ProgressCallback = None,
    ) -> dict[str, Any]:
        """Walk the citation graph from a seed paper using a random walk.

        At each step, fetches the current paper's references (backward)
        or citations (forward), applies filters, picks a candidate based
        on the bias strategy, and moves there.  Cross-edges to already
        visited papers are recorded.  Backtracks on dead ends.

        Args:
            seed_paper_id: Semantic Scholar paper ID to start from.
            num_steps: Maximum number of walk steps.
            max_depth: Maximum hop distance from seed before forced
                backtrack (``None`` = unlimited).
            direction_choice: ``"random"`` (default), ``"forward"``,
                ``"backward"``, or ``"alternating"``.
            bias: ``"random"`` (default), ``"top_cited"``, or
                ``"bottom_cited"``.
            candidates_per_step: Number of candidates to fetch per API
                call (max 1000).
            stop_similarity: If set, stop exploring a branch when the
                candidate's text similarity to the seed paper falls
                below this threshold (0.0 to 1.0).
            filters: Optional :class:`FilterConfig` to apply to
                candidates at each step.
            progress_callback: Optional progress reporting callback.

        Returns:
            Dict with ``papers``, ``edges``, ``path``, ``seed_paper_id``,
            and ``stats``.
        """
        # Resolve the seed identifier: DOI / arXiv / PMID / CorpusId / S2 id.
        resolved_id, normalized = self._resolve_seed_identifier(seed_paper_id)
        if resolved_id is None:
            raise ValueError(
                f"Could not resolve seed paper {seed_paper_id!r} "
                f"(parsed as {normalized!r}) to a Semantic Scholar paper ID. "
                + self._failure_message("resolve the seed identifier")
            )
        seed_paper_id = resolved_id

        # Fetch seed paper metadata (including TLDR for similarity)
        seed_url = (
            f"https://api.semanticscholar.org/graph/v1/paper/{quote(seed_paper_id)}"
            f"?fields={CITATION_GRAPH_FIELDS}"
        )
        time.sleep(API_DELAY)
        seed_data = self._request_with_retry(seed_url)
        seed_metadata_warning: Optional[str] = None
        if seed_data is None:
            # The walk only needs the paper id, so degrade gracefully rather
            # than failing the whole call on a transient throttle.
            seed_metadata_warning = (
                self._failure_message("fetch seed paper metadata")
                + " Continuing with the resolved paper id, but seed text is "
                "unavailable, so stop_similarity and bias='most_similar' "
                "cannot be applied."
            )
            logger.warning("%s", seed_metadata_warning)
            seed_data = {"paperId": seed_paper_id}

        seed_paper = seed_data

        # Need seed text for stop_similarity and/or most_similar bias
        need_seed_text = (stop_similarity is not None) or (bias == "most_similar")
        seed_text = get_paper_text_for_similarity(seed_paper) if need_seed_text else ""

        # Clear the graph response cache for a fresh walk
        self._graph_cache.clear()

        papers: dict[str, dict[str, Any]] = {seed_paper_id: seed_paper}
        edges: list[dict[str, Any]] = []
        path: list[str] = [seed_paper_id]

        # Step is a plain dict: {"paper_id": str, "remaining": list, "direction": str, "depth": int}
        stack: list[dict[str, Any]] = []
        current_id = seed_paper_id
        visited_paper_ids: set[str] = {seed_paper_id}
        total_api_calls = 1  # count the seed fetch
        dead_ends = 0
        backtracks = 0
        steps_completed = 0
        pruned_by_filters = 0
        cross_edges_found = 0

        # Determine max_depth from num_steps if not explicitly set
        if max_depth is None:
            max_depth = num_steps

        for step_idx in range(num_steps):
            if progress_callback is not None:
                progress_callback(
                    step_idx + 1, num_steps,
                    f"Walk step {step_idx + 1}/{num_steps} (depth {len(stack)})",
                )

            # --- Determine direction ---
            if direction_choice == "forward":
                direction = "forward"
            elif direction_choice == "backward":
                direction = "backward"
            elif direction_choice == "alternating":
                direction = "backward" if step_idx % 2 == 0 else "forward"
            else:  # random
                direction = "forward" if (step_idx % 2 == 0) else "backward"
                # Use a quick deterministic pseudo-random based on the paper ID
                if current_id:
                    char_sum = sum(ord(c) for c in current_id)
                    direction = "forward" if (char_sum + step_idx) % 2 == 0 else "backward"

            # --- Fetch candidates (with cache) ---
            endpoint = "citations" if direction == "forward" else "references"
            cache_key = (current_id, direction)

            if cache_key in self._graph_cache:
                graph_data = self._graph_cache[cache_key]
            else:
                graph_url = (
                    f"https://api.semanticscholar.org/graph/v1/paper/"
                    f"{quote(current_id)}/{endpoint}"
                    f"?limit={candidates_per_step}&fields={CITATION_GRAPH_FIELDS}"
                )
                time.sleep(API_DELAY)
                graph_data = self._request_with_retry(graph_url)
                self._graph_cache[cache_key] = graph_data
                total_api_calls += 1

            if graph_data is None or not graph_data.get("data"):
                # Dead end — backtrack
                dead_ends += 1
                backtracked = self._backtrack(stack, papers, path)
                if backtracked is None:
                    break  # no more branches to explore
                current_id, _ = backtracked
                backtracks += 1
                continue

            # --- Extract candidate papers ---
            key = "citingPaper" if direction == "forward" else "citedPaper"
            raw_candidates = []
            for item in graph_data["data"]:
                candidate = item.get(key)
                if candidate and isinstance(candidate, dict) and candidate.get("paperId"):
                    raw_candidates.append(candidate)

            if not raw_candidates:
                dead_ends += 1
                backtracked = self._backtrack(stack, papers, path)
                if backtracked is None:
                    break
                current_id, _ = backtracked
                backtracks += 1
                continue

            # --- Check for cross-edges to already visited papers ---
            unvisited_candidates: list[dict[str, Any]] = []
            for c in raw_candidates:
                pid = c["paperId"]
                if pid in visited_paper_ids:
                    # Record cross-edge
                    edges.append({
                        "source": current_id,
                        "target": pid,
                        "type": "cites" if direction == "backward" else "cited_by",
                    })
                    cross_edges_found += 1
                else:
                    unvisited_candidates.append(c)

            if not unvisited_candidates:
                dead_ends += 1
                backtracked = self._backtrack(stack, papers, path)
                if backtracked is None:
                    break
                current_id, _ = backtracked
                backtracks += 1
                continue

            # --- Store paper metadata for any new papers ---
            for c in unvisited_candidates:
                pid = c["paperId"]
                if pid not in papers:
                    papers[pid] = c

            # --- Apply filters ---
            if filters and filters.is_active():
                before = len(unvisited_candidates)
                unvisited_candidates = apply_filters(unvisited_candidates, filters)
                pruned_by_filters += before - len(unvisited_candidates)

            if not unvisited_candidates:
                dead_ends += 1
                backtracked = self._backtrack(stack, papers, path)
                if backtracked is None:
                    break
                current_id, _ = backtracked
                backtracks += 1
                continue

            # --- Compute similarity scores if needed for bias or stop_similarity ---
            need_sim_scores = need_seed_text and seed_text
            candidate_scores: dict[str, float] = {}

            if need_sim_scores:
                for c in unvisited_candidates:
                    pid = c["paperId"]
                    if pid not in candidate_scores:
                        c_text = get_paper_text_for_similarity(c)
                        candidate_scores[pid] = simple_text_similarity(seed_text, c_text) if c_text else 0.0

            # --- Apply stop_similarity if configured ---
            if stop_similarity is not None and candidate_scores:
                above_threshold = [(c, candidate_scores[c["paperId"]]) for c in unvisited_candidates
                                   if candidate_scores[c["paperId"]] >= stop_similarity]
                if not above_threshold:
                    # All candidates are below similarity threshold — backtrack
                    dead_ends += 1
                    backtracked = self._backtrack(stack, papers, path, similarity_lookup=candidate_scores,
                                                   bias=bias)
                    if backtracked is None:
                        break
                    current_id, _ = backtracked
                    backtracks += 1
                    continue
                unvisited_candidates = [c for c, _ in above_threshold]

            # --- Check depth bound ---
            current_depth = len(stack) + 1  # +1 for the current step
            if max_depth is not None and current_depth >= max_depth:
                pass  # select candidate but force backtrack afterwards

            # --- Select candidate based on bias ---
            selected = self._select_candidate(unvisited_candidates, bias,
                                               similarity_scores=candidate_scores)

            if selected is None:
                dead_ends += 1
                backtracked = self._backtrack(stack, papers, path, similarity_lookup=candidate_scores,
                                               bias=bias)
                if backtracked is None:
                    break
                current_id, _ = backtracked
                backtracks += 1
                continue

            # --- Record edge for this step ---
            edges.append({
                "source": current_id,
                "target": selected["paperId"],
                "type": "cites" if direction == "backward" else "cited_by",
            })

            # --- Record remaining candidates for backtracking ---
            remaining = [(c, candidate_scores.get(c["paperId"], 0.0))
                         for c in unvisited_candidates
                         if c["paperId"] != selected["paperId"]]
            current_depth_val = len(stack) + 1
            stack.append({
                "paper_id": current_id,
                "remaining": remaining,         # list of (dict, sim_score)
                "direction": direction,
                "depth": current_depth_val,
            })

            # --- Move to selected paper ---
            current_id = selected["paperId"]
            visited_paper_ids.add(current_id)
            path.append(current_id)
            steps_completed += 1

            # --- Check if depth limit forces backtrack ---
            if max_depth is not None and current_depth_val >= max_depth:
                backtracked = self._backtrack(stack, papers, path)
                if backtracked is not None:
                    current_id, _ = backtracked
                    backtracks += 1

        result: dict[str, Any] = {
            "seed_paper_id": seed_paper_id,
            "papers": papers,
            "edges": edges,
            "path": path,
            "stats": {
                "steps_completed": steps_completed,
                "unique_papers_visited": len(visited_paper_ids),
                "backtracks": backtracks,
                "dead_ends": dead_ends,
                "cross_edges_found": cross_edges_found,
                "pruned_by_filters": pruned_by_filters,
                "api_calls_made": total_api_calls,
            },
        }

        # Surface failures instead of returning a success-looking payload with
        # an empty path, which previously read as "this paper has no citations".
        diagnostics: list[str] = []
        if seed_metadata_warning:
            diagnostics.append(seed_metadata_warning)
        if steps_completed == 0:
            upstream_failed = total_api_calls > 0 and (
                self._last_request_error is not None
            )
            if upstream_failed:
                diagnostics.append(
                    self._failure_message("walk the citation graph")
                    + " The walk made no progress because upstream requests "
                    "failed, so an empty path does NOT mean the paper has no "
                    "citations."
                )
            else:
                diagnostics.append(
                    "The walk completed no steps: the seed's reference and "
                    "citation lists were both empty or filtered out. Increase "
                    "candidates_per_step or relax the filters."
                )
        if filters is not None and pruned_by_filters and steps_completed == 0:
            diagnostics.append(
                f"{pruned_by_filters} candidates were removed by the supplied "
                "filters, which is why nothing was left to walk."
            )
        if diagnostics:
            result["diagnostics"] = diagnostics

        return result

    def _backtrack(
        self,
        stack: list,
        papers: dict[str, dict],
        path: list[str],
        similarity_lookup: Optional[dict[str, float]] = None,
        bias: str = "random",
    ) -> Optional[tuple[str, str]]:
        """Pop the stack until we find a step with remaining candidates.

        ``step[\"remaining\"]`` is a list of ``(paper_dict, sim_score)`` tuples.

        Returns:
            ``(paper_id, direction)`` to continue from, or ``None`` if
            the stack is exhausted.
        """
        while stack:
            step = stack.pop()
            if step["remaining"]:
                # Extract just the dicts for selection
                remaining_dicts = [item[0] for item in step["remaining"]]
                # Build similarity lookup from stored tuples
                stored_scores = {item[0]["paperId"]: item[1] for item in step["remaining"]}
                scores = dict(similarity_lookup or {})
                scores.update(stored_scores)

                selected = self._select_candidate(remaining_dicts, bias,
                                                   similarity_scores=scores)
                if selected is None:
                    continue
                pid = selected["paperId"]
                # Remove selected from remaining (match by paperId)
                step["remaining"] = [item for item in step["remaining"]
                                     if item[0]["paperId"] != pid]
                if step["remaining"]:
                    stack.append(step)  # push back if more remain
                path.append(pid)
                return (pid, step["direction"])
        return None

    @staticmethod
    def _select_candidate(
        candidates: list[dict[str, Any]],
        bias: str,
        similarity_scores: Optional[dict[str, float]] = None,
    ) -> Optional[dict[str, Any]]:
        """Select a candidate paper based on the bias strategy.

        Args:
            candidates: List of paper dicts.
            bias: ``\"top_cited\"``, ``\"bottom_cited\"``, ``\"most_similar\"``,
                or ``\"random\"``.
            similarity_scores: Optional dict of ``paperId -> float`` for
                ``\"most_similar\"`` bias.

        Returns:
            The selected paper dict, or ``None`` if the list is empty.
        """
        if not candidates:
            return None

        if bias == "top_cited":
            return max(candidates, key=lambda c: c.get("citationCount", 0) or 0)
        elif bias == "bottom_cited":
            return min(candidates, key=lambda c: c.get("citationCount", 0) or 0)
        elif bias == "most_similar":
            scores = similarity_scores or {}
            return max(candidates, key=lambda c: scores.get(c["paperId"], 0.0))
        else:  # random
            total = sum(ord(c) for c in candidates[0].get("paperId", ""))
            idx = total % len(candidates)
            return candidates[idx]

    def get_stats(
        self,
        query: str,
        max_retrieval: int = 10_000,
        fields: str = DEFAULT_FIELDS,
        search_type: str = "limited",
    ) -> dict[str, Any]:
        """Fetch papers and return metadata about the result set."""
        extended_query = self._build_extended_query(query, search_type)
        papers = self._fetch_all(extended_query, fields, max_retrieval)
        return {
            "provider": self.provider_name,
            "query": query,
            "extended_query": extended_query,
            "total_papers": len(papers),
        }

    # ------------------------------------------------------------------
    # DOI resolution
    # ------------------------------------------------------------------

    # Accepted spellings of a DOI prefix, longest first so that
    # "https://doi.org/" is consumed before "doi:".
    _DOI_PREFIXES = (
        "https://doi.org/", "http://doi.org/",
        "https://dx.doi.org/", "http://dx.doi.org/",
        "https://www.doi.org/", "doi:", "doi ", "DOI:",
    )
    _ARXIV_PREFIXES = ("arxiv:", "https://arxiv.org/abs/", "http://arxiv.org/abs/")
    _PMID_PREFIXES = ("pmid:", "pmid ")
    _CORPUS_PREFIXES = ("corpusid:", "corpusid ", "s2:")
    _URL_PREFIXES = (
        "https://api.semanticscholar.org/graph/v1/paper/",
        "https://www.semanticscholar.org/paper/",
        "https://semanticscholar.org/paper/",
    )

    @staticmethod
    def _strip_prefix(value: str, prefixes: tuple[str, ...]) -> str:
        """Remove a leading prefix, case-insensitively, or return *value*."""
        cleaned = value.strip()
        lowered = cleaned.lower()
        for p in prefixes:
            if lowered.startswith(p):
                return cleaned[len(p):].strip()
        return cleaned

    @classmethod
    def _is_doi(cls, identifier: str) -> bool:
        """Check if an identifier string looks like a DOI."""
        cleaned = cls._strip_prefix(identifier, cls._DOI_PREFIXES).rstrip(".")
        return bool(re.match(r"^10\.\d{4,}/\S+", cleaned))

    @classmethod
    def _normalize_doi(cls, identifier: str) -> str:
        """Strip prefixes from a DOI and return the canonical form."""
        return cls._strip_prefix(identifier, cls._DOI_PREFIXES).rstrip(".")

    @classmethod
    def normalize_identifier(cls, identifier: str) -> str:
        """Convert any supported identifier form to a Semantic Scholar form.

        Semantic Scholar's single-paper endpoint accepts prefixed IDs
        (``DOI:``, ``ARXIV:``, ``PMID:``, ``CorpusId:``) or a bare SHA.
        Callers should not have to know which form they hold, so this maps
        every recognised spelling onto the right one.

        Args:
            identifier: A DOI (bare or URL, optionally ``doi:``-prefixed), an
                arXiv id (bare or ``arXiv:``-prefixed), a PMID, a
                ``CorpusId``, a Semantic Scholar paper URL, or a bare
                Semantic Scholar paper id.

        Returns:
            A Semantic Scholar-compatible identifier, or an empty string when
            nothing usable can be extracted.
        """
        if not identifier or not str(identifier).strip():
            return ""
        raw = str(identifier).strip()

        # A full Semantic Scholar URL: take the trailing 40-char SHA if present.
        stripped_url = cls._strip_prefix(raw, cls._URL_PREFIXES)
        if stripped_url != raw:
            sha = re.search(r"\b([0-9a-f]{40})\b", stripped_url)
            if sha:
                return sha.group(1)
            return stripped_url.split("?")[0].split("/")[0].strip()

        if cls._is_doi(raw):
            return f"DOI:{cls._normalize_doi(raw)}"

        arxiv = cls._strip_prefix(raw, cls._ARXIV_PREFIXES)
        if arxiv != raw:
            # A trailing version suffix is not accepted by the API:
            # 2006.10256v2 -> 2006.10256
            return f"ARXIV:{re.sub(r'v[0-9]+$', '', arxiv)}"

        if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", raw):
            # A bare arXiv id such as 2006.10256 -> arXiv:2006.10256
            return f"ARXIV:{raw.split('v')[0]}"

        pmid = cls._strip_prefix(raw, cls._PMID_PREFIXES)
        if pmid != raw or re.match(r"^\d{7,9}$", raw):
            digits = pmid if pmid != raw else raw
            return f"PMID:{digits}"

        corpus = cls._strip_prefix(raw, cls._CORPUS_PREFIXES)
        if corpus != raw:
            return f"CorpusId:{corpus}"

        # Assume it is already a Semantic Scholar paper id.
        return raw

    def _resolve_seed_identifier(self, identifier: str) -> tuple[Optional[str], str]:
        """Resolve any supported identifier to a Semantic Scholar paper id.

        Args:
            identifier: DOI / arXiv id / PMID / CorpusId / Semantic Scholar
                paper id or paper URL.

        Returns:
            ``(paper_id, normalized_identifier)``.  ``paper_id`` is ``None``
            when resolution failed; the normalized identifier is returned
            either way so the caller can build a useful error message.
        """
        normalized = self.normalize_identifier(identifier)
        if not normalized:
            return None, ""

        # A bare Semantic Scholar id needs no lookup.
        if not re.match(r"^(DOI|ARXIV|PMID|CorpusId):", normalized):
            return normalized, normalized

        url = (
            "https://api.semanticscholar.org/graph/v1/paper/"
            f"{quote(normalized, safe=':')}?fields=paperId"
        )
        time.sleep(API_DELAY)
        data = self._request_with_retry(url)
        if data is None:
            logger.warning("Identifier '%s' could not be resolved.", normalized)
            return None, normalized
        paper_id = data.get("paperId")
        if not paper_id:
            logger.warning("Identifier '%s' resolved but no paperId returned.", normalized)
            return None, normalized
        logger.info("Resolved '%s' -> paperId '%s'", normalized, paper_id)
        return paper_id, normalized

    def _resolve_doi_to_paper_id(self, identifier: str) -> Optional[str]:
        """Backwards-compatible DOI resolver; delegates to the generic one."""
        paper_id, _ = self._resolve_seed_identifier(identifier)
        return paper_id


    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_extended_query(self, query: str, search_type: str = "limited") -> str:
        """Transform a regex pattern into an API-compatible keyword query.

        Semantic Scholar's bulk search API treats space-separated words as
        AND.  It does **not** support ``+`` or ``|`` operators — sending
        them as literal text would return no results.  So we simply join
        extracted terms with spaces regardless of *search_type*.

        For providers that do support OR operators (e.g. PubMed), the
        *search_type* parameter is handled by their own implementation.
        """
        terms: list[str] = []
        seen: set[str] = set()
        for match in re.finditer(
            r'(?:"(.*?)")|(?:\'(.*?)\')|(?:([a-zA-Z-]{3,}[.*+?]{0,2}))',
            query,
        ):
            raw = "".join(match.groups(default="")).strip()
            if not raw or raw in seen:
                continue
            seen.add(raw)
            raw = raw.replace(".*", "*").replace(".+", "*").replace(".?", "*")
            terms.append(raw)

        # Space = AND in SS.  No OR support in the bulk API.
        return " ".join(terms)

    def _fetch_all(
        self,
        extended_query: str,
        fields: str = DEFAULT_FIELDS,
        max_retrieval: int = 10_000_000,
        progress_callback: ProgressCallback = None,
    ) -> list[dict[str, Any]]:
        """Paginate through the Semantic Scholar bulk API."""
        url = (
            f"{self.base_url}?query={quote(extended_query)}&fields={fields}"
        )

        papers: list[dict[str, Any]] = []
        retrieved = 0
        token: Optional[str] = None

        while retrieved < max_retrieval:
            request_url = f"{url}&token={token}" if token else url
            data = self._request_with_retry(request_url)
            if data is None:
                logger.warning("Stopping due to repeated API failures.")
                break

            if "data" in data:
                papers.extend(data["data"])
                retrieved += len(data["data"])

            # Report progress after each page
            if progress_callback is not None:
                batch_size = 500  # approximate batch size
                total = min(max_retrieval, retrieved + batch_size * 2)  # estimate
                progress_callback(retrieved, total, f"Fetching from Semantic Scholar...")

            token = data.get("token")
            if not token:
                break

            if API_DELAY > 0:
                time.sleep(API_DELAY)

        logger.info("Retrieved %d papers from Semantic Scholar.", retrieved)
        return papers

    def _request_with_retry(
        self,
        url: str,
        max_retries: int = MAX_RETRIES,
        headers: Optional[dict[str, str]] = None,
    ) -> Optional[dict]:
        """Make a GET request with retry logic for transient errors.

        The outcome of the final attempt is recorded in
        ``self._last_request_error`` so callers can tell "this DOI does not
        exist" (HTTP 404) apart from "we were rate limited" (HTTP 429).  The
        old code returned ``None`` for both and reported the same message,
        which is why a transient throttle looked like a bad identifier.
        """
        self._last_request_error: Optional[dict[str, Any]] = None
        request_headers = headers if headers is not None else _api_headers()
        for attempt in range(1, max_retries + 1):
            try:
                r = requests.get(url, timeout=30, headers=request_headers)
                r.raise_for_status()
                return r.json()
            except requests.exceptions.Timeout:
                self._last_request_error = {"kind": "timeout", "attempt": attempt}
                logger.warning("Request timed out (attempt %d/%d).", attempt, max_retries)
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else "unknown"
                self._last_request_error = {
                    "kind": "http_error",
                    "status": status,
                    "attempt": attempt,
                }
                logger.warning("HTTP %s error (attempt %d/%d).", status, attempt, max_retries)
                if status == 429:
                    # Long backoff for rate limiting (up to 60s)
                    wait = min(10 * attempt + 10, 60)
                    logger.warning("Rate limited. Waiting %ds before retry.", wait)
                    time.sleep(wait)
                elif status in (400, 404):
                    return None
                else:
                    if attempt < max_retries:
                        time.sleep(2 ** attempt)
            except requests.exceptions.ConnectionError:
                self._last_request_error = {"kind": "connection_error", "attempt": attempt}
                logger.warning("Connection error (attempt %d/%d).", attempt, max_retries)
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
            except Exception:
                self._last_request_error = {"kind": "unexpected_error", "attempt": attempt}
                logger.exception("Unexpected error (attempt %d/%d).", attempt, max_retries)
                if attempt < max_retries:
                    time.sleep(2 ** attempt)

        return None

    def _failure_message(self, action: str) -> str:
        """Build an actionable error message from the last request outcome.

        Args:
            action: What was being attempted, e.g. ``"fetch seed paper"``.

        Returns:
            A message naming the failure mode and, for rate limiting, the
            concrete fix.
        """
        err = getattr(self, "_last_request_error", None) or {}
        kind = err.get("kind")
        if kind == "http_error" and err.get("status") == 429:
            return (
                f"Could not {action}: Semantic Scholar rate limit reached "
                f"(HTTP 429) after {MAX_RETRIES} attempts. This is throttling, "
                "not a bad identifier. Set the S2_API_KEY environment variable "
                "for the academic-search server to use your own quota."
            )
        if kind == "timeout":
            return (
                f"Could not {action}: requests to Semantic Scholar timed out "
                f"after {MAX_RETRIES} attempts. Retry shortly."
            )
        if kind == "connection_error":
            return (
                f"Could not {action}: could not reach api.semanticscholar.org "
                "(network/DNS failure)."
            )
        return f"Could not {action} (unknown upstream failure)."

