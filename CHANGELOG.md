# Changelog

All notable changes to **research-stack** are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- GitHub Actions CI (`.github/workflows/ci.yml`): a `lint` job on Ubuntu + macOS
  (shell syntax, Python syntax, offline logic self-tests, the medical-narrative
  selftest) and an `r-tests` job that runs the meta-analysis golden tests and the
  evidence-synthesis gate suite.
- This changelog.
- **`benchmarks/`** — six reproducible harnesses that measure how well the gates
  actually work, against ground truth independent of the tool: retraction detection
  vs NLM-curated publication types (920 real citations), the arithmetic gate, and
  three overlap-detection sets including **real** bioRxiv/medRxiv preprint→published
  pairs and the **US ORI guide's own expert-labelled** paraphrasing exercise.
  Measured: retraction 100%/100% with a **99.17% Wilson lower bound**; overlap 100%
  sensitivity (95% CI 93.4–100%) and 100% specificity on real pairs; 6/6 agreement
  with ORI verdicts; **0 unsafe accepts in 920 citations**.
- `docs/BENCHMARK-RESULTS.md` (method, numbers, caveats) and
  `docs/AUDIT-FINDINGS.md` (code/docs audit: every defect found, fixed and re-verified).
- `originality_check.py --corpus PATH` — compare a draft against **any local text**
  (paywalled PDFs via optional `pypdf`, theses, books, unpublished manuscripts, saved
  web pages), in addition to the five open APIs or alone (`--sources ""`, fully
  offline). Unreadable files are reported, never silently skipped; an empty corpus
  warns loudly.
- Quotation awareness (ORI Guideline 2): a quoted verbatim run returns
  `QUOTED (verbatim; verify the citation)` and is **not** counted as a violation,
  while the same words unquoted remain `QUOTE + CITE (verbatim)`.
- Correction/erratum detection (ORI Guideline 17): `is-corrected-by`, `update-to`
  correction types and `erratum`/`corrigendum` records are reported as a **warning**,
  not a failure. Retraction remains a hard failure.

### Fixed
- `cross_verify_citations.py` — a DOI that is **not Crossref-registered** took an
  alternative-agency branch that returned *before any retraction check ran*, so a
  retracted paper could be reported `verified`. The three signals now run on both
  paths via a shared `apply_retraction_signals()`. This was the single missed
  retraction in the 920-citation benchmark; fixing it produced zero misses and the
  99% lower bound. Two offline regression guards added (helper + wiring).
- `cross_verify_citations.py` — retracted titles carry a `RETRACTED:`/`RETRACTED
  ARTICLE:` prefix at Crossref that PubMed's title lacks, so identical papers were
  reported as *"DOI resolves to a different paper"* (13 of 15 flagged mismatches).
  Prefixes are now stripped before comparison; flagged mismatches fell 15 → 2, and
  the 2 survivors are genuinely different papers.
- `check_numbers.py` — a significance claim and its p-value on **different lines**
  were downgraded to a warning and the manuscript **passed**. The check now joins a
  wrapped continuation line (only when the line does not end a sentence, so a later
  unrelated p-value is not attached to the claim). Sensitivity 87.5% → 100%.
- `paper-search-mcp` — `NameError` on every CiteSeerX PDF download (`os` never
  imported) and on every Elsevier full-text fetch (`assert_usable_bytes` never
  imported); fixed in the vendored file *and* its patch copy.
- `paper-search-mcp/cli.py` — duplicate `ALL_SOURCES` entries overwrote live
  coroutines (`RuntimeWarning: coroutine '_async_search' was never awaited`) and
  dropped results; `chemrxiv` was missing from the CLI registry entirely (27 vs 28
  sources). Both fixed; CLI and server now agree.
- `ncbi-mcp-server` — `CachedNCBIClient` had no `close()`, so every shutdown raised
  `AttributeError` and leaked the HTTP client; `advanced_search` silently dropped
  one-sided date ranges; analytics lost all data on a single unknown JSON key;
  `progressive_search` returned ~80% duplicate PMIDs.
- `ncbi-mcp-server/requirements.txt` — could not produce a working server: missing
  `python-dotenv`/`aiofiles`, and unconstrained `mcp>=1.0.0` pulled mcp 2.x and broke
  the v1 API. Now pins `mcp>=1.0.0,<2`.
- `install.sh` — an unexpanded glob created a symlink literally named `*` in the
  skills directory when a source list was empty; guarded.
- `academic-search-mcp` — `stats.py` emitted `NaN`, breaking strict-JSON clients.
- `originality_check.py` — default `--threshold` lowered 0.35 → 0.30 from measured
  score separation (independent text ≤ 0.115, copying ≥ 0.319); 0.35 missed light
  edits.
- Seven executable files hardcoded `/Users/drb/...` paths, so they only worked on one
  machine; now resolved relative to the script.
- Documentation accuracy: IEEE/ACM were advertised as working keyed sources but always
  raise `NotImplementedError` even with a key; "77 tools" → 87; "27 sources" → 28
  (27 work with zero config); "49 tests" → 51; `verify.sh --help` documented but
  absent; "each `NOTICE.md`" (3 of 12); "local CLIs make no network calls" (7 use
  `urllib.request`); the composition chart claimed 400 tracked files against 402
  (now derived from `git ls-files` and self-checking).

### Known limitations
- **ORI Guideline 4 (syntactical structure) is not caught.** A paraphrase that changes
  every content word but keeps the source's sentence structure is plagiarism under the
  ORI guide yet scores near zero on lexical overlap. Two stdlib-only frame measures were
  implemented and measured; neither separates frame-copying from unrelated text
  (unrelated reached 0.857 against frame-copies from 0.533), so the frame number is
  reported but drives no verdict. **A clean report does not cover frame-copying.**
- Retraction and resolution benchmarks are live (network-dependent) and were run on one
  day; provider-side changes could move the numbers.

## [1.0.0] — 2026-10-07

First release: reliable literature-review tooling for AI coding agents.

### Added
- **One-command installer** (`install.sh`, `bootstrap.sh`) that wires MCP servers
  and skills into Cline, Claude, OpenCode, Gemini, LM Studio, Trae, Cursor and
  Windsurf (+ Codex skills). Non-destructive — existing configs are backed up and
  only managed keys are merged.
- **5 MCP servers**: `paper-search` (27 free sources), `ncbi`, `academic-search`,
  `consensus`, `google-scholar`.
- **12 review/guard skills**: `sysreview`, `meta-analysis`,
  `evidence-synthesis-forge`, `meta-analysis-forge`, `medical-narrative-review`,
  `umbrella-review-skeptic`, `meta-ml-screener`, `environment-life-review-forge`,
  `paper-search`, `citecheck`, `humanizerdrb`, `originality-check`.
- **Gates** that make a false citation, a number nobody computed, or a
  contradictory PRISMA flow fail loudly instead of passing quietly.
- **Vendored MCP sources** (installed offline, no PyPI / upstream dependency):
  `mcp/paper-search-mcp/` (upstream `v0.1.4` + 43 patched modules),
  `mcp/ncbi-mcp-server/` (patched fork), `mcp/academic-search-mcp/` (`0.8.0+local1`).
- **`originality-toolkit`** (23 files) and `verification_report.py`.
- **103 automated checks**: evidence-synthesis-forge selftest (50),
  meta-analysis-forge golden tests (17), medical-narrative-review selftest (19),
  live adversarial acceptance run (17).
- **Charts** (`assets/*.svg`) and their generator (`scripts/make_readme_charts.py`).

### Fixed
- **MeSH query planner** expanded common words to a *subheading's* entry terms
  (`screening → diagnosis, signs, findings, symptoms`); it now reads NCBI's
  authoritative mapping (`screening → mass screening, early detection of cancer`).
- Vendored `paper-search-mcp` `pyproject.toml` under-constrained `mcp[cli]` (a
  fresh install pulled mcp 2.x and broke import) → pinned `mcp[cli]>=1.27.2,<2`
  and `fastmcp>=3.4.2,<4`, matching the working environment.
- Installer `cp -R` failed when a destination's parent directory did not exist
  (added `mkdir -p`); the `ncbi` install omitted `aiofiles`, required by the server.
- Skills hard-coded `~/.cline/skills` (broke parity on Claude/OpenCode) → made
  location-independent; `ncbi`/`academic-search` were configured but not installed.

### Changed
- `install.sh` installs `paper-search` from the **vendored source** by default;
  `--from-pypi` keeps the legacy PyPI + runtime-patch path.

### Security
- No secrets in the repository (secret-scanned); the vendored forks deliberately
  exclude their `.env*` files; the installer writes configs and `.env` with
  mode `600`.

[Unreleased]: https://github.com/drb253/research-stack/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/drb253/research-stack/releases/tag/v1.0.0
