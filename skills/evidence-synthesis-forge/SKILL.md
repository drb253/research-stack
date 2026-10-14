---
name: evidence-synthesis-forge
description: "This skill produces a review design package: an auditable protocol, eligibility criteria, a registered search plan, a screening and coding workflow, an appraisal plan, and a report structure for a systematic review, scoping review, evidence map, rapid review, or umbrella review. Use when a user asks to run or plan a systematic review, an SLR, a scoping review, a rapid review, or a PRISMA 2020 review, and when the sysreview alias routes an end-to-end review request here. It does not design a first-order statistical model (use meta-analysis-forge), review existing reviews (use umbrella-review-skeptic), or run machine-learning screening (use meta-ml-screener)."
---

# Evidence Synthesis Forge

Use this skill as the orchestrator for evidence synthesis. The skill moves a broad review idea to an auditable package. The package holds a protocol, a search plan, a screening workflow, a coding plan, a synthesis plan, and a report structure.

## Core Principle

Separate six decisions.

1. Question: the evidence to synthesize.
2. Search: the way the review finds the studies.
3. Screening: the rule that includes or excludes a record.
4. Coding: the study features and the effects to extract.
5. Synthesis: the narrative summary, the evidence map, or the statistical pool.
6. Judgment: the risk of bias, the certainty, and the interpretation.

Do not start a meta-analysis before you check the comparability of the studies, the outcomes, and the effect sizes.

## Terms Used In This Skill

Read this glossary before you read the rest of the file.

<!-- ste-allow R1, R8: a glossary table defines each term in the row that names it -->

| Full name | Meaning |
|---|---|
| Preferred Reporting Items for Systematic Reviews and Meta-Analyses (PRISMA) | the reporting standard |
| Population, Intervention, Comparator, Outcome (PICO) | the question frame for an intervention review |
| Population, Exposure, Comparator, Outcome (PECO) | the question frame for an exposure review |
| Population, Intervention, Comparator, Outcome, Study design (PICOS) | the extended question frame |
| Sample, Phenomenon of Interest, Design, Evaluation, Research type (SPIDER) | the frame for a qualitative review |
| Joanna Briggs Institute (JBI) | the guide for broader review types |
| Collaboration for Environmental Evidence (CEE) | the guide for environmental reviews |

<!-- ste-allow R1, R8: a glossary table defines each term in the row that names it -->

| Full name | Meaning |
|---|---|
| Grading of Recommendations Assessment, Development and Evaluation (GRADE) | the certainty framework |
| A MeaSurement Tool to Assess systematic Reviews (AMSTAR) 2 | the review-quality instrument |
| Risk Of Bias In Systematic reviews (ROBIS) | the risk-of-bias instrument for a review |
| Methodological Expectations of Cochrane Intervention Reviews (MECIR) | the conduct standard |
| machine learning (ML) | a learned model that ranks or labels records |
| PROSPERO | the international register of systematic reviews |

## Intake

Identify the review frame. Record each answer in the protocol.

- domain: environment, ecology, medicine, life science, economics, policy, education, psychology, or other.
- review type: systematic review, scoping review, evidence map, rapid review, meta-analysis, umbrella review, or second-order meta-analysis.
- question framework: PICO (Population, Intervention, Comparison, Outcome), PECO, PICOS, SPIDER, or a custom frame.
- population, exposure, intervention, comparator, and outcome.
- eligible study designs and the desired outputs.
- whether machine learning (ML) assists screening or extraction, and the human verification plan.

If the user is unsure, propose a review type and explain the tradeoff. Load `references/review-types.md` for the choice and the question frame.

## Preflight and Dependencies

Run `scripts/doctor.sh` before a live review. The script prints a version for each dependency. A missing core dependency gives a non-zero exit.

<!-- ste-allow R1: table cells are labels, not prose -->

| Dependency | Needed by | Preflight |
|---|---|---|
| python3 | every gate script | `python3 -V` |
| Rscript and the metafor package | the pooling engine and the figures | `scripts/doctor.sh` |
| network access | the citation gate and the registry search | the reachability probe in `doctor.sh` |
| one review root | every `--root` gate | one directory per review |

Set the review root before you run a gate. The gates read `prisma_counts.json`, `sources.csv`, and `ledgers/` under that root. A gate that cannot read an input exits 3 and reports an input gap. Never report an input gap as a result.

## Workflow

1. Build the review question.

2. Define the eligibility criteria.

3. Draft the search strategy and the databases.

4. Design the screening stages and the exclusion reasons.

5. Define the extraction fields and the coding rules.

6. Choose the synthesis type: narrative, evidence map, first-order meta-analysis, umbrella review, or second-order meta-analysis.

7. Specify the risk-of-bias or quality assessment.

8. Align the protocol and the report with the guidance source.

9. Add the reproducibility artifacts. The artifacts are the search log, the screening log, the coding sheet, the analysis script, and the protocol.

Run step 8 with the matching file. Use PRISMA (Preferred Reporting Items for Systematic Reviews and Meta-Analyses) for reporting. Use Cochrane and MECIR for an intervention review. Use JBI for a broader review type. Use CEE for environmental evidence. Load `references/protocol-reporting-crosswalk.md` for the crosswalk.

Run step 9 before you write the report. Use `references/prisma-2020-manuscript-reporting.md` for the 27-item manuscript check. Use `references/reporting-guideline-checklists.md` to select the reporting guideline and the risk-of-bias instrument.

## Load Map

Load a reference when the task matches the row.

<!-- ste-allow R1: table cells are labels, not prose -->

| Load | When |
|---|---|
| `references/review-types.md` | the user needs help with the review type or the question frame |
| `references/protocol-reporting-crosswalk.md` | the user needs PRISMA, Cochrane, JBI, or CEE alignment |
| `references/screening-governance.md` | the screen needs validation before scale |
| `references/prospero-and-citation-verification.md` | the review needs registration or source verification |
| `references/prisma-2020-manuscript-reporting.md` | the review needs the PRISMA 2020 manuscript check |
| `references/reporting-guideline-checklists.md` | the user selects a reporting guideline or an appraisal tool |

<!-- ste-allow R1: table cells are labels, not prose -->

| Load | When |
|---|---|
| `references/rob-tool-selection.md` | the user selects a risk-of-bias tool |
| `references/cochrane-handbook-map.md` | the review follows the Cochrane Handbook |
| `references/cochrane-figures-tables.md` | the report needs a forest plot or a summary-of-findings table |
| `references/grade-certainty.md` | the report rates certainty with GRADE |
| `references/search-reporting-prisma-s.md` | the report needs the PRISMA-S appendix |
| `references/mecir-standards.md` | the review claims MECIR conduct |
| `references/icmr-systematic-review-guide.md` | the review follows the Indian Council of Medical Research guide |

<!-- ste-allow R1: table cells are labels, not prose -->

| Tool | Role |
|---|---|
| `templates/evidence-protocol.md` | the full protocol skeleton |
| `templates/prisma-flow-counts.csv` | the count template for the flow diagram |
| `scripts/generate_prisma_flow.py` | the Mermaid flow diagram writer |
| `scripts/prisma_flow.py` | the print-ready PRISMA 2020 flow diagram |
| `scripts/prisma_s_appendix.py` | the PRISMA-S search appendix |
| `scripts/sof_table.py` | the GRADE summary-of-findings table |

<!-- ste-allow R1: table cells are labels, not prose -->

| Tool | Role |
|---|---|
| `scripts/prospero_search.py` | the PROSPERO registration and novelty search |
| `scripts/cross_verify_citations.py` | the citation and retraction gate; writes `GATE_REPORT.json` |
| `scripts/fetch_pubmed_complete.py` | the complete PubMed retrieval |
| `scripts/fetch_fulltext.py` | the open-access full-text retrieval |
| `scripts/gate2a_calibration.py` | the screening calibration gate |
| `scripts/numbers_provenance.py` | the number-provenance gate |

<!-- ste-allow R1: table cells are labels, not prose -->

| Tool | Role |
|---|---|
| `scripts/check_completeness.py` | the retrieval and assessment completeness gate |
| `scripts/check_ledger_completeness.py` | the screening-ledger completeness gate |
| `scripts/check_review_integrity.py` | the cross-artifact integrity gate |
| `scripts/check_appraisal.py` | the appraisal-honesty gate |
| `scripts/check_screening_disclosure.py` | the screening-conduct disclosure gate |
| `scripts/regression_suite.py` | the defect-fixture regression suite |

## Decision Tables

### Review Type

<!-- ste-allow R1: table cells are labels, not prose -->

| Signal | Review type |
|---|---|
| one focused question and a poolable effect | systematic review plus meta-analysis |
| a broad question and a mapped field | scoping review or evidence map |
| a decision inside a short deadline | rapid review |
| an existing body of reviews | umbrella review |

### Synthesis Type

<!-- ste-allow R1: table cells are labels, not prose -->

| Condition | Synthesis |
|---|---|
| constructs and estimands differ | narrative synthesis |
| outcomes differ but the evidence is broad | evidence map |
| one comparable effect family and enough studies | first-order meta-analysis |
| the unit is an existing review | umbrella review or second-order meta-analysis |

### Screening Stage

<!-- ste-allow R1: table cells are labels, not prose -->

| Stage | Decision | Gate |
|---|---|---|
| calibration pilot | lock the criteria after kappa passes | `scripts/gate2a_calibration.py` |
| title and abstract | include or exclude one record | `scripts/check_ledger_completeness.py` |
| full text | include, exclude, or record a gap | `scripts/prisma_flow.py` |
| final set | reconcile the counts with the logs | `scripts/check_completeness.py` |

## Worked Example

The request is a review of a treatment for a common infection. The review type is a systematic review with a meta-analysis.

1. Build the PICO question. State the population, the intervention, the comparator, and the outcome.

2. Define the eligibility criteria. Name the designs, the dates, and the language limits.

3. Draft the search. Record the database, the platform, the query, the date, and the hits.

4. Run `scripts/gate2a_calibration.py` on a pilot slice. The default threshold is 0.60.

5. Build the ledger. Give every excluded record a reason code.

6. Reconcile the counts with `scripts/prisma_flow.py`.

7. Verify every cited DOI with `scripts/cross_verify_citations.py`.

8. Check every report number with `scripts/numbers_provenance.py`.

The run writes a search log, a screening log, a coding sheet, and a protocol. A reviewer can repeat each step from those artifacts.

## Output Modes

### Protocol Skeleton

Use `templates/evidence-protocol.md` for a full protocol.

### Review Design Memo

```text
Review type:
Question framework:
Eligibility criteria:
Search plan:
Screening workflow:
Extraction fields:
Synthesis plan:
Bias/quality assessment:
Reproducibility artifacts:
Risks:
```

### PRISMA Flow

Use `templates/prisma-flow-counts.csv` to record the counts. Use `scripts/generate_prisma_flow.py` to write a Mermaid diagram. Use `scripts/prisma_flow.py` to write the print-ready diagram.

```text
Count source:
Records identified:
Duplicates removed:
Records screened:
Reports assessed:
Studies included:
Studies in meta-analysis:
Known deviations:
```

### Audit

When you review an existing protocol or review, inspect these items.

- vague eligibility criteria;
- an incomplete search;
- unlogged exclusions;
- incompatible outcomes;
- a missing risk-of-bias assessment;
- naive pooling.

Check the hidden ML decisions and the overclaiming in a second pass.

## Failure Modes

Each row names the condition, the gate, and the exact result.

<!-- ste-allow R1: table cells are labels, not prose -->

| Condition | Gate | Result |
|---|---|---|
| a draft number does not trace to an artifact | `scripts/numbers_provenance.py` | exit 2 |
| a supplied artifact cannot be read | `scripts/numbers_provenance.py` | exit 3, status `insufficient_evidence` |
| the draft cannot be read | `scripts/numbers_provenance.py` | exit 4, `insufficient_input` |
| an unresolved or retracted DOI | `scripts/cross_verify_citations.py` | exit 2, gate `FAIL` |
| the resolver is unreachable | `scripts/cross_verify_citations.py` | exit 3, gate `INCOMPLETE` |

<!-- ste-allow R1: table cells are labels, not prose -->

| Condition | Gate | Result |
|---|---|---|
| the PRISMA counts do not reconcile | `scripts/prisma_flow.py` | exit 2 |
| a search row has no date or no hits | `scripts/prisma_s_appendix.py` | exit 2 |
| a logged source was never reached | `scripts/prisma_s_appendix.py` | exit 3 |
| `removed_other` or `not_retrieved` is above zero | `scripts/check_completeness.py` | exit 2 |
| a waiver declares a stale value | `scripts/check_completeness.py` | exit 2 |

<!-- ste-allow R1: table cells are labels, not prose -->

| Condition | Gate | Result |
|---|---|---|
| the ledger is shorter than the flow claims | `scripts/check_ledger_completeness.py` | exit 2 |
| the PRISMA file carries no recognised shape | `scripts/check_ledger_completeness.py` | exit 1 |
| the appraisal is a placeholder | `scripts/check_appraisal.py` | exit 2 |
| the manuscript claims human screening | `scripts/check_screening_disclosure.py` | exit 2 |
| two artifacts disagree on one fact | `scripts/check_review_integrity.py` | exit 2 |

<!-- ste-allow R1: table cells are labels, not prose -->

| Condition | Gate | Result |
|---|---|---|
| the pilot kappa is below 0.60 | `scripts/gate2a_calibration.py` | exit 2, gate `FAIL` |
| the identified set does not match the fetched set | `scripts/fetch_pubmed_complete.py` | exit 2 |
| a PRISMA stage name is unknown | `scripts/generate_prisma_flow.py` | exit 2 |
| a summary-of-findings row has no certainty | `scripts/sof_table.py` | exit 2 |
| a gate has only one exercised path | `scripts/check_selftest_coverage.py` | exit 2 |

## Routing

- For statistical pooling, use `meta-analysis-forge`.
- For an umbrella review or a second-order meta-analysis, use `umbrella-review-skeptic`.
- For ML-assisted screening or extraction, use `meta-ml-screener`.
- For an environmental, ecological, biomedical, or life-science review, use `environment-life-review-forge`.

## Guardrails

- Do not invent included studies.
- Do not invent search results.
- Do not invent effect sizes.
- Do not recommend statistical pooling when the constructs or the estimands differ.

- Do not let ML replace a final inclusion decision without a protocol justification.
- Do not write a conclusion before the protocol, the eligibility criteria, and the appraisal are clear.
- Do not present PRISMA counts as final until the search, the deduplication, and the screening logs support them.

## What This Does Not Do

This skill does not fit a statistical model. Use `meta-analysis-forge` for the effect-size plan, the model, and the diagnostics. This skill does not appraise a body of existing reviews. Use `umbrella-review-skeptic` for the overlap matrix and the review-level decision. This skill does not run a learned screen. Use `meta-ml-screener` for the active-learning loop and the screening log.

This skill does not replace a librarian, a statistician, or a clinical expert. The named gates check internal consistency. The gates do not decide the scientific merit of a review.

## Rubric Coverage

Each row maps one rubric item to the section that implements it. The rubric lives in `eval.md`.

<!-- ste-allow R1: table cells are labels, not prose -->

| Rubric item | Implemented in |
|---|---|
| E1 question and eligibility criteria | Intake; Workflow steps 1 and 2 |
| E2 search completeness and reproducibility | Workflow step 3; Failure Modes |
| E3 screening calibration and disclosure | Decision Tables; Failure Modes |
| E4 exclusion reasons and ledger match | Workflow step 4; Failure Modes |
| E5 extraction fields and coding rules | Workflow step 5; Load Map |
| E6 synthesis type and poolability | Core Principle; Decision Tables |

<!-- ste-allow R1: table cells are labels, not prose -->

| Rubric item | Implemented in |
|---|---|
| E7 risk of bias and certainty | Workflow steps 7 and 8; Load Map |
| E8 PRISMA count reconciliation | Output Modes; Failure Modes |
| E9 number provenance | Failure Modes; Load Map |
| E10 citation and retraction verification | Load Map; Failure Modes |
| E11 gap reported as a gap | Preflight and Dependencies; Failure Modes |
| E12 reproducibility artifacts | Workflow step 9; Output Modes |
