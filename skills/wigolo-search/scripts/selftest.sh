#!/usr/bin/env bash
# selftest.sh -- the gate self-test for /wigolo-search.
#
# Three things are pinned here:
#   1. every rubric id in eval.md appears in SKILL.md (the coverage table);
#   2. the skill's declared gate -- the claim checker -- passes on the live file
#      and fails on a mutated copy, so both paths are exercised;
#   3. the claim checker's own self-test passes.
#
# Exit codes: 0 every fixture passed; 1 a fixture failed; 4 input gap (never a pass).
#
# Usage: bash selftest.sh
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS="$(cd "$HERE/../.." && pwd)"
SKILL="$SKILLS/wigolo-search/SKILL.md"
EVAL="$SKILLS/wigolo-search/eval.md"
CLAIMS="$HERE/check_skill_claims.py"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

pass=0; fail=0
ok()   { printf '  PASS %s\n' "$1"; pass=$((pass+1)); }
no()   { printf '  FAIL %s\n' "$1"; fail=$((fail+1)); }
# expect_exit <expected-code> <name> <cmd...>
expect_exit() { local want="$1" name="$2"; shift 2; "$@" >/dev/null 2>&1; local got=$?
  if [ "$got" -eq "$want" ]; then ok "$name (exit $got)"; else no "$name (want $want, got $got)"; fi }

# ---------------------------------------------------------------- input gap ---
[ -f "$SKILL" ]  || { echo "selftest: $SKILL missing (input gap, not a pass)" >&2; exit 4; }
[ -f "$EVAL" ]   || { echo "selftest: $EVAL missing (input gap, not a pass)" >&2; exit 4; }
[ -f "$CLAIMS" ] || { echo "selftest: $CLAIMS missing (input gap, not a pass)" >&2; exit 4; }

# ------------------------------------------------------- 1. rubric coverage ---
echo "== 1. Rubric coverage: every eval.md item appears in SKILL.md =="
grep -oE '^#{2,4} +[A-Z]{1,3}[0-9]+[a-z]?\.' "$EVAL" | grep -oE '[A-Z]{1,3}[0-9]+[a-z]?' | sort -u > "$TMP/ids.txt"
ids_n="$(wc -l < "$TMP/ids.txt" | tr -d ' ')"
if [ "$ids_n" -eq 0 ]; then echo "selftest: no rubric ids found in $EVAL (input gap)" >&2; exit 4; fi
while read -r id; do
  [ -n "$id" ] || continue
  if grep -qE "(^|[^A-Za-z0-9])${id}([^A-Za-z0-9]|$)" "$SKILL"; then ok "rubric $id is mapped in SKILL.md"; else no "rubric $id is missing from SKILL.md"; fi
done < "$TMP/ids.txt"

# ------------------------------------------------- 2. the declared gate paths ---
echo "== 2. Declared gate: the claim checker =="
if grep -qE '<!--[[:space:]]*gates:' "$SKILL"; then ok "SKILL.md declares its gates"; else no "SKILL.md declares no gate"; fi
expect_exit 0 "claims: the live SKILL.md satisfies every pinned claim (pass path)" python3 "$CLAIMS" --check "$SKILL"
expect_exit 0 "claims: the checker's own self-test passes" python3 "$CLAIMS" --self-test

# ------------------------------------------------ 3. the fail paths, twice over ---
echo "== 3. Mutated copies are rejected =="
grep -v '| `watch` |' "$SKILL" > "$TMP/no_tool.md"
expect_exit 1 "claims: a dropped tool name is rejected (fail path)" python3 "$CLAIMS" --check "$TMP/no_tool.md"
sed 's/not Google Scholar//g' "$SKILL" > "$TMP/no_denial.md"
expect_exit 1 "claims: a dropped Scholar denial is rejected (fail path)" python3 "$CLAIMS" --check "$TMP/no_denial.md"
expect_exit 4 "claims: a missing file is an input gap, never a pass" python3 "$CLAIMS" --check "$TMP/absent.md"

# ------------------------------------------------------------------- result ---
echo
printf 'RESULT: %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ] && exit 0 || exit 1
