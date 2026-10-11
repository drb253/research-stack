---
name: originality-check
description: Pre-submission originality and attribution checking for your own drafts, backed by a stdlib-only Python toolkit at ~/.research-stack/originality-toolkit. Finds passages that closely track a real published source (OpenAlex, Crossref, arXiv, Europe PMC, Semantic Scholar) OR any local corpus you supply (paywalled PDFs, theses, books, unpublished manuscripts, saved web pages), resolves each flagged passage to a verified BibTeX citation and in-text citation, produces a paraphrase-with-attribution worksheet, maps a corpus into an outline plus notes skeleton, and runs a style pass that structurally refuses to edit sourced sentences. Use when checking a draft for unintentional overlap, fixing citations on flagged passages, or preparing a defensible manuscript. Does NOT bypass or defeat plagiarism or AI-writing detectors.
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
- It cannot see Turnitin's private web crawl or student-paper repository, and the
  five open APIs do not index paywalled articles, books, theses or unpublished
  work. **A clean report is not a clearance** — say so when reporting results.
  Pass `--corpus` to cover the sources you actually have: that closes the gap for
  everything you can supply, and only that.
- It never certifies originality. It lowers avoidable matches by *attributing*
  them, and flags near-verbatim paraphrase.

## Alignment with the ORI ethical-writing guide

Checked against *"Avoiding Plagiarism, Self-plagiarism, and Other Questionable
Writing Practices"* (Roig, US Office of Research Integrity, 3rd rev. 2015). The
guide's own labelled exercise is the benchmark: `bench_ori_guide.py` reports
**6/6 agreement** with the ORI's verdicts (4 rewrites it calls plagiarism, 2 it
calls correct).

| ORI guideline | Status here |
|---|---|
| G2 — verbatim text must be **quoted** | **implemented**: a quoted run returns `QUOTED (verbatim; verify the citation)`, which is correct practice and *not* counted as a violation; the same words unquoted return `QUOTE + CITE (verbatim)` |
| G3/G6 — summarise and paraphrase in your own words, keeping the meaning | implemented (lexical overlap + verbatim run) |
| G4 — a paraphrase must also use its own **syntactical structure** | **known limitation** — see below |
| G5 — always identify the source | out of scope for this tool; `cite_fix.py` and `audit_citations.py` cover it |
| G8 — when in doubt about common knowledge, cite it | partly: the `--min-run` noise floor suppresses generic phrasing |
| G11/G14 — text recycling / self-plagiarism | use `--corpus` to add your own prior papers |
| G15 — body citations ↔ reference list, both directions | `audit_citations.py` (`UNCITED_REFERENCE`, `CITATION_EXCEEDS_REFERENCE_LIST`) |
| G17 — the cited work must not be **corrected or retracted** | `cross_verify_citations.py` — retraction is a hard failure (99% lower bound measured); corrections are a warning |

**G4 (structure) is a known limitation.** Swapping every content word while
keeping the frame ("whether X are able to Y") is plagiarism under G4 but scores
near zero on lexical overlap. Two stdlib-only frame measures were tried and
neither separates that case from unrelated text (unrelated reached 0.857 against
frame-copies from 0.533), so no verdict depends on the frame number — it is
reported for a human to weigh. **Say so when reporting**: a clean report does not
cover frame-copying.

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
| `sources.py` | API adapters plus the local-corpus adapter; each reports `ok` / `empty` / `unavailable` |
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

# 1b. also check against sources the APIs cannot reach (paywalled PDFs, a thesis,
#     a book, an unpublished manuscript, saved web pages). Repeatable coverage.
python3 originality_check.py DRAFT --corpus ./sources/ --out report.md

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

`--sources`, `--corpus`, `--threshold` (0.30), `--min-run` (3), `--min-words` (8),
`--keep-tables`, `--refresh`, `--json`, `--out`.

## Checking against sources the APIs cannot reach

The five API adapters only see what those APIs index. Paywalled articles, books,
theses, unpublished manuscripts and saved web pages are invisible to them — and
that is often where the overlap that matters lives. `--corpus` closes that gap:

```bash
# a directory (recursed) or a single file
python3 originality_check.py DRAFT --corpus ~/reading/paywalled/
python3 originality_check.py DRAFT --corpus thesis_chapter3.pdf
```

- Accepts `.txt`, `.md`, `.markdown`, `.rst`, `.html`/`.htm`, and `.pdf` when the
  optional `pypdf` package is installed (`pip install pypdf`); otherwise export
  the document to text. PDF-less installs still work — the checker says which
  files it could not read.
- The corpus is added to the API sources, not substituted for them. Use
  `--sources ""` to check the corpus **alone** (fully offline).
- Every unreadable or empty file is reported on stderr. If the corpus loads
  **zero** documents the run warns loudly, because a quietly-empty corpus would
  make "no overlap found" mean nothing.
- Report the corpus size alongside any result: "no overlap against N supplied
  documents and 5 APIs" is a meaningful statement; "no overlap" is not.

## Guardrails

- **Never** restyle or rewrite a passage flagged as sourced and present it as
  the user's own. `style_pass.py` enforces this structurally; keep that property
  in any change you make.
- Never add a citation that does not actually support the claim.
- State the limitations above whenever you report a clean result.
