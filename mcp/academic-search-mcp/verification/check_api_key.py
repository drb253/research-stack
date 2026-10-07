"""Verify the S2 API key fixes the previously failing path (run WITH S2_API_KEY set)."""

import json
import sys
import time

sys.path.insert(0, "/Users/drb/.local/share/academic-search-mcp/src")

from academic_search import server  # noqa: E402
from academic_search.providers.semantic_scholar import (  # noqa: E402
    API_DELAY,
    _api_headers,
)

f = lambda n: getattr(getattr(server, n), "fn", getattr(server, n))  # noqa: E731

headers = _api_headers()
print("auth header present:", "x-api-key" in headers)
print("API_DELAY (s between requests):", API_DELAY, "-> max", round(1 / API_DELAY, 2), "req/s")
print()

# 1) The path that failed with 429 before the key.
print("=== explore_citations, DOI-prefixed seed (previously 429) ===")
t0 = time.time()
try:
    r = f("explore_citations")(
        "DOI:10.1038/s41586-020-2649-2",
        num_steps=2,
        max_depth=1,
        direction_choice="forward",
    )
    print(f"OK in {time.time() - t0:.1f}s")
    print("  seed:", r["seed_paper_id"])
    print("  stats:", r["stats"])
    print("  edges:", len(r["edges"]), "| path length:", len(r["path"]))
    print("  diagnostics:", r.get("diagnostics"))
except Exception as e:  # noqa: BLE001
    print(f"FAILED after {time.time() - t0:.1f}s -> {type(e).__name__}: {str(e)[:300]}")
print()

# 2) Author search (the original bug #1).
print("=== search_by_author('Jennifer Doudna') ===")
t0 = time.time()
try:
    r = f("search_by_author")("Jennifer Doudna", limit=3, max_retrieval=100)
    print(f"OK in {time.time() - t0:.1f}s")
    print("  total_from_api:", r["total_from_api"])
    print("  total_after_author_filter:", r["total_after_author_filter"])
    print("  matched_author_names:", r["matched_author_names"])
except Exception as e:  # noqa: BLE001
    print(f"FAILED -> {type(e).__name__}: {str(e)[:300]}")
print()

# 3) PubMed-form seed, a form the old code could not even attempt.
print("=== explore_citations with an arXiv id ===")
t0 = time.time()
try:
    r = f("explore_citations")(
        "2006.10256", num_steps=1, max_depth=1, direction_choice="backward"
    )
    print(f"OK in {time.time() - t0:.1f}s | seed:", r["seed_paper_id"])
    print("  steps:", r["stats"]["steps_completed"], "| edges:", len(r["edges"]))
    print("  diagnostics:", r.get("diagnostics"))
except Exception as e:  # noqa: BLE001
    print(f"FAILED -> {type(e).__name__}: {str(e)[:300]}")
