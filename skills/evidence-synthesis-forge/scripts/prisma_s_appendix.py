#!/usr/bin/env python3
"""PRISMA-S search-reporting appendix builder (stdlib only).

Turns the review's search log into a PRISMA-S-compliant appendix and FLAGS any row
that is not reproducible (missing search date, or missing hit count). A search that
cannot be re-run to the same count is a defect, not a report.

It also keeps two conditions apart that used to look identical in the artifact:

  * a source that was searched and returned nothing  -> `0` records, a finding;
  * a source that was never reached (`source_status=unavailable`) -> `unavailable`,
    an input gap, and the run exits 3.

Rendering an unavailable database as `0` publishes a coverage gap as evidence of
absence, which is what sysreview's own rule forbids: "A source that is down must
never look like a source that found nothing."

Usage:
  python3 prisma_s_appendix.py --search-log search_log.csv --outdir out \
      [--review "Agentic AI in PHC in India"] [--allow-insufficient]

Input CSV columns (case-insensitive; extra columns are passed through):
  source, platform, query, date_run, hits, limits, notes, source_status, availability

Outputs: prisma_s_appendix.md ; exit 2 if any row fails reproducibility checks,
exit 3 if any source could not be reached.
"""
import argparse
import csv
import json
import os
import sys

REQUIRED = ["source", "query", "date_run", "hits"]
# Accept common real-world column names as aliases for the canonical ones.
ALIASES = {"source": ["database", "db", "resource"], "query": ["query_string", "strategy", "search_string"],
           "date_run": ["date", "search_date", "run_date"], "hits": ["hits_retrieved", "records", "n", "hits_returned"],
           "platform": ["interface", "via"], "limits": ["filters", "limit", "restrictions"], "notes": ["note"],
           "source_status": ["availability", "status", "retrieval_status", "source_availability"]}

#: Values of source_status that mean the source was actually queried. Anything else means we
#: did not reach it, so its hit count is unknown rather than zero.
REACHED_STATUSES = {"", "available", "ok", "searched", "returned", "success", "complete"}
UNREACHABLE_STATUSES = {"unavailable", "error", "failed", "timeout", "not_available", "down"}


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


def is_unreachable(row):
    status = (row.get("source_status") or "").strip().lower()
    if status in UNREACHABLE_STATUSES:
        return True
    # An unrecognised status is reported, never silently treated as "searched and empty".
    return bool(status) and status not in REACHED_STATUSES


def main(argv=None):
    ap = argparse.ArgumentParser(description="PRISMA-S search appendix builder.")
    ap.add_argument("--search-log", required=True)
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--review", default="the review")
    ap.add_argument("--allow-insufficient", action="store_true",
                    help="exit 0 although a source could not be reached. The appendix still "
                         "renders it as unavailable and the status stays "
                         "insufficient_evidence, so the override is recorded.")
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
                # An unavailable source has no hit count because nobody asked it. That is an
                # input gap, reported in its own list below, not a reproducibility failure.
                if not is_unreachable(r):
                    problems.append("row %d (%s): no hit count -> not reproducible" % (i, r.get("source", "?")))

    input_gaps = []
    for i, r in enumerate(rows, 1):
        if is_unreachable(r):
            input_gaps.append({
                "source": r.get("source", "?"),
                "platform": r.get("platform", ""),
                "source_status": (r.get("source_status") or "").strip() or "unknown",
                "row": i,
                "reason": ("%s was logged as not reached (%s), so its hit count is unknown. "
                           "Rendering it as 0 would publish a coverage gap as evidence of "
                           "absence." % (r.get("source", "?"), (r.get("source_status") or "").strip())),
                "action": ("re-run the search for this source, or state in the manuscript that "
                           "this database was unavailable and was not searched"),
            })

    total = len(rows)
    md = ["# PRISMA-S search appendix", "",
          "Review: %s" % args.review, "",
          "| # | Source | Platform | Search date | Records | Limits | Query |",
          "|---:|---|---|---|---:|---|---|"]
    for i, r in enumerate(rows, 1):
        q = (r.get("query", "") or "").replace("|", "\\|")
        if is_unreachable(r):
            # Never the digit 0: this source was not reached, which is a different fact.
            records = "unavailable (not reached)"
        else:
            records = r.get("hits", "")
        md.append("| %d | %s | %s | %s | %s | %s | `%s` |" % (
            i, r.get("source", ""), r.get("platform", ""), r.get("date_run", ""),
            records, r.get("limits", ""), q))
    md += ["", "## PRISMA-S item coverage", "",
           "| Item | Status |", "|---|---|",
           "| 1–2 Database / interface named | %s |" % ("yes" if "platform" in cols else "PARTIAL (no platform column)"),
           "| 3 Date each search run | %s |" % ("yes" if "date_run" in cols else "MISSING"),
           "| 5 Full search strategy per database | yes (query column) |",
           "| 6 Limits/filters | %s |" % ("yes" if "limits" in cols else "not recorded"),
           "| 16 Deduplication & totals | see prisma_flow.py counts |"]
    if input_gaps:
        md += ["", "## SOURCES NOT REACHED (input gap, not a finding)", "",
               "These sources were not searched. Their records are **unknown**, not zero, and the",
               "review's coverage of them is unverified. This is a statement about the search",
               "inputs, not a result."]
        for gap in input_gaps:
            md.append("- **%s** — %s" % (gap["source"], gap["reason"]))
            md.append("  - action: %s" % gap["action"])
    if problems:
        md += ["", "## REPRODUCIBILITY PROBLEMS", ""] + ["- " + p for p in problems]

    os.makedirs(args.outdir, exist_ok=True)
    out = os.path.join(args.outdir, "prisma_s_appendix.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")

    status = ("insufficient_evidence" if input_gaps else ("fail" if problems else "pass"))
    print(json.dumps({"tool": "prisma_s_appendix", "status": status, "searches": total,
                      "input_gaps": input_gaps}, indent=2, sort_keys=True), file=sys.stderr)
    print("PRISMA-S appendix -> %s (%d searches)" % (out, total))
    if problems:
        print("REPRODUCIBILITY FAILURES:")
        for p in problems:
            print("  -", p)
    if input_gaps:
        print("SOURCES NOT REACHED (%d) - an input gap, not a finding:" % len(input_gaps))
        for gap in input_gaps:
            print("  - %s: %s" % (gap["source"], gap["reason"]))
        print("  status: insufficient_evidence; these rows render as 'unavailable', never as 0")
    if input_gaps and not args.allow_insufficient:
        return 3
    if problems:
        return 2
    print("reproducibility checks: OK (every reached search has a date and a hit count)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
