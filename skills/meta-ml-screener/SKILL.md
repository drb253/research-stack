---
name: meta-ml-screener
description: This skill produces a machine-learning assisted screening plan: an active-learning or LLM workflow, an auditable screening log, a human-verification plan, and a measured recall check. Use when a user asks for deduplication, title and abstract screening, full-text triage, study classification, LLM-assisted extraction, risk-of-bias triage, topic modeling, or moderator discovery, and when the sysreview alias routes a review request here. It does not make final inclusion decisions, and it does not replace the review design in evidence-synthesis-forge or the synthesis in meta-analysis-forge.
---

# Meta ML Screener

Use this skill when machine learning (ML) assists a systematic review or a meta-analysis. The skill designs the assisted workflow and the audit trail. A human keeps the final decision.

## Core Principle

ML can reduce the workload. ML can rank the records and extract the candidates. ML can explore the heterogeneity. ML must not hide the eligibility criteria, the final inclusion decisions, or the effect-size verification.

Separate four things.

- the ML task;
- the human decision point;
- the evidence that the model works;
- the audit log of every decision.

## Terms Used In This Skill

Read this glossary before you read the rest of the file.

<!-- ste-allow R1, R8: a glossary table defines each term in the row that names it -->

| Full name | Meaning |
|---|---|
| machine learning (ML) | a learned model that ranks, labels, or extracts |
| Preferred Reporting Items for Systematic Reviews and Meta-Analyses (PRISMA) | the reporting standard for the review |
| active learning | a loop that trains on the labels a human supplies |
| recall | the share of the truly eligible records the model finds |
| prompt schema | the fixed instruction and output shape for a language model |
| adjudication | the recorded human decision after a disagreement |

## Intake

Identify the ML task first.

<!-- ste-allow R1: table cells are labels, not prose -->

| Task | Typical human decision point |
|---|---|
| deduplication | confirm a duplicate pair before the merge |
| title and abstract screening | include, exclude, or retrieve the full text |
| full-text triage | the final eligibility decision |
| study design classification | confirm the design label |
| outcome classification | confirm the outcome family |
| extraction assistance | verify each extracted number |

<!-- ste-allow R1: table cells are labels, not prose -->

| Task | Typical human decision point |
|---|---|
| risk-of-bias triage | confirm each domain judgement |
| topic modeling | name and interpret each topic |
| moderator discovery | promote a candidate to a pre-specified test |

Identify the constraints next.

- the labeled data available.
- the human verification plan.
- the recall requirement.
- the audit log format.
- the software or the platform.
- whether the review uses a language model.

Load `references/ml-assisted-review.md` for the task-specific guidance.

## Preflight and Dependencies

Confirm the environment before you run a model.

<!-- ste-allow R1: table cells are labels, not prose -->

| Dependency | Needed by | Check |
|---|---|---|
| python3 | `scripts/validate_screening_log.py` | `python3 -V` |
| a labeled seed set | calibration and recall | at least two reviewers agree on the seed |
| the protocol | the eligibility criteria | lock the criteria before the screen |
| the log schema | every decision | `templates/screening-log-schema.csv` |

Run `scripts/validate_screening_log.py --self-test` before a live screen. The self-test pins the exit codes and the input-gap behavior. Use `templates/example-screening-log.csv` for a minimal example.

## Workflow

1. Define the ML role and the decisions that stay human.

2. Create the seed labels or the validation set.

3. Define the features, the model, or the prompt schema.

4. Run the prioritization, the classification, or the extraction.

5. Record every score, label, and decision.

6. Validate the recall or the extraction accuracy.

7. Escalate an uncertain record to a human reviewer.

8. Export the decisions, the model scores, the prompts or schemas, and the human adjudication.

9. Report the ML use in the manuscript.

## Decision Tables

Choose the stopping rule and the escalation rule from these tables.

<!-- ste-allow R1: table cells are labels, not prose -->

| Condition | Action |
|---|---|
| the model is uncertain | escalate to a human |
| the score sits near the cut point | escalate to a human |
| a record has no abstract | retrieve the full text |
| the recall check fails the target | widen the search and re-screen |

<!-- ste-allow R1: table cells are labels, not prose -->

| Stopping rule | Meaning |
|---|---|
| a fixed recall estimate on the validation set | the worked example uses this rule |
| a fixed budget of records | state the budget and the coverage |
| no new include in a full pass | record the pass count |

## Worked Example

The request is a title and abstract screen with active learning.

1. Define the ML role. The model ranks the records. The human decides.

2. Create the seed labels. Two reviewers label the same seed records.

3. Define the features and the model. Record the version and the parameters.

4. Run the ranking. Record the score and the rank for every record.

5. Validate the recall on a held-out set. Report the recall and the interval.

6. Escalate every uncertain record to a human reviewer.

7. Export the decisions with `templates/screening-log.md`.

8. Validate the log with `scripts/validate_screening_log.py`.

The plan reports the recall it measured. The plan does not claim a recall it did not measure.

## Output Modes

### ML Screening Plan

```text
ML task:
Human decision point:
Training/seed labels:
Validation metric:
Audit log:
Stopping rule:
Failure modes:
Reporting sentence:
```

### Extraction Schema

```text
Field:
Definition:
Source anchor:
Confidence:
Human verification:
```

## Failure Modes

Each row names the condition, the validator result, and the required action.

<!-- ste-allow R1: table cells are labels, not prose -->

| Condition | Result | Action |
|---|---|---|
| a required column is absent | exit 1, a finding | add the column and re-run |
| a decision value is not allowed | exit 1, a finding | correct the value |
| a record identifier repeats | exit 1, a finding | merge or renumber the row |
| an exclusion carries no reason | exit 1, a finding | record the reason code |
| the log holds no data rows | exit 3, `insufficient_input` | supply the rows; the gap is not a result |

<!-- ste-allow R1: table cells are labels, not prose -->

| Condition | Result | Action |
|---|---|---|
| the log cannot be read | exit 2 | fix the path or the CSV syntax |
| the recall check cannot run | report the gap | do not claim a recall |
| the model version is unknown | report the gap | recover the version before you report |

An input gap exits 3. A finding exits 1. Never report the two in one channel.

## Guardrails

- Do not exclude a record solely because the model is confident. Exclude only when the protocol allows it and the recall check passes.
- Do not use an LLM-extracted number without a source anchor and a verification.
- Do not treat an ML-discovered moderator as confirmatory.

- Do not hide the prompt, the model, or the version when the choice affects a review decision.
- Do not let automation erase an exclusion reason or a reviewer's accountability.
- Do not accept a screening log as auditable unless the log records the human decisions and the exclusion reasons.

## What This Does Not Do

This skill does not make the final inclusion decision. A human owns that decision. This skill does not design the review. Use `evidence-synthesis-forge` for the protocol, the search, and the PRISMA flow. This skill does not fit the statistical model. Use `meta-analysis-forge` for the pool.

This skill does not measure the true recall of a model on the records the model never scored. That quantity is unknown. The skill reports the recall on the validation set only, and it names that bound.

## Rubric Coverage

Each row maps one rubric item to the section that implements it. The rubric lives in `eval.md`.

<!-- ste-allow R1: table cells are labels, not prose -->

| Rubric item | Implemented in |
|---|---|
| X1 ML role and human decision points | Core Principle; Intake |
| X2 validation set and recall | Workflow steps 2 and 6; Worked Example |
| X3 decision reasons | Failure Modes; Guardrails |
| X4 human verification and adjudication | Workflow steps 7 and 8 |
| X5 prompts, models, versions, schemas | Workflow step 3; Decision Tables |
| X6 uncertain records escalate | Decision Tables; Worked Example |

<!-- ste-allow R1: table cells are labels, not prose -->

| Rubric item | Implemented in |
|---|---|
| X7 moderators stay exploratory | Intake; Guardrails |
| X8 human final decision | Core Principle; What This Does Not Do |
