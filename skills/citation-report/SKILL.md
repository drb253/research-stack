---
name: citation-report
description: "Grade a document sentence by sentence against the sources you supply, then render a colour-coded citation report in PDF, DOCX, and HTML. Each sentence gets one state: attributed, synthesis, unverifiable here, unattributed, conflict, or no citation needed, assigned by a named deterministic rule from a recorded registry. It flags citations that resolve to nothing or point to a retracted source. Use when a reviewer asks which sentences the literature backs; this is an attribution report, not a similarity score."
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

Ask one question of every sentence: **does a supplied source support it**?
Show the answer in place, next to the sentence, with the evidence quoted.

## What this skill is, and is not

**It is**. An attribution report. It reads a document and finds every citation marker. It resolves each
marker to a source. It then compares the sentence's own numbers against the evidence held for that
source, and paints the sentence. Every colour traces to a recorded fact: a resolved identifier, a page,
a quoted value.

**It is not**. A plagiarism score, a similarity report, or an AI-writing detector. It never rewrites
prose, and it refuses to help evade a detector. If a sentence borrows from another work, the fix is a
citation.

**It does not guess**. The tool never paints a sentence red because a number is *not found* in extracted
text. Extraction is lossy, and tables and figures routinely do not survive it. Red requires positive
evidence. That evidence is a retracted source, or a value that contradicts a named measure in a held
source. A citation that resolves to nothing warns instead: it has no link to verify.

**It cannot judge the science for you**. The colour scheme reports attribution integrity. Whether a
sentence is good science, well argued, or appropriate for the venue is out of scope.

## The two channels

The report separates two things that authors usually conflate. This separation is the point of the
design.

**Channel D — deterministic, gate-grade**. This channel sets the paint colour. The named rules in
`references/verdict-rules.md` assign the colour, from recorded facts only. A language model cannot set,
change, or veto one of these colours.

**Channel A — advisory, opt-in**. This channel holds a model's opinion about *semantic* support. It
answers one question: does the source actually mean this? The report stores the opinion in a visibly
separate field, prefixed `ADVISORY_`, and the field never feeds a gate. The channel is off by default.
The repository's own measurements show a classifier failing causal-language traps, so an advisory grade
never becomes a red sentence.

## The six states

<!-- ste-allow R1,R2,R3: a markdown table is one layout block; the sentence-length, one-instruction and sentence-count rules do not apply to its cells -->

| State | Colour | Meaning | Gate |
|---|---|---|---|
| `attributed` | dark green | Every number in the sentence is present in the evidence of a cited source. | pass |
| `synthesis` | light green | Cited and resolvable, with no independently checkable value: comparison, conclusion, summary. | pass |
| `unverifiable` | steel blue | Cited and identified, but no evidence was held. This is a statement about your inputs, not the sentence. | info / warning |
| `unattributed` | orange | States something checkable with no resolvable citation, including a citation marker that matches no source in a closed apparatus. | warning |
| `conflict` | red | Cites a retracted source, or contradicts a supplied source. The tool requires a verified link and machine-comparable evidence. | **error** |
| `no_citation_needed` | none | No attribution-requiring signal, no marker. The denominator excludes this state. | info |

The reference tool that this design follows has no `unverifiable` state. A sentence that cites a source
it cannot read therefore defaults to looking supported. That state exists here, and the arithmetic
counts it separately.

The rule ladder uses (D03), (D04), (D07), (D08), (D11), (D12), and (D13). `references/verdict-rules.md`
gives the predicate and the severity for every id.

## The defined claim

This report can issue one defined claim, and only one: plagiarism-free against the sources checked.
The definition lives in `tools/attribution.py`, shared with the originality toolkit and the review gate.
The shared module states the definition in these words:

- A passage is plagiarism-free when it meets one of these conditions.

- It quotes another work. A marker shows the quotation. A citation names the source.

- It paraphrases another work. The author writes new words. A citation names the source.

- It states a fact that needs no citation.

- A document meets the definition when every assessed passage meets one condition.

- No citation may stay unresolved. Never cite a retracted source. The supplied corpus must be readable.

The check has limits. It reads only the sources supplied or reachable. It does not verify structure above the measured separation. So a paraphrase can keep the source's sentence structure, and the check does not catch that.

Run `python3 tools/attribution.py --definition` for the authoritative wording.

### The scope travels with the claim

The statement always carries its boundary, in this shape:

`Scope: 1 source(s) checked; 1 supplied document(s) read; 0 document(s) could not be read; structure is not verified above the measured separation.`

The four facts are the source count, the documents read, the documents that could not be read, and the one exception. A statement without them is the universal negative this project refuses.

### How the report computes the facts

| Fact | Where it comes from |
|---|---|
| `passage_findings` | sentences in `conflict` plus sentences in `unattributed` |
| `open_reviews` | sentences in `unverifiable` |
| `citations_unresolved` | citable tokens that resolved to no source; the D03 sentences carry them |
| `retracted_cited` | sentences that cite a retracted source (D04) |
| `sources_checked` | the source ledger size |
| `corpus_docs` | sources whose text was read |
| `corpus_unreadable` | supplied sources whose text was not read |

`tools/attribution.py` issues the statement only when every condition holds. It withholds the statement when any fact is missing. A fact that the run cannot establish stays `None`, never zero. The gate recomputes every fact from the recorded `verdicts.json` and fails on a disagreement (`ATTRIBUTION_MISMATCH`).

### Where the block appears

- `verdicts.json` carries the `attribution` object: the facts, the statement, the scope, and the blockers.

- The JSON envelope from `report` and `audit` carries the same object.

- The PDF, DOCX, and HTML artifacts print the definition, the statement, and the scope.

- The gate requires the HTML artifact to carry all three definition anchors. It fails with `ATTRIBUTION_BLOCK_MISSING` when one is absent.

The term never appears in an artifact without the definition. The honesty step scans the artifact text, so a bare claim fails with `HONESTY_CLAIM`.

## Preflight and dependencies

The reader uses optical character recognition (OCR) for a scan. Run these checks before the first report. Stop and report when a check fails.

<!-- ste-allow R1,R2,R3: a markdown table is one layout block; the sentence-length, one-instruction and sentence-count rules do not apply to its cells -->

| Item | Test | Action on failure. |
|---|---|---|
| Python | `python3 --version` (3.9 or later) | Stop; report the version. |
| Toolkit | `ls scripts/report.py scripts/report_gate.py` | Stop; the skill is incomplete. |
| PDF reader | `command -v pdftotext`, then `python3 -c "import pypdf"` | A supplied PDF becomes an input gap at exit 4. |
| OCR engine | `command -v tesseract`, then `python3 -c "import rapidocr_onnxruntime"` | A scan becomes an input gap at exit 4. |
| Network | Resolve one known DOI. | Continue with `--offline`; the report uses local evidence only. |
| Test fixture | `ls assets/sample-manuscript.md` | Stop; the example cannot run. |

The toolkit needs the standard library only. POppler's `pdftotext` or the optional `pypdf` package reads
a supplied PDF. The OCR tier needs `tesseract` or `rapidocr-onnxruntime`, and it needs poppler's
rasteriser.

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

Every input is optional, and the tool combines them. The more you supply, the more the report can
check.

<!-- ste-allow R1,R2,R3: a markdown table is one layout block; the sentence-length, one-instruction and sentence-count rules do not apply to its cells -->

| Input | What it links |
|---|---|
| `--bib refs.bib` | Its `file = {...}` field is your own upload manifest. That field is the strongest link to a supplied PDF. |
| `--pdf-dir sources/` | Source PDFs. The tool mines DOIs from page 1 when filenames are opaque. |
| `--sources sources.csv` | A ledger from this repository's review skills: already verified, with locators. |
| `--claims claims.csv` | A claim ledger, so `[claim:C001]` resolves to its recorded sources. |
| `--dois list.txt` | A plain list of DOIs or PMIDs. |

## Decision table

Pick the mode from the job in front of you.

<!-- ste-allow R1,R2,R3: a markdown table is one layout block; the sentence-length, one-instruction and sentence-count rules do not apply to its cells -->

| The job | Mode | Output. |
|---|---|---|
| Produce the colour-coded report. | `report` | `verdicts.json`, `coverage.json`, `sources_report.csv`, and the artifacts. |
| Check the source registry only. | `sources` | Retracted sources, and every source with no readable evidence. |
| Confirm a written report still holds. | `verify` | A re-located span check and reproduced coverage arithmetic. |
| Get findings as text for CI. | `audit` | A findings table plus the coverage summary. |
| Close the evidence gaps. | `worklist` | A count of closed and open gaps. |

## Statuses and exit codes

A finding about your document and a gap in the inputs are never the same thing. They therefore never
share a status.

<!-- ste-allow R1,R2,R3: a markdown table is one layout block; the sentence-length, one-instruction and sentence-count rules do not apply to its cells -->

| Status | Exit | Meaning |
|---|---|---|
| `pass` | 0 | Adequate evidence. Any findings are warnings. |
| `fail` | 1 | Error-severity findings about the document. |
| `insufficient_evidence` | 3 | The document was readable, but not enough source text was held. |
| `insufficient_input` | 4 | The document itself could not be read well enough to make findings. A scan with OCR off or unavailable reaches this status. |

A run that *did* read a scan is `insufficient_evidence` (exit 3) by default. A transcription is a
machine's reading, not the document's own text layer.

**Blocking is the default**. `--allow-insufficient` proceeds while the status stays visible in the JSON.
A blocked run still writes every artifact and a worklist. The artifacts carry a banner that reads `INPUT-BOUND — NOT A FINDING`, in its own colour, distinct from the gate banner.

A blocked run also carries a top-level `input_gaps[]`, one entry per gap. Each entry carries a
machine-readable `kind` (`no_text_layer`, `no_pdf_extractor`, `unreadable_pdf`, …) and a `how_to_close`
line. A caller can therefore act on the gap without parsing the prose reason. "Nothing could be read"
and "here is what is wrong with the document" never share a status, an exit code, or a field.

## Modes

1. **report** (default). Grade and render. Writes `verdicts.json`, `coverage.json`,
   `sources_report.csv` and the requested artifacts into `--out-dir`.

2. **sources**. Build and validate the source registry only. Reports retracted sources and every source
   with no readable evidence.

3. **verify**. Re-validate a recorded `verdicts.json` against the document. Every span must still locate
   its own sentence, and the coverage arithmetic must reproduce. This mode never re-classifies.

4. **audit**. A text-only findings table plus the coverage summary. No rendering. It applies the same
   evidence policy as `report`, so a mode choice cannot bypass the blocker.

5. **worklist**. Re-check a written `evidence_worklist.csv`: how many gaps closed, and which remain. It
   exits non-zero while any gap is open, so it works as a completeness check.

## Evidence acquisition and the red bar

The tool obtains source text in tiers. The tiers are a supplied file, open-access full text from Europe
PMC, and an open-access PDF. Then come the vendored `paper-search` CLI, an abstract, and a ledger's
recorded extraction.

The tool records every attempt, successful or not. It never bypasses a paywall. It uses acquired text
only after it confirms the identity against the cited work. On a mismatch it discards the text. Full
detail: `references/evidence-and-limits.md`.

A red finding additionally requires three things:

1. A **verified link**: a declared id, a supplied file, or a resolved DOI. A title match never counts.

2. **Machine-comparable evidence**: the source's own text, or a value copied verbatim into a ledger.

3. **Text that was read rather than transcribed**.

A prose summary may support a positive claim, but it may never convict. Rules D11 and D12 therefore
downgrade such a contradiction to `unverifiable` with the reason. OCR on either side is rule D13, which
does the same and names the side.

## Hard rules

- **Never invent a source**. If an identifier does not resolve, the tool records the source as
  `failed` or `unverified`. The sentence then becomes `unattributed` (in a closed reference apparatus) or
  `unverifiable`. The tool never treats it quietly as support.

- **Never accuse on an unlinked marker**. A citation marker that matches no source is a defect, and the
  sentence still needs the citation it lacks. It warns (`unattributed`, rule D03). It never becomes a
  `conflict`, because an unmatched marker has no link to verify and red requires an identity-verified
  link. The classifier records an `UNRESOLVED_CITATION` trigger for it.

- **Never paint green without evidence**. A source whose text the tool could not read cannot make a
  sentence `attributed`.

- **Never paint red without a quote**. Every `conflict` note carries the contradicting evidence, its
  source id, and its page or `abstract` locator.

- **Never resolve a reference by position**. A BibTeX file commonly orders entries by citekey, while a
  reference list is alphabetical. The tool matches entries by DOI, then title, then author and year.

- **Never report an input gap as a finding**. A missing source is `insufficient_evidence` (exit 3). A
  document the tool could not read is `insufficient_input` (exit 4). The tool never renders either one
  as a coverage figure, a colour, or a `pass`. See `docs/EVIDENCE-INVARIANT.md`.

- **Never assert an accusation on a guess**. A red needs a verified link and machine-comparable
  evidence. A title-inferred link or a ledger's prose summary downgrades it to `unverifiable`.

- **Never present a coverage ratio without its denominator**. Print `3/8`, not `37.5%` alone. The
  denominator is every sentence that carries a claim. The numerator is therefore always a subset, and
  the ratio can never exceed 100%. There is no single quality score. The honest scalar is the
  `attributed` share, printed under that name.

- **Never let the advisory channel touch a verdict**. With `--advisory off`, the deterministic verdicts
  and counts are byte-identical to a run with the channel on. The exit code and the colours are
  byte-identical too.

- **Never modify the user's document**. The renderer draws every artifact from a parsed model. The tool
  only ever reads the input file.

- **Never ship a claim the tool cannot bound**. The gate scans the report's own prose with
  `tools/claim_guard.py`. A universal negative is an `HONESTY_CLAIM` error, and a clean result without
  its bound is `HONESTY_UNBOUNDED`.

## Workflow

1. **Read the document** (`_intake.py`): `.md`, `.txt`, `.docx`, `.tex`, `.pdf`. The parser marks
   reference-list entries as structural. It does not grade them as prose. Otherwise a bibliography's
   `[Internet]` and `[cited 2026]` apparatus becomes dozens of false findings.

2. **Build the source registry** (`_bundle.py`): link BibTeX, PDFs, the reference list, a ledger, or a
   DOI list. Resolve DOIs unless `--offline` applies. Attach evidence and record its availability.

3. **Grade** (`verdicts.py`, `_evidence.py`): split into sentences, bind citation markers, and walk the
   rule ladder. The tool builds a number index once per source, then looks numbers up in it.

4. **Summarise** (`coverage.py`): exact arithmetic, validated to balance.

5. **Render** (`_pdfrender.py`, `_docxout.py`, `_htmlout.py`). The PDF carries painted highlights and
   printed margin notes. The DOCX carries run shading and real Word comments. The HTML carries coloured
   spans with hover notes and an always-visible appendix.

6. **Gate** (`report_gate.py`): recompute the arithmetic, re-locate every span, and re-open each
   artifact to count what is actually in it.

## Reading the output

- **PDF** — the sentence background is the state. The right margin carries the note with the source, the
  locator, and the quoted evidence. The tool *prints* the notes rather than attaching them as
  annotations, so they survive printing and every viewer. The notes appendix repeats all of them in full.

- **DOCX** — the renderer shades sentences with the exact state colour. Each sentence carries a native
  Word comment. The headings use real Word heading styles, so Word can build a table of contents.

- **HTML** — coloured spans with a hover note plus a numbered link to the notes appendix. The CSS sets
  `print-color-adjust: exact`, so the colours survive printing.

## Worked examples

### Example 1 — a sentence whose number contradicts a supplied source

The document says `HR 0.50` and cites `[src:S001]`. The supplied ledger records `HR 0.80` for `S001`,
with a locator. The link is exact, the evidence is the source's own text, and the tool read both sides.
The rule fires `D08`: state `conflict`, colour red, with the contradicting value and the locator in the
note.

### Example 2 — a sentence whose number is absent from the evidence

The document says `HR 0.50`. The source text is readable, but the value does not appear in it. The tool
does **not** paint red. Absence is rule D07: state `unverifiable`, with the missing values listed, so a
reader can check by hand.

### Example 3 — a metadata-only source

The run holds a DOI, a title, and an abstract summary for the cited work, but no full text. The cited
sentence becomes `unverifiable`. That result looks weak, and it is correct: the report cannot check what
it does not hold. Supply the PDF, or allow DOI resolution, to do better.

### Example 4 — a scanned document

The document is a one-page scan with no text layer. With an OCR engine installed, the reader transcribes
it and labels the transcription. The run is `insufficient_evidence` (exit 3) by default, with a
`TRANSCRIBED EVIDENCE` banner. `--allow-insufficient` exits 0, while the status still says
`insufficient_evidence` and the artifact records the override.

### Example 5 — the advisory channel stays inert

```bash
python3 scripts/report.py report --document draft.md --advisory off --out-dir a/
python3 scripts/report.py report --document draft.md --advisory grades.json --out-dir b/
```

A comparison of the two `verdicts.json` files must match, once you remove the `advisory` field. The
coverage summary and the gate result must match byte for byte.

### Example 6 — a citation marker that matches no source

The document says `An exploratory analysis suggested a benefit [99].` The apparatus is closed:
the run holds sources S001 to S003, and none of them is number 99. The rule fires `D03`: state
`unattributed`, colour orange, with the offending marker named in the note. The sentence needs the
citation it lacks, so the classifier records an `UNRESOLVED_CITATION` trigger. The finding never
becomes red, because no link exists to verify, and the run still passes its own gate.

## Failure modes and exit codes

<!-- ste-allow R1,R2,R3: a markdown table is one layout block; the sentence-length, one-instruction and sentence-count rules do not apply to its cells -->

| Symptom | Status | Exit | Cause and fix. |
|---|---|---|---|
| A supplied PDF has no reader. | `insufficient_input` | 4 | `input_gaps[].kind = no_pdf_extractor`. Install `pdftotext` or `pypdf`. |
| A scan has no text layer and OCR is off. | `insufficient_input` | 4 | `input_gaps[].kind = no_text_layer`. Install an engine or name the switch. |
| You asked for an OCR engine that is absent. | `insufficient_input` | 4 | `input_gaps[].kind = ocr_engine_unavailable`. The tool never substitutes another engine. |
| A cited source was never held. | `insufficient_evidence` | 3 | Supply the file the worklist names, then re-run `worklist`. |
| The artifacts disagree with the verdicts. | `fail` | 1 | `ARTIFACT_MISMATCH` or `COVERAGE_MISMATCH`. Re-render from the recorded model. |
| A citation marker matches no source. | `pass` | 0 | D03 warns. Add the missing reference, or remove the marker. The run still fails on any error-severity finding elsewhere. |
| A red has an inferred link. | `fail` | 1 | `CONFLICT_LINK_INFERRED`. Narrow the rule, or record a verified link. |
| A red rests on a prose summary. | `fail` | 1 | `CONFLICT_EVIDENCE_TOO_WEAK`. Use primary text or a recorded value. |
| Evidence has no recorded origin. | `fail` | 1 | `EVIDENCE_WITHOUT_PROVENANCE`. Record the acquisition attempt. |
| The report carries an absolute claim. | `fail` | 1 | `HONESTY_CLAIM` or `HONESTY_UNBOUNDED`. Rewrite the report text, or carry the defined block. |
| The artifact prints the term without the definition. | `fail` | 1 | `ATTRIBUTION_BLOCK_MISSING`. Render the block into the artifact. |
| The recorded claim disagrees with the recomputation. | `fail` | 1 | `ATTRIBUTION_MISMATCH`. Re-run `report.py`. |
| The shared definition is not installed. | `pass` | 0 | `ATTRIBUTION_DEFINITION_UNAVAILABLE`. Restore `tools/attribution.py`; the tool then issues no statement. |
| The audit preconditions fail. | `insufficient_input` | 4 | `CITATION_STYLE_UNRECOGNISED`, `TRIGGER_LANGUAGE_UNSUPPORTED`, `SENTENCE_SPLIT_SUSPECT`, or `NO_SOURCE_LIST`. Fix the input. |

## What this does not do

- **It does not score plagiarism**. It reads no corpus of other documents. It compares a sentence with
  the evidence held for the sources that sentence cites.

- **It does not detect AI writing**. It reports attribution, not authorship.

- **It does not rewrite the document**. It never edits the input file. The DOCX output is a derived
  report document, not a patched copy of your file.

- **It does not prove a sentence false**. A red states that a value contradicts a supplied source, or
  that the source carries a retraction. It does not judge the claim itself.

- **It does not cover sources it was not given**. With metadata-only inputs, most cited sentences become
  `unverifiable`. That result is honest, and it is not a finding about the document.

- **It does not guarantee completeness of the evidence base**. The source registry holds what you
  supplied, plus whatever the open-access tiers returned on that run.

- **It does not bound the whole literature**. The defined claim covers the sources the run checked, and
  the scope line names them. A source outside that set is outside the claim.

## Rubric coverage

`eval.md` grades a report. This table maps every check to the section that implements it.

<!-- ste-allow R1,R2,R3: a markdown table is one layout block; the sentence-length, one-instruction and sentence-count rules do not apply to its cells -->

| Check | Item | Implementing section. |
|---|---|---|
| 1 | Every number is recomputable. | **Hard rules**; **Statuses and exit codes**; **Workflow** step 4. |
| 2 | Every green rests on evidence. | **The six states**; **Hard rules**; **Failure modes and exit codes**. |
| 2b | A green rests on a distinctive value. | **The six states**; **Worked examples**, Example 1. |
| 3 | The reds are defensible. | **Evidence acquisition and the red bar**; **Worked examples**, Example 1. |
| 4 | The orange is honest. | **The six states**; **Failure modes and exit codes**. |
| 5 | `unverifiable` is used in both directions. | **The six states**; **Worked examples**, Example 3. |
| 6 | The reference list stays out of the prose. | **Workflow** step 1. |
| 7 | The advisory channel is inert. | **The two channels**; **Hard rules**; **Worked examples**, Example 5. |
| 8 | The artifacts contain what they claim. | **Reading the output**; **Workflow** step 6. |
| 8b | The input and result boundary is visible. | **Statuses and exit codes**; **Worked examples**, Example 4. |
| 8c | Every accusation clears the red bar, and the defined claim is earned or withheld. | **Evidence acquisition and the red bar**; **The defined claim**; **Failure modes and exit codes**. |
| 8d | The tool understood the document. | **Preflight and dependencies**; **Failure modes and exit codes**. |
| 9 | A bad input fails loudly. | **Failure modes and exit codes**; **Limits, stated plainly**. |
| 10 | A transcription stays a transcription. | **Statuses and exit codes**; **Worked examples**, Example 4. |

Run `benchmarks/bench_verdicts.py` before you change any rule. It reports precision and recall per
state against hand-labelled sentences.

## Limits, stated plainly

- **The report is only as strong as the evidence you supply**. With metadata-only sources, every cited
  sentence is `unverifiable`. That result looks weak, and it is correct. Supply the PDFs, or allow DOI
  resolution to fetch abstracts, to do better.

- **An abstract is weaker evidence than full text**. Every note that rests on an abstract says so.

- **The reader transcribes a scan when an OCR engine is available, and it labels the transcription**.
  Install `tesseract` or the optional `rapidocr-onnxruntime` package, plus poppler's rasteriser. OCR is
  on by default. `--no-ocr` refuses instead.

- **Four flags govern the OCR tier**. `--ocr-engine auto|tesseract|rapidocr` chooses the engine (`auto`
  prefers tesseract, then RapidOCR). `--ocr-lang` picks tesseract's language data. `--ocr-max-pages`
  defaults to 200, and `0` means no limit. The tool refuses a longer scan rather than partly reading it.

- **The tool marks everything it reads that way**. The document carries `transcribed: true` and
  `transcription: <engine>[:<lang>]`. A transcribed source's `evidence_origin` begins `ocr:`. Every
  artifact states how many sentences rest on a transcription. A transcription can never support an
  accusation. Without an engine, the tool refuses a scan as `insufficient_input` (exit 4) and names both
  install routes.

- **A transcribed run is input-bound by default**. A transcription is a machine's reading, so the run
  reports `insufficient_evidence` (exit 3) when its evidence rests on one. The banner reads `INPUT-BOUND — TRANSCRIBED EVIDENCE`. `--allow-insufficient` is how you proceed anyway. The status stays
  `insufficient_evidence` in the JSON, and the artifact records the override.

- **A transcription may describe, but never convict**. A contradiction is an accusation, so it needs
  three things: a verified link, machine-comparable evidence, and text that a reader read on both sides.
  Where the sentence or the source's evidence came from OCR, rule D13 reports the disagreement as
  `unverifiable` and names the transcribed side.

- **The benchmark measures that limit on a real scan**. Tesseract read `95% CI` as `95% Cl`, and on a two-sentence
  page it read `HR 0.50` correctly. One misread digit is all it takes, so the bar is provenance, not
  confidence.

- **Every unreadable PDF is an input gap, including the two that are not scans**. A machine with
  neither `pdftotext` nor `pypdf` cannot read any PDF at all. A file an extractor refuses to decode is
  not a file with nothing in it.

- **All three routes exit 4 as `insufficient_input`, with a distinct `input_gaps[].kind`, never 1**. The
  reader learns what to install or supply. The run is never mistaken for a document that graded to zero
  sentences. You can force the absent-extractor route on any machine with `CITATION_REPORT_PDF_EXTRACTOR=none`. The suite uses that hook to test the route where an extractor *is* installed.

- **The reader reads DOCX footnotes and endnotes, and it grades them**. It reads a text box once. It
  does not read comments, and it does not read deleted text.

- **It reports comments as a warning when `word/comments.xml` is present**. It *does* read and grade
  insertions (`w:ins`). It does not read deletions (`w:delText`), so a sentence removed by a tracked
  change is silently absent from the grade. Check the document without tracked changes if that matters.

- **A number absent from the evidence is not a contradiction**. It is `unverifiable` with the missing
  values listed, so you can check by hand.

- **`.docx` output is a derived report document**, not a patched copy of your file. Patching the
  original risks corrupting a user's document. The renderer draws the report from the parsed model
  instead.

- **The PDF renderer transliterates or replaces non-Latin-1 text**, and it reports the count. Use the
  HTML or DOCX output for CJK.

Full detail: `references/verdict-rules.md`, `references/report-schema.md`,
`references/source-bundle.md`, `references/intake-formats.md`, `references/limits-and-claims.md`.

## Files

<!-- ste-allow R1,R2,R3: a markdown table is one layout block; the sentence-length, one-instruction and sentence-count rules do not apply to its cells -->

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
| `scripts/report_gate.py` | gate and independent artifact verification, including the honesty and defined-claim steps |
| `scripts/_attribution.py` | the state-to-fact mapping for the defined claim, and the block every artifact prints |
| `scripts/selftest.sh` | both-path regression harness (pass *and* fail fixtures) |
| `scripts/self_test.py` | offline logic assertions over the pure functions |
| `references/verdict-rules.md` | every rule, its predicate, and its severity |
| `references/report-schema.md` | `verdicts.json`, `coverage.json`, `sources_report.csv` |
| `references/source-bundle.md` | how the tool links sources, and what each link method is worth |
| `references/intake-formats.md` | per-format capability and refusal behaviour |
| `references/limits-and-claims.md` | what the report does not claim |
| `references/evidence-and-limits.md` | acquisition tiers, evidence strength, the red bar, the sufficiency policy |
| `../../../docs/EVIDENCE-INVARIANT.md` | the repository-wide rule this skill is built on |
