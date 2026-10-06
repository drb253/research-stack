# Item 3 — Paraphrase-with-attribution (workflow)

This is the one step that is **interactive by design**. `paraphrase_brief.py`
prepares the ground; the rewrite itself runs as an LLM step inside Cline, on
prompts the script emits. It is deliberately not a batch "humaniser".

## Why it is not automated

Rewriting sourced text until a detector stops noticing is the thing this whole
toolkit declines to do. What *is* legitimate — and what an assignment actually
tests — is: put the idea in your own words **and attach the citation**. That is
a judgement call, so it stays interactive.

## Pipeline

```bash
# 1. check the draft, capture machine-readable results
python3 originality_check.py draft.md --json out.json

# 2. resolve each flagged passage to a citation (Item 2)
python3 cite_fix.py out.json --bib refs.bib --out citation_plan.md

# 3. build the rewrite worksheet + LLM prompt payload
python3 paraphrase_brief.py out.json --out paraphrase_worksheet.md --prompts prompts.json
```

`paraphrase_brief.py` reads the sibling `refs.bib`, links each passage to its
citation by DOI, and emits for every flagged sentence:

- the sentence and its source,
- the **exact overlapping wording to avoid**,
- the citation to attach (`(Vaswani et al., 2017)`, `[bib key]`),
- a decision checklist: quote / paraphrase / common knowledge,
- a ready-to-run prompt (also written to `prompts.json`).

## The interactive step in Cline

Take the prompts (one per passage) and run them here. Each prompt enforces:
keep the meaning, do **not** reuse the overlapping wording, attach the citation,
and say explicitly when something is common knowledge rather than cited. You get
back a rewritten sentence, the citation placement, and a note on what a reader
should verify.

## Output contract

For every flagged passage you end with exactly one of:

| Decision | Requirement |
|---|---|
| Quote | quotation marks + in-text citation + page/locator |
| Paraphrase | your own phrasing + in-text citation |
| Common knowledge | a one-line justification, no citation |

Anything else is an unresolved attribution and should block submission.
