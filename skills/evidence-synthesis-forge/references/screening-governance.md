# Screening governance — calibrate, lock, then screen

Adapted from AngelChen-HC/systematic-review-skill v8.1 (Apache-2.0), Phase 5a and the
audit-log specification. Implements the Cochrane requirement to pilot-test eligibility
criteria and screening forms, for AI-assisted screening.

## Why this phase exists

Screening thousands of records under un-validated criteria spends audit effort and
risks **systematic** error that per-record review will not surface as a pattern until far
too late. Validate the screening — criteria, prompt, rules — on small pilots with a complete
blind audit and an agreement gate **before** the full screen. In operational use this loop
has moved agreement from κ ≈ 0.30 (raw PICO) to κ ≥ 0.70 (after rule extraction) in two to
three cycles. Do not skip it.

**Mode note.** The audit below is performed by a human in *human-in-the-loop* mode, and by the
agent (blind second pass, logged as `auditor: agent`) in the default *autonomous* mode. The
κ/agreement machinery, the criteria lock and the audit log are identical either way — only the
*identity of the auditor* changes, and it is recorded.

## The loop

```
Pilot (50 records, stratified) -> blind audit (human or agent) -> compute
κ + % agreement + PABAK -> κ >= 0.60 on this fresh pilot?
   NO  -> extract disagreement-derived rules -> researcher approves ->
          update prompt + eligibility-rules registry (new prompt hash)
          -> run a NEW pilot on FRESH records -> repeat
   YES -> convergence check passed?
            NO  -> one more pilot (harder, include-enriched, no new rules)
            YES -> LOCK criteria -> GATE 2a -> full screen
```

## Pilot sampling (stratified, never purely random)

Default **50 fresh records** (never reused across pilots). A purely random sample is ~90%
easy excludes and tells you almost nothing about the dangerous cells.

1. Screen a **seeded candidate slice** (3–5× pilot size, deterministic/stable-ID order).
2. Draw the 50 **stratified by AI decision × confidence**: include **all** INCLUDE and
   UNCERTAIN (up to ~half the pilot), then low-confidence EXCLUDEs, topped up with a random
   draw of high-confidence EXCLUDEs.
3. A keyword/LLM classifier may enrich the slice — **labelled high-recall triage only,
   never the authoritative screen** (the `meta-ml-screener` rule).
4. Log sampling scheme, seed, slice, composition.
5. **Pre-lock outputs do not count.** Records screened under un-locked criteria are marked
   superseded and returned to the pool for re-screening under the locked prompt.

## Blind audit of the pilot

The auditor screens **all 50 without seeing the first pass's recommendations** (ground-truth
presentation), recording INCLUDE / EXCLUDE / UNCERTAIN-defer + a brief reason. Only after all 50
are recorded are the first-pass outputs revealed.

- **Human-in-the-loop mode:** the researcher performs this; their pilot decisions are final human
  decisions and carry into the review's results (these records are not re-screened).
- **Autonomous mode (default):** the agent performs the blind second pass itself, logging each
  decision with its rule reference (`ER-nnn`) and confidence. This is a **methodological check on
  the first pass — it is not human verification**, and the audit log records `auditor: agent`.
  The CONDUCT_DISCLOSURE must state that no human screened the records.

## Agreement metrics — report ALL, never κ alone

Cohen's κ (3-category and binary), raw % agreement, and **PABAK**, in both forms, for every
pilot. Add the κ-paradox base-rate caveat and the direction-of-disagreement rule.

## Gate, convergence, lock

κ ≥ 0.60 on the fresh pilot. **Convergence** = at least one *harder* pilot passing the gate
**with no new rules** (passing only on pilots that each generated new rules means criteria
are still moving). On convergence, **LOCK** the PICO criteria, the eligibility-rules
registry, and the calibration examples under a final `prompt_version_hash`. Any later change
is a logged protocol deviation requiring approval, and raises whether already-screened
batches must be re-screened.

## The eligibility-rules registry

Raw PICO cannot express the rules that decide borderline records. Keep
`eligibility_rules_registry.json` as the versioned, machine-readable home for them; the
calibration loop writes to it, the screening prompt reads from it.

```json
{
  "rule_id": "ER-001",
  "category": "publication_type | condition_boundary | informant_vs_subject | traits_vs_diagnosis | population_subgroup | proxy_outcome | other",
  "statement": "one-sentence operational rule a screener can apply directly",
  "disposition": "INCLUDE | EXCLUDE | UNCERTAIN",
  "origin": "pilot/batch + record_id(s) of the producing disagreement(s)",
  "approved_by": "researcher id",
  "approved_at": "ISO-8601",
  "status": "ACTIVE | RETIRED | SUPERSEDED",
  "prompt_versions": ["hashes containing this rule"]
}
```

Minimum rule kinds: condition boundaries; informant vs subject (a carer reporting *on* the
participant counts; the carer's *own* outcome does not); traits vs diagnosis; proxy/partial
outcomes; context-specific outcome variants (UNCERTAIN); publication-type nuance
(conference abstracts reporting a real study, letters, case reports are **not auto-excluded**
— assess; reviews, meta-analyses, editorials are excluded, with citation-chasing noted).

## Gates

- **GATE 2a — Calibration complete, criteria locked.**
- **GATE 2 — full audit of title/abstract screening.** Human in human-in-the-loop mode; in
  autonomous mode, an agent-run blind audit of the same records, logged with `auditor: agent`.
- **GATE 2b — independent dual screening, conflict resolution complete.** "Independent" second
  pass may be agent-run in autonomous mode; conflicts are resolved and logged, and the mode is
  disclosed.

## Audit log (tamper-evident)

Hash-chained. Per record: hashed input metadata; the AI rationale with evidence quotes;
recommendation; confidence level; the decision (human, or agent in autonomous mode); timestamps;
the `prompt_version_hash` in force; and the **model id + version per batch** (long screens span
sessions; the model can change — log per batch, do not assume constant).

## AI transparency block (include in the log and any publication)

model id/version, **per-batch** model ids, provider, prompt version, temperature (0, or
"platform-controlled" where it cannot be verified — never assert an unverifiable value),
seed. State the AI's role: in **human-in-the-loop** mode it is recommendation-only with all
decisions human-confirmed; in **autonomous** mode the agent makes the decisions and the
CONDUCT_DISCLOSURE must say so. Either way, state the
known limitations (plausible-but-wrong reasoning; training-data skew; reasoning not
seed-deterministic).

## Reproducibility honesty

**Can promise:** prompt/criteria versioning + hashes; complete decision logging; deterministic
sampling of pilots/batches; per-batch model identity. Computed statistics are deterministic
given a locked dataset hash, plan hash, script hash, and recorded library versions — stronger
than anything possible for LLM screening.

**Must not claim:** that `temperature=0` + seed yields token- or decision-identical AI
reasoning, or that a re-run would produce "identical results." The defensible claim:
*every decision is fully documented, criterion-referenced, evidence-quoted, audited (by a human,
or by the agent in autonomous mode), and traceable to a hashed prompt version and a logged model
version.* In autonomous mode, add: *and conducted without independent human screening.*

## Audit depth

100% by default. An opt-in risk-based alternative (documented): 100% of UNCERTAIN/INCLUDE/
low-confidence excludes plus a seeded sample of high-confidence excludes with escalation —
report the Cochrane trade-off as a limitation.

## Reviewer-hours estimate (do this before committing)

records × minutes-per-record × number of screeners; reach the team before screening starts.
It is the input to whether a second screener, a narrower eligibility gate, or a different
timeline is needed.

