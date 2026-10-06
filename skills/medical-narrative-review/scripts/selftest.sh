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

# --------------------------------------------------------------------------- #
# Checks                                                                      #
# --------------------------------------------------------------------------- #
echo "== 1. init_review (scaffold) =="
expect_exit 0 "scaffolds a workspace" python3 "$HERE/init_review.py" \
  --out-dir "$TMP/init" --document-id demo --title "Demo review"
expect_exit 1 "refuses to overwrite an existing dir" python3 "$HERE/init_review.py" \
  --out-dir "$TMP/init" --document-id demo --title "Demo review"

echo "== 2. validate_sources (verification gate) =="
expect_exit 0 "verified+included ledger passes" python3 "$HERE/validate_sources.py" \
  "$WS/sources.csv" --strict --require-included
expect_exit 1 "retracted-but-included FAILS" python3 "$HERE/validate_sources.py" \
  "$WS/sources_retracted.csv" --strict --require-included
expect_exit 1 "empty ledger FAILS --require-included" python3 "$HERE/validate_sources.py" \
  "$TMP/init/sources.csv" --strict --require-included

echo "== 3. audit_citations (claim/source join) =="
expect_exit 0 "draft markers join cleanly" python3 "$HERE/audit_citations.py" \
  "$WS/draft.md" "$WS/claims.csv" "$WS/sources.csv" --strict
expect_exit 1 "draft citing unknown source FAILS" python3 "$HERE/audit_citations.py" \
  "$WS/draft_bad.md" "$WS/claims.csv" "$WS/sources.csv" --strict
expect_exit 1 "claim referencing unknown source FAILS" python3 "$HERE/audit_citations.py" \
  "$WS/draft.md" "$WS/claims_bad.csv" "$WS/sources.csv" --strict

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
cp "$WS/prisma_ok.json" "$FULL/prisma_counts.json"
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

echo "== 10. gate PASSES a complete workspace =="
expect_exit 0 "gate passes the complete review" python3 "$HERE/gate.py" --dir "$FULL" --require-exports

echo
printf 'RESULT: %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ] && echo "MEDICAL-NARRATIVE-REVIEW SELFTEST PASSED" || echo "SELFTEST FAILED -- see above"
exit $((fail>0))
