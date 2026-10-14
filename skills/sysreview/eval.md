# eval.md — routing-contract rubric for /sysreview

Run this after a `/sysreview` dispatch or plan, before any stage output is trusted. This rubric
grades the **routing contract**. It does not grade review methodology; the forge skills own
that.

A **FAIL** in SR1-SR4 is blocking: the wrong skill received the request, so every later result
is suspect. SR5-SR10 are fix-or-flag.

The matching self-test is `scripts/selftest.sh`. It reads the `ROUTE` and `GATE` blocks in
`SKILL.md`, so a contract change that drops a target or a fixture fails the run.

---

## Routing items (blocking)

### SR1. Alias meaning
`/sysreview` names the full gated review pipeline. The request is review-shaped: a systematic
review, an SLR, a PRISMA 2020 review, a scoping review, an evidence map, a rapid review, or an
umbrella review.
FAIL if the alias is applied to a request that asks only for one stage, one statistic, or one
document edit.

### SR2. Request routing
Every request class reaches the owner named in the `ROUTE` block.
FAIL if the pooling leg goes to `meta-analysis-forge` from this skill (the `meta-analysis` skill
owns it); if protocol design goes to this skill; or if screening goes to `evidence-synthesis-forge`.

### SR3. Target unavailable
When a target skill is absent, the run stops on that stage. It names the missing dependency and
records an input gap (exit `4`). It does not run the stage by hand.
FAIL if the run screens, extracts, or pools manually after a target is reported missing.

### SR4. No duplicated analysis logic
The skill sequences; it does not reimplement.
FAIL if the plan writes eligibility criteria, a screening prompt, a statistical model, or an
effect-size conversion inside this skill.

---

## Conduct items (fix-or-flag)

### SR5. Machine gates not waived
Autonomous mode resolves gates; it never waives one. Citation resolution, PRISMA reconciliation,
numeric provenance, search reproducibility, coding-sheet validation, and the κ computation all
still run.
FAIL if a mode setting turns a machine gate off.

### SR6. Disclosure emitted
Every autonomous output carries the `CONDUCT_DISCLOSURE` block. It states the mode, the agent
identity, the human involvement, the compliance limit, the audit path, and the hours estimate.
FAIL if the block is missing, or if an autonomous review is labelled Cochrane-compliant,
MECIR-compliant, PRISMA-compliant, or human-screened.

### SR7. Ledger and counts
Every reported count traces to `search_log.csv`, `sources.csv`, `screening_log.csv`, `claims.csv`,
or `prisma_counts.json`.
FAIL if a count appears with no ledger row behind it, or if an unreached source is reported as
`0 results` instead of `unavailable`.

### SR8. Exit-code honesty
The run reports the exit code each gate produces and does not merge an input gap into a finding.
A pass is `0`; a finding is `2`; an input gap is `3`; a document the tool cannot read is `4`.
FAIL if a gap is reported in the same channel, shape, or status as a finding.

### SR9. Preflight before Stage 1
`doctor.sh` and a trivial MCP probe run before the first stage. A missing dependency is an input
gap, not a result.
FAIL if Stage 1 starts on a toolchain that did not answer.

### SR10. Mode selection
The mode is asked at Stage 0. When no answer comes, the run proceeds autonomously and logs the
default.
FAIL if a stage waits on a mode answer that never comes, or if the mode is never recorded.

---

## Attribution item (blocking)

### SR11. Attribution claim
The manuscript gate calls `tools/attribution.py` with the facts the upstream gates supply. It
never reads the gates itself and never guesses a fact. The defined term is issued only when
every assessed passage quotes and cites, paraphrases in new words and cites, or needs no
citation; every citation resolves; no cited source carries a retraction; and the supplied
corpus was read. The scope line names the sources checked, the supplied documents read, the
documents that could not be read, and the structure exception. A gate that did not run, or a
ledger that is absent, withholds the term and names the blocker.
FAIL if the term appears without the definition, the scope and the exception, or if a missing
gate or ledger is read as a condition met.

---

## Reporting

| Check | Result | Note |
|---|---|---|
| SR1 alias meaning | PASS/FAIL | |
| SR2 request routing | PASS/FAIL | |
| SR3 target unavailable | PASS/FAIL | |
| SR4 no duplicated analysis logic | PASS/FAIL | |
| SR5 machine gates not waived | PASS/FAIL | |
| SR6 disclosure emitted | PASS/FAIL | |
| SR7 ledger and counts | PASS/FAIL | |
| SR8 exit-code honesty | PASS/FAIL | |
| SR9 preflight before Stage 1 | PASS/FAIL | |
| SR10 mode selection | PASS/FAIL | |
| SR11 attribution claim | PASS/FAIL | |

Any FAIL in SR1-SR4 or SR11 means the request must go to another skill, or the claim must be
withheld, before work continues.
