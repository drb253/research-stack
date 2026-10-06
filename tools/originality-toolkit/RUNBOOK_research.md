# Item 4 — Research & synthesis runbook

Goal: make producing **original** prose the path of least resistance, by wiring
the existing skills over corpora you already own.

## 1. Map what you have

```bash
python3 outline.py ../agentic-ai-phc-india-systematic-review \
    --out outline.md --notes notes.md
```

`outline.py` walks a folder (or files), reads `.md` / `.txt` / `.html` (tags
stripped), and emits:

- `outline.md` — every heading with a word count, per file,
- `notes.md` — a notes skeleton with *Key claims*, *Sources needed*,
  *Evidence/numbers*, *My own observation*, *Open questions*.

The **Sources needed** box is the defence: a claim is either yours (no citation)
or it needs a bib key, and you decide that *before* it reaches the prose.

## 2. Find the sources — `literature-review` skill

Use `literature-review` for discovery (PubMed, arXiv, bioRxiv, Semantic
Scholar) and its PRISMA-style structure for systematic work. Search more than
one database: coverage differs sharply and a single source is the commonest
cause of a biased reference list.

## 3. Turn sources into verified citations — `citation-management` skill

```bash
~/.cline/skills/citation-management/scripts/extract_metadata.py --doi 10.1038/s41586-021-03819-2
~/.cline/skills/citation-management/scripts/extract_metadata.py -i identifiers.txt -o citations.bib
```

Note these two scripts need `requests` (not installed on this machine):
`uv pip install requests` in a venv, or use `cite_fix.py`, which performs the
same DOI Content Negotiation over the standard library and re-uses the skill's
own `_common` module for keys and rendering — so its output de-duplicates
against entries produced by the skill.

## 4. Close the loop

```
corpus → outline.md + notes.md        (structure)
notes "Sources needed" → literature-review   (discovery)
source → citation-management / cite_fix.py   (verified BibTeX)
final draft → originality_check.py           (self-check)
flagged → cite_fix.py + paraphrase_brief.py  (attribution fixes)
prose → style_pass.py --report out.json      (style, sourced text skipped)
```

## Why this lowers the similarity score honestly

Not by hiding matches, but by removing the two things that produce them:
unattributed borrowing (fixed by step 3) and accidental near-copying (fixed by
step 4, where the checker points at the exact overlapping wording).
