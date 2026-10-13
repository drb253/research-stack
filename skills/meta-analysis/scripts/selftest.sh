#!/usr/bin/env bash
# selftest.sh -- the routing-contract and gate-fixture self-test for /meta-analysis.
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
SKILL="$SKILLS/meta-analysis/SKILL.md"
ESF="$SKILLS/evidence-synthesis-forge/scripts"
MAF="$SKILLS/meta-analysis-forge/scripts"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

pass=0; fail=0; declared=0
ok()      { printf '  PASS %s\n' "$1"; pass=$((pass+1)); }
no()      { printf '  FAIL %s\n' "$1"; fail=$((fail+1)); }
declare_(){ printf '  DECL %s -- %s\n' "$1" "$2"; declared=$((declared+1)); }
# expect_exit <expected-code> <name> <cmd...>
expect_exit() { local want="$1" name="$2"; shift 2; "$@" >/dev/null 2>&1; local got=$?
  if [ "$got" -eq "$want" ]; then ok "$name (exit $got)"; else no "$name (want $want, got $got)"; fi; }

# ---------------------------------------------------------------- input gap ---
[ -f "$SKILL" ] || { echo "selftest: $SKILL missing (input gap, not a pass)" >&2; exit 4; }
grep -qE '^ROUTE ' "$SKILL" || { echo "selftest: no ROUTE block in $SKILL (input gap)" >&2; exit 4; }
grep -qE '^FALLBACK ' "$SKILL" || { echo "selftest: no FALLBACK line in $SKILL (input gap)" >&2; exit 4; }
grep -qE '^GATE ' "$SKILL" || { echo "selftest: no GATE registry in $SKILL (input gap)" >&2; exit 4; }
[ -d "$MAF" ] || { echo "selftest: $MAF missing (input gap, not a pass)" >&2; exit 4; }
[ -d "$ESF" ] || { echo "selftest: $ESF missing (input gap, not a pass)" >&2; exit 4; }

# ------------------------------------------------------------------- router ---
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
meta-analysis-forge	harmonize effect sizes across the studies
meta-analysis-forge	use random-effects for this synthesis
meta-analysis-forge	measure heterogeneity and a prediction interval
meta-analysis-forge	run a meta-regression on dose
meta-analysis-forge	check publication bias with a funnel plot
meta-analysis-forge	draw a forest plot for the outcome
self	should we pool these studies at all
sysreview	run a systematic review protocol for the question
sysreview	record risk of bias and certainty for each study
umbrella-review-skeptic	summarise the field as a review of reviews
TSV

echo "== 1. Routing contract: every request reaches its target =="
while IFS=$'\t' read -r want request; do
  [ -n "$want" ] || continue
  got="$(python3 "$TMP/router.py" "$SKILL" "$request")"
  if [ "$got" = "$want" ]; then ok "route '$request' -> $want"; else no "route '$request' -> $got (want $want)"; fi
done < "$TMP/routes.tsv"

grep -E '^ROUTE ' "$SKILL" | sed -E 's/.*->[[:space:]]*//; s/[[:space:]]+$//' | sort -u > "$TMP/targets_declared.txt"
cut -f1 "$TMP/routes.tsv" | sort -u > "$TMP/targets_fixtured.txt"
missing="$(comm -23 "$TMP/targets_declared.txt" "$TMP/targets_fixtured.txt" | tr '\n' ' ')"
if [ -z "$missing" ]; then ok "every declared route target has a fixture"; else no "targets with no fixture: $missing"; fi

echo "== 2. An unknown request must not silently route =="
got="$(python3 "$TMP/router.py" "$SKILL" "write a haiku about the ocean")"
if [ "$got" = "FALLBACK" ]; then ok "unknown request falls back instead of routing"; else no "unknown request silently routed to $got"; fi
fb="$(grep -E '^FALLBACK ' "$SKILL")"
case "$fb" in
  *"exit 4"*"never guess"*) ok "the fallback declares exit 4 and refuses to guess" ;;
  *) no "the fallback line does not declare exit 4 and a refusal to guess" ;;
esac
cp "$SKILL" "$TMP/mutated.md"
printf '\nROUTE the -> meta-analysis-forge\n' >> "$TMP/mutated.md"
got="$(python3 "$TMP/router.py" "$TMP/mutated.md" "write a haiku about the ocean")"
if [ "$got" != "FALLBACK" ]; then ok "an over-broad keyword is detected (mutation routed to $got)"; else no "mutation not detected: the silent-route check cannot fail"; fi

echo "== 3. Every declared gate has a pass fixture and a fail fixture =="
grep -E '^GATE ' "$SKILL" | sed -E 's/^GATE[[:space:]]+([a-z0-9-]+).*/\1/' | sort -u > "$TMP/gates.txt"
# Two explicit lists, kept in step with the fixtures in section 4. A gate added to the
# skill registry without a fixture on either path is caught here.
PASS_FIXTURED=" coding-sheet engine accuracy report numeric-provenance summary-of-findings search-reporting toolchain "
FAIL_FIXTURED=" coding-sheet engine accuracy report numeric-provenance summary-of-findings search-reporting toolchain "
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
# coding sheet
printf 'study_id,effect_id,effect_metric,estimate,se\nS1,E1,MD,0.50,0.10\nS2,E2,MD,0.60,0.12\n' > "$TMP/cs_ok.csv"
printf 'study_id,effect_id,effect_metric,estimate,se\nS1,E1,MD,0.50,0.10\nS2,E2,MD,,0.12\n' > "$TMP/cs_blank.csv"
# engine
printf 'study_id,effect_id,effect_metric,estimate,se\nS1,E1,MD,0.50,0.10\nS2,E2,MD,0.50,0.10\n' > "$TMP/k2.csv"
printf 'study_id,effect_id,effect_metric,estimate,se\nS1,E1,RR,0.1,0.2\nS2,E2,OR,0.3,0.2\n' > "$TMP/mixed.csv"
# report
printf 'study_id,effect_id,effect_metric,estimate,se\nS1,E1,MD,0.10,0.05\nS2,E2,MD,0.90,0.05\nS3,E3,MD,0.30,0.05\n' > "$TMP/spread.csv"
printf '\x00\x01\x02 junk \x00' > "$TMP/junk.csv"
# numeric provenance
printf '{"pooled":0.49,"ci_lb":0.34,"ci_ub":0.70}\n' > "$TMP/art.json"
printf 'The pooled RR was 0.49 (0.34 to 0.70).\n' > "$TMP/d_ok.md"
printf 'The pooled RR was 0.49 but also 0.77.\n' > "$TMP/d_bad.md"
# summary of findings
printf 'outcome,n_studies,n_participants,effect_measure,relative_effect,ci_lb,ci_ub,baseline_risk,certainty,comments\nMortality,8,4820,RR,0.86,0.74,0.99,0.15,Moderate,x\n' > "$TMP/sof.csv"
printf 'outcome,n_studies,n_participants,effect_measure,relative_effect,ci_lb,ci_ub,baseline_risk,certainty,comments\nX,3,100,RR,0.8,0.7,0.9,,,\n' > "$TMP/sofbad.csv"
# search reporting
printf 'source,platform,query,date_run,hits,limits\npubmed,NCBI,x,2026-09-20,412,en\n' > "$TMP/sl_ok.csv"
printf 'source,query,date_run,hits\nscopus,x,,\n' > "$TMP/sl_bad.csv"

expect_exit 0 "coding-sheet: valid sheet (pass)" python3 "$MAF/validate_coding_sheet.py" --input "$TMP/cs_ok.csv"
expect_exit 3 "coding-sheet: blank effect size (fail)" python3 "$MAF/validate_coding_sheet.py" --input "$TMP/cs_blank.csv"
expect_exit 0 "engine: homogeneous pair (pass)" Rscript "$MAF/cochrane_meta.R" --input "$TMP/k2.csv" --outdir "$TMP/eng_ok"
expect_exit 1 "engine: mixed metrics refuse to pool (fail)" Rscript "$MAF/cochrane_meta.R" --input "$TMP/mixed.csv" --outdir "$TMP/eng_bad"
expect_exit 0 "accuracy: golden tests (pass)" Rscript "$MAF/golden_tests.R"
declare_ "accuracy (fail)" "the golden tests have no negative CLI mode; a broken engine copy is the fail path"
expect_exit 0 "report: spread sheet (pass)" Rscript "$MAF/run_meta_analysis.R" --input "$TMP/spread.csv" --outdir "$TMP/rep_ok"
expect_exit 4 "report: unparseable sheet (fail)" Rscript "$MAF/run_meta_analysis.R" --input "$TMP/junk.csv" --outdir "$TMP/rep_bad"
expect_exit 0 "numeric-provenance: traceable (pass)" python3 "$ESF/numbers_provenance.py" --draft "$TMP/d_ok.md" --artifacts "$TMP/art.json"
expect_exit 2 "numeric-provenance: untraceable (fail)" python3 "$ESF/numbers_provenance.py" --draft "$TMP/d_bad.md" --artifacts "$TMP/art.json"
expect_exit 0 "summary-of-findings: valid SoF (pass)" python3 "$ESF/sof_table.py" --input "$TMP/sof.csv" --outdir "$TMP/sof_ok"
expect_exit 2 "summary-of-findings: no certainty/baseline (fail)" python3 "$ESF/sof_table.py" --input "$TMP/sofbad.csv" --outdir "$TMP/sof_bad"
expect_exit 0 "search-reporting: complete log (pass)" python3 "$ESF/prisma_s_appendix.py" --search-log "$TMP/sl_ok.csv" --outdir "$TMP/ps1"
expect_exit 2 "search-reporting: no date/hits (fail)" python3 "$ESF/prisma_s_appendix.py" --search-log "$TMP/sl_bad.csv" --outdir "$TMP/ps2"
expect_exit 0 "toolchain: doctor.sh passes (pass)" bash "$ESF/doctor.sh"
declare_ "toolchain (fail)" "a missing dependency is environment-specific and is not simulated"

echo
printf 'RESULT: %d passed, %d failed, %d declared-only\n' "$pass" "$fail" "$declared"
[ "$fail" -eq 0 ] && exit 0 || exit 1
