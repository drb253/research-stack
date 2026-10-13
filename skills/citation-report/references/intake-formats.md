# Intake formats: what each reader can do, and what it refuses

Every format is read into the same model: typed paragraphs, each with an exact character range inside
`Document.text`, then split into sentences with offsets into that same text. Those offsets are what
`report_gate.py` re-checks on every run, so a reader that shifted a span by one character would be
caught rather than silently mis-highlighting a sentence.

---

## Capability table

| Suffix | Reader | Structure recognised | Not read |
|---|---|---|---|
| `.md` `.markdown` | native | ATX and setext headings, lists, block quotes, fenced code, tables | HTML inside Markdown |
| `.txt` `.text` `.rst` | native | paragraphs split on blank lines | reStructuredText directives |
| `.docx` | `zipfile` + `ElementTree` | headings by style, lists, captions, tables, text boxes (once), footnotes, endnotes | comments, tracked changes |
| `.tex` | native | `\part`…`\subsubsection` hierarchy, `\parencite`/`\cite` → markers | mathematics, macros defined in the preamble |
| `.pdf` | `pdftotext` → `pypdf` → refuse | paragraphs reassembled from hard-wrapped lines, headings guessed | scanned pages with no text layer |

---

## Which paragraphs are graded

Only **narrative** paragraphs produce sentences: `para`, `list_item`, `quote`, `caption`.

Not graded:

* **headings** — "Introduction" is not a claim;
* **tables** — a table row graded for "citation support" is noise, and it would inflate the coverage
  denominator;
* **code** — not prose;
* **reference-list entries** — a bibliography entry is not a claim, and its apparatus
  (`[Internet]`, `[cited 2026 Jan 5]`, `[Epub ahead of print]`) would otherwise be read as dozens of
  fabricated citations.

The last of those was a real defect found during development: on the reference corpus, 47 of 48
reference entries produced false `conflict` findings until the reference list was marked structural.
The reference-list decision therefore lives in one place (`_intake.mark_reference_list`) so the
exclusion that keeps entries out of the graded prose and the registry that reads their DOIs can never
disagree.

### How a reference list is recognised

A trailing run of numbered paragraphs is treated as a bibliography only when **all** of these hold:

* at least five consecutive entries, with consecutive numbers;
* the run starts at `1`;
* the run starts in the last 60% of the document;
* the run reaches the last few paragraphs of the document.

Anything else is a numbered body list, and refusing to treat it as a bibliography is the correct
outcome — inventing forty sources from a body list would be far worse than reading no sources at all.

---

## Citation marker grammars

| Form | Example | Notes |
|---|---|---|
| Bracketed numeric | `[12]`, `[12,14]`, `[12-14]` | ranges expand to individual numbers |
| Parenthetical numeric | `(1)`, `(1-4)`, `(1,3,5)` | deliberately narrow: parentheses must contain only digits and separators, so `(PTSD)`, `(ITQ)` and `(DSO)` are not citations |
| Ledger source | `[src:S001,S011]` | this repository's review-skill markers |
| Ledger claim | `[claim:C014]` | resolved through `--claims`; **not** a citation on its own |
| Bracketed candidate | `[7483504]`, `[10.1234/xyz]` | any other bracketed token, handed to the registry to resolve or reject |
| Author-year | `(Smith et al., 2019)` | matched to a source's year only when exactly one source claims it |
| Superscript numeric | `sentence.` + superscript `12` | recognised in **DOCX** (`w:vertAlign`), where the formatting is recorded. A PDF text layer does not carry superscript, so such a document cannot be graded by markers and the run blocks with `CITATION_STYLE_UNRECOGNISED` rather than accusing every sentence. |

A four-digit value in the year range is never read as a reference number: `(2019)` is an author-year
pointer, not reference 2019.

### Sentence splitting

Deterministic, with a protected-abbreviation list (`e.g.`, `i.e.`, `vs.`, `et al.`, `cf.`, `Fig.`,
`Eq.`, `No.`, `pp.`, `Dr.`, `approx.`, `ca.`, `SD`, `CI`, `HR`, months, corporate suffixes, and more),
plus rules that keep these together:

* decimals — `0.49` does not split;
* initials — `J. Smith` does not split;
* bracketed citations — `[12].` splits after the bracket, not inside it;
* en-dash and hyphen ranges — `9-90%` does not split;
* CJK terminators — `。！？` end a sentence with no following space, so the splitter does not assume
  Latin punctuation;
* paragraph breaks — a blank line is a hard boundary, so a marker can never be attributed across
  paragraphs.

Adversarial cases live in `self_test.py::test_sentence_splitting` and run in CI.

---

## DOCX specifics

`word/document.xml` is parsed with the standard library. Runs are gathered in document order, honouring
`w:t`, `w:tab`, `w:br`, `w:cr` and `w:noBreakHyphen`, then whitespace-collapsed per paragraph.

Paragraph kind comes from `w:pPr/w:pStyle`: `Heading1`–`Heading9`, `Title`, `Subtitle`, anything
containing `List` (→ list item), and anything containing `Caption`.

**Read and graded:** body paragraphs and tables, plus `word/footnotes.xml` and
`word/endnotes.xml`. Every `w:footnote`/`w:endnote` whose `w:type` is `separator` or
`continuationSeparator` is Word's own rule mark and is skipped; every other one contributes
its `w:p` text as a graded paragraph, in the order body → footnotes → endnotes. A sentence
that lives only in a footnote is still a claim, so it is graded rather than disclosed as
unread.

Text boxes (`w:txbxContent`) are read **once**. The run that holds a text box is reached by
the paragraph walk and its own text walk descends into the box; the runs *inside* the box are
therefore skipped, so the box's sentence is not counted twice.

**Not read, and disclosed as a warning when the part is present:** comments
(`word/comments.xml`). **Not read and not applied:** tracked changes — a deleted sentence may
still be read from the XML if it survives in a `w:del` run, which is a known limitation.

### Why the DOCX output is a derived document

The DOCX report is rendered from the parsed model rather than by patching your file. Patching would
mean splitting `w:r` elements at sentence boundaries and re-serialising the whole part, which risks
corrupting a user's document for a cosmetic gain. The report is a derived artifact; your file is only
ever read.

---

## LaTeX specifics

The preamble is dropped (everything before `\begin{document}`). Heading commands are converted to a
sentinel **before** the generic command stripper runs — otherwise `\section{Introduction}` is deleted
as an unknown command and the document loses its structure, which is a defect that was found and fixed
during development.

Table, figure, algorithm, `tabular`, `verbatim`, `lstlisting` and `tikzpicture` environments are
dropped: their contents are not prose.

Citation commands become markers: `\parencites{a}{b}` → `[a;b]`, `\cite{a,b}` → `[a,b]`. `\pdfcomment`
margin notes (the mechanism the reference implementation uses) are dropped as metadata. Formatting
commands that carry visible text (`\textbf`, `\emph`, `\hl…`, `\SI`, …) are unwrapped; their content is
kept.

Mathematics is left alone. A sentence containing display math may not survive intact; this is a known
limitation and the report is not the right tool for a mathematics-heavy document.

---

## PDF specifics

`pdftotext -layout` is preferred because it preserves visual line layout, which matters for two-column
papers and for keeping a number next to its label. Page breaks are preserved so locators can be
page-accurate.

Paragraphs are reassembled from the extracted lines: a block separated by a blank line becomes one
paragraph, and a line ending in a hyphen is joined to the next (de-hyphenation) unless it ends in `--`.
Lines that are only a page number are dropped.

Headings are guessed from short lines that look like headings. The heuristic deliberately **keeps**
`References`, `Introduction`, `Methods`, `Results` and `Discussion` as body text rather than treating
them as headings, because losing the section boundary matters less than mislabelling body text.

Below 50 characters per page, extraction is treated as failed and the file is reported as
`unavailable` with the reason. A file with **no** text layer at all — a scan — gets its own
reason: it says the document has no text layer rather than blaming a missing extractor, and it
reaches `insufficient_input` (exit 4), because a document the tool could not read is an input
condition, never a document that graded to zero sentences. There is no OCR: the refusal probes
for `tesseract` with `shutil.which` only to name the install route, and OCR text is never
graded, because a transcription error would become a finding about the document.

All three ways a PDF can be unreadable reach that same status with a distinct
`input_gaps[].kind`, and none of them is a finding:

| Condition | `kind` | Worklist says |
|---|---|---|
| An extractor ran, the file has no text layer | `no_text_layer` | install `tesseract` and export the scan, or supply a text export |
| Extraction below the per-page threshold (probably a scan) | `no_text_layer` | as above |
| Neither `pdftotext` nor `pypdf` is available | `no_pdf_extractor` | install poppler or `pypdf`, or pass a `.txt` export |
| An extractor is installed but cannot decode the file | `unreadable_pdf` | supply a readable copy or a text export |

The third row is the one that matters most on a machine with no PDF tooling at all: it used to be
reported as `INVALID_INPUT` with the *finding* exit code 1, which reads as a verdict on the document
when nothing had been read. Set `CITATION_REPORT_PDF_EXTRACTOR=none` to force that route where an
extractor is installed; the self-test uses it so both routes are covered on every machine.

### OCR: reading a scan, and what it costs

A scan — no text layer, or a text layer too thin to grade — is transcribed when `tesseract` and
poppler's rasteriser (`pdftoppm`) are both installed. The tier is on by default, and every part of it
is labelled:

- the document carries `transcribed: true` and `transcription: tesseract:<lang>`;
- a transcribed source's `evidence_origin` begins `ocr:`, and `red_capable` is false for it;
- `transcription.sentences_resting_on_ocr` counts the sentences that rest on a transcription, and all
  three artifact formats print that count in their Limits section;
- **a contradiction where either side was transcribed is `unverifiable` (rule D13), never a
  conflict.** Measured: tesseract read `95% CI` as `95% Cl` on a real scan, and on the same fixture
  the same words with a text layer are still a `conflict` — so provenance, not the value, is what
  decides.

The refusals are input gaps like every other unreadable-PDF outcome: `ocr_failed`, `ocr_empty`,
`ocr_page_limit` (a scan longer than `--ocr-max-pages`, refused rather than partly read),
`ocr_language_missing`, and `no_pdf_rasterizer`. `--no-ocr` (or `CITATION_REPORT_OCR=none`) switches
the tier off, and the refusal then names the switch rather than claiming the build cannot transcribe
— a machine with the engine installed is told the truth about why nothing was read.

---

## Intake preconditions

Four checks run before any finding is reported, because each of them, when it fails, makes findings
meaningless rather than merely incomplete. They are documented with their thresholds in
`evidence-and-limits.md`; a failure makes the run `insufficient_input` (exit 4).

`CITATION_STYLE_UNRECOGNISED` · `TRIGGER_LANGUAGE_UNSUPPORTED` · `SENTENCE_SPLIT_SUSPECT` ·
`NO_SOURCE_LIST`

Each records its observed value whether it passes or fails, so the artifact shows the basis on which
the findings were made.

## Adding a format

1. Add a reader returning `list[DocParagraph]` with a `kind` from the existing vocabulary.
2. Add the suffix to `SUPPORTED_SUFFIXES` and dispatch it in `read_document`.
3. State in this file what the reader cannot see — the disclosure is part of the reader.
4. Add a fixture to `assets/` and an end-to-end check to `selftest.sh`, including the refusal path.
