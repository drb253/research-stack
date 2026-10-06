# PRISMA-S — reporting the search

Paraphrase of **PRISMA-S: an extension to PRISMA for reporting literature searches in
systematic reviews** (Rethlefsen ML et al., *Syst Rev* 2021;10:39; CC BY 4.0). PRISMA-S is
what makes a search **reproducible**; a review without it cannot be replicated.

## The 16 items (paraphrased)

**Database and register information**
1. **Database** — name each database/register searched (e.g. MEDLINE via PubMed, Embase, CENTRAL).
2. **Multi-database interface** — if several databases were searched through one platform, name the platform.
3. **Date of search** — the date **each** search was run (not "searched up to submission").
4. **Years/date range** — the date range covered, with rationale.
5. **Search strategy** — the **full line-by-line strategy** for each database (this is the core item; it is what makes the search reproducible).
6. **Limits and filters** — any limits/filters applied (language, publication type, date), and their effect.
7. **Search constraints** — any constraints on the search (e.g. no full-text search available).
8. **Language** — any language restrictions.

**Study registries**
9. **Registries searched** — which trial/study registries were searched and when.
10. **Registry search strategy** — how registries were searched (terms/limits).

**Grey literature and other sources**
11. **Grey-literature source** — which grey-literature sources were searched.
12. **Grey-literature search strategy** — how they were searched.
13. **Supplementary strategies** — citation searching (forward/backward), hand-searching, etc.
14. **Other sources** — e.g. contacting authors, reference lists, web searches.
15. **Peer review of the search** — whether the strategy was peer reviewed (PRESS), and by whom.
16. **Deduplication and total records** — how duplicates were removed and the numbers.

## The reproducibility rule

A search-strategy document is only valid if **re-running the documented strategy reproduces
the documented hit count on the documented date**. A count that cannot be reproduced is a
defect. Record, per database: the exact query string, the date run, the hit count, and the
database version/vendor.

## Known-item validation (do this before trusting the search)

Before the full search is trusted, confirm it retrieves a small set of papers you already
know are in scope. A strategy that misses a landmark paper has a **strategy bug**, not a
smaller corpus. Pair every controlled-vocabulary heading (MeSH/Emtree) with a free-text
`[tiab]` term: indexing is not retrospective, so a MeSH-only search silently loses the
pre-indexing era.

## Outputs from this skill

- `scripts/prisma_s_appendix.py` — assembles a PRISMA-S-compliant search appendix from
  `search_log.csv` (one row per executed query: `source, query, date_run, hits, source_status,
  platform, limits, notes`), and flags rows missing a date or a hit count.

## Anti-patterns

- "We searched PubMed, Embase and Web of Science" with **no strategy** — not reproducible.
- One date for the whole review instead of **per-database** dates.
- Reporting hits **before** deduplication as if unique.
- A strategy that cannot be re-run to the same count.
