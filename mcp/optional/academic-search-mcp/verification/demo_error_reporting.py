"""Demonstrate the improved upstream-failure reporting (deterministic, no waiting).

S2 is currently throttling this machine's anonymous quota, so rather than wait
out ~200s of real backoff, simulate an HTTP 429 and show the message the caller
now receives.  time.sleep is neutralised so the run is instant.
"""

import sys

sys.path.insert(0, "/Users/drb/.local/share/academic-search-mcp/src")

import requests  # noqa: E402

from academic_search.providers import semantic_scholar as ss  # noqa: E402


class FakeResponse429:
    status_code = 429
    text = "Too Many Requests"

    def raise_for_status(self):
        err = requests.exceptions.HTTPError("429 Too Many Requests")
        err.response = self
        raise err


# Neutralise backoff so the demonstration is instant.
ss.time.sleep = lambda *_: None
requests.get = lambda *a, **k: FakeResponse429()

prov = ss.SemanticScholarProvider()

print("=== BEFORE THE FIX, this produced: ===")
print('ValueError: Could not fetch seed paper \'024a2c03be8e468e7c4f9bda36cdc0eaae85fb\'')
print("   (a resolved paper id inside a 'fetch failed' message -> reads as a")
print("    bad-identifier / format problem, and the walk aborts entirely)")
print()
print("=== AFTER THE FIX ===")
prov._last_request_error = {"kind": "http_error", "status": 429, "attempt": 5}
print("actionable message:")
print("   " + prov._failure_message("resolve the seed identifier"))
print()

# And the end-to-end effect on a walk: the seed metadata fetch no longer
# aborts, and the zero-step result now explains itself.
try:
    from academic_search.providers.semantic_scholar import (
        SemanticScholarProvider,
    )

    prov2 = SemanticScholarProvider()
    # Resolution succeeds (cached), graph calls fail with 429.
    prov2._resolve_seed_identifier = lambda i: ("024a2c03be8e468e7c4fdf9bda36cdc0eaae85fb", "DOI:x")  # type: ignore
    result = prov2.explore_citations("DOI:10.1038/s41586-020-2649-2", num_steps=1)
    print("walk with throttled graph calls:")
    print("   stats:", result["stats"])
    for d in result.get("diagnostics", []):
        print("   diagnostic:", d[:190])
except Exception as e:  # noqa: BLE001
    print(f"   raised {type(e).__name__}: {e}")
