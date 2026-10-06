"""Query planning (Tier 4), source routing (Tier 5) and relevance ranking (Tier 3).

PATCHED-BY-paper-search-mcp-patches.

Why this module exists
----------------------
Measured on the user's own 41-query sweep: 6 sources produced 28 of 48 relevant
hits and the long tail produced 20, yet several sources returned 34-36 raw hits
with 0-1 relevant.  Three separate defects explain that, and none of them is a
"bad source":

* **Query fit (Tier 4).** Two-to-three-word queries under-specify a topic, so a
  source is asked the wrong question.  Retrieval benefits from an explicit
  ladder (phrase -> all-terms -> morphological -> raw) plus domain vocabulary.
* **Ill-matched sources (Tier 5).** Sending a biomedical query to a
  cryptography archive (IACR) cannot produce relevant hits; that is routing, not
  connector quality.  The long tail still yielded 20 relevant hits, so sources
  are *ranked and routed*, never dropped.
* **No ranking (Tier 3).** Results were concatenated in arrival order, so a
  perfect title match could sit below 30 weak abstract-only matches.  This
  module scores every hit against the query and re-orders them.

Stdlib only; the single network call is the free, key-free NLM MeSH lookup.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

from .source_status import and_query, clean_terms, phrase  # noqa: E402

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
# NCBI E-utilities credentials (tool + email + optional API key) come from
# config.ncbi_eutils_params -- a key raises the limit from 3 to 10 req/s.
from .config import ncbi_eutils_params

_USER_AGENT = "paper-search-mcp/0.1.4 (mailto:openags@example.com)"

#: NCBI writes the resolved controlled vocabulary into esearch's ``querytranslation``,
#: tagging each *descriptor* as ``"<label>"[MeSH Terms]`` (qualifiers are tagged
#: ``[Subheading]`` instead).  Capturing those phrases is the reliable way to read a
#: descriptor -- see the fix note in :func:`mesh_terms`.
_MESH_TERM_RE = re.compile(r'"([^"]+)"\[MeSH Terms\]', re.IGNORECASE)


def _eutils(endpoint: str, params: Dict[str, Any], timeout: float) -> Any:
    """One NCBI E-utilities JSON call (free, key-free, no registration)."""
    query = dict(params)
    query["retmode"] = "json"
    query.update(ncbi_eutils_params())
    url = f"{EUTILS_BASE}/{endpoint}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def mesh_terms(query: str, limit: int = 5, timeout: float = 15) -> List[str]:
    """Free controlled-vocabulary expansion via the NCBI MeSH database.

    MeSH resolves *entry terms*, which is why this uses E-utilities rather than
    the NLM descriptor-label endpoint (measured: ``label=heart attack`` returns
    ``[]`` and per-term contains-matching returns noise such as "American Heart
    Association", whereas ``db=mesh`` resolves it to ``Myocardial Infarction``
    plus its synonyms).

    Every failure path returns ``[]``: planning must never break a search.
    """
    terms = clean_terms(query)
    if not terms:
        return []

    # The whole phrase first ("heart attack" is one entry term), then single terms.
    candidates: List[str] = []
    body = phrase(terms)
    if body:
        candidates.append(body)
    candidates.extend(terms[:4])

    found: List[str] = []
    for candidate in candidates:
        try:
            search = _eutils(
                "esearch.fcgi",
                {"db": "mesh", "term": candidate, "retmax": 3},
                timeout,
            )
            result = search.get("esearchresult") or {}
            # Authoritative mapping first.  NCBI resolves the query to controlled
            # vocabulary and reports it in ``querytranslation``, tagging descriptors
            # as ``[MeSH Terms]``.  Reading ``ds_meshterms`` from the first esummary
            # record instead is unsafe: for a common word it returns a *qualifier*
            # (subheading) entry, whose entry terms are not descriptors -- measured,
            # "screening" resolved to the qualifier "diagnosis" and injected its entry
            # terms ("signs", "findings", "symptoms") into the search strategy.
            for label in _MESH_TERM_RE.findall(result.get("querytranslation") or ""):
                text = label.strip()
                if text and text.lower() != candidate.lower() and text not in found:
                    found.append(text)
            if found:
                break

            ids = result.get("idlist") or []
            if not ids:
                continue

            summary = _eutils(
                "esummary.fcgi",
                {"db": "mesh", "id": ",".join(str(i) for i in ids)},
                timeout,
            )
            sresult = summary.get("result") or {}
            for uid in ids:
                record = sresult.get(str(uid)) or {}
                if not isinstance(record, dict):
                    continue
                # Fallback only: never expand to a qualifier/subheading.  A qualifier
                # record (recordtype "qualifier" or a MeSH UI beginning with "Q") lists
                # a subheading's entry terms, which are not valid descriptors and must
                # never enter a search strategy.
                record_type = str(record.get("ds_recordtype", "")).lower()
                mesh_ui = str(record.get("ds_meshui", "")).upper()
                if record_type == "qualifier" or mesh_ui.startswith("Q"):
                    continue
                for label in (record.get("ds_meshterms") or [])[:limit]:
                    text = str(label or "").strip()
                    if text and text.lower() != candidate.lower() and text not in found:
                        found.append(text)
                if found:
                    break
        except Exception as exc:
            logger.debug("MeSH lookup failed for %r: %s", candidate, exc)
            continue

        if found:
            break

    return found[:limit]


# --------------------------------------------------------------------------- #
# Tier 4 -- query planning
# --------------------------------------------------------------------------- #

_VOWELS = frozenset("aeiou")

#: Suffixes where appending a plural is meaningless or wrong (editing, reached,
#: analysis, physics, virus, class, basis, Chinese, porous).
_NO_PLURAL = ("ing", "ed", "sis", "ics", "us", "ss", "is", "ese", "ous", "ism")


def singular_plural_variants(term: str) -> List[str]:
    """Morphological variants of one term (plural rules, revised for English).

    Verified on the sweep's vocabulary: ``biomarker -> biomarkers``,
    ``therapy -> therapies``, ``analysis``/``editing`` -> no variant (wrong to
    pluralise).  These feed a single recall rung only, never the raw query.
    """
    low = term.lower()
    if len(term) < 4 or low.endswith(_NO_PLURAL):
        return []
    if low.endswith("y") and len(term) > 3 and term[-2].lower() not in _VOWELS:
        return [term[:-1] + "ies"]
    if low.endswith(("s", "x", "z", "ch", "sh")):
        return [term + "es"]
    return [term + "s"]


def morphological_query(terms: Sequence[str]) -> str:
    """``(CRISPR OR CRISPRs) AND (base OR bases) AND editing``.

    An AND of per-term OR-groups: every concept must still be present, but any
    of its forms may satisfy it -- a recall rung, not an OR soup.
    """
    groups: List[str] = []
    for term in terms:
        variants = singular_plural_variants(term)
        if variants:
            groups.append(f"({term} OR {' OR '.join(variants)})")
        else:
            groups.append(term)
    return " AND ".join(groups)


def query_variants(query: str) -> List[Dict[str, Any]]:
    """Build the retrieval ladder for one user query, most precise first.

    ``kind`` labels the rung so callers can report which one produced a hit.
    """
    terms = clean_terms(query)
    variants: List[Dict[str, Any]] = []

    body = phrase(terms)
    if body:
        variants.append({"kind": "phrase", "query": f'"{body}"', "terms": terms})

    joined = and_query(terms)
    if joined:
        variants.append({"kind": "all_terms", "query": joined, "terms": terms})

    expanded = morphological_query(terms)
    if expanded and expanded.lower() != joined.lower():
        variants.append({"kind": "morphological", "query": expanded, "terms": terms})

    raw = str(query or "").strip()
    if raw:
        variants.append({"kind": "raw", "query": raw, "terms": terms})

    seen = set()
    unique: List[Dict[str, Any]] = []
    for item in variants:
        key = item["query"].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


# --------------------------------------------------------------------------- #
# Tier 5 -- source routing
# --------------------------------------------------------------------------- #

#: Domain -> sources in priority order.  Routing re-orders effort only; nothing
#: is dropped, because the sweep's long tail contributed 20 of 48 relevant hits.
DOMAIN_SOURCES: Dict[str, List[str]] = {
    "biomedical": ["pubmed", "europepmc", "pmc", "clinicaltrials", "ictrp", "ctis", "bookshelf", "biorxiv", "medrxiv",
                   "openalex", "crossref", "core", "semantic", "doaj"],
    "life_sciences": ["biorxiv", "clinicaltrials", "bookshelf", "pubmed", "europepmc", "pmc", "openalex",
                      "semantic", "figshare", "zenodo", "core", "doaj"],
    "cryptography": ["iacr", "arxiv", "semantic", "crossref", "openalex"],
    "chemistry": ["chemrxiv", "crossref", "openalex", "core", "semantic", "doaj",
                  "zenodo", "figshare"],
    "computer_science": ["arxiv", "semantic", "openalex", "crossref", "core"],
    "physics_math": ["arxiv", "semantic", "openalex", "crossref", "zenodo"],
    "policy_public_health": ["whoris", "clinicaltrials", "ictrp", "pubmed", "europepmc", "openalex",
                             "crossref", "doaj"],
    "preprints": ["biorxiv", "medrxiv", "osf", "arxiv", "zenodo", "openaire"],
    "datasets_software": ["datacite", "zenodo", "figshare", "osf", "openaire"],
    "humanities_social": ["ssrn", "hal", "jstage", "doaj", "openaire", "crossref"],
    "japan_regional": ["jstage", "crossref", "openalex", "doaj"],
    "cross_domain": ["openalex", "crossref", "core", "semantic", "doaj",
                     "openaire", "europepmc"],
}

_DOMAIN_PATTERNS: List[Tuple[str, Tuple[str, ...]]] = [
    ("cryptography", ("cryptograph", "cipher", "zero-knowledge", "zk-snark",
                      "post-quantum", "lattice", "homomorphic", "signature scheme",
                      "block cipher", "hash function", "secure multiparty")),
    ("biomedical", ("crispr", "gene", "genome", "protein", "cell", "clinical",
                    "patient", "disease", "cancer", "drug", "therapy", "vaccine",
                    "covid", "sars", "mrna", "antibody", "tumor", "tumour",
                    "in vivo", "in vitro", "receptor", "enzyme", "biomarker",
                    "cohort", "trial", "diagnos", "epidemiolog")),
    ("chemistry", ("catalys", "synthesis", "electrochem", "polymer", "spectroscop",
                   "ligand", "solvent", "organic chem", "inorganic chem",
                   "physical chem", "reaction mechanism", "chemrxiv")),
    ("preprints", ("preprint", "not yet peer")),
    ("datasets_software", ("dataset", "software release", "benchmark data")),
    ("humanities_social", ("economic", "historical", "discourse", "qualitative",
                           "sociolog", "education", "linguistic", "philosoph")),
    ("computer_science", ("machine learning", "neural network", "transformer",
                          "algorithm", "database", "compiler", "distributed system",
                          "robotics", "quantum computing")),
    ("physics_math", ("physics", "quantum", "topolog", "manifold", "theorem",
                      "astro", "particle", "cosmolog", "relativity")),
    ("policy_public_health", ("policy", "guideline", "world health", "governance",
                              "regulation", "surveillance", "public health",
                              "outbreak")),
    ("life_sciences", ("ecology", "evolution", "species", "plant", "microbiome",
                       "transcriptom", "proteom", "sequencing", "phylogen")),
]


def classify_domain(query: str) -> str:
    """Best-effort topic domain for a free-text query (never raises)."""
    text = " " + str(query or "").lower() + " "
    for domain, needles in _DOMAIN_PATTERNS:
        for needle in needles:
            if needle in text:
                return domain
    return "cross_domain"


def route_sources(
    query: str,
    domain: Optional[str] = None,
    limit: int = 0,
    all_sources: Optional[Sequence[str]] = None,
    retired_sources: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Order sources by likely relevance to a query's domain.

    Returns ``{"domain", "sources", "rationale"}``.  ``limit=0`` keeps every
    source (routing re-orders, it never drops, because the tail is productive).
    """
    resolved = (domain or "").strip().lower() or classify_domain(query)
    if resolved not in DOMAIN_SOURCES:
        resolved = "cross_domain"

    ordered = list(DOMAIN_SOURCES[resolved])

    # Append anything missing so no caller-visible source is ever lost.
    retired = set(retired_sources or ())
    for source in (all_sources or ()):
        if source not in ordered and source not in retired:
            ordered.append(source)

    if limit and limit > 0:
        ordered = ordered[:limit]

    return {
        "domain": resolved,
        "sources": ordered,
        "rationale": (
            f"'{resolved}' query: {', '.join(ordered[:5])} first, "
            "remaining sources appended (nothing dropped)."
        ),
    }


# --------------------------------------------------------------------------- #
# Tier 3 -- relevance ranking
# --------------------------------------------------------------------------- #

TITLE_WEIGHT = 2.0        # user-specified: a title match outweighs the abstract
ABSTRACT_WEIGHT = 1.0
META_WEIGHT = 0.5         # keywords / categories / venue
PHRASE_TITLE_BONUS = 3.0  # the exact query phrase occurring in the title
ALL_TERMS_TITLE_BONUS = 2.0
ALL_TERMS_SOMEWHERE_BONUS = 0.5

BAND_HIGH = "high"
BAND_MEDIUM = "medium"
BAND_LOW = "low"

_WORD_RE_CACHE: Dict[str, "re.Pattern[str]"] = {}


def _term_pattern(term: str) -> "re.Pattern[str]":
    """Word-boundary-anywhere, prefix-tolerant matcher for one query term."""
    pattern = _WORD_RE_CACHE.get(term)
    if pattern is None:
        pattern = re.compile(r"(?<!\w)" + re.escape(term) + r"\w*", re.IGNORECASE)
        _WORD_RE_CACHE[term] = pattern
    return pattern


def _normalized(text: Any) -> str:
    return " ".join(str(text or "").lower().split())


def _paper_field(paper: Any, *keys: str) -> str:
    """Join several paper fields into one searchable string."""
    if isinstance(paper, dict):
        parts = [paper.get(key) for key in keys]
    else:
        parts = [getattr(paper, key, None) for key in keys]
    return _normalized(" ".join(str(p) for p in parts if p))


def relevance_score(
    paper: Any,
    query: str,
    terms: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Score one hit against the query.

    Weights (per the agreed design): title match 2.0x, abstract 1.0x, metadata
    0.5x, plus a phrase-in-title bonus and an all-terms-in-title bonus.  Returns
    ``score``, ``band``, ``matched_terms`` and a human ``why`` string so a reader
    can see *why* a hit ranked where it did.
    """
    term_list = [t for t in (terms if terms is not None else clean_terms(query)) if t]
    if not term_list:
        return {"score": 0.0, "band": BAND_LOW, "matched_terms": [], "why": "empty query"}

    title = _paper_field(paper, "title")
    abstract = _paper_field(paper, "abstract")
    meta = _paper_field(paper, "keywords", "categories", "extra", "journal", "source")

    def hits(text: str) -> List[str]:
        return [t for t in term_list if text and _term_pattern(t).search(text)]

    title_hits = hits(title)
    abstract_hits = hits(abstract)
    meta_hits = hits(meta)

    title_fraction = len(title_hits) / len(term_list)
    abstract_fraction = len(abstract_hits) / len(term_list)
    meta_fraction = len(meta_hits) / len(term_list)

    phrase_text = _normalized(query.strip().strip('"'))
    phrase_in_title = bool(phrase_text) and phrase_text in title
    all_in_title = len(title_hits) == len(term_list)
    all_somewhere = len(set(title_hits) | set(abstract_hits)) == len(term_list)

    score = (
        TITLE_WEIGHT * title_fraction
        + ABSTRACT_WEIGHT * abstract_fraction
        + META_WEIGHT * meta_fraction
    )
    reasons: List[str] = []
    if phrase_in_title:
        score += PHRASE_TITLE_BONUS
        reasons.append("exact phrase in title")
    if all_in_title:
        score += ALL_TERMS_TITLE_BONUS
        reasons.append("all terms in title")
    if all_somewhere and not all_in_title:
        score += ALL_TERMS_SOMEWHERE_BONUS
        reasons.append("all terms in title+abstract")

    if phrase_in_title or all_in_title:
        band = BAND_HIGH
    elif title_fraction >= 0.6 or all_somewhere:
        band = BAND_MEDIUM
    else:
        band = BAND_LOW

    if not reasons:
        if title_hits:
            reasons.append(f"{len(title_hits)}/{len(term_list)} terms in title")
        elif abstract_hits:
            reasons.append(f"{len(abstract_hits)}/{len(term_list)} terms in abstract")
        else:
            reasons.append("no query term found in title or abstract")

    return {
        "score": round(score, 3),
        "band": band,
        "matched_terms": title_hits or abstract_hits or meta_hits,
        "why": "; ".join(reasons),
    }


def rank_papers(
    papers: Iterable[Dict[str, Any]],
    query: str,
    annotate: bool = True,
) -> List[Dict[str, Any]]:
    """Order hits by relevance to ``query`` (highest first, stable).

    ``annotate`` adds ``relevance_score`` / ``relevance_band`` / ``match_why`` /
    ``low_confidence`` to each returned paper so the ranking is inspectable
    rather than implicit.
    """
    terms = clean_terms(query)
    scored: List[Tuple[float, int, Dict[str, Any]]] = []

    for index, paper in enumerate(papers or []):
        result = relevance_score(paper, query, terms)
        item = dict(paper) if annotate else paper
        if annotate:
            item["relevance_score"] = result["score"]
            item["relevance_band"] = result["band"]
            item["matched_terms"] = result["matched_terms"]
            item["match_why"] = result["why"]
            item["low_confidence"] = result["band"] == BAND_LOW
        scored.append((result["score"], -index, item))

    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [row[2] for row in scored]


def band_summary(papers: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """Count hits per relevance band (for the search response header)."""
    summary = {BAND_HIGH: 0, BAND_MEDIUM: 0, BAND_LOW: 0}
    for paper in papers or []:
        band = paper.get("relevance_band") or BAND_LOW
        summary[band] = summary.get(band, 0) + 1
    return summary
