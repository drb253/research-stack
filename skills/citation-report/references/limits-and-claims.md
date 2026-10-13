# Limits and claims

What this report does and does not assert. Stated here so that nobody has to infer it from the output,
and so a reader can hold the tool to its own words.

---

## What a colour means

A colour is a statement about **attribution integrity**: whether the sentence's own checkable values
can be found in the evidence held for the sources it cites. It is not a statement about whether the
sentence is true, well written, important, or appropriate for the venue.

| The report says | The report does not say |
|---|---|
| every value in this sentence is present in the cited source's evidence | the sentence is correct in every respect |
| this sentence carries no independently checkable value | the sentence is unoriginal |
| this citation resolves to no work in the reference apparatus | the author intended to fabricate |
| this value contradicts the same named measure in a source we hold | the sentence is scientifically wrong |
| we held no evidence for the cited source | the source does not support the sentence |

---

## Not a plagiarism report

This is not a similarity report and it does not compute an overlap percentage against any corpus. It
does not compare a draft to published text; it compares a draft to the sources the draft cites.

The two questions are genuinely different. A sentence can be heavily paraphrased from a source it does
not cite — this report will not see it. A sentence can quote a source verbatim with a correct citation
— this report will mark it `attributed`.

For overlap detection, that is `originality-check`. For attribution of flagged passages, that is
`citecheck`. This skill answers a third question: **is the citation support actually there?**

## Not an AI-writing detector

Nothing here estimates whether text was machine-written, and nothing here will help make text evade
such a detector. The repository refuses detector evasion by design. If a passage is borrowed, the fix
is a citation.

## Not a gate on your writing

The gate blocks on `conflict` findings and warns on `unattributed` and on numbers absent from the
evidence. It does not block on `unverifiable` — that state describes our inputs, not your document,
and failing a build because a PDF was not supplied would be the wrong incentive. The consequence is
that `unverifiable` can be ignored, and a run that is entirely `unverifiable` reads as clean for the
wrong reason. That is why the coverage summary counts it separately and why the limitations section
of every artifact names it explicitly.

---

## The input-bound case

A run whose cited sources cannot be read is not a finding about the document. It is reported as
`insufficient_evidence` (or `insufficient_input`), blocks by default, and writes a worklist. The
acquisition tiers, the evidence-strength rules and the red bar are in `evidence-and-limits.md`; the
repository-wide principle is `docs/EVIDENCE-INVARIANT.md`.

## Evidence limits, and what each costs you

**Full text is the only evidence that supports page-accurate claims.** A note citing `p.13` came from
a PDF whose text layer was read. If the paper is scanned, or the tables were images, those values are
absent from the evidence and the sentence becomes `unverifiable` (D07), never red.

**An abstract is much weaker.** It rarely contains the numbers in the sentence, so a citation resolved
to an abstract will usually produce D07 rather than D09. Every note that relies on an abstract says
`evidence: abstract`. Do not read an abstract-based run as a clean bill of health.

**Tables, figures and supplementary material usually do not survive extraction.** This is the single
most common reason a correctly cited number is reported as not found. D07 is a warning rather than an
error for exactly this reason.

**Preprints and version drift.** A DOI resolves to the version of record; a sentence may legitimately
quote a preprint or a different version. The report will report the mismatch as D07 or D08. This is a
real finding to check, not automatically an author error.

**Retraction checking is only as current as the authority.** Crossref and OpenAlex signals are
consulted when the network is enabled. With `--offline`, `retraction_status` is `not_checked` and that
is recorded per source. A retracted source can therefore pass unnoticed in an offline run — the one
place where `--offline` weakens a safety check rather than just a convenience.

**Nothing is checked about the sources themselves beyond identity.** That a source is peer reviewed,
that its design supports its claims, that it is not superseded: out of scope. This is about the join
between a sentence and its citation, not about the quality of the literature.

---

## Structural limits

| Limit | Why, and what to do |
|---|---|
| DOCX comments are not read, and deleted text is not | Comments are reported as a warning when present. Insertions (`w:ins`) **are** read and graded; deletions (`w:delText`) are not, so a sentence removed by a tracked change is silently absent. Footnotes, endnotes and text boxes *are* read and graded |
| A PDF with no text layer is refused, not graded | A scan is `insufficient_input` (exit 4) with a scan-specific reason. No OCR is applied: OCR text is a transcription, and a misread value would become a finding about the document |
| Tracked changes are not applied | A deleted sentence may still be read. Accept all changes before reporting |
| DOCX output is a derived document | Patching the original risks corrupting a user's file. The report is rendered from the parsed model |
| Mathematics is not parsed | A `.tex` file with display math may lose sentence boundaries. Not the right tool for a mathematics paper |
| Non-Latin-1 text in the PDF is transliterated or replaced | The count is reported. Use HTML or DOCX output for CJK, Greek-heavy or Cyrillic text |
| Author-year citations are matched by year only when unambiguous | With several sources sharing a year, the marker is left unresolved rather than guessed |
| The report does not know what it did not receive | If you supply sources for one section only, sentences in other sections are `unverifiable`, which looks the same as a section whose sources were supplied but unreadable. The per-source evidence table in the artifacts is what distinguishes them |

---

## Claims about the deterministic channel

These are the claims the design is built to make good on, each with the mechanism:

| Claim | Mechanism |
|---|---|
| A sentence is never painted green without evidence | D09 requires readable evidence; a source with `metadata_only` or `unavailable` cannot produce `attributed` |
| A sentence is never painted red because a number was absent | D08 requires the same named measure with a different value, and quotes it. Absence is D07, a warning |
| A fabricated citation in a known apparatus is always an error | D03 fires when the apparatus is closed and a marker matches nothing, whether or not other markers resolve |
| The advisory channel cannot change a verdict | Advisory grades are stored in a separate field, read by no rule, and `selftest.sh` asserts byte-identical deterministic output with the channel on and off |
| Every printed number can be recomputed | `coverage.validate` refuses a summary whose parts do not sum; `report_gate.py` recomputes from the verdict list and fails on disagreement |
| Every span still locates its own sentence | Re-checked from the document on every gate run; a mismatch is an error |
| Every artifact contains what it claims | The gate re-opens each artifact and counts shaded runs, comments, coloured spans and, for the PDF, requires the printed notes to be findable in the text layer |

## Claims that are deliberately not made

* **"This document is citation-clean."** The report says which sentences it could check and which it
  could not. It never certifies the whole document.
* **"This sentence is supported by the literature."** It says a value is present in a source's
  evidence. Whether the source *means* what the sentence says is a reading question, and that is what
  the advisory channel is for — clearly labelled as advisory, and never a gate input.
* **A single quality score.** There is no scalar. The honest one is printed under its own name
  (`attributed_share_of_all_sentences`) and it is deliberately harsh.
