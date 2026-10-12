#!/usr/bin/env bash
# selftest.sh -- regression harness for citation-report.
#
# Runs the bundled CLIs against fixtures and asserts BOTH the passing path and the
# failing path, because a gate that cannot fail is not a gate. Offline, deterministic,
# standard library only. Exit 0 = all checks passed.
#
# Usage: bash selftest.sh
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"     # .../citation-report/scripts
SKILL="$(cd "$HERE/.." && pwd)"                          # .../citation-report
ASSETS="$SKILL/assets"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
WS="$TMP/ws"; mkdir -p "$WS"
OUT="$TMP/out"
pass=0; fail=0
ok()  { printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
no()  { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }

# expect_exit <want-code> <name> <cmd...>
expect_exit() { local want="$1" name="$2"; shift 2; "$@" >/dev/null 2>&1; local got=$?
  if [ "$got" -eq "$want" ]; then ok "$name (exit $got)"; else no "$name (want $want, got $got)"; fi; }

# json_field <file> <python-expression-on-d>
json_field() { python3 -c "
import json,sys
d=json.load(open(sys.argv[1]))
print(eval(sys.argv[2], {'d': d}))
" "$1" "$2" 2>/dev/null; }

# expect_json <name> <file> <expr> <want>
expect_json() { local name="$1" file="$2" expr="$3" want="$4"; local got
  got="$(json_field "$file" "$expr")"
  if [ "$got" = "$want" ]; then ok "$name ($got)"; else no "$name (want '$want', got '$got')"; fi; }

# expect_json_in <name> <file> <expr> <substring>
expect_json_in() { local name="$1" file="$2" expr="$3" want="$4"; local got
  got="$(json_field "$file" "$expr")"
  case "$got" in *"$want"*) ok "$name";; *) no "$name (want substring '$want', got '$got')";; esac; }

# expect_file <name> <path>   non-trivial artifact present
expect_file() { local name="$1" path="$2"
  if [ -s "$path" ]; then ok "$name ($(wc -c <"$path" | tr -d ' ') bytes)"; else no "$name (missing or empty: $path)"; fi; }

RUN=(python3 "$HERE/report.py")
GATE=(python3 "$HERE/report_gate.py")

echo "== 1. offline logic self-test =="
if python3 "$HERE/self_test.py" --self-test >/dev/null 2>&1; then
  ok "pure-function assertions pass"
else
  no "pure-function assertions pass"
  python3 "$HERE/self_test.py" --self-test
fi

echo
echo "== 2. sources mode =="
"${RUN[@]}" sources --document "$ASSETS/sample-manuscript.md" \
  --sources "$ASSETS/sample-sources.csv" --claims "$ASSETS/sample-claims.csv" \
  --offline --out-dir "$WS/src" >"$TMP/sources.json" 2>&1
expect_json "three sources linked" "$TMP/sources.json" "d['summary']['sources']" "3"
expect_json "one retracted source flagged" "$TMP/sources.json" "d['summary']['retraction']['retracted']" "1"
expect_json "one source carries no evidence" \
  "$TMP/sources.json" "d['summary']['evidence'].get('metadata_only', 0)" "1"
expect_json "claims ledger loaded" "$TMP/sources.json" "d['summary']['claims']" "7"

echo
echo "== 3. the shipped example produces exactly the six documented states =="
"${RUN[@]}" audit --document "$ASSETS/sample-manuscript.md" \
  --sources "$ASSETS/sample-sources.csv" --claims "$ASSETS/sample-claims.csv" \
  --offline >"$TMP/audit.json" 2>&1
audit_exit=$?
expect_json "attributed" "$TMP/audit.json" "d['coverage']['states']['attributed']" "1"
expect_json "synthesis" "$TMP/audit.json" "d['coverage']['states']['synthesis']" "2"
expect_json "unverifiable" "$TMP/audit.json" "d['coverage']['states']['unverifiable']" "2"
expect_json "unattributed" "$TMP/audit.json" "d['coverage']['states']['unattributed']" "1"
expect_json "conflict" "$TMP/audit.json" "d['coverage']['states']['conflict']" "2"
expect_json "no_citation_needed" "$TMP/audit.json" "d['coverage']['states']['no_citation_needed']" "1"
expect_json "coverage is 3/8" "$TMP/audit.json" "'%d/%d' % (d['coverage']['citation_coverage']['numerator'], d['coverage']['citation_coverage']['denominator'])" "3/8"
expect_json "numerator is a subset of the denominator" "$TMP/audit.json" \
  "d['coverage']['citation_coverage']['numerator'] <= d['coverage']['citation_coverage']['denominator']" "True"
expect_json "arithmetic balances" "$TMP/audit.json" \
  "sum(d['coverage']['states'].values()) == d['coverage']['sentences_total']" "True"
# The sample cites S003, whose ledger row holds no finding, so the evidence policy
# blocks. Exit 3 is the whole point of the sufficiency work: the run is input-bound and
# must not be mistakable for a clean or a failing result.
if [ "$audit_exit" -eq 3 ]; then ok "an unreadable cited source blocks the run (exit 3)"; else no "an unreadable cited source blocks the run (want 3, got $audit_exit)"; fi
expect_json "status names the input gap, not a verdict" "$TMP/audit.json" "d['status']" "insufficient_evidence"
expect_json "the evidence block reports the gap" "$TMP/audit.json" \
  "'%d of %d' % (d['evidence']['citing_sources_checkable'], d['evidence']['citing_sources'])" "2 of 3"

echo
echo "== 3b. --allow-insufficient keeps the status but restores the finding exit code =="
"${RUN[@]}" audit --document "$ASSETS/sample-manuscript.md" \
  --sources "$ASSETS/sample-sources.csv" --claims "$ASSETS/sample-claims.csv" \
  --offline --allow-insufficient >"$TMP/audit_override.json" 2>&1
override_exit=$?
expect_json "the status still names the input gap" "$TMP/audit_override.json" "d['status']" "insufficient_evidence"
if [ "$override_exit" -eq 1 ]; then ok "the exit code follows the findings again (exit 1)"; else no "the exit code follows the findings again (want 1, got $override_exit)"; fi
expect_json "the override is logged as a warning, not hidden" "$TMP/audit_override.json" \
  "[i['severity'] for i in d['issues'] if i['code'] == 'INSUFFICIENT_EVIDENCE']" "['warning']"

echo
echo "== 3c. the worklist is written and its gaps can be closed =="
"${RUN[@]}" report --document "$ASSETS/sample-manuscript.md" \
  --sources "$ASSETS/sample-sources.csv" --claims "$ASSETS/sample-claims.csv" \
  --offline --format html --out-dir "$WS/wl" >"$TMP/wl.json" 2>&1
expect_file "evidence_worklist.csv written" "$WS/wl/evidence_worklist.csv"
expect_json "one gap on the worklist" "$TMP/wl.json" "d['worklist_rows']" "1"
# The recorded file is the auditable one, so the intake basis must be in it and not only
# in the rendered banner: a reader of verdicts.json has to be able to see whether the
# tool was in a position to make these findings.
expect_json "the four preconditions are recorded in verdicts.json" "$WS/wl/verdicts.json" \
  "len(d['preconditions'])" "4"
expect_json "and carry their observed values" "$WS/wl/verdicts.json" \
  "all('observed' in r for r in d['preconditions'])" "True"
expect_exit 1 "an unclosed worklist fails the re-check" "${RUN[@]}" worklist \
  --document "$ASSETS/sample-manuscript.md" --sources "$ASSETS/sample-sources.csv" \
  --claims "$ASSETS/sample-claims.csv" --offline --worklist "$WS/wl/evidence_worklist.csv"
mkdir -p "$WS/pdfdir"
printf 'doi:10.9999/demo.review.2021\nFirst-line lipid-lowering strategies: a narrative overview. Roe B. Demo Review Quarterly 2021. RR 0.75 (95%% CI 0.60-0.94).\n' \
  >"$WS/pdfdir/10.9999_demo.review.2021.txt"
"${RUN[@]}" worklist --document "$ASSETS/sample-manuscript.md" \
  --sources "$ASSETS/sample-sources.csv" --claims "$ASSETS/sample-claims.csv" \
  --pdf-dir "$WS/pdfdir" --offline --worklist "$WS/wl/evidence_worklist.csv" >"$TMP/wl2.json" 2>&1
wl2_exit=$?
expect_json "the gap closes once the file is supplied" "$TMP/wl2.json" "d['summary']['closed']" "1"
expect_json "and nothing remains" "$TMP/wl2.json" "d['summary']['remaining']" "0"
if [ "$wl2_exit" -eq 0 ]; then ok "a closed worklist passes the re-check"; else no "a closed worklist passes the re-check (got $wl2_exit)"; fi
"${RUN[@]}" audit --document "$ASSETS/sample-manuscript.md" \
  --sources "$ASSETS/sample-sources.csv" --claims "$ASSETS/sample-claims.csv" \
  --pdf-dir "$WS/pdfdir" --offline >"$TMP/after.json" 2>&1
after_exit=$?
expect_json "the previously unverifiable sentence is now decided" "$TMP/after.json" \
  "d['coverage']['rules'].get('D05', 0)" "0"
if [ "$after_exit" -eq 1 ]; then ok "the run no longer blocks, and reports its real findings"; else no "the run no longer blocks (want 1, got $after_exit)"; fi

echo
echo "== 3d. --require-evidence accepts a share policy =="
"${RUN[@]}" audit --document "$ASSETS/sample-manuscript.md" \
  --sources "$ASSETS/sample-sources.csv" --claims "$ASSETS/sample-claims.csv" \
  --offline --require-evidence 0.6 >"$TMP/share.json" 2>&1
share_exit=$?
expect_json "a share policy does not name an input gap" "$TMP/share.json" "d['status']" "fail"
if [ "$share_exit" -eq 1 ]; then ok "2 of 3 checkable clears a 0.6 requirement"; else no "2 of 3 checkable clears a 0.6 requirement (got $share_exit)"; fi

echo
echo "== 4. JSON on stdout is the only thing on stdout =="
"${RUN[@]}" audit --document "$ASSETS/sample-manuscript.md" \
  --sources "$ASSETS/sample-sources.csv" --offline >"$TMP/pure.json" 2>/dev/null
if python3 -c "import json,sys; json.load(open('$TMP/pure.json'))" 2>/dev/null; then
  ok "audit stdout parses as JSON"
else
  no "audit stdout parses as JSON"
fi

echo
echo "== 5. a clean document passes, and all three artifacts are verified =="
cat >"$WS/clean.md" <<'MD'
# Statin therapy

## Results

Statin therapy reduced major adverse cardiovascular events in adults with hyperlipidaemia (HR 0.80) [src:S001].

Statin therapy was studied in a large randomised trial [src:S001].

This review summarises the available evidence.
MD
"${RUN[@]}" report --document "$WS/clean.md" --sources "$ASSETS/sample-sources.csv" \
  --offline --format pdf,docx,html,table --out-dir "$OUT" >"$TMP/clean.json" 2>&1
clean_exit=$?
expect_json "clean document gate status" "$TMP/clean.json" "d['status']" "pass"
expect_json "attributed sentence" "$TMP/clean.json" "d['summary']['states']['attributed']" "1"
if [ "$clean_exit" -eq 0 ]; then ok "clean document exits 0"; else no "clean document exits 0 (got $clean_exit)"; fi
expect_file "verdicts.json written" "$OUT/verdicts.json"
expect_file "coverage.json written" "$OUT/coverage.json"
expect_file "sources_report.csv written" "$OUT/sources_report.csv"
expect_file "findings.md written" "$OUT/findings.md"
expect_file "report.pdf written" "$OUT/report.pdf"
expect_file "report.docx written" "$OUT/report.docx"
expect_file "report.html written" "$OUT/report.html"
"${GATE[@]}" --dir "$OUT" --document "$WS/clean.md" >"$TMP/gate.json" 2>&1
gate_exit=$?
expect_json "every artifact re-verified" "$TMP/gate.json" "d['summary']['artifacts_verified']" "3"
if [ "$gate_exit" -eq 0 ]; then ok "gate passes a clean report"; else no "gate passes a clean report (got $gate_exit)"; fi
if grep -q "ARTIFACT_MISMATCH" "$TMP/gate.json"; then no "no artifact mismatches"; else ok "no artifact mismatches"; fi

echo
echo "== 6. fabricated citation is an error (D03) =="
cat >"$WS/fabricated.md" <<'MD'
# Fabrication

Statin therapy reduced major adverse cardiovascular events (HR 0.80) [src:S001].

An exploratory analysis suggested that statins reduce stroke risk [99].
MD
"${RUN[@]}" audit --document "$WS/fabricated.md" --sources "$ASSETS/sample-sources.csv" --offline >"$TMP/fab.json" 2>&1
expect_exit 1 "fabricated citation fails" "${RUN[@]}" audit --document "$WS/fabricated.md" --sources "$ASSETS/sample-sources.csv" --offline
expect_json "one conflict" "$TMP/fab.json" "d['coverage']['states']['conflict']" "1"
expect_json_in "rule D03 named" "$TMP/fab.json" "str(d['issues'])" "D03"

echo
echo "== 7. retracted source is an error (D04) =="
cat >"$WS/retracted.md" <<'MD'
# Retraction

Vitamin D supplementation reduced all-cause mortality (RR 0.70) [src:S002].
MD
"${RUN[@]}" audit --document "$WS/retracted.md" --sources "$ASSETS/sample-sources.csv" --offline >"$TMP/ret.json" 2>&1
expect_exit 1 "retracted source fails" "${RUN[@]}" audit --document "$WS/retracted.md" --sources "$ASSETS/sample-sources.csv" --offline
expect_json_in "rule D04 named" "$TMP/ret.json" "str(d['issues'])" "D04"

echo
echo "== 8. a contradicting value is an error (D08), a matching one is not =="
cat >"$WS/contradict.md" <<'MD'
# Contradiction

Statin therapy reduced major adverse cardiovascular events (HR 0.80) [src:S001].

Statin therapy reduced major adverse cardiovascular events (HR 0.50) [src:S001].
MD
"${RUN[@]}" audit --document "$WS/contradict.md" --sources "$ASSETS/sample-sources.csv" --offline >"$TMP/contra.json" 2>&1
expect_exit 1 "contradiction fails" "${RUN[@]}" audit --document "$WS/contradict.md" --sources "$ASSETS/sample-sources.csv" --offline
expect_json_in "rule D08 named" "$TMP/contra.json" "str(d['issues'])" "D08"
expect_json "the matching sentence is attributed, not conflicted" "$TMP/contra.json" "d['coverage']['states']['attributed']" "1"
expect_json "exactly one conflict" "$TMP/contra.json" "d['coverage']['states']['conflict']" "1"

echo
echo "== 9. an absent number is a warning, never a conflict (D07) =="
cat >"$WS/absent.md" <<'MD'
# Absent number

Statin therapy reduced mortality by 55% [src:S001].
MD
"${RUN[@]}" audit --document "$WS/absent.md" --sources "$ASSETS/sample-sources.csv" --offline >"$TMP/absent.json" 2>&1
absent_exit=$?
expect_json "no conflict for an absent number" "$TMP/absent.json" "d['coverage']['states']['conflict']" "0"
expect_json "recorded as unverifiable" "$TMP/absent.json" "d['coverage']['states']['unverifiable']" "1"
expect_json_in "rule D07 named" "$TMP/absent.json" "str(d['issues'])" "D07"
if [ "$absent_exit" -eq 0 ]; then ok "a warning does not block the gate"; else no "a warning does not block the gate (got $absent_exit)"; fi

echo
echo "== 10. no source list at all is unverifiable, not a false accusation (D06) =="
cat >"$WS/noapparatus.md" <<'MD'
# No apparatus

Statin therapy reduced major adverse cardiovascular events (HR 0.80) [12].
MD
"${RUN[@]}" audit --document "$WS/noapparatus.md" --offline >"$TMP/noapp.json" 2>&1
noapp_exit=$?
expect_json "resolves to nothing" "$TMP/noapp.json" "d['coverage']['states']['unverifiable']" "1"
expect_json "and is NOT called a conflict" "$TMP/noapp.json" "d['coverage']['states']['conflict']" "0"
expect_json "rule D06 named" "$TMP/noapp.json" "d['coverage']['rules'].get('D06', 0)" "1"
# Citations with nothing to check them against is an input gap, not a clean result.
# It used to exit 0, which is how a run that could check nothing looked reassuring.
expect_json "the missing source list is an input failure" "$TMP/noapp.json" "d['status']" "insufficient_input"
expect_json "named as a precondition, with the observed value" "$TMP/noapp.json" \
  "[r['code'] for r in d['preconditions'] if r['status'] == 'failed']" "['NO_SOURCE_LIST']"
if [ "$noapp_exit" -eq 4 ]; then ok "no apparatus blocks and names the reason (exit 4)"; else no "no apparatus blocks and names the reason (want 4, got $noapp_exit)"; fi

echo
echo "== 11. a bibliography is not graded as prose =="
cat >"$WS/withrefs.md" <<'MD'
# Review

Statin therapy reduced major adverse cardiovascular events in adults (HR 0.80) [src:S001].

Statin therapy was studied in a large randomised trial [src:S001].

## References

1. Smith J. Statin therapy and major adverse cardiovascular events. Demo Journal [Internet]. 2020 [cited 2026 Jan 5]. Available from: https://doi.org/10.1056/NEJMoa1234567
2. Doe A. Retracted trial of vitamin D. Demo Journal [Epub ahead of print]. 2019.
3. Roe B. First-line lipid-lowering strategies. Demo Review Quarterly. 2021;12(3):200-215.
MD
"${RUN[@]}" audit --document "$WS/withrefs.md" --sources "$ASSETS/sample-sources.csv" --offline >"$TMP/refs.json" 2>&1
expect_json "no conflict from reference-list apparatus" "$TMP/refs.json" "d['coverage']['states']['conflict']" "0"
expect_json "reference entries are not graded" "$TMP/refs.json" "d['coverage']['sentences_total']" "2"

echo
echo "== 11b. the same holds when the reader KEEPS the number in the text (DOCX) =="
# Markdown and plain text strip an ordered-list marker into DocParagraph.marker; DOCX,
# PDF and LaTeX leave it in the text. A shipped revision read capture group 2 of a
# one-group pattern, so grading any DOCX with a numbered bibliography crashed with
# IndexError. The unit guard lives in self_test.py; this is the end-to-end path.
python3 - "$WS/withrefs.docx" <<'PY'
import sys, zipfile
CT = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '</Types>'
)
RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    '</Relationships>'
)
def para(text, style=None):
    pr = '<w:pPr><w:pStyle w:val="%s"/></w:pPr>' % style if style else ''
    return '<w:p>%s<w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % (pr, text)
body = ''.join([
    para('Review', 'Heading1'),
    para('Statin therapy reduced major adverse cardiovascular events in adults (HR 0.80) [src:S001].'),
    para('References', 'Heading2'),
    para('1. Smith J. Statin therapy and major adverse cardiovascular events. Demo Journal [Internet]. 2020 [cited 2026 Jan 5].'),
    para('2. Doe A. Retracted trial of vitamin D. Demo Journal [Epub ahead of print]. 2019.'),
    para('3. Roe B. First-line lipid-lowering strategies. Demo Review Quarterly. 2021;12(3):200-215.'),
])
document = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:body>' + body + '</w:body></w:document>'
)
with zipfile.ZipFile(sys.argv[1], 'w') as archive:
    archive.writestr('[Content_Types].xml', CT)
    archive.writestr('_rels/.rels', RELS)
    archive.writestr('word/document.xml', document)
PY
"${RUN[@]}" audit --document "$WS/withrefs.docx" --sources "$ASSETS/sample-sources.csv" --offline >"$TMP/refsdocx.json" 2>&1
expect_exit 0 "a DOCX with a numbered bibliography is graded" "${RUN[@]}" audit --document "$WS/withrefs.docx" --sources "$ASSETS/sample-sources.csv" --offline
expect_json "DOCX reference entries are not graded" "$TMP/refsdocx.json" "d['coverage']['sentences_total']" "1"
expect_json "and produce no conflict" "$TMP/refsdocx.json" "d['coverage']['states']['conflict']" "0"
expect_json "the cited sentence is attributed" "$TMP/refsdocx.json" "d['coverage']['states']['attributed']" "1"

echo
echo "== 11c. a recorded verdicts.json is honoured, not silently re-classified =="
# The reproducibility path: a reviewer corrects a verdict by hand and re-renders without
# the classifier running. The flag used to be accepted and ignored, so a hand-correction
# looked applied while the artifact showed the machine's answer.
rm -rf "$TMP/rec" "$TMP/rec2" "$TMP/rec3"
"${RUN[@]}" report --document "$WS/contradict.md" --sources "$ASSETS/sample-sources.csv" \
  --offline --allow-insufficient --format json --out-dir "$TMP/rec" >/dev/null 2>&1
python3 "$HERE/_fixture_edit_verdicts.py" "$TMP/rec/verdicts.json" D12 unverifiable "$TMP/rec_edited.json"
"${RUN[@]}" report --document "$WS/contradict.md" --sources "$ASSETS/sample-sources.csv" \
  --offline --allow-insufficient --verdicts "$TMP/rec_edited.json" \
  --format json --out-dir "$TMP/rec2" >"$TMP/rec.json" 2>&1
expect_json "the recorded verdict is rendered" "$TMP/rec2/verdicts.json" \
  "[r['rule_id'] for r in d['verdicts'] if r['state'] == 'unverifiable']" "['D12']"
expect_json "and the classifier did not run" "$TMP/rec2/verdicts.json" \
  "any('was NOT run' in w for w in d['bundle']['warnings'])" "True"
python3 "$HERE/_fixture_edit_verdicts.py" "$TMP/rec/verdicts.json" D99 unverifiable "$TMP/rec_broken.json"
"${RUN[@]}" report --document "$WS/contradict.md" --sources "$ASSETS/sample-sources.csv" \
  --offline --allow-insufficient --verdicts "$TMP/rec_broken.json" --format json \
  --out-dir "$TMP/rec3" >"$TMP/recbad.json" 2>&1
expect_json_in "an unknown rule in the file is rejected" "$TMP/recbad.json" \
  "str(d['issues'])" "unknown rule"

echo
echo "== 12. the advisory channel is inert =="
rm -rf "$TMP/adv_off" "$TMP/adv_on"
"${RUN[@]}" report --document "$ASSETS/sample-manuscript.md" \
  --sources "$ASSETS/sample-sources.csv" --claims "$ASSETS/sample-claims.csv" \
  --offline --advisory off --format html --out-dir "$TMP/adv_off" >/dev/null 2>&1
"${RUN[@]}" report --document "$ASSETS/sample-manuscript.md" \
  --sources "$ASSETS/sample-sources.csv" --claims "$ASSETS/sample-claims.csv" \
  --offline --advisory "$ASSETS/sample-advisory.json" --format html --out-dir "$TMP/adv_on" >/dev/null 2>&1
if python3 - "$TMP/adv_off/verdicts.json" "$TMP/adv_on/verdicts.json" <<'PY'
import json, sys
off = json.load(open(sys.argv[1])); on = json.load(open(sys.argv[2]))
def strip(payload):
    return [{k: v for k, v in row.items() if k != "advisory"} for row in payload["verdicts"]]
assert strip(off) == strip(on), "advisory changed a deterministic verdict"
assert off["coverage"] == on["coverage"], "advisory changed the coverage arithmetic"
assert off["gate"] == on["gate"], "advisory changed the gate verdict"
assert any(row.get("advisory") for row in on["verdicts"]), "advisory grades were not applied at all"
print("inert")
PY
then ok "advisory cannot change a verdict, the arithmetic, or the gate"; else no "advisory is inert across all three"; fi
python3 - "$TMP/adv_off/report.html" "$TMP/adv_on/report.html" >"$TMP/paint.txt" 2>&1 <<'PY'
import re, sys
# The advisory channel IS rendered, in its own labelled block, so the two files
# differ. What must not change is the deterministic paint: the sequence of states
# applied to sentences. Only that sequence is compared.
pattern = re.compile(r'class="v v-([a-z_]+)"')
off = pattern.findall(open(sys.argv[1], encoding="utf-8").read())
on = pattern.findall(open(sys.argv[2], encoding="utf-8").read())
assert off, "no coloured spans found to compare"
assert off == on, "the advisory channel changed the deterministic colouring"
advisory_mark = "advisory, model-generated, not a gate input"
assert advisory_mark in open(sys.argv[2], encoding="utf-8").read(), "advisory was not rendered at all"
print("paint unchanged")
PY
if grep -q "paint unchanged" "$TMP/paint.txt"; then
  ok "advisory leaves the deterministic colouring identical"
else
  no "advisory leaves the deterministic colouring identical"
  cat "$TMP/paint.txt"
fi

echo
echo "== 13. tampered coverage.json is caught by the gate =="
rm -rf "$TMP/tamper"; cp -R "$OUT" "$TMP/tamper"
python3 - "$TMP/tamper/coverage.json" <<'PY'
import json, sys
path = sys.argv[1]
payload = json.load(open(path))
payload["states"]["attributed"] += 1
json.dump(payload, open(path, "w"), indent=2, sort_keys=True)
PY
expect_exit 1 "tampered coverage fails the gate" "${GATE[@]}" --dir "$TMP/tamper" --document "$WS/clean.md"
"${GATE[@]}" --dir "$TMP/tamper" --document "$WS/clean.md" >"$TMP/tamper.json" 2>&1
expect_json_in "a coverage disagreement is reported" "$TMP/tamper.json" "str(d['issues'])" "COVERAGE"

echo
echo "== 14. a verdict that contradicts the rule table is rejected =="
rm -rf "$TMP/badrule"; cp -R "$OUT" "$TMP/badrule"
python3 - "$TMP/badrule/verdicts.json" <<'PY'
import json, sys
path = sys.argv[1]
payload = json.load(open(path))
for row in payload["verdicts"]:
    if row["state"] == "attributed":
        row["state"] = "conflict"
        break
json.dump(payload, open(path, "w"), indent=2, sort_keys=True)
PY
expect_exit 1 "state/rule contradiction is rejected" "${GATE[@]}" --dir "$TMP/badrule" --document "$WS/clean.md"

echo
echo "== 15. a span that no longer locates its sentence is caught =="
rm -rf "$TMP/span"; cp -R "$OUT" "$TMP/span"
cat >"$WS/moved.md" <<'MD'
# Statin therapy

## Results

ACompletely different opening sentence that shifts every offset downstream.

Statin therapy reduced major adverse cardiovascular events in adults with hyperlipidaemia (HR 0.80) [src:S001].

Statin therapy was studied in a large randomised trial [src:S001].

This review summarises the available evidence.
MD
expect_exit 1 "a moved span fails the gate" "${GATE[@]}" --dir "$TMP/span" --document "$WS/moved.md"
"${GATE[@]}" --dir "$TMP/span" --document "$WS/moved.md" >"$TMP/span.json" 2>&1
expect_json_in "SPAN_NOT_RELOCATABLE reported" "$TMP/span.json" "str(d['issues'])" "SPAN_NOT_RELOCATABLE"

echo
echo "== 16. bad inputs fail loudly =="
printf 'not a document' >"$WS/thing.xyz"
expect_exit 1 "unsupported extension refused" "${RUN[@]}" audit --document "$WS/thing.xyz" --offline
"${RUN[@]}" audit --document "$WS/thing.xyz" --offline >"$TMP/ext.json" 2>&1
expect_json_in "with a legible reason" "$TMP/ext.json" "str(d['issue'] if 'issue' in d else d['issues'])" "unsupported document extension"

printf '%%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\ntrailer<</Root 1 0 R>>\n%%%%EOF\n' >"$WS/blank.pdf"
expect_exit 1 "a PDF with no text layer is refused" "${RUN[@]}" report --document "$WS/blank.pdf" --offline --out-dir "$TMP/blankout"

if python3 - "$TMP/adv_on/verdicts.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
for row in payload["verdicts"]:
    if row.get("advisory"):
        row["advisory"]["grade"] = "definitely_supported"
        break
json.dump(payload, open("/tmp/cr_badadvisory.json", "w"), indent=2)
PY
then
  if python3 -c "
import sys; sys.path.insert(0, '$HERE')
import _common, verdicts
try:
    verdicts.from_dict(__import__('json').load(open('/tmp/cr_badadvisory.json')))
    raise SystemExit(1)
except _common.InputError:
    raise SystemExit(0)
"; then ok "an advisory grade outside the vocabulary is rejected"; else no "an advisory grade outside the vocabulary is rejected"; fi
else
  no "could not build the bad-advisory fixture"
fi

echo
echo "== 16b. a superscript-citation DOCX is read rather than mis-accused =="
# Nature-style citations are superscript numbers with no brackets. Before superscript
# support, every checkable sentence in such a document became `unattributed` -- an
# accusation that the author failed to cite, thousands of times over.
python3 - "$WS/superscript.docx" <<'PY'
import sys, zipfile
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
 '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
 '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
 '<Default Extension="xml" ContentType="application/xml"/>'
 '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
def para(text, style=None):
    pr = '<w:pPr><w:pStyle w:val="%s"/></w:pPr>' % style if style else ''
    return '<w:p>%s<w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % (pr, text)
def cited(text, number, style=None):
    pr = '<w:pPr><w:pStyle w:val="%s"/></w:pPr>' % style if style else ''
    return ('<w:p>%s<w:r><w:t xml:space="preserve">%s</w:t></w:r>'
            '<w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr><w:t>%s</w:t></w:r>'
            '<w:r><w:t xml:space="preserve">.</w:t></w:r></w:p>') % (pr, text, number)
body = ''.join([
    para('Review', 'Heading1'),
    cited('Statin therapy reduced major adverse cardiovascular events (HR 0.80)', '1'),
    para('References', 'Heading2'),
    para('1. Smith J. Statin therapy and major adverse cardiovascular events. Demo Journal. 2020;1(1):1-9. doi:10.1056/NEJMoa1234567'),
    para('2. Doe A. Vitamin D and mortality. Demo Journal. 2019;2(2):2-9. doi:10.1136/bmj.demo2'),
])
document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="%s"><w:body>%s</w:body></w:document>') % (W, body)
with zipfile.ZipFile(sys.argv[1], 'w') as archive:
    archive.writestr('[Content_Types].xml', CT)
    archive.writestr('_rels/.rels', RELS)
    archive.writestr('word/document.xml', document)
PY
"${RUN[@]}" audit --document "$WS/superscript.docx" --sources "$ASSETS/sample-sources.csv" \
  --offline --allow-insufficient >"$TMP/super.json" 2>&1
expect_json "the superscript citation is bound" "$TMP/super.json" \
  "d['coverage']['states']['unattributed']" "0"
expect_json "so the sentence is never accused of missing a citation" "$TMP/super.json" \
  "d['coverage']['rules'].get('D02', 0)" "0"

echo
echo "== 16c. intake preconditions block a document the tool cannot read properly =="
python3 -c "open('$WS/blob.md','w').write('# Blob\n\n' + 'Statin therapy reduced events and the authors reported results ' * 40 + '\n')"
"${RUN[@]}" audit --document "$WS/blob.md" --offline >"$TMP/blob.json" 2>&1
blob_exit=$?
expect_json "an unsplittable document is an input failure" "$TMP/blob.json" "d['status']" "insufficient_input"
expect_json "named as SENTENCE_SPLIT_SUSPECT" "$TMP/blob.json" \
  "[r['code'] for r in d['preconditions'] if r['status'] == 'failed']" "['SENTENCE_SPLIT_SUSPECT']"
if [ "$blob_exit" -eq 4 ]; then ok "and it blocks (exit 4)"; else no "and it blocks (want 4, got $blob_exit)"; fi

# A reference list with no citation marker anywhere in the prose: the marker grammar
# does not match this document's style, so every checkable sentence would be accused.
python3 - "$WS/style.md" <<'PY'
import sys
lines = ["# Review", "", "Statin therapy reduced major adverse cardiovascular events in adults.", "", "## References", ""]
for index in range(1, 13):
    lines.append("%d. Author%d A. A study of statins in adults. Demo Journal. 2020;%d(%d):%d-%d."
                 % (index, index, index, index, index, index + 9))
open(sys.argv[1], "w").write("\n".join(lines) + "\n")
PY
"${RUN[@]}" audit --document "$WS/style.md" --offline >"$TMP/style.json" 2>&1
style_exit=$?
expect_json "an unrecognised citation style is an input failure" "$TMP/style.json" "d['status']" "insufficient_input"
expect_json "named as CITATION_STYLE_UNRECOGNISED" "$TMP/style.json" \
  "[r['code'] for r in d['preconditions'] if r['status'] == 'failed']" "['CITATION_STYLE_UNRECOGNISED']"
if [ "$style_exit" -eq 4 ]; then ok "and it blocks (exit 4)"; else no "and it blocks (want 4, got $style_exit)"; fi

# A short document must NOT trip the sentence-share heuristic: in a two-sentence
# document the longest is inevitably about half the text.
printf '# Tiny\n\nStatin therapy reduced events (HR 0.80).\n\nIt was well tolerated.\n' >"$WS/tiny.md"
"${RUN[@]}" audit --document "$WS/tiny.md" --offline --allow-insufficient >"$TMP/tiny.json" 2>&1
expect_json "a short document is not accused of a failed split" "$TMP/tiny.json" \
  "[r['code'] for r in d['preconditions'] if r['status'] == 'failed']" "[]"

echo
echo "== 17. the report never modifies the document it grades =="
cp "$ASSETS/sample-manuscript.md" "$WS/untouched.md"
before="$(shasum -a 256 <"$WS/untouched.md" | awk '{print $1}')"
"${RUN[@]}" report --document "$WS/untouched.md" --sources "$ASSETS/sample-sources.csv" \
  --offline --format html --out-dir "$TMP/nomod" >/dev/null 2>&1
after="$(shasum -a 256 <"$WS/untouched.md" | awk '{print $1}')"
if [ "$before" = "$after" ]; then ok "input document is byte-identical after a run"; else no "input document was modified"; fi

echo
printf 'RESULT: %d passed, %d failed\n' "$pass" "$fail"
if [ "$fail" -eq 0 ]; then
  printf '\033[32mCITATION-REPORT VERIFIED\033[0m\n'
  exit 0
fi
printf '\033[31mCITATION-REPORT FAILED\033[0m\n'
exit 1

echo
echo "== 18. live acquisition control (opt-in: CITATION_REPORT_LIVE=1) =="
# Network tests are opt-in, following the precedent of the live retraction benchmark,
# which is also excluded from CI. This uses one DOI that is known open access, and it
# asserts the two things that matter: the text is acquired and identity-verified, and
# the run refuses rather than inventing text when it cannot get any.
if [ "${CITATION_REPORT_LIVE:-0}" != "1" ]; then
  printf '  \033[33mSKIP\033[0m live acquisition (set CITATION_REPORT_LIVE=1 to run)\n'
else
  OPEN_DOI="10.1016/j.lanepe.2023.100773"
  LIVE_DOC="$WS/live.md"
  printf '# Live control\n\nStatin therapy reduced major adverse cardiovascular events (HR 0.80) [%s].\n' "$OPEN_DOI" >"$LIVE_DOC"
  printf 'source_id,title,authors,container,year,volume,issue,pages,doi,pmid,pmcid,publication_type,peer_reviewed,study_design,population,intervention,comparator,n_participants,follow_up,key_outcomes,main_finding,effect_estimate,verification_status,verifier,verified_date,locator,retraction_status,inclusion_status,exclusion_reason,retrieval_status,theme,notes\nS001,Post-traumatic stress disorder in health-care workers,Scott HR,The Lancet Psychiatry,2023,10,1,1-9,%s,,,cohort_study,yes,cross_sectional_study,health-care workers,not_applicable,not_applicable,not_reported,not_reported,not_reported,not_reported,PTSD prevalence in health-care workers,not_reported,verified,live,2026-01-01,Abstract,clear,included,,returned,treatment,\n' "$OPEN_DOI" >"$WS/live.csv"
  "${RUN[@]}" report --document "$LIVE_DOC" --sources "$WS/live.csv" \
    --acquire api --cache-dir "$WS/livecache" --allow-insufficient \
    --format json --out-dir "$WS/liveout" >"$TMP/live.json" 2>&1
  if python3 - "$WS/liveout/verdicts.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
sources = payload["bundle"]["sources"]
primary = [s for s in sources if s["evidence_strength"] == "primary"]
assert primary, "no source reached primary strength: acquisition did not run"
source = primary[0]
assert source["identity_check"] == "doi_matched", "identity was not confirmed: %s" % source["identity_check"]
assert source["evidence_origin"].startswith("europepmc"), source["evidence_origin"]
assert source["evidence_chars"] > 5000, source["evidence_chars"]
assert any(a["retrieval_status"] == "returned" for a in source["attempts"]), "no attempt recorded"
assert source["evidence_sections"], "no section ranges, so a tier-1 locator is impossible"
print("acquired %d chars, origin %s" % (source["evidence_chars"], source["evidence_origin"]))
PY
  then ok "open-access full text acquired and identity-verified"; else no "live acquisition control"; fi

  # A paywalled DOI must yield nothing, with the refusal recorded rather than a guess.
  PAYWALLED_DOI="10.1016/j.jvs.2022.10.056"
  printf '# Live paywall control\n\nStatin therapy reduced major adverse cardiovascular events (HR 0.80) [%s].\n' "$PAYWALLED_DOI" >"$WS/paywall.md"
  sed "s|$OPEN_DOI|$PAYWALLED_DOI|" "$WS/live.csv" >"$WS/paywall.csv"
  "${RUN[@]}" report --document "$WS/paywall.md" --sources "$WS/paywall.csv" \
    --acquire api --cache-dir "$WS/livecache" --allow-insufficient \
    --format json --out-dir "$WS/paywallout" >"$TMP/paywall.json" 2>&1
  if python3 - "$WS/paywallout/verdicts.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
for source in payload["bundle"]["sources"]:
    assert source["evidence_strength"] == "none", "a paywalled source gained evidence"
    assert source["evidence_chars"] == 0, "text appeared from nowhere"
    assert source["attempts"], "the refusal was not recorded"
    assert any(a["retrieval_status"] in ("unavailable", "error") for a in source["attempts"])
print("paywalled source stayed at strength none, with the attempt recorded")
PY
  then ok "a paywalled source yields nothing and says why"; else no "live paywall control"; fi
fi
