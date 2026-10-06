---
name: meta-analysis
description: "Meta-analysis entry point (alias /meta-analysis). Use when the user asks to pool studies, run or design a meta-analysis, choose an effect size (Cohen's d, Hedges' g, r, OR, RR), pick fixed- vs random-effects, assess heterogeneity (Q, I², τ², prediction intervals), run subgroup or meta-regression, check publication bias (funnel, Egger, trim-and-fill, p-curve), rate certainty (GRADE), draw a forest/funnel plot, or decide whether studies are homogeneous enough to combine. Routes to meta-analysis-forge (statistics and R scripts), statistical-analysis, and the statistical-review leg of the sysreview skill. Starts with a poolability gate: it will refuse to combine incompatible estimands and reports why. Never fabricates effect sizes and never selects the model by an I²-significance rule."
allowed-tools: Read Write Edit Bash
license: MIT
metadata:
  version: "1.0"
  orchestrates: "meta-analysis-forge, statistical-analysis, umbrella-review-skeptic, sysreview"
---

# /meta-analysis — Quantitative Synthesis Entry Point

Systematic review = a reproducible synthesis process (PRISMA). Meta-analysis = statistical
pooling **on top of** that process, *when the studies are homogeneous enough*. Not every
systematic review can — or should — be pooled.

## When this fires

"meta-analysis", "pool the studies", "combine effect sizes", "forest plot", "funnel plot",
"I² too high", "fixed- or random-effects", "Hedges g / Cohen d / OR / RR", "publication bias",
or an explicit `/meta-analysis`.

## Finding the evidence (paper-search MCP)

If a review has not been run yet, the search layer belongs to `sysreview` (stage 3–4) — do not
start pooling a hand-assembled list. But when you need to locate studies *for* a pooling question,
or to check whether a body of evidence exists at all, use the **`paper-search` MCP** directly:

- `plan_search_query(query)` — query variants, MeSH expansion, and topic-based source routing.
  Run it before a broad sweep; it tells you which sources are likely to answer the question.
- `search_papers(query, sources="auto", expand=True)` — applies that routing. **Never use
  `sources="all"`**: it burns paid quota for no gain.
- `search_clinicaltrials` / `search_ictrp` / `search_ctis` — **trial registries**. These are not
  optional for a meta-analysis: a registered trial that was never published is invisible to every
  bibliographic database, and terminated or results-free registrations are exactly where
  publication bias hides.
- `search_biorxiv` / `search_medrxiv` — preprints, which may be the only record of recent work.
- `get_related_articles(pmid)` — expand from a known seed.
- `check_retraction(doi)` — before citing anything.

A PubMed-only search is a **single-source** search. It cannot see registries, preprints, or
non-MEDLINE journals, and a meta-analysis built on it inherits that blind spot. Record every source
searched and its hit count (`search_log.csv`); `prisma_s_appendix.py` fails a search log that omits
either.

## Step 0 — the poolability gate (do this first, always)

Read `references/poolability-and-model-choice.md`. Answer, in order:

1. Is the search/screening systematic and reproducible? If not → it is not a meta-analysis
   yet; run `sysreview` to build the systematic layer first.
2. Are the studies conceptually **homogeneous enough** — comparable PICO, design, and
   measurement — and can each yield the **same effect-size family** with a variance?
   If not → narrate (SWiM), do not pool. Say so and stop.
3. Are there enough studies and is quality acceptable? (No hard floor, but be explicit and
   cautious at very small k.)
4. Is the review pre-registered (PROSPERO)?
5. Is the team ready to report **heterogeneity + publication bias + risk of bias**?

If any answer blocks pooling, deliver an honest narrative/structured synthesis plan instead.

## The pooling pipeline

| Step | What | Owner |
|---|---|---|
| 1 | Effect-size family + conversions, direction unification, variances | `../meta-analysis-forge/references/effect-sizes.md`, `../meta-analysis-forge/scripts/effect_size_helpers.R` |
| 2 | Dependence handling (multiple outcomes/timepoints/samples per study) | `meta-analysis-forge` |
| 3 | Model: fixed / random / multilevel / RVE / Bayesian | `../meta-analysis-forge/references/synthesis-models.md` |
| 4 | Heterogeneity: Q, I², τ², **prediction interval**, subgroup, meta-regression | `meta-analysis-forge` |
| 5 | Small-study effects / publication bias (funnel, Egger, trim-and-fill, p-curve) | `meta-analysis-forge` |
| 6 | Risk of bias + certainty (RoB 2 / ROBINS-I / NOS / GRADE) | `sysreview` (stage 8) |
| 7 | Sensitivity checks | `meta-analysis-forge` |
| 8 | Forest / funnel plots + reproducible report | `../meta-analysis-forge/scripts/run_meta_analysis.R` |

## Decision rules (defaults)

- **Default to random-effects** when true between-study effects are expected to differ — the
  usual case. Cochrane does **not** give a universal recommendation (§10.10.4); fixed-effect
  only when studies plausibly estimate one effect.
- **Never choose the model by "is I² significant".** Model choice follows whether the
  studies are *conceptually* homogeneous; the significance of a heterogeneity test is a
  poor proxy and its power depends on k.
- **Always report τ² and a prediction interval**, not just I² and a pooled CI. The Handbook
  (§10.10.2) warns that I² *"thresholds ... can be misleading"*; I² is not an absolute measure
  of heterogeneity.
- **τ² estimator:** prefer REML; state which estimator was used.
- **Small k (< 5):** use the Hartung-Knapp-Sidik-Jonkman adjustment for a more robust CI.
- **Publication-bias tests need enough studies** (funnel/Egger are unreliable at very small
  k) — report the limitation rather than a false reassurance.

## Reporting

Align every number with PRISMA 2020 items 12 (effect measures), 13 (synthesis methods),
20b–20d (results, heterogeneity, sensitivity), 21 (reporting biases), and 22 (certainty).
See `../evidence-synthesis-forge/references/prisma-2020-manuscript-reporting.md`.

## Load

- `references/poolability-and-model-choice.md` — the gate, the type distinctions, and the
  fixed-vs-random decision rules (mandatory before pooling).
- `../meta-analysis-forge/references/effect-sizes.md` — effect metrics, conversion, variance.
- `../meta-analysis-forge/references/synthesis-models.md` — model choice and diagnostics.
- `../meta-analysis-forge/references/meta-analysis-quality-gates.md` — pre-pooling checks.
- `../meta-analysis-forge/references/network-meta-analysis.md` — 3+ treatment networks.
- `../meta-analysis-forge/references/ipd-and-mega-analysis.md` — individual participant data.
- `../meta-analysis-forge/references/ml-moderator-analysis.md` — exploratory ML moderators
  (complements, never replaces, pre-specified meta-regression).
- `../meta-analysis-forge/scripts/validate_coding_sheet.py` — validate before pooling.
- `../meta-analysis-forge/scripts/run_meta_analysis.R` — run only after gates pass.

## Cochrane-standard engine (validated)

Run `../evidence-synthesis-forge/scripts/doctor.sh` first — it verifies the R engine and
the Python helpers and prints their versions.

- `../meta-analysis-forge/scripts/cochrane_meta.R` — the engine. Fixed- and random-effects
  models, tau^2 estimators (REML/DL/PM), **HKSJ**, cluster-robust (CR2) SEs, subgroup and
  meta-regression, Egger/Begg/trim-and-fill, prediction interval, `sessionInfo()` captured.
  Every number is computed; none is typed.
- `../meta-analysis-forge/scripts/golden_tests.R` — **the proof of accuracy.** Reproduces
  metafor's canonical datasets (`dat.bcg`, `dat.normand1999`) and checks the engine against
  (A) a direct `rma()` fit, (B) closed-form maths computed without metafor, and (C) raw-input
  vs precomputed-input equivalence. Run it after any change to the engine.
- `../meta-analysis-forge/scripts/forest_funnel.R` — forest + contour-enhanced funnel with
  self-contained captions stating the model and heterogeneity.
- `../meta-analysis-forge/scripts/rob_figure.R` — RoB traffic-light + summary (`robvis`).
- `../evidence-synthesis-forge/references/cochrane-handbook-map.md` — the ch.6/10/11/13/14
  decision rules (incl. the >=10-studies rules for funnel and meta-regression).
- `../evidence-synthesis-forge/references/grade-certainty.md` — GRADE certainty + SoF structure.
- `../evidence-synthesis-forge/references/rob-tool-selection.md` — RoB 2 vs ROBINS-I/E vs ROB-ME.
- `../evidence-synthesis-forge/references/cochrane-figures-tables.md` — Handbook III.S1 figure rules.
- `../evidence-synthesis-forge/scripts/sof_table.py` — Summary-of-findings generator; validates
  certainty and computes absolute effects from a baseline risk.
- `../evidence-synthesis-forge/scripts/numbers_provenance.py` — the gate that fails if any
  number in the write-up is not traceable to a computed artifact.

### Handbook rules the engine enforces (not optional)

- Report **tau^2 and a prediction interval**, never I^2 alone.
- Choose the model by *conceptual* homogeneity, never by an I^2-significance rule.
- Funnel/Egger/meta-regression only at **k >= 10**; the engine warns below that.
- Funnel asymmetry is reported as **not proof** of publication bias.

## Guardrails


- Do not pool incompatible outcomes/estimands; do not silently convert and combine.
- Do not treat multiple effects from one study as independent (handle dependence).
- Never fabricate, round-away, or "approximately" a computed number — compute it.
- Do not report a pooled estimate without heterogeneity, and do not overclaim from
  meta-regression with few studies.
- Do not let ML-discovered moderators be presented as confirmatory.

## Provenance

Merges methodology from maydengximin-sketch/meta-analysis-systematic-review-skill (MIT,
poolability + fixed-vs-random decision rules) with the local `meta-analysis-forge`
(MIT). See `NOTICE.md`.

