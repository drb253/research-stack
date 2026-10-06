---
name: originality-check
description: Pre-submission originality and attribution checking for your own drafts, backed by a stdlib-only Python toolkit at ~/.research-stack/originality-toolkit. Finds passages that closely track a real published source (OpenAlex, Crossref, arXiv, Europe PMC, Semantic Scholar), resolves each flagged passage to a verified BibTeX citation and in-text citation, produces a paraphrase-with-attribution worksheet, maps a corpus into an outline plus notes skeleton, and runs a style pass that structurally refuses to edit sourced sentences. Use when checking a draft for unintentional overlap, fixing citations on flagged passages, or preparing a defensible manuscript. Does NOT bypass or defeat plagiarism or AI-writing detectors.
license: MIT
metadata:
  version: "1.0"
  toolkit-path: ~/.research-stack/originality-toolkit
---

# Originality Check

Pre-submission checking for **your own** writing. It answers one question
honestly: *which passages in this draft closely track a real published source,
what exactly overlaps, and what citation belongs there?*

## What it does NOT do

- It does **not** defeat or tune text for plagiarism/AI detectors. That is out
  of scope by design; decline such requests and point to the institution's AI
  and integrity policy instead.
- It cannot see Turnitin's private web crawl or student-paper repository. **A
  clean report is not a clearance** — say so when reporting results.
- It never certifies originality. It lowers avoidable matches by *attributing*
  them, and flags near-verbatim paraphrase.

## Prerequisites

- Python 3.9+ — **standard library only, no pip installs**.
- Network access to api.openalex.org, api.crossref.org, export.arxiv.org,
  ebi.ac.uk, doi.org.
- Optional: set `OPENALEX_EMAIL` / `NCBI_EMAIL` to join the polite API pools.

## Toolkit

All code lives in `~/.research-stack/originality-toolkit/` (7 modules plus a
`check.sh` wrapper). Do not copy it — run it in place:

| Module | Purpose |
|---|---|
| `originality_check.py` | the checker (accepts `.md`, `.txt`, `.html`) |
| `sources.py` | API adapters; each reports `ok` / `empty` / `unavailable` |
| `htmltext.py` | HTML → prose-only text (drops chrome, scripts, tables) |
| `cite_fix.py` | report → verified BibTeX + citation plan |
| `paraphrase_brief.py` | rewrite worksheet + LLM prompts |
| `outline.py` | corpus → outline + notes skeleton |
| `style_pass.py` | style-only editor; skips sourced sentences |

## Workflow

Run from the toolkit directory:

```bash
cd ~/.research-stack/originality-toolkit

# 1. check a draft (HTML or markdown), machine-readable output for the next step
python3 originality_check.py DRAFT --json out.json --out report.md

# 2. resolve flagged passages to verified BibTeX + in-text citations
python3 cite_fix.py out.json --bib refs.bib --out citation_plan.md

# 3. paraphrase-with-attribution worksheet (the rewrite step is interactive)
python3 paraphrase_brief.py out.json --out worksheet.md --prompts prompts.json

# 4. map a corpus into an outline and notes skeleton
python3 outline.py CORPUS_DIR --out outline.md --notes notes.md

# 5. style pass on your own prose only (sourced sentences are skipped, never edited)
python3 style_pass.py DRAFT --report out.json --out style_report.md --clean draft_edited.md
```

## Interpreting a report

- `QUOTE + CITE (verbatim)` — copied wording (>= 12-word run and >= 60% of the
  sentence). Quote it with a locator and cite, or rewrite it.
- `PARAPHRASE + CITE` — close to the source; rewrite in your own voice and cite.
- `REVIEW (topical overlap)` — check whether a citation is warranted; **common
  phrasing usually needs nothing**. Short generic matches are suppressed by the
  `--min-run` noise floor (default 3 words).
- A `REVIEW` flag whose "source" is unrelated to the claim is a **false
  positive**. Do **not** attach that citation — check first, and prefer the
  "common knowledge / no citation" decision. Fabricating a citation is worse
  than the overlap it was meant to fix.

## Key flags

`--sources`, `--threshold` (0.35), `--min-run` (3), `--min-words` (8),
`--keep-tables`, `--refresh`, `--json`, `--out`.

## Guardrails

- **Never** restyle or rewrite a passage flagged as sourced and present it as
  the user's own. `style_pass.py` enforces this structurally; keep that property
  in any change you make.
- Never add a citation that does not actually support the claim.
- State the limitations above whenever you report a clean result.
