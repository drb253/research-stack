#!/usr/bin/env bash
# selftest.sh -- regression harness for medical-narrative-review.
#
# Runs every bundled CLI against fixtures and asserts BOTH the PASS path and the
# FAIL path (a gate that cannot fail is not a gate). Offline, deterministic,
# standard library only. Exit 0 = all checks passed.
#
# Usage: bash selftest.sh
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # .../medical-narrative-review/scripts
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
WS="$TMP/ws"; mkdir -p "$WS"
pass=0; fail=0
ok()  { printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
no()  { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }
# expect_exit <want-code> <name> <cmd...>
expect_exit() { local want="$1" name="$2"; shift 2; "$@" >/dev/null 2>&1; local got=$?
  if [ "$got" -eq "$want" ]; then ok "$name (exit $got)"; else no "$name (want $want, got $got)"; fi; }

# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #
cat > "$WS/sources.csv" <<'CSV'
source_id,title,authors,container,year,volume,issue,pages,doi,pmid,pmcid,publication_type,peer_reviewed,study_design,population,intervention,comparator,n_participants,follow_up,key_outcomes,main_finding,effect_estimate,verification_status,verifier,verified_date,locator,retraction_status,inclusion_status,exclusion_reason,retrieval_status,theme,notes
S001,Effect of statins on cardiovascular events,Smith J and Doe A,New England Journal of Medicine,2020,382,5,100-110,10.1056/NEJMoa1234567,12345678,PMC1234567,randomised_trial,yes,RCT,Adults with hyperlipidaemia,Statin therapy,Placebo,1000,24 months,Major adverse cardiovascular events,Statin therapy reduced major adverse cardiovascular events,HR 0.80,verified,agent,2024-01-01,abstract,clear,included,,returned,Treatment,
CSV
# a ledger that is identical except the included source is marked retracted
sed 's/,clear,included,/,retracted,included,/' "$WS/sources.csv" > "$WS/sources_retracted.csv"

cat > "$WS/claims.csv" <<'CSV'
claim_id,section,claim_kind,direction,claim_summary,source_ids,verification_status,certainty,analysis_intent,notes
C001,Results,treatment_effect,supports,Statin therapy reduced major adverse cardiovascular events,S001,verified,high,confirmatory,
CSV
# a claim that points at a source id absent from the ledger
sed 's/,S001,verified/,S999,verified/' "$WS/claims.csv" > "$WS/claims_bad.csv"

cat > "$WS/draft.md" <<'MD'
# Statins in hyperlipidaemia

## Results

Statin therapy reduced major adverse cardiovascular events in adults with hyperlipidaemia. [claim:C001] [src:S001]
MD
sed 's/\[src:S001\]/[src:S999]/' "$WS/draft.md" > "$WS/draft_bad.md"

cat > "$WS/numbers_ok.md" <<'MD'
Among participants, 30/100 (30.0%) reached the primary endpoint, and the risk ratio was 0.80 (95% CI 0.70 to 0.92).
MD
sed 's#30/100 (30.0%)#30/100 (50.0%)#' "$WS/numbers_ok.md" > "$WS/numbers_bad.md"

cat > "$WS/manuscript_ok.md" <<'MD'
# Statins in hyperlipidaemia

## Abstract
Statin therapy was associated with fewer cardiovascular events in adults with hyperlipidaemia.

## Introduction
Cardiovascular disease affects many adults worldwide.

## Methods
We reviewed the available evidence on statin therapy.

## Results
Statin therapy was associated with a lower risk of major adverse cardiovascular events.

## Discussion
The findings are consistent with earlier trial evidence.

## Conclusion
Statin therapy may reduce cardiovascular events in this population.

## References
1. Smith J, Doe A. Statins. N Engl J Med. 2020;382:100-110.

## Declarations
Funding: none. Conflicts of interest: none. Author contributions: all authors.
Data availability: not applicable. AI use: none.
MD
{ echo "[[TODO write the background]]"; echo; cat "$WS/manuscript_ok.md"; } > "$WS/manuscript_bad.md"

cat > "$WS/prisma_ok.json" <<'JSON'
{
  "review_type": "narrative",
  "identification": {"records_from_databases": 100, "records_from_registers": 0, "records_from_other_methods": 0, "duplicates_removed": 10},
  "screening": {"records_screened": 90, "records_excluded": 70},
  "retrieval": {"reports_sought": 20, "reports_not_retrieved": 2},
  "eligibility": {"reports_assessed": 18, "reports_excluded": 8, "exclusion_reasons": {"wrong population": 5, "wrong outcome": 3}},
  "included": {"studies_included": 10, "sources_verified": 10}
}
JSON
sed 's/"studies_included": 10/"studies_included": 11/' "$WS/prisma_ok.json" > "$WS/prisma_bad.json"
# the full workspace carries a one-row ledger, so its counts file must agree with it
cat > "$WS/prisma_full.json" <<'JSON'
{
  "review_type": "narrative",
  "identification": {"records_from_databases": 100, "records_from_registers": 0, "records_from_other_methods": 0, "duplicates_removed": 10},
  "screening": {"records_screened": 90, "records_excluded": 70},
  "retrieval": {"reports_sought": 20, "reports_not_retrieved": 2},
  "eligibility": {"reports_assessed": 18, "reports_excluded": 17, "exclusion_reasons": {"wrong population": 10, "wrong outcome": 7}},
  "included": {"studies_included": 1, "sources_verified": 1}
}
JSON

mkdir -p "$WS/records"
cat > "$WS/records/record_ok.json" <<'JSON'
[{"doi": "10.1056/NEJMoa1234567", "title": "Effect of statins on cardiovascular events", "authors": ["John Smith"], "container_title": "New England Journal of Medicine", "year": 2020, "volume": "382", "page": "100-110", "abstract": "Statin therapy reduced major adverse cardiovascular events (HR 0.80)."}]
JSON
cat > "$WS/records/record_wrong.json" <<'JSON'
[{"doi": "10.1056/NEJMoa1234567", "title": "Epidemiological aspects and financial impact of lumpy skin disease in Ethiopia", "authors": ["G. Gari"], "container_title": "Preventive Veterinary Medicine", "year": 2011, "volume": "102", "page": "274-283", "abstract": "Lumpy skin disease causes economic loss."}]
JSON


# --------------------------------------------------------------------------- #
# Checks                                                                      #
# --------------------------------------------------------------------------- #
echo "== 1. init_review (scaffold) =="
expect_exit 0 "scaffolds a workspace" python3 "$HERE/init_review.py" \
  --out-dir "$TMP/init" --document-id demo --title "Demo review"
# 4, not 1: refusing to touch an existing directory is a precondition on the inputs, not a
# finding about a review, so it must not share the finding's exit code. This fixture asserted
# 1 while every refusal shared one code.
expect_exit 4 "refuses to overwrite an existing dir" python3 "$HERE/init_review.py" \
  --out-dir "$TMP/init" --document-id demo --title "Demo review"

echo "== 2. validate_sources (verification gate) =="
expect_exit 0 "verified+included ledger passes" python3 "$HERE/validate_sources.py" \
  "$WS/sources.csv" --strict --require-included
expect_exit 1 "retracted-but-included FAILS" python3 "$HERE/validate_sources.py" \
  "$WS/sources_retracted.csv" --strict --require-included
expect_exit 1 "empty ledger FAILS --require-included" python3 "$HERE/validate_sources.py" \
  "$TMP/init/sources.csv" --strict --require-included
# A ledger that cannot be parsed is not a finding about the review: it means nothing could be
# checked. It carries its own status (insufficient_input) and its own exit code (4), and it
# lands in input_gaps[] rather than issues[]. Before this it was an INVALID_INPUT error at
# exit 1 -- the same channel, shape and code as a finding.
printf 'not,a,ledger\n1,2,3\n' > "$WS/sources_malformed.csv"
cat > "$TMP/check_input.py" <<'PY'
import json, os, subprocess, sys
here, bad = sys.argv[1], sys.argv[2]
p = subprocess.run([sys.executable, os.path.join(here, "validate_sources.py"), bad],
                   capture_output=True, text=True)
problems = []
try:
    d = json.loads(p.stdout)
except Exception as exc:
    problems.append("no JSON report: %s" % exc)
    d = {}
if p.returncode != 4:
    problems.append("exit=%d, want 4" % p.returncode)
if d.get("status") != "insufficient_input":
    problems.append("status=%r" % d.get("status"))
if d.get("issues"):
    problems.append("the input condition leaked into issues[]: %s"
                    % [i.get("code") for i in d["issues"]])
gaps = d.get("input_gaps") or []
if len(gaps) != 1:
    problems.append("input_gaps=%d" % len(gaps))
elif not gaps[0].get("action"):
    problems.append("the worklist row carries no action")
print("; ".join(problems))
sys.exit(1 if problems else 0)
PY
if python3 "$TMP/check_input.py" "$HERE" "$WS/sources_malformed.csv" >"$TMP/inputcheck.log" 2>&1; then
  ok "an unreadable ledger is insufficient_input (exit 4), never an issue[] finding"
else
  no "the unreadable-ledger path is wrong ($(cat "$TMP/inputcheck.log"))"
fi

echo "== 3. audit_citations (claim/source join) =="
expect_exit 0 "draft markers join cleanly" python3 "$HERE/audit_citations.py" \
  "$WS/draft.md" "$WS/claims.csv" "$WS/sources.csv" --strict
expect_exit 1 "draft citing unknown source FAILS" python3 "$HERE/audit_citations.py" \
  "$WS/draft_bad.md" "$WS/claims.csv" "$WS/sources.csv" --strict
expect_exit 1 "claim referencing unknown source FAILS" python3 "$HERE/audit_citations.py" \
  "$WS/draft.md" "$WS/claims_bad.csv" "$WS/sources.csv" --strict

echo "== 3b. the retrieval invariant: a source nobody read cannot support a claim =="
# The exact bypass this guards: retrieval_status=empty (the text was never obtained) with
# every extraction field written as the sanctioned `not_reported`, verification=verified and
# inclusion=included. All three gates used to report pass, because `retrieval_status` was
# enum-checked and then read by no decision path.
python3 - "$WS/sources.csv" "$WS/sources_unread.csv" <<'PY'
import csv, sys
src, dst = sys.argv[1], sys.argv[2]
rows = list(csv.DictReader(open(src, newline="", encoding="utf-8")))
extraction = ["study_design", "population", "intervention", "comparator", "n_participants",
              "follow_up", "key_outcomes", "main_finding", "effect_estimate", "theme"]
with open(dst, "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
    w.writeheader()
    for row in rows:
        row["retrieval_status"] = "empty"
        for field in extraction:
            row[field] = "not_reported"
        w.writerow(row)
PY
# user_supplied is the other value under which a source may be cited
sed 's/,returned,Treatment,/,user_supplied,Treatment,/' "$WS/sources.csv" > "$WS/sources_supplied.csv"

expect_exit 0 "a retrieved source is citable" python3 "$HERE/validate_sources.py" \
  "$WS/sources.csv" --strict --require-included
expect_exit 0 "a user-supplied source is citable" python3 "$HERE/validate_sources.py" \
  "$WS/sources_supplied.csv" --strict --require-included
expect_exit 3 "an unread citable source is an INPUT GAP (exit 3), not a finding" \
  python3 "$HERE/validate_sources.py" "$WS/sources_unread.csv" --strict --require-included
expect_exit 3 "a claim citing an unread source is an INPUT GAP (exit 3)" \
  python3 "$HERE/audit_citations.py" "$WS/draft.md" "$WS/claims.csv" \
  "$WS/sources_unread.csv" --strict
expect_exit 0 "--allow-insufficient is the logged opt-out (sources)" \
  python3 "$HERE/validate_sources.py" "$WS/sources_unread.csv" --strict --require-included \
  --allow-insufficient
expect_exit 0 "--allow-insufficient is the logged opt-out (citations)" \
  python3 "$HERE/audit_citations.py" "$WS/draft.md" "$WS/claims.csv" \
  "$WS/sources_unread.csv" --strict --allow-insufficient
cat > "$TMP/check_gap.py" <<'PY'
import json, subprocess, sys, os
here, ws = sys.argv[1], sys.argv[2]
def run(args):
    p = subprocess.run([sys.executable] + args, capture_output=True, text=True)
    return p.returncode, json.loads(p.stdout)
problems = []
rc, red = run([os.path.join(here, "validate_sources.py"), os.path.join(ws, "sources_unread.csv"),
               "--strict", "--require-included"])
if rc != 3:
    problems.append("validate rc=%d" % rc)
if red["status"] != "insufficient_evidence":
    problems.append("validate status=%s" % red["status"])
if len(red.get("input_gaps", [])) != 1:
    problems.append("validate input_gaps=%d" % len(red.get("input_gaps", [])))
if not red["input_gaps"][0].get("action"):
    problems.append("gap carries no action")
# the gap must NOT also be reported as a finding about the ledger
if any(i.get("code") == "SOURCE_NOT_RETRIEVED" for i in red["issues"]):
    problems.append("the gap leaked into issues[] as a finding")
rc, blue = run([os.path.join(here, "audit_citations.py"), os.path.join(ws, "draft.md"),
                os.path.join(ws, "claims.csv"), os.path.join(ws, "sources_unread.csv"), "--strict"])
if rc != 3 or blue["status"] != "insufficient_evidence":
    problems.append("audit rc=%d status=%s" % (rc, blue["status"]))
if len(blue.get("input_gaps", [])) != 1:
    problems.append("audit input_gaps=%d" % len(blue.get("input_gaps", [])))
if blue["issues"]:
    problems.append("audit reported %d finding(s) about the artefact" % len(blue["issues"]))
print("; ".join(problems))
sys.exit(1 if problems else 0)
PY
if python3 "$TMP/check_gap.py" "$HERE" "$WS" >"$TMP/gapcheck.log" 2>&1; then
  ok "the gap stays in its own channel: no issue, no finding, action present"
else
  no "the retrieval gap leaked ($(cat "$TMP/gapcheck.log"))"
fi

echo "== 4. check_numbers (arithmetic) =="
expect_exit 0 "consistent fraction/CI passes" python3 "$HERE/check_numbers.py" "$WS/numbers_ok.md"
expect_exit 1 "wrong percentage FAILS" python3 "$HERE/check_numbers.py" "$WS/numbers_bad.md"

echo "== 5. lint_manuscript (--sections) =="
expect_exit 0 "complete manuscript passes" python3 "$HERE/lint_manuscript.py" \
  "$WS/manuscript_ok.md" --sections
expect_exit 1 "placeholder manuscript FAILS" python3 "$HERE/lint_manuscript.py" \
  "$WS/manuscript_bad.md" --sections

echo "== 6. make_prisma_flow (--check-only) =="
expect_exit 0 "reconciled counts pass" python3 "$HERE/make_prisma_flow.py" "$WS/prisma_ok.json" --check-only
expect_exit 1 "unreconciled counts FAIL" python3 "$HERE/make_prisma_flow.py" "$WS/prisma_bad.json" --check-only

echo "== 7. gate (end-to-end verdict) =="
expect_exit 1 "gate FAILS an empty scaffold" python3 "$HERE/gate.py" --dir "$TMP/init" --skip-final

# --------------------------------------------------------------------------- #
# Full-chain fixtures: a complete, valid workspace (gate must PASS)           #
# --------------------------------------------------------------------------- #
FULL="$TMP/full"; mkdir -p "$FULL"
cp "$WS/sources.csv" "$WS/claims.csv" "$FULL/"
cp "$WS/prisma_full.json" "$FULL/prisma_counts.json"
printf 'search_id,database,platform,query_string,filters,date_run,hits_retrieved,availability,records_screened,records_included,notes\nSR1,PubMed,NCBI,statins AND cardiovascular,year>=2015,2024-01-01,100,available,90,10,\n' > "$FULL/search_log.csv"
printf '# Unresolved items\n\n_none yet_\n' > "$FULL/UNRESOLVED.md"
cat > "$FULL/draft.md" <<'MD'
# Statins in hyperlipidaemia

## Abstract
Statin therapy was associated with fewer cardiovascular events in adults with hyperlipidaemia. [claim:C001] [src:S001]

## Introduction
Cardiovascular disease affects many adults worldwide. [claim:C001] [src:S001]

## Methods
We reviewed the available evidence on statin therapy. [claim:C001] [src:S001]

## Results
Statin therapy was associated with a lower risk of major adverse cardiovascular events. [claim:C001] [src:S001]

## Discussion
The findings are consistent with earlier trial evidence. [claim:C001] [src:S001]

## Conclusion
Statin therapy may reduce cardiovascular events in this population. [claim:C001] [src:S001]

## References

## Declarations
Funding: none. Conflicts of interest: none. Author contributions: all authors.
Data availability: not applicable. AI use: none.
MD

echo "== 8. build_reference_list (draft -> final) =="
expect_exit 0 "builds final/manuscript_cited.md" python3 "$HERE/build_reference_list.py" \
  "$FULL/draft.md" "$FULL/sources.csv" "$FULL/claims.csv" --style vancouver --out-dir "$FULL/final"
expect_exit 0 "final numbered-citation audit passes" python3 "$HERE/audit_citations.py" \
  "$FULL/final/manuscript_cited.md" "$FULL/claims.csv" "$FULL/sources.csv" --final \
  --references "$FULL/final/references.md" --strict

echo "== 9. export_document (DOCX / PDF / HTML) =="
expect_exit 0 "exports three formats" python3 "$HERE/export_document.py" \
  "$FULL/final/manuscript_cited.md" --workspace "$FULL" --out-dir "$FULL/final" \
  --references "$FULL/final/references.md" --title "Statins in hyperlipidaemia"

echo "== 9b. house_style_build (designed HTML edition) =="
expect_exit 0 "builds the house-style HTML and manifest" python3 "$HERE/house_style_build.py" \
  --workspace "$FULL" --out final/house_style.html
if python3 - "$FULL/final/house_style.html" <<'PY'
import sys
doc = open(sys.argv[1], encoding="utf-8").read()
bad = []
for needle in ('class="cover"', "Contents", "References", "<section"):
    if needle not in doc:
        bad.append("missing " + needle)
if doc.count("<section") < 4:
    bad.append("too few sections")
if "%s" in doc:
    bad.append("unformatted placeholder")
print("; ".join(bad))
sys.exit(1 if bad else 0)
PY
then ok "house-style HTML has a cover, sections, contents and references"
else no "house-style HTML is structurally incomplete"; fi

echo "== 9b. crosscheck_counts (ledger vs PRISMA vs references) =="
expect_exit 0 "PRISMA totals agree with the ledger" python3 "$HERE/crosscheck_counts.py" \
  --workspace "$FULL" --strict
BADCC="$TMP/full_badcounts"; mkdir -p "$BADCC"; cp -R "$FULL/." "$BADCC/"
python3 - "$BADCC/prisma_counts.json" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["included"]["studies_included"] = 9
json.dump(d, open(p, "w"))
PY
expect_exit 1 "a PRISMA total that disagrees with the ledger FAILS --strict" python3 \
  "$HERE/crosscheck_counts.py" --workspace "$BADCC" --strict

echo "== 9c. verify_records (ledger vs saved retrieval records) =="
expect_exit 0 "a matching record passes" python3 "$HERE/verify_records.py" \
  --sources "$WS/sources.csv" --records "$WS/records/record_ok.json" --check-numbers
expect_exit 1 "a DOI that resolves to another paper FAILS" python3 "$HERE/verify_records.py" \
  --sources "$WS/sources.csv" --records "$WS/records/record_wrong.json"

echo "== 10. gate PASSES a complete workspace =="
expect_exit 0 "gate passes the complete review" python3 "$HERE/gate.py" --dir "$FULL" --require-exports

echo "== 11. gate REFUSES to call a review submission-ready over an unread source =="
# The end-to-end assertion for the retrieval invariant: same complete workspace, one
# retrieval_status changed to `empty`. Before the fix this exited 0 with
# submission_ready=true.
UNREAD="$TMP/unread"; mkdir -p "$UNREAD"
cp -R "$FULL/." "$UNREAD/"
sed 's/,returned,Treatment,/,empty,Treatment,/' "$FULL/sources.csv" > "$UNREAD/sources.csv"
python3 - "$UNREAD/GATE_REPORT.json" <<'PY'
import os, sys
p = sys.argv[1]
if os.path.exists(p):
    os.remove(p)
PY
expect_exit 3 "gate exits 3 on an unread citable source" python3 "$HERE/gate.py" --dir "$UNREAD"
if python3 - "$UNREAD/GATE_REPORT.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
bad = []
if d["status"] != "insufficient_evidence":
    bad.append("status=%s" % d["status"])
if d["summary"]["submission_ready"]:
    bad.append("submission_ready=true")
if not d.get("input_gaps"):
    bad.append("no input_gaps recorded")
if not any(c.get("status") == "insufficient_evidence" for c in d["checks"]):
    bad.append("no sub-check reported the gap")
print("; ".join(bad))
sys.exit(1 if bad else 0)
PY
then ok "GATE_REPORT.json records the gap and refuses submission_ready"
else no "the gate still called an unread source submission-ready"; fi
expect_exit 0 "--allow-insufficient on the gate is the logged opt-out" \
  python3 "$HERE/gate.py" --dir "$UNREAD" --allow-insufficient

echo
printf 'RESULT: %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ] && echo "MEDICAL-NARRATIVE-REVIEW SELFTEST PASSED" || echo "SELFTEST FAILED -- see above"
exit $((fail>0))
