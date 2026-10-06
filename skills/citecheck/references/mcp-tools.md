# MCP tool routing (paper-search / ncbi)

When the runtime exposes these MCP tools, **prefer them over the bundled script**: they are DOI-verified,
retraction-checked, and carry per-source status. The script stays the keyless fallback and does all the
formatting. Signatures and return shapes below were verified against live calls.

## Routing table

| Task | Preferred tool | Exact args | Fallback |
|---|---|---|---|
| DOI → full metadata | `paper-search__get_crossref_paper_by_doi` | `doi` | `citecheck.py resolve <doi>` |
| DOI batch → citations + retraction | `paper-search__export_citations` | `dois`, `format`, `check_retractions` | loop `resolve` |
| Retraction check (with notice DOI) | `paper-search__check_retraction` | `doi`, optional `title` | `resolve` (OpenAlex flag) |
| Title/author → candidate DOIs | `paper-search__search_papers` | `query`, `sources`, `max_results_per_source` | `resolve "<title>"` |
| PMID → metadata + DOI | `ncbi__get_article_details` | `pmids` (list) | `resolve <pmid>` |
| PMID batch | `ncbi__batch_get_article_details` | `pmids` | loop `resolve` |
| PubMed discovery | `ncbi__search_pubmed` | `query`, `max_results` | — |
| PMID ↔ DOI ↔ PMCID | `paper-search__convert_paper_ids` | `ids` | `ncbi__get_article_details` |
| Citation counts | `paper-search__get_citation_metrics` | `pmids` | — |
| Formatting (APA … BibTeX) | `citecheck.py format` | `--format`, `--file`/stdin | — |

## The interlock: MCP fetches, the script formats

The MCP tools return metadata; the script normalizes and formats it. Pipe any MCP JSON envelope into
`citecheck.py format`:

```bash
# export_citations result -> a formatted reference list
echo "$EXPORT_JSON" | python scripts/citecheck.py format --style apa

# a single get_crossref_paper_by_doi record -> one reference
echo "$CROSSREF_JSON" | python scripts/citecheck.py format --style mla
```

### Batch-resolving a draft's DOIs (one round trip)

```bash
# 1. list the DOIs in the draft
python scripts/citecheck.py scan draft.md --ids-only
# 2. agent: paper-search__export_citations(dois="<those DOIs>", format="bibtex", check_retractions=true)
# 3. format the returned envelope
echo "$EXPORT_JSON" | python scripts/citecheck.py format --style apa
```

Prefer this over N single-DOI calls when a draft has more than a handful of references; `export_citations`
is retraction-checked in the same pass.

`format` accepts a single record, a list, or an envelope with one of the keys
`entries` / `articles` / `papers` / `results` / `data`. It normalizes these author shapes -
`[{family,given}]`, `["Given Family"]`, `"A; B; C"`, `"A and B"`, `"Family, Given"` - reads
volume/issue/pages from the top level **or** from a stringified `extra` dict, and takes the year from
`year`, `publication_year`, `published_date`, or `publication_date`.

## Tool-specific notes (verified live)

- **`export_citations`** returns `retraction_checked: true` plus `retracted: [...]`. For a batch, this
  alone satisfies the C3 retraction check. `retraction_unverified` and `unavailable` must be reported,
  never dropped.
- **`check_retraction`** is the richest source: it names the actual **retraction notice DOI**
  (Wakefield → `10.1016/s0140-6736(10)60175-4`). Prefer it in audit mode.
- **`get_crossref_paper_by_doi`** puts `volume` / `issue` / `page` / `container_title` inside a
  stringified `extra` dict, and `authors` as a `"; "`-joined string. `format` parses both.
- **`search_papers`** returns per-source `status` (`ok` / `empty` / `unavailable`). Read `empty` as "no
  matches" and `unavailable` as "retry or fall back". Title hits are noisy (a query for "Attention is
  all you need" surfaced a book chapter and a quantum-tomography paper): **confirm the DOI with
  `get_crossref_paper_by_doi` before citing.**
- **`convert_paper_ids`** can return HTTP 429 (rate limit). Treat it as optional; get the DOI from
  `ncbi__get_article_details` when it errors.

## Failure handling

- A tool error or a source `unavailable` is reported, never read as "clean".
- If a DOI does not resolve, mark the entry `[UNRESOLVED]`.
- If a retraction check cannot run, say so; never imply the work is retraction-free.
