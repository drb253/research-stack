# eval.md — grade a review design package

Grade the package against the twelve rubric items below. Each item names the artifact it
reads, the gate that decides it, and the failure it catches. An item is PASS, FAIL, or
NOT APPLICABLE, and a NOT APPLICABLE item needs a reason.

Every gate named here is exercised on both paths in `scripts/selftest.sh` (78 checks), and
`scripts/check_selftest_coverage.py` asserts that mechanically. Run it after any edit to
the suite:

```bash
python3 scripts/check_selftest_coverage.py --selftest scripts/selftest.sh
```

---

## Hard errors

A package with a FAIL on E9, E10, or E11 must not ship until the defect is fixed.

### E1. Question and eligibility criteria are explicit

Read the protocol. The question frame (PICO, PECO, PICOS, SPIDER, or a custom frame) must
be named. The population, the exposure or intervention, the comparator, and the outcome
must each be stated. The eligible designs, the date limits, and the language limits must
be stated.

**Fails when:** the protocol says "relevant studies" with no design, no dates, and no
outcome list. A criterion a second reviewer cannot apply is not a criterion.

**Gate:** none. This item is a reading check.

### E2. Search completeness and reproducibility

Read the search log. Each row needs the source, the platform, the exact query, the run
date, and the hit count. A row without a date or a hit count is a defect, not a note.

**Gate:** `scripts/prisma_s_appendix.py`. A row without a date or a hit count exits 2.

**Fails when:** the appendix renders a database that was never reached as `0` records.
That is a coverage gap published as evidence of absence. The gate exits 3 for that row.

### E3. Screening calibration and conduct disclosure

The pilot calibration must pass before the full screen. The default gate is a kappa of
0.60 on a pilot of at least 50 records. The deliverable must disclose who screened and
whether a human verified the decisions.

**Gates:** `scripts/gate2a_calibration.py` (exit 2 below the threshold),
`scripts/check_screening_disclosure.py` (exit 2 on a false human-screening claim).

**Fails when:** the manuscript says "two reviewers screened independently" while the
screening log holds only agent decisions. The disclosure gate exits 2.

### E4. Exclusion reasons and ledger completeness

The screening ledger must hold one row per record the PRISMA flow claims was screened.
Every exclusion carries a reason code. Every include carries no exclusion reason.

**Gate:** `scripts/check_ledger_completeness.py`. A short ledger exits 2.

**Fails when:** an INCLUDE row carries an exclusion reason. That means the rule was
applied inconsistently, or the row is mis-tagged. Both need a human decision.

### E5. Extraction fields and coding rules

The coding sheet must have machine-readable field definitions and a stated coding rule for
each field. A record the coder could not read must appear as a gap, not as a blank cell.

**Gate:** the coding sheet validator of the pooling layer
(`../meta-analysis-forge/scripts/validate_coding_sheet.py`), listed in
`meta-analysis-forge/eval.md`. A blank effect size exits 3.

### E6. Synthesis type and poolability

The synthesis type must match the evidence. Do not pool effects with different constructs
or different estimands. Name the poolability check and its result.

**Gate:** none in this skill. The gate lives in `umbrella-review-skeptic` and
`meta-analysis-forge`.

**Fails when:** the report pools effects with different constructs because the number of
studies looked sufficient.

### E7. Risk of bias and certainty

The appraisal must name a tool and record a domain judgement. An AMSTAR 2-style appraisal
must not collapse into one total score when the tool warns against it.

**Gate:** `scripts/check_appraisal.py`. A placeholder appraisal such as "PROBAST
(conceptual)" exits 2.

### E8. PRISMA count reconciliation

Every stage total must reconcile: identified minus duplicates, screened minus excluded,
sought minus not retrieved, assessed minus excluded, and the included total.

**Gate:** `scripts/prisma_flow.py`. Broken totals exit 2. A missing count file exits 2.

### E9. Number provenance

Every number in the report must trace to a computed artifact. This is a hard error.

**Gate:** `scripts/numbers_provenance.py`. An untraceable number exits 2.

**Fails when:** an effect size appears in the draft and in no artifact. A partial
comparison must never read as a full one: an unreadable artifact exits 3, so the run is
not a pass.

### E10. Citation and retraction verification

Every cited DOI must resolve, and no cited source may carry a retraction flag. This is a
hard error.

**Gate:** `scripts/cross_verify_citations.py`, which writes `GATE_REPORT.json`. An
unresolved or retracted DOI exits 2 and sets the gate word to `FAIL`.

**Fails when:** the resolver cannot be reached. That is an input gap: exit 3, gate word
`INCOMPLETE`, status `insufficient_evidence`. `--allow-unresolved` must not waive it,
because no check was made.

### E11. Gaps stay gaps

A source that was never reached, an artifact that could not be read, and a record with no
data rows are input gaps. They must never be reported as a result, and never as a zero.
This is a hard error.

**Gates:** `scripts/prisma_s_appendix.py` (exit 3), `scripts/check_completeness.py`
(exit 3), `scripts/numbers_provenance.py` (exit 3), and
`../meta-ml-screener/scripts/validate_screening_log.py` (exit 3).

**Fails when:** a run reports a zero for a source nobody queried.

### E12. Reproducibility artifacts

The package must hold the search log, the screening log, the coding sheet, the analysis
script, and the protocol. A reader must be able to repeat each step from those artifacts.

**Fails when:** the report cites a number that no script in the package can reproduce.

---

## Gate inventory

Each row names the gate script, the decision it makes, its exit codes, and the fixture
that exercises each path in `scripts/selftest.sh`. A fixture that does not exist is stated
as missing, never guessed.

| Gate script | Decides | Exit codes | Pass fixture | Fail fixture |
|---|---|---|---|---|
| `scripts/cross_verify_citations.py` | every cited DOI resolves and carries no retraction | 0 pass; 2 unresolved or retracted; 3 resolver unreachable; 4 no input; 1 self-test failure | `--self-test`; `--allow-insufficient` on the dead proxy | fake DOI `10.9999/...` gives 2; the dead proxy gives 3; `--recheck` with the proxy gives 3 |
| `scripts/prisma_flow.py` | the PRISMA stage totals reconcile | 0 reconciled; 2 broken totals or a missing count file | reconciled counts give 0 | `identified_databases=100, screened=50` gives 2 |
| `scripts/sof_table.py` | each summary-of-findings row carries certainty and a computed absolute effect | 0 valid; 2 invalid row or a missing input file | a valid SoF row gives 0 | a row with no certainty and no baseline risk gives 2 |
| `scripts/prisma_s_appendix.py` | each reached search is reproducible, and an unreached source stays a gap | 0 pass; 2 irreproducible row; 3 unreached source | a complete log gives 0; `--allow-insufficient` gives 0; a searched-and-empty source gives 0 | a row with no date or no hits gives 2; `source_status=unavailable` gives 3 |
| `scripts/check_completeness.py` | no record vanished silently in `removed_other` or `not_retrieved` | 0 complete or waived; 2 incomplete; 3 unreached source; 1 usage | an attributed waiver gives 0; an all-reached log gives 0 | an unwaived gap gives 2; a stale waiver gives 2; a waiver with no approver gives 2; a single-source search gives 2 |
| `scripts/numbers_provenance.py` | every draft number traces to a computed artifact | 0 traceable; 2 untraceable number; 3 unreadable artifact; 4 unreadable draft | a traceable draft gives 0; `--allow-incomplete` gives 0 | an untraceable number gives 2; a missing artifact gives 3; a missing draft gives 4 |
| `scripts/check_review_integrity.py` | the R/C/C2/D/M/E/X/T/W/P artifact checks | 0 consistent; 2 problems | `--selftest` passes; a flat PRISMA shape gives 0 | a prose value in an ID column gives 2; a missing manuscript gives 2 |
| `scripts/check_ledger_completeness.py` | the ledger is evidence for the flow's counts | 0 consistent; 2 problems; 1 unrecognised PRISMA shape | `--selftest` passes; a flat shape gives 0 | a short ledger with an INCLUDE-with-reason gives 2; `{"nonsense": 1}` gives 1 |
| `scripts/check_appraisal.py` | a tool named in Methods is backed by real domain judgements | 0 ok; 2 placeholder appraisal; 1 self-test failure | `--selftest` passes | a "PROBAST (conceptual)" ledger gives 2 |
| `scripts/gate2a_calibration.py` | the screening pilot passes the agreement gate | 0 pass; 2 kappa below the threshold or n below the minimum; 1 self-test failure | `--selftest` passes | opposite decisions on the pilot give 2 |
| `scripts/generate_prisma_flow.py` | the stage names are recognised | 0 written; 2 no recognised stage name | recognised stages give 0 | a bogus stage name gives 2 |
| `scripts/fetch_pubmed_complete.py` | identified equals fetched | 0 complete; 2 mismatch; 1 usage | `--self-test` passes | no `--query` and no `--out` gives 1 |
| `scripts/check_screening_disclosure.py` | the deliverables claim no screening conduct they did not have | 0 consistent; 2 inconsistent; 1 usage | an honest negation gives 0 | a false human-screening claim gives 2 |
| `scripts/regression_suite.py` | one fixture per known defect class is caught | 0 all caught | the offline fixtures give 0 | no one-line fixture: it is a meta-suite, and `check_selftest_coverage.py` records the exemption with a reason |
| `scripts/check_selftest_coverage.py` | every gate has a pass fixture and a fail fixture | 0 covered; 2 a gate is one-sided; 1 usage | `--selftest` passes | no fixture: it is a meta-gate, and the exemption is recorded in the script with a reason |
| `scripts/doctor.sh` | the core toolchain is present | 0 every core dependency is present; 1 at least one core dependency is missing | running it on a complete machine gives 0 | no fixture: the missing-dependency path needs a broken environment |
| `scripts/fetch_fulltext.py` | how many records remain abstract-only | 0 measured; live network | none: the script calls PubMed | none: live network script |
| `scripts/prospero_search.py` | registration and novelty search results | 0 on a completed search; 1 with no argument | none: the endpoint is live | none: live network script |
| `scripts/acceptance_test.py` | the whole toolchain works end to end on live data | 0 every phase behaved; 1 a phase misbehaved | the live run | the adversarial live phases |

The suite also runs gates owned by other skills: the pooling engine and its validators
from `meta-analysis-forge` (listed in `meta-analysis-forge/eval.md`) and the numeric
fixture checker from `humanizerdrb`. Those rows live in their own eval files.

---

## Reporting

| Rubric item | Result | Note |
|---|---|---|
| E1 question and eligibility criteria | PASS/FAIL | |
| E2 search completeness | PASS/FAIL | |
| E3 calibration and disclosure | PASS/FAIL | |
| E4 exclusion reasons and ledger | PASS/FAIL | |
| E5 extraction fields and coding rules | PASS/FAIL | |
| E6 synthesis type and poolability | PASS/FAIL/NA | |
| E7 risk of bias and certainty | PASS/FAIL | |
| E8 PRISMA reconciliation | PASS/FAIL | |
| E9 number provenance | PASS/FAIL | |
| E10 citation verification | PASS/FAIL | |
| E11 gaps stay gaps | PASS/FAIL | |
| E12 reproducibility artifacts | PASS/FAIL | |

These checks bound what the package supports. They are not a clearance, and an all-pass
row set is not a quality grade: the checks cover internal consistency on the artifacts
supplied, and they do not cover the scientific merit of the review question.
