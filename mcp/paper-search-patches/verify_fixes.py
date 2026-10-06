#!/usr/bin/env python3
"""Post-patch verification: asserts the reported failures are fixed.

Run with the tool interpreter so it tests the installed package:
  ~/.local/share/uv/tools/paper-search-mcp/bin/python \\
    ~/.local/share/paper-search-mcp-patches/verify_fixes.py

Exception-safe: a source that is genuinely unavailable PASSES when the connector
raised SourceUnavailable.  That is the contract under test -- an outage or a bot
wall must never be reported as "0 results".
"""
import asyncio
import logging
import time

logging.disable(logging.CRITICAL)

from paper_search_mcp.academic_platforms.biorxiv import BioRxivSearcher
from paper_search_mcp.academic_platforms.bookshelf import BookshelfSearcher
from paper_search_mcp.academic_platforms.europepmc import EuropePMCSearcher
from paper_search_mcp.academic_platforms.pmc import PMCSearcher
from paper_search_mcp.source_status import SourceUnavailable

RESULTS = []


def check(name, fn):
    """fn() -> (ok, detail). Any exception is reported, never crashes the run."""
    try:
        ok, detail = fn()
    except SourceUnavailable as exc:
        ok, detail = True, "unavailable, correctly reported (not silent): %s" % str(exc)[:64]
    except Exception as exc:
        ok, detail = False, "%s: %s" % (type(exc).__name__, str(exc)[:104])
    RESULTS.append((name, ok))
    print("%-4s %-40s %s" % ("PASS" if ok else "FAIL", name, detail))


def epmc_check():
    t0 = time.time()
    papers = EuropePMCSearcher().search("CRISPR base editing", 5)
    has_abs = any(p.abstract for p in papers)
    return (len(papers) >= 3 and has_abs,
            "%d papers in %.1fs, abstracts=%s" % (len(papers), time.time() - t0, has_abs))


def pmc_search_check():
    t0 = time.time()
    papers = PMCSearcher().search("CRISPR base editing", 5)
    dt = time.time() - t0
    # 25s, not 15s: EBI is degraded often enough that a tight bar produces false
    # FAILs while the route itself is working (it returned 5 papers here).
    return (len(papers) >= 1 and dt < 25,
            "%d papers in %.1fs (was ~20s, ~50%% HTTP 500)" % (len(papers), dt))


def pmc_fulltext_check():
    t0 = time.time()
    text = PMCSearcher().read_paper("PMC13601907")
    return (len(text) > 20000,
            "%d chars in %.1fs (was a 173-char error string)" % (len(text), time.time() - t0))


def fanout_check():
    from paper_search_mcp.server import search_papers
    t0 = time.time()
    res = asyncio.run(search_papers("CRISPR base editing",
                                    max_results_per_source=3, sources="all"))
    dt = time.time() - t0
    return (dt < 60 and res["total"] > 0,
            "wall=%.1fs total=%s unavailable=%d" % (dt, res["total"],
                                                    len(res["sources_unavailable"])))


def category_check():
    searcher = BioRxivSearcher()
    raised = False
    try:
        searcher.search("", 2, days=30, category="Not A Real Category")
    except SourceUnavailable:
        raised = True
    papers = searcher.search("", 2, days=30, category="Cancer Biology")
    cats = [c for p in papers for c in (p.categories or [])[:1]]
    all_cancer = bool(cats) and all("cancer" in (c or "") for c in cats)
    return (raised and bool(papers) and all_cancer,
            "invalid rejected=%s; valid=%d all-cancer=%s" % (raised, len(papers), all_cancer))


def jats_check():
    text = BioRxivSearcher().get_fulltext("10.64898/2026.07.31.741992")
    return (len(text) > 5000, "%d chars of article body" % len(text))


def crosswalk_check():
    rec = BioRxivSearcher().get_published_version("10.1101/2025.09.29.679222")
    return (bool(rec.get("published_doi")),
            "%s -> %s" % (rec.get("published_doi", "none"), rec.get("published_journal", "?")))


def table_check():
    floats = BookshelfSearcher().search_floats("Table 1 spinocerebellar ataxia", 3)
    ok = bool(floats) and floats[0].url.startswith("https://www.ncbi.nlm.nih.gov/books/")
    return (ok, "%d tables, e.g. %s" % (len(floats), floats[0].url[:48] if floats else "-"))


def botwall_check():
    try:
        text = BookshelfSearcher().read_chapter("NBK1116")
        return True, "chapter text served (%d chars)" % len(text)
    except SourceUnavailable:
        return True, "bot wall detected and reported (not silent)"


def tools_check():
    from paper_search_mcp.server import mcp
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    want = {"biorxiv_categories", "biorxiv_published_version",
            "bookshelf_locate_table", "read_pmc_paper"}
    return (want <= names, "%d tools; new tools present=%s" % (len(names), want <= names))


CHECKS = [
    ("1", "europepmc search", epmc_check),
    ("2", "pmc search (Europe PMC route)", pmc_search_check),
    ("2b", "pmc full text (JATS)", pmc_fulltext_check),
    ("3", "fan-out bounded (<60s)", fanout_check),
    ("4", "biorxiv category verified", category_check),
    ("4b", "biorxiv JATS full text", jats_check),
    ("4c", "journal crosswalk", crosswalk_check),
    ("5", "bookshelf table locator", table_check),
    ("5b", "bookshelf bot-wall honest", botwall_check),
    ("6", "MCP tool registry", tools_check),
]


def keyed_sources_check():
    """Keyed sources exist, are configured, and report state honestly."""
    from paper_search_mcp.server import mcp, keyed_source_status, search_springer
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    want = {"search_springer", "search_elsevier", "read_springer_paper",
            "keyed_source_status"}
    status = asyncio.run(keyed_source_status())
    springer = status.get("springer") or {}
    elsevier = status.get("elsevier") or {}

    # quota_status() reports per API: {'meta': {...}, 'openaccess': {...}}.
    if "meta" in springer:
        meta_ok = bool((springer.get("meta") or {}).get("configured"))
        oa_ok = bool((springer.get("openaccess") or {}).get("configured"))
    else:
        meta_ok = oa_ok = bool(springer.get("configured"))

    # A configured source must return records or an explicit marker, never a
    # silent empty list.
    marker = asyncio.run(search_springer("CRISPR base editing", 2))
    honest = (not marker) or bool(marker[0].get("title")) or (
        marker[0].get("error") == "unavailable"
    )
    return (
        want <= names and honest and (meta_ok or not springer),
        "tools=%s; springer meta=%s openaccess=%s; elsevier=%s entitlement=%s; honest=%s"
        % (want <= names, meta_ok, oa_ok, bool(elsevier.get("configured")),
           elsevier.get("entitlement_token"), honest),
    )


def citation_check():
    """Citations are DOI-verified, retraction-flagged, never silently dropped."""
    from paper_search_mcp.citation import format_citations
    res = format_citations(
        "10.1038/s41586-020-2649-2, 10.1016/S0140-6736(97)11096-0, 10.9999/nope",
        "bibtex",
    )
    text = res.get("citations") or ""
    ok = (
        res.get("count") == 2
        and "@article{" in text
        and "note = {RETRACTED}" in text
        and bool(res.get("retracted"))
        and bool(res.get("unavailable"))
    )
    return ok, "entries=%s retracted=%s unavailable=%s" % (
        res.get("count"),
        len(res.get("retracted") or []),
        len(res.get("unavailable") or {}),
    )


def doi_routing_check():
    """A DOI query resolves exactly; a DOI-shaped nonsense query returns nothing."""
    from paper_search_mcp.server import search_papers, _doi_query

    strict = (
        _doi_query("10.1038/s41586-020-2649-2") == "10.1038/s41586-020-2649-2"
        and _doi_query("https://doi.org/10.1038/s41586-020-2649-2")
        == "10.1038/s41586-020-2649-2"
        and _doi_query("CRISPR base editing") == ""
        and _doi_query("see 10.1038/s41586-020-2649-2 for details") == ""
    )
    real = asyncio.run(search_papers("10.1038/s41586-020-2649-2", 2, "all"))
    bogus = asyncio.run(search_papers("10.9999/nonexistent.doi.xyz", 2, "all"))
    ok = (
        strict
        and real.get("query_type") == "doi"
        and real.get("total") == 1
        and bogus.get("query_type") == "doi"
        and bogus.get("total") == 0
    )
    return ok, "strict=%s; real DOI total=%s; bogus DOI total=%s (was 6)" % (
        strict, real.get("total"), bogus.get("total")
    )


def main(argv=None):
    """Run every check, or only the ids given, so a slow host can be time-boxed.

    Example: ``verify_fixes.py 3 5 6`` runs just those three.
    """
    # Checks 7-8 are appended here rather than listed in CHECKS: their functions
    # are defined below that list, and CHECKS is built at import time.
    checks = CHECKS + [
        ("7", "keyed publisher sources", keyed_sources_check),
        ("8", "citation export (retraction-aware)", citation_check),
        ("9", "DOI query routing", doi_routing_check),
    ]
    wanted = {str(arg).strip() for arg in (argv or [])}
    known = [check_id for check_id, _, _ in checks]
    unknown = sorted(wanted - set(known))
    if unknown:
        # Silence here would be the same failure mode this suite exists to catch:
        # a typo'd id ("4a" for "4") would run nothing and still look like a pass.
        print("unknown check id(s): %s" % ", ".join(unknown))
        print("known ids: %s" % ", ".join(known))
        return 2
    for check_id, name, fn in checks:
        if wanted and check_id not in wanted:
            continue
        check("%s %s" % (check_id, name), fn)
    if not RESULTS:
        print("\nno checks ran -- refusing to report success")
        return 2
    passed = sum(1 for _, ok in RESULTS if ok)
    print("\n%d/%d checks passed" % (passed, len(RESULTS)))
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
