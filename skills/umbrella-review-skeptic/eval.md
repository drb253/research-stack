# eval.md — grade an umbrella review

Grade the synthesis against the ten rubric items below. Each item names the artifact it
reads, the check that decides it, and the failure it catches.

The skill has one gate script, `scripts/check_pooling_defensibility.py`, and a harness,
`scripts/selftest.sh` (24 checks). Run both:

```bash
python3 scripts/check_pooling_defensibility.py --self-test
bash scripts/selftest.sh
```

---

## Hard errors

A synthesis with a FAIL on U3, U6, or U10 must not ship until the defect is fixed.

### U1. Review classification

The project must be classified as an umbrella review, a review of reviews, or a
second-order meta-analysis. The three labels are not interchangeable, and a narrative
umbrella review is not a second-order meta-analysis.

**Fails when:** the manuscript calls a narrative summary a second-order meta-analysis.

### U2. Overlap quantified per review pair

Build the primary-study by review matrix. Report the number of studies per review, the
shared studies for each pair, and the share. Name the denominator.

**Gate:** `scripts/check_pooling_defensibility.py`. The report carries one record per pair
with `shared`, `studies_a`, `studies_b`, and `share`. The share equals shared / min(studies
in review A, studies in review B); the report states that definition, because a different
denominator gives a different number.

**Fails when:** the report names the overlap as a worry with no number.

### U3. Overlap above the threshold blocks the pool

A pair of reviews that shares more than 30% of its primary studies must be flagged. This
project records that rule in
`references/agricultural-diversification-second-order-meta.md` (rule 9). This is a hard
error.

**Gate:** `scripts/check_pooling_defensibility.py --pool`. An above-threshold pair gives
exit 2, status `fail`, and the verdict `indefensible_pooling`, with the pair, the shared
count, and the share in the finding.

**Fails when:** the pool proceeds because nobody computed the share, or because a large
review size hid the overlap.

### U4. Review quality appraisal

Appraise each review with AMSTAR 2-style or ROBIS-style logic. Report the critical domains
and the risk-of-bias judgement. Do not collapse the appraisal into one total score when
the tool warns against it.

**Fails when:** the scorecard prints one number per review and no domain judgement.

### U5. Effect comparability

The review-level effects must share a construct and a metric, or carry a stated defensible
conversion. Report the metric per review.

**Gate:** `scripts/check_pooling_defensibility.py --pool`. Differing review-level metrics
give exit 2 and the rule `metric_mismatch`.

### U6. Dependence modelled or sensitivity-tested

Pool only when the dependence is modelled or sensitivity-tested. State the model and the
dependence structure. This is a hard error.

**Gate:** `scripts/check_pooling_defensibility.py --pool` requires
`--dependence-handled` before an above-threshold overlap can pass. The declaration is
recorded in the report as `dependence_handled`.

**Fails when:** two reviews of the same trials enter a random-effects pool as if they were
independent bodies of evidence.

### U7. Review currency and superseded reviews

Track the last search date of each review and name the reviews that a newer review
supersedes. A superseded review must not add weight to the pool.

### U8. Discordance and certainty

Report where the reviews disagree, and report the certainty of the second-order
conclusion. A pooled estimate that hides a disagreement is misleading.

### U9. The unit is the review

The interpretation must state that the unit is a review or a meta-analysis. A review-level
effect is not a primary-study effect.

### U10. Unreadable primary-study lists stay gaps

A review whose primary-study list could not be read is an input gap. The gate must then
emit no pooling verdict at all, because a recommendation over a partial matrix is a claim
about evidence nobody read. Never absorb the unreadable count into the totals. This is a
hard error.

**Gate:** `scripts/check_pooling_defensibility.py`. Exit 3, status
`insufficient_evidence`, `verdict` null, `findings` empty, and one `input_gaps` entry with
a reason and an action. `--allow-insufficient` is the logged opt-out: it lowers the exit
code to 0 and leaves the status, the verdict, and the gap untouched.

---

## Gate inventory

| Gate script | Decides | Exit codes | Pass fixture | Fail fixture |
|---|---|---|---|---|
| `scripts/check_pooling_defensibility.py` | whether review-level pooling is defensible | 0 defensible or narrative; 1 usage error; 2 a finding blocks the pool; 3 a primary-study list could not be read; 4 `insufficient_input` | `--self-test` passes; the defensible matrix gives 0 with verdict `defensible_pooling`; the same matrix with no `--pool` gives 0 with verdict `narrative_synthesis`; `--dependence-handled` gives 0 | the overlapping matrix gives 2 with verdict `indefensible_pooling`; mixed metrics give 2; fewer than two reviews give 2; the gap matrix gives 3; a missing matrix gives 4; no arguments give 1 |
| `scripts/selftest.sh` | the whole contract above, on both paths | 0 every check passed; 1 a check failed; 4 a required file or interpreter is absent | the 24 checks in the suite | the harness itself is the fail fixture: before `SKILL.md` stated the AMSTAR, ROBIS, and 30% rules, two contract checks failed and the harness exited 1 |

The harness pins the gap rule directly, not only the exit code. It asserts that a gap run
carries `status = insufficient_evidence`, `verdict = null`, and an empty `findings` list,
and that `--allow-insufficient` changes none of those three fields.

---

## Reporting

| Rubric item | Result | Note |
|---|---|---|
| U1 review classification | PASS/FAIL | |
| U2 overlap quantified per pair | PASS/FAIL | |
| U3 above-threshold overlap blocks the pool | PASS/FAIL | |
| U4 review quality appraisal | PASS/FAIL | |
| U5 effect comparability | PASS/FAIL | |
| U6 dependence modelled or tested | PASS/FAIL | |
| U7 review currency | PASS/FAIL | |
| U8 discordance and certainty | PASS/FAIL | |
| U9 the unit is the review | PASS/FAIL | |
| U10 unreadable lists stay gaps | PASS/FAIL | |

These checks bound the pool. They are not a clearance: the gate covers the overlap matrix
and the effect table supplied to it, and it does not cover the quality of the searches
inside the included reviews.
