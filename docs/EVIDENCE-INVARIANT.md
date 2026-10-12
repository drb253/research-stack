# The evidence invariant

**An input gap must never be reported in the same channel, shape, or exit status as a finding
about the artefact under test.**

This document states the rule once so every skill in this repository can be held to it. It exists
because the rule was broken, and the break was invisible.

## What went wrong

A 1,027-sentence document was graded against 62 identified sources while holding readable evidence
for **none** of them. The run reported:

```
Citation coverage: 0/371 = 0.0%
```

Nothing in that line was false. `0/371` is an accurate count of sentences that were attributed or
synthesised. But it was printed where a reader expects a statement about the *document*, and it was
printed in the same shape, with the same exit code, as a run that had checked all 371 and found them
wanting. The report looked like a verdict on the writing. It was a statement about which PDFs
happened to be in a folder.

This is the failure mode the whole repository exists to prevent, one level up from the ones already
guarded: not a *false* claim, but a **true claim presented as the wrong kind of claim**.

## The rule

1. **Separate the two conditions by name and by status.** A finding about the artefact is `pass` or
   `fail`. A gap in the inputs is `insufficient_input` or `insufficient_evidence`. They are never
   merged into one number, one colour, or one verdict.
2. **Block by default.** An input condition exits non-zero (`3` for missing evidence, `4` for a
   document that could not be read). The documented opt-out (`--allow-insufficient`) keeps the
   condition in the recorded status, so overriding it is logged rather than silent.
3. **Never render a gap as a metric.** No percentage, coverage figure, score, or colour that a reader
   could mistake for a result. If a ratio must be printed, the reason it is what it is is printed
   beside it, in the same block.
4. **Always emit a worklist.** An input gap produces a machine-readable list of what is missing, why,
   and what to do — and a mode that re-checks it, so the gap can be closed and shown to be closed.
5. **A negative finding needs verified, machine-comparable evidence.** An accusation (a red) requires
   the source's identity to be confirmed rather than guessed, and the evidence to be the source's own
   text or a value copied from it verbatim. A prose summary written by a human, or a link inferred
   from a title match, may support a *positive* claim but may never convict.
6. **Every reported fact carries provenance.** Evidence text may not exist in a verdict without a
   record of where it came from: which method, which endpoint, which identity check, when. A verdict
   whose evidence cannot be traced is a gate error, not a warning.
7. **Distinguish "does not" from "cannot".** A source we could not read is not a source that does not
   support the claim. Both are recorded, and the difference is never smoothed over with the same
   sentence.

## Corollaries worth stating

- **Absence of evidence is a warning, never an accusation.** Text extraction loses tables and figures
  routinely, so a value that is merely missing from extracted text is `unverifiable`, not a conflict.
- **A model's opinion is advisory only.** It may never set, change or veto a status that decides an
  exit code. This is already enforced in `medical-narrative-review` (`advisory_laya.md`), and
  `citation-report` follows the same contract.
- **A sample is not a population.** The five code paths that must be exercised are the ones that
  never ran: the reference-list path that only fires for DOCX, the superscript style that only fires
  for Nature-style citations, the contradiction path that only fires when both evidence and link are
  good enough. A test suite that never reaches a branch has not tested it.
- **Measure the rule, then keep measuring.** A rule added without a labelled case is a guess with a
  name. `benchmarks/` exists so a rule change is visible as a number.

## Applying this to the other gates

Scope for this change was `citation-report`, plus this document. The question to ask each remaining
gate is the same one, and the answer is not assumed:

| Skill | The question to ask |
|---|---|
| `medical-narrative-review` | `validate_sources.py` already requires extraction fields for an included, verified source (`MISSING_EXTRACTION_FIELD`). Does any path let an *unread* source support a claim, and does a run with unreadable sources report a pass? |
| `sysreview` | The PRISMA flow reconciles with the search and screening logs. If a database was `unavailable`, does the flow render a number that reads as evidence of absence? |
| `evidence-synthesis-forge` | The citation gate resolves DOIs and matches titles. If resolution fails because the network failed rather than because the DOI is wrong, are those two recorded as the same thing? |
| `originality-check` | An unreadable corpus file is reported, not skipped. Is the overlap result reported as a measurement when the corpus was partly unreadable? |
| `citecheck` | An unresolved identifier is marked `[UNRESOLVED]`. Is a reference list containing one still emitted as if complete? |

Each of those is a question, not a finding. Answering one means reading the code path and running it
against a fixture where the input is missing — the same method that produced every defect recorded in
`docs/AUDIT-FINDINGS.md`.

## What this rule does not claim

It does not make a report *accurate*; it makes a report **honest about its own basis**. A run that
says `insufficient_evidence` and lists the eleven PDFs it needs is not a better analysis of the
document than one that silently graded nothing — it is a truthful one. The analysis still depends on
the evidence, and obtaining paywalled evidence legitimately is the author's job, not the tool's.

Acquisition pushes the bound back where it legitimately can be pushed, and it is worth having: on one
real 60-DOI clinical reference list it took usable evidence from 0 to **20 sources (33.3%)**, all from
a single keyless endpoint. It is nowhere near enough to complete a bibliography, which is precisely why
the rule is *block and hand over a worklist* rather than *report a low percentage*.
