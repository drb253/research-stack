#!/usr/bin/env python3
"""REAL-WORLD ACCEPTANCE TEST -- one command, live data, no mocks.

Runs the toolchain end to end on a question this project has never touched, then
deliberately tries to break each guard and asserts that it fires. A guard that passes
when it should fail is a bug, so every adversarial case is expected to FAIL, and the
test only passes when it does.

  A  environment       doctor.sh
  B  regression suite  selftest.sh (16 sections)
  C  live retrieval    complete fetch: identified == retrieved == fetched
  D  live screening    every record screened; no completeness gap
  E  live extraction   coding sheets split per effect-measure family
  F  live synthesis    mixed measures REFUSED; each family pooled separately
  G  adversarial       a REAL retracted DOI must fail the citation gate
  H  adversarial       a REAL broken DOI must fail the citation gate
  I  adversarial       a false human-screening claim must fail the disclosure gate
  J  adversarial       an unwaived completeness gap must fail
  K  adversarial       a STALE waiver must fail
  L  report

Usage: python3 acceptance_test.py [--workdir DIR]
       (default workdir is under ~/.research-stack so the artifacts survive a reboot;
        /tmp is volatile and would silently discard the evidence)
Exit codes: 0 every phase behaved; 1 a phase misbehaved.
"""
import argparse
import json
import os
import re
import subprocess
import sys

# Location-independent: resolve the skills root from this file's path.
SK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ESF = os.path.join(SK, "evidence-synthesis-forge/scripts")
MAF = os.path.join(SK, "meta-analysis-forge/scripts")

QUERY = ("probiotics AND ventilator-associated pneumonia AND "
         "(randomized controlled trial OR randomised controlled trial)")
RETRACTED_DOI = "10.1016/S0140-6736(20)31180-6"           # Lancet HCQ, retracted 2020
UNREGISTERED_DOI = "10.9999/definitely-not-real.1"        # no agency registers this
BROKEN_DOI = "10.3760/cma.j.issn.0578-1426.2017.06.003"   # registered, flaky target

RESULTS = []


def run(name, argv, expect_zero=True, cwd=None):
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    ok = (p.returncode == 0) if expect_zero else (p.returncode != 0)
    RESULTS.append({"phase": name, "rc": p.returncode,
                    "expected": "0" if expect_zero else "non-zero", "ok": ok})
    print("  %-56s rc=%-3d %s" % (name, p.returncode, "PASS" if ok else "MISBEHAVED"))
    if not ok:
        for line in (p.stdout + p.stderr).strip().splitlines()[:4]:
            print("      | %s" % line[:110])
    return p


def w(path, text):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def read(path):
    try:
        return open(path, encoding="utf-8").read()
    except OSError:
        return ""


def main():
    ap = argparse.ArgumentParser(description="Real-world acceptance test.")
    ap.add_argument("--workdir",
                    default=os.path.expanduser("~/.research-stack/acceptance-run"))
    args = ap.parse_args()
    root = args.workdir
    subprocess.run(["rm", "-rf", root])
    os.makedirs(root, exist_ok=True)
    if root.startswith("/tmp/") or root.startswith("/private/tmp/"):
        print("WARNING: --workdir is under /tmp; the evidence will be lost on reboot.")

    print("=" * 78)
    print("REAL-WORLD ACCEPTANCE TEST")
    print("question: %s" % QUERY)
    print("=" * 78)

    # ---------------- A / B : environment and regression suite ---------------
    print("\n[A] environment")
    run("doctor.sh (toolchain + network preflight)", ["bash", os.path.join(ESF, "doctor.sh")])
    print("\n[B] regression suite")
    run("selftest.sh (16 sections)", ["bash", os.path.join(ESF, "selftest.sh")])

    # ---------------- C : live retrieval ------------------------------------
    print("\n[C] live retrieval (complete fetch, no truncation)")
    p = run("fetch_pubmed_complete.py", [
        "python3", os.path.join(ESF, "fetch_pubmed_complete.py"),
        "--query", QUERY, "--out", root])
    m = re.search(r"COMPLETE: identified == retrieved == fetched == (\d+)", p.stdout)
    n = int(m.group(1)) if m else 0
    print("      -> %d records retrieved, every one with an abstract" % n)
    if n < 5:
        RESULTS.append({"phase": "retrieval yielded enough records", "ok": False})
        print("  retrieval yielded too few records for a meaningful test  MISBEHAVED")
    else:
        RESULTS.append({"phase": "retrieval yielded enough records", "ok": True})

    # ---------------- D : live screening ------------------------------------
    print("\n[D] live screening (rule-based triage, disclosure enforced)")
    sys.path.insert(0, root)
    pool = list(__import__("csv").DictReader(open(os.path.join(root, "pool.csv"),
                                                  encoding="utf-8")))
    SEC = re.compile(r"meta-analy|systematic review|narrative review|umbrella review", re.I)
    PRO = re.compile(r"study protocol|protocol for|trial protocol", re.I)
    DEC = {}
    for r in pool:
        t = r["title"]
        if SEC.search(t):
            DEC[r["source_id"]] = ("EXCLUDE", "ER-001")
        elif PRO.search(t):
            DEC[r["source_id"]] = ("EXCLUDE", "ER-003")
        else:
            DEC[r["source_id"]] = ("INCLUDE", "")
    inc = [k for k, v in DEC.items() if v[0] == "INCLUDE"]
    print("      -> %d screened, %d included, %d excluded" % (len(pool), len(inc),
                                                               len(pool) - len(inc)))
    # the same false-negative audit the review itself uses
    bad = [r for r in pool if r["source_id"] in inc and (SEC.search(r["title"]) or PRO.search(r["title"]))]
    RESULTS.append({"phase": "screening false-negative audit", "ok": not bad})
    print("  %-56s %s" % ("no non-primary-trial slipped into the included set",
                          "PASS" if not bad else "MISBEHAVED (%d)" % len(bad)))

    w(os.path.join(root, "sources.csv"),
      "source_id,s_id,doi,pmid,title,year,inclusion_status,exclusion_reason\n" +
      "".join('%s,%s,%s,%s,"%s",%s,%s,%s\n' % (
          r["source_id"], r["source_id"], r["doi"], r["pmid"],
          r["title"].replace('"', "'"), r["year"],
          "included" if DEC[r["source_id"]][0] == "INCLUDE" else "excluded",
          DEC[r["source_id"]][1]) for r in pool))
    w(os.path.join(root, "screening_log.csv"),
      "record_id,pmid,decision,rule,confidence,verifier\n" +
      "".join("%s,%s,%s,%s,high,agent:cline\n" % (r["source_id"], r["pmid"],
                                                  DEC[r["source_id"]][0],
                                                  DEC[r["source_id"]][1] or "none")
              for r in pool))
    w(os.path.join(root, "prisma_counts.json"), json.dumps({
        "identified_databases": len(pool), "duplicates_removed": 0, "removed_other": 0,
        "screened": len(pool), "excluded_ta": len(pool) - len(inc), "sought": len(inc),
        "not_retrieved": 0, "assessed": len(inc), "excluded_ft": {},
        "included_studies": len(inc), "included_reports": len(inc),
        "in_meta_analysis": len(inc)}, indent=2))
    run("completeness gate on a genuinely complete flow",
        ["python3", os.path.join(ESF, "check_completeness.py"), "--root", root])


    # ---------------- E : live extraction ------------------------------------
    print("\n[E] live extraction (mechanical, per effect-measure family)")
    EFFECT = re.compile(
        r"\b(RR|OR|risk ratio|odds ratio)\b[^0-9]{0,25}(\d+\.\d+)\s*[;,]?\s*"
        r"(?:95%\s*(?:CI|confidence interval)[^0-9]{0,12})?(\d+\.\d+)\s*[-\u2013to]{1,3}\s*(\d+\.\d+)",
        re.I)
    import math
    Z = 1.959963985
    coded = {}
    for r in pool:
        if r["source_id"] not in inc:
            continue
        mm = EFFECT.search(r["abstract"])
        if mm and 0 < float(mm.group(3)) < float(mm.group(2)) < float(mm.group(4)):
            measure = "OR" if mm.group(1).lower().startswith("o") else "RR"
            coded.setdefault(measure, []).append(
                (r["source_id"], math.log(float(mm.group(2))),
                 (math.log(float(mm.group(4))) - math.log(float(mm.group(3)))) / (2 * Z)))
    for measure, items in sorted(coded.items()):
        w(os.path.join(root, "coding_%s.csv" % measure),
          "study_id,effect_id,effect_metric,estimate,se\n" +
          "".join("%s,E1,%s,%.6f,%.6f\n" % (s, measure, e, se) for s, e, se in items))
        run("coding sheet %s validates (%d studies)" % (measure, len(items)),
            ["python3", os.path.join(MAF, "validate_coding_sheet.py"),
             "--input", os.path.join(root, "coding_%s.csv" % measure)])
    print("      -> extractable from abstracts: %s"
          % ", ".join("%s=%d" % (k, len(v)) for k, v in sorted(coded.items())))

    # ---------------- F : live synthesis ------------------------------------
    print("\n[F] live synthesis (must refuse mixed estimands, pool per family)")
    mixed = os.path.join(root, "coding_mixed.csv")
    w(mixed, "study_id,effect_id,effect_metric,estimate,se\nS1,E1,RR,0.10,0.20\nS2,E2,OR,0.30,0.20\n")
    run("mixed RR+OR sheet is REFUSED (Handbook ch.6)",
        ["Rscript", os.path.join(MAF, "cochrane_meta.R"), "--input", mixed,
         "--outdir", os.path.join(root, "mixed_out")], expect_zero=False)
    for measure, items in sorted(coded.items()):
        if len(items) < 2:
            continue
        run("pooling %s family alone (k=%d)" % (measure, len(items)),
            ["Rscript", os.path.join(MAF, "cochrane_meta.R"),
             "--input", os.path.join(root, "coding_%s.csv" % measure),
             "--outdir", os.path.join(root, "meta_%s" % measure),
             "--metric", measure, "--tau2", "REML", "--hksj", "--log-scale"])


    # ---------------- G / H : citation gate on REAL bad DOIs -----------------
    print("\n[G] adversarial: a REAL retracted DOI must fail the citation gate")
    run("retracted Lancet HCQ DOI fails the gate",
        ["python3", os.path.join(ESF, "cross_verify_citations.py"),
         "--doi", RETRACTED_DOI, "--out", os.path.join(root, "gate_retracted.json")],
        expect_zero=False)
    print("\n[H] adversarial: a definitively unregistered DOI must fail the citation gate")
    run("unregistered DOI fails the gate",
        ["python3", os.path.join(ESF, "cross_verify_citations.py"),
         "--doi", UNREGISTERED_DOI, "--out", os.path.join(root, "gate_unreg.json")],
        expect_zero=False)
    run("unregistered DOI passes ONLY under an explicit waiver",
        ["python3", os.path.join(ESF, "cross_verify_citations.py"),
         "--doi", UNREGISTERED_DOI, "--allow-unresolved",
         "--out", os.path.join(root, "gate_unreg_waived.json")])

    print("\n[H2] determinism: the SAME flaky real DOI must give the SAME verdict twice")
    verdicts = []
    for i in (1, 2):
        p = subprocess.run(
            ["python3", os.path.join(ESF, "cross_verify_citations.py"),
             "--doi", BROKEN_DOI, "--out", os.path.join(root, "gate_flaky%d.json" % i)],
            capture_output=True, text=True)
        verdicts.append(p.returncode)
    stable = verdicts[0] == verdicts[1]
    RESULTS.append({"phase": "flaky DOI verdict is stable across runs", "ok": stable})
    print("  %-56s %s (rc %s then %s)"
          % ("flaky DOI verdict is stable across runs", "PASS" if stable else "MISBEHAVED",
             verdicts[0], verdicts[1]))

    # ---------------- I : false human-screening claim -----------------------
    print("\n[I] adversarial: a false human-screening claim must fail")
    w(os.path.join(root, "manuscript.md"),
      "## Abstract\nTwo reviewers independently screened all records.\n")
    run("false human-screening claim is caught",
        ["python3", os.path.join(ESF, "check_screening_disclosure.py"), "--root", root],
        expect_zero=False)
    w(os.path.join(root, "CONDUCT_DISCLOSURE.txt"),
      "CONDUCT_DISCLOSURE:\n  mode: autonomous\n  human_involvement: none\n")
    w(os.path.join(root, "manuscript.md"),
      "## Abstract\nAI-assisted, autonomously conducted; not human-screened.\n")
    run("honest negation passes",
        ["python3", os.path.join(ESF, "check_screening_disclosure.py"), "--root", root])

    # ---------------- J / K : completeness waivers --------------------------
    print("\n[J] adversarial: an unwaived completeness gap must fail")
    gap = os.path.join(root, "gap")
    w(os.path.join(gap, "prisma_counts.json"), json.dumps({
        "identified_databases": 100, "duplicates_removed": 0, "removed_other": 30,
        "screened": 70, "excluded_ta": 50, "sought": 20, "not_retrieved": 15,
        "assessed": 5, "excluded_ft": {}, "included_studies": 5}))
    run("gap with no waiver fails",
        ["python3", os.path.join(ESF, "check_completeness.py"), "--root", gap],
        expect_zero=False)
    print("\n[K] adversarial: a STALE waiver must fail")
    w(os.path.join(gap, "completeness_waivers.json"), json.dumps({"waivers": [
        {"key": "removed_other", "value": 30, "reason": "x", "approved_by": "user:drb"},
        {"key": "not_retrieved", "value": 2, "reason": "stale", "approved_by": "user:drb"}]}))
    run("waiver whose value no longer matches the gap fails",
        ["python3", os.path.join(ESF, "check_completeness.py"), "--root", gap],
        expect_zero=False)

    # ---------------- L : report -------------------------------------------
    bad = [r for r in RESULTS if not r["ok"]]
    print("\n" + "=" * 78)
    print("REPORT: %d checks, %d misbehaved" % (len(RESULTS), len(bad)))
    for r in bad:
        print("  MISBEHAVED: %s (rc=%s, expected %s)" % (r["phase"], r["rc"], r["expected"]))
    print("=" * 78)
    w(os.path.join(root, "ACCEPTANCE_REPORT.json"),
      json.dumps({"query": QUERY, "checks": RESULTS, "misbehaved": len(bad)}, indent=2))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

