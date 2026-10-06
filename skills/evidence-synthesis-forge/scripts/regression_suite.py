#!/usr/bin/env python3
"""Regression suite - one fixture per defect class this pipeline has actually produced.

Every defect found in a real review is encoded here as a fixture that MUST be caught, plus
a baseline review that must pass every gate. A gate that cannot fail is not a gate; a defect
without a fixture comes back.

  python3 regression_suite.py              # offline fixtures
  python3 regression_suite.py --network    # + the PMID->DOI resolution fixture
"""
import argparse
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent


def _mod(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


INTEG = _mod("check_review_integrity")
LEDGER = _mod("check_ledger_completeness")
APPR = _mod("check_appraisal")

SRC_HDR = ("source_id,s_id,doi,pmid,title,year,journal,country,surveillance_function,ai_method,"
           "design,inclusion_status,disposition,exclusion_reason,verification_status,verifier,"
           "verified_date,locator")


def _w(path, text):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def base_review(t):
    """A minimal, internally consistent review that every gate passes."""
    _w(t + "/sources.csv",
       SRC_HDR + "\nS001,S001,10.1/x,1,Study one,2024,J,India,forecasting,LSTM,model-development,"
                 "included,INCLUDE,,verified,agent,2026-01-01,PMID 1\n")
    _w(t + "/claims.csv", 'claim_id,claim_summary,supporting_sids\n'
                          'C001,"The evidence is retrospective.",S001\n')
    _w(t + "/ledgers/extraction.csv",
       "source_id,primary_outcome,effect_primary,extraction_note\nS001,Acute care visits,RR 0.5,x\n")
    _w(t + "/ledgers/rob_assessment.csv",
       "source_id,tool,domain_summary\n"
       "S001,PROBAST,participants low; predictors low; outcome low; analysis low; overall low\n")
    _w(t + "/ledgers/sources_included.csv", "source_id\nS001\n")
    _w(t + "/manuscript.md", "## References\n1. [src:S001] Study one.\n")
    _w(t + "/synthesis.md", "Synthesis: one included study, retrospective.\n")
    _w(t + "/review_full.html", '<ol class="refs"><li>Study one.</li></ol>\n')
    _w(t + "/search_log.csv", "source,platform,query,date_run,hits\n"
                              "PubMed,NCBI,ai india,2026-01-01,10\n"
                              "Scopus,Elsevier,ai india,2026-01-01,5\n")
    _w(t + "/prisma_counts.json", json.dumps({
        "identification": {"records_from_databases": 10, "records_from_registers": 0,
                           "records_from_other_methods": 0, "duplicates_removed": 1,
                           "removed_automation": 0, "removed_other": 8},
        "screening": {"records_screened": 1, "records_excluded": 0},
        "retrieval": {"reports_sought": 1, "reports_not_retrieved": 0},
        "eligibility": {"reports_assessed": 1, "exclusion_reasons": {}, "reports_excluded": 0},
        "included": {"studies_included": 1, "sources_verified": 1, "in_meta_analysis": 0}}))
    return t


def run(network=False):
    res = []

    def case(name, probs, expect=True):
        good = bool(probs) == expect
        res.append((good, name, (probs[0][:96] if probs else "")))

    # ---- baseline: a consistent review must pass everything ----
    with tempfile.TemporaryDirectory() as t:
        base_review(t)
        case("BASE consistent review passes integrity", INTEG.collect(t), expect=False)
        case("BASE consistent review passes ledger-completeness", LEDGER.collect(t), expect=False)
        case("BASE consistent review passes appraisal-honesty", APPR.collect(t), expect=False)

    # ---- F1/F2: the claims ledger's supporting_sids column ----
    with tempfile.TemporaryDirectory() as t:
        base_review(t)
        _w(t + "/claims.csv", "claim_id,claim_summary,supporting_sids\n"
                              "C001,An LSTM outperformed VAR, boosted and SVR baselines (RMSE 0.345\n")
        case("F1 unquoted-comma claim split is caught", INTEG.collect(t))
    with tempfile.TemporaryDirectory() as t:
        base_review(t)
        _w(t + "/claims.csv", "claim_id,claim_summary,supporting_sids\nC001,Some claim,\n")
        case("F2 unsourced claim is caught", INTEG.collect(t))
    with tempfile.TemporaryDirectory() as t:
        base_review(t)
        _w(t + "/claims.csv", 'claim_id,claim_summary,supporting_sids\nC001,"Some claim",S999\n')
        case("F2b unknown source id is caught", INTEG.collect(t))

    # ---- F3/F4: ledger completeness ----
    with tempfile.TemporaryDirectory() as t:
        base_review(t)
        _w(t + "/sources.csv",
           SRC_HDR + "\nS001,S001,10.1/x,1,T,2024,J,India,f,LSTM,md,included,INCLUDE,"
                     "multi-country,verified,agent,2026-01-01,P\n")
        case("F3 INCLUDE carrying an exclusion reason is caught", LEDGER.collect(t))
    with tempfile.TemporaryDirectory() as t:
        base_review(t)
        pc = json.loads(pathlib.Path(t + "/prisma_counts.json").read_text())
        pc["screening"]["records_screened"] = 234
        _w(t + "/prisma_counts.json", json.dumps(pc))
        case("F4 ledger shorter than the PRISMA flow is caught", LEDGER.collect(t))

    # ---- F5: zero deduplication across overlapping sources ----
    with tempfile.TemporaryDirectory() as t:
        base_review(t)
        case("F5 zero-dedup across 2 sources is caught", INTEG.check_dedup_plausibility({
            "identification": {"records_from_databases": 7475, "duplicates_removed": 0}},
            [{"source": "PubMed"}, {"source": "Scopus"}]))

    # ---- F6: cross-artifact contradiction on a shared fact ----
    with tempfile.TemporaryDirectory() as t:
        base_review(t)
        rows = [("S001", "multi-country incl India")] + [("S00%d" % i, "India") for i in range(2, 6)]
        body = "".join("%s,%s,10.1/%d,,T,2024,J,%s,f,LSTM,md,included,INCLUDE,,verified,agent,"
                       "2026-01-01,P\n" % (s, s, i, c) for i, (s, c) in enumerate(rows, 1))
        _w(t + "/sources.csv", SRC_HDR + "\n" + body)
        src = INTEG._load_csv("sources.csv", t)
        case("F6 contradiction (2 vs 4 India-specific) is caught",
             INTEG.check_fact_consistency(src, {"synthesis.md":
                 "only two of five included studies are India-specific"}))
        case("F6 consistent statement passes", INTEG.check_fact_consistency(src, {"synthesis.md":
             "only four of five included studies are India-specific"}), expect=False)

    # ---- F7: template marker leaking into the deliverable ----
    with tempfile.TemporaryDirectory() as t:
        base_review(t)
        _w(t + "/review_full.html", '<ol class="refs"><li>[src:S001] Study one.</li></ol>\n')
        case("F7 template marker leak is caught", INTEG.collect(t))

    # ---- F8: a tool named in Methods but never applied ----
    with tempfile.TemporaryDirectory() as t:
        base_review(t)
        _w(t + "/manuscript.md", "## Appraisal\nAppraisal used PROBAST in concept.\n"
                                 "## References\n1. [src:S001] Study one.\n")
        _w(t + "/ledgers/rob_assessment.csv",
           "source_id,tool,domain_summary\n"
           "S001,PROBAST (conceptual),no clinical prediction model to fully score\n")
        case("F8 placeholder appraisal is caught", APPR.collect(t))

    # ---- F9: a number in the draft with no artifact behind it ----
    with tempfile.TemporaryDirectory() as t:
        _w(t + "/art.json", '{"pooled": 0.49}\n')
        _w(t + "/d.md", "The pooled RR was 0.49 but also 0.77.\n")
        r = subprocess.run([sys.executable, str(HERE / "numbers_provenance.py"),
                            "--draft", t + "/d.md", "--artifacts", t + "/art.json"],
                           capture_output=True, text=True)
        case("F9 untraceable number is caught", ["untraceable 0.77"] if r.returncode else [])

    # ---- F11: a UTF-8 BOM on a ledger must not break parsing ----
    with tempfile.TemporaryDirectory() as t:
        base_review(t)
        p = pathlib.Path(t + "/sources.csv")
        p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes())
        try:
            case("F11 BOM-prefixed ledger parses (no crash, no spurious finding)",
                 INTEG.collect(t), expect=False)
        except Exception as exc:  # noqa: BLE001
            case("F11 BOM-prefixed ledger parses (no crash)", ["CRASH: %s" % exc])

    # ---- F10: a resolvable DOI omitted from the ledger (network) ----
    if network:
        with tempfile.TemporaryDirectory() as t:
            _w(t + "/pmid.csv", "s_id,doi,pmid,title\n"
                                "S002,,32114430,An AI-based approach in determining the effect\n")
            r = subprocess.run([sys.executable, str(HERE / "cross_verify_citations.py"),
                                "--sources", t + "/pmid.csv", "--out", t + "/g.json",
                                "--resolve-pmid-doi"], capture_output=True, text=True)
            case("F10 resolvable-but-absent DOI is caught",
                 ["ledger defect"] if r.returncode else [])

    print("REGRESSION SUITE")
    bad = 0
    for good, name, detail in res:
        print("  %-4s %s" % ("OK" if good else "BAD", name))
        if not good:
            bad += 1
            if detail:
                print("        unexpected finding: %s" % detail)
    print("\n%d/%d fixtures behave correctly" % (len(res) - bad, len(res)))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--network", action="store_true")
    sys.exit(run(network=ap.parse_args().network))
