# Cline Research Workstation — Setup Playbook

Reproduces the setup built 18 Sep – 1 Oct 2026 on macOS (Apple Silicon).
Every command here was run and verified on the source machine; nothing is recalled.

**Who can run this:** you, by hand. Or Cline itself — paste
[AGENT_PROMPT.md](AGENT_PROMPT.md) into a fresh session and it will work through
these phases.

**Time:** ~45–60 min, mostly downloads. Phase 4.1 (paper-search patches) is the
only part that needs care.

---

## 0. Target state

When you finish you will have:

| Layer | What | Count |
|---|---|---|
| MCP servers | `paper-search`, `ncbi`, `academic-search`, `consensus`, `google-scholar`, (`laya` optional) | 6 |
| Literature sources | reachable through `paper-search` | **30 active** (28 keyless + 2 keyed), 4 retired |
| MCP tools | callable across the fleet | ~87 (`paper-search`) + 12 (`ncbi`) + 5 (`academic-search`) |
| Skills | on the `/` menu | **176** = 166 scientific + 10 custom |
| Custom skills | `medical-narrative-review`, `paper-search`, `humanizerdrb`, `citecheck`, `originality-check`, `evidence-synthesis-forge`, `meta-analysis-forge`, `umbrella-review-skeptic`, `meta-ml-screener`, `environment-life-review-forge` | 10 |
| Rendering | HTML → print-ready PDF with page previews | working |

**The one design principle everything follows:** *a source that is down must
never look like a source that found nothing.* You will see this as
`source_status`, as `unavailable` markers, and as verification gates that fail
loudly instead of passing quietly.

---

## 1. Prerequisites

| Need | Why | Check |
|---|---|---|
| **macOS 13+** or Linux | Tested on darwin/arm64. Linux works; adjust paths. | `uname -a` |
| **Cline desktop app 4.1.x+** | Agent Skills are a 4.x feature. | Cline → Settings → About |
| **Homebrew** | Easiest route for git/node. | `brew --version` |
| **git** | Clones the forks. | `git --version` |
| **uv** | Installs `paper-search-mcp` as a tool + Python 3.11. | `uv --version` |
| **Node 20+ / npm** | `npx mcp-remote` bridges two remote servers. | `node -v` |
| **Chromium browser** | Headless print-to-PDF. Edge or Chrome. | `ls /Applications/"Microsoft Edge.app"` |
| **~4 GB free disk** | Venvs, Playwright, 166 skills, git checkouts. | `df -h ~` |

> **Windows is not covered.** The `ncbi` fix in Phase 4.2 depends on POSIX
> read-only-root behaviour, and the `paper-search-mcp-patches` paths assume a
> `~/.local/share/uv/tools/` layout. You would need to adapt both.

---

## Phase 1 — Cline itself

1. Install the Cline desktop app (cline.bot) and open it.
2. Sign in / set the provider. The reference machine used:
   - Provider: **`cline-pass`**
   - Model: **`cline-free/deepseek-v4.1-flash`** (1M context, 384k max tokens)
   - Reasoning effort: **high** on both Plan and Act
3. Settings → **Auto-approve**: enable, and tick read / edit / execute / MCP.
   (Reference: max 20 requests, notifications off.)

**Verify:** Cline opens, and `~/.cline/data/globalState.json` exists.

```bash
test -f ~/.cline/data/globalState.json && echo "Cline initialised"
```

> `~/.cline/data/settings/` is where the MCP config will go. If it does not
> exist yet, launch Cline once before continuing.

---

## Phase 2 — Toolchain

```bash
# uv  (installs paper-search-mcp as a uv tool, and Python 3.11)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"     # add to ~/.zshrc too

# Python 3.11 (ncbi server is verified on 3.11.16)
uv python install 3.11

# git + node (skip whatever you already have)
brew install git node

# Chromium browser for PDF rendering
brew install --cask microsoft-edge
```

**Verify:**

```bash
uv --version && git --version && node -v && npx --version
uv python find 3.11
ls -d /Applications/"Microsoft Edge.app" 2>/dev/null || echo "Edge missing -> install Chrome instead"
```

**Note on `npx`:** the reference machine used a non-system Node at
`~/.local/bin/npx` (via `~/.hermes/node`). The MCP config hardcodes the npx
path, so **record yours now** — you will need it in Phase 5:

```bash
echo "NPX=$(command -v npx)"     # write this down
```

---

## Phase 3 — Scientific Agent Skills (166 skills)

The collection is [`K-Dense-AI/scientific-agent-skills`](https://github.com/K-Dense-AI/scientific-agent-skills).
It documents install for Cursor/Claude Code/Codex/Antigravity but **not Cline**.
Cline's real discovery paths (read out of the app runtime, not guessed):

| Scope | Directory |
|---|---|
| Global | `~/.cline/skills/<name>/SKILL.md` |
| Global (legacy) | `~/.agents/skills/<name>/SKILL.md` |
| Project | `<project>/.cline/skills/<name>/SKILL.md` |

### Option A — use the manager script (recommended)

```bash
cp portable/cline-scientific-skills ~/.local/bin/cline-scientific-skills
chmod +x ~/.local/bin/cline-scientific-skills

cline-scientific-skills install     # sparse clone + symlink every skill
cline-scientific-skills status      # what is linked now
```

### Option B — do it by hand

```bash
git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/K-Dense-AI/scientific-agent-skills.git \
  ~/.local/share/scientific-agent-skills

git -C ~/.local/share/scientific-agent-skills sparse-checkout set --no-cone \
  "/skills/" "/plugin.json" "/README.md" "/LICENSE.md"

mkdir -p ~/.cline/skills
cd ~/.cline/skills
for d in ~/.local/share/scientific-agent-skills/skills/*/; do
  ln -sfn "${d%/}" "$(basename "$d")"      # NOTE: no trailing slash on the target
done
```

> **The trailing slash matters.** With it, `readlink` resolves in a way Cline's
> `discoverSkillFiles` does not expect. The loop above strips it.

**Verify:**

```bash
ls -1 ~/.cline/skills | wc -l            # expect 166 (+10 after Phase 6)
find ~/.cline/skills -maxdepth 1 -type l | wc -l
# every SKILL.md must start with --- and carry a name: and description:
for f in ~/.cline/skills/*/SKILL.md; do
  [ "$(head -1 "$f")" = "---" ] || echo "BAD FRONTMATTER: $f"
done
```

Then **restart Cline** and type `/` — the skills appear.

---

## Phase 4 — The MCP fleet

Six servers. Install in this order — 4.1 is the most involved.

### 4.1 `paper-search` — the federated literature server

**Upstream:** `openags/paper-search-mcp` v**0.1.4**. It carries real defects
that make sources silently return nothing, so the patches are not optional for
serious work.

```bash
# 1. Install the server as a uv tool
uv tool install paper-search-mcp
# binary: ~/.local/bin/paper-search-mcp   (+ a `paper-search` CLI)

# 2. API keys
mkdir -p ~/.config/paper-search-mcp
cp paper-search.env.template ~/.config/paper-search-mcp/.env
$EDITOR ~/.config/paper-search-mcp/.env     # fill __PLACEHOLDER__s
chmod 600 ~/.config/paper-search-mcp/.env

# 3. Deploy the patch system
mkdir -p ~/.local/share/paper-search-mcp-patches
cp portable/apply_patches.py portable/verify_fixes.py portable/yield_table.py \
   ~/.local/share/paper-search-mcp-patches/
cp -R portable/replacements ~/.local/share/paper-search-mcp-patches/replacements

# 4. Apply (idempotent -- safe to re-run after any upgrade)
python3 ~/.local/share/paper-search-mcp-patches/apply_patches.py
```

`apply_patches.py` locates the package at
`~/.local/share/uv/tools/paper-search-mcp/lib/python*/site-packages/paper_search_mcp`
and must sit **next to `replacements/`** — it resolves paths from its own
directory.

---


**What the patches fix — the nine hardening tiers:**

| Tier | Fix |
|---|---|
| 1 | **Silent failures.** Non-200 now returns an explicit `unavailable` marker instead of `[]`, honours `retryAfter` (cap ~40 s), and adds a per-query `source_status`. This is the single most important change: a 429 can no longer masquerade as "no literature exists". |
| 2 | **Field-targeted queries.** openalex `title.search:`, datacite `titles.title:` + text-only, zenodo `title:`, pmc `[Title/Abstract]`, plos phrase-then-AND fallback, hal `title_t:`. |
| 3 | **Relevance re-ranking** in `search_papers` — title 2.0×, abstract 1.0×, metadata 0.5×, phrase/all-terms bonuses; results banded high/medium/low. |
| 4 | **Query planning** — free MeSH expansion, plural/stem variants, phrase-vs-AND union, dedupe by DOI. |
| 5 | **Source routing** — `sources="auto"` routes by topic domain. |
| 6 | **Retraction flagging** via OpenAlex `is_retracted` + Crossref notices. |
| 7 | **Date-serialisation crash** — `Paper.to_dict()` raised `AttributeError` when a connector supplied a date as `str`, breaking Zenodo and HAL. |
| 8 | **arXiv HTTP 406** — the connector used `requests`, which arXiv's bot mitigation rejects, so arXiv search silently returned **zero**. Replaced with a curl-backed transport. |
| 9 | **DOI-shaped query routing** — when the whole query is a DOI, resolve it exactly at Crossref (+ Unpaywall) and skip the keyword fan-out. A DOI string fuzzy-matches irrelevant records otherwise (measured: bogus DOI → 6 false hits before, **0** after). |

**Also patched:** the OpenAlex key/email was completely **inert** (hardcoded
`mailto:openags@example.com`); OpenAIRE switched to Graph API v1 (the v2 XML
endpoints hang); NCBI E-utilities key support (3 → 10 req/s); **four
upstream-broken sources retired** (`dblp`, `base`, `citeseerx`,
`google_scholar`); and new sources registered — ClinicalTrials.gov, NCBI
Bookshelf, WHO ICTRP, EU CTIS, PLOS, J-STAGE, figshare, DataCite, WHO IRIS,
OSF Preprints, OpenCitations, iCite.

**Verify:**

```bash
# MUST use the uv-tool venv python -- the script imports paper_search_mcp.
# Takes ~2.5 min (13 live network checks). Use -u or you will see no output.
~/.local/share/uv/tools/paper-search-mcp/bin/python -u \
    ~/.local/share/paper-search-mcp-patches/verify_fixes.py

# expect: 13/13 checks passed, exit 0
# ids: 1, 2, 2b, 3, 4, 4b, 4c, 5, 5b, 6, 7, 8, 9
```

> **A defect in the verifier itself was fixed** — passing a non-existent check id
> used to print `0/0 checks passed` and **exit 0 (success)**. Unknown ids now
> exit 2. If you ever see `0/0`, treat it as a failure.

---


### 4.2 `ncbi` — PubMed / MeSH / iCite

**Upstream:** `vitorpavinato/ncbi-mcp-server` v1.0.0.

**The bug:** it calls `mkdir("/.cache")` **at import time**. Cline's hub daemon
runs with `cwd=/` and every server it spawns inherits that; `/.cache` is
read-only under macOS SIP → `OSError: [Errno 30]` → **exit 1, zero bytes on
stdout** → the server dies before the MCP handshake → **Cline shows nothing at
all.** This is why an unpatched install looks like "the server just isn't there".

```bash
# 1. Clone
git clone https://github.com/vitorpavinato/ncbi-mcp-server ~/.local/share/ncbi-mcp-server
cd ~/.local/share/ncbi-mcp-server

# 2. Apply the fix (3 sites, all marked '# PATCHED:')
git apply /path/to/cline-setup/portable/ncbi-mcp-server.patch
#    If git apply fails:  patch -p1 < ncbi-mcp-server.patch
#    Or take the full history:  git clone <portable>/ncbi-mcp-server.bundle repo

# 3. Venv (verified on Python 3.11.16; the package is run via PYTHONPATH, not installed)
uv venv .venv --python 3.11
uv pip install --python .venv mcp httpx python-dotenv typing-extensions redis aiofiles

# 4. Credentials
cat > .env <<'EOF'
NCBI_EMAIL=__YOUR_EMAIL__
NCBI_API_KEY=__YOUR_KEY__
LOG_LEVEL=INFO
EOF
chmod 600 .env

# 5. Tests (72 of them; copied from portable/ because upstream does not track them)
mkdir -p tests && cp /path/to/cline-setup/portable/ncbi-tests/*.py tests/
uv pip install --python .venv pytest pytest-asyncio pytest-cov
.venv/bin/python -m pytest                 # expect 52 passed, 20 deselected
.venv/bin/python -m pytest -m integration  # expect 20 passed, 52 deselected
```

**The three patched sites:**

| File | Change |
|---|---|
| `src/ncbi_mcp_server/server.py` | cache dir → `NCBI_MCP_CACHE_DIR` or `~/.cache/ncbi-mcp-server` (absolute, cwd-independent). `analytics.json` → absolute via `NCBI_MCP_DATA_DIR`. |
| `src/ncbi_mcp_server/cache.py` | `mkdir` wrapped — failure falls back to a temp dir instead of killing the server at import. `parents=True`. |
| `cline_mcp_settings.json` | entry normalised to `"type": "stdio"`, `"disabled": false`. |

> **Reproduce Cline's exact condition to test it.** Run the server with
> `cwd=/`, only the config's four env vars, and `clientInfo: cline`.
> Handshake OK + 12 tools + `search_pubmed` returning hits = the fix holds.

**Also cleaned up:** a dead `server_old.py` (729 lines, not imported by
anything, with a pre-existing `IndentationError`) and 73 tracked `.cache/`
pickles were deleted, and a `.gitignore` rule that would have **silently
ignored a real test file** was corrected.

---


### 4.3 `academic-search` — multi-provider with Semantic Scholar

**Upstream:** PyPI `academic-search` **0.8.0** — forked because none of the six
fixes are upstream.

```bash
# 1. Restore the fork (the bundle carries the full history, commit 9b9b675)
git clone /path/to/cline-setup/portable/academic-search-mcp.bundle ~/.local/share/academic-search-mcp
cd ~/.local/share/academic-search-mcp

# 2. Venv + editable install (verified on Python 3.12.14)
uv venv .venv --python 3.12
uv pip install --python .venv -e .
# entry point: .venv/bin/academic-search  ->  academic_search.__main__:main

# 3. Tests (51, fully offline)
uv pip install --python .venv pytest
.venv/bin/python -m pytest
```

If the bundle will not clone, use the tarball instead:

```bash
mkdir -p ~/.local/share/academic-search-mcp && cd $_
tar xzf /path/to/cline-setup/portable/academic-search-mcp-src.tgz
# then create pyproject.toml from the same tarball and run step 2
```

**The six fixes:**

| # | Defect | Status |
|---|---|---|
| 1 | Author search returned 0 rows for a correct full name (`"Jennifer Doudna"` → 227 candidates, 0 kept — literal-substring matching) | fixed |
| 2 | Crossref had no relevance ranking (`"base editing"` → denture papers) | fixed |
| 3 | Junk records passed through to the top of results | fixed |
| 4 | Citation walk hard-failed on transient errors with a misleading message | fixed |
| 5 | *(found during verification)* Fix 3 was a no-op on the real junk records | fixed |
| 6 | *(found during verification)* DOI queries reported mangled metadata | fixed |

Also: S2 429s now correctly report **throttling**, not "bad identifier".

**Verify:**

```bash
.venv/bin/python verification/smoke_all_providers.py
.venv/bin/python verification/check_api_key.py     # confirms S2 key reaches the process
```

### 4.4 `consensus` — remote bridge

```bash
# No install. Cline spawns it via npx on first use.
npx -y mcp-remote https://mcp.consensus.app/mcp   # one-off handshake test
```

### 4.5 `google-scholar` — remote bridge (HasData)

```bash
npx -y mcp-remote "https://mcp.hasdata.com/mcp?apis=google_scholar"
```

> Both remote bridges need `npx` on PATH **inside the spawned process**, which
> is why the MCP config sets an explicit `PATH` and `HOME` in their `env` blocks.

### 4.6 `laya` — optional, and deliberately disabled

`NandhaKishorM/laya` was evaluated as a decision layer for the review skill and
**rejected on measured evidence**, not opinion:

- Best composed accuracy **77.2%** against a **90%** bar.
- A ledger field at 77% would silently mislabel roughly **one study in four** —
  an error neither the reader nor the gate can catch, because that column is
  hand-entered ground truth.
- The tuned run came back *worse* (51.8%), reproducing upstream's own
  long-context warning.

The MCP entry is present in the template but `"disabled": true`. Install only if
you want to re-run the evaluation — the measurement scripts live in
`~/.local/share/laya-mcp-server/` (`measure_hierarchy.py`, `measure_tuned.py`,
`sweep_head_max_len.py`, `eval/`).

> **Handshake note:** if you do install it, `LAYA_MODELS=english` +
> `LAYA_PRELOAD=0` are required or the server never completes the MCP handshake.

---


## Phase 5 — Register the servers with Cline

```bash
cp mcp-settings.template.json ~/.cline/data/settings/cline_mcp_settings.json
$EDITOR ~/.cline/data/settings/cline_mcp_settings.json
```

**Replace every placeholder.** Cline does **not** expand `~` or environment
variables in this file — every path must be literal and absolute.

| Placeholder | Value |
|---|---|
| `__HOME__` | `/Users/you` (macOS) or `/home/you` (Linux) — no trailing slash |
| `__PY311__` | absolute python3.11 — `$(uv python find 3.11)` |
| `__NPX__` | the `npx` you recorded in Phase 2 — `$(command -v npx)` |
| `__NCBI_EMAIL__` / `__NCBI_KEY__` | from Phase 8 |
| `__S2_KEY__` | from Phase 8 |

```bash
chmod 600 ~/.cline/data/settings/cline_mcp_settings.json   # it holds keys
python3 -c "import json;json.load(open('$HOME/.cline/data/settings/cline_mcp_settings.json'));print('valid JSON')"
```

**Then fully quit and reopen Cline.** MCP servers are spawned only at startup —
a window reload is not always enough.

---

## Phase 6 — The ten custom skills

These are hand-built and live in `portable/skills/`. Drop them straight in:

```bash
cp -R portable/skills/* ~/.cline/skills/
rm -rf ~/.cline/skills/*/__pycache__ ~/.cline/skills/*/scripts/__pycache__

ls -1 ~/.cline/skills | wc -l      # expect 176  (166 + 10)

# Optional: R + metafor, so meta-analysis-forge's pooling scripts run
brew install r
Rscript ~/.cline/skills/meta-analysis-forge/scripts/install_r_packages.R   # installs metafor
```

| Skill | Slash command | What it does |
|---|---|---|
| `medical-narrative-review` | `/medical-narrative-review <topic>` | End-to-end publication-ready review. Enforces `question → search log → records → verified sources → claims → prose → displays → gate`. 16 stdlib-only CLI scripts, 13 reference docs. **Blocks unverified, retracted, duplicated or fabricated references.** |
| `paper-search` | `/paper-search <topic>` | Search / download / extract across the 27 free-first sources, with the retired four explicitly excluded. |
| `humanizerdrb` | `/humanizerdrb <draft>` | Removes AI-writing tells (25-pattern catalogue) while preserving your voice. 7 tone registers. Modes: `edit`, `audit`. **Does not defeat detectors** — by design. |
| `citecheck` | `/citecheck <draft\|refs\|DOIs>` | 4 modes: `audit`, `build`, `verify`, `scan`. Crossref + OpenAlex resolution, retraction flagging, 7 citation styles. |
| `originality-check` | `/originality-check <draft>` | Pre-submission overlap check against open scholarly indexes. Backed by the toolkit in Phase 7.5. |
| `evidence-synthesis-forge` | `/evidence-synthesis-forge <topic>` | **EvidenceForge** orchestrator: protocol → eligibility → search/screening plan → extraction → synthesis type; PRISMA/Cochrane/JBI/CEE alignment and reproducibility artifacts. |
| `meta-analysis-forge` | `/meta-analysis-forge <effects>` | **EvidenceForge** first-order meta-analysis: effect-size extraction/harmonisation, fixed/random/multilevel/RVE models, heterogeneity, prediction intervals, publication-bias diagnostics. R pooling scripts need `Rscript` + `metafor`. |
| `umbrella-review-skeptic` | `/umbrella-review-skeptic <reviews>` | **EvidenceForge** review-of-reviews: primary-study overlap matrix, AMSTAR 2/ROBIS-style appraisal, second-order pooling decisions. |
| `meta-ml-screener` | `/meta-ml-screener <task>` | **EvidenceForge** human-in-the-loop ML screening: dedup, title/abstract triage, extraction assist, risk-of-bias triage, audit logs. |
| `environment-life-review-forge` | `/environment-life-review-forge <question>` | **EvidenceForge** domain adaptation for environment/ecology/biomedical/life-science reviews (PECO/PICO, spatial/GIS, causal-ML guardrails). |

> **EvidenceForge provenance.** The five `*-forge`/`screener` skills are vendored
> from [github.com/Vambrocop/EvidenceForge](https://github.com/Vambrocop/EvidenceForge)
> (MIT, vendored 2026-10-01; licence copied to `portable/skills/EvidenceForge-LICENSE.txt`).
> They are instructions-only + stdlib Python; no network, no keys. The
> `meta-analysis-forge` R scripts (`scripts/*.R`, incl. `install_r_packages.R`)
> need R installed with `metafor` (`brew install r`).

**Two things worth knowing:**

- **Skill discovery happens at startup.** If a new skill does not autocomplete
  after a restart, the skill folder is the thing to check — not the code.
- **A skill cannot call MCP tools from Python.** The *agent* calls the tools and
  pipes results in. `citecheck`'s `format` subcommand exists to normalise those
  payloads; it was validated against real tool output, which is not the same as
  a full end-to-end agent run.

---

## Phase 7 — Rendering toolchain (PDF + previews)

Every review project renders HTML → print-ready PDF through Playwright and a
Chromium browser, then rasterises pages for visual QA.

```bash
uv venv ~/.local/share/browser-probe/.venv --python 3.11
uv pip install --python ~/.local/share/browser-probe/.venv \
    -r portable/browser-probe.requirements.txt

# Playwright's browser download is separate
~/.local/share/browser-probe/.venv/bin/python -m playwright install chromium
```

Verified versions: `playwright 1.63.0`, `pypdf 6.19.0`, `pypdfium2 5.13.0`,
`reportlab 5.0.1`, `pillow 12.3.0`.

The render scripts expect the browser-probe interpreter by absolute path, e.g.:

```bash
~/.local/share/browser-probe/.venv/bin/python render_pdf.py
```

**Verify:**

```bash
~/.local/share/browser-probe/.venv/bin/python - <<'PY'
import playwright, pypdf, pypdfium2, reportlab, PIL
print("render toolchain OK")
PY
```

### 7.5 Optional — the originality toolkit

The `originality-check` skill expects its toolkit at
`~/Documents/Cline/originality-toolkit/`. It is **8 stdlib-only files, zero
dependencies** (`originality_check.py`, `cite_fix.py`, `paraphrase_brief.py`,
`outline.py`, `style_pass.py`, `sources.py`, `htmltext.py`, `check.sh`).

Copy it from the source machine, or read its `README.md` — which is
self-contained enough to rebuild from.

> **Design guarantee worth preserving if you edit it:** `style_pass.py`
> structurally **refuses** to edit any sentence the originality report flagged,
> and the membership test is **fuzzy (≥ 0.85 similarity)**, not exact, so a
> re-split line cannot slip a sourced sentence past it.

### 7.6 Optional — Mermaid diagram rendering

```bash
npm install -g @mermaid-js/mermaid-cli     # provides `mmdc`
mmdc --version
```

Used by `paper-search-mcp-diagrams/render-and-lint.sh`.

---


## Phase 8 — API keys

All free. Every one is optional, but the first two are decisive.

| # | Key | Where to get it | Why it matters |
|---|---|---|---|
| 1 | **Unpaywall email** | just your email | **Without it the Unpaywall fallback is SKIPPED** — no free PDF resolution for paywalled papers. |
| 2 | **OpenAlex email** | just your email | **Decisive.** Anonymous OpenAlex search is rate-limited; with the polite-pool email it returns results. |
| 3 | NCBI API key | ncbi.nlm.nih.gov/account/settings | 3 → **10 req/s** on pubmed, pmc, MeSH, iCite, ID converter |
| 4 | Semantic Scholar | semanticscholar.org/product/api | 1 req/s (cumulative across all endpoints) |
| 5 | CORE | core.ac.uk/services/api | raises limits |
| 6 | Elsevier (optional) | dev.elsevier.com | Scopus metadata. **No insttoken = search + abstracts only.** |
| 7 | Springer Nature (optional) | dev.springernature.com | **Two separate keys** (Meta + Open Access), each 500/day |

**Where they go:**

| File | Contains | Perms |
|---|---|---|
| `~/.config/paper-search-mcp/.env` | all 7 | `600` |
| `~/.local/share/ncbi-mcp-server/.env` | NCBI email + key | `600` |
| `~/.cline/data/settings/cline_mcp_settings.json` | NCBI + S2 (inline in `env` blocks) | `600` |

**Two warnings:**

1. **Rotate anything you have ever pasted into a chat.** On the source machine
   several keys were pasted in plaintext and remain unrotated, including one
   recovered from shell history.
2. **Setting `ELSEVIER_API_KEY` or the Springer keys makes `sources="all"`
   include them.** There is no caching, so every broad sweep burns quota
   (Springer 500/day, Elsevier 20,000/week). Use `sources="auto"` or an explicit
   source list instead.

---

## 9. Verification — the acceptance test

Run these in order. If all pass, the setup is complete.

```bash
# 1. Cline + config
python3 -c "import json;json.load(open('$HOME/.cline/data/settings/cline_mcp_settings.json'));print('MCP config valid')"

# 2. Skills
echo "skills: $(ls -1 ~/.cline/skills | wc -l | tr -d ' ')  (expect 176)"

# 3. paper-search binary
command -v paper-search-mcp && paper-search-mcp --help >/dev/null && echo "paper-search OK"

# 4. paper-search patches  (uv-tool python + -u; ~2.5 min)
~/.local/share/uv/tools/paper-search-mcp/bin/python -u \
    ~/.local/share/paper-search-mcp-patches/verify_fixes.py   # 13/13

# 5. ncbi tests
cd ~/.local/share/ncbi-mcp-server && .venv/bin/python -m pytest -q   # 52 passed

# 6. academic-search tests
cd ~/.local/share/academic-search-mcp && .venv/bin/python -m pytest -q  # 51 passed

# 7. render toolchain
~/.local/share/browser-probe/.venv/bin/python -c "import playwright,pypdf,pypdfium2,reportlab;print('render OK')"
```

**Or just run the packaged script**, which does all of the above and prints a
pass/fail summary:

```bash
bash cline-setup/verify-setup.sh
# expect: RESULT: 31 passed, 0 failed   ->   SETUP VERIFIED
```

Then **inside Cline**, confirm the tool surfaces exist:

| Check | Expect |
|---|---|
| Type `/` | 176 skills listed, including the 10 custom ones |
| Ask for the MCP tool list | ~87 `paper-search__*` + 12 `ncbi__*` + 5 `academic-search__*` tools |
| Run a real search | `paper-search__search_papers` with `query="CRISPR base editing"`, `sources="auto"` → returns hits **and** a `source_status` block |
| Check the honesty layer | Any source that is down appears as **`unavailable`**, never as `0 results` |
| Run the DOI gate | A bogus DOI-shaped query returns **0** results (not 6 fuzzy matches) |

**The one test that matters most:**

```bash
# Confirm "unavailable" is reported rather than swallowed.
# Temporarily break a source URL, or catch a real 503, and check that
# search_papers reports  source_status: unavailable (HTTP 503)
# and NOT  "0 results".
```

If you see `0 results` for a source you know is down, **the Tier-1 patch did not
apply.** Re-run `apply_patches.py` and restart Cline.

---

## 10. What is machine-specific

Change these on a new machine. Everything else is portable.

| Thing | Source machine | You |
|---|---|---|
| Home dir | `/Users/drb` | `$HOME` — every path in the MCP config is literal |
| `npx` | `~/.local/bin/npx` (Node via `~/.hermes/node`) | `$(command -v npx)` |
| Python 3.11 | `~/.local/share/uv/python/cpython-3.11-macos-aarch64-none/bin/python3.11` | `$(uv python find 3.11)` |
| Browser for PDF | `Microsoft Edge.app` | Edge or Chrome; edit the render scripts' browser path |
| OS | macOS arm64 | Linux works; **Windows does not** (see §1) |

**Nothing else is machine-bound.** The patches locate the package by glob, the
skills are symlinks or plain folders, and every venv is self-contained.

---


## 11. Upstream defects fixed — re-apply after any upgrade

**This is the most important maintenance rule.** `uv tool upgrade` and
`git pull` will revert these fixes. After any upgrade, re-run
`apply_patches.py` and re-verify.

| Project | Version | Defect | Fixed by |
|---|---|---|---|
| `paper-search-mcp` | 0.1.4 | non-200 → `[]` (silent zeros) | `apply_patches.py` |
| | | `retryAfter` ignored | |
| | | OpenAlex key + polite email inert | |
| | | `Paper.to_dict()` `AttributeError` on str dates → Zenodo/HAL broken | |
| | | arXiv HTTP 406 (requests) → silent zero results | |
| | | OpenAIRE v2 XML endpoints hang | |
| | | biorxiv/medrxiv ignored the query entirely | |
| | | `sources="all"` included retired sources | |
| `ncbi-mcp-server` | 1.0.0 | `mkdir("/.cache")` at import → dies under `cwd=/` | `ncbi-mcp-server.patch` |
| | | dead `server_old.py` + tracked `.cache/` | |
| | | `.gitignore` hid a real test file | |
| `academic-search` | 0.8.0 | literal-substring author match → 0 rows | `academic-search-mcp.bundle` |
| | | Crossref had no relevance ranking | |
| | | junk records at top of results | |
| | | citation walk hard-failed on transients | |
| `laya` | — | MCP handshake never completed | `LAYA_MODELS=english` + `LAYA_PRELOAD=0` |

**Post-upgrade routine:**

```bash
uv tool upgrade paper-search-mcp
python3 ~/.local/share/paper-search-mcp-patches/apply_patches.py
~/.local/share/uv/tools/paper-search-mcp/bin/python -u ~/.local/share/paper-search-mcp-patches/verify_fixes.py  # must be 13/13
# then restart Cline
```

---

## 12. Rollback

Every fix is reversible without re-cloning.

| Want to undo | Do this |
|---|---|
| paper-search patches | `apply_patches.py` backs up each file before writing; restore from the `.bak` files it leaves beside the originals, or `uv tool install --force paper-search-mcp` for a clean copy |
| ncbi patches | `grep -rn PATCHED src/` finds all 3 sites; `git checkout src/` reverts them |
| academic-search fork | `git -C ~/.local/share/academic-search-mcp checkout 9b9b675` (the fork commit) or reinstall `academic-search==0.8.0` from PyPI |
| Custom skills | `rm -rf ~/.cline/skills/<name>` |
| Scientific skills | `cline-scientific-skills unlink` (all) or `unlink <name>` |
| MCP config | backups exist from the source machine's work, e.g. `cline_mcp_settings.json.bak-before-academic-search-fork-*` |
| Everything | delete `~/.cline/skills/*`, `~/.local/share/*-mcp*`, `~/.config/paper-search-mcp/` |

---

## Appendix A — File map

```
~/.cline/
├── skills/                          # 176 entries (166 symlinks + 10 real)
└── data/
    ├── globalState.json             # provider, model, auto-approve
    └── settings/
        └── cline_mcp_settings.json  # the 6-server config  (chmod 600)

~/.config/paper-search-mcp/.env      # API keys               (chmod 600)

~/.local/bin/
├── paper-search-mcp                 # MCP server binary
├── paper-search                     # CLI
└── cline-scientific-skills          # skill manager

~/.local/share/
├── scientific-agent-skills/         # git checkout of the 166-skill pack
├── uv/tools/paper-search-mcp/       # the installed package the patches edit
├── paper-search-mcp-patches/        # apply_patches.py + 43 replacements + ARCHITECTURE.md
├── ncbi-mcp-server/                 # patched clone (Python 3.11.16 venv)
├── academic-search-mcp/             # fork 0.8.0+local1 (Python 3.12.14 venv)
├── browser-probe/.venv/             # playwright + pypdf + pypdfium2 + reportlab
└── laya-mcp-server/                 # optional; evaluation scripts + eval/

~/Documents/Cline/
├── cline-setup/                     # THIS package
├── originality-toolkit/             # 8 stdlib-only tools (Phase 7.5)
├── review-agentic-ai-phc-india/     # S/C-ID ledger + gate report
├── sca7-report/                     # 2 PDFs + render scripts
├── ppiuccd-study/                   # extraction + gap analysis
├── paper-search-mcp-diagrams/       # 10 SVGs + render-and-lint.sh
├── paper-search-mcp-flow.md         # 692-line architecture doc
├── agentic-ai-india-review/         # narrative + scoping PDFs
├── agentic-ai-india-critical-review/# 32-page critical review
├── agentic-ai-phc-india-systematic-review/  # 46-page SR + renumber.py
├── downloads/                       # fetched PDFs + extractions
└── Hooks/, Workflows/               # empty scaffolding (unused)
```

**Source counts to sanity-check against:**

| Thing | Count |
|---|---|
| MCP servers configured | 6 |
| `paper-search` tools | ~87 |
| `paper-search` sources registered / active / retired | 34 / **30** / 4 |
| Replacement modules in the patch set | 43 |
| `verify_fixes.py` checks | 13 |
| ncbi tests | 72 (52 offline + 20 integration) |
| academic-search tests | 51 |
| Skills total | **176** (166 + 10) |
| medical-narrative-review CLI modules | 16 |

---


## Appendix B — Troubleshooting

Every entry below is a failure that actually happened on the source machine.

### An MCP server shows nothing at all in Cline

Not "errors" — *nothing*. Usually a server that dies **before the handshake**.

```bash
# Run it by hand with Cline's exact conditions and watch stderr
cd ~/.local/share/ncbi-mcp-server
env -i HOME="$HOME" PATH="$PATH" PYTHONPATH="$PWD/src" \
    NCBI_EMAIL=x NCBI_API_KEY=y LOG_LEVEL=INFO \
    .venv/bin/python -m ncbi_mcp_server.server </dev/null
```

If it exits non-zero with **zero bytes on stdout**, it crashed at import. The
known cause is a `cwd`-relative `mkdir` under `cwd=/` — see Phase 4.2.

### `verify_fixes.py` crashes, hangs, or prints nothing

Three separate traps, all hit while testing this runbook:

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'paper_search_mcp'` | Run with the **system** python3. The script imports the package. | Use the uv-tool venv python: `~/.local/share/uv/tools/paper-search-mcp/bin/python` |
| Hangs with **zero output** | Python **buffers stdout** when redirected to a file | Add `-u` (unbuffered): `python -u verify_fixes.py` |
| `setsid: command not found` | macOS has no `setsid` | Detach with the subshell idiom: `(nohup cmd > out 2>&1 </dev/null &)` |

**It is also slow.** The 13 checks make live network calls and take **~2.5
minutes**. Do not assume a hang. A correct run ends with:

```text
13/13 checks passed
```

### A source reports `0 results` but you know it is up

**The Tier-1 patch is not applied.** That is exactly the defect it fixes.

```bash
python3 ~/.local/share/paper-search-mcp-patches/apply_patches.py
~/.local/share/uv/tools/paper-search-mcp/bin/python -u ~/.local/share/paper-search-mcp-patches/verify_fixes.py
# restart Cline
```

### My fixes are not taking effect

**You did not restart Cline.** Python imports modules once at startup. On the
source machine the live MCP processes were **~30 hours older** than the patched
files on disk — the code was correct, but the running session was pre-patch.

Fully quit and reopen the app (not just a window reload), and remember LM Studio
/ Claude Desktop each need their own restart.

### `No module named pytest` when running a fork's tests

`pytest` is **not** a runtime dependency of either fork, so the venv you create
in Phase 4 does not have it. Install it per-venv:

```bash
uv pip install --python ~/.local/share/academic-search-mcp/.venv pytest
uv pip install --python ~/.local/share/ncbi-mcp-server/.venv pytest pytest-asyncio pytest-cov
```

Then: **51** tests for academic-search, **72** for ncbi (52 offline + 20
`integration`).

### A new skill does not autocomplete

Skill discovery happens **at startup**. Restart, then check the Skills tab is
toggled on. If it still fails, the fault is almost always the SKILL.md
frontmatter — a **colon-space in `description`** broke `/humanizerdrb` on the
source machine. Validate:

```bash
head -5 ~/.cline/skills/<name>/SKILL.md    # must open with --- and parse as YAML
```

### `verify_fixes.py` prints `0/0 checks passed`

A **fixed bug in the verifier** — a non-existent check id used to silently skip
and exit 0 (success). Current versions exit 2. If you see `0/0`, your
`verify_fixes.py` is the old one; re-copy it from `portable/`.

### arXiv returns nothing

The `requests`-based connector gets HTTP 406 from arXiv's bot mitigation.
The patch replaces it with a curl-backed transport. Re-run `apply_patches.py`.

### Zenodo / HAL raise `'str' object has no attribute 'isoformat'`

`Paper.to_dict()` cannot serialise a str date. Fixed by the date helpers in
`apply_patches.py`. Re-run it.

### `pmc` search is slow, or ~50% HTTP 500

Unpatched, `pmc` uses NCBI E-utilities directly. The patch routes it via Europe
PMC: **~20 s → 1.1 s**, 500 rate → 0, and full text goes from a 173-char error
string to **127,685 chars in 1.5 s**.

### Google Scholar returns nothing

The in-`paper-search` connector needs a proxy and is **retired**. Use the
dedicated `google-scholar` MCP server (HasData bridge) instead — Phase 4.5.

### `npx` not found inside an MCP server

Remote bridges spawn a child process that needs its own `PATH`. The template
sets `PATH` and `HOME` explicitly in the `consensus` and `google-scholar` `env`
blocks. Point `__NPX__` at an absolute path.

### Playwright cannot find a browser

```bash
~/.local/share/browser-probe/.venv/bin/python -m playwright install chromium
```

Or edit the render script to use your Edge/Chrome path.

### A PDF has blank pages or a wrong TOC

Both are real defects that were caught and fixed on the source machine, and both
have regression checks you should keep:

- **Blank pages / footers:** the render scripts assert page count, per-page text
  length, and footer `N / M`.
- **TOC page numbers:** extract the real heading pages and rewrite the TOC — do
  not guess. (One shipped document had guessed TOC numbers.)
- **Uncited references:** `render_pdf.py` parses the HTML and **splits at the
  references `<ol>`** so a reference's own number cannot masquerade as a
  citation. This caught 3 genuinely uncited references.
- **Citation order (systematic reviews):** ICMJE/Vancouver requires numbering by
  **first citation in text**, not thematically. `renumber.py` recomputes it, and
  `build.py` asserts the body's order is exactly `1..N`.

### A source is rate-limited (429 / 503)

**This is expected and by design.** The system's guarantee is that it is
**reported as `unavailable`**, never disguised as "0 papers". Retry is a client
decision. If you want fewer of them: set the polite-pool emails (Phase 8, items 1–2) and
prefer `sources="auto"` over `sources="all"`.

---

## Appendix C — Deliberately NOT done

Recorded so a future setup does not "fix" these by accident.

| Not done | Why |
|---|---|
| Enabling `laya` as a decision layer | 77.2% vs a 90% bar — would silently mislabel ~1 study in 4 |
| Caching `sources="all"` to stop quota burn | Offered; declined on the source machine. **Still an open risk.** |
| Getting an Elsevier insttoken | Search + abstracts only without it |
| Using Sci-Hub tools | Present in the package, deliberately unused |
| Unlinking the unused scientific skills | All 166 stay linked, so the `/` menu and context stay large |
| Detector-evasion in any skill | `humanizerdrb`, `citecheck` and `originality-check` all refuse by design — attribution is the goal, not evasion |

---

*Generated from the live machine state on 1 Oct 2026. Every count, path and
version in this document was read off disk or out of the Cline session database,
not recalled.*

