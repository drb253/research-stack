# Medical Language, Numbers, and Units

## The hedging ladder

Match the verb to the design, not to your enthusiasm. The `certainty` field in `claims.csv` picks
the rung.

| Rung | Use | Wording |
|---|---|---|
| Causal, randomised | Randomised trial with the outcome as a primary endpoint | "reduced", "improved", "increased survival" — state the comparison and the interval |
| Causal, quasi-experimental | Difference-in-differences, Mendelian randomisation, target-trial emulation | "is likely to reduce", "the analysis estimates a causal effect of" — name the assumption |
| Associational | Cohort, case-control, cross-sectional | "was associated with", "was more common among", "correlated with" |
| Mechanistic | Animal or in vitro | "in mice", "in cell lines", "preclinical data suggest" |
| Hypothesis-generating | Subgroup, post hoc, exploratory | "hypothesis-generating", "requires confirmation in a prospective trial" |
| Absent | Nothing found | "no studies were identified that address", "evidence is lacking" |

Forbidden conversions:

- association -> causation ("associated with" must never become "caused");
- non-significance -> equivalence ("did not differ significantly" is not "were equivalent");
- absence of evidence -> evidence of absence;
- surrogate endpoint -> clinical outcome (a response rate is not survival benefit);
- single study -> established fact ("a trial showed" is not "it is established that");
- exploratory subgroup -> practice-changing signal;
- statistical significance -> clinical importance (always give the effect size and its interval).

## Causal verbs the lint flags

`causes`, `leads to`, `results in`, and similar verbs are flagged as `CAUSAL_CLAIM_WITHOUT_HEDGE`
unless the same sentence contains a hedging marker. That is a prompt, not a prohibition: if the
sentence describes a randomised comparison, add the comparison and the interval rather than a hedge.

## Numbers

- Copy numbers; never recompute a published result. If the paper says 3.4%, write 3.4%.
- Give the denominator for every percentage: "37% (92/249)".
- Pair every effect estimate with its interval and its comparison: "HR 0.49 (95% CI 0.38 to 0.64)
  versus chemotherapy alone".
- Report p values as the source reported them; do not convert `p < 0.001` into `p = 0.0003`, and
  never write `p = 0` (`P_VALUE_REPORTED_AS_ZERO` warns on that).
- Round consistently: effect estimates to two decimals, percentages to one decimal, p values to
  three decimals or a threshold.
- Absolute before relative risk: a 50% relative risk reduction on a 2% baseline is 1 percentage
  point. Give both when the decision depends on it.
- Time is always attached to the outcome: "at 12 months", "median follow-up 10.5 months".
- Do not present a mean without its dispersion, or a median without a range or interquartile range.
- Convert units only when necessary, state the conversion factor, and note when a source uses
  conventional units while you report SI (`MIXED_UNIT_SYSTEMS` is informational).
- Distinguish randomised, analysed, and evaluable populations; mixing them is one of the most common
  review errors.

## Significance language

- Write "statistically significant" only with the test and the comparison nearby.
- Never write "significant" alone when the meaning is "important"; say "clinically important".
- Never write "trend towards significance"; give the estimate and the interval.
- Non-significance with a wide interval is "imprecise", not "no effect".
- Mention multiplicity when a source reports many endpoints without adjustment; do not present an
  unadjusted secondary endpoint as a finding.



## Terminology

| Use | Not |
|---|---|
| INN (generic) drug name: pembrolizumab | Brand name only; if a brand is needed, give it once alongside the generic |
| "randomised controlled trial" | "clinical trial" when the design matters |
| "patients with validated sepsis" | "septic patients" |
| "people with obesity" | "the obese" |
| "participants" for trials, "patients" for clinical cohorts | "subjects" where avoidable |
| "first-line" or "second-line", defined by the clinical setting | "frontline" without definition |
| "device, manufacturer, city, country, version" | "the device" |
| "preprint (not peer reviewed)" | "study" |
| "conference abstract" | "publication" |
| "sensitivity and specificity with 95% CI" | "accuracy" alone |

Define every abbreviation at first use in the abstract, the body, and every table and figure caption
(the lint reports `ABBREVIATION_NOT_DEFINED` for a term used twice without a definition). Follow the
journal's convention for italics of gene names, and keep gene and protein naming consistent with the
species named.

## Structure and readability

- One idea per paragraph; the first sentence states the paragraph's claim.
- Prefer active voice where the actor matters ("the investigators randomised"), passive where the
  object matters.
- Keep sentences under about 40 words (`VERY_LONG_SENTENCE` fires above 55).
- Cut adjectives that add nothing: "very", "extremely", "notably", "highly significant".
- No marketing language: `breakthrough`, `revolutionary`, `cutting-edge`, `miracle`, `game-changing`
  are flagged as `OVERCLAIMING_LANGUAGE`.
- No absolute statements: "always", "never", "in all patients", "guarantees", "conclusively proves"
  are flagged as `ABSOLUTE_LANGUAGE` unless they are quoting a source.
- One term per concept throughout; do not alternate between "therapy", "treatment", and
  "intervention" for the same thing.

## Writing in English as an additional language

The errors reviewers notice most in medical reviews:

- Article use with disease names: "patients with NSCLC", not "patients with the NSCLC".
- "Significantly" needs an explicit comparison: "significantly higher than in the control arm".
- Use "in a dose-dependent manner" rather than "dose-dependently" in clinical prose.
- "Compared with" and "compared to" are both acceptable; be consistent within the manuscript.
- Avoid "respectively" unless the order is unambiguous.
- Do not begin a sentence with "Also" in journal prose; use "In addition".
- Use one variant of English consistently (British or American) and set the spell-checker to it.

## Paragraph patterns that work in reviews

| Purpose | Pattern |
|---|---|
| Introduce a theme | "Three lines of evidence bear on X: preclinical models, observational cohorts, and randomised trials." |
| Present a trial | Design and population -> comparison -> result with interval -> what it does **not** show |
| Reconcile conflict | "Whereas the earlier single-centre cohort reported X, the larger multicentre trial found Y; the difference may reflect population, endpoint definition, or follow-up." |
| State a mechanism claim | "Preclinical work implicates the pathway; human data remain associative." |
| Bound generalisability | "These findings apply to the trial population; they do not extend to the excluded group." |
| Justify a gap | "No randomised data address this question; current practice rests on observational evidence and expert opinion." |
