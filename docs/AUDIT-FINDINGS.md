# research-stack — verified audit & fix report

Repo: `github.com/drb253/research-stack` (cloned to `Research-stack/repo`, HEAD `053c02a`)
Method: every finding below was **reproduced by running code**. Findings that turned out to be
false alarms are listed explicitly in §3 so the audit can be trusted. 41 files changed (§6 covers
the second round).

---

## 1. Confirmed defects — fixed and verified

### HIGH

**1.1 `install.sh` created a literal `*` symlink in the user's skills directory**
`install.sh:272` looped `for d in "$STORE"/skills/*/` with no guard. When the glob matches
nothing (empty skills dir, empty upstream pack), bash leaves the pattern literal, so the loop ran
once with `name="*"` and executed `ln -s '<dir>/*/' '<skills>/*'`.
*Evidence (end-to-end, real script, throwaway `$HOME`):* produced
`* -> /tmp/rs-fakehome/.local/share/scientific-agent-skills/skills/*/` — a dangling symlink
literally named `*` — while still exiting 0.
*Fix:* `[ -d "$d" ] || continue` guards on both the local and upstream loops.
*Verified:* empty-upstream case → no `*`, 12 skills, 0 dangling; populated case (166 upstream)
→ 178 links, 0 dangling; CI dry-run still exit 0.

**1.2 `ncbi-mcp-server/requirements.txt` could not produce a working server (two bugs)**
`pip install -r requirements.txt` then importing the server failed:
- `ModuleNotFoundError: No module named 'dotenv'` — `python-dotenv` and `aiofiles` were missing
  (both are imported: `server.py:19`, `analytics.py:19`), even though `pyproject.toml` declares them.
- After adding them: `ModuleNotFoundError: mcp.server.fastmcp. This is mcp 2.x` — the entry
  `mcp>=1.0.0` was unconstrained, so pip installed mcp 2.x and broke the v1 API. `pyproject.toml`
  pins `^1.0.0`, so only the requirements file was wrong. This is the *same defect class* the
  CHANGELOG says was fixed for `paper-search-mcp`, missed for `ncbi`.
*Fix:* added the missing deps, constrained `mcp>=1.0.0,<2`, dropped the bogus `asyncio` backport
  entry, documented `redis` as optional (lazily imported in `cache.py:69`).
*Verified:* fresh venv → `IMPORT OK`, mcp 1.30.0; suite still 52 passed.

**1.3 `citeseerx.py` — `NameError: name 'os' is not defined`**
`download_pdf()` calls `os.makedirs` / `os.path.join` (lines 321, 327) but the module never
imports `os`.
*Evidence:* executed `download_pdf` with a stubbed response → `NameError: name 'os' is not defined`.
*Fix:* `import os`. *Verified:* now returns the saved path.

**1.4 `elsevier.py` — `NameError: name 'assert_usable_bytes' is not defined`**
`get_fulltext()` calls `assert_usable_bytes` (lines 301, 308) but only
`SourceUnavailable, request_json` were imported from `..source_status`.
*Evidence:* executed `get_fulltext` with a stubbed XML response → `NameError`.
*Fix:* added the import **and** mirrored it into `paper-search-patches/replacements/elsevier.py`,
because that file is a byte-identical whole-file copy — otherwise re-applying patches would
reintroduce the bug. *Verified:* returns 749 chars; both copies byte-identical.

### MEDIUM

**1.5 `cli.py` — duplicate source list silently dropped sources; `chemrxiv` unreachable**
Two bugs in one place:
- `ALL_SOURCES` was appended twice with the same five names (`plos, jstage, figshare, datacite,
  whoris`) → 36 entries / 31 unique. `cmd_search` keys its task dict by source name, so the
  duplicates **overwrote live coroutines**: `RuntimeWarning: coroutine '_async_search' was never
  awaited` and those sources' results were discarded.
- `chemrxiv` is fully wired in `server.py` but was entirely absent from `cli.py`, so the CLI
  listed 27 sources against the server's 28.
*Evidence:* `ALL_SOURCES len 36 unique 31`; `-s all` emitted the RuntimeWarning; `chemrxiv` not
referenced anywhere in `cli.py`.
*Fix:* de-duplicate via `dict.fromkeys` (mirroring `server.py:170`), de-dup in `_parse_sources`,
register `ChemRxivSearcher`, add `chemrxiv` to the list, and sync the whole-file patch copy.
*Verified:* CLI == server == 28 sources in a keyless env; no duplicates; no RuntimeWarning.

**1.6 `CachedNCBIClient` had no `close()` → `AttributeError` on every shutdown + client leak**
`server.py:554` awaits `ncbi_client.close()`, but `ncbi_client` is a `CachedNCBIClient`
(`server.py:512`), whose class (`cache.py:204`) defines no `close`. So every shutdown raised
`AttributeError` and the inner `httpx.AsyncClient` was never closed.
*Evidence:* `hasattr(c,'close')` → `False`; `await c.close()` → `AttributeError`.
*Fix:* delegating `async def close()` that calls the inner client's `close` when present.
*Verified:* inner closed; an inner client without `close` is tolerated; suite still 52 passed.

**1.7 Seven executable files hardcoded the author's home directory**
`sys.path.insert(0, "/Users/drb/.local/share/...")` in six `academic-search-mcp/verification/*.py`
and `paper-search-patches/yield_table.py`. These are the very scripts that establish trust, and
they work for exactly one user on one machine.
*Fix:* resolve the package relative to the script (with an env override), and for `yield_table.py`
search the vendored checkout and any uv-tool install.
*Verified:* no `/Users/...` paths remain in executable files; resolution logic returns the correct
vendored directory.

**1.8 CI never ran the 103 tests that already shipped in the repo**
`mcp/ncbi-mcp-server/tests` (52) and `mcp/academic-search-mcp/tests` (51) passed but no CI job
invoked them.
*Fix:* added an `mcp-tests` job to `.github/workflows/ci.yml` with the correct declared deps.
*Verified:* YAML parses (`jobs: lint, r-tests, mcp-tests`); both jobs simulated in clean venvs
→ 52 passed / 51 passed.

**1.9 The composition chart claimed "400 tracked files"; git tracks 402**
`scripts/make_readme_charts.py` hard-coded `files = [198,160,24,5,4,1,1,1,3,3]` (= 400) and the
title "400 tracked files", rendered into `assets/composition.svg`. It had drifted (root `.sh` = 4,
meta = 4, `.github` = 1 missing).
*Fix:* derive every count from `git ls-files`, sort by size, and **fail loudly** if the categories
don't sum to the real total — so it can never drift again.
*Verified:* chart reads "402 tracked files" (198+160+24+5+4+4+3+1+1+1+1); deliberately removing a
category from the list makes it exit 1 with an explanatory error; SVG regenerated.

### LOW — documentation accuracy ("no false claiming")

**1.10 IEEE / ACM were advertised as working keyed sources; they are stubs.**
README:546 sold them as the "last ~10%" of coverage ("paid-index coverage"), and
`paper-search/SKILL.md:237` said the keys are "only needed for those paywalled indexes".
*Evidence:* with a valid-looking key set, `is_configured=True` and then
`NotImplementedError: IEEE Xplore search is not yet implemented.` (same for ACM).
*Fix:* both docs now state the connectors are skeletons that add no coverage.

**1.11 Other corrected claims (each verified before editing)**
| Claim | Reality | Where |
|---|---|---|
| "77 tools exposed directly" | **87** registered (live `list_tools()`) | `paper-search/SKILL.md:20` |
| "`verify.sh` … plus `--help`" | no `--help` case existed | `README.md:404` → added `--help` to `verify.sh` |
| "`verify.sh → 19 checks`" | **20** | `README.md:205` |
| "27 free sources" / "fans out to those 23" | 28 registered; 27 work with zero config (Unpaywall needs an email); CLI now matches server | `README.md` ×5, `SKILL.md` ×2 |
| "49 offline regression tests" | **51** | `mcp/academic-search-mcp/README.md:20` |
| "550+" AIPOCH skills | **463** (README already said 460+) | `install.sh:66` |
| "credited per-skill in each `NOTICE.md`" | only **3 of 12** skills have one | `README.md:708,715` |
| "The local CLIs make no network calls" | **7** CLIs use `urllib.request`; `citecheck.py resolve` fetches Crossref live | `README.md:669` |
| `bash cline-setup/verify-setup.sh` | path doesn't exist (file is `docs/original/verify-setup.sh`) | `docs/original/VERIFY.md:15` |
| "43 patched connectors" | 43 files exist but only **28** are connectors; "modules" is accurate | `README.md:141,618` |

**1.12 Citation gate: added Crossref's canonical `is-retracted-by` relation**
`cross_verify_citations.py:116` only read `relation["update-to"]`/`["updated-by"]`, while the
sibling `retraction.py:151` correctly reads `relation["is-retracted-by"]`.
*Fix:* read `is-retracted-by` too, plus a self-test fixture. This is **defence in depth** — see §3.2,
the gate already caught the real-world cases via OpenAlex.

---

## 2. Verification after all changes

| Check | Result |
|---|---|
| humanizer self-test | OK (12 pos / 4 neg) |
| `cross_verify_citations --self-test` | OK |
| medical-narrative-review selftest | 19 passed, 0 failed |
| evidence-synthesis-forge selftest | 50 passed, 0 failed |
| R golden tests (engine vs metafor) | 17 passed, 0 failed |
| ncbi-mcp-server tests | 52 passed, 20 deselected |
| academic-search tests | 51 passed |
| Python syntax, 3.11, CI parity | 133 files, 0 bad |
| `bash -n` all shell | clean |
| installer dry-run (CI command) | exit 0 |
| `verify.sh --help` | works, exit 0 |
| Patch-system idempotency | `applied=0 already_applied=45 failed=0`, no file changed |
| Chart self-check | 402 accounted = 402 tracked |

Live end-to-end: the retracted Lancet HCQ DOI and Wakefield 1998 both still `gate: FAIL`.

**A cross-check that caught my own mistake:** after fixing `cli.py` I re-ran the patch-system
idempotency test, which reported `applied=1` — the whole-file replacement had silently reverted my
fix, because `replacements/cli.py` is the byte-for-byte source of truth. I synced it; the test then
returned `applied=0`. Without that check the fix would have evaporated on the next
`--from-pypi` install.

---

## 3. False alarms — checked and **rejected** (not reported as defects)

1. **"~100 Python files have syntax errors."** My first sweep used the system `python3` (3.9),
   which failed on a macOS bytecode-cache `PermissionError`
   (`/Users/drb/Library/Caches/com.apple.python/...`), *not* a syntax error. Under the CI target
   (3.11) all 133 files compile; under 3.9 `ast.parse` also accepts all but one intentional
   fragment. No defect.
2. **"Retracted papers pass the citation gate" (reported HIGH by an audit subagent).** The schema
   gap is real (§1.12), but the severity claim is wrong: tested live against the hardest case,
   Wakefield 1998 — for which Crossref carries *no* retraction signal at all — the gate returned
   `status: retracted`, `evidence: ["openalex:is_retracted"]`, `gate: FAIL`. The multi-source
   design works; OpenAlex covers what Crossref misses.
3. **"27 free sources is wrong, it's 28."** 28 are registered, but `unpaywall` refuses to work
   without a contact email (`unpaywall.py:28`), so 27 genuinely work with zero configuration.
   The real defect was the internal inconsistency (CLI 27 vs server 28), now fixed.
4. **"43 patched connectors is wrong."** `replacements/` contains exactly **43** files. Accurate.
5. **"ncbi tests fail in a clean environment."** They fail only without `pytest-asyncio`, which
   **is** declared in `pyproject.toml:40` (Poetry dev group). Not a defect — my venv was incomplete.
6. **"`verify.sh` reports a FAIL."** The originality toolkit genuinely isn't installed on this
   machine; that FAIL is correct post-install behaviour, not a bug.
7. **"`acceptance_test.py` misbehaves (exit 1)."** My sandbox denied writes to `~/.research-stack`.
   With a writable `--workdir` it reports **17 checks, 0 misbehaved**.
8. **"`head: illegal line count -- 0`"** in one output — my own command, not the repo.
9. **"Broken links in `table_templates.md`"** — inside a fenced Markdown template block; not links.

---

## 4. Verified working (not assumed)

- **"103 automated checks, all passing"** is arithmetically exact and every suite passes:
  50 + 19 + 17 + 17. The four chart values sum to 103.
- **Vendored tree ⇄ patch system consistency**: 45 patch operations (28 whole-file copies,
  6 new files, 1 injection, 10 marker patches) over 36 distinct modules; re-running
  `apply_patches.py` against the vendored tree is a no-op and every whole-file copy is byte-identical.
- No hardcoded secrets (only `*.env.template` / `.env.example`); 0 broken anchors repo-wide.
- 12 skills, 5 MCP servers, 8 config platforms, 198 `skills/` files, 23 toolkit files — all match.

---

## 5. Honest limits — what this audit does **not** establish

You asked for "99% accuracy", "medical grade", "plagiarism-free", "no hallucination". I can't
certify any of those, and I'd be making things up if I said otherwise:

- **"99% accuracy" is not a measurable property of this repo.** There is no ground-truth labelled
  corpus here, so no accuracy figure can be computed or claimed. What *is* measurable and verified
  is the check count, the gate behaviour, and the fact that every gate is exercised on both a pass
  and a fail path.
- **"Medical grade" is a regulatory status, not a code property.** This is research tooling. It has
  no FDA/CE clearance, no clinical validation, no QMS, and no PHI handling beyond a ledger linter.
  Calling it medical-grade would be a false claim, and the repo itself does not make that claim —
  correctly.
- **"Plagiarism-free" cannot be guaranteed by software.** `originality-check` measures attribution
  and overlap on *your* draft; it is not a plagiarism detector and cannot clear a manuscript.
- **"No hallucination" is bounded, not absolute.** The gates refuse unresolvable DOIs, retracted
  works, untraceable numbers and unreconciled PRISMA flows — verified. They cannot detect a
  *fluent but wrong* sentence that cites a real, verified paper. That residual risk is inherent.
- **The 17 "live acceptance" checks are network-dependent** and are not part of CI, so the "103"
  figure is only reproducible with working network access.

---

## 6. Second round — further findings verified by execution and fixed

These were surfaced by an independent audit subagent. I reproduced each one before touching it.

**6.1 [HIGH] `print()` to stdout inside a stdio MCP server — JSON-RPC corruption.**
`server.py` runs `mcp.run(transport="stdio")`, where stdout *is* the protocol channel. Four
`read_*_paper` tools did `print(f"Error reading paper ...")` on failure.
*Evidence:* with the inner searcher forced to raise, stdout captured
`'Error reading paper 2106.12345: simulated unexpected failure'` — protocol corruption — and the
tool returned `""`, masking the failure.
*Fix:* `logger.error(...)` (stderr). *Verified:* stdout now empty; error still reported.
*(Note: `server.py` is a whole-file patch copy — synced to `replacements/server.py`.)*

**6.2 [HIGH] `citecheck.py` silently disabled TLS verification.**
`_open()` caught `ssl.SSLError` and retried with `check_hostname=False` / `CERT_NONE`.
*Evidence:* simulated an SSLError → retry context had `verify_mode=CERT_NONE`.
In a tool whose job is *verifying citations*, that lets a MITM substitute fabricated
Crossref/OpenAlex metadata.
*Fix:* removed the downgrade; the error now propagates. The now-unused `ssl` import was dropped.
*Verified:* no `CERT_NONE` remains; live `resolve` still returns correct metadata.

**6.3 [HIGH] `citecheck.py` swallowed retraction-lookup failures — a retracted paper could look clean.**
`enrich_retraction()` had `except Exception: pass`, so a failed OpenAlex check left
`is_retracted` unset and the record was reported as *not retracted* — the exact "failed source
looks like no results" anti-pattern the repo promises to avoid elsewhere.
*Fix:* record `retraction_check_failed` and surface it as a `WARN` note in `verify` output.
*Verified:* a forced failure sets the flag; `is_retracted` stays `None` rather than false.

**6.4 [MED] `query_planning.py` matched relevance "phrases" by raw substring.**
`phrase_in_title = phrase_text in title` had no word boundary, unlike the term matcher.
*Evidence:* query `base` vs title "Database systems for the cloud" → `band: high, score 3.0,
why: exact phrase in title`.
*Fix:* word-boundary regex, consistent with `_term_pattern()`. *Verified:* `base` → `low`;
"Base editing…" still `high`; multi-word phrases still match.

**6.5 [MED] `analytics.py` lost all data on one unknown key.**
`UsageStats(**stats_data)` raised `TypeError` on any unrecognised key; the broad `except` then
aborted the whole load, so `total_requests` became 0 **and** `query_hashes` was discarded.
*Evidence:* a file with one extra key loaded `total_requests=0`, `query_hashes=set()`.
*Fix:* ignore unknown keys with a warning; load the rest. *Verified:* 42 requests, 7 cache hits
and both query hashes preserved.

**6.6 [MED] NCBI `advanced_search` dropped one-sided date ranges.**
`if date_from and date_to:` meant a `date_from`-only or `date_to`-only call silently applied **no**
date filter.
*Evidence:* `date_from='2020'` produced the query `(crispr)`.
*Fix:* open-ended bounds (`1800`/`3000`). *Verified:* from-only → `(2020[pdat]:3000[pdat])`,
to-only → `(1800[pdat]:2024[pdat])`, neither → unchanged.

**6.7 [MED] `retraction.py` failed its own documented contract.**
The docstring promises "every failed lookup is recorded in `sources_unavailable`", but the
notice-search failure was logged at `debug` only, so `status` could still read `ok`.
*Fix:* record `crossref-notice-search` and log at warning. *Verified:* the failure now appears in
`sources_unavailable`.

**6.8 [MED] `_pdfrender.py` — the PRISMA figure note was dead code.**
The explanatory note sat *after* `return payload, report`, so it was never drawn.
*Fix:* moved it to immediately after the screening figure, before `document.build()`.
*Verified:* `mnr` selftest still 19/19 (it exercises PDF export).

**6.9 [MED] `stats.py` emitted `NaN`, breaking strict-JSON clients.**
Sample `std` of a single observation is `NaN`; `json.dumps(..., allow_nan=False)` raised
"Out of range float values are not JSON compliant".
*Fix:* a `_num()` helper maps `NaN`/`inf` → `null` (honestly "undefined") across all ten
statistic sites. *Verified:* n=1 now serialises as strict JSON with `"std": null`; n=2 computes a
real value; 51 tests still pass.

**6.10 [LOW] `build_reference_list.py` — crash instead of a clear error.**
`format_reference()` fell through and returned `None` for an unknown style, so the caller's
tuple-unpack died with `TypeError: cannot unpack non-sequence NoneType`. The intended
`raise ValueError("unsupported citation style")` sat unreachable after a `return`.
*Fix:* removed the dead code and raise a descriptive `ValueError` at the fall-through.
*Verified:* unknown style → `ValueError: unsupported citation style: 'nonexistent-style'`;
all four real styles unchanged.

**6.11 [LOW] `server.py` off-by-one on a citation limit.**
`data[: max(limit, 1)]` made `get_citing_articles(limit=0)` return one record.
*Fix:* `max(limit, 0)`. *Verified:* limit 0 → 0 records, 1 → 1, 3 → 3.

**6.12 [LOW] `batch.py` `progressive_search` returned ~80% duplicate PMIDs.**
The loop re-sent the *same* first page every iteration — `search_pubmed` exposes no
`retstart`/offset, yet a comment claimed it was used.
*Evidence:* a stub returning 3 PMIDs each call produced `total_fetched: 500`.
*Fix:* de-duplicate and stop as soon as a page adds nothing new, with an honest docstring.
*Verified:* 3 unique PMIDs and 2 API calls instead of 500 duplicates.

**6.13 [LOW] Dead code / misleading leftovers removed.**
`oaipmh.py` assigned `retry_count`/`max_retries` that were never used;
`chemrxiv.py` built a `chemistry_subjects` list then discarded it with `pass`;
`check_review_integrity.py` listed `"referral"` twice in the same set literal.
*Fix:* removed all three. *Verified:* syntax clean, esf selftest still 50/50.

### Formerly open — both fixed in the fifth round (§11)

- **`async` MCP tools calling blocking searchers.** Fixed: the search path already went through
  `async_search` (→ `asyncio.to_thread`), but 34 *other* tools — every `download_pdf`, `read_paper`,
  `list_categories` and `quota_status` — still did blocking socket and file I/O on the event loop.
  All 36 call sites now go through `async_call`, and a test asserts a tick of the loop happens
  *during* a deliberately slow searcher call. Two mutations (either helper put back on the loop) are
  caught by name.
- **`academic-search` keeping `year=None` records.** Fixed by making the semantics explicit rather
  than by changing them: an undated record still passes a year filter (dropping it could hide a paper
  that is in range, the worse error for a review), and it is now returned with
  `_year_unknown: True` so the caller can tell "in range" from "not known". The annotation is made on
  a copy, so the provider's payload is not mutated, and a boolean `year` is no longer treated as
  year 1. Four tests pin it.

---

## 7. Final state

_State at the end of round 2, kept as the record of that round. For the current numbers see §8._

| Check | Result |
|---|---|
| Patch idempotency | `applied=0 already_applied=45 failed=0`, no file changed |
| Whole-file patch copies byte-identical | yes (server, cli, elsevier, retraction, query_planning, …) |
| Python syntax (3.11, CI parity) | 133 files, 0 bad |
| `bash -n` all shell | clean |
| mnr selftest | 19 passed, 0 failed (29 as of §8) |
| esf selftest | 50 passed, 0 failed (62 as of §8) |
| R golden tests | 17 passed, 0 failed |
| humanizer / cross_verify self-tests | OK |
| ncbi-mcp-server tests | 52 passed, 20 deselected |
| academic-search tests | 51 passed |
| citecheck live resolve | correct metadata |
| installer dry-run | exit 0 |
| `verify.sh --help` | exit 0 |

**41 files changed.** Every fix was reproduced before and re-verified after; every whole-file patch
copy was re-synced and the patch system re-checked for drift.

---

## 8. Third round — the evidence-invariant audit

`docs/EVIDENCE-INVARIANT.md` closed with five open questions, one per remaining gate, and said plainly
that each was a question rather than a finding. All five were asked, by reading the code path and then
running it against a fixture where the input was missing. **All five answered yes — every one of them
broke the rule.** Each was reproduced against the committed code before its fix, and each fix ships a
pass-and-fail test; the answers and the reproductions are recorded in that document, and the work is
one commit per gate.

| Gate | The pre-fix behaviour, measured | Fixed |
|---|---|---|
| `cross_verify_citations.py` | a refused connection and a nonexistent DOI gave byte-identical stdout, `gate: FAIL`, exit 2, and the same DOI in `unresolved[]`/`failures[]`; `--allow-unresolved` made a total outage `gate: PASS`, exit 0 | unreachable resolver gets its own status, `input_gaps[]`, gate `INCOMPLETE` and exit 3, not waivable by that flag; `--recheck` re-checks the worklist |
| `citecheck` | an unresolvable identifier was **dropped** from the emitted list (an all-bad draft wrote 1 byte) and the run exited 0 — a hard error by its own `eval.md` C2 | `[UNRESOLVED]` / `[NOT CHECKED]` placeholders are written into the artifact; exit 2 for a finding, 3 for an input gap |
| `medical-narrative-review` | a source row with `retrieval_status=empty` and `not_reported` extraction passed `validate_sources --strict`, `audit_citations --strict` and `gate.py` (`submission_ready: true`), all exit 0 | an unread citable source, and a verified claim joined to one, are `insufficient_evidence` (exit 3) with a worklist; `GATE_REPORT.json` records it and refuses `submission_ready` |
| `sysreview` / PRISMA | with `source_status=unavailable, hits=0`, the appendix printed `embase … 0` and "OK", and the completeness gate printed "OK - retrieval and assessment complete", both exit 0; no script read the column | the appendix renders `unavailable (not reached)`, never the digit; both gates exit 3 and state that the identified total is a floor |
| `originality-check` / toolkit | three of four unreadable corpus files still gave "highest score: 0.813" and a full score table, exit 0; a wholly unreadable corpus or a missing path gave the clean verdict shape | the gap reaches the report, `corpus.not_checked[]` and the exit code; a corpus that loaded nothing prints no score line and no verdict |

Two consumers had inherited the same confusion, because a gate's output is the next tool's input:
`benchmarks/bench_accuracy.py` read the old generic `error` status as *resolved*, so a lookup failure
on a retracted paper counted as a **missed retraction** — the one number the 920-citation claim rests
on; and `acceptance_test.py` accepted any non-zero exit, so a network outage satisfied an adversarial
test. Both are fixed.

**Current state** (re-run on the committed tree; `git diff --check` clean):

| Check | Result |
|---|---|
| esf selftest | **62 passed, 0 failed** |
| medical-narrative-review selftest | **29 passed, 0 failed** |
| citation-report selftest | **95 passed, 0 failed** |
| meta-analysis-forge golden tests | 17 passed, 0 failed |
| offline logic self-tests (humanizer, cross_verify, citecheck, originality toolkit) | 4 of 4 OK |
| offline benchmarks (numeric, ORI guide, verdicts) | 3 of 3 exit 0 |
| `verify.sh --targets cline,claude,opencode` | **25 passed, 0 failed — RESEARCH-STACK VERIFIED** |
| README check total | 220, and the chart refuses to render if it disagrees with the text |

**What this round does not establish**, recorded so §8 is not read as a clean bill of health:

- The five audits were verified by their own fixtures, not by an independent reviewer.
- A malformed input file is still reported in the finding channel (`INVALID_INPUT`, exit 1): the status
  vocabulary has no `insufficient_input` member. It exits non-zero and is labelled as an input problem,
  so it never reads as a finding about the artefact, but the vocabulary is not yet uniform.
- A partial failure of the retraction signals is a recorded warning rather than an input condition.
  Crossref's own signal still runs, so the check is real; a run in which *every* signal failed would
  still be presented as a findings-based result.
- The trigger still misses four of thirty attribution-requiring sentences in real prose (sensitivity
  0.867), all of them multi-clause subjects beyond the deliberate four-word cap. They are named
  individually in `docs/BENCHMARK-RESULTS.md` rather than averaged away.
- The conflict ground truth was widened from 4 to 26 positives, moving its Wilson lower bound from
  0.510 to 0.871 — but it remains author-written, so it shows the rules do what they were designed to
  do, not that they generalise.


---

## 9. Fourth round — two violations that CI found, and the gate that should have

Round three asked each gate the invariant question and fixed what it found. It missed two things, and
the way they surfaced is the finding: **a suite that passes on the machine that wrote it can still be
asserting an environment that machine happens to have.**

### 9.1 `citation-report`: "no PDF extractor" was reported as a finding (exit 1)

The round-three fix taught the report CLI that a *scan* — a PDF an extractor read and found no text in
— is `insufficient_input` (exit 4). It left the neighbouring condition in the finding channel: a
machine with neither `pdftotext` nor `pypdf` cannot read any PDF, and that refusal was emitted as
`INVALID_INPUT` with exit 1, the same status and code as a verdict about the document. Nothing had
been read; the reader was told, in the finding channel, about a document the tool had not opened.

The selftest asserted the scan wording unconditionally. On the developer machine (poppler installed)
it passed; on CI, which has no PDF extractor at all, the fixture took the other branch and six
assertions failed — which is how the violation was found, and why the fix is in this round rather
than a footnote.

Fixed:

- every unreadable-PDF outcome now carries a machine-readable `gap_kind` and `gap_worklist` from
  `_pdftext.py`, and all three routes — `no_text_layer` (scan), `no_pdf_extractor`, `unreadable_pdf`
  — raise `UnreadableDocument` and exit 4;
- the envelope gained a top-level `input_gaps[]` (`kind`, `detail`, `how_to_close`), emitted from one
  shared helper in `_common.py` so the report CLI and `report_gate.py` cannot drift apart. The gate
  had the same defect and is fixed with it;
- `CITATION_REPORT_PDF_EXTRACTOR=none` forces the absent-extractor route, so a machine that *can*
  read PDFs still exercises the message a machine that cannot will print.

Verified: 133 checks pass with poppler present, and **131 pass with `pdftotext` off `PATH` and `pypdf`
shadowed** — the suite is environment-independent, and both branches are asserted in both
environments.

### 9.2 `paper-search`: "no package to patch" was reported as a failed check (exit 1)

`audit_fix_check.py` is a post-install checker: it looks in the uv-tool directory and, finding
nothing, printed `paper-search package not found -- install the uv tool first.` and exited 1. CI has
no uv install, so the new CI step failed on its first line for two commits. Two problems, one of them
the same rule: "there is nothing here to check" is an input gap, and it shared an exit code with
"the fix is missing from a file that is there".

Fixed: `apply_patches.py` and `audit_fix_check.py` both take `--package <path>` / `$PAPER_SEARCH_MCP_PATH`,
and both report a missing package as `insufficient_input` (exit 4) with a worklist naming what to
install and every path searched. An explicit override that does not resolve is an error rather than a
licence to patch a different install. The live-behaviour tier is `SKIP`ped — never failed — when the
uv interpreter is absent or when the tree under test is not the one that interpreter imports.

### 9.3 The gate that was missing, and the probe that proves it can fail

The patch system had never been exercised on a push at all, because the package it edits lives
outside this repository. `mcp/paper-search-patches/ci_patch_check.py` supplies the missing target: it
copies the vendored package to a temporary directory, runs the real patch pipeline against it, checks
the fixes are present, runs the availability invariant suite, and then **mutates** the copy —
renaming `SOURCE_UNAVAILABLE` to `"empty"`, which is exactly the defect the layer exists to prevent —
and asserts the suite still rejects it. A checker whose fail path is never run is an assertion, not a
gate; this one is run against its own mutant on every push.

The gate's own first CI run then failed for the same reason in a new place. Two of the availability
suite's ten tests import the package's own `server.py`, and the job's earlier steps had installed
`mcp` 2.x — which renamed `mcp.server.fastmcp` — so those two tests could not run while the other
eight passed. The suite was therefore borrowing the job's interpreter and its ambient dependencies.
It now gets a hermetic venv built from the package's own pins, and the checker **probes the imports
it needs** (`requests`, `httpx`, `bs4`, `feedparser`, `pypdf`, `mcp.server.fastmcp`) and exits 4 with
a worklist rather than reporting a pass, so a future environment change cannot silently reduce ten
tests to eight.

### 9.4 The gate itself, reviewed

The gate shipped in §9.3 was then read against its own claims, and four weaknesses were
found and fixed. They are recorded because a checker that is trusted without being checked
is the thing this repository exists to avoid.

| Weakness | Why it mattered | Fixed |
|---|---|---|
| The byte-identity check globbed `replacements/*.py` instead of reading `apply_patches.py`'s registry | a *registered* source whose vendored file was deleted or renamed was skipped silently (`if candidates and ...`), so the invariant could not see the case it most needed to | the check is driven by the `COPIES`/`NEWFILES` registry: a missing vendored target is now a finding, and a source named but absent is too |
| A file in `replacements/` that nothing applies was invisible | the directory is described as the single source of truth, so a maintainer could edit a dead file expecting an effect | unconsumed files are now a finding; the one legitimate case is an explicit `MIRRORS` entry with a written reason |
| Nothing asserted the availability suite collected any tests | a suite that collects nothing exits 0, so every check above it was a pass with no tests behind it | the `Ran N tests` count is parsed and asserted against a floor of 10, for the clean copy **and** for the mutant (a crash on import also exits non-zero and would otherwise look like a working probe) |
| `check(..., False)` for a missing mutation target raised outside the `try` | that path printed a traceback instead of the summary, and returned 1 without saying which check failed | wrapped, so it reports like every other finding |

Running the fixed check immediately produced a real finding rather than a green tick: **seven
files in `replacements/` were read by nothing** — `bookshelf_tool.py`, `ct_tool.py`,
`ncbi_tools.py`, `registry_tools.py` and `server_new_tools_{a,b,c}.py`, 759 lines in total.
Every top-level unit of all seven is byte-present in `replacements/server.py`, which *is*
applied as a whole-file replacement, so they were superseded fragments from the v1.0.0
injection mechanism (whose `INJECTS` registry is now empty). One of them,
`ncbi_tools.py`, held the **pre-fix** `get_mesh_details` — the function the MeSH audit fix
patches — so a reader could have taken it for the current implementation. They are deleted.
The eighth unconsumed file, `chemrxiv.py`, is a live module that upstream already ships; it
is kept byte-identical on purpose and is now a declared mirror with that reason written down.

**What this review does not establish:** the self-test pins the *detections* (drift, a missing
target, a dead file, a drifted mirror, the count parser, the registry being non-empty) against
synthetic trees, not the real one; the real tree is checked by the gate's own step 1. And the
`MIRRORS` allowlist is a judgement — one file is excused by a written reason, which a future
maintainer could extend without justification.

---

**What this round does not establish**, recorded so §9 is not read as a clean bill of health:

- The vendored package is kept in the patched state, so the patch run against it is idempotent by
  construction. The gate catches drift, breakage and a toothless suite; it does **not** reconstruct
  the fixed files from pristine upstream `0.1.4`, which would need those upstream files.
- `report_gate.py` and `report.py` now share one gap emitter, but the other intake failures (an
  unsupported extension, a malformed JSON sidecar) are still `INVALID_INPUT`, exit 1, by design: they
  are usage errors about the request rather than a resource that could not be read. That distinction
  is a judgement, not a measurement.
- The mutation probe proves the availability suite detects one reintroduced defect. It does not
  establish that the suite covers every way the invariant could break.
- Both CI-discovered violations were environment-dependent, which means other gates could still be
  asserting an environment. §10 addresses that for `citation-report`: its suite now branches on the
  tools installed, and the README records all three environments (137 / 139 / 144 checks). No other
  gate has been run on a machine stripped of its optional tooling, and that is how these two were
  found.

### 9.5 The availability suite, reviewed against its own claims

Asked to look deeper at §9, the next thing to check was the suite §9.3 added — the one whose
mutation probe is supposed to prove the gate has teeth. Reading it end to end found that **it tested
one direction only**.

Every test asserted that an outage *is* caught. None asserted that a working lookup is *left alone*.
A mutation that reported **every** success as an outage therefore passed the whole suite. Measured,
not argued: with `SOURCE_OK` renamed to `"unavailable"` in `source_status.py`, the ten pre-existing
tests report **OK**, and the suite as it now stands reports **FAILED**.

Five tests were added, and the gap they close is worth stating precisely:

| Test | The hole it closes |
|---|---|
| a successful lookup is not reported unavailable | specificity: nothing checked that a working source is left alone |
| an outage lands in `source_status`, not in the papers | the module docstring's user-visible claim — "so a failed lookup is never mistaken for absent literature" — was never exercised at the aggregate level |
| an empty answer is neither unavailable nor a paper | the third state, so "unavailable" cannot quietly absorb "empty" |
| a record with an `error` key and a title is still a paper | `is_unavailable_marker`'s shape rules were asserted only on real markers |
| `split_markers` separates papers from markers | the function that carries the condition through list-returning tools had no test |

The gate now asserts the suite's own count (15) as a floor and runs **two** mutation probes — an
outage named like an empty answer, and a success named like an outage — so both directions are proved
to have teeth rather than one.

**Both gaps named here were then closed**, in the fifth round: `request_json`'s retry path (a
transient status is retried and then succeeds, a transport error is retried, `Retry-After` and a JSON
`retryAfter` are honoured and capped, retries are bounded, and a 403 is *not* retried) and
`search_ladder` (a later rung succeeds after a refusal, an all-empty ladder is a real empty result, an
all-refused ladder raises rather than returning empty, and a parser bug is not an empty result). The
suite went from 15 to 28 tests, and a mutation that removes retries is caught by five of them.

---

## 10. Fifth round — the OCR tier, and the rule that keeps it honest

The user asked for a working OCR tier and chose the safety rule: **a transcription may never create a
conflict.** That is the whole design, because OCR's failure mode is not "no answer", it is "a confident
wrong answer that the tool then attributes to the author".

**What was built.** A scan (no text layer, or one below the per-page density threshold) is transcribed
with tesseract when the engine and poppler's rasteriser are both present. On by default; `--no-ocr`
refuses instead, `--ocr-lang` selects the language data, `--ocr-max-pages` bounds the work, and a scan
over that bound is refused rather than partly read. Nothing is installed or imported by the tool: both
binaries are probed with `shutil.which`, so the tier degrades to the old refusal.

**How the rule is enforced.** A contradiction now has four bars, and `D13` is the new one:

| Bar | Failure rule | State |
|---|---|---|
| the link is verified | D11 | unverifiable |
| the evidence is machine-comparable | D12 | unverifiable |
| a contradicting value exists | (the search) | — |
| neither side was transcribed | **D13** | unverifiable |

`Source.red_capable` is false for a transcribed source, so the D08 gate cannot be cleared by one; and
the *document's* transcription is checked separately, because a misread sentence value against a
correctly read source is just as false an accusation as the reverse. The note names the side that was
transcribed and what would close the gap.

**How it is labelled.** `transcribed`/`transcription` on the document and on each source, `ocr:` in a
transcribed source's `evidence_origin`, `transcription.sentences_resting_on_ocr` in `verdicts.json`,
and the same count printed in the Limits section of all three artifact formats. A run that used no OCR
prints none of it.

**What was measured, not assumed.**

| Claim | Evidence |
|---|---|
| OCR reads a real scan | a one-page image PDF built with Pillow: 178 characters, `method=tesseract`, `transcribed=true` |
| OCR misreads characters | tesseract read `95% CI` as `95% Cl` — an upper-case I as a lower-case l |
| a transcribed contradiction is not an accusation | scanned manuscript (`HR 0.50`) vs a source recording `HR 0.80`: `unverifiable`/D13, exit 0 |
| the *same words* read as text still are | the identical sentence as `.md`: `conflict`/D08, exit 1 |
| a scanned source behaves the same way | `evidence_origin = ocr:S001.pdf:tesseract:eng`, D13, and `transcribed: true` in the verdict's source record |
| the rule holds without an engine | `self_test.py` asserts a transcribed source is not `red_capable` at every red-capable strength, and that D13 is non-error — it runs on CI, which has no tesseract |

### 10.1 The four changes asked for, and what they cost

| Asked for | Done | Cost, stated |
|---|---|---|
| block by default on transcribed evidence | `insufficient_evidence` (exit 3), `TRANSCRIBED EVIDENCE` banner, `--allow-insufficient` to proceed | a scanned bibliography now needs the flag; the status and the override are both in the artifact |
| raise or remove the page cap | default 200, `--ocr-max-pages 0` = no limit, timeout scales with pages | an uncapped 900-page scan is minutes of work; it is still never partly read and presented as whole |
| a second OCR engine | `--ocr-engine auto\|tesseract\|rapidocr`; RapidOCR installed and tested; engine named in the provenance | a second dependency surface (~60 MB with onnxruntime); `--ocr-lang` is tesseract-only and says so |
| more language packs | 163 tesseract languages installed; a German scan verified (`tesseract:deu`) | 686 MB on disk; the packs are the user's, not the tool's |

The cross-engine measurement is the one worth keeping: on the same page image, **tesseract read
`95% CI` as `95% Cl` and RapidOCR read it correctly**. It is why the engine is named in the
provenance rather than assumed, and it is also why engine agreement does **not** lift the D13 bar —
the rule is about provenance, not confidence, and two engines agreeing is still a machine reading.

Two defects were found while making the blocking change, both by running it rather than reading it:
the banner used the *missing-source-evidence* wording for an OCR-blocked run (which would have told
a reader the opposite of what happened), and the `--allow-insufficient` override note was appended to
`meta["warnings"]` **after** the artifacts had been written, so it never reached one — the note was
dead code that looked like a feature.

**What this round does not establish.**

- The engine's *accuracy* is not characterised. Two pages were transcribed and one character was
  wrong; that is enough to justify the rule and nowhere near a measured error rate. No corpus of scans
  was assembled, and no per-character or per-value error rate is claimed.
- Language coverage is whatever the machine has installed. The fixtures use `eng`; a document in
  another language needs its own data, and a missing pack is an input gap rather than a silent
  fallback to English.
- Only tesseract is supported. The design is engine-shaped (probe, rasterise, transcribe, mark), but
  another engine is untested and would need its own provenance string.
- The page cap means a very long scan is refused, not read. That is deliberate — a partial reading
  presented as a whole document is the failure this repository exists to prevent — but it does mean a
  200-page scanned thesis is not graded without `--ocr-max-pages`.
- Transcription of the *document* means sentence boundaries and span offsets come from OCR text. The
  report says so, and D13 covers accusations, but a misread word could still change which sentences
  exist. Nothing here measures that.


---

## 11. Sixth round — the deferred defects, and what measuring them showed

Everything §6 and §9.5 had recorded as open, plus the four the user asked for, with the measurements
that decided each one.

### 11.1 The measure formats a real corpus writes (recall)

Four formats observed in the fetched open-access full texts were unread by the grammar: a comma
between label and value (`aOR, 3.15`), a parenthesised label (`(OR) = 2.15`), a negative estimate set
with a typographic minus (`beta = −0.22`), and the long form followed by the short form in brackets
(`risk ratio (RR) 1.42`). The grammar now accepts a `,` separator, an optional closing bracket after
the label, and a signed value, and `_to_float` normalises a Unicode minus.

The guards were the risk, and they held: `Variables OR 95% CI` (a table header), `MD 21702` (a ZIP
code) and `Treatment continued for 6 or 12 weeks` (the conjunction) are still refused, and a dash used
as a separator (`risk difference – 0.05`) is *missed rather than inverted*. All seven cases are
fixtures in `benchmarks/bench_verdicts.py`, and the safety block fails if any regresses.

### 11.2 The trigger misses were partly a measurement artefact

The four false negatives that had been recorded as a sensitivity limit turned out to be **all
digit-free**. The sample is partly digit-stripped — several sentences have had their numbers removed
before being recorded, leaving broken grammar (`scores at or above as indicative`, `attributed to -HT`,
`deriving an optimal cutoff f`) — and the tool's main trigger is the statistic one, so those sentences
cannot fire *by construction*. Restoring one plausible number to each makes all four fire.

Measured, on the sample as recorded:

| subset | n | sensitivity | specificity |
|---|---|---|---|
| all 40 sentences | 40 | 0.867 → **0.900** | 1.000 |
| sentences that still carry a number | 14 | **1.000** (9/9) | 1.000 |
| sentences whose number was removed | 26 | 0.857 | 1.000 |

So `0.867` was a floor on a handicapped sample, not an estimate of field sensitivity. Both figures are
now computed and printed, so the headline number cannot be read without the split beside it.

One genuine gap was closed anyway, under the rule that a widening is kept only if sensitivity rises
without losing specificity: `provides … evidence on|for|that` was added to the vague-attribution
pattern. It catches one of the four misses and fires on none of the ten negatives; **sensitivity
0.867 → 0.900 with real specificity 1.000 and constructed specificity 1.000** (the earlier widening
attempt broke constructed case 21, which is why that bar exists). The three remaining misses are all
digit-free; two are visibly damaged by number removal, and one is a genuine finding-claim with no
number.

### 11.3 The event loop (the defect §6 deferred as too wide)

The search path was already off the loop (`async_search` → `asyncio.to_thread`), so §6's "~35 async
tools call blocking sync searchers" was **stale for search but right about everything else**: 34 tools
— every `download_pdf`, `read_paper`, `list_categories` and `quota_status` — did blocking socket and
file I/O inside an `async def`. All 36 call sites now go through `async_call`, and the vendored file
and its patch replacement are byte-identical (the gate asserts it).

The test asserts *interleaving*, not duration: a tick of the event loop must happen while a
deliberately slow searcher is working. A direct call cannot produce one. Two mutations were run to
prove the tests bite: putting `async_call` back on the loop fails
`test_the_off_loop_helper_is_what_runs_it`, and putting `async_search` back on the loop fails
`test_a_slow_searcher_does_not_stall_the_loop`.

### 11.4 The year filter: semantics made explicit, not changed

An undated record still passes a year filter — dropping it could hide a paper that is in range, which
for a review is the worse error — but it now comes back with `_year_unknown: True`, so a caller can
tell "in range" from "not known" instead of guessing. The annotation is made on a copy (the provider's
payload is not mutated), a boolean `year` is no longer treated as year 1, and four tests pin the
behaviour including the no-year-filter case.

### 11.5 The two test gaps named in §9.5

`request_json`'s retry path and `search_ladder` now have eleven tests between them: a transient status
is retried and then succeeds, a transport error is retried, `Retry-After` and a JSON `retryAfter` are
honoured and capped, retries are bounded by `max_retries`, a 403 is *not* retried, a later rung
succeeds after a refusal, an all-empty ladder is a real empty result, an all-refused ladder raises, and
a parser bug is not an empty result. A mutation that removes retries is caught by five of them. The
suite went from 15 tests to 28 and the gate's floor moved with it.

**What this round does not establish.**

- The trigger's remaining three misses are still misses. Two look like sample damage; one
  (`provides detailed evidence on …`) is a real gap that the added pattern does not cover, and the
  sample is too small (26 digit-free positives, 10 negatives) to justify a wider rule.
- The measure-format fixtures are *formats* observed in the corpus, with sentences written for the
  test. They pin the grammar; they are not ground truth about any paper.
- The event-loop tests prove the loop is not stalled by the two helpers. They do not prove no other
  tool blocks: a new tool that calls a sync function directly would pass, because nothing enumerates
  the tools and asserts every blocking call is wrapped.
- The year-filter change adds a key to records that pass a year filter. A consumer that asserts on the
  exact key set of a record would see it; none in this repository does, and no downstream consumer was
  surveyed.

### 11.6 A flaky suite, chased rather than re-run

`verify.sh` reported `24 passed, 1 failed` once and `25 passed, 0 failed` on every re-run. The
temptation is to call it transient; the honest move is to find it, because an intermittent gate is
worse than a broken one — it teaches people to re-run until it passes.

Cause: one fixture in `skills/citation-report/scripts/selftest.sh` wrote its tampered verdict file to a
fixed global path, `/tmp/cr_badadvisory.json`. The failing run was executed **concurrently** with a
hand-run of the same suite (both were started to save time), so the two runs read each other's file.
The fixture now writes into the suite's own temporary directory, and two concurrent runs both report
154/0.

Recorded because it is the same class of defect as the rest of this file: the suite was asserting a
fact about a shared global, not about the code.
