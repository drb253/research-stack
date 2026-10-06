# Review Methodology

## Which kind of review is this?

Decide and declare it in `scope.md`. The bundled tooling supports transparent searching for all
three, but the claims a review may make differ.

| Type | Question | Search | Synthesis | Claim strength |
|---|---|---|---|---|
| Narrative review | "What is the current understanding of X, and how should clinicians think about it?" | Structured but not necessarily exhaustive; documented | Thematic, argument-driven | Interpretive; proportional to the best available design |
| Narrative review with systematic search | "What does the literature say about X?" | Reproducible query per database, counts reported (PRISMA-S) | Thematic; no pooled estimate | Depends on the designs found; report the pattern and its inconsistency |
| Systematic review / meta-analysis | "What is the pooled effect of X on Y?" | Exhaustive, protocol-registered | Quantitative pooling | Highest, but **out of scope for this skill** |

This skill does not pool effect sizes, does not compute heterogeneity statistics, and does not
claim to be a systematic review. If the user needs pooling, say so and route to a
systematic-review workflow with a registered protocol, dual screening, risk-of-bias assessment
(RoB 2, ROBINS-I, Newcastle-Ottawa), and PRISMA 2020 reporting.

## What a narrative review must still get right

1. **Justification.** Why this review, and why now. State the clinical problem and the gap.
2. **Aims.** One explicit objective sentence, in the Introduction, matching the abstract.
3. **Search description.** Databases, exact queries, date of the last search, years covered,
   language and publication-type limits, and what could not be searched. PRISMA-S lists the items.
4. **Referencing quality.** Every substantive claim cited to a retrievable source, ideally to the
   primary report rather than to another review. Avoid citing another review for a primary finding
   (secondary citation) unless the primary report is genuinely unobtainable — and say so.
5. **Scientific reasoning.** Weigh designs against each other, address conflicting results, and
   state the mechanism by which conclusions were reached.
6. **Presentation of data.** Tables and figures that carry the evidence, not decoration.

These six items are exactly the SANRA domains, so a SANRA self-assessment is the natural appendix.
SANRA is a 6-item scale scored 0-2 each (maximum 12). Report it as an author self-assessment, not
as peer-reviewed validation.

## Evidence hierarchy and what each design can support

| Design | Can support | Cannot support |
|---|---|---|
| Systematic review / meta-analysis of RCTs | Effect estimates in a defined population; guideline-grade recommendations | Extrapolation to populations excluded from the trials |
| Large multicentre RCT | Causal statements about the randomised intervention within the trial population | Rare harms (unless powered), real-world effectiveness, long-term outcomes |
| Single-centre or underpowered RCT | Directional signals; hypothesis generation | Definitive effect sizes; subgroup claims |
| Prospective cohort | Incidence, prognosis, temporal association | Causation unless the design and analysis address confounding |
| Case-control | Association with an exposure | Incidence; temporal order certainty |
| Cross-sectional | Prevalence, correlation | Any temporal or causal statement |
| Case series / case reports | Recognition of a new phenomenon; adverse-event signals | Frequency, generalisability |
| Registry / real-world data | Effectiveness and safety in routine care; rare events | Causal inference without specific methods |
| Animal or in vitro | Mechanisms, plausibility, hypotheses | Clinical recommendations — label as preclinical in every sentence |
| Modelling / cost-effectiveness | Economic projections under stated assumptions | Observed clinical outcomes |
| Guideline / consensus | What a body currently recommends | Proof that the recommendation is correct |
| Preprint / conference abstract | Early signals | Anything that needs peer-reviewed confidence; label as unrefereed every time it appears |

## Certainty vocabulary

Use a four-level scheme (GRADE-compatible) and keep it consistent between the claim ledger's
`certainty` field and the prose:

- **high** — "randomised trials show", "consistently demonstrates", "the evidence supports".
- **moderate** — "randomised trials suggest", "the weight of evidence indicates".
- **low** — "observational data suggest", "the available evidence is limited and more likely to
  change", "an association was observed".
- **very_low** — "case reports describe", "data are insufficient to determine", "no conclusion can
  be drawn at present".

Downgrade reasons to state explicitly where relevant: risk of bias, inconsistency across studies,
indirectness (different population or outcome), imprecision (wide intervals or small events),
publication bias (small positive studies only).

## Handling conflict and null results

- Present conflicting findings in the same section, in proportion to study quality, and say
  explicitly that they conflict.
- Report null and negative findings. A review that only reports positive studies is a biased review.
- When a large trial contradicts earlier smaller studies, say so: "The larger confirmatory trial
  did not confirm the earlier single-centre signal".
- Never resolve a conflict by citing only the side you prefer.

## Prohibited patterns

- Pooling or pseudo-pooling numbers that were not pooled in the cited analysis.
- Stating a specific effect size when the cited source reported only a direction.
- Calling a preprint or abstract a "trial" or "study published in".
- Describing a cost-effectiveness model as evidence of clinical benefit.
- Upgrading "no significant difference" to "equivalent", or "no evidence of effect" to "no effect".
- Presenting an animal finding in a clinical sentence without the preclinical label.
