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

Scope for the first change was `citation-report`, plus this document. The five remaining gates were
then asked the same question by reading each code path and running it against a fixture where the
input was missing. **All five answered yes: every one of them broke the rule**, and all five are now
fixed with a pass-and-fail test each. The reproduction below is the pre-fix behaviour, measured on
the committed code, and every fix is a separate commit.

| Skill | The question | Answer, with the reproduction |
|---|---|---|
| `medical-narrative-review` | Does any path let an *unread* source support a claim, and does a run with unreadable sources report a pass? | **Yes.** A row with `retrieval_status=empty`, `verification_status=verified`, `inclusion_status=included` and the ten extraction fields written as the sanctioned `not_reported` passed `validate_sources --strict` (exit 0), `audit_citations --strict` (exit 0) and `gate.py` (exit 0, `submission_ready: true`). `retrieval_status` was enum-checked and read by no decision path. Fixed: an unread citable source, and a verified claim joined to one, are `insufficient_evidence` (exit 3) with a worklist; the gate refuses `submission_ready`. |
| `sysreview` | If a database was `unavailable`, does the flow render a number that reads as evidence of absence? | **Yes.** With `source_status=unavailable, hits=0`, the PRISMA-S appendix printed `embase … 0` and "reproducibility checks: OK", and the completeness gate printed "OK - retrieval and assessment complete" — both exit 0. No script read `source_status` at all. Fixed: the appendix renders `unavailable (not reached)` and never the digit, and both it and the completeness gate exit 3, stating that the identified total is a floor rather than a total. |
| `evidence-synthesis-forge` | If resolution fails because the network failed rather than because the DOI is wrong, are those two recorded as the same thing? | **Yes.** A non-existent DOI and a refused connection produced byte-identical stdout, `gate: FAIL`, exit 2, and the same DOI in `unresolved[]`/`failures[]`; with `--allow-unresolved` a total outage reported `gate: PASS`, exit 0. Fixed: an unreachable resolver is its own status, its own key (`input_gaps[]`), its own gate word (`INCOMPLETE`) and exit 3, which `--allow-unresolved` cannot waive. `--recheck` re-checks the worklist. |
| `originality-check` | Is the overlap result reported as a measurement when the corpus was partly unreadable? | **Yes.** With three of four corpus files unreadable the report still showed "highest score: 0.813" and a full score table, exit 0; a wholly unreadable corpus or a nonexistent path gave "highest score: 0.000" and the clean verdict shape. The unreadable files appeared on stderr only. Fixed: they are listed in the report and in `--json`, a corpus that loaded nothing prints no score line and no verdict, and the run exits 3. `--recheck` re-reads just those files. |
| `citecheck` | Is a reference list containing an unresolved identifier still emitted as if complete? | **Yes — worse: the entry was dropped.** A draft with one resolvable and one unresolvable identifier wrote a list with no trace of the second and exited 0; an all-unresolvable draft wrote a one-byte file (a newline) and exited 0. That contradicts the skill's own `eval.md` C2 hard error. Fixed: every identifier that produced no entry gets an `[UNRESOLVED]` or `[NOT CHECKED]` line in the artifact itself, and the run exits 2 (a finding) or 3 (an input gap), each with its own opt-out. |

### The same question, asked of two consumers

Answering it for the gates exposed the identical confusion in two places that consume them, because a
gate's output is someone else's input:

- **`benchmarks/bench_accuracy.py`** read the citation gate's old generic `error` status as
  *resolved*. A lookup failure on a retracted paper therefore counted as a **missed retraction** —
  silently moving the one number the 920-citation benchmark exists to certify. Input-side statuses now
  count as unresolved, and a shard exiting 3 is rejected instead of contributing rows.
- **`acceptance_test.py`** accepted any non-zero exit from the adversarial retracted/unregistered DOI
  cases, so a network outage satisfied the test that exists to catch false greens. It now pins the
  finding code.

### What is still not covered

Recorded so the audit is not read as complete:

- **`citation-report` needs a wider conflict ground truth.** Four conflict positives give a Wilson
  lower bound of 0.51 on conflict precision. The interval, not the point estimate, is the claim.
- **A malformed input file is reported in the finding channel.** `emit_report` has no
  `insufficient_input` status for "the CSV could not be parsed at all" (it is an `INVALID_INPUT`
  error, exit 1). It exits non-zero and is labelled as an input problem, so it never reads as a
  finding about the review — but the vocabulary is not yet uniform across skills.
- **Partial retraction-signal failure is a warning, not a gap.** When one of the three retraction
  signals cannot be reached, the others still run and the failure is recorded per record
  (`retraction_check_failed`). That is deliberate — Crossref alone is a real check — but a run where
  *every* retraction signal failed would still be reported as a findings-based result rather than an
  input condition.
- **The five audits were verified by their own fixtures**, not by an independent reviewer. Each fix
  ships a test asserting both the pass and the fail path, which is the strongest evidence this
  repository can produce about itself; it is not third-party validation.

## What this rule does not claim

It does not make a report *accurate*; it makes a report **honest about its own basis**. A run that
says `insufficient_evidence` and lists the eleven PDFs it needs is not a better analysis of the
document than one that silently graded nothing — it is a truthful one. The analysis still depends on
the evidence, and obtaining paywalled evidence legitimately is the author's job, not the tool's.

Acquisition pushes the bound back where it legitimately can be pushed, and it is worth having: on one
real 60-DOI clinical reference list it took usable evidence from 0 to **20 sources (33.3%)**, all from
a single keyless endpoint. It is nowhere near enough to complete a bibliography, which is precisely why
the rule is *block and hand over a worklist* rather than *report a low percentage*.
