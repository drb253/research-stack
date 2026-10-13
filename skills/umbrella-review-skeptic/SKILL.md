---
name: umbrella-review-skeptic
description: This skill produces an umbrella-review audit: a primary-study by review overlap matrix, a review-quality appraisal, an effect-comparability verdict, and a defensible narrative or second-order synthesis plan. Use when a user asks to synthesize existing systematic reviews or meta-analyses, quantify duplicate evidence or primary-study overlap, appraise review quality with AMSTAR 2 or ROBIS logic, or judge whether review-level statistical pooling is defensible, and when the sysreview alias routes a review-of-reviews request here. It does not pool primary studies for the first time; use meta-analysis-forge for a first-order meta-analysis.
---

# Umbrella Review Skeptic

Use this skill when the evidence base already holds reviews or meta-analyses, and the user wants to synthesize the syntheses. The skill tests whether that second synthesis is defensible. The unit of evidence is a review, not a primary study.

## Core Principle

Do not simply average the meta-analyses. Existing reviews often reuse the same primary studies. Existing reviews often use different inclusion rules. Existing reviews often report non-comparable pooled effects.

A second-order pool is defensible only when the reviews do not double count the same evidence. The review-level effects must measure the same thing, and the analysis must model or test the dependence. Prefer a narrative umbrella synthesis when any condition fails.

## Terms Used In This Skill

Read this glossary before you read the rest of the file.

<!-- ste-allow R1, R8: a glossary table defines each term in the row that names it -->

| Full name | Meaning |
|---|---|
| A MeaSurement Tool to Assess systematic Reviews (AMSTAR) 2 | the review-quality instrument |
| Risk Of Bias In Systematic reviews (ROBIS) | the risk-of-bias instrument for a review |
| Open Science Framework (OSF) | a repository for the R scripts and the data |
| second-order meta-analysis | a statistical synthesis of review-level effects |
| umbrella review | a structured summary of many reviews |
| review of reviews | a broader summary that need not be quantitative |

## Intake

Identify the review set. Record each answer in the overlap matrix.

- the included reviews and meta-analyses.
- the review questions.
- the search dates for each review.
- the primary studies inside each review.

- the pooled effects and the metrics.
- the quality assessment method.
- the overlap among the reviews.
- whether the project plans a second-order statistical synthesis.

Load `references/overlap-and-quality.md` for the overlap and the quality checks. Load `references/second-order-decision-rules.md` when you decide whether review-level pooling is defensible. Load `references/agricultural-diversification-second-order-meta.md` for a long-term agricultural diversification synthesis with ecosystem-service, profitability, and yield trade-offs.

## Preflight and Dependencies

Answer these questions before you pool anything.

<!-- ste-allow R1: table cells are labels, not prose -->

| Question | Evidence needed |
|---|---|
| Can you read every primary-study list? | one row per primary study in the overlap matrix |
| Is the review set complete? | the search date of each review |
| Do the reviews share a metric? | the metric column of the effect schema |
| Is the overlap quantified? | the share for every review pair |
| Is the dependence handled? | a model statement or a sensitivity test |

Run `scripts/check_pooling_defensibility.py` on the effect table and the overlap matrix. The gate reads `--effects` and `--overlap`, and it reports one of four outcomes.

<!-- ste-allow R1: table cells are labels, not prose -->

| Outcome | Exit code | Meaning |
|---|---|---|
| defensible pooling | 0 | the pool is allowed, or the narrative route wins |
| indefensible pooling | 2 | an overlap or a metric mismatch blocks the pool as requested |
| insufficient_evidence | 3 | a primary-study list could not be read; the gate emits no verdict |
| insufficient_input | 4 | a supplied file is missing or unparseable |

The gate never reports a pool over a partial matrix. Use `--allow-insufficient` only as a logged opt-out. The opt-out lowers the exit code. The opt-out does not change the status and it does not produce a verdict.

The gate flags a review pair that shares more than 30% of its primary studies. This project records that rule in `references/agricultural-diversification-second-order-meta.md` (rule 9). The share equals shared / min(studies in review A, studies in review B). State that definition in the report, because a different denominator gives a different number.

## Workflow

1. Classify the project: umbrella review, review of reviews, or second-order meta-analysis.

2. Extract the review-level characteristics.

3. Build a primary-study by review matrix.

4. Assess the overlap and the duplicate evidence.

5. Assess the review quality and the search currency.

6. Compare the effect metrics and the inclusion criteria.

7. Apply the AMSTAR 2 or ROBIS appraisal logic.

8. Decide: a narrative umbrella synthesis, an evidence map, or a second-order pool.

9. State the dependence assumptions and the model choice if the project pools.

10. Report the discordance and the certainty.

Use `templates/overlap-matrix.md` for the overlap tracking. Report the count of reviews whose primary-study list you could not read beside the totals. Never absorb that count into the totals.

## Pooling Decision

Answer each question. The first "no" decides the synthesis type.

<!-- ste-allow R1: table cells are labels, not prose -->

| Question | If no |
|---|---|
| Do the review-level effects share one construct? | narrative umbrella synthesis |
| Do the reviews share one metric, or a defensible conversion? | narrative umbrella synthesis |
| Is the overlap below 30%, or is the dependence handled? | narrative umbrella synthesis |
| Are the inclusion scopes similar? | narrative umbrella synthesis |

<!-- ste-allow R1: table cells are labels, not prose -->

| Condition | Preferred synthesis |
|---|---|
| high overlap | narrative umbrella synthesis |
| different effect metrics | narrative umbrella synthesis |
| incompatible eligibility criteria | narrative umbrella synthesis |
| highly variable review quality | narrative umbrella synthesis |
| superseded older reviews | narrative umbrella synthesis |
| compatible effects and quantified overlap | second-order meta-analysis |

## Worked Example

The request is a second-order synthesis of five meta-analyses on one practice.

1. Classify the project. The request is a second-order meta-analysis.

2. Extract the review-level effects into `templates/review-level-effect-schema.csv`.

3. Build the primary-study by review matrix in `templates/overlap-matrix.md`.

4. Run `scripts/check_pooling_defensibility.py --effects ... --overlap ... --pool`.

5. Read the verdict. A share above 0.30 blocks the pool.

6. If the gate blocks the pool, switch to a narrative umbrella synthesis.

7. If the pool is allowed, state the dependence plan in `templates/second-order-model-spec-ledger.csv`.

8. Report the discordance and the certainty.

The gate reports the overlap it measured. The gate does not report a pool over a review whose primary-study list is unreadable.

## Output Modes

### Umbrella Audit

```text
Review set:
Overlap risk:
Quality concerns:
Effect comparability:
Can pool statistically?
Preferred synthesis:
Main caution:
```

### Second-Order Meta Plan

```text
Review-level effect:
Primary-study overlap:
Dependence handling:
Quality weighting/sensitivity:
Model:
Interpretation limits:
```

### Temporal Trade-Off Audit

Use this mode when the second-order synthesis asks how the effects change over years or decades.

```text
Review-level evidence base:
Duration moderator:
Outcome families:
Review-level weights:
Random effects:
Primary-study overlap:
Trade-off categories:
Long-term research gaps:
Policy interpretation limits:
```

Load `templates/second-order-temporal-tradeoff-audit.md` and `templates/review-level-effect-schema.csv` for the review-level temporal meta-regression and the yield-service trade-off audit.

Load `templates/second-order-r-package-ledger.csv` when you extract the software packages and the model roles from a second-order meta-analysis. Load `templates/osf-r-dependency-inventory.csv` when you audit the OSF or GitHub R scripts beyond the packages the paper names.

Load `templates/second-order-quality-scorecard.csv`, `templates/second-order-model-spec-ledger.csv`, and `templates/agricultural-diversification-taxonomy.csv` when you adapt an agricultural diversification protocol. Load `templates/second-order-peer-review-readiness-checklist.csv` before a submission or a revision.

## Failure Modes

Each row names the condition, the gate or the check, and the exact result.

<!-- ste-allow R1: table cells are labels, not prose -->

| Condition | Gate | Result |
|---|---|---|
| a review pair shares more than 30% of its studies | `scripts/check_pooling_defensibility.py --pool` | exit 2, verdict `indefensible_pooling` |
| the review-level metrics differ | `scripts/check_pooling_defensibility.py --pool` | exit 2, rule `metric_mismatch` |
| fewer than two reviews | `scripts/check_pooling_defensibility.py --pool` | exit 2, rule `review_count` |
| a primary-study list could not be read | `scripts/check_pooling_defensibility.py` | exit 3, `insufficient_evidence`, no verdict |
| a supplied file is missing | `scripts/check_pooling_defensibility.py` | exit 4, `insufficient_input` |

<!-- ste-allow R1: table cells are labels, not prose -->

| Condition | Check | Result |
|---|---|---|
| the review quality is a single total score | the AMSTAR 2 rule | flag the score and name the critical domains |
| a newer review supersedes an older review | the currency check | name the superseded review |
| one fact differs between two templates | the audit | resolve the difference before the report |
| the overlap matrix has no primary-study list | the overlap check | report the gap; do not pool |

## Guardrails

- Do not double count the same primary studies.
- Do not pool reviews with incompatible effect metrics without a justification.
- Do not treat many reviews as many independent bodies of evidence.
- Do not ignore an older review that a newer review supersedes.

- Do not call a narrative umbrella review a second-order meta-analysis.
- Do not assign a simple total score to the review quality when the appraisal tool warns against it.
- Do not interpret a review-level duration trend as a primary-study causal effect.
- Do not collapse yield, profitability, biodiversity, soil quality, and climate mitigation into one sustainability score.

The last rule holds unless the weighting rule is explicit.

## What This Does Not Do

This skill does not pool primary studies for the first time. Use `meta-analysis-forge` for a first-order meta-analysis, for the effect-size conversion, and for the model diagnostics. This skill does not find the reviews. Use `evidence-synthesis-forge` for the search, the eligibility criteria, and the PRISMA flow. This skill does not run a learned screen. Use `meta-ml-screener` for that screen.

This skill does not decide that a review is trustworthy. The appraisal records the quality. A domain expert makes the final judgment. This skill does not make an unreadable primary-study list readable. The gate reports that list as a gap and stops.

## Rubric Coverage

Each row maps one rubric item to the section that implements it. The rubric lives in `eval.md`.

<!-- ste-allow R1: table cells are labels, not prose -->

| Rubric item | Implemented in |
|---|---|
| U1 review classification | Workflow step 1; Core Principle |
| U2 overlap quantified per pair | Preflight and Dependencies; Pooling Decision |
| U3 overlap above the threshold blocks pooling | Pooling Decision; Failure Modes |
| U4 review quality appraisal | Intake; Workflow step 7; Guardrails |
| U5 effect comparability | Pooling Decision; Failure Modes |
| U6 dependence modelled or tested | Preflight and Dependencies; Failure Modes |

<!-- ste-allow R1: table cells are labels, not prose -->

| Rubric item | Implemented in |
|---|---|
| U7 review currency and superseded reviews | Workflow step 5; Guardrails |
| U8 discordance and certainty | Workflow step 10; Output Modes |
| U9 the unit is the review | Core Principle; What This Does Not Do |
| U10 unreadable lists stay gaps | Preflight and Dependencies; Failure Modes |
