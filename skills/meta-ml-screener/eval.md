# eval.md — grade an ML-assisted screening plan

Grade the workflow against the eight rubric items below. Each item names the artifact it
reads, the check that decides it, and the failure it catches.

The skill has one gate script, `scripts/validate_screening_log.py`. Its own suite pins the
full exit vocabulary:

```bash
python3 scripts/validate_screening_log.py --self-test
```

---

## Hard errors

A plan with a FAIL on X3, X4, or X8 must not ship until the defect is fixed.

### X1. ML role and human decision points

The plan must state the ML task and the decision that stays human. The table in `Intake`
gives the usual pairing for each task.

**Fails when:** the plan says "the model screens the records" and names no human decision
point.

### X2. Validation set and recall

The plan must name the seed set or the validation set, the recall target, and the way the
recall was measured. Recall is measured on the validation set only. The true recall on the
records the model never scored is unknown, and the plan must say so.

**Fails when:** the plan reports a recall with no validation set, or reports a recall as a
property of the whole record set.

### X3. Decision reasons

Every exclusion carries a reason code. Every record carries a decision value from the
allowed set. This is a hard error.

**Gate:** `scripts/validate_screening_log.py`. A missing required column, an unknown
decision value, a duplicate record identifier, or an exclusion with no reason is a finding
about the log: exit 1.

### X4. Human verification and adjudication

The log must record the human decision and the reviewer for every record that needed one.
A disagreement must end in a recorded adjudication.

**Gate:** the required `human_decision` and `reviewer` columns. A log without them exits 1.
This is a hard error.

### X5. Prompts, models, versions, and schemas

Record the prompt or the schema, the model name, and the model version. A version that
affects a review decision must not be private to the operator.

**Fails when:** the log records a score with no model version, so the run cannot be
repeated.

### X6. Uncertain records escalate

A score near the cut point and an explicit uncertainty flag must escalate to a human
reviewer. The escalation rule must be stated before the screen.

**Fails when:** the model decides the borderline records alone.

### X7. Moderators stay exploratory

An ML-discovered moderator is a hypothesis. It must not enter the report as a confirmatory
finding. Promote it to a pre-specified test, or label it as exploratory.

### X8. The final inclusion decision stays human

Automation must not own the inclusion decision, and it must not erase the exclusion reason
or the reviewer's accountability. This is a hard error.

---

## Gate inventory

| Gate script | Decides | Exit codes | Pass fixture | Fail fixture |
|---|---|---|---|---|
| `scripts/validate_screening_log.py` | the log is complete, consistent, and auditable | 0 pass; 1 a finding about the log; 2 the input cannot be read; 3 `insufficient_input` | a valid log gives 0 with "Validation passed" on stdout | a bad row gives 1; a missing file gives 2; a header with no data rows gives 3 with an empty stdout and a JSON worklist on stderr |

The input-gap path is the one to check by hand. A log with a header and no rows exits 3,
writes `insufficient_input` and a worklist to stderr, and leaves stdout empty. No finding
wording may appear on either stream. The script's `--self-test` asserts each of those
conditions, so a regression fails the self-test rather than the reader's trust.

---

## Reporting

| Rubric item | Result | Note |
|---|---|---|
| X1 ML role and human decision points | PASS/FAIL | |
| X2 validation set and recall | PASS/FAIL | |
| X3 decision reasons | PASS/FAIL | |
| X4 human verification and adjudication | PASS/FAIL | |
| X5 prompts, models, versions, schemas | PASS/FAIL | |
| X6 uncertain records escalate | PASS/FAIL | |
| X7 moderators stay exploratory | PASS/FAIL/NA | |
| X8 human final decision | PASS/FAIL | |

These checks bound the log. They are not a clearance: the log records the decisions it
contains, and it does not show that the search found every eligible record.
