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
