---
name: meta-analysis-forge
description: "This skill produces a first-order meta-analysis design and audit: an effect-size and harmonization plan, a machine-readable coding sheet, a model specification, heterogeneity and prediction-interval reporting, publication-bias diagnostics, and sensitivity checks. Use when a user asks to pool primary studies, choose an effect size, pick a fixed, random, multilevel, or robust-variance model, or audit a published meta-analysis, and when the meta-analysis alias routes a /meta-analysis request here. It does not synthesize existing reviews (use umbrella-review-skeptic) or orchestrate the full review (use evidence-synthesis-forge)."
---

# Meta-Analysis Forge

Use this skill when evidence synthesis needs statistical pooling of primary-study effects. The skill designs the pooling and audits an existing pool. The skill does not replace the substantive judgment of the review team.

## Core Principle

A meta-analysis is valid only when the combined effects are comparable for the target inference. The effects must agree in construct and in scale.

Separate seven decisions.

- effect-size extraction;
- effect-size conversion;
- dependence among effects;
- model choice;
- heterogeneity interpretation;
- publication-bias diagnostics;
- substantive conclusion.

Do not pool two effects solely because both carry a number.

## Terms Used In This Skill

Read this glossary before you read the rest of the file.

<!-- ste-allow R1, R8: a glossary table defines each term in the row that names it -->

| Full name | Meaning |
|---|---|
| standardised mean difference (SMD) | a unitless effect for a continuous outcome |
| odds ratio (OR), risk ratio (RR), hazard ratio (HR), risk difference (RD) | the ratio and difference measures |
| confidence interval (CI) | the interval around an estimate |
| standard error (SE) | the precision of one effect |
| robust variance estimation (RVE) | a dependence-robust method for many effects |
| Hartung-Knapp-Sidik-Jonkman (HKSJ) | a small-sample adjustment of the random-effects interval |

<!-- ste-allow R1, R8: a glossary table defines each term in the row that names it -->

| Full name | Meaning |
|---|---|
| individual participant data (IPD) | the raw participant rows behind a study |
| machine learning (ML) | a learned model that ranks or predicts |
| network meta-analysis (NMA) | a comparison of three or more treatments |
| partial least squares (PLS) path model (PM) | a component-based path model |
| structural equation model (SEM) | a covariance-based path model |
| SHapley Additive exPlanations (SHAP) | an attribution method for a model |
| explainable boosting machine (EBM) and generalised additive model (GAM) | two interpretable model families |

## Intake

Identify the pooling frame. Record each answer in the coding sheet.

- outcome construct.
- effect-size metric.
- standard error, confidence interval, p-value, or sample size availability.

- number of studies and the number of effects per study.
- study designs and the expected heterogeneity.
- moderators and the field norms.
- whether raw, participant-level, sample-level, or harmonized derived data are available.

If the user is unsure, propose two models and explain the tradeoff.

## Preflight and Dependencies

Run `scripts/install_r_packages.R` when the R packages are absent. The engine needs Rscript and the metafor package. The figures need robvis and ggplot2.

<!-- ste-allow R1: table cells are labels, not prose -->

| Dependency | Needed by | Check |
|---|---|---|
| python3 | `scripts/validate_coding_sheet.py` | `python3 -V` |
| Rscript | every R script | `Rscript --version` |
| metafor | the engine and the golden tests | `Rscript -e 'library(metafor)'` |
| robvis and ggplot2 | the risk-of-bias figures | `../evidence-synthesis-forge/scripts/doctor.sh` |

Run `scripts/validate_coding_sheet.py` before the engine. The validator checks the required fields, the numeric estimates, the positive standard errors, the duplicate effect identifiers, and the mixed effect metrics.

## Workflow

1. Define the effect-size family.

2. Build the coding sheet.

3. Convert or preserve each metric, and record the justification.

4. Identify the dependence: multiple outcomes, time points, samples, or models per study.

5. Pass the quality gates before you pool.

6. Choose the model: fixed, random, multilevel, robust variance, Bayesian, or narrative synthesis.

7. Report the heterogeneity: tau2, I2, and a prediction interval.

8. Assess the small-study effects or the publication bias when the design allows it.

9. Run the sensitivity checks.

10. Write the interpretation with the limits.

For individual participant data (IPD) or a mega-analysis, build a dataset inventory, a harmonization plan, and a quality-control ledger. Add a study or site heterogeneity model before any pooled interpretation.

## Poolability and Model Choice

Answer each question before you pool.

<!-- ste-allow R1: table cells are labels, not prose -->

| Question | If no | If yes |
|---|---|---|
| Do the effects share one construct? | use narrative synthesis | continue |
| Do the effects share one metric? | convert, or split the analysis | continue |
| Are the effects independent? | model the dependence | continue |
| Are the studies few (k below 10)? | avoid a funnel-plot claim | continue |

<!-- ste-allow R1: table cells are labels, not prose -->

| Situation | Model |
|---|---|
| one effect per study and low heterogeneity | fixed effect |
| one effect per study and real heterogeneity | random effects |
| many effects per study | multilevel or RVE |
| few studies with unequal precision | HKSJ interval |
| three or more treatments | NMA |

## Worked Example

The request is a pool of one comparable effect across several studies. Load `references/effect-sizes.md` for the metric definitions. Load `references/synthesis-models.md` for the model choice and the diagnostics. Load `references/poolability-and-model-choice.md` for the poolability gate.

1. Define the effect family. Choose the ratio measure.

2. Build `templates/coding-sheet.md` from `templates/coding-schema.csv`.

3. Run `scripts/validate_coding_sheet.py` on the sheet. The validator reports any blank estimate.

4. Run `scripts/run_meta_analysis.R` for the minimal demonstration.

5. Run `scripts/cochrane_meta.R` for the full report. Request tau2, I2, and a prediction interval.

6. Check the k against the funnel and meta-regression threshold of 10 studies.

The engine reports the numbers. The engine never invents a number.

## Output Modes

### Coding Sheet

Use the coding sheet before any model.

- `templates/coding-sheet.md` for a human-readable table.
- `templates/coding-schema.csv` for the field definitions.
- `templates/example-coding-sheet.csv` for a minimal machine-readable example.
- `templates/validation-rules.md` for the validation rules.

### Analysis Plan

```text
Effect-size metric:
Inclusion for pooling:
Model:
Dependence handling:
Heterogeneity:
Bias diagnostics:
Sensitivity checks:
Software:
Interpretation limits:
```

### Minimal R Run

Use `scripts/run_meta_analysis.R` for a small reproducible demonstration. Run it only when the coding sheet has one harmonized effect metric and valid standard errors.

```text
Input CSV:
Output directory:
Effect metric:
Pre-pooling checks passed:
Known limits:
```

### Validation and Conversion

Use `scripts/validate_coding_sheet.py` to check the required fields and the numeric estimates. Use the script to check the positive standard errors, the duplicate effect identifiers, and the mixed effect metrics.

Use `scripts/effect_size_helpers.R` for transparent mechanical helpers only. The helpers cover CI-to-SE, log-ratio transforms, Fisher z, the approximate SMD standard error, and lnROM. Record the formula and the assumption in the coding sheet notes.

### IPD / Mega-Analysis

Use these files for a participant-data pool.

- `references/ipd-and-mega-analysis.md` for the workflow and the guardrails.
- `templates/mega-analysis-dataset-inventory.csv` for data access and harmonization.
- `templates/mega-analysis-audit-report.md` for the audit output.

### Audit

Flag each defect in this list.

- incompatible outcomes;
- mixed effect metrics with no conversion;
- missing uncertainty;
- multiple effects treated as independent;
- I2 without a prediction interval;
- meta-regression overclaiming;

<!-- ste-allow R1: table cells are labels, not prose -->

| Defect | Gate | Result |
|---|---|---|
| a publication-bias test with too few studies | `scripts/cochrane_meta.R` | the engine reports the k limit |
| a blank effect size | `scripts/validate_coding_sheet.py` | exit 3 |
| a mixed effect metric | `scripts/cochrane_meta.R` | exit 1, refusal |

Load `references/meta-analysis-quality-gates.md` for the pre-pooling checks.

### Ecological Meta + ML + Path Model

Use `templates/ecological-meta-ml-path-model-audit.md` for a combined pool and a path model.

```text
Meta-analysis layer:
ML layer:
Path-model layer:
Effect-size families:
Dependence plan:
Main reuse lesson:
Main overclaim risk:
```

Load `references/soil-fauna-carbon-meta.md` when the project pools carbon stocks and carbon fluxes together.

<!-- ste-allow R8: PLS-PM is one hyphenated term; the rule reads its two halves -->
Load `references/ecological-meta-ml-path-model-paradigm.md` when the project pairs meta-regression with random forest. Use it for a partial least squares path model (PLS-PM) or an SEM-family model.

Load `references/ml-moderator-analysis.md` for the exploratory machine learning (ML) moderator analysis. The ML analysis complements a pre-specified meta-regression. The ML analysis never replaces it.

Load `references/network-meta-analysis.md` when three or more treatments form a connected network.

### High-Value Paper Reproducibility Audit

Use `templates/high-value-paper-reproducibility-audit.md` when the user wants to learn from a strong article with public data or code. Do not stop at a paper summary.

Extract each item in this list.

- the file and repository inventory.
- the data table structure.
- the effect-size and uncertainty logic.
- the `metafor::rma.mv()` implementation.
- the shared-control VCV or the other dependence handling.
- the random forest or ML layer.

<!-- ste-allow R1: table cells are labels, not prose -->

| Extract | Detail |
|---|---|
| the `plspm`, PLS-PM, PLS-SEM, or other path-model layer | record the package and the role |
| the peer-review lessons | record the reviewer request |
| the reproducibility gaps | name the missing artifact |
| the reusable skill rules | name the rule |

Load `references/high-value-paper-reproducibility-audit.md` for the full audit guide.

```text
Article logic:
Data table structure:
Effect-size logic:
rma.mv / dependence implementation:
Random forest layer:
PLS-PM / path-model layer:
Reproducibility verdict:
Reusable rule:
```

## Failure Modes

Each row names the condition, the gate, and the exact result.

<!-- ste-allow R1: table cells are labels, not prose -->

| Condition | Gate | Result |
|---|---|---|
| a blank effect size | `scripts/validate_coding_sheet.py` | exit 3, `insufficient_evidence` |
| a standard error at or below zero | `scripts/validate_coding_sheet.py` | exit 3, `insufficient_evidence` |
| the sheet cannot be read | `scripts/validate_coding_sheet.py` | exit 4, `insufficient_input` |
| mixed effect metrics | `scripts/cochrane_meta.R` | exit 1, refusal |
| fewer than two usable effects | `scripts/cochrane_meta.R` | exit 1, no pooled estimate |

<!-- ste-allow R1: table cells are labels, not prose -->

| Condition | Gate | Result |
|---|---|---|
| rows supplied do not match rows usable | `scripts/cochrane_meta.R` | exit 3, worklist written |
| an unparseable sheet | `scripts/cochrane_meta.R` | exit 4, `insufficient_input` |
| a requested figure cannot be written | `scripts/rob_figure.R` | exit 1, no false success |
| the fallback traffic light disagrees with robvis | `scripts/validate_rob_fallback.R` | exit 1 |
| the input CSV is absent | `scripts/forest_funnel.R` | exit 4, `insufficient_input` |

The engine writes a pooled estimate only from the rows it accepted. The engine never writes an estimate over a subset of the supplied rows.

## Guardrails

- Do not invent effect sizes.
- Do not pool effects solely because the numbers are available.
- Do not interpret a meta-regression causally unless the design supports it.
- Do not interpret a random-forest importance or a PLS-PM path causally unless the design supports it.

- Do not ignore the within-study dependence.
- Do not treat a high pooled N as proof of high evidence quality.
- Do not use vote-counting as a substitute for effect-size synthesis.
- Do not treat the minimal R script as a full pipeline.
- Do not run a conversion without preserving the original reported value and the source anchor.

<!-- ste-allow R1: table cells are labels, not prose -->

| Rule | Reason |
|---|---|
| Do not call a project a mega-analysis without raw, participant-level, sample-level, or harmonized derived data | the analysis reprocesses or remodels the unit under one frame |
| Do not call a high-value paper reproducible until you inspect the public code, the data schema, the package versions, and the model scripts | a summary is not an audit |

## What This Does Not Do

This skill does not find the studies. Use `evidence-synthesis-forge` for the search, the eligibility criteria, and the PRISMA flow. This skill does not synthesize existing reviews. Use `umbrella-review-skeptic` for the review-level unit and the overlap matrix. This skill does not run a learned screen. Use `meta-ml-screener` for that screen.

This skill does not certify a pooling decision. The engine reports the numbers it computed. The engine does not judge whether the clinical or ecological question permits a pool. A statistician and a domain expert make that judgment.

## Rubric Coverage

Each row maps one rubric item to the section that implements it. The rubric lives in `eval.md`.

<!-- ste-allow R1: table cells are labels, not prose -->

| Rubric item | Implemented in |
|---|---|
| M1 effect-size family | Core Principle; Workflow step 1 |
| M2 source anchor and original value | Guardrails; Validation and Conversion |
| M3 dependence handling | Workflow step 4; Poolability and Model Choice |
| M4 model choice | Poolability and Model Choice |
| M5 heterogeneity reporting | Workflow step 7; Output Modes |
| M6 publication-bias k limit | Poolability and Model Choice; Audit |

<!-- ste-allow R1: table cells are labels, not prose -->

| Rubric item | Implemented in |
|---|---|
| M7 sensitivity checks | Workflow step 9 |
| M8 certainty limits | Workflow step 10; What This Does Not Do |
| M9 number provenance | Failure Modes; Worked Example |
| M10 refusals | Failure Modes; Guardrails |
| M11 reproducibility package | Preflight and Dependencies; IPD / Mega-Analysis |
