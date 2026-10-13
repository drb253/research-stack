---
name: citation-report
description: "Grade a document sentence by sentence against the sources you supply, and render the result as a colour-coded citation report in PDF, DOCX and HTML. Every sentence gets one of six states - attributed, synthesis, unverifiable here, unattributed, conflict, or no citation needed - assigned by a named deterministic rule from a recorded source registry, with the evidence value and page quoted in a printed margin note or a real Word comment. Detects citations that resolve to nothing, citations to retracted sources, and numbers that contradict the same named measure in a source you supplied. Resolves DOIs through Crossref/OpenAlex/Europe PMC and reads text out of supplied PDFs. It is an attribution report, not a plagiarism score and not an AI-writing detector. Use when a draft needs its citation support reviewed, when a reviewer asks which sentences are actually backed by the literature, or when you need to see at a glance where a document's evidence is thin."
allowed-tools: Read Write Edit Bash
license: MIT
compatibility: "Instructions plus a stdlib-only Python 3.9+ toolkit (scripts/*.py). No third-party packages required. Reading source PDFs needs poppler (`pdftotext`) or the optional `pypdf` package, and refuses legibly without either. Network is used only to resolve DOIs and is fully disabled by `--offline`. Works in any agent that supports SKILL.md."
metadata:
  version: "1.0"
  skill-author: local (custom skill)
  slash-command: /citation-report
  invocation-example: /citation-report --document draft.docx --pdf-dir sources/ --bib refs.bib
  modes: report, sources, verify, audit
  states: attributed, synthesis, unverifiable, unattributed, conflict, no_citation_needed
  sources:
    - https://api.crossref.org
    - https://api.openalex.org
    - https://www.ebi.ac.uk/europepmc/webservices/rest
---

# citation-report

Answer one question per sentence: **is this sentence actually supported by the sources this
document cites?** — and show the answer in place, next to the sentence, with the evidence quoted.

## What this skill is, and is not

**It is.** An attribution report. It reads a document, finds every citation marker, resolves each
marker to a source, compares the sentence's own numbers against the evidence held for that source,
and paints the sentence accordingly. Every colour traces to a recorded fact: a resolved identifier,
a page, a quoted value.

**It is not.** A plagiarism score, a similarity report, or an AI-writing detector. It never rewrites
prose and it refuses to help evade a detector. If a sentence is borrowed, the fix is a citation.

**It does not guess.** A sentence is never painted red because a number was *not found* in extracted
text — extraction is lossy, and tables and figures routinely do not survive it. Red requires positive
evidence: a citation that resolves to nothing, a retracted source, or a value that contradicts the
same named measure in a source actually held.

**It cannot make a judgment for you.** The colour scheme reports attribution integrity. Whether a
sentence is *good* science, well argued, or appropriate for the venue is not in scope.

## The two channels

The report separates two things that are usually conflated, and this is the point of the design.

**Channel D — deterministic, gate-grade.** The paint colour. Assigned by the named rules in
`references/verdict-rules.md`, from recorded facts only. A language model cannot set, change, or veto
one of these.

**Channel A — advisory, opt-in.** A model's opinion about *semantic* support (does the source actually
mean this?), stored in a visibly separate field, prefixed `ADVISORY_`, never a gate input. Off by
default. The repository's own measurements show a classifier failing causal-language traps, so an
advisory grade never becomes a red sentence.

## The six states

| State | Colour | Meaning | Gate |
|---|---|---|---|
| `attributed` | dark green | Every number in the sentence is present in the evidence of a cited source. | pass |
| `synthesis` | light green | Cited and resolvable, no independently checkable value: comparison, conclusion, summary. | pass |
| `unverifiable` | steel blue | Cited and identified, but no evidence was held. A statement about your inputs, not the sentence. | info / warning |
| `unattributed` | orange | States something checkable with no resolvable citation. | warning |
| `conflict` | red | Citation resolves to nothing, cites a retracted source, or contradicts a supplied source. Requires a verified link and machine-comparable evidence. | **error** |
| `no_citation_needed` | none | No attribution-requiring signal, no marker. Excluded from the coverage denominator. | info |

The reference tool this is modelled on has no `unverifiable` state, so a sentence citing a source it
cannot read defaults to looking supported. That state exists here and is counted separately.

## Quickstart

```bash
# 0. what do we know about the sources?
python3 scripts/report.py sources --document draft.docx --bib refs.bib --pdf-dir sources/

# 1. grade and render (offline: no DOI resolution, local evidence only)
python3 scripts/report.py report --document draft.docx --bib refs.bib --pdf-dir sources/ \
    --offline --format pdf,docx,html --out-dir citation-report/

# 2. verify the artifacts that were written
python3 scripts/report_gate.py --dir citation-report/ --document draft.docx

# if it exits 3, the worklist names what to supply; add the files and close the loop
python3 scripts/report.py worklist --document draft.docx --bib refs.bib \
    --pdf-dir sources/ --worklist citation-report/evidence_worklist.csv

# 3. text-only findings, for an agent or CI
python3 scripts/report.py audit --document draft.docx --bib refs.bib --pdf-dir sources/ \
    --offline --format table
```

Inputs are all optional and are combined; the more you supply, the more the report can check.

| Input | What it links |
|---|---|
| `--bib refs.bib` | Its `file = {...}` field is your own upload manifest → the strongest link to a supplied PDF |
| `--pdf-dir sources/` | Source PDFs. DOIs are mined from page 1 when filenames are opaque |
| `--sources sources.csv` | A ledger from this repository's review skills: already verified, with locators |
| `--claims claims.csv` | A claim ledger, so `[claim:C001]` resolves to its recorded sources |
| `--dois list.txt` | A plain list of DOIs or PMIDs |

## Statuses and exit codes

A finding about your document and a gap in the inputs are never the same thing, so they never share a
status:

| Status | Exit | Meaning |
|---|---|---|
| `pass` | 0 | adequate evidence; any findings are warnings |
| `fail` | 1 | error-severity findings about the document |
| `insufficient_evidence` | 3 | the document was readable; not enough source text was held |
| `insufficient_input` | 4 | the document itself could not be read well enough to make findings |

**Blocking is the default.** `--allow-insufficient` proceeds while keeping the status visible in the
JSON. A blocked run still writes every artifact and a worklist; the artifacts carry an
`INPUT-BOUND — NOT A FINDING` banner, in its own colour, distinct from the gate banner.

A blocked run also carries a top-level `input_gaps[]`, one entry per gap with a machine-readable
`kind` (`no_text_layer`, `no_pdf_extractor`, `unreadable_pdf`, …) and a `how_to_close` line, so a
caller can act on the gap without parsing the prose reason. "Nothing could be read" and "here is what
is wrong with the document" never share a status, an exit code, or a field.

## Modes

1. **report** (default). Grade and render. Writes `verdicts.json`, `coverage.json`,
   `sources_report.csv` and the requested artifacts into `--out-dir`.
2. **sources**. Build and validate the source registry only. Reports retracted sources and every
   source with no readable evidence.
3. **verify**. Re-validate a recorded `verdicts.json` against the document: every span must still
   locate its own sentence, and the coverage arithmetic must reproduce. Never re-classifies.
4. **audit**. Text-only findings table plus the coverage summary. No rendering. Applies the same
   evidence policy as `report`, so the blocker cannot be bypassed by choosing a mode.
5. **worklist**. Re-check a written `evidence_worklist.csv`: how many gaps closed, which remain. Exits
   non-zero while any gap is open, so it works as a completeness check.

## Evidence acquisition and the red bar

Source text is obtained in tiers — a supplied file, open-access full text from Europe PMC, an
open-access PDF, the vendored `paper-search` CLI as an optional subprocess, an abstract, a ledger's
recorded extraction — and every attempt is recorded, successful or not. Paywalls are never bypassed.
Acquired text is used only after its identity is confirmed against the cited work; on mismatch it is
discarded. Full detail: `references/evidence-and-limits.md`.

A red finding additionally requires a **verified link** (a declared id, a supplied file, or a resolved
DOI — never a title match) and **machine-comparable evidence** (the source's own text, or a value copied
verbatim into a ledger). A prose summary may support a positive claim but may never convict, so rules
`D11` and `D12` downgrade such a contradiction to `unverifiable` with the reason.

## Hard rules

- **Never invent a source.** If an identifier cannot be resolved, the source is recorded as
  `failed`/`unverified` and the sentence becomes `conflict` (in a closed reference apparatus) or
  `unverifiable`. It is never quietly treated as support.
- **Never paint green without evidence.** A source whose text could not be read cannot make a
  sentence `attributed`.
- **Never paint red without a quote.** Every `conflict` note carries the contradicting evidence, its
  source id, and its page or `abstract` locator.
- **Never resolve a reference by position.** A BibTeX file is commonly ordered by citekey while a
  reference list is alphabetical; entries are matched by DOI, then title, then author and year.
- **Never report an input gap as a finding.** A missing source is `insufficient_evidence` (exit 3) and
  a document the tool could not read is `insufficient_input` (exit 4); neither is ever rendered as a
  coverage figure, a colour, or a `pass`. See `docs/EVIDENCE-INVARIANT.md`.
- **Never assert an accusation on a guess.** A red needs a verified link and machine-comparable
  evidence; a title-inferred link or a ledger's prose summary downgrades it to `unverifiable`.
- **Never present a coverage ratio without its denominator.** `3/8`, not `37.5%` alone, and the
  denominator is every sentence carrying a claim — so the numerator is always a subset and the ratio
  can never exceed 100%. There is no single "quality score": the honest scalar is the `attributed`
  share, printed under that name.
- **Never let the advisory channel touch a verdict.** With `--advisory off`, the deterministic
  verdicts, colours, counts and exit code are byte-identical to a run with it on.
- **Never modify the user's document.** Every artifact is rendered from a parsed model; the input file
  is only ever read.

## Workflow

1. **Read the document** (`_intake.py`): `.md`, `.txt`, `.docx`, `.tex`, `.pdf`. Reference-list
   entries are marked structural and are *not* graded as prose — otherwise a bibliography's
   `[Internet]` and `[cited 2026]` apparatus becomes dozens of false findings.
2. **Build the source registry** (`_bundle.py`): link BibTeX, PDFs, the reference list, a ledger, or a
   DOI list; resolve DOIs unless `--offline`; attach evidence and record its availability.
3. **Grade** (`verdicts.py`, `_evidence.py`): split into sentences, bind citation markers, and walk
   the rule ladder. Numbers are looked up in an index built once per source.
4. **Summarise** (`coverage.py`): exact arithmetic, validated to balance.
5. **Render** (`_pdfrender.py`, `_docxout.py`, `_htmlout.py`): painted highlights and printed margin
   notes in the PDF, run shading and real Word comments in the DOCX, coloured spans with hover notes
   and an always-visible appendix in the HTML.
6. **Gate** (`report_gate.py`): recompute the arithmetic, re-locate every span, and re-open each
   artifact to count what is actually in it.

## Reading the output

- **PDF** — the sentence background is the state; the right margin carries the note with the source,
  the locator, and the quoted evidence. Notes are *printed*, not attached as annotations, so they
  survive printing and every viewer. The notes appendix repeats all of them in full.
- **DOCX** — sentences are shaded with the exact state colour, and each carries a native Word
  comment. Headings use real Word heading styles, so Word can build a table of contents.
- **HTML** — coloured spans with a hover note plus a numbered link to the notes appendix, and
  `print-color-adjust: exact` so the colours survive printing.

## Limits, stated plainly

- **The report is only as strong as the evidence you supply.** With metadata-only sources, every cited
  sentence is `unverifiable`, which looks weak — and is correct. Supply the PDFs, or allow DOI
  resolution to fetch abstracts, to do better.
- **An abstract is weaker evidence than full text**, and every note that relies on one says so.
- **Scanned PDFs have no text layer.** They are refused as `insufficient_input` (exit 4) with a
  reason that says the document has no text layer — a scan — not that an extractor is missing.
  There is no OCR: the refusal names the `tesseract` install route, but OCR text is never graded,
  because a transcription error would be reported as a finding about the document.
- **Every unreadable PDF is an input gap, including the two that are not scans.** A machine with
  neither `pdftotext` nor `pypdf` cannot read any PDF at all, and a file an extractor refuses to
  decode is not a file with nothing in it. All three routes exit 4 as `insufficient_input` with a
  distinct `input_gaps[].kind`, never 1: the reader is told what to install or supply, and the run is
  never mistaken for a document that graded to zero sentences. The absent-extractor route can be
  forced on any machine with `CITATION_REPORT_PDF_EXTRACTOR=none`, which is how it is tested where
  an extractor *is* installed.
- **DOCX footnotes and endnotes are read and graded, and text boxes are read once. Comments are
  not read, and deleted text is not.** Comments are reported as a warning when
  `word/comments.xml` is present. Insertions (`w:ins`) *are* read and graded; deletions
  (`w:delText`) are not, so a sentence removed by a tracked change is silently absent from the
  grade — check the document without tracked changes if that matters.
- **A number absent from the evidence is not a contradiction.** It is `unverifiable` with the missing
  values listed, so you can check by hand.
- **`.docx` output is a derived report document**, not a patched copy of your file. Patching the
  original risks corrupting a user's document; the report is rendered from the parsed model instead.
- **Non-Latin-1 text in the PDF** is transliterated or replaced, and the count is reported. Use the
  HTML or DOCX output for CJK.

Full detail: `references/verdict-rules.md`, `references/report-schema.md`,
`references/source-bundle.md`, `references/intake-formats.md`, `references/limits-and-claims.md`.

## Files

| Path | What it is |
|---|---|
| `scripts/report.py` | the CLI: report, sources, verify, audit |
| `scripts/verdicts.py` | the rule table and the classifier |
| `scripts/coverage.py` | the arithmetic, validated to balance |
| `scripts/_bundle.py` | source registry, BibTeX/reference-list parsing, evidence attachment |
| `scripts/_resolve.py` | Crossref / OpenAlex / Europe PMC, keyless, skipped by `--offline` |
| `scripts/_intake.py` | document readers with a declared capability per format |
| `scripts/_sentences.py` | deterministic sentence splitting and citation binding |
| `scripts/_signals.py` | what needs a citation, and which numbers must be traceable |
| `scripts/_evidence.py` | per-source evidence index |
| `scripts/_highlight.py` | the span model and the single colour palette |
| `scripts/_pdftext.py` | PDF text extraction, with a legible refusal |
| `scripts/_pdfrender.py`, `_pdfout.py` | PDF: painted highlights, printed margin notes |
| `scripts/_docxout.py` | DOCX: run shading and real Word comments |
| `scripts/_htmlout.py` | HTML: coloured spans, hover notes, coverage bar |
| `scripts/report_gate.py` | gate and independent artifact verification |
| `scripts/selftest.sh` | both-path regression harness (pass *and* fail fixtures) |
| `scripts/self_test.py` | offline logic assertions over the pure functions |
| `references/verdict-rules.md` | every rule, its predicate, and its severity |
| `references/report-schema.md` | `verdicts.json`, `coverage.json`, `sources_report.csv` |
| `references/source-bundle.md` | how sources are linked and what each link method is worth |
| `references/intake-formats.md` | per-format capability and refusal behaviour |
| `references/limits-and-claims.md` | what the report does not claim |
| `references/evidence-and-limits.md` | acquisition tiers, evidence strength, the red bar, the sufficiency policy |
| `../../../docs/EVIDENCE-INVARIANT.md` | the repository-wide rule this skill is built on |
