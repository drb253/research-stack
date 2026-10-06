# Section Blueprints

Lengths are indicative for a 4000-5000 word narrative review. The order is the order journals expect.
Every factual sentence carries its markers while drafting.

## Title

- Descriptive or declarative, with the population and the question: "Immune checkpoint inhibition in
  advanced non-small-cell lung cancer: mechanisms, evidence, and unresolved questions".
- No overclaiming adjective; no "a review of" if the article type is already Review.
- Include the review type in the title when the journal requires it.

## Structured abstract (200-300 words, no citations)

| Element | Content | Constraint |
|---|---|---|
| Background | Why this matters clinically | 2-3 sentences, no citations |
| Objective | The question and the population | One sentence |
| Methods | Databases, dates of search, eligibility, number of sources, how certainty was judged | Concrete: name the databases and the search date |
| Results | Main findings, strongest designs named | No numbers without a marker; no citations |
| Conclusions | Proportionate takeaway | Must not exceed what the body supports |

Keywords: 4-8, mirroring MeSH where the journal requires it.

## Introduction (400-600 words)

1. Clinical importance in the first two sentences: burden, practice relevance, why a clinician should
   read on.
2. What is already established, cited to primary work or current guidelines.
3. The gap: what is uncertain, contested, newly changing, or under-recognised. It must be a gap
   identifiable in the literature, not a rhetorical one.
4. One sentence per aim: "This review summarises ... and identifies ...", matching the abstract's
   objective exactly.
5. One sentence on scope, including what is not covered.

## Methods (300-600 words)

Use sub-headings; this section is what makes the review auditable.

- **Search strategy**: databases, registers, exact queries (or an appendix pointer), date of the last
  search, years covered, languages, publication-type limits, and what could not be searched.
- **Selection and verification**: inclusion criteria, screening process, deduplication method, and how
  each source's identity was verified (DOI/PMID) and its retraction status checked.
- **Data extracted**: the fields extracted, the locators recorded, and how missing data are reported.
- **Certainty assessment**: how each theme's certainty was judged, and by whom.
- **Reporting standard**: which guideline was followed (SANRA, or PRISMA 2020 with PRISMA-S when a
  systematic search was performed) and what was not done.

If a step was performed by one person rather than in duplicate, say so. If no risk-of-bias instrument
was used, say so and explain why.

## Body: thematic sections (2000-2500 words total, 3-6 sections)

Order them so the argument builds. A reliable order for clinical reviews:

1. **Biology or mechanism** — how the intervention works; preclinical evidence labelled as such.
2. **Clinical efficacy** — randomised evidence first, then observational, then real-world; describe
   each study by design, population, comparison, result with interval, and what it does not show.
3. **Safety and tolerability** — incidence of the main harms from the designs best able to detect
   them, separating trial data from pharmacovigilance data.
4. **Special populations and subgroups** — pre-specified subgroups only, with the multiplicity caveat.
5. **Guidelines, implementation, cost** — what bodies recommend, with dates, and where practice
   diverges from evidence.
6. **Controversies and unresolved questions** — the honest section; conflicts presented side by side.

Each theme section: opening claim sentence -> evidence in descending quality -> what disagrees ->
what remains unknown -> an explicitly bounded bottom line.



## Discussion (600-900 words)

- **Summary of main findings**: 1-2 paragraphs restating the argument with the strongest sources
  named; no new citations.
- **Clinical implications**: concrete but bounded — who might benefit, who might not, what a clinician
  should do differently, with the certainty level stated.
- **Comparison with other reviews and guidelines**: where this review agrees and disagrees, and why.
- **Strengths and limitations**: of the evidence (designs, risk of bias, heterogeneity, publication
  bias, indirectness) and of the review (search limits, single screener, no formal risk-of-bias
  instrument, language restrictions, no pooling).
- **Future research**: specific testable questions with the design that would answer them (population,
  intervention, comparator, endpoint) and the practical barrier to running it.

## Conclusions (100-200 words)

- 2-4 sentences: the answer, its certainty, and the most important caveat.
- No new citations, no numbers that were not already presented, no new argument.

## Declarations

Funding (with the funder's role); conflicts of interest per author; author contributions in CRediT;
data availability; acknowledgments with permission; AI-use disclosure per journal policy; an ethics
statement when identifiable data were analysed (usually not applicable for a literature review).

## Appendices

- **A. Search strategy**: `search_log.csv` reproduced verbatim, one block per database.
- **B. Screening flow**: the figure plus the recorded counts.
- **C. Unresolved items**: `UNRESOLVED.md`, including every placeholder and any claim withdrawn for
  lack of verified support.
- **D. Reporting checklist**: the SANRA or PRISMA item table with each item marked reported / not
  applicable / not done, and the reason.
- **E. Extraction ledger**: the sources table, or a statement that it is available on request.

## Word budgeting

If the review exceeds the venue's limit, cut in this order: repeated background in the Introduction,
secondary descriptive detail in the body, restated findings in the Discussion. Never cut: the search
description, the limitations, the certainty qualifications, or any citation supporting a claim that
remains in the text.

## Paragraph template for an evidence paragraph

```text
[Claim sentence stating what this evidence shows.] [claim:C0xx] [src:S0xx]
[Design and population of the source, with n.]
[Result with the effect estimate, interval, and comparator.]
[What this study cannot show: endpoint, follow-up, or population limitation.]
```

Three to five sentences. If it needs a sixth, it probably contains a second claim and should be split,
with its own claim ID.

## Section self-check before moving on

| Section | Question |
|---|---|
| Abstract | Does every element match the body, and does the Results element avoid numbers? |
| Introduction | Is the gap a real gap in the cited literature, and does the aim match the abstract? |
| Methods | Could a reader reproduce the search exactly, including what failed? |
| Body | Does every theme end with an explicit bound on what the evidence supports? |
| Discussion | Are the limitations of the review itself stated, not only of the evidence? |
| Conclusions | No new information, no numbers, no new citations? |
| Declarations | Funding, conflicts, contributions, data availability, AI use all present? |
| Appendices | Search log, flow diagram, unresolved items, and checklist all present? |
