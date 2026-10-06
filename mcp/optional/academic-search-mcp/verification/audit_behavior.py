"""Audit: what is still NOT working after the patch."""

import sys

sys.path.insert(0, "/Users/drb/.local/share/academic-search-mcp/src")

from academic_search import server  # noqa: E402
from academic_search.quality import is_usable_record  # noqa: E402

f = lambda n: getattr(getattr(server, n), "fn", getattr(server, n))  # noqa: E731

print("=" * 72)
print("CHECK 1: does the junk filter catch the REAL Semantic Scholar junk record?")
# Verbatim shape from the original live response that motivated fix #3.
real_junk = {
    "paperId": "00047d3348061683b2105ddad64563fdd73302c3",
    "externalIds": {"CorpusId": 250116566},
    "title": "GABA OF THE THALAMIC NUCLEUS REGULATE SLEEP SPINDLES: AN IN VIVO",
    "year": None,
    "referenceCount": 0,
    "citationCount": 0,
    "isOpenAccess": False,
    "openAccessPdf": {"url": "", "status": None, "license": None},
    "publicationTypes": None,
    "publicationDate": None,
    "journal": None,
    "authors": [],
    "abstract": None,
}
print("   is_usable_record(real_junk) =", is_usable_record(real_junk))
print("   -> expected False (junk). If True, fix #3 does NOT work in practice.")
print()

print("=" * 72)
print("CHECK 2: crossref + open_access_only=True")
try:
    r = f("search_papers")(
        "base editing", provider="crossref", limit=3, max_retrieval=100,
        open_access_only=True,
    )
    print("   returned:", r["returned_count"], "| total_from_api:", r["total_from_api"])
    print("   filter_notes:", r.get("filter_notes"))
except Exception as e:  # noqa: BLE001
    print("   error:", type(e).__name__, e)
print()

print("=" * 72)
print("CHECK 3: multi-term crossref query, how much does the gate drop?")
for q in ("base editing", "CRISPR base editing", "CRISPR base editing prime editors"):
    r = f("search_papers")(q, provider="crossref", limit=3, max_retrieval=200)
    print(
        f"   {q!r:45} api={r['total_from_api']:4} kept={r['total_after_filters']:4} "
        f"returned={r['returned_count']}"
    )
print()

print("=" * 72)
print("CHECK 4: does min_relevance=0.0 also disable the completeness ranking?")
r = f("search_papers")(
    "base editing", provider="crossref", limit=3, max_retrieval=200, min_relevance=0.0
)
print("   gate OFF  -> with_abstract_pct:", r["quality"]["with_abstract_pct"],
      "| mean_completeness:", r["quality"]["mean_completeness"])
r = f("search_papers")("base editing", provider="crossref", limit=3, max_retrieval=200)
print("   gate ON   -> with_abstract_pct:", r["quality"]["with_abstract_pct"],
      "| mean_completeness:", r["quality"]["mean_completeness"])
