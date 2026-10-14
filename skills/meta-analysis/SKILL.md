---
name: meta-analysis
description: "Decides whether a set of studies is poolable, then runs the quantitative synthesis and reports its uncertainty. Use when the user asks to pool studies, choose an effect size, pick fixed- or random-effects, measure heterogeneity, run meta-regression, check publication bias, or read a forest or funnel plot. It routes the statistical work to meta-analysis-forge and refuses to combine unlike estimands; it does not run the search, screening, or risk-of-bias stages, which belong to sysreview."
allowed-tools: Read Write Edit Bash
license: MIT
metadata:
  version: "1.1"
  orchestrates: "meta-analysis-forge, statistical-analysis, umbrella-review-skeptic, sysreview"
---

# /meta-analysis — Quantitative Synthesis Entry Point

A systematic review is a reproducible synthesis process (PRISMA). A meta-analysis is a
statistical pooling step on top of that process. Pool the studies only when they are
homogeneous enough. Many systematic reviews should not pool at all.

## When this fires

The request names pooling or a pooling diagnostic. The usual binary effect measures are the odds ratio (OR) and the risk ratio (RR). Watch for these phrases:

- "meta-analysis", "pool the studies", or "combine effect sizes".
- "forest plot" or "funnel plot".
- "I² too high" or "fixed- or random-effects".
- "Hedges g", "Cohen d", an OR, or an RR.
- "publication bias".
- An explicit `/meta-analysis`.

## Routing contract

The alias `/meta-analysis` is the quantitative-synthesis entry point, not the whole review.
This skill owns the poolability decision and the effect-size plan, and it routes the rest.

```
ROUTE extract-effect-size,harmonize,convert-effect,standard-error -> meta-analysis-forge
ROUTE fixed-effect,random-effects,multilevel -> meta-analysis-forge
ROUTE heterogeneity,prediction-interval,tau-squared -> meta-analysis-forge
ROUTE meta-regression,subgroup,moderator -> meta-analysis-forge
ROUTE publication-bias,funnel,egger,trim-and-fill,p-curve -> meta-analysis-forge
ROUTE forest-plot,funnel-plot,report-table -> meta-analysis-forge
ROUTE poolability,should-we-pool,is-it-poolable -> self
ROUTE systematic-review,protocol,search-strategy,screening -> sysreview
ROUTE risk-of-bias,grade,certainty -> sysreview
ROUTE umbrella,review-of-reviews,second-order -> umbrella-review-skeptic
FALLBACK no-route -> stop and ask the user; record an input gap (exit 4); never guess a target
```

`meta-analysis-forge` is the statistics owner. `sysreview` is the process owner.
`umbrella-review-skeptic` owns a review of reviews. This skill owns the poolability decision
and the effect-size plan.

When a target skill is unavailable, stop and report the missing dependency as an input gap
(exit 4). Do not hand-compute a pooled number. Do not invent the missing layer.

## Preflight (run before the first pooled number)

Confirm four things before you pool anything:

1. The coding sheet exists and parses.
2. Every effect size has a metric and a variance.
3. The search log exists and names more than one source.
4. The protocol and the registration exist, or the user accepts their absence.

Run `../evidence-synthesis-forge/scripts/doctor.sh` first. It reports the R engine and the
Python helper versions. A missing dependency is an input gap, not a result.

## Finding the evidence (paper-search MCP)

A review that has not run yet belongs to `sysreview` (stages 3 and 4). Do not pool a
hand-assembled list. Use the `paper-search` MCP to find studies for a pooling question. Use it
also to learn whether a body of evidence exists at all:

- `plan_search_query(query)` returns query variants, MeSH expansion, and topic-based source
  routing. Run it before a broad sweep.
- `search_papers(query, sources="auto", expand=True)` applies that routing. Never use
  `sources="all"`, because it burns paid quota.
- `search_clinicaltrials`, `search_ictrp`, and `search_ctis` query trial registries. A
  registered trial that was never published is invisible to every bibliographic database.

- `search_biorxiv` and `search_medrxiv` query preprints, which may hold the only record of
  recent work.
- `get_related_articles(pmid)` expands from a known seed.
- `check_retraction(doi)` checks a DOI before a citation enters the draft.
- Terminated or results-free registrations are where publication bias hides.

A PubMed-only search is a single-source search. It cannot see registries, preprints, or
non-MEDLINE journals. A meta-analysis built on it inherits that blind spot. Record every
source searched and its hit count in `search_log.csv`.
`../evidence-synthesis-forge/scripts/prisma_s_appendix.py` fails a log that omits either one.

## Step 0 — the poolability gate (do this first, always)

Read `references/poolability-and-model-choice.md`. Answer these questions in order:

1. Is the search and screening systematic and reproducible? If not, run `sysreview` to build
   that layer first.
2. Are the studies conceptually homogeneous enough, and can each yield the same effect-size
   family with a variance? If not, narrate the result (SWiM) and stop.

3. Are there enough studies, and is the quality acceptable? There is no hard floor. Be
   explicit and cautious at very small k.
4. Is the review pre-registered (PROSPERO)?
5. Is the team ready to report heterogeneity, publication bias, and risk of bias?

If any answer blocks pooling, deliver an honest narrative synthesis plan instead.

## The pooling pipeline

| Step | Work | Owner |
|---|---|---|
| 1 | Effect-size family and conversion | `../meta-analysis-forge/references/effect-sizes.md`. |
| 2 | Dependence between effects | `meta-analysis-forge`. |
| 3 | Model choice | `../meta-analysis-forge/references/synthesis-models.md`. |
| 4 | Heterogeneity | `meta-analysis-forge`. |

| Step | Work | Owner |
|---|---|---|
| 5 | Small-study effects and bias | `meta-analysis-forge`. |
| 6 | Risk of bias and certainty | `sysreview` (stage 8). |
| 7 | Sensitivity checks | `meta-analysis-forge`. |
| 8 | Figures and report | `../meta-analysis-forge/scripts/run_meta_analysis.R`. |

Step 6 is an interface note. The appraisal belongs to `sysreview` (stage 8), and it runs before
synthesis.

## Decision rules (defaults)

Two defaults matter. Prefer restricted maximum likelihood (REML) for τ² and the Hartung-Knapp-Sidik-Jonkman (HKSJ) adjustment at small k.

- Default to random-effects when the true between-study effects differ, which is the usual
  case. Cochrane gives no universal recommendation (Handbook §10.10.4).
- Use fixed-effect only when the studies plausibly estimate one effect.
- Never choose the model by an I²-significance rule. Model choice follows conceptual
  homogeneity. A heterogeneity test has low power at small k.

- Report τ² and a prediction interval, not I² and a pooled CI alone. The Handbook (§10.10.2)
  warns that I² thresholds can mislead.
- Prefer REML for τ², and state the estimator used.

- Use the HKSJ adjustment at small k, which means fewer than 5 studies.
- Funnel and Egger tests need enough studies. At very small k they mislead. Report that
  limitation instead of a false reassurance.

## Reporting

Align every number with PRISMA 2020. Use item 12 for effect measures and item 13 for
synthesis methods. Use items 20b-20d for results, heterogeneity, and sensitivity. Use item 21
for reporting biases and item 22 for certainty. The reporting reference is
`../evidence-synthesis-forge/references/prisma-2020-manuscript-reporting.md`.
PRISMA 2020 means the Preferred Reporting Items for Systematic Reviews and Meta-Analyses.

## Quality gates (must pass before a pooled number is reported)

Every gate fails loudly. None is optional.

```
GATE coding-sheet | script: ../meta-analysis-forge/scripts/validate_coding_sheet.py | pass-exit: 0 | fail-exit: 3
GATE engine | script: ../meta-analysis-forge/scripts/cochrane_meta.R | pass-exit: 0 | fail-exit: 1
GATE accuracy | script: ../meta-analysis-forge/scripts/golden_tests.R | pass-exit: 0 | fail-exit: declared
GATE report | script: ../meta-analysis-forge/scripts/run_meta_analysis.R | pass-exit: 0 | fail-exit: 4
GATE numeric-provenance | script: ../evidence-synthesis-forge/scripts/numbers_provenance.py | pass-exit: 0 | fail-exit: 2
GATE summary-of-findings | script: ../evidence-synthesis-forge/scripts/sof_table.py | pass-exit: 0 | fail-exit: 2
GATE search-reporting | script: ../evidence-synthesis-forge/scripts/prisma_s_appendix.py | pass-exit: 0 | fail-exit: 2
GATE toolchain | script: ../evidence-synthesis-forge/scripts/doctor.sh | pass-exit: 0 | fail-exit: declared
```

Run the routing and gate fixtures with `scripts/selftest.sh`. It reads the block above, so a
new gate without a pass and a fail fixture fails the self-test.

## Load

- `references/poolability-and-model-choice.md` — the gate, the type distinctions, and the
  fixed-versus-random decision rules. This file is mandatory before pooling.
- `../meta-analysis-forge/references/effect-sizes.md` — effect metrics, conversion, variance.
- `../meta-analysis-forge/references/synthesis-models.md` — model choice and diagnostics.
- `../meta-analysis-forge/references/meta-analysis-quality-gates.md` — pre-pooling checks.
- `../meta-analysis-forge/references/network-meta-analysis.md` — three or more treatments.

- `../meta-analysis-forge/references/ml-moderator-analysis.md` — exploratory machine learning (ML) moderators.
- `../meta-analysis-forge/references/ipd-and-mega-analysis.md` — individual participant data.
- `../meta-analysis-forge/scripts/validate_coding_sheet.py` — validate before pooling.
- `../meta-analysis-forge/scripts/run_meta_analysis.R` — run only after the gates pass.

## Cochrane-standard engine (validated)

Run `../evidence-synthesis-forge/scripts/doctor.sh` first. It verifies the R engine and the
Python helpers, and it prints their versions.

- `../meta-analysis-forge/scripts/cochrane_meta.R` — the engine. It runs fixed- and
  random-effects models, τ² estimators, HKSJ intervals, and cluster-robust standard errors.
- It also runs subgroup analysis, meta-regression, Egger and Begg tests, trim-and-fill, and a
  prediction interval. It captures `sessionInfo()`. Every number comes from the engine.

- `../meta-analysis-forge/scripts/golden_tests.R` — the accuracy proof. It reproduces
  metafor's canonical datasets (`dat.bcg`, `dat.normand1999`).
- It checks the engine against a direct `rma()` fit, against closed-form values computed
  without metafor, and against raw-input versus precomputed-input equivalence.
- Run it after every engine change.

- `../meta-analysis-forge/scripts/forest_funnel.R` — a forest plot and a contour-enhanced
  funnel plot, with captions that state the model and the heterogeneity.
- `../meta-analysis-forge/scripts/rob_figure.R` — a risk-of-bias traffic-light and summary
  figure (`robvis`).
- `../evidence-synthesis-forge/references/cochrane-handbook-map.md` — the chapter 6, 10, 11,
  13, and 14 decision rules, including the ten-study rules for funnel and meta-regression.

- `../evidence-synthesis-forge/references/grade-certainty.md` — certainty, and the Grading of Recommendations Assessment, Development and Evaluation (GRADE) structure.
- `../evidence-synthesis-forge/references/rob-tool-selection.md` — RoB 2 versus ROBINS-I.
- `../evidence-synthesis-forge/references/cochrane-figures-tables.md` — Handbook III.S1 rules.

- `../evidence-synthesis-forge/scripts/sof_table.py` — the summary-of-findings generator. It
  validates certainty and computes absolute effects from a baseline risk.
- `../evidence-synthesis-forge/scripts/numbers_provenance.py` — the gate that fails when any
  number in the write-up has no computed artifact behind it.

### Handbook rules the engine enforces (not optional)

- Report τ² and a prediction interval. Never report I² alone.
- Choose the model by conceptual homogeneity. Never use an I²-significance rule.
- Use funnel plots, Egger tests, and meta-regression only at k ≥ 10. The engine warns below
  that count.

- Report funnel asymmetry as a signal, not as proof of publication bias.
- State the τ² estimator and the software versions.

## Decision table

| Request shape | Route |
|---|---|
| The estimates need extraction or conversion | meta-analysis-forge. |
| The studies need a search and screening first | sysreview. |
| The request is a review of reviews | umbrella-review-skeptic. |
| The studies are not poolable | Narrate the result (SWiM) and stop. |

## Worked examples

### Example 1 — a poolable set

The request: "pool the effect sizes for these eight trials". The search and screening already
exist. The estimand is one standardised mean difference family. Route the statistics to
`meta-analysis-forge`. Report τ² and a prediction interval beside the pooled estimate.

### Example 2 — a request that must not pool

The request: "combine these studies, but some report odds ratios and some report mean
differences." The estimands differ. Do not pool. Narrate the result (SWiM), and state why.

### Example 3 — an unavailable target

`meta-analysis-forge` is not installed. Stop. Report the missing dependency and record an
input gap (exit 4). Do not compute a pooled number by hand.

## Failure modes and exit codes

| Condition | Result |
|---|---|
| The coding sheet has a blank effect size | `validate_coding_sheet.py` exits `3`. |
| The sheet mixes effect metrics | `cochrane_meta.R` exits `1`, unless `--allow-mixed-metrics` is set. |
| The sheet is unreadable | `validate_coding_sheet.py` exits `4`. |
| A draft number has no artifact | `numbers_provenance.py` exits `2`. |
| A search log lacks a date or a hit count | `prisma_s_appendix.py` exits `2`. |
| A source was never reached | `prisma_s_appendix.py` exits `3`.

## What this does not do

- It does not run the search or the screening. `sysreview` owns those stages.
- It does not appraise risk of bias. `sysreview` records the appraisal at stage 8.
- It does not invent an effect size, a variance, or a study.

- It does not combine unlike estimands to produce a single number.
- It does not replace the statistical engine in `meta-analysis-forge`.

## Rubric coverage

Every item of `eval.md` maps to the section that implements it.

| Check | Section |
|---|---|
| MR1 alias meaning | Routing contract. |
| MR2 request routing | Routing contract and Decision table. |
| MR3 target unavailable | Routing contract and Worked examples. |
| MR4 poolability first | Step 0 — the poolability gate (do this first, always). |
| MR5 no I²-significance rule | Decision rules (defaults). |

| Check | Section |
|---|---|
| MR6 heterogeneity reported | Decision rules (defaults) and Reporting. |
| MR7 no fabricated number | Quality gates and Failure modes and exit codes. |
| MR8 exit-code honesty | Failure modes and exit codes. |
| MR9 no duplicated analysis logic | What this does not do and The pooling pipeline. |

## Guardrails

- Do not pool incompatible outcomes or estimands. Do not convert and combine in silence.
- Do not treat several effects from one study as independent. Handle the dependence.
- Never fabricate, round away, or approximate a computed number. Compute it.

- Do not report a pooled estimate without heterogeneity. Do not overclaim from a
  meta-regression with few studies.
- Do not present an ML-discovered moderator as confirmatory.

## Provenance

Merges methodology from maydengximin-sketch/meta-analysis-systematic-review-skill (MIT), and
from the local `meta-analysis-forge` (MIT). See `NOTICE.md`.
