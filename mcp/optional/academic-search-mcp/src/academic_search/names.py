"""Author-name matching utilities.

Why this module exists
----------------------
Every provider renders personal names differently::

    "Jennifer Doudna"        (what a caller types)
    "Jennifer A. Doudna"     (Semantic Scholar)
    "Doudna, Jennifer"       (Crossref)
    "J. Doudna"              (Semantic Scholar, abbreviated)
    "Doudna J"               (PubMed)

The historical filter did ``author_query.lower() in candidate.lower()``,
which is a *literal substring* test.  Because ``"jennifer doudna"`` is not a
substring of ``"jennifer a. doudna"``, a perfectly correct full-name lookup
matched **zero** records while the API had 227 candidates -- and it reported
that as a successful empty result, so it looked like the author had no
papers rather than like a bug.

The matcher below compares *name parts* (surname + given names/initials)
instead of raw strings, which is the convention bibliographic databases use:

* The **surname must match**, after normalising case, accents, punctuation
  and particles (``van``, ``de``, ``von`` ...).
* The **given names must be compatible**: equal as whole tokens, or
  compatible as initials (``J.`` matches ``Jennifer``).
* A surname-only query (``"Doudna"``) matches any rendering of that surname.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

# Nobiliary particles that belong to the surname rather than the given names.
_PARTICLES = {
    "van", "von", "de", "del", "della", "der", "den", "di", "da", "dos",
    "du", "la", "le", "ter", "ten", "st", "mac", "mc", "bin", "ibn", "al",
}

# Suffixes that are not part of the surname and should be ignored.
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "phd", "md", "msc", "mph"}


def _strip_accents(text: str) -> str:
    """Fold accented characters to ASCII (``Garcia`` <- ``Garcia``)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _tokenize(name: str) -> list[str]:
    """Lowercase, accent-fold and split a name into comparable tokens.

    Hyphens and periods become separators so that ``Jean-Paul`` and
    ``J.`` behave like ``jean paul`` and ``j``.
    """
    if not name:
        return []
    text = _strip_accents(str(name)).lower()
    text = re.sub(r"[^\w\s,]", " ", text)      # punctuation -> space
    text = re.sub(r"[_\-/]", " ", text)        # separators -> space
    text = re.sub(r"\s+", " ", text).strip()
    return [t for t in text.split(" ") if t]


@dataclass(frozen=True)
class NameParts:
    """A parsed personal name."""

    raw: str
    surname: str
    givens: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_surname_only(self) -> bool:
        """True when no given names/initials were supplied."""
        return not self.givens


def parse_name(name: str) -> NameParts:
    """Parse a personal name into surname + given tokens.

    Handles both ``"Given Family"`` and ``"Family, Given"`` orderings, and
    keeps nobiliary particles attached to the surname.

    Args:
        name: A personal name in any of the common renderings.

    Returns:
        A :class:`NameParts`.  Missing parts degrade to empty strings rather
        than raising, so a malformed candidate name cannot break a search.
    """
    if not name or not str(name).strip():
        return NameParts(raw="", surname="", givens=())

    raw = str(name).strip()

    # "Family, Given" (Crossref / PubMed style) -> treat comma as a boundary.
    if "," in raw:
        family_part, _, given_part = raw.partition(",")
        family_tokens = _tokenize(family_part)
        given_tokens = [t for t in _tokenize(given_part) if t not in _SUFFIXES]
        return NameParts(
            raw=raw,
            surname=" ".join(family_tokens),
            givens=tuple(given_tokens),
        )

    tokens = _tokenize(raw)
    if not tokens:
        return NameParts(raw=raw, surname="", givens=())

    # Drop trailing suffixes ("Jennifer Doudna Jr").
    while len(tokens) > 1 and tokens[-1] in _SUFFIXES:
        tokens.pop()

    # Walk backwards over particles to build the surname.
    surname_parts = [tokens[-1]]
    idx = len(tokens) - 2
    while idx >= 0 and tokens[idx] in _PARTICLES:
        surname_parts.insert(0, tokens[idx])
        idx -= 1

    givens = tuple(tokens[: idx + 1])
    return NameParts(raw=raw, surname=" ".join(surname_parts), givens=givens)



def _given_token_compatible(query_token: str, candidate_token: str) -> bool:
    """Compare one given-name token, allowing initial-vs-full matches.

    ``j`` matches ``jennifer`` (an initial is compatible with a full name),
    but ``john`` does not match ``jennifer`` (two distinct full names).
    """
    q = query_token.strip(".")
    c = candidate_token.strip(".")
    if not q or not c:
        return False
    if q == c:
        return True
    # An initial matches any name starting with that letter.
    if len(q) == 1 or len(c) == 1:
        return q[0] == c[0]
    return False


def name_matches(
    query: str,
    candidate: str,
    *,
    allow_initial_match: bool = True,
    allow_surname_only: bool = True,
) -> bool:
    """Return True if *candidate* can plausibly be the person in *query*.

    Args:
        query: The name the caller asked for (e.g. ``"Jennifer Doudna"``).
        candidate: One author name from a provider (e.g. ``"J. Doudna"``).
        allow_initial_match: When False, ``J.`` no longer matches
            ``Jennifer`` -- useful for disambiguating same-surname authors.
        allow_surname_only: When False, a bare surname query
            (``"Doudna"``) no longer matches every variant.

    Returns:
        True on a match.  A surname-only query matches on surname alone;
        otherwise the surname must match *and* the first given tokens must be
        compatible.
    """
    q = parse_name(query)
    c = parse_name(candidate)

    if not q.surname or not c.surname:
        return False
    if q.surname != c.surname:
        return False

    # Surname-only query: match any given-name rendering.
    if q.is_surname_only:
        return allow_surname_only
    # Candidate carries no given names: accept on surname alone, since
    # providers frequently drop them.
    if c.is_surname_only:
        return allow_surname_only

    if allow_initial_match:
        return _given_token_compatible(q.givens[0], c.givens[0])

    return q.givens[0].strip(".") == c.givens[0].strip(".")


def _extract_names(authors: Any) -> list[str]:
    """Pull author name strings out of a provider's author list."""
    if not isinstance(authors, list):
        return []
    names: list[str] = []
    for entry in authors:
        if isinstance(entry, dict):
            name = entry.get("name") or entry.get("display_name") or ""
        else:
            name = str(entry)
        if name and str(name).strip():
            names.append(str(name).strip())
    return names


def match_author_in_paper(
    query: str,
    paper: dict[str, Any],
    *,
    allow_initial_match: bool = True,
    allow_surname_only: bool = True,
) -> Optional[str]:
    """Return the matching author name inside *paper*, or None."""
    for candidate in _extract_names(paper.get("authors")):
        if name_matches(
            query,
            candidate,
            allow_initial_match=allow_initial_match,
            allow_surname_only=allow_surname_only,
        ):
            return candidate
    return None


def filter_by_author(
    papers: Iterable[dict[str, Any]],
    query: str,
    *,
    allow_initial_match: bool = True,
    allow_surname_only: bool = True,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Keep papers whose author list matches *query*.

    Returns:
        ``(matching_papers, matched_names)`` -- the matched names are returned
        so callers can show which renderings actually matched.
    """
    kept: list[dict[str, Any]] = []
    matched_names: list[str] = []
    for paper in papers:
        hit = match_author_in_paper(
            query,
            paper,
            allow_initial_match=allow_initial_match,
            allow_surname_only=allow_surname_only,
        )
        if hit is not None:
            kept.append(paper)
            if hit not in matched_names:
                matched_names.append(hit)
    return kept, matched_names


def sample_author_names(papers: Iterable[dict[str, Any]], limit: int = 5) -> list[str]:
    """Collect a few author names from candidate papers, for diagnostics.

    Args:
        papers: Candidate paper dicts, pre-filter.
        limit: Maximum names to return.

    Returns:
        Up to *limit* distinct author names in first-seen order.
    """
    names: list[str] = []
    for paper in papers:
        for name in _extract_names(paper.get("authors"))[:2]:
            if name not in names:
                names.append(name)
        if len(names) >= limit:
            break
    return names[:limit]


def author_match_diagnostic(
    query: str,
    papers: Iterable[dict[str, Any]],
    total_from_api: int,
    candidate_names: Optional[Iterable[str]] = None,
) -> Optional[dict[str, Any]]:
    """Explain a zero-result author search instead of returning a silent 0.

    A literal-substring filter used to return ``papers: []`` with HTTP-level
    success, which reads as "this author has no papers".  When the API did
    return candidates but none matched, this builds a diagnostic that says so
    and suggests the surname-only retry.
    """
    if total_from_api <= 0:
        return {
            "reason": "provider_returned_no_candidates",
            "query": query,
            "total_from_api": 0,
            "hint": (
                "The provider returned no records at all for this query. "
                "Check the spelling, or try the surname only."
            ),
        }

    parsed = parse_name(query)
    # Build the suggestions from the caller's original wording, so the
    # capitalisation survives instead of being echoed back lowercased.
    raw_words = [w for w in re.split(r"[\s,]+", query.strip()) if w]
    surname_len = len(parsed.surname.split()) if parsed.surname else 0
    surname_suggestion = " ".join(raw_words[-surname_len:]) if surname_len else ""
    given_suggestion = ""
    if surname_suggestion and len(raw_words) > surname_len:
        given_suggestion = f"{raw_words[0]} {surname_suggestion}"
    suggestions = [
        s for s in (surname_suggestion, given_suggestion) if s
    ]

    sample: list[str] = []
    if candidate_names is not None:
        for name in candidate_names:
            if name and name not in sample:
                sample.append(name)
            if len(sample) >= 5:
                break
    else:
        for paper in papers:
            for name in _extract_names(paper.get("authors"))[:2]:
                if name not in sample:
                    sample.append(name)
            if len(sample) >= 5:
                break

    return {
        "reason": "no_name_parts_matched",
        "query": query,
        "total_from_api": total_from_api,
        "matched_author_names": [],
        "sample_candidate_names": sample[:5],
        "suggested_queries": suggestions[:2],
        "hint": (
            "The provider returned records but none carried a matching "
            "author name. Names are indexed inconsistently (for example "
            "'Jennifer Doudna' vs 'Jennifer A. Doudna' vs 'J. Doudna'), so "
            "retry with the surname only. Set allow_initial_match=False to "
            "require an exact given-name match."
        ),
    }

