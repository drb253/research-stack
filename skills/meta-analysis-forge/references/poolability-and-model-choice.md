# Poolability and model choice — should this be a meta-analysis at all?

Adapted from maydengximin-sketch/meta-analysis-systematic-review-skill (MIT),
`references/00-should-you-use-meta-analysis.md` and `06-fixed-vs-random.md`.

> "I read a lot of papers" ≠ a systematic review, and ≠ a meta-analysis. Separate the
> three types first, then decide whether the evidence can and should be pooled.

## 1. The three types

| | Narrative review | Systematic review | Meta-analysis |
|---|---|---|---|
| Search | unsystematic, selective | **systematic, reproducible** (PRISMA) | systematic (as left) |
| Screening | subjective | pre-set eligibility, dual screening | as left |
| Synthesis | qualitative narrative | qualitative/structured, **may pool nothing** | **statistical pooling to a summary effect** |
| Bias control | high risk | low (transparent process) | low + quantitative bias checks |

Systematic review ⊇ meta-analysis. A systematic review without meta-analysis is legitimate
(studies too heterogeneous); a serious meta-analysis must sit on a systematic-review process.

## 2. When pooling is defensible

- **Comparable question/PICO** — population, intervention/exposure, comparator, outcome
  roughly comparable.
- **Extractable, same-family effect size** — each study yields the same metric (d/g/r/OR…)
  with a variance.
- **Enough studies** — pooling 2–3 has limited value (no hard floor, but be cautious).

The **"apples and oranges"** critique: pooling genuinely different studies gives a
meaningless summary. Response: state the level at which the studies are "the same relation",
use random-effects to acknowledge differences, and use subgroups/meta-regression to explain
heterogeneity.

## 3. When NOT to pool (or to be very cautious)

- Highly heterogeneous designs/measurement/populations with no common comparable effect →
  narrative/structured synthesis.
- Too few or too low-quality studies → pooling amplifies bias.
- Outcomes cannot be converted to a common effect size.
- Severe, uncorrectable publication bias → the pooled value may be inflated.

## 4. Naming discipline

Know the family and use the matching reporting guideline: systematic review, meta-analysis,
**scoping review** (maps the field, does not pool), **umbrella review** (review of reviews →
`umbrella-review-skeptic`), rapid review, **meta-synthesis** (qualitative). Do not call a
narrative review a meta-analysis.

## 5. Decision checklist

1. Is my search/screening systematic and reproducible? (No → build the systematic layer first.)
2. Are studies homogeneous enough and can they yield the same effect size? (Yes → poolable.)
3. Enough studies? Acceptable quality?
4. Pre-registered (PROSPERO)? (See the PROSPERO reference.)
5. Ready to report **heterogeneity + publication bias + risk of bias**?

## 6. Fixed-effect vs random-effects

| | Fixed-effect | Random-effects |
|---|---|---|
| Assumption | all studies estimate **one true effect**; differences are sampling error only | each study's true effect **differs**, drawn from a distribution |
| Weighting | inverse-variance (larger studies dominate) | inverse-variance + between-study variance τ² (more balanced) |
| Inference scope | these studies only | a wider population of studies |
| When | studies functionally identical | real between-study heterogeneity (the norm) |

**How to choose**

- **Default random-effects** in social / education / psychology / clinical work.
- Fixed-effect only when you have strong grounds to believe all studies estimate one effect.
- **Never use "I² is not significant → fixed-effect".** Model choice follows whether studies
  are *conceptually* homogeneous; a heterogeneity test's power depends on k.

**Weighting and pooling** — inverse-variance weights (random-effects adds τ²); report the
pooled estimate + 95% CI + z/p. **Random-effects must also report a prediction interval** —
the likely range of a future study's true effect, which conveys heterogeneity better than
the CI.

**τ² estimator** — DerSimonian-Laird (classical, can underestimate), **REML (preferred)**,
Paule-Mandel, etc. State which was used.

**Small k (< 5)** — τ² is unstable and the random-effects CI can be too narrow → use the
**Hartung-Knapp-Sidik-Jonkman** adjustment for a more robust CI.

**Common errors** — choosing the model by I² significance; fixed-effect on heterogeneous data
(false significance); random-effects without a prediction interval; DL without HKSJ at small k.

## Key references

Borenstein et al. (2021) *Introduction to Meta-Analysis* (2nd ed.); Borenstein et al. (2017)
"I² is not an absolute measure of heterogeneity", *Res Synth Methods* 8; IntHout et al. (2016)
"Plea for prediction intervals", *BMJ Open* 6; Higgins et al. (2023) *Cochrane Handbook*.
