"""Live smoke test for the patched academic-search MCP (real network calls)."""

import json
import sys
import time

sys.path.insert(0, "/Users/drb/.local/share/academic-search-mcp/src")

from academic_search import server  # noqa: E402


def fn(name):
    """FastMCP may wrap tools; unwrap to the plain function."""
    f = getattr(server, name)
    return getattr(f, "fn", f)


def summarize(r):
    if isinstance(r, dict) and "error" in r:
        return r
    out = {k: v for k, v in r.items() if k not in ("papers", "filters_applied")}
    out["paper_titles"] = [(p.get("title") or "")[:72] for p in r.get("papers", [])][:5]
    return out


def run(title, func):
    t0 = time.time()
    try:
        r = func()
    except Exception as e:  # noqa: BLE001
        r = {"error": f"{type(e).__name__}: {e}"}
    print("=" * 72)
    print(f"{title}   ({time.time() - t0:.1f}s)")
    print(json.dumps(summarize(r), indent=2, default=str)[:3000])
    print()
    return r


# 1) BUG 1 — full-name author lookup used to return 0 rows.
run(
    "1) search_by_author('Jennifer Doudna')  [was: 0 results]",
    lambda: fn("search_by_author")("Jennifer Doudna", limit=3, max_retrieval=300),
)

# 2) BUG 2 — Crossref relevance gate ON (new default for crossref).
run(
    "2) crossref 'base editing' min_relevance=1.0  [denture should be gone]",
    lambda: fn("search_papers")(
        "base editing", provider="crossref", limit=3, max_retrieval=200
    ),
)

# 3) BUG 2 — same query with the gate OFF, to show the old behaviour.
run(
    "3) crossref 'base editing' min_relevance=0.0  [old behaviour]",
    lambda: fn("search_papers")(
        "base editing", provider="crossref", limit=3, max_retrieval=200,
        min_relevance=0.0,
    ),
)

# 4) BUG 4 — 'DOI:' prefixed seed, the form I misdiagnosed earlier.
run(
    "4) explore_citations('DOI:10.1038/s41586-020-2649-2')",
    lambda: fn("explore_citations")(
        "DOI:10.1038/s41586-020-2649-2", num_steps=1, max_depth=1,
        direction_choice="forward",
    ),
)

# 5) BUG 4 — a bare arXiv id, a form the old code could not seed at all.
run(
    "5) explore_citations('2006.10256')  [arXiv form]",
    lambda: fn("explore_citations")(
        "2006.10256", num_steps=1, max_depth=1, direction_choice="forward"
    ),
)

# 6) BUG 3 — junk handling is visible in stats.
run(
    "6) get_paper_stats('CRISPR base editing')",
    lambda: fn("get_paper_stats")("CRISPR base editing", max_retrieval=120),
)
