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

### Still open (verified as real, **not** fixed — flagged as a deliberate deferral)

- **~35 `async` MCP tools call blocking sync searchers** with no `asyncio.to_thread`, stalling the
  event loop. Real, but a wide refactor across many tools; the repo already uses `to_thread` in
  `cli.py`, so the pattern to follow exists. Deferred because the blast radius is large relative to
  the benefit (throughput, not correctness).
- **`academic-search` filters keep `year=None` records** when a year range is set. The string-year
  bypass is *not* reachable (Crossref/PubMed/OpenAlex all yield ints), and keeping undated records
  looks deliberate but is undocumented. Deferred rather than silently changing filter semantics.

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

