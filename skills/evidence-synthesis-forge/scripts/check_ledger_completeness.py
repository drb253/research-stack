#!/usr/bin/env python3
"""Ledger-completeness gate.

A PRISMA flow ASSERTS how many records were screened and excluded. This gate makes the
ledger EVIDENCE of that assertion: the screening ledger must hold one row per record the
flow claims was screened, every EXCLUDE must carry a reason, and every INCLUDE must carry
NO exclusion reason (an INCLUDE row with an exclusion reason means the rule was applied
inconsistently, or the row is mis-tagged - both need a human decision).

  python3 check_ledger_completeness.py --root .
  python3 check_ledger_completeness.py --selftest
"""
import argparse
import csv
import json
import os
import sys


def _rows(root, name):
    p = os.path.join(root, name)
    if not os.path.exists(p):
        sys.exit("FAIL - missing ledger: %s" % name)
    with open(p, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _prisma(pc):
    """Return the nested PRISMA sections, accepting the flat prisma_flow.py shape."""
    if isinstance(pc.get("screening"), dict):
        return pc
    if "screened" in pc:
        ft = pc.get("excluded_ft") or {}
        return {
            "screening": {"records_screened": pc.get("screened", 0),
                          "records_excluded": pc.get("excluded_ta", 0)},
            "retrieval": {"reports_sought": pc.get("sought", 0),
                          "reports_not_retrieved": pc.get("not_retrieved", 0)},
            "eligibility": {"reports_assessed": pc.get("assessed", 0),
                            "reports_excluded": sum(int(v or 0) for v in ft.values())},
            "included": {"studies_included": pc.get("included_studies", 0)},
        }
    raise SystemExit(
        "prisma_counts.json: unrecognised shape. Expected either the nested keys "
        "(identification/screening/retrieval/eligibility/included) or the flat keys "
        "used by prisma_flow.py (identified_databases/screened/excluded_ta/...).")


def _prisma_screened(pc):
    """Read 'records screened' from either PRISMA shape.

    prisma_flow.py emits/accepts BOTH the nested shape and the flat shape, but this
    gate and check_review_integrity.py only understood the nested one -- so a valid
    flat counts file crashed them with a raw KeyError instead of a finding.
    """
    return int(_prisma(pc)["screening"].get("records_screened", 0) or 0)


def collect(root="."):
    probs = []
    src = _rows(root, "sources.csv")
    with open(os.path.join(root, "prisma_counts.json"), encoding="utf-8") as fh:
        pc = _prisma(json.load(fh))

    claimed = pc["screening"]["records_screened"]
    if len(src) != claimed:
        probs.append("LEDGER: PRISMA flow claims %d records screened; sources.csv holds %d row(s) "
                     "- %d screening decision(s) have no ledger entry"
                     % (claimed, len(src), claimed - len(src)))

    inc = [r for r in src if (r.get("inclusion_status") or "").strip() == "included"]
    exc = [r for r in src if (r.get("inclusion_status") or "").strip() == "excluded"]

    bad_status = [r.get("s_id") for r in src
                  if (r.get("inclusion_status") or "").strip() not in ("included", "excluded")]
    if bad_status:
        probs.append("LEDGER: row(s) with no valid inclusion_status: %s" % bad_status[:8])

    for r in exc:
        if not (r.get("exclusion_reason") or "").strip():
            probs.append("LEDGER: %s is excluded with an empty exclusion_reason" % r.get("s_id"))
    for r in inc:
        if (r.get("exclusion_reason") or "").strip():
            probs.append("LEDGER: %s is INCLUDED but carries exclusion_reason %r - "
                         "the rule was applied inconsistently"
                         % (r.get("s_id"), (r.get("exclusion_reason") or "")[:50]))

    if len(inc) != pc["included"]["studies_included"]:
        probs.append("LEDGER: PRISMA flow claims %d studies included; ledger holds %d"
                     % (pc["included"]["studies_included"], len(inc)))
    return probs


def selftest():
    import tempfile
    ok, n, passed = True, 0, 0

    def case(label, probs, expect):
        nonlocal ok, n, passed
        good = bool(probs) == expect
        ok &= good
        n += 1
        passed += good
        print("%-4s %s" % ("OK" if good else "BAD", label))

    def build(rows, screened, included):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "sources.csv"), "w", newline="", encoding="utf-8") as fh:
            wtr = csv.DictWriter(fh, fieldnames=["source_id", "s_id", "inclusion_status",
                                                 "exclusion_reason", "country"])
            wtr.writeheader()
            for r in rows:
                wtr.writerow(r)
        with open(os.path.join(d, "prisma_counts.json"), "w", encoding="utf-8") as fh:
            json.dump({"screening": {"records_screened": screened},
                       "included": {"studies_included": included}}, fh)
        return collect(d)

    good = [{"source_id": "S001", "s_id": "S001", "inclusion_status": "included",
             "exclusion_reason": "", "country": "India"}]
    case("complete ledger passes", build(good, 1, 1), False)
    case("ledger shorter than flow fires", build(good, 234, 1), True)
    case("INCLUDE with exclusion reason fires",
         build([{"source_id": "S001", "s_id": "S001", "inclusion_status": "included",
                 "exclusion_reason": "multi-country", "country": "India"}], 1, 1), True)
    case("EXCLUDE with no reason fires",
         build([{"source_id": "S002", "s_id": "S002", "inclusion_status": "excluded",
                 "exclusion_reason": "", "country": "India"}], 1, 0), True)
    print("\nSELFTEST: %d/%d assertions pass" % (passed, n))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    probs = collect(a.root)
    if probs:
        print("FAIL - %d ledger-completeness problem(s):" % len(probs))
        for x in probs:
            print("  - %s" % x)
        return 2
    print("OK - screening ledger is complete and internally consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
