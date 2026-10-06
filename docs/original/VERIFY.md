# VERIFY.md — the acceptance test

Run this **last**, after a full quit-and-reopen of Cline.

Nothing here is a formality. Each check corresponds to a real defect that was
found on the source machine; a failure means that specific defect is present.

---

## Part 1 — Automated (run in a terminal)

The runnable script is **[verify-setup.sh](verify-setup.sh)** in this folder.

```bash
bash cline-setup/verify-setup.sh
```

It runs 6 groups of checks and prints `SETUP VERIFIED` or a list of failures.

**Expected output on a correct machine** (this is the real recorded run):

```text
== 1. Cline config ==
  PASS  MCP config exists and is valid JSON
  PASS  config perms 600
  PASS  server 'paper-search' present
  PASS  server 'ncbi' present
  PASS  server 'academic-search' present
  PASS  no placeholders left in config
== 2. Skills ==
  PASS  176 skills present
  PASS  166 scientific symlinks
  PASS  custom skill 'medical-narrative-review'
  PASS  custom skill 'paper-search'
  PASS  custom skill 'humanizerdrb'
  PASS  custom skill 'citecheck'
  PASS  custom skill 'originality-check'
  PASS  custom skill 'evidence-synthesis-forge'
  PASS  custom skill 'meta-analysis-forge'
  PASS  custom skill 'umbrella-review-skeptic'
  PASS  custom skill 'meta-ml-screener'
  PASS  custom skill 'environment-life-review-forge'
  PASS  all SKILL.md frontmatter opens with ---
== 3. paper-search ==
  PASS  paper-search-mcp on PATH
  PASS  patch system deployed
  PASS  uv-tool python found
        PASS 9 DOI query routing   strict=True; real DOI total=1; bogus DOI total=0 (was 6)
        13/13 checks passed
  PASS  verify_fixes.py: 13/13 checks passed
  PASS  paper-search .env present
  PASS  Unpaywall email set (PDF resolution enabled)
  PASS  OpenAlex email set (polite pool)
== 4. ncbi ==
  PASS  ncbi patches applied (3 markers)
  PASS  ncbi tests pass (52)
== 5. academic-search ==
  PASS  academic-search entry point
  PASS  academic-search tests pass (51)
== 6. Render toolchain ==
  PASS  render toolchain imports

RESULT: 31 passed, 0 failed
SETUP VERIFIED
```

### Four things that will bite you (all discovered by running it)

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'paper_search_mcp'` | `verify_fixes.py` was run with the **system** python3 | Run it with the uv-tool venv python: `~/.local/share/uv/tools/paper-search-mcp/bin/python` |
| The verifier seems to hang with **no output** | Python **buffers stdout** when redirected | Add `-u`: `python -u verify_fixes.py` |
| `setsid: command not found` | macOS has no `setsid` | Use the `(nohup ... &)` subshell idiom to detach |
| `academic-search tests FAIL` / `No module named pytest` | pytest is **not** a runtime dep of that fork | `uv pip install --python ~/.local/share/academic-search-mcp/.venv pytest` |

**Timing:** `verify_fixes.py` makes live network calls across all 13 checks and
takes **~2.5 minutes**. Do not assume a hang.

The full 13/13 output looks like this:

```text
PASS 1 europepmc search                       5 papers in 1.3s, abstracts=True
PASS 2 pmc search (Europe PMC route)          3 papers in 0.9s (was ~20s, ~50% HTTP 500)
PASS 2b pmc full text (JATS)                  127685 chars in 6.5s (was a 173-char error string)
PASS 3 fan-out bounded (<60s)                 wall=45.2s total=67 unavailable=1
PASS 4 biorxiv category verified              invalid rejected=True; valid=2 all-cancer=True
PASS 4b biorxiv JATS full text                26810 chars of article body
PASS 4c journal crosswalk                     10.1162/IMAG.a.1376 -> Imaging Neuroscience
PASS 5 bookshelf table locator                3 tables
PASS 5b bookshelf bot-wall honest             bot wall detected and reported (not silent)
PASS 6 MCP tool registry                      87 tools; new tools present=True
PASS 7 keyed publisher sources                springer meta=True openaccess=True; elsevier=True entitlement=False
PASS 8 citation export (retraction-aware)     entries=2 retracted=1 unavailable=1
PASS 9 DOI query routing                      strict=True; real DOI total=1; bogus DOI total=0 (was 6)

13/13 checks passed
```

Note check 3: `unavailable=1` — a source genuinely failed during that run and was
**reported**, not swallowed. That is the system working correctly.

---

## Part 2 — In Cline (after a full quit and reopen)

| # | Do this | Expect | If it fails |
|---|---|---|---|
| 1 | Type `/` | **176** skills listed, incl. the 10 custom ones | Discovery is at startup — you did not fully restart, or frontmatter is malformed |
| 2 | Ask Cline to list its MCP tools | ~87 `paper-search__*`, 12 `ncbi__*`, 5 `academic-search__*` | Server died before the handshake — SETUP.md App. B |
| 3 | `paper-search__search_papers` `query="CRISPR base editing"`, `sources="auto"` | Hits **plus** a `source_status` block | Tier-1 patch not applied |
| 4 | Same call — inspect each source's status | `ok`, `empty`, or **`unavailable`** | A source reporting `0 results` while down = patch missing |
| 5 | Same tool, a **bogus DOI** as the whole query | **0** results | Tier-9 routing missing (unpatched ≈ 6 fuzzy matches) |
| 6 | `paper-search__plan_search_query` `query="agentic AI primary healthcare India"` | Query variants, MeSH terms, domain, recommended sources | Tier-4/5 missing |
| 7 | `paper-search__check_retraction` on a known-retracted DOI | Reports retracted, with the notice | Tier-6 missing |
| 8 | `ncbi__search_pubmed` `query="CRISPR"` | Returns hits (not an error, not nothing) | The `mkdir("/.cache")` bug is present |
| 9 | `academic-search__search_by_author` `author_name="Jennifer Doudna"` | Returns rows | Fork fix #1 missing (unpatched returns 0) |
| 10 | `/medical-narrative-review` a small topic | Produces `scope.md` + ledger skeleton; gate runs | Skill not registered |
| 11 | `/humanizerdrb` on a paragraph | An edit **plus** a "What changed" list | Skill not registered |
| 12 | `/citecheck` on a DOI | Resolves at Crossref, formats a citation | Skill not registered |

---

## Part 3 — The one test that matters most

Everything above can pass while the setup is still untrustworthy, because the
failure this whole system exists to prevent is **silent**:

> A source is rate-limited. The tool reports **"0 results"**. You conclude the
> literature does not exist.

So do this deliberately. Force a source to fail — point a connector at an
unroutable host, or simply catch a real 503 during a broad sweep.

**Pass condition:** the response contains `unavailable` (with an HTTP status)
for that source.

**Fail condition:** the response contains `0 results`, or the source is silently
absent from the output.

If it fails, the Tier-1 patch is not in the running process. Re-run
`apply_patches.py`, verify with `verify_fixes.py`, and **fully restart Cline**.

---

## Part 4 — Sign-off

| Layer | Verified | Notes |
|---|---|---|
| Cline app + config | ☐ | |
| Toolchain | ☐ | |
| 166 scientific skills | ☐ | |
| 10 custom skills | ☐ | |
| paper-search + patches | ☐ | |
| ncbi + patches | ☐ | |
| academic-search fork | ☐ | |
| consensus / google-scholar | ☐ | |
| Render toolchain | ☐ | |
| API keys | ☐ | |
| **Honesty layer** (Part 3) | ☐ | |

**Two reminders before you call it done:**

1. **Re-run `apply_patches.py` after any `uv tool upgrade` or `git pull`.** The
   patches revert silently, and the symptom is silent zeros.
2. **`sources="all"` burns paid quota** if you set the Elsevier or Springer keys.
   Prefer `sources="auto"`.

