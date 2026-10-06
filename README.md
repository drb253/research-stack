# research-stack

**Reliable literature-review tooling for AI coding agents** — the search MCP
servers plus the systematic/scoping/narrative-review and meta-analysis skills,
wired into **Cline, Claude, OpenCode** (and optionally Gemini / LM Studio) by one
command.

It is built for one promise: **no false citations, no hallucinated numbers, no
silent empty searches.** Every guard (citation verification, numeric provenance,
retraction checks, PRISMA reconciliation, screening-conduct disclosure) ships in
the skills, and the retrieval MCP is patched for the upstream defects that make
free sources silently return nothing.

---

## Quick start

**One command** (clones + installs, wires Cline by default):

```bash
curl -fsSL https://raw.githubusercontent.com/REPLACE_ME/research-stack/main/bootstrap.sh | bash
```

**Choose platforms:**

```bash
curl -fsSL https://raw.githubusercontent.com/REPLACE_ME/research-stack/main/bootstrap.sh | bash -s -- \
  --targets cline,claude,opencode --email you@org
```

**Or clone and run the installer directly:**

```bash
git clone https://github.com/REPLACE_ME/research-stack.git
cd research-stack
./install.sh --targets cline,claude,opencode,gemini,lmstudio --email you@org
```

Then **restart your client(s)** so the MCP servers are spawned, and check:

```bash
./verify.sh --targets cline,claude,opencode
```

> Edit `REPLACE_ME` to your GitHub user/org after you push the repo
> (see [Publishing](#publishing-this-repo)).

---

## What it installs

| Layer | Contents |
|---|---|
| **MCP servers** | `paper-search` (27 sources, patched), `consensus`, `google-scholar`, `ncbi`, `academic-search` |
| **Review skills** | `sysreview`, `meta-analysis`, `evidence-synthesis-forge`, `meta-analysis-forge`, `medical-narrative-review`, `umbrella-review-skeptic`, `meta-ml-screener`, `environment-life-review-forge` |
| **Guard skills** | `paper-search`, `citecheck`, `humanizerdrb`, `originality-check` |
| **Patched connectors** | 43 modules fixing arXiv/OpenAlex/Zenodo/HAL/J-STAGE/PLOS/WHO-IRIS and the MeSH query-planner |
| **Toolbox** | `originality-toolkit` (required by `originality-check`) → `~/.research-stack/originality-toolkit` |
| **Render/PDF** | `browser-probe` venv (playwright + chromium, pypdf/pypdfium2/reportlab/pillow) for DOCX/PDF export |
| **R engine** | metafor, meta, netmeta, robumeta, clubSandwich, robvis, esc, mvmeta, ggplot2 (via `install_r_packages.R`) |

Runs on **macOS and Linux**; needs `git`, `curl`, `python3`, and (for two remote
servers) `node`/`npx`. `uv` is installed automatically if missing.

---

## Options

```
--targets LIST   cline,claude,opencode,gemini,lmstudio   (default: cline)
--no-mcp         skills only
--no-skills      configure MCP only
--minimal        skip ncbi, academic-search, render toolchain and R packages
--no-ncbi / --no-academic-search / --no-render / --no-r   skip one default step
--ncbi-repo URL  override the ncbi source repo (default: upstream)
--with-upstream-skills   (default) clone the 160+ K-Dense scientific skills (MIT)
--no-upstream-skills     skip the upstream scientific skills
--copy-skills    copy skills instead of symlinking
--reinstall      reinstall/upgrade the paper-search tool first
--with-runtime   also create the Python toolchain venv (scipy/pandas/...)
--email ADDR     NCBI / polite-pool email
--ncbi-key KEY   NCBI API key          --s2-key KEY   Semantic Scholar key
--dry-run        print actions, change nothing
```

Skills are symlinked from `~/.research-stack/skills` so an update is one `git pull`.

### Installed by default (opt out with the flags above)

- **`ncbi`** — clones the upstream repo, applies `mcp/optional/ncbi-mcp-server.patch`,
  builds a venv. Only added to the config if the install actually succeeded.
- **`academic-search`** — installs the patched source tree from `mcp/optional/academic-search-mcp/`.
- **render / PDF toolchain** — `browser-probe` venv + chromium (DOCX/PDF export; downloads chromium).
- **R packages** — `install_r_packages.R` (needs R on PATH; skipped with a warning otherwise).
- **upstream scientific skills** — the 160+ K-Dense pack, symlinked alongside the 12 (skip with `--no-upstream-skills`).

Generated MCP configs carry the `autoApprove` tool lists and `timeout` values from
the working setup, so the search tools do not need per-call approval.

`--minimal` installs just the skills + `paper-search`. Every default step is
best-effort: a network failure warns and the rest of the install continues.



---

## What each client gets

| Client | Skills dir | MCP config written |
|---|---|---|
| Cline | `~/.cline/skills` | `~/.cline/data/settings/cline_mcp_settings.json` |
| Claude Desktop | `~/.claude/skills` | `~/Library/Application Support/Claude/claude_desktop_config.json` (mac) / `~/.config/Claude/...` (linux) |
| OpenCode | `~/.config/opencode/skills` | `~/.config/opencode/opencode.json` |
| Gemini CLI | `~/.gemini/skills` | `~/.gemini/settings.json` |
| LM Studio | `~/.lmstudio/skills` | `~/.lmstudio/mcp.json` |
| Trae | — | `…/Trae/User/mcp.json` |
| Cursor | — | `~/.cursor/mcp.json` |
| Windsurf | — | `~/.codeium/windsurf/mcp_config.json` |
| Codex | `~/.codex/skills` | (TOML — configure manually) |

Existing configs are **backed up** (`.bak.<timestamp>`) and only the managed MCP
keys are merged in — nothing else is touched. Generated configs are chmod `600`.

Full details: [`docs/PLATFORMS.md`](docs/PLATFORMS.md).

---

## Verify

```bash
./verify.sh --targets cline,claude,opencode
```

Checks the tool on PATH, the patch system, the MeSH audit fix, the 12 skills in
each target, and that each config is valid JSON with the servers present. Prints
`RESEARCH-STACK VERIFIED` on success.

---

## After an upgrade

The paper-search patches (and the MeSH audit fix) are **reverted by
`uv tool upgrade`**. Re-apply them:

```bash
uv tool install --reinstall paper-search-mcp --force
~/.research-stack-src/install.sh --no-skills          # re-runs apply_patches.py
# or directly:
python3 ~/.research-stack-src/mcp/paper-search-patches/apply_patches.py
```

The skills layer has its own regression suite (50 gate checks + 17 engine golden
tests + a live adversarial acceptance run):

```bash
bash ~/.research-stack/skills/evidence-synthesis-forge/scripts/selftest.sh
bash ~/.research-stack/skills/medical-narrative-review/scripts/selftest.sh   # 19 checks
```

---

## Publishing this repo

One step, once you have a GitHub account (repo is already committed):

```bash
cd research-stack
./publish.sh --user <your-github-user>      # stamps owner, sets origin, pushes
```

It replaces every `REPLACE_ME`, commits, sets `origin`, and pushes `main`. If you
are not authenticated yet, add `--no-push` and it prints the exact commands
(`gh auth login` + `gh repo create research-stack --public --source=. --push`, or a
manual `git push`).

## License & provenance

MIT — see [LICENSE](LICENSE). Bundled review skills are MIT (EvidenceForge) with
merged methodology credited in each skill's `NOTICE.md`; the upstream scientific
skills are MIT by K-Dense Inc. and are cloned, not vendored. Nothing here claims
to defeat AI- or plagiarism-detectors; the guard skills explicitly refuse that.
