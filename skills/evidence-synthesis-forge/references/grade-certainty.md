# GRADE — certainty of evidence and Summary of findings

Paraphrase of the GRADE approach (Cochrane Handbook v6.5 ch. 14; GRADE Handbook; GRADE Book).
© GRADE Working Group — paraphrase and cite; do not reproduce the instruments. GRADEpro GDT
is the official tool; this skill generates GRADEpro-style SoF tables and evidence profiles.

## The rating

Start by design: **randomised trials → High**; **observational studies → Low**. Then move the
rating for each **outcome** (not each study) by the domains below.

### Five domains that can downgrade

1. **Risk of bias** (study limitations) — from the RoB assessment (RoB 2 / ROBINS-I).
2. **Inconsistency** — unexplained heterogeneity across studies (look at the *direction and
   magnitude* of effects, not only I²; a high I² with a consistent direction may not downgrade).
3. **Indirectness** — evidence does not directly address the PICO (population, intervention,
   comparator, outcome) or the comparison is indirect.
4. **Imprecision** — wide CI crossing clinical decision thresholds, few events, or small
   sample; judge against a **pre-specified** threshold, not "p > 0.05".
5. **Publication bias** — suspected missing results (ROB-ME), funnel asymmetry (≥10 studies),
   strong small-study effects, or industry sponsorship patterns.

### Three domains that can upgrade (observational, rarely)

1. **Large magnitude** of effect (e.g. very large RR).
2. **Dose–response gradient**.
3. **Plausible residual confounding would reduce** the observed effect.

Each domain moves the rating by −1 or −2 (downgrade) or +1 (upgrade, observational only).

## Certainty levels

**High** (very confident the true effect is close to the estimate) · **Moderate** · **Low** ·
**Very low**. Report a level **per outcome**, with the domains that drove it.

## Where GRADE fits in a review vs a guideline

- In a **systematic review**, GRADE ends at **certainty per outcome** and the **SoF table**.
- In a **guideline**, GRADE continues into recommendations (strong/weak) via
  the Evidence-to-Decision framework. That is out of scope here — this skill stops at certainty.

## Summary of findings (SoF) table — structure

One table **per comparison**. Columns:

| Outcome | № studies | № participants | Effect (relative) | Effect (absolute) | Certainty (GRADE) | Comments |
|---|---|---|---|---|---|---|

- Include **all** pre-specified outcomes, even with no data (an empty row is informative — it
  marks a research gap); the intervention and comparator are named in the header.
- Absolute effects are **computed from the relative effect and a baseline risk**, not guessed —
  the generator requires an assumed/comparator baseline risk.
- Add **footnotes** for each downgrade domain and the reason.

## GRADE evidence profile — structure

A more detailed table: for each outcome, the **judgement per domain** (risk of bias,
inconsistency, indirectness, imprecision, publication bias → downgrade or "no serious
concern") and the resulting certainty. Use when a reviewer wants the reasoning visible.

## Anti-patterns (checkable)

- Reporting certainty **per study** instead of **per outcome**.
- Downgrading for inconsistency **only because I² is high**, without checking direction.
- Downgrading for imprecision by **p-value** instead of a pre-specified CI threshold.
- A SoF table with **no absolute effect** or **no certainty column**.
- Certainty stated in the abstract **without** the domains that produced it.
