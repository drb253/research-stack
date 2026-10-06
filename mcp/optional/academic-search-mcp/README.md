# academic-search-mcp (locally patched fork)

A local fork of **`academic-search` 0.8.0** (PyPI, MIT) with four fixes.
0.8.0 is the newest release on PyPI, so none of these fixes exist upstream.

## Why a fork instead of a patch

The server was launched as `uvx academic-search`, which runs the copy inside
the **uv cache** (`~/.cache/uv/archive-v0/...`). That directory is ephemeral:
`uv cache clean` or any version bump would silently discard a patch made
there. This fork lives at a stable path and is installed into its own venv,
mirroring how the `ncbi` and `laya` servers are already configured.

## Layout

```
~/.local/share/academic-search-mcp/
├── pyproject.toml          # packaging (setuptools, src layout)
├── src/academic_search/    # patched source
├── tests/test_fixes.py     # 49 offline regression tests
└── .venv/                  # runtime venv
```

## What was fixed

### 1. Author search returned 0 rows for a correct full name

`search_by_author` filtered with `query.lower() in candidate.lower()` — a
literal substring test. `"jennifer doudna"` is not a substring of
`"jennifer a. doudna"`, so the API returned 227 candidates and the filter
kept **none**. Because that surfaced as a successful empty list, it read as
"this author has no papers" rather than as a bug.

* New `src/academic_search/names.py` compares *name parts* — surname plus
  given names/initials — with accent folding, particle handling
  (`van`, `de`, `von`), `<Family, Given>` parsing and initial-vs-full
  matching (`J. Doudna` ≈ `Jennifer Doudna`).
* A zero result now carries a `diagnostic` block naming the reason and
  suggesting the surname-only retry, so an empty list is never silent again.
* Tunable via `allow_initial_match=False` (exact given name) and
  `allow_surname_only=False`.

### 2. Crossref relevance

Crossref has no semantic ranking, so the query `"base editing"` returned
*"…denture **base** additions…"* and *"…**base** deficit in trauma…"*.

* Switched from the omnibus `query` field to `query.bibliographic` with an
  explicit `sort=relevance`.
* Added a local term-overlap gate (`min_relevance`, defaulting to `1.0` for
  Crossref only — every other provider is unaffected). All query terms must
  appear as whole words, so `base` no longer matches inside `database`.
* Results are re-ranked by term overlap, then metadata completeness, then
  citations.
* Fixed year extraction: `issued` (publication) is now preferred over
  `created` (DOI deposit date), which can differ by years. This also
  populates `publicationDate`, previously always `null`.

### 3. Junk records

Semantic Scholar sometimes returns records with no year, authors, abstract,
journal, citations or references — occasionally with a garbled title — which
could sit at the top of a result list.

* `is_usable_record` rejects a record only when it has **no substantive field
  at all** (year, authors, abstract, journal, citations, references).
* Identifiers and titles are deliberately **not** treated as substantive.
  Every Semantic Scholar record carries a `paperId`/`CorpusId`, and the junk
  records do come with a (garbled) title — so an earlier version of this check,
  which counted identifiers, was a **no-op on exactly the records it was
  written for**. The test fixture is now the verbatim junk record, so that
  regression is caught rather than passing on an unrealistic fixture.
* Trade-off, accepted deliberately: a record carrying only a title + DOI is
  also dropped, because it is indistinguishable by field emptiness from the
  junk and gives no way to judge recency or attribution. Disable the gate with
  `exclude_incomplete=False`.
* Counts are reported as `total_dropped_incomplete`; `get_paper_stats` also
  reports `usable_records`, `unusable_records` and a `quality` summary.

### 4. Citation-walk robustness (the "`DOI:` prefix" red herring)

The `DOI:` prefix was **not** the problem — `_is_doi()` already stripped it,
and `DOI:<doi>` resolved fine in testing. The real cause was transient
upstream failure one step later: the seed *metadata* fetch failed and raised
`ValueError("Could not fetch seed paper '<already-resolved-id>'")`, printing a
resolved ID inside a message that looked like a format error.

Semantic Scholar's unauthenticated pool is aggressively rate limited
(HTTP 429 reproduced live while testing this).

* `S2_API_KEY` (or `SEMANTIC_SCHOLAR_API_KEY`) is now honoured via the
  `x-api-key` header, moving requests onto your own quota. **This is the
  actual fix for the flakiness.**
* Failures are classified — rate limit / timeout / connection / not-found —
  and reported with the concrete cause instead of one generic message.
* A failed seed-metadata fetch no longer aborts the walk; it continues from
  the resolved paper id and says so.
* A zero-step walk returns a `diagnostics` entry explaining whether it was
  throttling, empty link lists, or over-aggressive filters.
* Seeding now accepts DOI (bare, `doi:`, URL), arXiv id (bare or prefixed),
  PMID, `CorpusId`, Semantic Scholar paper URLs and bare paper ids.

## Running the tests

```bash
cd ~/.local/share/academic-search-mcp
./.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

Tests are fully offline — no provider is contacted.

## Known limitations (still NOT working)

These are not fixed. They are upstream constraints or deliberate trade-offs,
recorded so they are not mistaken for solved problems.

1. **Semantic Scholar throttling is not fully solved, even with a key.** A key
   is configured (`S2_API_KEY`) and is valid — verified by differential test:
   an invalid key returns `403 Forbidden` while this key returns `200`. It
   reduces failures but does **not** eliminate them. Measured with the key
   configured, the walk's endpoints behaved differently:

   | Endpoint | Result |
   |---|---|
   | `/paper/DOI:...?fields=paperId` | 200 |
   | `/paper/{sha}?fields=<12 fields>` | 200 |
   | `/paper/{sha}/citations?limit=100` | **429** |
   | `/paper/{sha}/citations?limit=25` | 200 |
   | `/paper/{sha}/citations?limit=10` | **429** |

   The alternating `200/429` pattern at a 4-5s spacing (well inside the
   documented 1 req/s) means the budget is saturated/intermittent rather than
   exceeded by rate, and it is **not** about page size — `limit=10` failed
   where `limit=25` succeeded. The citation/reference listing endpoints are
   the ones that suffer.

   Consequence: `explore_citations` succeeds intermittently and depends on the
   5-attempt retry with 20-60s backoff (~200s worst case) to get through. That
   ceiling sits just under the 300s MCP timeout, so a walk can still fail
   outright under sustained throttling. Raising retries further would push the
   call past the MCP timeout, so the current trade-off is deliberate.

2. ~~**The `explore_citations` success path was not re-verified live.**~~
   **Closed.** With the API key active, a DOI-seeded walk completed cleanly:
   `DOI:10.1038/s41586-020-2649-2` → `024a2c03be8e468e7c4fdf9bda36cdc0eaae85fb`
   ("Array programming with NumPy"), `steps_completed: 1`,
   `unique_papers_visited: 2`, 1 edge, no `diagnostics`. The happy path is
   verified end-to-end.

3. **Crossref open-access filtering does not work.** The Crossref API does not
   expose OA status, so `isOpenAccess` is always `false` and
   `open_access_only=True` returns zero results. The patch adds a
   `filter_notes` explanation instead of a silent empty list. Use
   `semantic_scholar` or `openalex` for OA filtering.

4. **Crossref is still a weak discovery engine.** The gate and ranking act only
   on the records fetched within `max_retrieval`. Crossref's own ordering can
   place a relevant paper outside that window, where it is never seen. Suitable
   for metadata/DOI sweeps, not relevance-ranked discovery.

5. **The Crossref relevance gate over-filters multi-term queries.** With
   `min_relevance=1.0` every query term must appear as a whole word. Measured:
   `'base editing'` keeps 96/100 and `'CRISPR base editing'` keeps 88/100, but
   `'CRISPR base editing prime editors'` keeps only **13/100**. Lower
   `min_relevance` (e.g. `0.5`) for long queries. A note is emitted when >=80%
   of records are dropped.

6. **Initial-based author matching can produce false positives.**
   `"Jennifer Doudna"` matches `"J. Doudna"`, but `"John Doudna"` indexed as
   `"J. Doudna"` would match too. Set `allow_initial_match=False` for exact
   given-name matching. Proper disambiguation (ORCID) is not implemented.

7. **Provider metadata gaps are reported, not repaired.** Sparse records
   (~54% abstract coverage on a sample of 50 Semantic Scholar records) are
   surfaced through `get_paper_stats`; nothing backfills them.

## MCP registration

`~/.cline/data/settings/cline_mcp_settings.json`:

```json
"academic-search": {
  "command": "/Users/drb/.local/share/academic-search-mcp/.venv/bin/academic-search",
  "args": []
}
```

### Reverting

```bash
cp ~/.cline/data/settings/cline_mcp_settings.json.bak-before-academic-search-fork-* \
   ~/.cline/data/settings/cline_mcp_settings.json
```

## Semantic Scholar API key (configured)

A key is set as `S2_API_KEY` in the `env` block of the `academic-search`
entry in `~/.cline/data/settings/cline_mcp_settings.json`; the provider sends
it as the `x-api-key` header. Without it, Semantic Scholar traffic shares a
small global anonymous pool and intermittently fails with HTTP 429 — which is
the failure that was reproduced repeatedly while building these fixes.

Semantic Scholar's published limit is **1 request per second, cumulative
across all endpoints**. `API_DELAY` in
`src/academic_search/providers/semantic_scholar.py` is **3.0 s**, i.e. about
0.33 req/s — roughly 3x headroom. That headroom is deliberate: each Cline
session can run its own server process, and all of them draw on the same
1 req/s budget for this key. Lower `API_DELAY` toward ~1.1 s only if you run a
single session and want faster pagination.

The settings file also holds the NCBI key and is therefore chmod `600`. Keys
are stored in plain text — treat that file as a credential.
