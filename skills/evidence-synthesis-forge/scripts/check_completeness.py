#!/usr/bin/env python3
"""Completeness gate: an incomplete review must FAIL, not merely mention it.

`removed_other` and `not_retrieved` are the two PRISMA cells where records vanish
silently. They reconcile arithmetically, so prisma_flow.py passes them -- which means a
review that screened 60 of 83 records, or assessed 2 of 21 eligible reports, sails
through every other gate with only a prose limitation. This gate closes that hole:

  * a non-zero `removed_other` (identified but never screened) is a FAILURE
  * a non-zero `not_retrieved` (sought but never assessed) is a FAILURE
  * each is waivable ONLY by an explicit, attributed, value-matched waiver

A waiver whose declared value no longer matches the actual gap is itself a failure, so a
waiver cannot silently cover a gap that grew after it was signed.

Usage:
  python3 check_completeness.py --root <review-dir>
  python3 check_completeness.py --root <review-dir> --waivers my_waivers.json

Waiver file (default <root>/completeness_waivers.json):
  {"waivers": [
     {"key": "removed_other", "value": 23,
      "reason": "pilot scope: only the top 60 by relevance were retrieved",
      "approved_by": "user:drb", "approved_at": "2026-10-02"}
  ]}

Exit codes: 0 complete (or every gap explicitly waived); 2 incomplete; 1 usage error.
"""
import argparse
import csv
import json
import os
import sys

# (key, human label)
GAPS = [("removed_other", "identified but never screened"),
        ("not_retrieved", "sought but never assessed")]
SINGLE_SOURCE = "single_source_search"


def _search_sources(root):
    """Distinct bibliographic sources in search_log.csv, or None if there is no log."""
    path = os.path.join(root, "search_log.csv")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    return sorted({(r.get("source") or "").strip() for r in rows
                   if (r.get("source") or "").strip()})


def _nested(pc):
    """Return the nested PRISMA sections, accepting the flat prisma_flow shape."""
    if isinstance(pc.get("screening"), dict):
        return pc
    if "screened" in pc:
        return {
            "identification": {
                "records_from_databases": pc.get("identified_databases", 0),
                "records_from_registers": pc.get("identified_registers", 0),
                "records_from_other_methods": pc.get("identified_other", 0),
                "duplicates_removed": pc.get("duplicates_removed", 0),
                "removed_automation": pc.get("removed_automation", 0),
                "removed_other": pc.get("removed_other", 0)},
            "screening": {"records_screened": pc.get("screened", 0),
                          "records_excluded": pc.get("excluded_ta", 0)},
            "retrieval": {"reports_sought": pc.get("sought", 0),
                          "reports_not_retrieved": pc.get("not_retrieved", 0)},
            "eligibility": {"reports_assessed": pc.get("assessed", 0),
                            "reports_excluded": sum(int(v or 0)
                                                    for v in (pc.get("excluded_ft") or {}).values())},
            "included": {"studies_included": pc.get("included_studies", 0)},
        }
    raise SystemExit("prisma_counts.json: unrecognised shape -- expected the nested "
                     "(identification/screening/retrieval/eligibility/included) or the flat "
                     "prisma_flow keys (identified_databases/screened/excluded_ta/...).")

def _gap_values(nested):
    ident = nested.get("identification", {}) or {}
    ret = nested.get("retrieval", {}) or {}
    return {"removed_other": int(ident.get("removed_other", 0) or 0),
            "not_retrieved": int(ret.get("reports_not_retrieved", 0) or 0)}


def _reconcile(nested):
    """The same four identities prisma_flow.py enforces; reported here too."""
    def n(d, k):
        return int((d or {}).get(k, 0) or 0)

    ident, scr = nested.get("identification", {}), nested.get("screening", {})
    ret = nested.get("retrieval", {})
    eli, inc = nested.get("eligibility", {}), nested.get("included", {})
    total = (n(ident, "records_from_databases") + n(ident, "records_from_registers")
             + n(ident, "records_from_other_methods"))
    removed = (n(ident, "duplicates_removed") + n(ident, "removed_automation")
               + n(ident, "removed_other"))
    probs = []
    if total - removed != n(scr, "records_screened"):
        probs.append("identified(%d) - removed(%d) != screened(%d)"
                     % (total, removed, n(scr, "records_screened")))
    if n(scr, "records_screened") - n(scr, "records_excluded") != n(ret, "reports_sought"):
        probs.append("screened(%d) - excluded(%d) != sought(%d)"
                     % (n(scr, "records_screened"), n(scr, "records_excluded"),
                        n(ret, "reports_sought")))
    if n(ret, "reports_sought") - n(ret, "reports_not_retrieved") != n(eli, "reports_assessed"):
        probs.append("sought(%d) - not_retrieved(%d) != assessed(%d)"
                     % (n(ret, "reports_sought"), n(ret, "reports_not_retrieved"),
                        n(eli, "reports_assessed")))
    if n(eli, "reports_assessed") - n(eli, "reports_excluded") != n(inc, "studies_included"):
        probs.append("assessed(%d) - excluded(%d) != included(%d)"
                     % (n(eli, "reports_assessed"), n(eli, "reports_excluded"),
                        n(inc, "studies_included")))
    return probs


def check(root, waivers_path=None):
    with open(os.path.join(root, "prisma_counts.json"), encoding="utf-8") as fh:
        nested = _nested(json.load(fh))

    probs = ["ARITHMETIC: %s" % p for p in _reconcile(nested)]

    waivers = {}
    wpath = waivers_path or os.path.join(root, "completeness_waivers.json")
    if os.path.exists(wpath):
        with open(wpath, encoding="utf-8") as fh:
            for w in (json.load(fh).get("waivers") or []):
                key = w.get("key")
                if not key:
                    continue
                missing = [f for f in ("value", "reason", "approved_by") if not w.get(f)]
                if missing:
                    probs.append("WAIVER(%s): incomplete -- missing %s" % (key, ", ".join(missing)))
                    continue
                waivers[key] = w

    gaps = _gap_values(nested)
    for key, label in GAPS:
        actual = gaps[key]
        if actual == 0:
            continue
        w = waivers.get(key)
        if not w:
            probs.append(
                "INCOMPLETE: %s = %d record(s) (%s), with no waiver. A review that loses records "
                "at this stage must either complete the stage or record an explicit, attributed "
                "waiver in completeness_waivers.json." % (key, actual, label))
        elif int(w["value"]) != actual:
            probs.append("STALE WAIVER(%s): declares %s but the actual gap is %d -- a waiver must "
                         "not silently cover a gap that changed after it was signed."
                         % (key, w["value"], actual))

    for key, w in waivers.items():
        if key not in dict(GAPS) and key != SINGLE_SOURCE:
            probs.append("WAIVER(%s): unknown gap key" % key)
        elif int(w["value"]) == 0:
            probs.append("WAIVER(%s): declares 0 -- remove it" % key)

    # --- search coverage: a single-source search is a blind spot, not a complete search ---
    srcs = _search_sources(root)
    if srcs is not None and len(srcs) < 2:
        w = waivers.get(SINGLE_SOURCE)
        if not w:
            probs.append(
                "INCOMPLETE: only one bibliographic source was searched (%s). A single-database "
                "search cannot see trial registries, preprints, or non-MEDLINE journals -- the "
                "places where unpublished and terminated trials sit. Search further sources "
                "(paper-search MCP: search_papers with sources=\"auto\", plus search_clinicaltrials / "
                "search_ictrp), or record an explicit waiver." % ", ".join(srcs))
        elif int(w["value"]) != 1:
            probs.append("STALE WAIVER(%s): declares %s but the actual gap is 1 source"
                         % (SINGLE_SOURCE, w["value"]))

    return probs, gaps


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fail an incomplete review.")
    ap.add_argument("--root", default=".")
    ap.add_argument("--waivers", default=None, help="path to the waiver JSON")
    args = ap.parse_args(argv)

    if not os.path.exists(os.path.join(args.root, "prisma_counts.json")):
        print("ERROR: prisma_counts.json not found under %s" % args.root, file=sys.stderr)
        return 1
    probs, gaps = check(args.root, args.waivers)
    if probs:
        print("FAIL - review is not complete (%d problem(s)):" % len(probs))
        for p in probs:
            print("  - %s" % p)
        return 2
    waived = {k: v for k, v in gaps.items() if v}
    if waived:
        print("OK - every completeness gap is covered by an explicit waiver: %s"
              % ", ".join("%s=%d" % (k, v) for k, v in sorted(waived.items())))
        print("     The review is NOT complete; the gaps are accepted and attributed, "
              "and must be reported as limitations.")
    else:
        print("OK - retrieval and assessment complete (removed_other=0, not_retrieved=0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

