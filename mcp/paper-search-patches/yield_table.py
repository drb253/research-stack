#!/usr/bin/env python3
"""Per-source yield table: raw hits, relevant hits, yield %, false positives.

'relevant' = hits scoring medium/high on the Tier-3 scorer (all query terms
present in title or abstract, weighted toward the title). That is an automatic
proxy for human judgment, applied identically to every source.
"""
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.disable(logging.CRITICAL)
sys.path.insert(0, "/Users/drb/.local/share/uv/tools/paper-search-mcp/lib/python3.11/site-packages")

from paper_search_mcp import server
from paper_search_mcp.source_status import SourceUnavailable
from paper_search_mcp.query_planning import relevance_score

CROSS = "CRISPR base editing"
GARBAGE = "zzzqqq xylophone nonexistent"

# A domain-appropriate query, so a specialised source is judged on its own turf.
DOMAIN = {
    "iacr": "lattice-based cryptography",
    "arxiv": "lattice-based cryptography",
    "whoris": "malaria treatment guidelines",
    "ssrn": "corporate governance reform",
    "jstage": "graphene oxide synthesis",
    "hal": "single-cell RNA sequencing",
    "openaire": "single-cell RNA sequencing",
    "doaj": "single-cell RNA sequencing",
    "semantic": "machine learning interpretability",
    "crossref": "machine learning interpretability",
    "core": "machine learning interpretability",
    "openalex": "machine learning interpretability",
    "figshare": "single-cell RNA sequencing",
    "datacite": "single-cell RNA sequencing",
    "osf": "single-cell RNA sequencing",
    "zenodo": "single-cell RNA sequencing",
    "europepmc": "single-cell RNA sequencing",
    "pubmed": "single-cell RNA sequencing",
    "pmc": "single-cell RNA sequencing",
    "biorxiv": "single-cell RNA sequencing",
    "medrxiv": "single-cell RNA sequencing",
    "plos": "single-cell RNA sequencing",
    "unpaywall": "10.1038/s41586-021-03534-y",
}

HEADER = f"{'source':<12}{'query run (domain)':<34}{'raw':>5}{'rel':>5}{'yield':>8}{'garbage':>9}"


def measure(name):
    searcher = getattr(server, f"{name}_searcher", None)
    if searcher is None:
        return name, DOMAIN.get(name, CROSS), "no-searcher", "", "", ""

    domain_query = DOMAIN.get(name, CROSS)
    queries = [domain_query]
    if domain_query != CROSS:
        queries.append(CROSS)

    raw = relevant = 0
    unavailable = ""
    for query in queries:
        try:
            papers = searcher.search(query, max_results=5)
        except SourceUnavailable as exc:
            unavailable = f"UNAVAIL({exc.http_status})"
            continue
        except Exception as exc:
            unavailable = f"EXC:{type(exc).__name__}"
            continue
        raw += len(papers)
        relevant += sum(
            1 for paper in papers
            if relevance_score(paper, query)["band"] in ("high", "medium")
        )

    garbage_hits = ""
    try:
        garbage_hits = str(len(searcher.search(GARBAGE, max_results=5)))
    except SourceUnavailable as exc:
        garbage_hits = f"UNAVAIL({exc.http_status})"
    except Exception as exc:
        garbage_hits = f"EXC:{type(exc).__name__}"

    if unavailable and raw == 0:
        yield_pct = unavailable
    elif raw == 0:
        yield_pct = "0/0"
    else:
        yield_pct = f"{100 * relevant / raw:.0f}%"
    return name, domain_query, str(raw), str(relevant), yield_pct, garbage_hits


print(HEADER, flush=True)
print("-" * len(HEADER), flush=True)

targets = [n for n in server.ALL_SOURCES if server._is_active_source(n)]
rows = {}
with ThreadPoolExecutor(max_workers=10) as pool:
    futures = [pool.submit(measure, name) for name in targets]
    for future in as_completed(futures):
        name, query, raw, rel, yield_pct, garbage = future.result()
        rows[name] = (query, raw, rel, yield_pct, garbage)
        print(f"{name:<12}{query[:33]:<34}{raw:>5}{rel:>5}{yield_pct:>8}{garbage:>9}", flush=True)

tot_raw = sum(int(r[1]) for r in rows.values() if r[1].isdigit())
tot_rel = sum(int(r[2]) for r in rows.values() if r[2].isdigit())
print("-" * len(HEADER), flush=True)
print(
    f"{'TOTAL':<12}{len(rows)} sources{'':<20}{tot_raw:>5}{tot_rel:>5}"
    f"{(f'{100 * tot_rel / tot_raw:.0f}%' if tot_raw else '-'):>8}"
    f"{sum(int(r[4]) for r in rows.values() if r[4].isdigit()):>9}",
    flush=True,
)
