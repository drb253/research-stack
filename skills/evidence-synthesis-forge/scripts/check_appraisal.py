#!/usr/bin/env python3
"""Appraisal-honesty gate.

Naming a risk-of-bias tool in Methods and then not applying it is worse than naming none:
it advertises an appraisal that does not exist. This gate fails when the appraisal ledger
is a placeholder (e.g. "PROBAST (conceptual)", "no clinical prediction model to fully
score") or records no domain judgement at all, while the Methods name a tool.

If PRISMA-ScR is the reporting standard, critical appraisal is OPTIONAL - but then the
Methods must not claim it. This gate enforces that choice in both directions.

  python3 check_appraisal.py --root .
  python3 check_appraisal.py --selftest
"""
import argparse
import csv
import os
import sys

TOOLS = ("rob 2", "rob2", "robins-i", "robins-e", "rob-me", "quadas", "probast",
         "amstar", "robis", "syrcile")
PLACEHOLDER = ("in concept", "conceptual", "not scored", "not assessed", "to be assessed",
               "no clinical prediction model", "to fully score", "n/a", "tbd", "pending",
               "not applicable")
JUDGEMENTS = ("low", "some concerns", "high", "unclear", "moderate", "serious", "critical")


def _read(root, name):
    p = os.path.join(root, name)
    return open(p, encoding="utf-8", errors="replace").read() if os.path.exists(p) else ""


def collect(root="."):
    probs = []
    rob_path = os.path.join(root, "ledgers/rob_assessment.csv")
    rob = []
    if os.path.exists(rob_path):
        with open(rob_path, newline="", encoding="utf-8-sig") as fh:
            rob = list(csv.DictReader(fh))

    methods = " ".join(_read(root, n) for n in
                       ("manuscript.md", "protocol.md", "review_full.html")).lower()
    named = sorted({t for t in TOOLS if t in methods})
    if not named:
        return probs                      # nothing claimed -> nothing to police
    if not rob:
        probs.append("APPRAISAL: Methods name %s but ledgers/rob_assessment.csv is absent/empty"
                     % ", ".join(named))
        return probs

    for r in rob:
        sid = r.get("source_id", "?")
        blob = " ".join(str(v or "") for v in r.values()).lower()
        ph = [p for p in PLACEHOLDER if p in blob]
        if ph:
            probs.append("APPRAISAL:%s is a placeholder (%r) - the tool is named in Methods "
                         "but was not applied" % (sid, ph[0]))
            continue
        if not any(j in blob for j in JUDGEMENTS):
            probs.append("APPRAISAL:%s records no domain judgement - an unjudged appraisal "
                         "is not an appraisal" % sid)
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

    def build(rows, claim=True):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "ledgers"), exist_ok=True)
        with open(os.path.join(d, "ledgers/rob_assessment.csv"), "w", newline="",
                  encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["source_id", "tool", "domain_summary"])
            w.writeheader()
            for r in rows:
                w.writerow(r)
        with open(os.path.join(d, "manuscript.md"), "w", encoding="utf-8") as fh:
            fh.write("Appraisal used PROBAST.\n" if claim else "No appraisal was performed.\n")
        return collect(d)

    case("placeholder fires",
         build([{"source_id": "S1", "tool": "PROBAST (conceptual)",
                 "domain_summary": "no clinical prediction model to fully score"}]), True)
    case("silent-no-claim passes",
         build([{"source_id": "S1", "tool": "PROBAST (conceptual)",
                 "domain_summary": "in concept"}], claim=False), False)
    case("real appraisal passes",
         build([{"source_id": "S1", "tool": "PROBAST",
                 "domain_summary": "participants low; predictors low; outcome some concerns; "
                                   "analysis high; overall high"}]), False)
    case("unjudged appraisal fires",
         build([{"source_id": "S1", "tool": "PROBAST",
                 "domain_summary": "model development study"}]), True)
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
        print("FAIL - %d appraisal problem(s):" % len(probs))
        for x in probs:
            print("  - %s" % x)
        return 2
    print("OK - appraisal claims in Methods are backed by real domain judgements")
    return 0


if __name__ == "__main__":
    sys.exit(main())
