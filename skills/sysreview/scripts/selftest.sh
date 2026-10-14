#!/usr/bin/env bash
# selftest.sh -- the routing-contract and gate-fixture self-test for /sysreview.
#
# Three things are pinned here:
#   1. every request class in the skill's ROUTE block reaches its declared target;
#   2. an unknown request does NOT silently route (and the check that proves it can fail);
#   3. every gate the skill declares has a pass fixture and a fail fixture, and the
#      offline fixtures run and produce the declared exit code.
#
# Exit codes: 0 every fixture passed; 1 a fixture failed; 4 input gap (never a pass).
#
# Usage: bash selftest.sh
set -u
# Location-independent: resolve the skills root from this script's own path.
SKILLS="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKILL="$SKILLS/sysreview/SKILL.md"
ESF="$SKILLS/evidence-synthesis-forge/scripts"
TOOLS="$SKILLS/../tools"
MG="$SKILLS/sysreview/scripts/manuscript_gate.py"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

pass=0; fail=0; declared=0
ok()      { printf '  PASS %s\n' "$1"; pass=$((pass+1)); }
no()      { printf '  FAIL %s\n' "$1"; fail=$((fail+1)); }
declare_(){ printf '  DECL %s -- %s\n' "$1" "$2"; declared=$((declared+1)); }
# expect_exit <expected-code> <name> <cmd...>
expect_exit() { local want="$1" name="$2"; shift 2; "$@" >/dev/null 2>&1; local got=$?
  if [ "$got" -eq "$want" ]; then ok "$name (exit $got)"; else no "$name (want $want, got $got)"; fi; }

# ---------------------------------------------------------------- input gap ---
# A missing contract is an input gap, not a pass. Exit 4 and say why.
[ -f "$SKILL" ] || { echo "selftest: $SKILL missing (input gap, not a pass)" >&2; exit 4; }
grep -qE '^ROUTE ' "$SKILL" || { echo "selftest: no ROUTE block in $SKILL (input gap)" >&2; exit 4; }
grep -qE '^FALLBACK ' "$SKILL" || { echo "selftest: no FALLBACK line in $SKILL (input gap)" >&2; exit 4; }
grep -qE '^GATE ' "$SKILL" || { echo "selftest: no GATE registry in $SKILL (input gap)" >&2; exit 4; }
[ -d "$ESF" ] || { echo "selftest: $ESF missing (input gap, not a pass)" >&2; exit 4; }
[ -f "$TOOLS/attribution.py" ] || { echo "selftest: $TOOLS/attribution.py missing (input gap, not a pass)" >&2; exit 4; }
[ -f "$MG" ] || { echo "selftest: $MG missing (input gap, not a pass)" >&2; exit 4; }

# ------------------------------------------------------------------- router ---
# The router reads the skill's own ROUTE block. The fixture is only the request text;
# the expected target is the contract's own answer, so a contract edit moves the test.
cat > "$TMP/router.py" <<'PY'
import re, sys
skill, request = sys.argv[1], sys.argv[2]
routes = []
for line in open(skill, encoding="utf-8"):
    m = re.match(r"ROUTE\s+(.+?)\s*->\s*([A-Za-z0-9_-]+)\s*$", line.strip())
    if m:
        routes.append(([k.strip() for k in m.group(1).split(",") if k.strip()], m.group(2)))

def route(text):
    t = text.lower()
    for keys, target in routes:
        for key in keys:
            parts = [re.escape(p) for p in key.lower().split("-")]
            pat = r"(?<![a-z0-9])" + r"[-_ ]?".join(parts) + r"(?![a-z0-9])"
            if re.search(pat, t):
                return target
    return "FALLBACK"

print(route(request))
PY

cat > "$TMP/routes.tsv" <<'TSV'
self	run a systematic review on ventilator-associated pneumonia
self	conduct a PRISMA 2020 review of the evidence
evidence-synthesis-forge	design the protocol and the eligibility criteria
meta-ml-screener	screen these records and triage them
meta-analysis	pool the effect sizes and check heterogeneity
umbrella-review-skeptic	summarise the existing reviews as a review of reviews
environment-life-review-forge	an ecological life-science review
paper-search	search sources and retrieve records from a registry
citecheck	do a citation verification and resolve the DOI
humanizerdrb	humanize the final prose and pick a register
TSV

echo "== 1. Routing contract: every request reaches its target =="
while IFS=$'\t' read -r want request; do
  [ -n "$want" ] || continue
  got="$(python3 "$TMP/router.py" "$SKILL" "$request")"
  if [ "$got" = "$want" ]; then ok "route '$request' -> $want"; else no "route '$request' -> $got (want $want)"; fi
done < "$TMP/routes.tsv"

# Every target the contract names must have a fixture. A new target without one is a
# routing rule nobody tests.
grep -E '^ROUTE ' "$SKILL" | sed -E 's/.*->[[:space:]]*//; s/[[:space:]]+$//' | sort -u > "$TMP/targets_declared.txt"
cut -f1 "$TMP/routes.tsv" | sort -u > "$TMP/targets_fixtured.txt"
missing="$(comm -23 "$TMP/targets_declared.txt" "$TMP/targets_fixtured.txt" | tr '\n' ' ')"
if [ -z "$missing" ]; then ok "every declared route target has a fixture"; else no "targets with no fixture: $missing"; fi

echo "== 2. An unknown request must not silently route =="
got="$(python3 "$TMP/router.py" "$SKILL" "write a haiku about the ocean")"
if [ "$got" = "FALLBACK" ]; then ok "unknown request falls back instead of routing"; else no "unknown request silently routed to $got"; fi
# The declared fallback behaviour: stop, record an input gap (exit 4), never guess.
fb="$(grep -E '^FALLBACK ' "$SKILL")"
case "$fb" in
  *"exit 4"*"never guess"*) ok "the fallback declares exit 4 and refuses to guess" ;;
  *) no "the fallback line does not declare exit 4 and a refusal to guess" ;;
esac
# The check above CAN fail: an over-broad keyword makes the unknown request route.
cp "$SKILL" "$TMP/mutated.md"
printf '\nROUTE the -> meta-analysis\n' >> "$TMP/mutated.md"
got="$(python3 "$TMP/router.py" "$TMP/mutated.md" "write a haiku about the ocean")"
if [ "$got" != "FALLBACK" ]; then ok "an over-broad keyword is detected (mutation routed to $got)"; else no "mutation not detected: the silent-route check cannot fail"; fi

echo "== 3. Every declared gate has a pass fixture and a fail fixture =="
grep -E '^GATE ' "$SKILL" | sed -E 's/^GATE[[:space:]]+([a-z0-9-]+).*/\1/' | sort -u > "$TMP/gates.txt"
# Two explicit lists, kept in step with the fixtures in section 4. A gate added to the
# skill registry without a fixture on either path is caught here.
PASS_FIXTURED=" toolchain search-reproducibility prisma-counts citation-integrity numeric-provenance cross-artifact-integrity ledger-completeness review-completeness screening-disclosure gate-coverage appraisal-honesty screening-calibration certainty defect-regressions acceptance-live manuscript-attribution "
FAIL_FIXTURED=" toolchain search-reproducibility prisma-counts citation-integrity numeric-provenance cross-artifact-integrity ledger-completeness review-completeness screening-disclosure gate-coverage appraisal-honesty screening-calibration certainty defect-regressions acceptance-live manuscript-attribution "
while read -r g; do
  case "$PASS_FIXTURED" in *" $g "*) ;; *) no "gate '$g' has no pass fixture";; esac
  case "$FAIL_FIXTURED" in *" $g "*) ;; *) no "gate '$g' has no fail fixture";; esac
done < "$TMP/gates.txt"
# Every declared gate must also appear in the fixture section below, and section 4 must
# carry at least two fixture lines (a pass and a fail) for each declared gate.
awk '/^echo "== 4\. Fixtures =="/{f=1} f' "$0" > "$TMP/fixture_section.sh"
while read -r g; do
  grep -q -- "$g" "$TMP/fixture_section.sh" || no "gate '$g' has no fixture line in section 4"
done < "$TMP/gates.txt"
gates_n="$(wc -l < "$TMP/gates.txt" | tr -d ' ')"
fixtures_n="$(grep -cE '^[[:space:]]*(expect_exit|declare_)' "$TMP/fixture_section.sh" || true)"
if [ "$fixtures_n" -ge $((2 * gates_n)) ]; then
  ok "gate-fixture coverage: $gates_n declared gate(s), $fixtures_n fixture line(s)"
else
  no "gate-fixture coverage: $gates_n gate(s) need $((2 * gates_n)) fixture lines, found $fixtures_n"
fi

echo "== 4. Fixtures =="
mkdir -p "$TMP/rev/ledgers" "$TMP/lc" "$TMP/lc2" "$TMP/comp" "$TMP/sd" "$TMP/ra/ledgers" "$TMP/ra2/ledgers"
# search reproducibility
printf 'source,platform,query,date_run,hits,limits\npubmed,NCBI,x,2026-09-20,412,en\n' > "$TMP/sl_ok.csv"
printf 'source,query,date_run,hits\nscopus,x,,\n' > "$TMP/sl_bad.csv"
# PRISMA counts
printf '{"identified_databases":100,"duplicates_removed":1,"screened":99,"excluded_ta":97,"sought":2,"not_retrieved":0,"assessed":2,"excluded_ft":{},"included_studies":2}\n' > "$TMP/counts_ok.json"
printf '{"identified_databases":100,"screened":50}\n' > "$TMP/counts_bad.json"
# numeric provenance
printf '{"pooled":0.49,"ci_lb":0.34,"ci_ub":0.70}\n' > "$TMP/art.json"
printf 'The pooled RR was 0.49 (0.34 to 0.70).\n' > "$TMP/d_ok.md"
printf 'The pooled RR was 0.49 but also 0.77.\n' > "$TMP/d_bad.md"
# cross-artifact integrity (the ESF fixture)
printf 'source_id,s_id,doi,pmid,title,year,inclusion_status,exclusion_reason,country\nS001,S001,10.1/x,1,T,2024,included,,India\n' > "$TMP/rev/sources.csv"
printf 'claim_id,claim_summary,supporting_sids\nC001,An LSTM outperformed VAR, boosted and SVR baselines (RMSE 0.345\n' > "$TMP/rev/claims.csv"
printf 'source_id,primary_outcome,effect_primary,extraction_note\nS001,Acute care visits,RR 0.5,x\n' > "$TMP/rev/ledgers/extraction.csv"
printf 'source_id,tool,domain_summary\nS001,PROBAST,participants low; analysis low; overall low\n' > "$TMP/rev/ledgers/rob_assessment.csv"
printf 'source_id\nS001\n' > "$TMP/rev/ledgers/sources_included.csv"
printf '## References\n1. [src:S001] T.\n' > "$TMP/rev/manuscript.md"
printf '{"screening":{"records_screened":1,"records_excluded":0},"retrieval":{"reports_sought":1,"reports_not_retrieved":0},"eligibility":{"reports_assessed":1,"reports_excluded":0},"included":{"studies_included":1},"identification":{"records_from_databases":10,"duplicates_removed":1}}\n' > "$TMP/rev/prisma_counts.json"
# ledger completeness
printf 'source_id,s_id,inclusion_status,exclusion_reason,country\nS001,S001,included,multi-country,India\n' > "$TMP/lc/sources.csv"
printf '{"screening":{"records_screened":234},"included":{"studies_included":1}}\n' > "$TMP/lc/prisma_counts.json"
printf 'source_id,s_id,inclusion_status,exclusion_reason,country\nS001,S001,included,,India\n' > "$TMP/lc2/sources.csv"
printf '{"screening":{"records_screened":1},"included":{"studies_included":1}}\n' > "$TMP/lc2/prisma_counts.json"
# review completeness
printf '{"identified_databases":100,"duplicates_removed":0,"screened":100,"excluded_ta":98,"sought":2,"not_retrieved":0,"assessed":2,"included_studies":2}\n' > "$TMP/comp/prisma_counts.json"
printf 'source,platform,query,date_run,hits,limits,source_status\npubmed,NCBI,x,2026-09-20,412,en,available\nembase,Elsevier,x,2026-09-20,0,none,available\n' > "$TMP/comp/search_log.csv"
# screening-conduct disclosure
mkdir -p "$TMP/sd_ok"
printf 'record_id,decision,rule,confidence\nS1,INCLUDE,none,high\n' > "$TMP/sd/screening_log.csv"
printf '## Abstract\nTwo reviewers independently screened all records.\n' > "$TMP/sd/manuscript.md"
printf 'record_id,decision,rule,confidence\nS1,INCLUDE,none,high\n' > "$TMP/sd_ok/screening_log.csv"
printf 'CONDUCT_DISCLOSURE:\n  mode: autonomous\n  human_involvement: none\n' > "$TMP/sd_ok/CONDUCT_DISCLOSURE.txt"
printf '## Abstract\nAI-assisted, autonomously conducted; not human-screened.\n' > "$TMP/sd_ok/manuscript.md"
# appraisal honesty
printf 'source_id,tool,domain_summary\nS001,PROBAST (conceptual),no clinical prediction model to fully score\n' > "$TMP/ra/ledgers/rob_assessment.csv"
printf 'Appraisal used PROBAST in concept.\n' > "$TMP/ra/manuscript.md"
printf 'source_id,tool,domain_summary\nS001,PROBAST,participants low; analysis low; overall low\n' > "$TMP/ra2/ledgers/rob_assessment.csv"
printf 'Appraisal used PROBAST.\n' > "$TMP/ra2/manuscript.md"
# screening calibration
printf 'record_id,pass1,pass2\nP1,INCLUDE,INCLUDE\nP2,EXCLUDE,EXCLUDE\nP3,INCLUDE,INCLUDE\nP4,EXCLUDE,EXCLUDE\n' > "$TMP/pilot_ok.csv"
printf 'record_id,pass1,pass2\nP1,INCLUDE,EXCLUDE\nP2,EXCLUDE,INCLUDE\nP3,INCLUDE,EXCLUDE\nP4,EXCLUDE,INCLUDE\n' > "$TMP/pilot_bad.csv"
# summary of findings
printf 'outcome,n_studies,n_participants,effect_measure,relative_effect,ci_lb,ci_ub,baseline_risk,certainty,comments\nMortality,8,4820,RR,0.86,0.74,0.99,0.15,Moderate,x\n' > "$TMP/sof.csv"
printf 'outcome,n_studies,n_participants,effect_measure,relative_effect,ci_lb,ci_ub,baseline_risk,certainty,comments\nX,3,100,RR,0.8,0.7,0.9,,,\n' > "$TMP/sofbad.csv"
# gate coverage (the meta-gate's own fixtures)
printf 'expect_exit 0 "pass path" python3 foo.py\nexpect_exit 2 "fail path" python3 foo.py\n' > "$TMP/cov_ok.sh"
printf 'expect_exit 0 "pass only" python3 bar.py\n' > "$TMP/cov_bad.sh"

expect_exit 0 "toolchain: doctor.sh passes (pass)" bash "$ESF/doctor.sh"
declare_ "toolchain (fail)" "a missing dependency is environment-specific and is not simulated"
expect_exit 0 "search-reproducibility: complete log (pass)" python3 "$ESF/prisma_s_appendix.py" --search-log "$TMP/sl_ok.csv" --outdir "$TMP/ps1"
expect_exit 2 "search-reproducibility: no date/hits (fail)" python3 "$ESF/prisma_s_appendix.py" --search-log "$TMP/sl_bad.csv" --outdir "$TMP/ps2"
expect_exit 0 "prisma-counts: reconciled (pass)" python3 "$ESF/prisma_flow.py" --counts "$TMP/counts_ok.json" --outdir "$TMP/pf1"
expect_exit 2 "prisma-counts: broken arithmetic (fail)" python3 "$ESF/prisma_flow.py" --counts "$TMP/counts_bad.json" --outdir "$TMP/pf2"
expect_exit 0 "citation-integrity: offline self-test (pass)" python3 "$ESF/cross_verify_citations.py" --self-test
declare_ "citation-integrity (fail)" "a real finding needs a live resolver; the offline self-test covers the logic"
expect_exit 0 "numeric-provenance: traceable (pass)" python3 "$ESF/numbers_provenance.py" --draft "$TMP/d_ok.md" --artifacts "$TMP/art.json"
expect_exit 2 "numeric-provenance: untraceable (fail)" python3 "$ESF/numbers_provenance.py" --draft "$TMP/d_bad.md" --artifacts "$TMP/art.json"
expect_exit 0 "cross-artifact-integrity: self-test (pass)" python3 "$ESF/check_review_integrity.py" --selftest
expect_exit 2 "cross-artifact-integrity: prose in an ID column (fail)" python3 "$ESF/check_review_integrity.py" --root "$TMP/rev"
expect_exit 0 "ledger-completeness: matching ledger (pass)" python3 "$ESF/check_ledger_completeness.py" --root "$TMP/lc2"
expect_exit 2 "ledger-completeness: short ledger (fail)" python3 "$ESF/check_ledger_completeness.py" --root "$TMP/lc"
expect_exit 0 "review-completeness: complete review (pass)" python3 "$ESF/check_completeness.py" --root "$TMP/comp"
printf '{"identified_databases":100,"duplicates_removed":0,"removed_other":5,"screened":95,"excluded_ta":93,"sought":2,"not_retrieved":0,"assessed":2,"included_studies":2}\n' > "$TMP/comp/prisma_counts.json"
expect_exit 2 "review-completeness: unwaived gap (fail)" python3 "$ESF/check_completeness.py" --root "$TMP/comp"
expect_exit 0 "screening-disclosure: honest negation (pass)" python3 "$ESF/check_screening_disclosure.py" --root "$TMP/sd_ok"
expect_exit 2 "screening-disclosure: false human claim (fail)" python3 "$ESF/check_screening_disclosure.py" --root "$TMP/sd"
expect_exit 0 "gate-coverage: both paths present (pass)" python3 "$ESF/check_selftest_coverage.py" --selftest "$TMP/cov_ok.sh"
expect_exit 2 "gate-coverage: one-sided gate (fail)" python3 "$ESF/check_selftest_coverage.py" --selftest "$TMP/cov_bad.sh"
expect_exit 0 "appraisal-honesty: self-test (pass)" python3 "$ESF/check_appraisal.py" --selftest
expect_exit 2 "appraisal-honesty: placeholder ledger (fail)" python3 "$ESF/check_appraisal.py" --root "$TMP/ra"
expect_exit 0 "screening-calibration: agreement (pass)" python3 "$ESF/gate2a_calibration.py" --pilot "$TMP/pilot_ok.csv" --out "$TMP/g2a_ok.json" --min-n 0
expect_exit 2 "screening-calibration: chance agreement (fail)" python3 "$ESF/gate2a_calibration.py" --pilot "$TMP/pilot_bad.csv" --out "$TMP/g2a_bad.json" --min-n 0
expect_exit 0 "certainty: valid SoF (pass)" python3 "$ESF/sof_table.py" --input "$TMP/sof.csv" --outdir "$TMP/sof_ok"
expect_exit 2 "certainty: no certainty/baseline (fail)" python3 "$ESF/sof_table.py" --input "$TMP/sofbad.csv" --outdir "$TMP/sof_bad"
expect_exit 0 "defect-regressions: suite passes (pass)" python3 "$ESF/regression_suite.py"
declare_ "defect-regressions (fail)" "its fail path is a re-introduced defect; the suite has no negative CLI mode"
declare_ "acceptance-live (pass)" "it runs the whole toolchain on a live query; not run offline"
declare_ "acceptance-live (fail)" "the adversarial cases need the live query; not run offline"

echo "== 5. Manuscript gate: the defined attribution claim =="
# Three review roots. They differ in one artifact each, so the fixture proves both
# directions: every condition holds, and one missing gate or one unresolved citation.
mg_ok="$TMP/mg_ok"; mg_nogate="$TMP/mg_nogate"; mg_unres="$TMP/mg_unres"
for d in "$mg_ok" "$mg_nogate" "$mg_unres"; do
  mkdir -p "$d/ledgers"
  printf 'source_id,doi,pmid,title,year,inclusion_status,verification_status\n' > "$d/sources.csv"
  i=1; while [ $i -le 8 ]; do
    printf 'S%03d,10.1/x%d,1,Study %d,2024,included,verified\n' "$i" "$i" "$i" >> "$d/sources.csv"
    i=$((i+1))
  done
  printf 'source,platform,query,date_run,hits\npubmed,NCBI,x,2026-09-20,42\nclinicaltrials,CTgov,y,2026-09-20,3\n' > "$d/search_log.csv"
  printf 'source_id\nS001\nS002\nS003\n' > "$d/ledgers/sources_included.csv"
  printf '{"included_studies":3,"not_retrieved":0}\n' > "$d/prisma_counts.json"
  printf '{"states":{"attributed":6,"synthesis":0,"unverifiable":0,"unattributed":0,"conflict":0,"no_citation_needed":2}}\n' > "$d/coverage.json"
done
printf '{"checked":8,"unresolved":[],"no_identifier":[],"retracted":[],"input_gaps":[],"status":"pass","gate":"PASS"}\n' > "$mg_ok/GATE_REPORT.json"
printf '{"checked":8,"unresolved":["10.9999/not-real"],"no_identifier":[],"retracted":[],"input_gaps":[],"status":"fail","gate":"FAIL"}\n' > "$mg_unres/GATE_REPORT.json"

expect_exit 0 "manuscript-attribution: every condition holds (issued)" python3 "$MG" --root "$mg_ok" --json "$TMP/mg_ok.json"
expect_exit 1 "manuscript-attribution: the citation gate is absent (withheld)" python3 "$MG" --root "$mg_nogate" --json "$TMP/mg_nogate.json"
expect_exit 1 "manuscript-attribution: one unresolved citation (withheld)" python3 "$MG" --root "$mg_unres" --json "$TMP/mg_unres.json"

cat > "$TMP/mg_check.py" <<'PY'
import json, pathlib, sys
ok, nogate, unres = (json.load(open(p)) for p in sys.argv[1:4])
outdir = pathlib.Path(sys.argv[4])
problems = []
def need(cond, msg):
    if not cond:
        problems.append(msg)
scope = ("Scope: 8 source(s) checked; 3 supplied document(s) read; 0 document(s) could not be "
         "read; structure is not verified above the measured separation.")
need(ok["attribution"]["issuable"] is True, "the clean fixture was not issued")
need(scope in ok["attribution"]["statement"], "the issued statement is missing a scope fact")
need(ok["facts"]["sources_checked"] == 8, "sources_checked did not come from GATE_REPORT.json")
need(ok["facts"]["corpus_docs"] == 3, "corpus_docs did not come from the full-text ledger")
need(ok["facts"]["corpus_unreadable"] == 0, "corpus_unreadable is wrong for a read corpus")
need(ok["fact_sources"]["citations_unresolved"].startswith("GATE_REPORT.json"),
     "citations_unresolved is not attributed to the citation gate")
need(ok["fact_sources"]["corpus_docs"].startswith("ledgers/sources_included.csv"),
     "corpus_docs is not attributed to the full-text ledger")
need(nogate["attribution"]["issuable"] is False, "the missing-gate fixture was issued")
need("NOT ISSUED" in nogate["attribution"]["statement"], "the missing gate did not refuse")
need(any("citation resolution was not verified" in b for b in nogate["attribution"]["blockers"]),
     "the missing gate is not named as the blocker")
need("Scope:" in nogate["block"], "the withheld block dropped the scope anchor")
need(unres["attribution"]["issuable"] is False, "the unresolved-citation fixture was issued")
need(any("do not resolve" in b for b in unres["attribution"]["blockers"]),
     "the unresolved citation is not named as the blocker")
need(unres["facts"]["citations_unresolved"] == 1, "the unresolved count was not read")
for name, payload in (("mg_ok", ok), ("mg_nogate", nogate)):
    (outdir / (name + ".md")).write_text(payload["block"] + "\n", encoding="utf-8")
print("; ".join(problems))
sys.exit(1 if problems else 0)
PY
if python3 "$TMP/mg_check.py" "$TMP/mg_ok.json" "$TMP/mg_nogate.json" "$TMP/mg_unres.json" "$TMP" >"$TMP/mg_check.log" 2>&1; then
  ok "manuscript-attribution: issued and withheld lines carry the scope, the blocker, and each fact's source"
else
  no "manuscript-attribution fixture check: $(cat "$TMP/mg_check.log")"
fi
# The term may appear only inside the definition. Both directions are pinned.
expect_exit 0 "claim_guard accepts the issued block" python3 "$TOOLS/claim_guard.py" "$TMP/mg_ok.md"
expect_exit 0 "claim_guard accepts the withheld block" python3 "$TOOLS/claim_guard.py" "$TMP/mg_nogate.md"
printf 'The draft is plagiarism-free.\n' > "$TMP/mg_bare.md"
expect_exit 1 "claim_guard refuses the bare term (fail)" python3 "$TOOLS/claim_guard.py" "$TMP/mg_bare.md"
expect_exit 0 "the shared definition self-test" python3 "$TOOLS/attribution.py" --self-test

echo
printf 'RESULT: %d passed, %d failed, %d declared-only\n' "$pass" "$fail" "$declared"
[ "$fail" -eq 0 ] && exit 0 || exit 1
