# Verdict rules

Every sentence gets exactly one state, assigned by exactly one rule. The rule id is printed on every
note in every format, so a reader can look up why a sentence was coloured the way it was. The table is
mirrored in code at `scripts/verdicts.py::RULES`, and `selftest.sh` asserts that the two never drift.

Rules are evaluated **in the order below, first match wins**. The order matters: D11, D12 and D13 sit
before D09 so that a contradiction which cannot be asserted is recorded as unverifiable, never quietly
downgraded into a green.

Every red must also clear the **red bar** — an identity-verified link, machine-comparable evidence, and
text that was read rather than transcribed by OCR.
`report_gate.py` re-checks that from the recorded verdicts, so the bar cannot be bypassed by editing a
file. Full detail: `evidence-and-limits.md`.

---

## D01 — no citation needed

**State** `no_citation_needed` · **Severity** info · **Colour** none

Predicate: the sentence carries no citation marker **and** no attribution-requiring signal
(`_signals.citation_triggers` returns nothing).

Excluded from the coverage denominator. Printed in the distribution anyway, because a report that
silently drops the sentences it did not judge is not a report.

## D02 — unattributed

**State** `unattributed` · **Severity** warning · **Colour** orange

Predicate: an attribution-requiring signal is present and the sentence has no resolvable citation to a
*work*.

Three ways to arrive here:

1. no marker at all, but the sentence states a statistic, a superlative, a vague attribution
   ("studies show"), or a borrowed definition;
2. a marker that is a claim marker only (`[claim:C006]`) — a claim reference names a registered claim,
   not a source, so on its own it attributes nothing;
3. markers exist but none resolves, **and** the reference apparatus is not closed (see D06) — with no
   source list supplied, "unresolved" is a gap in our inputs, not a finding about the sentence.

The note names the trigger, e.g. `States something checkable (statistic, vague attribution) with no citation.`

### What fires the signal

| Trigger | Fires on |
|---|---|
| `STATISTIC` | any numeric assertion: percent, `p` value, `HR`/`OR`/`RR`, fraction, `n =`, range, unit, duration, year. Also a **statistical noun carrying a quantity** (`prevalence of`, `scores were higher`), an **approximation hedge** (`approximately`, `roughly`, `nearly`, `circa`), and an **associational or causal claim** (`is associated with`, `correlate with`, `predicts`, `prevents`, `reduces`, `increases`, `requires`) — these assert a relationship the reader is owed a source for. The digits of a **numbered label** (`ICD-11`, `DSM-5`, `PCL-5`) are masked first: a label names a version, it does not measure anything. |
| `SUPERLATIVE` | `the first`, `the largest`, `the most common`, `the only`, `majority of`, `unprecedented` |
| `VAGUE_ATTRIBUTION` | A **named body of evidence plus a reporting verb**, with up to four intervening lowercase words and an optional auxiliary or adverb: `studies show`, `research has documented`, `investigations describe`, `observations indicate`, `models of prolonged stress similarly show`, `instruments explicitly operationalise`. Plus the passive forms (`is described as`, `is widely acknowledged as`, `were consistently operationalised using`) and vague attribution (`experts agree`, `it is well established`, `according to some`). The interpolation is capped at four words so the subject cannot drift into another clause. |
| `DEFINITION` | `is defined as`, `refers to`, `is characterised by`, `is the term for` |

Deliberately **not** triggers: `at least one`, `at most`, `most participants`, a lone year, a bare method
statement, and `produce`/`produced` — "might have produced" is the author's own hedged inference, and
including it was measured to cost a true negative. `about` is excluded from the hedge list because it
matched the preposition in "thinking about how ... might have produced".

### Measured behaviour of the trigger

`benchmarks/bench_verdicts.py` scores the trigger on 48 constructed cases and on **40 unseen sentences
from a real review**, with confusion matrices and Wilson intervals. The last measurement:

| Trigger | Accuracy | Sensitivity | Specificity |
|---|---|---|---|
| 48 constructed cases | 1.000 | 1.000 | 1.000 |
| 40 unseen real sentences | **0.900** | **0.867** | **1.000** |

Specificity is asserted, not just printed: a false orange accuses an author of failing to cite something
they did cite, so the benchmark fails if specificity drops below 1.000 on the real sample. Sensitivity is
reported rather than asserted, because a missed gap costs a reader a moment and the trade-off is real —
an earlier revision of these rules scored accuracy 0.475 and sensitivity 0.300 on the same 40 sentences,
and the difference is documented in `docs/BENCHMARK-RESULTS.md`.

## D03 — citation resolves to nothing

**State** `conflict` · **Severity** **error** · **Colour** red

Predicate: a citation marker is present, the reference apparatus **is** closed (a reference list, a
BibTeX file, a ledger, or numbered sources — so we know what the citable set is), and the marker
matches no source in it.

Two shapes:

* every marker in the sentence is unmatched;
* some markers resolve and others do not. A fabricated citation beside three real ones is still a
  fabricated citation, so this is an error either way.

This is the finding the reference tool structurally cannot produce, because it never checks that a
citation resolves to a real work. The note names the offending marker: `Citation `99` matches no
source in the document's reference apparatus.`

**Not** this rule: a marker that resolves to an entry which has no DOI and no full text. That is
D05 — the entry exists.

## D04 — retracted source

**State** `conflict` · **Severity** **error** · **Colour** red

Predicate: a cited source has `retraction_status == "retracted"`.

Set from Crossref `update-to` / `relation` types, OpenAlex `is_retracted`, or the `retraction_status`
column of a ledger. The note names the source and the signal that flagged it.

## D05 — no evidence held

**State** `unverifiable` · **Severity** info · **Colour** steel blue

Predicate: at least one citation resolves to an identified source, and **none** of the cited sources
has evidence we can read (`evidence_availability` is `metadata_only` or `unavailable` for all of them).

The note names the availability so the fix is obvious: supply the PDF, or allow DOI resolution to
fetch an abstract. This state is the honest answer to "we cannot tell", and it is why this report has
six colours rather than four.

## D06 — citation unresolvable, no apparatus supplied

**State** `unverifiable` · **Severity** info · **Colour** steel blue

Predicate: markers are present, none resolves, and the reference apparatus is **not** closed — no
reference list, no BibTeX, no ledger with numbered sources.

Distinguishing D06 from D03 is the whole reason `_apparatus_is_closed` exists. With no source list,
"citation `[4]` does not resolve" describes our inputs, not the document, and accusing the writer
would be exactly the false finding this design is built to avoid.

## D07 — number absent from the evidence held

**State** `unverifiable` · **Severity** warning · **Colour** steel blue

Predicate: citations resolve, at least one cited source has readable evidence, and at least one
checkable value in the sentence is **not** present anywhere in that evidence.

**This is not a contradiction and is never red.** Extracted text is lossy: tables, figures,
supplementary material and equations routinely do not survive PDF extraction. The note lists the
values that were not found so a human can check them by hand in seconds.

A `year` is not checkable here — publication years are citation metadata, verified by resolving the
DOI against an authority, and frequently appear only in the reference list rather than in the evidence
text. Confidence-interval *levels* (`95%`) are apparatus, not results, and are likewise excluded.

## D08 — contradiction

**State** `conflict` · **Severity** **error** · **Colour** red

Predicate: the sentence states an explicitly labelled measure (`HR`, `OR`, `RR`, `aHR`, `IRR`, `SMD`,
…) with a value, a cited source we hold states **the same label** with a **different** value, and the
two are not numerically equal.

The note quotes both and gives the locator:
`Contradicts HR in S001: the sentence reports 0.50, the source reports 0.8.`

**Deliberately narrow.** Only a labelled measure can contradict. An unlabelled number never can,
because the same value legitimately appears in many roles — sample size, year, dosage, page. Widening
this rule is the single easiest way to make the report produce false accusations, and any widening
must be measured first (see `eval.md`).

Numerical equality tolerates formatting (`30` = `30.0`) and is strict about magnitude; a relative
tolerance of 1e-6.

## D11 — the link is inferred, so the conflict cannot be asserted

**State** `unverifiable` · **Severity** warning · **Colour** steel blue

Predicate: a rule would have produced a `conflict` (D04 or D08), but the citation's link to that source
is `inferred` rather than `exact`.

An inferred link means the identity of the work was **guessed**: matched to a reference entry by title
or by first-author-year, or not linked to a verified identifier at all. Accusing a document of
contradicting a source we are not sure it cited is a false accusation, so the finding is disclosed
instead of asserted. The note says which source and what would confirm it.

An `exact` link is one the document declared (`[src:S001]`), one the user declared (a BibTeX
`file = {...}` or a supplied file), or one confirmed by resolving the DOI against an authority.

**Not** this rule: a link that is exact but whose evidence is weak. That is D12, or D13 when the
weakness is that OCR read it.

## D12 — the evidence is a summary, so the conflict cannot be asserted

**State** `unverifiable` · **Severity** warning · **Colour** steel blue

Predicate: a rule would have produced a `conflict` (D04 or D08), the link is exact, but the evidence is
a `prose_summary` — the extractor's own sentence in `main_finding` or `key_outcomes` — rather than
`primary` text or a `recorded_estimate` copied verbatim.

A value the ledger copied (`HR 0.80`, `n = 1000`, `24 months`) is machine-comparable and may convict.
A sentence the extractor wrote is an interpretation, and if the interpretation is wrong the tool would
issue a confident false accusation. The note gives the sentence, the source and the two values, and
names the two ways to turn it into a finding: supply the source file, or record the verbatim effect
estimate.

**Accepted cost:** conflict recall falls. Some genuine contradictions visible only through a prose
summary are no longer red. The benchmark measures the change rather than hiding it, and conflict
precision stays at 1.000.

## D13 — the value came from OCR, so the conflict cannot be asserted

**State** `unverifiable` · **Severity** warning · **Colour** steel blue

Predicate: a rule would have produced a `conflict` (D04 or D08), the link is exact, the evidence is
machine-comparable — but the sentence's text, or the evidence held for the cited source, was
transcribed by OCR.

A transcription is a machine's reading of an image. It is good enough to *describe* what a paper says
and to support a positive attribution; it is not good enough to accuse an author of contradicting a
source, because a single misread character moves a value. Measured on a real scan built for the test:
tesseract read `95% CI` as `95% Cl` — an upper-case I became a lower-case l. A contradiction built on
that would be the tool's error presented as the author's.

The note names the side that was transcribed (`tesseract:eng`) and what would close the gap: a
text-layer copy of the document, or a corrected text export for the source. Both directions are
covered, because a misread *sentence* value against a correctly read source is just as false an
accusation as the reverse.

**Accepted cost:** a genuine contradiction visible only through a scan stays `unverifiable`. It is
counted in `transcription.sentences_resting_on_ocr` and stated in every artifact, so the cost is
visible rather than silent. On the control fixture — the same words with a text layer — the verdict is
still `conflict`/D08, so what changed the outcome is provenance, not the value.

### What may serve as a checkable value

Not every number in a sentence is a measurement, and only a measurement can support a green. Each
quantity is recorded with a `checkable` flag:

| Kind | Checkable? |
|---|---|
| percent, `p` value, `HR`/`OR`/`RR`, fraction, `n =`, range, unit, duration | yes — each carries its own context |
| a bare number | only when it is **≥ 20 or has a decimal part** |
| a numbered label (`ICD-11`, `DSM-5`, `PCL-5`) | **no** — the digits are masked before extraction |
| a structural pointer (`Figure 2`, `Table 3`, `phase 2`, `type 2`, `grade 3`) | **no** — masked |
| a year, a confidence-interval level | no — metadata and apparatus |

The threshold exists because a small integer is ubiquitous in extracted text: page numbers, list
numbers, ages, "9 of 12", a protein name like "metalloproteinase 9". Finding one proves nothing and
finding none proves nothing, so it cannot be the basis of a claim of support. Measured on a real
document, this was the mechanism behind **12 of 12** false greens; after the fix that document reports
zero greens, which is the correct answer for its sources.

Values that are not checkable are still recorded on the verdict, so a reader can see every number the
sentence contains and which of them a colour rested on.

## D09 — attributed

**State** `attributed` · **Severity** info · **Colour** dark green

Predicate: citations resolve; at least one cited source has readable evidence; the sentence carries at
least one checkable value; and **every** checkable value in the sentence is present in the evidence of
some cited source.

The note names the values and the sources: `Every value in the sentence (HR 0.80) is present in the
evidence of S001.` Each source record in `verdicts.json` carries the locator and a quoted evidence
span for the note.

## D10 — synthesis

**State** `synthesis` · **Severity** info · **Colour** light green

Predicate: citations resolve and at least one cited source has readable evidence, but the sentence
carries **no** independently checkable value.

Typical: comparative statements, conclusions, summaries, and sentences whose content is structural.
Operationally defined — this is "there is nothing here to look up", not a model's opinion that the
sentence is good synthesis. A model's opinion belongs in the advisory channel.

---

## The advisory channel

Channel A is stored in a separate field (`advisory`) on the verdict and rendered in a visually
distinct way — a separate note block prefixed `advisory:`, never the sentence background.

Vocabulary: `direct_support`, `synthesis`, `unsupported`, `contradictory`.

Every advisory entry carries:

* the **quoted source span** the grade was based on, and
* the `evidence_availability` of that source, so an abstract-only grade is disclosed as weaker,
* the fixed disclosure string `advisory, model-generated, not a gate input`.

`verdicts.load_advisory` validates every grade against the controlled vocabulary and rejects an
unknown value rather than accepting it quietly. An advisory grade can never:

* set, change or veto `state`, `rule_id` or `severity`;
* contribute an `error`-severity finding, and therefore never affects the gate verdict;
* change any number, quote, locator or reference in the output.

`selftest.sh` asserts this by rendering with `--advisory off` and with `--advisory <file>` and
requiring the deterministic verdicts, state counts, coverage arithmetic and exit code to be identical.

---

## Adding a rule

1. Add the entry to `RULES` in `scripts/verdicts.py` with state, severity and meaning.
2. Add the predicate to `_classify`, in the right position in the ladder.
3. Add the record to this file, in the same position, with the predicate stated as a test.
4. Add both a triggering and a non-triggering fixture to `selftest.sh`.
5. Measure it: add labelled sentences to `benchmarks/bench_verdicts.py` and report precision.

Step 5 is not optional. Every rule here that produced a false positive in development was found by
reading the rule's own output against real prose, not by inspection.
