# Search and Retrieval

## Rule zero

The search is only as good as its record. Every executed query gets a row in `search_log.csv` with
the database, platform, exact query string, filters, date, hit count, and availability. A query you
cannot reproduce is a query you cannot report, and an unreported search is a Methods section that
does not describe what was actually done.

## Sequence

1. **Decompose the question** into PICO/PEO concept blocks (population, intervention/exposure,
   comparator, outcome), then map each block to controlled vocabulary and free text.
2. **Resolve controlled vocabulary** with `get_mesh_details` (MeSH) and, where available, Emtree via
   the database's own interface. Record the descriptor and its entry terms.
3. **Build the query** per database, using the syntax that database actually supports.
4. **Run the same concept blocks across at least three independent sources**, then add registry
   searches for interventional questions and preprint servers for very recent topics.
5. **Record counts and availability**, including databases that returned nothing or could not be
   searched.
6. **Deduplicate** by DOI, then PMID, then normalized title+year. Record the duplicate count: it is
   the "records removed before screening" box in the flow diagram.
7. **Sweep forward and backward** from the included set with `get_citing_articles` and
   `get_related_articles`, and check the reference lists of any narrative reviews or guidelines you
   are responding to. Log these as "records identified from other methods".

## Query construction

Concept blocks are ORed within a block, ANDed between blocks. Use truncation, phrase searching, and
field tags where the database supports them.

| Database | Tag examples | Notes |
|---|---|---|
| PubMed | `[tiab]`, `[MeSH Terms]`, `[mh]`, `[pt]`, `[dp]`, `[tw]` | MeSH terms explode by default; use `[mh:noexp]` to stop that. `[tiab]` covers title and abstract; add `[tw]` for text words. |
| Europe PMC | `TITLE_ABS:`, `MESH:`, `PUB_TYPE:`, `PUB_YEAR:` | Broad coverage including preprints; report which records were preprints. |
| PMC | `[Title/Abstract]`, `[MeSH]` | Full-text subset only — never treat PMC as the complete literature. |
| Crossref / OpenAlex / Semantic Scholar | Free text and DOI-based | Best for DOI resolution, metadata, citation counts, and forward citation sweeps. Preprint versions may appear separately. |
| ClinicalTrials.gov / ICTRP / CTIS | Condition, intervention, status, phase | Registry records surface studies whose results were never published. Report both. |
| Consensus / academic-search tools | Natural language plus filters | Useful for discovery and coverage checks; verify every hit by identifier before citing. |

Example PubMed block structure for an immunotherapy question:

```text
("Carcinoma, Non-Small-Cell Lung"[Mesh] OR "non-small cell lung cancer"[tiab] OR NSCLC[tiab])
AND ("Pembrolizumab"[Mesh] OR pembrolizumab[tiab] OR "PD-1"[tiab])
AND ("Immunotherapy"[Mesh] OR immunotherapy[tiab] OR "immune checkpoint"[tiab])
AND ("2010"[dp] : "3000"[dp])
```

Filters to consider and to declare: language, publication type (exclude `Editorial`, `Comment`,
`Letter` only if you can justify it), species (use `Humans[Mesh]` for clinical questions but keep
animal studies in a separate, labelled set when the mechanism matters), and date range.

## Availability and rate limits

Record `availability` honestly:

- `returned` — the query executed and returned records.
- `empty` — the query executed and genuinely matched nothing.
- `unavailable` — the source could not be queried (rate limit, outage, authentication).
- `error` — the query failed (syntax, transport).

Then state in Methods: "X was searched on <date>; Y could not be searched because ...". Never write
"no studies were identified" when what happened is "one database was unavailable".

## Screening record

Screen titles and abstracts first, then full texts. For every record that reaches full text,
record `inclusion_status` and, when excluded, a specific `exclusion_reason` such as
`wrong_population`, `not_peer_reviewed`, `outcome_not_relevant`, `superseded_by_later_report`,
`duplicate_publication`, `no_original_data`. "Not relevant" is not a reason.

## PRISMA-S items to report

1. Databases and registers searched, with platform names.
2. Full search strategies, reproduced verbatim in an appendix.
3. Search dates, and the date of the last search.
4. Limits and filters applied.
5. Deduplication method and counts.
6. Number of records screened, retrieved, assessed, and included.
7. Whether searches were updated or rerun, and when.
8. Any additional methods (citation chasing, hand searching, trial registries).
9. Any peer review of the search strategy, and by whom.

## Reproducibility details worth logging

- The platform version or interface where relevant (for example "PubMed as accessed 2026-09-20").
- Whether MeSH terms were auto-exploded.
- Whether any query was rerun and why.
- The order of deduplication (DOI, then PMID, then title+year), because it changes the counts.
- Any publication-type or language restriction, with the justification.

## Common failure modes

| Failure | Consequence |
|---|---|
| Only PubMed searched | Non-indexed literature missing; state the limitation |
| No query strings recorded | Methods cannot be reproduced; human reviewer cannot verify |
| Preprints mixed into the evidence without labels | Overstated certainty |
| Registry records ignored | Missing unpublished results and reporting bias |
| No forward citation sweep on a landmark trial | Missing later corrections, retractions, or confirmations |
| Duplicates not removed before counting | Inflated flow diagram and an arithmetic failure in `prisma_counts.json` |
| Search date omitted | Review appears current when it is not |
