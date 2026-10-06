# STATUS — academic-search MCP fix work

**Snapshot:** 2026-09-30 (evening session). Fork version `0.8.0+local1`.

This is the running state record. The `README.md` explains *why* each change
was made; this file records *what is true right now*.

## TL;DR

The `academic-search` MCP server was forked from PyPI `0.8.0` (the newest
release, so none of these fixes are upstream) and patched. Four defects were
fixed and verified live, two further issues were found and fixed during
verification. **The patched build is live and working.**

## Live state

| Thing | Value |
|---|---|
| Fork location | `~/.local/share/academic-search-mcp/` |
| Installed command | `.venv/bin/academic-search` (setuptools src layout) |
| MCP config | `~/.cline/data/settings/cline_mcp_settings.json` (`academic-search` entry only) |
| Config perms | `600` (holds the S2 key + NCBI key) |
| `S2_API_KEY` | configured, verified present in the serving process env |
| Server process | `.../academic-search-mcp/.venv/bin/academic-search` |
| Tests | 51 passing, fully offline |

Only the `academic-search` entry was modified. `paper-search`, `ncbi`,
`consensus`, `google-scholar` and `laya` are byte-identical to before — that
was confirmed by per-server JSON diff, not assumed.

## Fixes applied

| # | Defect | Status |
|---|---|---|
| 1 | Author search returned 0 rows for a correct full name (`"Jennifer Doudna"` → 227 candidates, 0 kept) | fixed, verified live |
| 2 | Crossref had no relevance ranking (`"base editing"` → denture papers) | fixed, verified live |
| 3 | Junk records passed through to the top of results | fixed, verified live |
| 4 | Citation walk hard-failed on transient errors with a misleading message | fixed, verified live |
| 5 | *(found during verification)* Fix 3 was a no-op on the real junk records | fixed, verified |
| 6 | *(found during verification)* DOI queries reported mangled metadata | fixed, pending restart |

### Detail on 5 and 6, since both were defects in my own work

**Fix 5** — my first version of `is_usable_record` treated an identifier as
evidence of quality. Every Semantic Scholar record carries a
`paperId`/`CorpusId`, and the junk records come with a (garbled) title, so the
check was a **no-op on exactly the records it was written for**. My unit test
passed only because I had written an unrealistic fixture. The fixture is now
the verbatim junk record, and the rule requires a *substantive* field.

**Fix 6** — `search_papers` with a DOI reported `extended_query` as the
keyword transformation of the DOI (`"10.1126/science.add8643"` →
`"science. add"`), which is not what was used. The result was always correct
because the provider resolves DOIs directly; only the reported metadata lied.
Now reports `DOI:10.1126/science.add8643`, and `mean_relevance` is suppressed
for identifier queries.

## Verification evidence

All fixes were verified through the **real MCP tool surface**, not just tests.

| Check | Evidence |
|---|---|
| Fix 1 | `total_from_api: 227` → `total_after_author_filter: 16`, `matched_author_names: ["J. Doudna", "Jennifer A. Doudna"]` (was `0`) |
| Fix 2 | Crossref `"base editing"` top hits are genuine base-editing papers, `mean_relevance: 1.0`, denture paper gone; `publicationDate` populated (was always `null`) |
| Fix 3 | Live 20-record sample: `usable_records: 19, unusable_records: 1` |
| Fix 4 | Deterministic 429 simulation → walk continues and reports the real cause instead of aborting |
| Fix 5 | `is_usable_record(real_junk)` = `False` (was `True`) |
| Fix 6 | `_actual_query` returns `DOI:10.1126/science.add8643` (was `science. add`) |
| Key | Invalid key → `403 Forbidden`; this key → `200`. Serving process proven by live socket: `TCP ->18.164.237.119:https (ESTABLISHED)` |
| Citation walk | `DOI:10.1038/s41586-020-2649-2` → "Array programming with NumPy", `steps_completed: 1`, 1 edge, **no diagnostics** |

Method note: each probe that could have been a false positive was validated
against a control. The env-var probe was checked against `laya`'s
`LAYA_MODELS`; process attribution was settled by watching sockets rather than
trusting parentage. An earlier claim of mine — that the `DOI:` seed prefix was
broken — was **wrong** and was retracted: the prefix always parsed correctly;
the real failure was S2 throttling plus a misleading error message.

## Pending / not yet in effect

- **Fix 6 needs a restart** to reach the running server process. Purely
  cosmetic (results were always correct). No urgency.
- Nothing else is pending from this work.

## Known limitations (not fixed — see README for detail)

1. **S2 throttling persists even with a valid key.** Measured with the key
   active, `/paper/{sha}/citations` returned `429` while `/paper/{sha}`
   returned `200`, and `limit=10` failed where `limit=25` succeeded — an
   alternating pattern at 4-5s spacing, i.e. budget saturation, not rate
   violation. The retry/backoff absorbs it; occasional failures remain.
2. Crossref open-access filtering cannot work (API exposes no OA status).
3. Crossref remains a weak *discovery* engine; good for metadata/DOI sweeps.
4. The Crossref relevance gate over-filters long queries
   (`'CRISPR base editing prime editors'` keeps 13/100).
5. Initial-based author matching can produce false positives
   (`"J. Doudna"` matches `"Jennifer Doudna"` but also a `J.`-initialised
   `John Doudna`). Use `allow_initial_match=False`.
6. Provider metadata gaps are reported, never repaired.

## How to run things

```bash
cd ~/.local/share/academic-search-mcp

# 51 offline regression tests (no network)
./.venv/bin/python -m unittest discover -s tests -p 'test_*.py'

# live behaviour audit of the fixed paths (hits the network)
./.venv/bin/python verification/audit_behavior.py

# deterministic upstream-failure demo (no waiting, no network)
./.venv/bin/python verification/demo_error_reporting.py

# key / endpoint reachability, and a minimal citation walk
S2_API_KEY=<key> ./.venv/bin/python verification/check_api_key.py
S2_API_KEY=<key> ./.venv/bin/python verification/check_citation_walk.py
```

`verification/` holds the ad-hoc scripts that produced the evidence above;
they lived in `/tmp` and were rescued here so the evidence is reproducible.
They contain no credentials — the key is read from the environment.

## Reverting

```bash
# config revert (backup made before any change)
cp ~/.cline/data/settings/cline_mcp_settings.json.bak-before-academic-search-fork-* \
   ~/.cline/data/settings/cline_mcp_settings.json
```

Reinstating the original `uvx`-based server also requires removing the fork
path from the config; the original entry was:

```json
{ "command": "/Users/drb/.local/bin/uvx", "args": ["academic-search"] }
```

## Origin

The upstream server ran via `uvx academic-search`, i.e. from the **ephemeral
uv cache** — `uv cache clean` or a version bump would silently discard any
patch there. Evidence it was genuinely volatile: 11 leaked `uvx` processes
were found referencing **three different** uv archive hashes. The fork runs
from a fixed venv path and is not affected. The leaked processes were cleared;
the current state is a single server process (this count fluctuates as
sessions open and close).

