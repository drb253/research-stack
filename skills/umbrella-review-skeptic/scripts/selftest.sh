#!/usr/bin/env bash
# selftest.sh -- the QA suite for umbrella-review-skeptic. Runs the skill's gate and
# asserts BOTH paths: a defensible pool must pass, an overlapping pool must be flagged,
# and an unreadable primary-study list must stay an INPUT GAP that emits no verdict.
#
# Usage: bash selftest.sh
#   0 = every check passed
#   1 = at least one check failed
#   4 = an input gap: a required file or interpreter is absent, so nothing was checked
set -u

# Location-independent: resolve the skills root from this script's own path.
SKILLS="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HERE="$SKILLS/umbrella-review-skeptic"
CHECK="$HERE/scripts/check_pooling_defensibility.py"
SKILLMD="$HERE/SKILL.md"

if ! command -v python3 >/dev/null 2>&1; then
  echo "INPUT GAP: python3 is not on PATH (not a pass)" >&2
  exit 4
fi
if [ ! -f "$HERE/scripts/check_pooling_defensibility.py" ]; then
  echo "INPUT GAP: $CHECK is missing (not a pass)" >&2
  exit 4
fi
if [ ! -f "$SKILLMD" ]; then
  echo "INPUT GAP: $SKILLMD is missing (not a pass)" >&2
  exit 4
fi

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok() { printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
no() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }
# expect_exit <expected-code> <name> <cmd...>
expect_exit() { local want="$1" name="$2"; shift 2; "$@" >/dev/null 2>&1; local got=$?
  if [ "$got" -eq "$want" ]; then ok "$name (exit $got)"; else no "$name (want $want, got $got)"; fi; }

# ---- fixtures -------------------------------------------------------------
cat > "$TMP/effects_ok.csv" <<'CSV'
review_id,effect_metric,outcome_family,effect_estimate
R1,LnRR,yield,0.10
R2,LnRR,yield,0.12
CSV
cat > "$TMP/effects_mixed.csv" <<'CSV'
review_id,effect_metric,outcome_family,effect_estimate
R1,LnRR,yield,0.10
R2,SMD,yield,0.30
CSV
# Two reviews of five studies that share one study: 1/5 = 20%, below the 30% rule.
cat > "$TMP/overlap_defensible.csv" <<'CSV'
primary_study_id,R1,R2
S1,1,0
S2,1,0
S3,1,0
S4,1,0
S5,1,1
S6,0,1
S7,0,1
S8,0,1
S9,0,1
CSV
# The same reviews with two of three studies shared: 2/2 = 100%, above the rule.
cat > "$TMP/overlap_overlapping.csv" <<'CSV'
primary_study_id,R1,R2
S1,1,1
S2,1,1
S3,1,0
CSV
# R2 has no mark at all: its primary-study list could not be read.
cat > "$TMP/overlap_gap.csv" <<'CSV'
primary_study_id,R1,R2
S1,1,
S2,1,
CSV

echo "== 1. Gate self-test (exit vocabulary + gap channel) =="
expect_exit 0 "check_pooling_defensibility --self-test" python3 "$HERE/scripts/check_pooling_defensibility.py" --self-test

echo "== 2. A defensible pool passes (exit 0, verdict defensible_pooling) =="
python3 "$HERE/scripts/check_pooling_defensibility.py" --effects "$TMP/effects_ok.csv" --overlap "$TMP/overlap_defensible.csv" \
  --pool --out "$TMP/defensible.json" >/dev/null 2>&1
if [ $? -eq 0 ]; then ok "defensible pool passes (exit 0)"; else no "defensible pool did not pass"; fi
if python3 - "$TMP/defensible.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
sys.exit(0 if r["status"] == "pass" and r["verdict"] == "defensible_pooling" else 1)
PY
then ok "defensible report carries status=pass and verdict=defensible_pooling"
else no "defensible report carried the wrong status or verdict"; fi

echo "== 3. An overlapping pool is FLAGGED (exit 2) =="
expect_exit 2 "overlapping primary studies are flagged (exit 2)" python3 "$HERE/scripts/check_pooling_defensibility.py" --effects "$TMP/effects_ok.csv" --overlap "$TMP/overlap_overlapping.csv" \
  --pool --out "$TMP/overlapping.json"
if python3 - "$TMP/overlapping.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
sys.exit(0 if (r["verdict"] == "indefensible_pooling" and r["findings"]
               and r["findings"][0]["rule"] == "overlap"
               and r["overlap_pairs"][0]["share"] > r["threshold"]) else 1)
PY
then ok "the finding names the overlap rule and a share above the 30% threshold"
else no "the overlap was not reported as an above-threshold finding"; fi

echo "== 4. Narrative synthesis stays available over an overlapping pool =="
python3 "$HERE/scripts/check_pooling_defensibility.py" --effects "$TMP/effects_ok.csv" --overlap "$TMP/overlap_overlapping.csv" \
  --out "$TMP/narrative.json" >/dev/null 2>&1
if [ $? -eq 0 ] && python3 - "$TMP/narrative.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
sys.exit(0 if r["verdict"] == "narrative_synthesis" and not r["findings"] else 1)
PY
then ok "narrative synthesis is the verdict when no pool is requested"
else no "narrative synthesis was not reported"; fi

echo "== 5. An unreadable primary-study list is an INPUT GAP, never a result =="
python3 "$HERE/scripts/check_pooling_defensibility.py" --effects "$TMP/effects_ok.csv" --overlap "$TMP/overlap_gap.csv" \
  --pool --out "$TMP/gap.json" >/dev/null 2>&1
case $? in
  3) ok "unreadable list -> input gap (exit 3)" ;;
  *) no "unreadable list did not give exit 3 (an input gap, NOT a result)" ;;
esac
if python3 - "$TMP/gap.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
bad = []
if r["status"] != "insufficient_evidence":
    bad.append("status=%s" % r["status"])
if r["verdict"] is not None:
    bad.append("verdict=%s" % r["verdict"])
if r["findings"]:
    bad.append("findings=%d" % len(r["findings"]))
if len(r["input_gaps"]) != 1:
    bad.append("input_gaps=%d" % len(r["input_gaps"]))
elif not r["input_gaps"][0].get("action"):
    bad.append("gap entry carries no action")
if bad:
    print("; ".join(bad))
sys.exit(1 if bad else 0)
PY
then ok "the gap reports no verdict and stays out of findings[]"
else no "the input gap leaked into the result channel"; fi
expect_exit 0 "--allow-insufficient is the logged opt-out (exit 0)" python3 "$HERE/scripts/check_pooling_defensibility.py" --effects "$TMP/effects_ok.csv" --overlap "$TMP/overlap_gap.csv" \
  --pool --allow-insufficient --out "$TMP/gap_waived.json"
if python3 - "$TMP/gap.json" "$TMP/gap_waived.json" <<'PY'
import json, sys
gap, waived = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
bad = []
for key in ("status", "verdict", "findings"):
    if gap[key] != waived[key]:
        bad.append("--allow-insufficient changed %s" % key)
if not waived["input_gaps"]:
    bad.append("the waived run dropped the gap")
if bad:
    print("; ".join(bad))
sys.exit(1 if bad else 0)
PY
then ok "the opt-out keeps the status, the gap, and the empty verdict"
else no "the opt-out rewrote the report"; fi

echo "== 6. Dependence handling and metric compatibility =="
expect_exit 0 "a declared dependence plan makes an overlapping pool defensible" python3 "$HERE/scripts/check_pooling_defensibility.py" --effects "$TMP/effects_ok.csv" --overlap "$TMP/overlap_overlapping.csv" \
  --pool --dependence-handled --out "$TMP/dependence.json"
expect_exit 2 "mixed review-level metrics refuse the pool (exit 2)" python3 "$HERE/scripts/check_pooling_defensibility.py" --effects "$TMP/effects_mixed.csv" --overlap "$TMP/overlap_defensible.csv" \
  --pool --out "$TMP/mixed.json"
expect_exit 1 "no --effects/--overlap is a usage error (exit 1)" python3 "$HERE/scripts/check_pooling_defensibility.py"

echo "== 7. Input conditions (exit 4), never a finding =="
expect_exit 4 "a missing overlap matrix is insufficient_input (exit 4)" python3 "$HERE/scripts/check_pooling_defensibility.py" --effects "$TMP/effects_ok.csv" --overlap "$TMP/absent.csv" --pool
printf 'primary_study_id\nS1\n' > "$TMP/overlap_single_col.csv"
expect_exit 4 "a matrix with no review column is insufficient_input (exit 4)" python3 "$HERE/scripts/check_pooling_defensibility.py" --effects "$TMP/effects_ok.csv" --overlap "$TMP/overlap_single_col.csv" --pool

echo "== 8. The skill contract is still pinned in SKILL.md =="
for f in references/overlap-and-quality.md references/second-order-decision-rules.md \
         references/agricultural-diversification-second-order-meta.md; do
  if [ -f "$HERE/$f" ]; then ok "reference present: $f"; else no "missing reference: $f"; fi
done
for f in templates/overlap-matrix.md templates/review-level-effect-schema.csv \
         templates/second-order-temporal-tradeoff-audit.md; do
  if [ -f "$HERE/$f" ]; then ok "template present: $f"; else no "missing template: $f"; fi
done
# AMSTAR and ROBIS must be EXPANDED at least once, not only named: the naming was the
# documented defect this rewrite fixed.
if grep -q "AMSTAR)" "$SKILLMD" && grep -q "ROBIS)" "$SKILLMD"; then
  ok "AMSTAR 2 and ROBIS are expanded in SKILL.md"
else
  no "AMSTAR 2 or ROBIS is used in SKILL.md with no expansion"
fi
if grep -q "30%" "$SKILLMD"; then
  ok "the recorded 30% overlap rule is stated in SKILL.md"
else
  no "the 30% overlap rule is not stated in SKILL.md"
fi
if head -3 "$SKILLMD" | grep -q "^name: umbrella-review-skeptic$"; then
  ok "frontmatter name matches the directory"
else
  no "frontmatter name does not match the directory"
fi

echo
printf 'RESULT: %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ] && exit 0 || exit 1
