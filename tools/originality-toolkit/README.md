# Originality Toolkit

Legitimate, pre-submission originality checking for your **own** writing.

It does one job: take a draft, find the passages that closely track a real
published source, print the overlapping wording, and link the source — so you
can quote it, paraphrase it with attribution, or cite it. That is the honest
half of what a similarity engine does, applied to your text *before* you submit.

## What it is not

- It does **not** defeat AI-writing classifiers, and it will not try to.
- It cannot reproduce Turnitin's private index (web crawl + student-paper
  repository). It checks **open scholarly indexes** — which is where most
  *accidental* overlap comes from (copied definitions, boilerplate methods,
  near-verbatim paraphrases).
- A clean report is **not** a clearance. It lowers avoidable matches; it does
  not certify originality.

## Three ways to run it

1. **Ask** — in a Cline session, say *"check `part_10a_intro.html` for
   originality"* or *"run the citation fix on that report"*. The agent runs the
   CLI and reports back. No commands to remember.
2. **Run it yourself** — `./check.sh draft.html`, or call
   `python3 originality_check.py draft.html` directly.
3. **Slash command** — an `originality-check` skill is registered at
   `~/.cline/skills/originality-check/`, so `/originality-check` is available
   and the toolkit is auto-discoverable when a task matches it.

**Nothing runs automatically.** There is no daemon, no schedule, and no hook
into any submission system. It is a manual pre-submission check: you point it at
a draft, read the report, fix the flagged passages, then submit as normal.

## Install

None. Standard library only, Python 3.8+.

## Use

Drafts may be `.md`, `.txt` or `.html`. HTML is converted to prose-only text
first (chrome, scripts and tables removed), so you can point it straight at a
built chapter:

```bash
python3 originality_check.py ../agentic-ai-phc-india-systematic-review/part_10a_intro.html --out report.md
```

Options:

| Flag | Default | Meaning |
|------|---------|---------|
| `--sources` | `openalex,crossref,arxiv,europepmc` | which indexes to query (`semantic` optional) |
| `--per-source` | `5` | candidates per sentence per source |
| `--threshold` | `0.35` | score at/above which a passage is flagged |
| `--min-run` | `3` | noise floor: verbatim words required for a REVIEW flag |
| `--keep-tables` | off | keep `<table>` content in HTML drafts (dropped by default) |
| `--min-words` | `8` | sentences shorter than this are skipped |
| `--out` | stdout | write the markdown report here |
| `--refresh` | off | ignore the on-disk cache |

Set `OPENALEX_EMAIL` (or `NCBI_EMAIL`) to join the polite API pools.

## How scoring works

1. Sentences are extracted (headings, tables and URLs stripped).
2. Each sentence becomes a keyphrase query (stopwords and common academic
   words removed, longest/most distinctive terms first).
3. Candidate title + abstract text is reconstructed — including OpenAlex's
   inverted-index abstracts.
4. Two signals are combined:
   - **TF cosine** over content tokens (topical overlap), and
   - **longest verbatim word run** via `difflib` (actual copying).
   `score = 0.55*cosine + 0.45*(run_words / sentence_words)`.
5. Verdicts: `QUOTE + CITE` (verbatim run ≥ 12 words and ≥ 60% of the
   sentence), `PARAPHRASE + CITE` (score ≥ 0.55), `REVIEW`, or `ok`.

## Files

- `sources.py` — API adapters (OpenAlex, Crossref, arXiv, Europe PMC,
  Semantic Scholar). Each returns `ok` / `empty` / `unavailable`, so a
  rate-limited service is never mistaken for a clean result.
- `htmltext.py` — HTML → prose-only text: drops scripts, styles, chrome
  elements and tables, and keeps paragraph boundaries so a heading never merges
  into the sentence after it.
- `originality_check.py` — chunking, scoring, report rendering, CLI.
- `samples/draft_sample.md` — test fixture (contains deliberate copies).
- `.cache/` — per-query response cache, so re-runs are instant.

## The five tools

| Tool | Purpose | Command |
|---|---|---|
| `originality_check.py` | find passages tracking a published source | `python3 originality_check.py draft.md --json out.json` |
| `cite_fix.py` | report → verified BibTeX + citation plan | `python3 cite_fix.py out.json --bib refs.bib` |
| `paraphrase_brief.py` | rewrite worksheet + LLM prompts, with the citation attached | `python3 paraphrase_brief.py out.json` |
| `outline.py` | corpus → outline + notes skeleton | `python3 outline.py <folder> --notes notes.md` |
| `style_pass.py` | style-only editing; **skips sourced sentences** | `python3 style_pass.py draft.md --report out.json` |

Full pipeline:

```bash
python3 originality_check.py draft.md --json out.json
python3 cite_fix.py out.json --bib refs.bib --out citation_plan.md
python3 paraphrase_brief.py out.json --out worksheet.md --prompts prompts.json
python3 outline.py <corpus> --out outline.md --notes notes.md
python3 style_pass.py draft.md --report out.json --clean draft_edited.md
```

## Design guarantees

- **Unavailable != clean.** Every source adapter reports `ok` / `empty` /
  `unavailable`, and unreachable services are printed in the report. A
  rate-limited API is never presented as "no matches".
- **Skill-native citations.** `cite_fix.py` renders entries and builds citation
  keys with the citation-management skill's own `_common` module, re-keying
  fetched entries (arXiv returns URL-shaped keys) so they de-duplicate against
  entries that skill produces elsewhere. It needs no `requests`.
- **No laundering.** `style_pass.py` structurally refuses to edit any sentence
  the originality report flagged, listing every skipped sentence. The
  membership test is fuzzy (>= 0.85 similarity), not exact, so a re-split line
  cannot slip a sourced sentence past it.
- **Attribution is the goal, not evasion.** Nothing here tunes text to beat a
  detector, and nothing touches AI-writing classifiers.

## Known limitations

- Cannot see Turnitin's private web crawl or student-paper repository. A clean
  report is **not** a clearance.
- `outline.py` needs `<h1–h6>` for fine granularity; HTML parts without semantic
  headings fall back to one entry per file (word counts stay accurate).
- HTML tables are dropped from the prose by default, because a research-question
  table is not made of sentences. Use `--keep-tables` if a table really does
  carry prose you want checked.
- `arxiv` queries use an AND of distinctive terms; very short sentences yield
  weak queries.

