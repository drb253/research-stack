#!/usr/bin/env bash
# selftest.sh -- the QA suite for the Cochrane-grade layer. Runs the real scripts and
# asserts both the PASS path and the FAIL path (a gate that cannot fail is not a gate).
#
# Usage: bash selftest.sh        (exit 0 = everything passed)
set -u
# Location-independent: resolve the skills root from this script's own path, so the
# suite works whether skills live in ~/.cline/skills, ~/.claude/skills, or a repo checkout.
SKILLS="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ESF="$SKILLS/evidence-synthesis-forge/scripts"
MAF="$SKILLS/meta-analysis-forge/scripts"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
no()   { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }
# expect_exit <expected-code> <name> <cmd...>
expect_exit() { local want="$1" name="$2"; shift 2; "$@" >/dev/null 2>&1; local got=$?
  if [ "$got" -eq "$want" ]; then ok "$name (exit $got)"; else no "$name (want $want, got $got)"; fi; }

echo "== 1. Statistical engine: golden tests (accuracy proof) =="
if Rscript "$MAF/golden_tests.R" >"$TMP/gt.log" 2>&1; then
  ok "golden_tests.R all pass ($(grep -c PASS "$TMP/gt.log") checks)"
else
  no "golden_tests.R ($(grep -c FAIL "$TMP/gt.log") failures)"; tail -12 "$TMP/gt.log"
fi

echo "== 2. Citation gate (cross_verify_citations.py) =="
expect_exit 0 "self-test" python3 "$ESF/cross_verify_citations.py" --self-test
# A DOI that does not exist is a FINDING (exit 2). A resolver we could not reach is an INPUT
# GAP (exit 3). Scored as a bare `expect_exit 2`, a network outage used to satisfy this test
# for the wrong reason; now an outage fails it, loudly and accurately.
python3 "$ESF/cross_verify_citations.py" --doi 10.9999/definitely-not-real.1 \
  --out "$TMP/g.json" >/dev/null 2>&1
case $? in
  2) ok "fake DOI is a finding (exit 2; resolver was reached)" ;;
  3) no "fake-DOI check could not run: resolver unreachable (an input gap, NOT a pass)" ;;
  *) no "fake DOI gave an unexpected exit code" ;;
esac
# The evidence invariant, asserted with a dead proxy so it is deterministic and offline:
# a refused connection produces a different status, a different gate word, a different key
# and a different exit code from a 404, and no waiver turns it into a pass.
DEADPROXY="https_proxy=http://127.0.0.1:9 http_proxy=http://127.0.0.1:9 all_proxy=http://127.0.0.1:9"
expect_exit 3 "unreachable resolver -> input gap (exit 3)" \
  env $DEADPROXY python3 "$ESF/cross_verify_citations.py" --doi 10.9999/x --out "$TMP/gap.json"
expect_exit 3 "--allow-unresolved must NOT waive an input gap" \
  env $DEADPROXY python3 "$ESF/cross_verify_citations.py" --doi 10.9999/x \
  --allow-unresolved --out "$TMP/gap2.json"
expect_exit 0 "--allow-insufficient is the logged opt-out" \
  env $DEADPROXY python3 "$ESF/cross_verify_citations.py" --doi 10.9999/x \
  --allow-insufficient --out "$TMP/gap3.json"
expect_exit 3 "recheck keeps the gap open while the resolver is unreachable" \
  env $DEADPROXY python3 "$ESF/cross_verify_citations.py" --recheck "$TMP/gap.json"
cat > "$TMP/check_gap.py" <<'PY'
import json, sys
gap, waived = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
problems = []
if gap["status"] != "insufficient_evidence":
    problems.append("status=%s" % gap["status"])
if gap["gate"] != "INCOMPLETE":
    problems.append("gate=%s" % gap["gate"])
if gap["unresolved"]:
    problems.append("gap counted as unresolved: %s" % gap["unresolved"])
if gap["failures"]:
    problems.append("gap counted as a failure: %s" % gap["failures"])
if len(gap["input_gaps"]) != 1:
    problems.append("input_gaps=%d" % len(gap["input_gaps"]))
elif not gap["input_gaps"][0].get("action"):
    problems.append("gap entry carries no action")
for key in ("status", "gate", "unresolved", "failures"):
    if waived[key] != gap[key]:
        problems.append("--allow-unresolved changed %s" % key)
if len(waived["input_gaps"]) != 1:
    problems.append("waived input_gaps=%d" % len(waived["input_gaps"]))
print("; ".join(problems))
sys.exit(1 if problems else 0)
PY
if python3 "$TMP/check_gap.py" "$TMP/gap.json" "$TMP/gap2.json" >"$TMP/gapcheck.log" 2>&1; then
  ok "input gap kept out of unresolved[] and failures[]; no waiver touches it"
else
  no "input gap leaked into the findings ($(cat "$TMP/gapcheck.log"))"
fi

echo "== 3. PRISMA flow (reconciliation) =="
cat > "$TMP/counts.json" <<'JSON'
{"identified_databases":1847,"identified_registers":60,"identified_other":15,
 "duplicates_removed":512,"removed_automation":0,"removed_other":20,
 "screened":1390,"excluded_ta":1100,"sought":290,"not_retrieved":12,"assessed":278,
 "excluded_ft":{"a":120,"b":45,"c":30,"d":55},
 "included_studies":28,"included_reports":31,"in_meta_analysis":22}
JSON
expect_exit 0 "reconciled counts pass" python3 "$ESF/prisma_flow.py" --counts "$TMP/counts.json" --outdir "$TMP/pf"
printf '{"identified_databases":100,"screened":50}\n' > "$TMP/bad.json"
expect_exit 2 "broken counts FAIL" python3 "$ESF/prisma_flow.py" --counts "$TMP/bad.json" --outdir "$TMP/pf2"

echo "== 4. Summary of findings =="
cat > "$TMP/sof.csv" <<'CSV'
outcome,n_studies,n_participants,effect_measure,relative_effect,ci_lb,ci_ub,baseline_risk,certainty,comments
Mortality,8,4820,RR,0.86,0.74,0.99,0.15,Moderate,x
CSV
expect_exit 0 "valid SoF passes" python3 "$ESF/sof_table.py" --input "$TMP/sof.csv" --outdir "$TMP/sof"
printf 'outcome,n_studies,n_participants,effect_measure,relative_effect,ci_lb,ci_ub,baseline_risk,certainty,comments\nX,3,100,RR,0.8,0.7,0.9,,,\n' > "$TMP/sofbad.csv"
expect_exit 2 "SoF without certainty/baseline FAILS" python3 "$ESF/sof_table.py" --input "$TMP/sofbad.csv" --outdir "$TMP/sofbad"

echo "== 5. PRISMA-S appendix =="
printf 'source,platform,query,date_run,hits,limits\npubmed,NCBI,x,2026-09-20,412,en\n' > "$TMP/sl_ok.csv"
expect_exit 0 "complete search log passes" python3 "$ESF/prisma_s_appendix.py" --search-log "$TMP/sl_ok.csv" --outdir "$TMP/ps1"
printf 'source,query,date_run,hits\nscopus,x,,\n' > "$TMP/sl_bad.csv"
expect_exit 2 "search missing date/hits FAILS" python3 "$ESF/prisma_s_appendix.py" --search-log "$TMP/sl_bad.csv" --outdir "$TMP/ps2"
# A source that was never reached has NO hit count because nobody asked it. That is an input
# gap, not a reproducibility failure, and it must never render as 0 records -- sysreview's own
# rule: "a source that is down must never look like a source that found nothing."
printf 'source,platform,query,date_run,hits,limits,source_status\npubmed,NCBI,x,2026-09-20,412,en,\nembase,Elsevier,x,2026-09-20,0,none,unavailable\n' > "$TMP/sl_unreached.csv"
printf 'source,platform,query,date_run,hits,limits,source_status\npubmed,NCBI,x,2026-09-20,412,en,available\nembase,Elsevier,x,2026-09-20,0,none,available\n' > "$TMP/sl_empty_ok.csv"
expect_exit 3 "an unreached source is an INPUT GAP (exit 3)" \
  python3 "$ESF/prisma_s_appendix.py" --search-log "$TMP/sl_unreached.csv" --outdir "$TMP/ps3"
expect_exit 0 "--allow-insufficient is the logged opt-out" \
  python3 "$ESF/prisma_s_appendix.py" --search-log "$TMP/sl_unreached.csv" --outdir "$TMP/ps4" \
  --allow-insufficient
expect_exit 0 "a searched-and-empty source is a finding, not a gap: 0 still passes" \
  python3 "$ESF/prisma_s_appendix.py" --search-log "$TMP/sl_empty_ok.csv" --outdir "$TMP/ps5"
if grep -q "unavailable (not reached)" "$TMP/ps4/prisma_s_appendix.md" \
   && ! grep -qE "^\| 2 \| embase .* \| 0 \|" "$TMP/ps4/prisma_s_appendix.md"; then
  ok "the appendix renders 'unavailable', never a record count of 0"
else
  no "the appendix rendered an unreached source as 0 records"
fi
# The same condition, one level up: the completeness gate must not report OK over a source
# that was never searched, because the flow's identified total is then a floor, not a total.
mkdir -p "$TMP/comp_unreached"
printf '{"identified_databases":100,"duplicates_removed":0,"screened":100,"excluded_ta":98,"sought":2,"not_retrieved":0,"assessed":2,"included_studies":2}\n' > "$TMP/comp_unreached/prisma_counts.json"
cp "$TMP/sl_unreached.csv" "$TMP/comp_unreached/search_log.csv"
expect_exit 3 "completeness gate: unreached source is an INPUT GAP (exit 3)" \
  python3 "$ESF/check_completeness.py" --root "$TMP/comp_unreached"
expect_exit 0 "completeness gate --allow-insufficient opt-out" \
  python3 "$ESF/check_completeness.py" --root "$TMP/comp_unreached" --allow-insufficient
mkdir -p "$TMP/comp_reached"
cp "$TMP/comp_unreached/prisma_counts.json" "$TMP/comp_reached/prisma_counts.json"
printf 'source,platform,query,date_run,hits,limits,source_status\npubmed,NCBI,x,2026-09-20,412,en,\nembase,Elsevier,x,2026-09-20,0,none,available\n' > "$TMP/comp_reached/search_log.csv"
expect_exit 0 "completeness gate unchanged when every source was reached" \
  python3 "$ESF/check_completeness.py" --root "$TMP/comp_reached"

echo "== 6. Numeric provenance =="
Rscript "$MAF/cochrane_meta.R" --input "$TMP/none.csv" --outdir "$TMP/o" >/dev/null 2>&1 || true
printf '{"pooled":0.49,"ci_lb":0.34,"ci_ub":0.70}\n' > "$TMP/art.json"
printf 'The pooled RR was 0.49 (0.34 to 0.70).\n' > "$TMP/d_ok.md"
expect_exit 0 "traceable numbers pass" python3 "$ESF/numbers_provenance.py" --draft "$TMP/d_ok.md" --artifacts "$TMP/art.json"
printf 'The pooled RR was 0.49 but also 0.77.\n' > "$TMP/d_bad.md"
expect_exit 2 "untraceable number FAILS" python3 "$ESF/numbers_provenance.py" --draft "$TMP/d_bad.md" --artifacts "$TMP/art.json"
# The coding sheet's own vocabulary used to put an unreadable sheet in the finding channel.
# golden_tests.R is R-only and cannot cover this Python pre-gate, so it is pinned here.
printf 'study_id,effect_id,effect_metric,estimate,se\nS1,E1,MD,0.50,0.10\nS2,E2,MD,0.60,0.12\n' > "$TMP/cs_ok.csv"
printf 'study_id,effect_id,effect_metric,estimate,se\nS1,E1,MD,0.50,0.10\nS2,E2,MD,,0.12\n' > "$TMP/cs_blank.csv"
printf 'study_id,effect_id,effect_metric,estimate,se\nS1,E1,MD,0.50,0.10\nS2,E2,MD,,0.12\nS3,E3,MD,0.40,0.11\nS4,E4,MD,0.55,0.10\n' > "$TMP/cs_blank_engine.csv"
printf 'study_id,effect_id,effect_metric,estimate,se\nS1,E1,MD,0.50,0.10\nS2,E2,MD,0.60,0.00\n' > "$TMP/cs_se0.csv"
expect_exit 0 "a valid coding sheet passes" python3 "$MAF/validate_coding_sheet.py" --input "$TMP/cs_ok.csv"
expect_exit 3 "a blank effect size is an INPUT CONDITION (exit 3)" python3 "$MAF/validate_coding_sheet.py" --input "$TMP/cs_blank.csv"
expect_exit 3 "se <= 0 is an INPUT CONDITION (exit 3)" python3 "$MAF/validate_coding_sheet.py" --input "$TMP/cs_se0.csv"
expect_exit 4 "an unreadable coding sheet is insufficient_input (exit 4)" python3 "$MAF/validate_coding_sheet.py" --input "$TMP/no-such-sheet.csv"
# ...and the same condition in the engine: a pooled estimate must not be written over a subset.
expect_exit 3 "the engine refuses a partly unusable sheet (exit 3)" Rscript "$MAF/cochrane_meta.R" --input "$TMP/cs_blank_engine.csv" --outdir "$TMP/ma_blank"
# run_meta_analysis.R prints summary(model), which carries I^2/H^2/Q; with QE <= df those are
# undefined, and printing 0.0% reads as "no heterogeneity" -- a claim about the literature
# rather than a statement that the quantity could not be estimated.
printf 'study_id,effect_id,effect_metric,estimate,se\nS1,E1,MD,0.50,0.10\nS2,E2,MD,0.50,0.10\n' > "$TMP/rma_k2.csv"
printf 'study_id,effect_id,effect_metric,estimate,se\nS1,E1,MD,0.10,0.05\nS2,E2,MD,0.90,0.05\nS3,E3,MD,0.30,0.05\nS4,E4,MD,0.70,0.05\nS5,E5,MD,0.50,0.05\n' > "$TMP/rma_spread.csv"
expect_exit 0 "run_meta_analysis on a k=2 sheet" Rscript "$MAF/run_meta_analysis.R" --input "$TMP/rma_k2.csv" --outdir "$TMP/rma_k2_out"
if grep -q "not estimable (QE <= df)" "$TMP/rma_k2_out/meta-summary.txt" \
   && grep -q "not estimable" "$TMP/rma_k2_out/model-results.csv"; then
  ok "heterogeneity is reported as not estimable when QE <= df (not as 0%)"
else
  no "heterogeneity was printed as a number when it is not estimable"
fi
expect_exit 0 "run_meta_analysis on a spread sheet" Rscript "$MAF/run_meta_analysis.R" --input "$TMP/rma_spread.csv" --outdir "$TMP/rma_spread_out"
if ! grep -q "not estimable" "$TMP/rma_spread_out/meta-summary.txt" \
   && grep -q '"97.5"\|97.5' "$TMP/rma_spread_out/model-results.csv"; then
  ok "heterogeneity is still reported normally when QE > df"
else
  no "an estimable heterogeneity was suppressed"
fi
printf '\x00\x01\x02 binary junk \x00' > "$TMP/rma_junk.csv"
expect_exit 4 "an unparseable sheet is insufficient_input (exit 4)" Rscript "$MAF/run_meta_analysis.R" --input "$TMP/rma_junk.csv" --outdir "$TMP/rma_junk_out"
if [ ! -f "$TMP/ma_blank/results.json" ]; then
  ok "no pooled estimate is written when rows were dropped"
else
  no "the engine wrote a pooled estimate over a subset of the supplied rows"
fi
# A supplied artifact that could not be read is an input gap, not a clean check. This used to
# print "WARNING: artifact not found (skipped)" and then "OK: every checked number is
# traceable" with exit 0 -- a partial comparison presented as a complete one.
expect_exit 3 "a missing artifact is an INPUT GAP, not an OK (exit 3)" \
  python3 "$ESF/numbers_provenance.py" --draft "$TMP/d_ok.md" \
  --artifacts "$TMP/art.json" "$TMP/does-not-exist.json"
expect_exit 0 "--allow-incomplete is the logged opt-out" \
  python3 "$ESF/numbers_provenance.py" --draft "$TMP/d_ok.md" \
  --artifacts "$TMP/art.json" "$TMP/does-not-exist.json" --allow-incomplete
expect_exit 3 "no readable artifact at all is an input gap (exit 3)" \
  python3 "$ESF/numbers_provenance.py" --draft "$TMP/d_ok.md" \
  --artifacts "$TMP/nope1.json" "$TMP/nope2.json"
expect_exit 4 "an unreadable draft is insufficient_input (exit 4)" \
  python3 "$ESF/numbers_provenance.py" --draft "$TMP/no-such-draft.md" --artifacts "$TMP/art.json"
if python3 "$ESF/numbers_provenance.py" --draft "$TMP/d_ok.md" \
     --artifacts "$TMP/art.json" "$TMP/does-not-exist.json" 2>&1 | grep -q "OK: every checked"; then
  no "the partial-artifact run still claims every number is traceable"
else
  ok "a partial-artifact run never claims every number is traceable"
fi

echo "== 7. Cross-artifact integrity (R/C/C2/D/M/E/X/T/W/P) =="
expect_exit 0 "integrity selftest (18 assertions)" python3 "$ESF/check_review_integrity.py" --selftest
mkdir -p "$TMP/rev/ledgers"
printf 'source_id,s_id,doi,pmid,title,year,inclusion_status,exclusion_reason,country\nS001,S001,10.1/x,1,T,2024,included,,India\n' > "$TMP/rev/sources.csv"
printf 'claim_id,claim_summary,supporting_sids\nC001,An LSTM outperformed VAR, boosted and SVR baselines (RMSE 0.345\n' > "$TMP/rev/claims.csv"
printf 'source_id,primary_outcome,effect_primary,extraction_note\nS001,Acute care visits,RR 0.5,x\n' > "$TMP/rev/ledgers/extraction.csv"
printf 'source_id,tool,domain_summary\nS001,PROBAST,participants low; analysis low; overall low\n' > "$TMP/rev/ledgers/rob_assessment.csv"
printf 'source_id\nS001\n' > "$TMP/rev/ledgers/sources_included.csv"
printf '## References\n1. [src:S001] T.\n' > "$TMP/rev/manuscript.md"
printf '{"screening":{"records_screened":1,"records_excluded":0},"retrieval":{"reports_sought":1,"reports_not_retrieved":0},"eligibility":{"reports_assessed":1,"reports_excluded":0},"included":{"studies_included":1},"identification":{"records_from_databases":10,"duplicates_removed":1}}\n' > "$TMP/rev/prisma_counts.json"
expect_exit 2 "prose-in-ID-column claims row FAILS integrity" python3 "$ESF/check_review_integrity.py" --root "$TMP/rev"

echo "== 8. Screening-ledger completeness =="
expect_exit 0 "ledger-completeness selftest" python3 "$ESF/check_ledger_completeness.py" --selftest
mkdir -p "$TMP/lc"
printf 'source_id,s_id,inclusion_status,exclusion_reason,country\nS001,S001,included,multi-country,India\n' > "$TMP/lc/sources.csv"
printf '{"screening":{"records_screened":234},"included":{"studies_included":1}}\n' > "$TMP/lc/prisma_counts.json"
expect_exit 2 "short ledger + INCLUDE-with-reason FAILS" python3 "$ESF/check_ledger_completeness.py" --root "$TMP/lc"

echo "== 9. Appraisal honesty =="
expect_exit 0 "appraisal selftest" python3 "$ESF/check_appraisal.py" --selftest
mkdir -p "$TMP/ra/ledgers"
printf 'source_id,tool,domain_summary\nS001,PROBAST (conceptual),no clinical prediction model to fully score\n' > "$TMP/ra/ledgers/rob_assessment.csv"
printf 'Appraisal used PROBAST in concept.\n' > "$TMP/ra/manuscript.md"
expect_exit 2 "placeholder appraisal FAILS" python3 "$ESF/check_appraisal.py" --root "$TMP/ra"

echo "== 10. Regression suite (one fixture per defect class) =="
expect_exit 0 "all defect fixtures are caught" python3 "$ESF/regression_suite.py"

echo "== 11. Gate 2a screening calibration (pilot kappa) =="
expect_exit 0 "gate2a selftest" python3 "$ESF/gate2a_calibration.py" --selftest
cat > "$TMP/pilot.csv" <<'CSV'
record_id,pass1,pass2
P1,INCLUDE,EXCLUDE
P2,EXCLUDE,INCLUDE
P3,INCLUDE,EXCLUDE
P4,EXCLUDE,INCLUDE
CSV
expect_exit 2 "kappa below threshold FAILS" python3 "$ESF/gate2a_calibration.py" --pilot "$TMP/pilot.csv" --out "$TMP/g2a.json" --min-n 0

echo "== 12. RoB figure writer (must never claim success on failure) =="
printf 'Study,D1,D2,D3,D4,D5,Overall\nS1,Low,Low,Low,Low,Low,Low\nS2,Low,Some concerns,Low,Low,Low,Low\nS3,High,Low,Some concerns,High,Some concerns,High\n' > "$TMP/rob_ok.csv"
if Rscript "$MAF/rob_figure.R" --input "$TMP/rob_ok.csv" --outdir "$TMP/robf" --tool ROB2 \
     >"$TMP/rob_ok.log" 2>&1 \
   && [ -s "$TMP/robf/rob_traffic_light.pdf" ] && [ -s "$TMP/robf/rob_summary.pdf" ]; then
  ok "valid RoB sheet -> both figures written"
else
  no "valid RoB sheet -> both figures written"; tail -5 "$TMP/rob_ok.log"
fi
printf 'study,dom1,dom2,dom3,overall\nS1,Low,Low,Low,Low\n' > "$TMP/rob_bad.csv"
expect_exit 1 "malformed RoB sheet FAILS loudly (no false success)" Rscript "$MAF/rob_figure.R" \
  --input "$TMP/rob_bad.csv" --outdir "$TMP/robb" --tool ROB2
expect_exit 0 "built-in traffic-light matches robvis cell-for-cell" Rscript "$MAF/validate_rob_fallback.R"
expect_exit 0 "valid RoB sheet passes (explicit pass path)" Rscript "$MAF/rob_figure.R" \
  --input "$TMP/rob_ok.csv" --outdir "$TMP/robf2" --tool ROB2
expect_exit 1 "validator detects a corrupted fallback mapping" Rscript "$MAF/validate_rob_fallback.R" --mutate

echo "== 13. Optional analyses surfaced + PRISMA flow stage guard =="
cat > "$TMP/opt.csv" <<'CSV'
study_id,effect_id,effect_metric,estimate,se,cluster,dose
S01,E01,SMD,0.21,0.12,A,10
S02,E02,SMD,0.33,0.14,A,15
S03,E03,SMD,0.45,0.11,A,20
S04,E04,SMD,0.28,0.13,A,25
S05,E05,SMD,0.52,0.16,A,30
S06,E06,SMD,0.37,0.12,A,35
S07,E07,SMD,0.19,0.15,B,40
S08,E08,SMD,0.41,0.13,B,45
S09,E09,SMD,0.55,0.14,B,50
S10,E10,SMD,0.31,0.11,B,55
S11,E11,SMD,0.48,0.17,B,60
S12,E12,SMD,0.26,0.12,B,65
CSV
Rscript "$MAF/cochrane_meta.R" --input "$TMP/opt.csv" --outdir "$TMP/o_rve" --rve >/dev/null 2>&1
if grep -q 'RVE (CR2) cluster-robust CI' "$TMP/o_rve/summary.txt" 2>/dev/null; then
  ok "--rve result is reported, not silently dropped"
else
  no "--rve result is reported, not silently dropped"
fi
Rscript "$MAF/cochrane_meta.R" --input "$TMP/opt.csv" --outdir "$TMP/o_mr" --moderator dose >/dev/null 2>&1
if grep -q 'Meta-regression' "$TMP/o_mr/summary.txt" 2>/dev/null; then
  ok "--moderator result is reported, not silently dropped"
else
  no "--moderator result is reported, not silently dropped"
fi
printf 'stage,count,label\nbogus,1,x\n' > "$TMP/flow_bad.csv"
expect_exit 2 "PRISMA flow with unrecognised stage names FAILS" python3 "$ESF/generate_prisma_flow.py" \
  --input "$TMP/flow_bad.csv" --output "$TMP/flow_bad.md"
printf 'stage,count,label
records_database,10,DB
records_screened,9,S
' > "$TMP/flow_ok.csv"
expect_exit 0 "PRISMA flow with recognised stages passes" python3 "$ESF/generate_prisma_flow.py" \
  --input "$TMP/flow_ok.csv" --output "$TMP/flow_ok.md"

echo "== 14. All PRISMA consumers accept both count shapes =="
mkdir -p "$TMP/pf_shape/ledgers"
printf '{"identified_databases":10,"duplicates_removed":1,"screened":9,"excluded_ta":7,' > "$TMP/pf_shape/prisma_counts.json"
printf '"sought":2,"not_retrieved":0,"assessed":2,"excluded_ft":{},"included_studies":2,' >> "$TMP/pf_shape/prisma_counts.json"
printf '"included_reports":2,"in_meta_analysis":2}\n' >> "$TMP/pf_shape/prisma_counts.json"
printf 'source_id,s_id,doi,pmid,title,year,inclusion_status,exclusion_reason\n' > "$TMP/pf_shape/sources.csv"
printf 'S001,S001,10.1136/bmj.n71,1,Study one,2024,included,\n' >> "$TMP/pf_shape/sources.csv"
printf 'S002,S002,10.1136/bmj.n71,2,Study two,2024,included,\n' >> "$TMP/pf_shape/sources.csv"
i=3; while [ $i -le 9 ]; do
  printf 'S%03d,S%03d,10.1136/bmj.n71,%d,Study %d,2024,excluded,ER-001: not a primary trial\n' "$i" "$i" "$i" "$i" >> "$TMP/pf_shape/sources.csv"
  i=$((i+1))
done
printf 'claim_id,claim_summary,supporting_sids\nC001,"The evidence is limited.","S001,S002"\n' > "$TMP/pf_shape/claims.csv"
printf 'source_id,primary_outcome,effect_primary,extraction_note\nS001,AAD incidence,RR 0.64,x\nS002,AAD incidence,RR 1.08,x\n' > "$TMP/pf_shape/ledgers/extraction.csv"
printf 'source_id,tool,domain_summary\nS001,RoB 2,randomisation low; deviations low; overall low\nS002,RoB 2,randomisation low; deviations low; overall low\n' > "$TMP/pf_shape/ledgers/rob_assessment.csv"
printf 'source_id\nS001\nS002\n' > "$TMP/pf_shape/ledgers/sources_included.csv"
printf '## References\n1. [src:S001] Study one.\n2. [src:S002] Study two.\n' > "$TMP/pf_shape/manuscript.md"
expect_exit 0 "flat PRISMA shape: prisma_flow accepts it" python3 "$ESF/prisma_flow.py" \
  --counts "$TMP/pf_shape/prisma_counts.json" --outdir "$TMP/pf_shape/out"
expect_exit 0 "flat PRISMA shape: ledger-completeness accepts it" python3 "$ESF/check_ledger_completeness.py" \
  --root "$TMP/pf_shape"
expect_exit 0 "flat PRISMA shape: review-integrity accepts it" python3 "$ESF/check_review_integrity.py" \
  --root "$TMP/pf_shape"
printf '{"nonsense":1}\n' > "$TMP/pf_shape/prisma_counts.json"
expect_exit 1 "unrecognised PRISMA shape fails legibly (no traceback)" python3 "$ESF/check_ledger_completeness.py" \
  --root "$TMP/pf_shape"
rm -f "$TMP/pf_shape/manuscript.md"
printf '{"identified_databases":10,"duplicates_removed":1,"screened":9,"excluded_ta":7,"sought":2,"not_retrieved":0,"assessed":2,"excluded_ft":{},"included_studies":2}\n' > "$TMP/pf_shape/prisma_counts.json"
expect_exit 2 "missing mandatory artifact reported as a finding, not a traceback" python3 "$ESF/check_review_integrity.py" \
  --root "$TMP/pf_shape"

echo "== 15. Completeness gate + mixed-metric refusal =="
mkdir -p "$TMP/cmp"
printf '{"identified_databases":83,"duplicates_removed":0,"removed_other":23,"screened":60,' > "$TMP/cmp/prisma_counts.json"
printf '"excluded_ta":39,"sought":21,"not_retrieved":19,"assessed":2,"excluded_ft":{},' >> "$TMP/cmp/prisma_counts.json"
printf '"included_studies":2,"included_reports":2,"in_meta_analysis":2}\n' >> "$TMP/cmp/prisma_counts.json"
expect_exit 2 "incomplete review FAILS the completeness gate" python3 "$ESF/check_completeness.py" --root "$TMP/cmp"
printf '{"waivers":[{"key":"removed_other","value":23,"reason":"pilot scope","approved_by":"user:drb"},' > "$TMP/cmp/completeness_waivers.json"
printf '{"key":"not_retrieved","value":19,"reason":"abstract-only pilot","approved_by":"user:drb"}]}\n' >> "$TMP/cmp/completeness_waivers.json"
expect_exit 0 "attributed waiver makes the gap acceptable" python3 "$ESF/check_completeness.py" --root "$TMP/cmp"
printf '{"waivers":[{"key":"removed_other","value":23,"reason":"pilot scope","approved_by":"user:drb"},' > "$TMP/cmp/completeness_waivers.json"
printf '{"key":"not_retrieved","value":5,"reason":"stale","approved_by":"user:drb"}]}\n' >> "$TMP/cmp/completeness_waivers.json"
expect_exit 2 "STALE waiver (declared value != actual gap) FAILS" python3 "$ESF/check_completeness.py" --root "$TMP/cmp"
printf '{"waivers":[{"key":"removed_other","value":23,"reason":"x"}]}\n' > "$TMP/cmp/completeness_waivers.json"
expect_exit 2 "waiver with no approver FAILS" python3 "$ESF/check_completeness.py" --root "$TMP/cmp"
mkdir -p "$TMP/one_src"
printf '{"identified_databases":10,"duplicates_removed":0,"removed_other":0,"screened":10,' > "$TMP/one_src/prisma_counts.json"
printf '"excluded_ta":8,"sought":2,"not_retrieved":0,"assessed":2,"excluded_ft":{},' >> "$TMP/one_src/prisma_counts.json"
printf '"included_studies":2}\n' >> "$TMP/one_src/prisma_counts.json"
printf 'source,platform,query,date_run,hits\npubmed,NCBI,x,2026-10-02,10\n' > "$TMP/one_src/search_log.csv"
expect_exit 2 "a SINGLE-source search FAILS the completeness gate" python3 "$ESF/check_completeness.py" --root "$TMP/one_src"
printf 'source,platform,query,date_run,hits\npubmed,NCBI,x,2026-10-02,10\nclinicaltrials,CTgov,y,2026-10-02,3\n' > "$TMP/one_src/search_log.csv"
expect_exit 0 "two sources (bibliographic + registry) PASS" python3 "$ESF/check_completeness.py" --root "$TMP/one_src"
printf 'study_id,effect_id,effect_metric,estimate,se\nS1,E1,RR,0.1,0.2\nS2,E2,OR,0.3,0.2\n' > "$TMP/mixed.csv"
expect_exit 1 "mixed effect metrics REFUSE to pool (Handbook ch.6)" Rscript "$MAF/cochrane_meta.R" \
  --input "$TMP/mixed.csv" --outdir "$TMP/mixed_out"
expect_exit 0 "explicit --allow-mixed-metrics permits it" Rscript "$MAF/cochrane_meta.R" \
  --input "$TMP/mixed.csv" --outdir "$TMP/mixed_out2" --allow-mixed-metrics
expect_exit 0 "PubMed DOI is scoped to the article, not its reference list" python3 "$ESF/fetch_pubmed_complete.py" --self-test
expect_exit 1 "complete-fetch refuses to run without --query/--out" python3 "$ESF/fetch_pubmed_complete.py"

echo "== 16. Screening-conduct disclosure + heuristic fixtures + meta-coverage =="
mkdir -p "$TMP/sd"
printf 'record_id,decision,rule,confidence\nS1,INCLUDE,none,high\n' > "$TMP/sd/screening_log.csv"
printf '## Abstract\nTwo reviewers independently screened all records.\n' > "$TMP/sd/manuscript.md"
expect_exit 2 "manuscript claiming human screening FAILS disclosure" python3 "$ESF/check_screening_disclosure.py" --root "$TMP/sd"
printf 'CONDUCT_DISCLOSURE:\n  mode: autonomous\n  human_involvement: none\n' > "$TMP/sd/CONDUCT_DISCLOSURE.txt"
printf '## Abstract\nAI-assisted, autonomously conducted; not human-screened.\n' > "$TMP/sd/manuscript.md"
expect_exit 0 "honest negation of human screening PASSES" python3 "$ESF/check_screening_disclosure.py" --root "$TMP/sd"
expect_exit 0 "humanizer pattern fixtures behave as documented" python3 "$SKILLS/humanizerdrb/scripts/humanizer_check.py" --self-test
printf 'Readmissions fell by 32%%.\n' > "$TMP/sd/before.md"
printf 'Readmissions fell by 45%%.\n' > "$TMP/sd/after.md"
expect_exit 2 "humanizer H1/H2 numeric violation FAILS" python3 "$SKILLS/humanizerdrb/scripts/humanizer_check.py" \
  --before "$TMP/sd/before.md" --after "$TMP/sd/after.md"
printf 'Readmissions fell by 32%%.\n' > "$TMP/sd/after2.md"
expect_exit 0 "humanizer accepts a faithful rewrite" python3 "$SKILLS/humanizerdrb/scripts/humanizer_check.py" \
  --before "$TMP/sd/before.md" --after "$TMP/sd/after2.md"
expect_exit 0 "every gate has a pass and a fail fixture" python3 "$ESF/check_selftest_coverage.py" --selftest "$ESF/selftest.sh"

echo
printf 'RESULT: %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ] && exit 0 || exit 1
