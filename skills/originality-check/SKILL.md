---
name: originality-check
description: Pre-submission originality and attribution checking for your own drafts, backed by a stdlib-only Python toolkit at ~/.research-stack/originality-toolkit. It finds passages that closely track a real published source (OpenAlex, Crossref, arXiv, Europe PMC, Semantic Scholar) or any local corpus you supply, such as paywalled PDFs, theses, books and saved pages. It resolves each flagged passage to a verified BibTeX citation, builds a paraphrase-with-attribution worksheet, maps a corpus to an outline, and runs a style pass that refuses to edit sourced sentences. It does not defeat plagiarism or AI-writing detectors.
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
  of scope by design. Decline such requests. Point to the institution's AI and
  integrity policy instead.

- It cannot see Turnitin's private web crawl or student-paper repository.

- The five open APIs do not index paywalled articles, books, theses or
  unpublished work. Pass `--corpus` to cover the sources you have. That step
  closes the gap for those files, and only those.

- **A clean report is not a clearance.** Say so when you report results.

- It never certifies originality. It lowers avoidable matches by *attributing*
  them and by flagging near-verbatim paraphrase.

## Alignment with the ORI ethical-writing guide

The guide is *"Avoiding Plagiarism, Self-plagiarism, and Other Questionable
Writing Practices"* (Roig, US Office of Research Integrity, 3rd rev. 2015).

The guide's own labelled exercise is the benchmark. `bench_ori_guide.py`
reports **6/6 agreement** with the ORI verdicts: 4 rewrites it calls
plagiarism, and 2 it calls correct.

<!-- ste-allow R1,R3,R6: one markdown table is one lint block; its rows cannot meet the sentence limit -->

| ORI guideline | Status here |
|---|---|
| G2 — verbatim text must be **quoted** | **implemented**: a quoted run returns `QUOTED (verbatim; verify the citation)`, which is correct practice and not a violation; the same words unquoted return `QUOTE + CITE (verbatim)` |
| G3/G6 — summarise and paraphrase in your own words, keeping the meaning | implemented (lexical overlap plus verbatim run) |
| G4 — a paraphrase must also use its own **syntactical structure** | **measured, no threshold wired** — see below |
| G5 — always identify the source | out of scope for this tool; `cite_fix.py` and `audit_citations.py` cover it |
| G8 — when in doubt about common knowledge, cite it | partly: the `--min-run` noise floor suppresses generic phrasing |
| G11/G14 — text recycling and self-plagiarism | use `--corpus` to add your own prior papers |
| G15 — body citations and reference list, both directions | `audit_citations.py` (`UNCITED_REFERENCE`, `CITATION_EXCEEDS_REFERENCE_LIST`) |
| G17 — the cited work must not be corrected or retracted | `cross_verify_citations.py` makes retraction a hard failure (99% lower bound measured); corrections are a warning |

**G4 (structure): the toolkit measures it, and it wires no threshold**. A frame
copy swaps every content word but keeps the function-word frame: "whether X are
able to Y" becomes "whether P are able to Q". The lexical
score cannot see that rewrite.

`benchmarks/bench_frame_copy.py` measured candidate measures on a frozen corpus:
108 frame copies against 116 negatives. No measure reached the pre-declared bar
of 90% sensitivity at 5% false positives or less, with a lower confidence bound
of 80% or more.

Two measures separate frame copies from unrelated text (AUC 0.982 and 1.000).
Both also fire on a preprint against its own published version, so their
false-positive floors are 37.1% and 19.0%. A threshold would flag legitimate
writing, so the skill ships no `FRAME-COPY` verdict.

Every generated report therefore carries a **structural-coverage** section. That
section gives the number of sentences the run compared, and states that
frame-copying is not covered above the measured separation. The `--json` payload carries the same
line under `structural_coverage`. The deployment must not remove it.

## Prerequisites

- Python 3.9 or later, **standard library only, no pip installs**.

- Network access to api.openalex.org, api.crossref.org, export.arxiv.org,
  ebi.ac.uk and doi.org.

- Optional: set `OPENALEX_EMAIL` or `NCBI_EMAIL` to join the polite API pools.

## Toolkit

All code lives in `~/.research-stack/originality-toolkit/` (7 modules plus a
`check.sh` wrapper). Do not copy it. Run it in place.

<!-- ste-allow R1,R3: one markdown table is one lint block; its rows cannot meet the sentence limit -->

| Module | Purpose |
|---|---|
| `originality_check.py` | the checker; accepts `.md`, `.txt` and `.html` |
| `sources.py` | API adapters plus the local-corpus adapter; each reports `ok`, `empty` or `unavailable` |
| `htmltext.py` | HTML to prose-only text (drops chrome, scripts and tables) |
| `cite_fix.py` | report to verified BibTeX plus a citation plan |
| `paraphrase_brief.py` | rewrite worksheet plus LLM prompts |
| `outline.py` | corpus to outline plus a notes skeleton |
| `style_pass.py` | style-only editor; skips sourced sentences |

### A corpus that was not read is an input gap, not a measurement

`--corpus` may be partly or wholly unreadable: a locked file, a corrupt PDF, or
a path that does not exist. The toolkit then exits `3` and records every
unreadable file in three places:

- the markdown report, under `## Corpus not fully read — INPUT GAP, not a result`;

- the `--json` payload, as `corpus.not_checked[]` plus a top-level `status`;

- the process exit code.

If **no** document in the corpus was read, the report prints no score line. It
says the run cannot determine the local-corpus figures. A score over a corpus that
was not read is the one output this skill must never produce.

`--allow-insufficient` exits `0` and still records the gap.
`--recheck <previous --json output>` re-reads only the files that failed. It
exits `3` until every one of them is readable, so a re-run can close a gap
rather than re-assert it.

The same rule applies to the API sources. `sources.py` reports `ok`, `empty` or
`unavailable`. An unreadable local corpus is `unavailable`, never `empty`. "The
corpus matched nothing" and "the corpus was never read" are different claims.

## Workflow

Run from the toolkit directory.

```bash
cd ~/.research-stack/originality-toolkit

# 1. check a draft; machine-readable output feeds the next step
python3 originality_check.py DRAFT --json out.json --out report.md

# 1b. also check sources the APIs cannot reach; repeatable coverage
python3 originality_check.py DRAFT --corpus ./sources/ --out report.md

# 2. resolve flagged passages to verified BibTeX and in-text citations
python3 cite_fix.py out.json --bib refs.bib --out citation_plan.md

# 3. paraphrase-with-attribution worksheet (the rewrite step is interactive)
python3 paraphrase_brief.py out.json --out worksheet.md --prompts prompts.json

# 4. map a corpus to an outline and notes skeleton
python3 outline.py CORPUS_DIR --out outline.md --notes notes.md

# 5. style pass on your own prose only; sourced sentences are skipped
python3 style_pass.py DRAFT --report out.json --out style_report.md --clean draft_edited.md
```

## Interpreting a report

- `QUOTE + CITE (verbatim)` — copied wording of 12 words or more, and 60% or
  more of the sentence. Quote it with a locator and cite it, or rewrite it.

- `PARAPHRASE + CITE` — close to the source. Rewrite the sentence in your own
  voice and cite the idea.

- `REVIEW (topical overlap)` — check whether a citation applies. Common
  phrasing usually needs nothing. The `--min-run` noise floor (default 3 words)
  suppresses short generic matches.

- `QUOTED (verbatim; verify the citation)` — correct practice when a citation
  is present. The toolkit does not count it as a violation.

- **A `REVIEW` flag with an unrelated source is a false positive.** Do not
  attach that citation. Check first, and prefer the "common knowledge"
  decision. A fabricated citation is worse than the overlap it was meant to
  fix.

## Key flags

`--sources`, `--corpus`, `--threshold` (0.30), `--min-run` (3), `--min-words`
(8), `--keep-tables`, `--refresh`, `--json`, `--out`, `--allow-insufficient`,
`--recheck`.

## Checking against sources the APIs cannot reach

The five API adapters see only what those APIs index. Paywalled articles,
books, theses, unpublished manuscripts and saved web pages are invisible to
them. The overlap that matters often lives there. `--corpus` closes
that gap.

```bash
# a directory (recursed) or a single file
python3 originality_check.py DRAFT --corpus ~/reading/paywalled/
python3 originality_check.py DRAFT --corpus thesis_chapter3.pdf
```

- `--corpus` accepts `.txt`, `.md`, `.markdown`, `.rst`, `.html`/`.htm`, and
  `.pdf` when the optional `pypdf` package is present. Otherwise export the
  document to text. A PDF-less install still works: the checker says which
  files it could not read.

- The corpus joins the API sources; it does not replace them. Use
  `--sources ""` to check the corpus alone, fully offline.

- The report names every unreadable or empty file. If the corpus loads zero
  documents the run warns loudly, because a quietly-empty corpus makes "no
  overlap found" meaningless.

- Report the corpus size with any result. "No overlap against N supplied
  documents and 5 APIs" is meaningful; "no overlap" alone is not.

## Guardrails

- **Never** restyle or rewrite a passage that a rule flagged as sourced, then
  present it as the user's own. `style_pass.py` enforces this structurally.
  Keep that property in any change you make.

- Never add a citation that does not support the claim.

- State the limitations above in every report of a clean result.

- Every report carries the structural-coverage section. Do not remove it and do
  not soften it.

- `eval.md` lists the checks to run before you return output: hard errors O1,
  O2 and O3, plus O4, O5, O6 and O7.
