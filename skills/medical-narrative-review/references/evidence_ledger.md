# Ledger Schemas

Three files carry all machine-checkable facts. Write them exactly as specified: the validators
reject unknown states and refuse to run when a required column is missing.

## 1. `sources.csv` — the source ledger

One row per **retrieved record**, included or not. 32 columns, in this order:

```text
source_id,title,authors,container,year,volume,issue,pages,doi,pmid,pmcid,
publication_type,peer_reviewed,study_design,population,intervention,comparator,
n_participants,follow_up,key_outcomes,main_finding,effect_estimate,
verification_status,verifier,verified_date,locator,retraction_status,
inclusion_status,exclusion_reason,retrieval_status,theme,notes
```

### Controlled vocabularies

| Column | Allowed values |
|---|---|
| `source_id` | `S` + digits, `S001`-`S99999999`, unique |
| `publication_type` | `journal_article`, `randomised_trial`, `systematic_review`, `meta_analysis`, `review`, `guideline`, `consensus_statement`, `cohort_study`, `case_control_study`, `cross_sectional_study`, `case_report`, `case_series`, `editorial`, `comment`, `letter`, `preprint`, `conference_abstract`, `registry_record`, `book_chapter`, `report`, `other` |
| `peer_reviewed` | `yes`, `no`, `unknown` |
| `verification_status` | `verified`, `unverified`, `failed` |
| `retraction_status` | `not_checked`, `clear`, `retracted`, `expression_of_concern`, `corrected` |
| `inclusion_status` | `included`, `cited_for_context`, `excluded`, `pending` |
| `retrieval_status` | `returned`, `empty`, `unavailable`, `error`, `user_supplied` |

### The four inclusion states

- `included` — part of the evidence base. Counted in the flow diagram, listed in the evidence table,
  and requires full extraction.
- `cited_for_context` — **verified and citable but not part of the evidence base**: an out-of-scope
  modelling study, a superseded guideline cited as such, a trial discussed only for its design.
  It appears in the reference list, is excluded from the evidence table, and is not counted as an
  included study. Use this instead of forcing a context citation into `included`, and never use it to
  smuggle a weak study into the evidence base.
- `excluded` — screened out; requires `exclusion_reason`.
- `pending` — decision open; raises a warning and is excluded from tables and counts.

Absent identifiers are written as `none`. Absent data values are written as `not_reported`;
fields that do not apply (a guideline has no comparator) are written as `not_applicable`.
Never leave a cell empty, and never use `0`, `unknown`, `na`, or `-` — the validator flags
those as ambiguous.

### Conditional requirements

| Condition | Required |
|---|---|
| `verification_status = verified` | `verifier`, `verified_date` (YYYY-MM-DD, not in the future), `locator`, and at least one of `doi`/`pmid`/`pmcid` |
| `inclusion_status = included` | at least one identifier, and all ten extraction fields present |
| `inclusion_status = excluded` | `exclusion_reason` |
| `inclusion_status = included` and `verification_status != verified` | error `UNVERIFIED_SOURCE_INCLUDED` — never cite it |
| `retraction_status = retracted` and included | error `RETRACTED_SOURCE_INCLUDED` |

### Extraction fields

`study_design`, `population`, `intervention`, `comparator`, `n_participants`, `follow_up`,
`key_outcomes`, `main_finding`, `effect_estimate`, `theme`.

- `n_participants`: digits only (`616`), or `not_reported`/`not_applicable`. Never `616 (ITT)`.
- `effect_estimate`: copy the source's numbers verbatim, e.g. `HR 0.49 (95% CI 0.38-0.64)`.
  Never compute, convert, or round it.
- `main_finding`: one sentence in your own words matching the source's own conclusion **and its
  direction**. Report null and negative results as such.
- `locator`: where the claim lives — `Results, p.5; Table 2`, `Abstract only`, `Fig 3B`.
- `theme`: the review section this source belongs to; the evidence table groups by it.

### Example row

```csv
S001,Pembrolizumab plus chemotherapy in metastatic non-small-cell lung cancer,"Gandhi L, Rodriguez-Abreu D, Gadgeel S, et al.",N Engl J Med,2018,378,22,2078-2092,10.1056/NEJMoa1801005,30280635,none,randomised_trial,yes,multicentre double-blind phase 3 RCT,"adults with previously untreated metastatic non-squamous NSCLC without EGFR or ALK alterations",pembrolizumab plus platinum-pemetrexed chemotherapy,placebo plus platinum-pemetrexed chemotherapy,616,median 10.5 months,overall survival; progression-free survival,Pembrolizumab plus chemotherapy prolonged overall survival versus chemotherapy alone,HR 0.49 (95% CI 0.38-0.64),verified,DB,2026-09-20,"Results, p.5; Table 2",clear,included,,returned,first-line immunotherapy,
```

The two empty cells after `included` are `exclusion_reason` and `notes`: both may be empty for
an included row. `exclusion_reason` is mandatory only when `inclusion_status` is `excluded`.



## 2. `claims.csv` — the claim ledger

One row per atomic claim. 10 columns:

```text
claim_id,section,claim_kind,direction,claim_summary,source_ids,
verification_status,certainty,analysis_intent,notes
```

| Column | Allowed values |
|---|---|
| `claim_id` | `C` + digits, `C001`-`C99999999`, unique |
| `claim_kind` | `epidemiology`, `burden`, `mechanism`, `diagnosis`, `prognosis`, `treatment_effect`, `safety`, `guideline`, `health_services`, `economic`, `methodological`, `contextual` |
| `direction` | `supports`, `refutes`, `mixed`, `neutral` |
| `verification_status` | `verified`, `unverified`, `disputed` |
| `certainty` | `high`, `moderate`, `low`, `very_low`, `not_assessed` |
| `analysis_intent` | `confirmatory`, `exploratory`, `descriptive`, `not_applicable` |
| `source_ids` | one or more verified `S` IDs, separated by `;` or `,` |

`claim_summary` is your own one-sentence statement of the claim, at most 200 characters, and it
becomes the outline the review is written from. Write a claim, not a topic:
"Pembrolizumab plus chemotherapy prolonged overall survival in untreated metastatic
non-squamous NSCLC" rather than "KEYNOTE-189".

`certainty` governs the hedging in the prose. A claim marked `low` or `very_low` must read as
uncertain, and the audit emits an advisory reminder for those rows. `direction` records what the
evidence says, not what you hope it says: use `refutes` and `neutral` freely, because a review
containing only supportive claims is usually an incomplete review.

The audit enforces three rules: every source in `source_ids` must exist, be `verified`, be
`included`, and not be `retracted`; a claim marked `verified` cannot rest on an unverified
source; and every registered claim should appear in the manuscript as a `[claim:Cxxx]` marker.

## 3. `search_log.csv` — the search log

One row per executed query. Appendix A reproduces this table, so it must be complete:

```text
search_id,database,platform,query_string,filters,date_run,hits_retrieved,
availability,records_screened,records_included,notes
```

`availability` is `returned`, `empty`, `unavailable`, or `error`. Record unavailable databases
explicitly: a rate-limited database is not evidence that no studies exist, and the Methods
section must say which sources could not be searched.

## 4. `prisma_counts.json` — screening counts

```json
{
  "review_type": "narrative_with_systematic_search",
  "review_title": "Title used in the figure caption",
  "search_date_range": "2010-01-01 to 2026-09-20",
  "databases_searched": ["PubMed", "Europe PMC"],
  "registers_searched": ["ClinicalTrials.gov"],
  "identification": {
    "records_from_databases": 812,
    "records_from_registers": 46,
    "records_from_other_methods": 12,
    "duplicates_removed": 190
  },
  "screening": { "records_screened": 680, "records_excluded": 604 },
  "retrieval": { "reports_sought": 76, "reports_not_retrieved": 6 },
  "eligibility": {
    "reports_assessed": 70,
    "reports_excluded": 26,
    "exclusion_reasons": { "wrong_population": 9, "not_peer_reviewed": 5 }
  },
  "included": { "studies_included": 44, "sources_verified": 44 }
}
```

`make_prisma_flow.py` refuses to draw the figure unless all five identities hold:

```text
records_screened        = databases + registers + other - duplicates_removed
reports_sought          = records_screened - records_excluded
reports_assessed        = reports_sought - reports_not_retrieved
studies_included        = reports_assessed - reports_excluded
sum(exclusion_reasons)  = reports_excluded
```

All counts are integers. If the arithmetic fails, the counts are wrong: correct the screening log
and re-derive them. Never adjust the figure, and never edit numbers to fit a draft.

## Cross-file consistency

| Fact | Lives in | Checked by |
|---|---|---|
| Cited source is verified and included | `sources.csv` | `audit_citations.py`, `build_reference_list.py` |
| Citation number order and completeness | draft -> `final/manuscript_cited.md` | `build_reference_list.py`, `audit_citations.py --final` |
| Bibliographic fields | `sources.csv` -> `final/references.md` | `build_reference_list.py` |
| Percentage and interval arithmetic | manuscript | `check_numbers.py` |
| Certainty wording | `claims.csv` -> prose | `lint_manuscript.py` and human review |
| Screening totals | `sources.csv` vs `prisma_counts.json` | `gate.py` summaries, human review |
