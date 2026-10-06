# PRISMA 2020 manuscript reporting layer

Adapted from keemanxp/slr-prisma (MIT) and Aperivue/medsci-skills (MIT, PRISMA_2020
checklist). PRISMA 2020 statement: Page MJ et al., *BMJ* 2021;372:n71 (doi
10.1136/bmj.n71), CC BY 4.0.

**PRISMA is a reporting guideline, not a conduct guideline** — it says what to report, not
how to run the review. The 2020 version supersedes PRISMA 2009.

## The 27-item checklist (42 sub-items)

**TITLE** — 1 Title: identify the report as a systematic review.

**ABSTRACT** — 2 Abstract: see the separate PRISMA 2020 for Abstracts checklist (score with
its own denominator; it is not a subset).

**INTRODUCTION** — 3 Rationale; 4 Objectives.

**METHODS** — 5 Eligibility criteria (and how studies were grouped); 6 Information sources
(all databases/registers/others + last-search date each); 7 Search strategy (full, with
filters/limits); 8 Selection process (how many reviewers, independent?, automation);
9 Data collection process; 10a Data items (outcomes); 10b Data items (other variables);
11 Study risk of bias assessment; 12 Effect measures; 13a–13f Synthesis methods (eligibility
for synthesis, data preparation, method, heterogeneity handling, sensitivity analyses,
subgroup overviews); 14 Reporting-bias assessment; 15 Certainty assessment.

**RESULTS** — 16a Study selection (ideally a flow diagram); 16b Excluded studies + why;
17 Study characteristics; 18 Risk of bias in studies; 19 Results of individual studies;
20a–20d Results of syntheses (characteristics, statistical, heterogeneity, sensitivity);
21 Reporting biases; 22 Certainty of evidence.

**DISCUSSION** — 23a Interpretation; 23b Limitations of evidence; 23c Limitations of process;
23d Implications.

**OTHER** — 24a Registration + number; 24b Protocol access; 24c Amendments; 25 Support;
26 Competing interests; 27 Data/code availability.

Not every item applies to every review; qualitative/mixed-methods reviews may adapt items
like Effect Measures (12) or statistical synthesis (13d, 20b) and mark them "Not applicable".
Reviews pooling observational studies should also report against **MOOSE**.

## Manuscript assembly (journal-format, not a checklist walkthrough)

The document must read as a journal article in continuous academic prose, with tables and
figures integrated — not a template or a checklist walkthrough.

1. **Interview** — capture topic, review questions, databases, eligibility, screening
   process, appraisal tool, synthesis approach, and flow-diagram numbers. If the user uploads
   a protocol / PROSPERO form / extraction sheet / search log, extract what is present and
   ask only for the gaps.
2. **Draft section by section** — Title Page → Abstract → Introduction → Methods → Results →
   Discussion → Conclusions → Declarations → References → Tables/Figures. Anchor each
   subsection to its PRISMA items (Methods 5–15, Results 16–22).
3. **PRISMA flow diagram** — both a table and a visual, with annotated guidance for each box.
4. **Referencing** — APA 7 by default (adapt to the target journal); every reference verified,
   never fabricated.
5. **Word document** — `.docx`, A4, double-spaced, heading styles, numbered sections,
   style-correct tables, flow diagram embedded in Results. Use the `docx` skill.
6. **Checklist audit (optional)** — map each of the 27 items to where it appears; flag
   missing/incomplete items.

## PRISMA 2020 flow diagram (item 16a) — four phases

```
IDENTIFICATION
  Records identified from databases (n = ?)      Records from other sources (n = ?)
      |
  Records removed before screening: duplicates (n = ?); removed by automation (n = ?); other (n = ?)
      v
SCREENING
  Records screened (n = ?)   ->  Records excluded (n = ?)
  Reports sought for retrieval (n = ?)  ->  Reports not retrieved (n = ?)
  Reports assessed for eligibility (n = ?)  ->  Reports excluded (n = ?), with reasons:
      Reason 1 (n = ?), Reason 2 (n = ?), Reason 3 (n = ?)
      v
INCLUDED
  Studies included in review (n = ?);  Reports of included studies (n = ?)
```

Generate it from counts with `scripts/generate_prisma_flow.py` (reads
`templates/prisma-flow-counts.csv`). Do not hand-draw numbers that the logs can produce.

## Partial requests

Support targeted work: a Methods-only draft (items 5–15); a flow diagram from supplied
numbers; an audit of an existing manuscript against the 27 items; a build-a-search-strategy
task; a Results-only draft (16–22); a references check. Always anchor partial work to the
relevant PRISMA items.
