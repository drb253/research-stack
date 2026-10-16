#!/usr/bin/env bash
# selftest.sh -- the gate self-test for /openserp-search.
#
# Three things are pinned here:
#   1. every rubric id in eval.md appears in SKILL.md (the coverage table);
#   2. the skill's declared gate -- the wrapped-link unwrap tool -- has BOTH a
#      passing fixture and a failing fixture, and each produces its own exit code;
#   3. an unresolved wrapper is labelled, never presented as a real address.
#
# Exit codes: 0 every fixture passed; 1 a fixture failed; 4 input gap (never a pass).
#
# Usage: bash selftest.sh
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS="$(cd "$HERE/../.." && pwd)"
SKILL="$SKILLS/openserp-search/SKILL.md"
EVAL="$SKILLS/openserp-search/eval.md"
UNWRAP="$HERE/openserp_unwrap.py"
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
[ -f "$UNWRAP" ] || { echo "selftest: $UNWRAP missing (input gap, not a pass)" >&2; exit 4; }

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
echo "== 2. Declared gate: the wrapped-link unwrap tool =="
if grep -qE '<!--[[:space:]]*gates:' "$SKILL"; then ok "SKILL.md declares its gates"; else no "SKILL.md declares no gate"; fi
expect_exit 0 "unwrap: the offline self-test passes (pass path)" python3 "$UNWRAP" --self-test
expect_exit 1 "unwrap: an unreachable wrapper exits 1 (fail path)" python3 "$UNWRAP" --url "http://127.0.0.1:9/goto?url=dead"

# ------------------------------------------------------ 3. labelled failures ---
echo "== 3. An unresolved wrapper is labelled, never passed off as real =="
printf '%s' '{"results":[{"url":"http://127.0.0.1:9/goto?url=dead","domain":"google.com"}]}' > "$TMP/dead.json"
set +e
python3 "$UNWRAP" < "$TMP/dead.json" > "$TMP/dead.out" 2> "$TMP/dead.err"
dead_exit=$?
set -e
if [ "$dead_exit" -eq 1 ]; then ok "a dead wrapper exits 1"; else no "a dead wrapper exits $dead_exit (want 1)"; fi
if python3 -c "import json,sys; d=json.load(open('$TMP/dead.out')); r=d['results'][0]; sys.exit(0 if r.get('unwrapped') is False and 'goto?url=dead' in r.get('url','') else 1)"; then
  ok "the record keeps its original address and is marked unwrapped=false"
else
  no "the record did not keep its original address or the label"
fi

# ------------------------------------------------------------------- result ---
echo
printf 'RESULT: %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ] && exit 0 || exit 1
