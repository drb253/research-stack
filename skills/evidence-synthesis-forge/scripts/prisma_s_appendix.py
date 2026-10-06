#!/usr/bin/env python3
"""PRISMA-S search-reporting appendix builder (stdlib only).

Turns the review's search log into a PRISMA-S-compliant appendix and FLAGS any row
that is not reproducible (missing search date, or missing hit count). A search that
cannot be re-run to the same count is a defect, not a report.

Usage:
  python3 prisma_s_appendix.py --search-log search_log.csv --outdir out \
      [--review "Agentic AI in PHC in India"]

Input CSV columns (case-insensitive; extra columns are passed through):
  source, platform, query, date_run, hits, limits, notes

Outputs: prisma_s_appendix.md ; exit 2 if any row fails reproducibility checks.
"""
import argparse
import csv
import os
import sys

REQUIRED = ["source", "query", "date_run", "hits"]
# Accept common real-world column names as aliases for the canonical ones.
ALIASES = {"source": ["database", "db", "resource"], "query": ["query_string", "strategy", "search_string"],
           "date_run": ["date", "search_date", "run_date"], "hits": ["hits_retrieved", "records", "n", "hits_returned"],
           "platform": ["interface", "via"], "limits": ["filters", "limit", "restrictions"], "notes": ["note"]}


def load(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rdr = csv.DictReader(fh)
        cols = {(c or "").strip().lower(): c for c in (rdr.fieldnames or [])}
        rows = []
        for r in rdr:
            canon = {}
            for key, alts in ALIASES.items():
                src = key if key in cols else next((a for a in alts if a in cols), None)
                canon[key] = (r.get(cols[src]) or "").strip() if src else ""
            rows.append(canon)
    return rows, cols


def main(argv=None):
    ap = argparse.ArgumentParser(description="PRISMA-S search appendix builder.")
    ap.add_argument("--search-log", required=True)
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--review", default="the review")
    args = ap.parse_args(argv)
    if not os.path.exists(args.search_log):
        ap.error("search log not found: %s" % args.search_log)

    rows, cols = load(args.search_log)
    problems = []
    for c in REQUIRED:
        if not any(a in cols for a in [c] + ALIASES.get(c, [])):
            problems.append("search log is missing the required column '%s' (or an alias of it)" % c)
    if not problems:
        for i, r in enumerate(rows, 1):
            if not r.get("date_run"):
                problems.append("row %d (%s): no date_run -> not reproducible" % (i, r.get("source", "?")))
            if not r.get("hits"):
                problems.append("row %d (%s): no hit count -> not reproducible" % (i, r.get("source", "?")))

    total = len(rows)
    md = ["# PRISMA-S search appendix", "",
          "Review: %s" % args.review, "",
          "| # | Source | Platform | Search date | Records | Limits | Query |",
          "|---:|---|---|---|---:|---|---|"]
    for i, r in enumerate(rows, 1):
        q = (r.get("query", "") or "").replace("|", "\\|")
        md.append("| %d | %s | %s | %s | %s | %s | `%s` |" % (
            i, r.get("source", ""), r.get("platform", ""), r.get("date_run", ""),
            r.get("hits", ""), r.get("limits", ""), q))
    md += ["", "## PRISMA-S item coverage", "",
           "| Item | Status |", "|---|---|",
           "| 1–2 Database / interface named | %s |" % ("yes" if "platform" in cols else "PARTIAL (no platform column)"),
           "| 3 Date each search run | %s |" % ("yes" if "date_run" in cols else "MISSING"),
           "| 5 Full search strategy per database | yes (query column) |",
           "| 6 Limits/filters | %s |" % ("yes" if "limits" in cols else "not recorded"),
           "| 16 Deduplication & totals | see prisma_flow.py counts |"]
    if problems:
        md += ["", "## REPRODUCIBILITY PROBLEMS", ""] + ["- " + p for p in problems]

    os.makedirs(args.outdir, exist_ok=True)
    out = os.path.join(args.outdir, "prisma_s_appendix.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    print("PRISMA-S appendix -> %s (%d searches)" % (out, total))
    if problems:
        print("REPRODUCIBILITY FAILURES:")
        for p in problems:
            print("  -", p)
        return 2
    print("reproducibility checks: OK (every search has a date and a hit count)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
