# eval.md — grade a first-order meta-analysis

Grade the design and the run against the eleven rubric items below. Each item names the
artifact it reads, the gate that decides it, and the failure it catches.

The engine's numbers are measured, not asserted. `scripts/golden_tests.R` runs 22 checks
against `metafor` and against closed-form arithmetic computed in base R: 12 checks on
`dat.bcg` (13 studies, REML), 4 on `dat.normand1999` (9 studies), 1 on the difference
between the DL and the REML tau^2 estimators, and 5 refusal checks. Run it before you
quote a number from the engine:

```bash
Rscript scripts/golden_tests.R        # 22 passed, 0 failed
```

---

## Hard errors

A run with a FAIL on M2, M9, or M10 must not ship until the defect is fixed.

### M1. Effect-size family

The effect family must be named before any model runs: a standardised mean difference
(SMD), a ratio measure (OR, RR, HR), a difference measure (RD, MD), a correlation, or a
log response ratio. The coding sheet must carry the metric in every row.

**Gate:** `scripts/validate_coding_sheet.py`. A mixed effect metric is a finding about
the sheet, exit 1.

### M2. Source anchor and original value

Every effect must trace to a source anchor: the table, the figure, or the page it came
from. A conversion must preserve the original reported value beside the converted one.

**Fails when:** a converted value replaces the reported value with no record of the
original. This is a hard error.

### M3. Dependence

Multiple outcomes, time points, samples, or models from one study are dependent. Name
each dependence and the method that handles it: one effect per study, a multilevel model,
a shared-control covariance matrix, or robust variance estimation (RVE).

**Fails when:** 40 effects from 12 studies enter one fixed-effect pool as if all 40 were
independent.

### M4. Model choice

State the model and the reason: fixed effect, random effects, multilevel, RVE, Bayesian,
or narrative synthesis. State the tau^2 estimator.

**Gate:** `scripts/cochrane_meta.R`, which accepts `--tau2` and reports the chosen model.
`references/poolability-and-model-choice.md` holds the decision rules.

### M5. Heterogeneity reporting

Report tau^2, I^2, Q, and a prediction interval. Report I^2 never alone.

**Gate:** `scripts/cochrane_meta.R`. When QE is at or below its degrees of freedom, the
quantity is not estimable and the engine reports "not estimable (QE <= df)". It must not
print 0.0%, because that reads as a claim about the literature.

### M6. Publication-bias diagnostics

A funnel plot or a meta-regression needs at least 10 studies. Below that count, report the
diagnostic as not interpretable rather than as a negative result.

**Gate:** `scripts/cochrane_meta.R` enforces the Handbook's k of 10 and states it in the
report. `scripts/forest_funnel.R` writes the funnel plot only above that count.

### M7. Sensitivity checks

Run at least one check that could change the conclusion: a leave-one-out pass, an
influential-case check, a tau^2 estimator swap, or a high-risk-of-bias exclusion.

**Fails when:** the section reports one model and no check.

### M8. Certainty and interpretation limits

State what the pool does not support. A high pooled N is not evidence quality. A
meta-regression coefficient is not a causal effect unless the design supports it.

### M9. Number provenance

Every number in the report must come from a fitted model or from a computed artifact. This
is a hard error.

**Gate:** the engine writes `results.json` and `summary.txt`; the review-level provenance
gate (`../evidence-synthesis-forge/scripts/numbers_provenance.py`, listed in
`evidence-synthesis-forge/eval.md`) checks the draft against those artifacts. An
untraceable number exits 2.

### M10. Refusals

An unusable row must be refused, not silently dropped. The engine counts the supplied rows
and the usable rows, names every row it cannot use, and does not write a pooled estimate
over a subset. This is a hard error.

**Gate:** `scripts/cochrane_meta.R`. A blank effect size and a standard error at or below
zero exit 3; fewer than two usable effects exit 1; an unparseable sheet exits 4.

**Fails when:** a pooled estimate is written while rows were dropped.

### M11. Reproducibility package

The package must hold the coding sheet, the script, the tau^2 estimator, the package
versions, and the session information. For a mega-analysis, it must also hold the dataset
inventory and the harmonization ledger.

**Gate:** `scripts/cochrane_meta.R` writes `sessionInfo.txt`.

---

## Gate inventory

Each row names the gate script, the decision it makes, its exit codes, and the fixture
that exercises each path in `../evidence-synthesis-forge/scripts/selftest.sh`. A fixture
that does not exist is stated as missing, never guessed.

| Gate script | Decides | Exit codes | Pass fixture | Fail fixture |
|---|---|---|---|---|
| `scripts/golden_tests.R` | the engine equals `metafor` and closed-form arithmetic | 0 all 22 checks pass; non-zero on a failed check | selftest section 1 runs it and reads the PASS count | none in the suite: the fail path needs a mutated engine, so it is not exercised offline |
| `scripts/cochrane_meta.R` | the pooled estimate, the heterogeneity, and the refusals | 0 fit; 1 refusal (mixed metrics, or fewer than 2 usable effects); 3 supplied rows do not match usable rows; 4 unparseable input | a 5-study spread sheet gives 0; `--rve` and `--moderator` results are reported | a mixed-metric sheet gives 1; `--allow-mixed-metrics` gives 0 as the logged opt-out; a partly blank sheet gives 3 |
| `scripts/run_meta_analysis.R` | the minimal reproducible run | 0 fit; 3 a partly unusable sheet; 4 an unparseable sheet | a k=2 sheet gives 0; a spread sheet gives 0 | a binary-junk sheet gives 4 |
| `scripts/validate_coding_sheet.py` | the sheet structure and the pre-pooling conditions | 0 pass; 1 a finding about the sheet; 3 `insufficient_evidence`; 4 `insufficient_input` | a valid sheet gives 0 | a blank effect size gives 3; `se <= 0` gives 3; a missing file gives 4 |
| `scripts/rob_figure.R` | the traffic-light figure and the summary figure are written, or the failure is loud | 0 both figures written; 1 a requested figure cannot be written | a valid RoB sheet gives 0 and writes both PDFs | a malformed RoB sheet gives 1 with no false success |
| `scripts/validate_rob_fallback.R` | the built-in traffic light matches robvis cell for cell | 0 match; 1 mismatch | the default run gives 0 | `--mutate` gives 1 |
| `scripts/forest_funnel.R` | the forest plot and the funnel plot | 0 written; 4 a missing or unreadable input; 1 a missing required column | none in the suite | none in the suite: the input-condition path is not exercised |
| `scripts/effect_size_helpers.R` | the mechanical conversions | no CLI: each helper calls `stop()` on invalid input | none in the suite | none in the suite: the helpers are sourced, not run |
| `scripts/install_r_packages.R` | the R environment holds the required packages | 0 after the install attempt | none in the suite | none in the suite: it is environment setup |

The golden tests also pin the measured behaviour of the engine: the raw-counts path equals
the precomputed path, the fixed-effect closed form equals `metafor`, the I^2 identity
holds, the prediction interval is wider than the confidence interval, and the DL and REML
tau^2 estimators disagree on `dat.bcg` as the theory predicts.

---

## Reporting

| Rubric item | Result | Note |
|---|---|---|
| M1 effect-size family | PASS/FAIL | |
| M2 source anchor and original value | PASS/FAIL | |
| M3 dependence | PASS/FAIL | |
| M4 model choice | PASS/FAIL | |
| M5 heterogeneity reporting | PASS/FAIL | |
| M6 publication-bias diagnostics | PASS/FAIL/NA | |
| M7 sensitivity checks | PASS/FAIL | |
| M8 certainty and limits | PASS/FAIL | |
| M9 number provenance | PASS/FAIL | |
| M10 refusals | PASS/FAIL | |
| M11 reproducibility package | PASS/FAIL | |

These checks bound what the run supports. They are not a clearance: they cover the coded
sheet and the fitted model, and they do not cover whether the question permits a pool.
