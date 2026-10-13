#!/usr/bin/env bash
# selftest.sh -- the QA suite for environment-life-review-forge.
#
# Pins the contract of THIS skill: the gate scripts exist and behave, a PECO or
# PICO framework input is accepted, a missing input is an input gap and never a
# result, and every declared gate (G1-G8) has a pass fixture and a fail fixture.
#
# Usage: bash scripts/selftest.sh
# Exit codes: 0 everything passed | 1 at least one failure | 4 input gap
set -u
SKILL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATE="$SKILL/scripts/check_protocol.py"
COVER="$SKILL/scripts/check_gate_coverage.py"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok() { printf '  PASS %s\n' "$1"; pass=$((pass+1)); }
no() { printf '  FAIL %s\n' "$1"; fail=$((fail+1)); }
# expect_exit <expected-code> <name> <cmd...>
expect_exit() { local want="$1" name="$2"; shift 2; "$@" >/dev/null 2>&1; local got=$?
  if [ "$got" -eq "$want" ]; then ok "$name (exit $got)"; else no "$name (want $want, got $got)"; fi; }

if [ ! -f "$SKILL/SKILL.md" ] || [ ! -f "$GATE" ] || [ ! -f "$COVER" ]; then
  echo "INPUT GAP: SKILL.md, check_protocol.py or check_gate_coverage.py is missing" >&2
  echo "  skill dir: $SKILL" >&2
  exit 4
fi

echo "== 1. The gate scripts exist and their own self-tests pass =="
for f in "$GATE" "$COVER"; do
  if [ -s "$f" ]; then ok "gate script present: $(basename "$f")"; else no "gate script missing or empty: $f"; fi
done
expect_exit 0 "check_protocol.py --self-test" python3 "$GATE" --self-test

echo "== 2. A PECO or PICO framework input is accepted =="
cat > "$TMP/peco.json" <<'JSON'
{"framework": "PECO", "population": "dryland soil fauna", "exposure": "ant activity",
 "comparator": "fauna exclusion", "outcomes": "soil organic carbon stock",
 "units": "g C per kg soil", "designs": "field exclusion experiment",
 "heterogeneity": "climate zone; soil texture", "risk_of_bias": "SYRCLE-style checklist",
 "synthesis": "meta-analysis",
 "comparability": "one carbon-stock unit per study after a documented conversion"}
JSON
cat > "$TMP/pico.json" <<'JSON'
{"framework": "PICO", "population": "children under five", "intervention": "clean cookstove",
 "comparator": "open fire", "outcomes": "respiratory infection incidence",
 "units": "cases per 100 child-years", "designs": "randomized trial",
 "heterogeneity": "fuel type; household income", "risk_of_bias": "Cochrane RoB 2",
 "synthesis": "narrative"}
JSON
cat > "$TMP/peco.md" <<'MD'
| Element | Definition |
|---|---|
| Framework | PECO |
| Population | dryland soil fauna |
| Exposure | ant activity |
| Comparator | fauna exclusion |
| Outcomes | soil organic carbon stock |
| Units | g C per kg soil |
| Designs | field exclusion experiment |
| Heterogeneity | climate zone; soil texture |
| Risk of bias | SYRCLE-style checklist |
| Synthesis | meta-analysis |
| Comparability | one carbon-stock unit per study after a documented conversion |
MD
expect_exit 0 "PECO framework is accepted (JSON)" python3 "$GATE" --input "$TMP/peco.json"
expect_exit 0 "PICO framework is accepted (JSON)" python3 "$GATE" --input "$TMP/pico.json"
expect_exit 0 "PECO framework is accepted (markdown table)" python3 "$GATE" --input "$TMP/peco.md"
expect_exit 0 "PICO framework is accepted (markdown keys)" \
  python3 "$GATE" --input "$TMP/pico.json" --json "$TMP/report.json"
if [ -s "$TMP/report.json" ] && grep -q '"status": "pass"' "$TMP/report.json"; then
  ok "the JSON report records status=pass"
else
  no "the JSON report did not record status=pass"
fi

echo "== 3. A missing input is an INPUT GAP, never a result =="
: > "$TMP/empty.json"
printf '{ this is not json' > "$TMP/broken.json"
printf '[1, 2, 3]' > "$TMP/array.json"
expect_exit 4 "missing file -> input gap (exit 4)" \
  python3 "$GATE" --input "$TMP/does-not-exist.json"
expect_exit 4 "empty file -> input gap (exit 4)" python3 "$GATE" --input "$TMP/empty.json"
expect_exit 4 "invalid JSON -> input gap (exit 4)" python3 "$GATE" --input "$TMP/broken.json"
expect_exit 4 "JSON array root -> input gap (exit 4)" python3 "$GATE" --input "$TMP/array.json"
expect_exit 4 "a directory -> input gap (exit 4)" python3 "$GATE" --input "$TMP"
expect_exit 4 "no --input -> input gap (exit 4)" python3 "$GATE"
if python3 "$GATE" --input "$TMP/does-not-exist.json" 2>&1 | grep -q "INPUT GAP"; then
  ok "the gap is reported as INPUT GAP"
else
  no "the gap was not labelled as an input gap"
fi
if python3 "$GATE" --input "$TMP/does-not-exist.json" 2>&1 | grep -q "RESULT:"; then
  no "an input gap was rendered as a gate result"
else
  ok "an input gap is never rendered as a gate result"
fi
if python3 "$GATE" --input "$TMP/does-not-exist.json" >/dev/null 2>&1; then
  no "an input gap exited 0 (an input gap must never pass)"
else
  ok "an input gap never exits 0"
fi

echo "== 4. Every declared gate has a pass fixture and a fail fixture =="
python3 - "$TMP" <<'PY'
import json, sys
tmp = sys.argv[1]
valid = json.load(open(tmp + "/peco.json"))
json.dump(valid, open(tmp + "/valid.json", "w"))
drop = {"G1": "framework", "G2": "exposure", "G3": "units", "G4": "designs",
        "G5": "heterogeneity", "G6": "risk_of_bias", "G7": "synthesis", "G8": "comparability"}
for gid, key in drop.items():
    data = dict(valid)
    data.pop(key, None)
    json.dump(data, open("%s/fail_%s.json" % (tmp, gid), "w"))
PY
expect_exit 0 "G1 pass: framework named" python3 "$GATE" --input "$TMP/valid.json"
expect_exit 1 "G1 fail: framework missing" python3 "$GATE" --input "$TMP/fail_G1.json"
expect_exit 0 "G2 pass: exposure named" python3 "$GATE" --input "$TMP/valid.json"
expect_exit 1 "G2 fail: exposure missing" python3 "$GATE" --input "$TMP/fail_G2.json"
expect_exit 0 "G3 pass: outcome unit named" python3 "$GATE" --input "$TMP/valid.json"
expect_exit 1 "G3 fail: outcome unit missing" python3 "$GATE" --input "$TMP/fail_G3.json"
expect_exit 0 "G4 pass: eligible designs named" python3 "$GATE" --input "$TMP/valid.json"
expect_exit 1 "G4 fail: eligible designs missing" python3 "$GATE" --input "$TMP/fail_G4.json"
expect_exit 0 "G5 pass: heterogeneity named" python3 "$GATE" --input "$TMP/valid.json"
expect_exit 1 "G5 fail: heterogeneity missing" python3 "$GATE" --input "$TMP/fail_G5.json"
expect_exit 0 "G6 pass: appraisal tool named" python3 "$GATE" --input "$TMP/valid.json"
expect_exit 1 "G6 fail: appraisal tool missing" python3 "$GATE" --input "$TMP/fail_G6.json"
expect_exit 0 "G7 pass: synthesis mode named" python3 "$GATE" --input "$TMP/valid.json"
expect_exit 1 "G7 fail: synthesis mode missing" python3 "$GATE" --input "$TMP/fail_G7.json"
expect_exit 0 "G8 pass: pooling rationale named" python3 "$GATE" --input "$TMP/valid.json"
expect_exit 1 "G8 fail: pooling rationale missing" python3 "$GATE" --input "$TMP/fail_G8.json"
for g in G1 G2 G3 G4 G5 G6 G7 G8; do
  if python3 "$GATE" --input "$TMP/fail_$g.json" 2>/dev/null | grep -q "^FAIL $g "; then
    ok "$g fail fixture names the failing gate"
  else
    no "$g fail fixture did not name the failing gate"
  fi
done

echo "== 5. The files this skill references exist =="
python3 - "$SKILL" <<'PY'
import os, re, sys
skill = sys.argv[1]
text = open(os.path.join(skill, "SKILL.md"), encoding="utf-8").read()
names = sorted(set(re.findall(r"`([A-Za-z0-9_./-]+\.(?:md|csv))`", text)))
missing = [n for n in names if not os.path.exists(os.path.join(skill, n))]
print("referenced=%d missing=%d" % (len(names), len(missing)))
for n in missing:
    print("  MISSING %s" % n)
sys.exit(1 if missing else 0)
PY
if [ $? -eq 0 ]; then ok "every referenced reference/template file exists"; else no "a referenced file is missing"; fi

echo "== 6. The declared gates are pinned on both paths (meta-gate) =="
expect_exit 0 "gate coverage: every declared gate has both fixtures" \
  python3 "$COVER" --skill "$SKILL/SKILL.md" --selftest "$SKILL/scripts/selftest.sh"
sed '/G1 fail: framework missing/d' "$SKILL/scripts/selftest.sh" > "$TMP/one_sided.sh"
expect_exit 1 "gate coverage detects a removed fail fixture" \
  python3 "$COVER" --skill "$SKILL/SKILL.md" --selftest "$TMP/one_sided.sh"
expect_exit 4 "gate coverage: a missing selftest is an input gap (exit 4)" \
  python3 "$COVER" --skill "$SKILL/SKILL.md" --selftest "$TMP/no-such-selftest.sh"

echo
printf 'RESULT: %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ] && exit 0 || exit 1
