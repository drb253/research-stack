# Reporting Guidelines

Always take the current version from the EQUATOR Network or the guideline's own site, and note the
access date. Never cite a guideline version from memory.

## Which standard applies

| Review type | Report | Notes |
|---|---|---|
| Narrative review | **SANRA** (6 items) | Self-assessment; put it in the appendix |
| Narrative review with a systematic search | **PRISMA 2020** items 1-16 plus **PRISMA-S** for the search | Report the items you can; state explicitly which are not applicable and why |
| Systematic review / meta-analysis | PRISMA 2020 + PRISMA-S + PRISMA-A for the abstract | Out of scope for this skill unless a protocol-driven workflow is used |
| Observational evidence synthesis | **MOOSE** | Complements PRISMA when the review is built on cohorts |
| Certainty of a body of evidence | **GRADE** or GRADE-CERQual for qualitative evidence | Use the vocabulary; full GRADE tables need a trained reviewer |
| Primary study cited in the review | CONSORT (trials), STROBE (observational), CARE (case reports), STARD (diagnostic accuracy), TRIPOD (prediction models), SPIRIT (protocols) | You cite these designs; you do not re-report them |
| Health-economic claim | CHEERS | Relevant when you cite a cost-effectiveness model |

## SANRA items (score 0-2 each; maximum 12)

1. **Justification of the review's importance for readers.**
2. **Statement of concrete aims or formulation of questions.**
3. **Description of the literature search.**
4. **Referencing.**
5. **Scientific reasoning.**
6. **Appropriate presentation of data.**

Fill it in honestly and include the scores in the appendix. A low score is information; an inflated
score is a credibility risk if a reviewer checks.

## PRISMA 2020 items in one page

1. Title identifies the report as a review.
2. Structured abstract.
3. Rationale.
4. Objectives with an explicit question.
5. Eligibility criteria.
6. Information sources.
7. Full search strategies.
8. Selection process (screening, reviewers, conflicts).
9. Data collection process.
10. Data items (outcomes, effect measures, other variables).
11. Risk-of-bias assessment method.
12. Effect measures.
13. Synthesis methods.
14. Reporting-bias assessment.
15. Certainty assessment.
16. Study selection, characteristics, risk of bias, results of syntheses, and certainty of evidence
    (items 16a-16f), each with the flow diagram.

A narrative review will legitimately answer "not applicable" to several of these (pooling,
heterogeneity, reporting-bias tests). Say so in the Methods rather than leaving the reader to guess.

## PRISMA-S: the search-reporting subset

Databases and registers with platform names; the full strategy per database; search dates and the
date of the last search; limits and filters; deduplication method and counts; number of records
screened, retrieved, assessed, and included; whether searches were updated; any additional methods
such as citation chasing; and whether the strategy was peer reviewed, and by whom.

## GRADE-style certainty statements

Use one of four levels with the reason attached:

```text
Moderate certainty: the randomised evidence consistently shows a benefit in this population, but
the intervals include a clinically unimportant effect and the trials were open label.
Low certainty: the evidence is observational, the cohorts adjusted for different confounders, and
the direction of effect is consistent but the magnitude varies.
```

Deduplicate the downgrade reasons you use, and state them in the same order for every theme.
Downgrade for risk of bias, inconsistency, indirectness, imprecision, and publication bias; upgrade
only for large effects, dose-response, or when plausible confounding would reduce the observed
effect.

## Other statements worth declaring when relevant

- **ICMJE** recommendations for authorship, conflicts, and AI disclosure.
- **COPE** guidance for ethical issues and corrections. Note that COPE's 2017 Core Practices were
  retired in 2024: do not describe them as current standards; cite the current Code of Conduct.
- **STROBE-Vet** or **ARRIVE 2.0** when animal work is central to a mechanism section.
- **SPIRIT** if you discuss trial protocols rather than results.
- Funder-specific reporting requirements (for example open-access or data-sharing mandates).

## Glossary discipline

Whatever guideline you follow, define in Methods:

- what "included" means in your flow diagram (studies, reports, or publications — they differ);
- what a "source" is in your tables (a report, not a study, when multiple reports share a study);
- how certainty was assigned and by whom;
- whether any screening or extraction was performed in duplicate.

## Quick routing checklist

- [ ] Guideline chosen and its version and access date recorded in `scope.md`.
- [ ] Appendix contains the checklist with each item marked reported / not applicable / reason.
- [ ] Methods state what could not be done and why (no pooling, single screener, no risk-of-bias
      instrument, non-exhaustive search).
- [ ] The abstract matches the guideline's abstract requirements.
- [ ] The flow diagram caption names the guideline version it follows.
