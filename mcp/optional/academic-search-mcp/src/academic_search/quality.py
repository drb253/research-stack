"""Result-quality and relevance scoring shared by all providers.

Two independent problems motivated this module:

1. **Junk records.**  Semantic Scholar occasionally returns records with no
   year, no authors, no abstract, no DOI and no citations -- sometimes with a
   truncated title.  They were passed through verbatim and could occupy the
   top of a result list, which makes a working query look broken.

2. **No local relevance gate.**  Crossref has no semantic ranking, so a
   bibliographic query returns loose term-overlap matches: the query
   ``"base editing"`` returned a paper about *denture base* repair and
   another about *base deficit* in trauma resuscitation.  Scoring documents
   against the query's own terms removes those.

Both helpers are provider-agnostic -- they only read the normalised schema.
"""

from __future__ import annotations

import re
from typing import Any, Optional

_WORD_RE = re.compile(r"[a-z0-9]+")

# Tokens that carry no discriminating power when scoring relevance.
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "in", "is", "it", "of", "on", "or", "that", "the", "to", "with",
        "using", "use", "used", "via", "based",
    }
)


def _tokens(text: Any) -> list[str]:
    """Lowercase word tokens from arbitrary text."""
    if not text or not isinstance(text, str):
        return []
    return _WORD_RE.findall(text.lower())


def query_terms(query: str, *, drop_stopwords: bool = True) -> list[str]:
    """Extract the discriminating terms from a search query.

    A regex query is treated as its literal word content, because scoring
    needs plain terms rather than patterns.

    Args:
        query: The caller's query string.
        drop_stopwords: Remove low-information tokens such as ``of``/``the``.

    Returns:
        De-duplicated terms in first-seen order.
    """
    seen: list[str] = []
    for token in _tokens(query):
        if drop_stopwords and token in _STOPWORDS:
            continue
        if token not in seen:
            seen.append(token)
    # If stopword removal empties a legitimate query, fall back to raw tokens.
    if not seen and drop_stopwords:
        return query_terms(query, drop_stopwords=False)
    return seen


def _paper_text(paper: dict[str, Any], *, include_abstract: bool = True) -> list[str]:
    """Collect the searchable text of a record as a token list."""
    parts: list[str] = []
    title = paper.get("title")
    if isinstance(title, str):
        parts.append(title)
    if include_abstract:
        abstract = paper.get("abstract")
        if isinstance(abstract, str):
            parts.append(abstract)
    journal = paper.get("journal")
    if isinstance(journal, str):
        parts.append(journal)
    elif isinstance(journal, dict) and isinstance(journal.get("name"), str):
        parts.append(journal["name"])
    return _tokens(" ".join(parts))


def relevance_score(
    query: str,
    paper: dict[str, Any],
    *,
    include_abstract: bool = True,
) -> float:
    """Fraction of the query's terms present in the record, in ``[0.0, 1.0]``.

    Whole-word matching is used so that ``base`` does not match ``database``.

    Args:
        query: The caller's search query.
        paper: A normalised paper dict.
        include_abstract: Also match against the abstract when present.
            Records without abstracts fall back to title + journal only, so
            a missing abstract never *forces* a low score by itself.

    Returns:
        ``matched_terms / total_terms``; ``1.0`` when the query has no terms
        (nothing to filter on).
    """
    terms = query_terms(query)
    if not terms:
        return 1.0

    document = set(_paper_text(paper, include_abstract=include_abstract))
    if not document:
        return 0.0

    matched = sum(1 for t in terms if t in document)
    return matched / len(terms)


def completeness_score(paper: dict[str, Any]) -> float:
    """How complete a record's metadata is, in ``[0.0, 1.0]``.

    Each of five fields contributes equally: year, authors, abstract, a DOI
    (or other external identifier) and a journal.
    """
    checks = (
        bool(paper.get("year")),
        bool(paper.get("authors")),
        bool(paper.get("abstract")),
        bool(paper.get("externalIds")),
        bool(paper.get("journal")),
    )
    return sum(1 for c in checks if c) / len(checks)


def is_usable_record(paper: dict[str, Any]) -> bool:
    """Return False for records with essentially no usable metadata.

    A record is rejected when it carries **no substantive field at all** --
    no year, no authors, no abstract, no journal, no citations and no
    references.

    Note that the presence of an identifier or a title is deliberately *not*
    enough.  Every Semantic Scholar record carries a ``paperId``/``CorpusId``,
    and the junk records this guards against do come with a (garbled) title --
    so treating identifiers or titles as evidence of quality made an earlier
    version of this check a no-op for exactly the records it was written for.

    The consequence, accepted deliberately: a record that has only a title and
    a DOI (no year, authors, journal or abstract) is also dropped, because it
    is indistinguishable by field emptiness from the junk.  Such a record
    gives a reader no way to judge recency or attribution, the dropped count is
    reported as ``total_dropped_incomplete``, and the gate can be disabled
    with ``exclude_incomplete=False``.

    Args:
        paper: A normalised paper dict.

    Returns:
        True when the record is worth returning.
    """
    if not isinstance(paper, dict):
        return False
    citations = paper.get("citationCount")
    references = paper.get("referenceCount")
    return any(
        (
            bool(paper.get("year")),
            bool(paper.get("authors")),
            bool(paper.get("abstract")),
            bool(paper.get("journal")),
            bool(citations) if isinstance(citations, int) else bool(citations),
            bool(references) if isinstance(references, int) else bool(references),
        )
    )


def filter_usable_records(
    papers: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Drop unusable records.

    Args:
        papers: Normalised paper dicts.

    Returns:
        ``(kept_papers, dropped_count)``.
    """
    kept = [p for p in papers if is_usable_record(p)]
    return kept, len(papers) - len(kept)


def rank_by_relevance(
    papers: list[dict[str, Any]],
    query: str,
) -> list[dict[str, Any]]:
    """Stable-sort records so the strongest query matches come first.

    Records are ordered by relevance score, then by completeness, then by
    citation count.  The sort is stable, so records that tie on all three
    keep their provider ordering.

    Args:
        papers: Normalised paper dicts.
        query: The caller's search query.

    Returns:
        A new list in ranked order.
    """
    def _key(entry: tuple[int, dict[str, Any]]) -> tuple[float, float, float]:
        _, paper = entry
        citations = paper.get("citationCount")
        return (
            -relevance_score(query, paper),
            -completeness_score(paper),
            -(citations if isinstance(citations, int) else 0),
        )

    return [p for _, p in sorted(enumerate(papers), key=_key)]


def quality_summary(
    papers: list[dict[str, Any]],
    query: Optional[str] = None,
) -> dict[str, Any]:
    """Summarise metadata completeness and relevance for a result set.

    Args:
        papers: Normalised paper dicts.
        query: When given, include the mean relevance score.

    Returns:
        A dict with counts and mean scores, suitable for embedding in a tool
        response so a caller can judge how trustworthy the list is.
    """
    if not papers:
        summary: dict[str, Any] = {
            "records": 0,
            "mean_completeness": 0.0,
            "with_year_pct": 0.0,
            "with_authors_pct": 0.0,
            "with_abstract_pct": 0.0,
        }
        if query is not None:
            summary["mean_relevance"] = 0.0
        return summary

    total = len(papers)
    summary = {
        "records": total,
        "mean_completeness": round(
            sum(completeness_score(p) for p in papers) / total, 3
        ),
        "with_year_pct": round(
            100.0 * sum(1 for p in papers if p.get("year")) / total, 1
        ),
        "with_authors_pct": round(
            100.0 * sum(1 for p in papers if p.get("authors")) / total, 1
        ),
        "with_abstract_pct": round(
            100.0 * sum(1 for p in papers if p.get("abstract")) / total, 1
        ),
    }
    if query is not None:
        summary["mean_relevance"] = round(
            sum(relevance_score(query, p) for p in papers) / total, 3
        )
    return summary

