# eval.md — how to tell whether a citation report is any good

A report is not good because it looks thorough. It is good when its claims about a document are
checkable and right. Grade one against the checks below; each has a failure it is designed to catch.

---

## 1. Can you recompute every number?

Pick three figures from the coverage bar and recompute them by hand from `verdicts.json`.

* `states` must sum to `sentences_total`.
* `citation_coverage.numerator` must equal `attributed + synthesis`.
* `citation_coverage.denominator` must equal `sentences_with_support_claim`, which must equal
  `sentences_total - states["no_citation_needed"]`. Check the numerator is a subset of it, and that
  `sentences_requiring_citation` is reported separately rather than used as the denominator.
* every rule id in `rules` must appear in `references/verdict-rules.md`, with the state it produced.

**Fails when:** a summary prints a percentage with no denominator, or a "score" nobody can derive. The
reference tool this skill is modelled on prints `Citation Coverage: 50%` and `Citation Quality Score:
97.5%` with no stated formula. A number a reader cannot recompute is decoration, and it invites a
reader to trust the tool instead of the document.

## 2. Are the greens earned?

Pick five dark-green sentences. For each, open the cited source at the locator in the note and confirm
the value is there.

**Fails when:** a source with no readable evidence still produces green. Check that every
`attributed` verdict has a source with `evidence_availability` of `full_text` or `abstract`, and that
`missing_numbers` is empty. This is the claim most worth attacking: a report that paints green without
evidence is worse than no report.

## 2b. Are the greens earned by a *distinctive* value?

Pick five dark-green sentences and check the `quantities` entry for each: the values a verdict rested on
are the ones with `"checkable": true`.

**Fails when:** a green rests on a bare small integer, a numbered label (`ICD-11`, `DSM-5`, `PCL-5`), or a
structural pointer (`Figure 2`, `phase 2`, `grade 3`). A small integer is everywhere in extracted text —
page numbers, list numbers, a protein name like "metalloproteinase 9" — so finding one proves nothing.
This is not hypothetical: on a real 1,027-sentence document, **11 of 12 greens rested on the digits of
`ICD-11` or `DSM-5` and the twelfth on a protein name**, i.e. every green was false. After the fix that
document reports zero greens. Run `python3 benchmarks/bench_verdicts.py` and confirm the accusation
sensitivity has not gone to zero while you were checking: a rule that never fires is also a failure.

## 3. Are the reds defensible?

Pick every red sentence. For each, the note must give a rule id, a source id, a locator, and either a
quoted evidence span or the offending citation token.

**Fails when:** any red exists without a quote or a locator, or a red is justified only by a number
being *absent* from the evidence. Absence is D07 and is a warning, never red. A red is an accusation;
it has to be checkable in seconds or it should not be printed.

**A citation that matches no source is not a red.** An unmatched marker has no link to the work it
names, and the red bar requires an identity-verified link, so D03 lands on `unattributed` and warns.
Calling it a conflict made the tool refuse its own report, because the gate correctly rejects a red
whose link is inferred. Pin both directions:

* **Pass fixture.** A document whose only defect is a citation that resolves to nothing (for example
  `An exploratory analysis suggested a benefit [99].` against sources S001 to S003) grades to
  `unattributed`, records the `UNRESOLVED_CITATION` trigger, and its own gate verifies the artifacts
  without reporting `CONFLICT_LINK_INFERRED`.
* **Fail fixture.** Tamper a legitimate D04 red's `link_confidence` to `inferred`. The gate must still
  exit 1 with `CONFLICT_LINK_INFERRED`. The fix narrowed D03; it did not weaken the bar.

Both fixtures run in `scripts/selftest.sh`, sections 6 and 6b.

## 4. Is the orange honest?

Sample ten orange sentences. Each must genuinely need a citation, and each must genuinely have none.

**Fails when:** a well-cited-looking sentence is orange because the marker grammar missed its citation
style, or an ordinary method statement is orange because the trigger was too broad. During development
`at least one`, `at most`, `most participants` and bare `leading` all produced orange sentences a
careful author would rightly reject; they are no longer triggers. If you find a new one, add it to the
non-trigger list in `self_test.py` and to the benchmark before changing the rule.

Check specifically: does the orange count move when you add the bibliography file the document's
citation style actually uses (`--bib`, `--style numeric|author-year`)?

**The trigger has a measured sensitivity and specificity, so read both.** Run
`python3 benchmarks/bench_verdicts.py` and look at section C. On the last measurement the trigger scored
**sensitivity 0.867 and specificity 1.000** on 40 unseen real sentences. Specificity 1.000 is asserted by
the benchmark — a false orange accuses an author of failing to cite something they did cite. Sensitivity
is not asserted, so a miss is expected and acceptable: an earlier revision scored 0.300, and the 21
misses it produced are what drove the rules to be broadened. If you find a sentence that needs a citation
and is not flagged, add it to `REAL_SAMPLE` in `benchmarks/bench_verdicts.py` with its label before
changing a rule, so the change is measurable rather than a guess.

## 5. Is `unverifiable` used honestly, in both directions?

An `unverifiable` state is a statement about *your inputs*. It should appear when a cited source was
identified but not held, and it should **not** appear when evidence was available.

**Fails when:** a run with full-text sources still produces `unverifiable` for most sentences (the
evidence attachment is not working), or a run with no evidence at all produces greens (the evidence
gate is not working). Compare `sources_report.csv` against the state distribution: the number of
`full_text` sources and the number of `attributed` sentences should move together.

## 6. Does the reference list stay out of the prose?

For a document with a bibliography, check that no verdict's sentence id falls on a reference entry.

**Fails when:** reference entries are graded, which shows up as a burst of `conflict` findings whose
text is a citation, or whose offending token is `Internet`, `Epub`, or `cited 2026`. This was a real
defect: 47 of 48 entries were falsely reported until the reference list was marked structural.

## 7. Is the advisory channel inert?

```bash
python3 scripts/report.py report --document draft.md ... --advisory off --out-dir a/
python3 scripts/report.py report --document draft.md ... --advisory grades.json --out-dir b/
python3 - <<'PY'
import json
a = json.load(open("a/verdicts.json")); b = json.load(open("b/verdicts.json"))
def strip(d):
    return [{k: v for k, v in r.items() if k != "advisory"} for r in d["verdicts"]]
assert strip(a) == strip(b)
assert a["coverage"] == b["coverage"]
assert a["gate"] == b["gate"]
print("advisory channel is inert")
PY
```

**Fails when:** any of those assertions fails. A model output that can change a gate verdict is a
model output nobody can audit.

## 8. Do the artifacts contain what they claim?

```bash
python3 scripts/report_gate.py --dir citation-report/ --document draft.docx
```

Every artifact must re-open, and its counts must match the verdict list: shaded runs and Word
comments in the DOCX, coloured spans in the HTML, painted rectangles and findable printed notes in the
PDF.

**Fails when:** the PDF's notes are only annotations. This is the specific regression the gate exists
to catch: extract the PDF's text layer and confirm note bodies are present there. If notes live only
in `/Annots`, they are invisible in print and most viewers, which defeats the reason for choosing
printed notes.

## 8b. Is the input/result boundary visible?

The failure this guards against is a *true* claim presented as the wrong kind: `0/508` printed where a
verdict on the document belongs.

* Run against a document whose cited sources you deliberately do not supply. The run must be
  `insufficient_evidence`, exit **3**, and write `evidence_worklist.csv`.
* The artifacts must carry an `INPUT-BOUND — NOT A FINDING` banner whose colour and wording differ from
  the gate banner, and the coverage line must state the reason beside the figure.
* Supply the files the worklist names, re-run `worklist`, and confirm the count closes — and that the
  report then reports its real findings.
* Confirm `--allow-insufficient` keeps `insufficient_evidence` as the status while restoring the
  findings-based exit code. If the status becomes `pass`, the override is hiding something.

**Fails when:** a run that could check nothing reports `pass`, or reports a bare percentage with no
reason, or the status disappears when the policy is overridden.

## 8c. Does every accusation clear the red bar?

Take every red finding and check all three:

1. the link is `exact` — a declared id, a supplied file, or a resolved DOI, never a title match;
2. the evidence is `primary` or `recorded_estimate`, never a `prose_summary`;
3. the note quotes the contradicting value with a locator.

Then try to break it: point a contradiction at a ledger row that records only `main_finding`, and at a
source linked by a title match. Both must come out `unverifiable` (rules `D12` and `D11`), not red.

Then check the boundary: a rule that cannot produce a link must not produce a red. D03 is that rule. An
unmatched citation marker has no link by construction, so it warns, and the run's own gate must verify
its artifacts instead of reporting `CONFLICT_LINK_INFERRED`. Section 3 holds both fixtures for it.

**Fails when:** a red exists whose `link_confidence` is `inferred` or whose `evidence_strength` is
`prose_summary`. Editing `verdicts.json` to create one must also fail the gate
(`CONFLICT_LINK_INFERRED`, `CONFLICT_EVIDENCE_TOO_WEAK`).

## 8d. Did the tool understand the document?

Read the `preconditions` array in the audit output. All four report an observed value whether they pass
or fail. Then try to make each one fail:

* a document with a real bibliography and no citation marker in its prose → `CITATION_STYLE_UNRECOGNISED`
* a non-English body → `TRIGGER_LANGUAGE_UNSUPPORTED`, with or without numbers in it, and at any length once it is clearly another language (a short English method paragraph is not blocked)
* one enormous unpunctuated block → `SENTENCE_SPLIT_SUSPECT`
* citations with no reference list, bib or ledger → `NO_SOURCE_LIST`

All four must exit **4**. And a two-sentence document must **not** trip the split check: in a two-sentence
document the longest is inevitably about half the text.

**Fails when:** any of these reports `pass`, or a short legitimate document is blocked.

## 9. Does a bad input fail loudly?

Run each of these and confirm a non-zero exit and a legible reason, not a confident empty report:

* a `.pdf` document with `pdftotext` and `pypdf` both unavailable — a gap in the machine, so exit 4
  with `insufficient_input` and `input_gaps[].kind = no_pdf_extractor`, never exit 1;
* a verdict whose evidence has no recorded origin (`EVIDENCE_WITHOUT_PROVENANCE`);
* a scanned PDF with no text layer — read by OCR where the engine is installed, and otherwise exit 4
  with `input_gaps[].kind = no_text_layer`; with `--no-ocr`, exit 4 and a reason that names the
  switch (where tesseract is installed) or the install route (where it is not);
* an unsupported extension;
* a `verdicts.json` whose `state` does not match its `rule_id`;
* a `coverage.json` with one state count incremented by hand.

**Fails when:** any of these produces a report that looks clean. Silence in the failure path is the
defect this repository exists to prevent.

---

## 10. Does a transcription stay a transcription?

Build a one-page scan (an image PDF with no text layer) whose text contains a value that contradicts
the source it cites — `(HR 0.50) [src:S001]` against a source recording `HR 0.80` — and check four
things:

* with OCR available, the run is **not** a conflict: the verdict is `unverifiable` under `D13`, the
  note names the engine as what read it, and `transcription.sentences_resting_on_ocr` is at least 1;
* the run is **`insufficient_evidence` (exit 3) by default** with a `TRANSCRIBED EVIDENCE` banner,
  and `--allow-insufficient` exits 0 while the status still says `insufficient_evidence` and the
  override appears in the artifact;
* asking for an engine that is not installed (`--ocr-engine rapidocr` where the package is absent)
  exits 4 with `input_gaps[].kind = ocr_engine_unavailable` rather than silently using another one;
* `--ocr-max-pages 0` reads a scan that the default cap would have refused, and a scan longer than a
  finite cap is refused rather than partly read;
* the **control** — the same sentence in a `.md` file — *is* a conflict (`D08`, exit 1), so the
  provenance is what changed the outcome rather than the value;
* a scanned **source** PDF behaves the same way, with `evidence_origin` beginning `ocr:`;
* the count appears in the PDF, DOCX and HTML artifacts (in their Limits section), and a run with no
  OCR shows no such line.

**Fails when:** a transcribed value produces a red finding, when the artifact does not say the text
was transcribed, or when a run that never used OCR claims it did.

---

## Scoring a run against a labelled set

`benchmarks/bench_verdicts.py` measures the deterministic channel against hand-labelled sentences and
reports precision and recall per state, plus the precision of each trigger reason. Run it before
changing any rule.

Reading the output:

* **`conflict` precision must be 1.00.** A red finding is an accusation; there is no acceptable rate of
  false accusation here. If precision drops, narrow the rule that caused it. The red rules are D04
  (retracted source) and D08 (contradicted value): both rest on an identity-verified link. D03 is not
  among them, because an unmatched marker has no link to verify.
* **`unattributed` precision should stay above 0.9.** Orange is the noisiest state, because
  "needs a citation" is a judgment about prose. Recall matters less than precision: a missed orange
  costs a reader a moment, a false orange costs the report its credibility.
* **`attributed` recall should be high**, and every `attributed` must carry evidence — a precision of
  1.00 is a precondition, not a result.
* **Advisory agreement** is reported separately and must never be presented as gate-grade. The
  repository's own measurement of a comparable classifier found chance-level accuracy on a seven-way
  choice and a failure on a causality trap. Read an advisory row as a hint, not a finding.
