"""Live smoke test that avoids Semantic Scholar entirely (Crossref + local logic)."""

import json
import sys
import time

sys.path.insert(0, "/Users/drb/.local/share/academic-search-mcp/src")

from academic_search import server  # noqa: E402


def fn(name):
    f = getattr(server, name)
    return getattr(f, "fn", f)


def summarize(r):
    if isinstance(r, dict) and "error" in r:
        return r
    out = {k: v for k, v in r.items() if k not in ("papers", "filters_applied")}
    out["paper_titles"] = [(p.get("title") or "")[:78] for p in r.get("papers", [])][:5]
    return out


def run(title, func):
    t0 = time.time()
    try:
        r = func()
    except Exception as e:  # noqa: BLE001
        r = {"error": f"{type(e).__name__}: {e}"}
    print("=" * 74)
    print(f"{title}   ({time.time() - t0:.1f}s)")
    print(json.dumps(summarize(r), indent=2, default=str)[:2600])
    print()


# A) BUG 2 — relevance gate ON (new Crossref default).
run(
    "A) crossref 'base editing'  [gate ON, new default]",
    lambda: fn("search_papers")(
        "base editing", provider="crossref", limit=4, max_retrieval=200
    ),
)

# B) BUG 2 — same query, gate OFF, reproducing the old behaviour.
run(
    "B) crossref 'base editing'  [gate OFF = old behaviour]",
    lambda: fn("search_papers")(
        "base editing", provider="crossref", limit=4, max_retrieval=200,
        min_relevance=0.0,
    ),
)

# C) BUG 2 — year/date extraction from `issued`.
run(
    "C) crossref 'CRISPR base editing'  [check year + publicationDate]",
    lambda: fn("search_papers")(
        "CRISPR base editing", provider="crossref", limit=2, max_retrieval=200
    ),
)

# D) BUG 1 — the shared matcher through the Crossref provider.
run(
    "D) crossref search_by_author('Jennifer Doudna')",
    lambda: fn("search_by_author")(
        "Jennifer Doudna", provider="crossref", limit=3, max_retrieval=200
    ),
)
