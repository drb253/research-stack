# Table Templates

Copy the skeletons below, or generate them from the ledgers with `make_evidence_table.py`, which is
always preferred because it cannot introduce a number that is not in `sources.csv`.

## Table 1. Characteristics of included studies

```markdown
**Table 1. Characteristics of included studies.**

| Source | Study (first author, year) | Design | Population | Intervention / exposure | Comparator | n | Follow-up | Outcomes | Main finding | Effect estimate | Verified by |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S001 |  |  |  |  |  |  |  |  |  |  |  |

NSCLC, non-small-cell lung cancer; RCT, randomised controlled trial; HR, hazard ratio; CI,
confidence interval. Effect estimates are reported as published; no pooling was performed.
"not_reported" means the source did not report the item.
```

Generate with:

```bash
python3 scripts/make_evidence_table.py sources.csv --style evidence-table \
  --group-by theme --out tables/table1.md
```

## Table 2. Certainty of evidence by theme

```markdown
**Table 2. Certainty of evidence by theme.**

| Theme | Included sources | Participants (sum of reported n) | Highest certainty | Direction of evidence | Designs | Caveat |
|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |

Certainty is assessed on a four-level scheme (high, moderate, low, very low) and is the lowest level
supported by the majority of the contributing evidence for the theme.
```

Generate with:

```bash
python3 scripts/make_evidence_table.py sources.csv --style certainty-of-evidence \
  --claims claims.csv --out tables/table2.md
```

## Table 3. Excluded records and reasons (appendix)

```markdown
**Table 3. Records excluded at full-text assessment.**

| Source | Study (first author, year) | Type | Reason excluded | Retrieval | Verification |
|---|---|---|---|---|---|
|  |  |  |  |  |  |

Reasons follow the categories recorded in sources.csv.
```

Generate with:

```bash
python3 scripts/make_evidence_table.py sources.csv --style excluded-log --out tables/table3.md
```

## Table 4. Guideline recommendations (optional)

```markdown
**Table 4. Current guideline recommendations.**

| Body | Document and year | Recommendation | Evidence grade as stated | Population | Differs from this review? |
|---|---|---|---|---|---|
|  |  |  |  |  |  |

Recommendations are quoted as published; grades are those of the issuing body, not of this review.
```

## Table 5. Ongoing or reported trials (optional)

```markdown
**Table 5. Key trials relevant to the review question.**

| Registry ID | Study name | Phase | Population | Intervention | Comparator | Primary endpoint | Status | Results reported? |
|---|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |  |

Registry identifiers link to the registration record; "results reported" refers to a peer-reviewed
publication, not a registry results posting.
```

## Figure 1. Screening flow

```markdown
**Figure 1. Screening flow of records identified, screened, and included.**

![Screening flow](figures/prisma_flow.svg)

Counts are those recorded in search_log.csv and prisma_counts.json; the flow is checked
arithmetically before the figure is drawn.
```

## Figure 2. Conceptual framework (optional)

```markdown
**Figure 2. Conceptual framework linking [[mechanism]] to [[clinical outcome]].**

![Framework](figures/framework.svg)

The framework is an explanatory synthesis of the cited evidence and does not itself constitute data.
Numbers in parentheses are citation numbers.
```

## Rules that apply to every table

- One row per source; never merge two studies into one row.
- Percentages always accompanied by the numerator and denominator.
- Effect estimates copied verbatim from the source, with the comparator named.
- Missing values as `not_reported`; never blank, never `0`, never `-`.
- Abbreviations expanded in the footnote at first use.
- Display numbering follows the order of first citation in the text.
- No significance marks, no derived statistics, no pooled estimate.
- Regenerate rather than hand-edit when the ledger changes.
