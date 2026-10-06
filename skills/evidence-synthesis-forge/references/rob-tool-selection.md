# Risk-of-bias tool selection

Paraphrase of the Cochrane Handbook v6.5 (ch. 8, 25) and the tool publications. **RoB 2,
ROBINS-I, QUADAS and PROBAST carry no open licence** — this file describes their *structure
in our own words* and cites the source; it never reproduces the instruments. Consult the
official tools before scoring.

## Pick the tool by study design — never by convenience

| Design | Tool | Domains (paraphrased) |
|---|---|---|
| Randomised trial | **RoB 2** | randomisation process; deviations from intended interventions; missing outcome data; measurement of the outcome; selection of the reported result; + overall. Two target questions: **effect of assignment** vs **effect of adherence**. |
| Cluster / cross-over RCT | **RoB 2** variant / cluster RoB 2 | as above, adapted for clustering/carry-over |
| Non-randomised, **intervention** effect | **ROBINS-I** | confounding; selection of participants; classification of interventions; deviations from intended interventions; missing data; measurement of outcomes; selection of the reported result |
| Non-randomised, **exposure** (environmental/occupational) | **ROBINS-E** | confounding; measurement of the exposure; selection of participants; post-exposure interventions; missing data; measurement of the outcome; selection of the reported result |
| Bias due to **missing results** (reporting bias) | **ROB-ME** | assessed per *synthesis*, not per study |
| Diagnostic test accuracy | **QUADAS-2** / **QUADAS-3** | patient selection; index test; reference standard; flow and timing |
| Prediction model | **PROBAST** / **PROBAST+AI** | participants; predictors; outcome; analysis |
| Cohort / case-control (legacy) | **NOS** | selection; comparability; outcome/exposure |
| Reviews of reviews | **AMSTAR 2** (16 items, 7 critical) / **ROBIS** | ROBIS: study eligibility criteria; identification & selection; data collection & appraisal; synthesis & findings |
| Animal studies | **SYRCLE** | randomisation, blinding, etc. |

## The rule amateurs break

**Do not apply RoB 2 to a non-randomised study.** RoB 2's domains (randomisation process,
deviations from intended intervention) do not map onto an observational cohort; use
ROBINS-I/E. A mismatch here invalidates the entire appraisal column.

## Assessment mechanics

- Judge each domain **Low / Some concerns / High** (RoB 2, ROBINS-I/E) — and derive the
  **overall** judgement by the tool's algorithm, not by averaging.
- Assess **independently by two people**; record disagreements and how they were resolved.
- Base judgements on **outcome-level** assessment (RoB 2 is outcome-specific), not study-level.
- Feed the results into the synthesis (sensitivity analysis, subgroup by risk of bias) and
  into **GRADE** (risk-of-bias is one of the five downgrade domains).

## Figures

`robvis` (MIT) renders both required figures from the assessment matrix:
- **`rob_traffic_light()`** — per-study, per-domain traffic-light plot.
- **`rob_summary()`** — weighted bar plot of domain judgements.
- Palettes: `"cochrane"` or `"colourblind"`; supports `ROB2`, `ROB2-Cluster`, `ROBINS-I`,
  `ROBINS-E`, `QUADAS-2`, `QUIPS`, `Generic`.

See `cochrane-figures-tables.md` for output specs and `scripts/rob_figure.R` for the driver.

## MISMATCH WARNING (a common, checkable defect)

A manuscript that reports "we assessed risk of bias using the Cochrane Risk of Bias tool"
without naming the version and the design is **incomplete** — RoB 2 vs ROBINS-I is a
different instrument with a different domain set. The reporting layer flags this.
