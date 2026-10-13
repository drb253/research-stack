# eval.md — routing-contract rubric for /meta-analysis

Run this after a `/meta-analysis` dispatch or plan, before any pooled number is trusted. This
rubric grades the **routing contract** and the poolability boundary. It does not grade the
statistical engine; `meta-analysis-forge` owns that.

A **FAIL** in MR1-MR3 is blocking: the wrong skill received the request. MR4-MR9 are
fix-or-flag.

The matching self-test is `scripts/selftest.sh`. It reads the `ROUTE` and `GATE` blocks in
`SKILL.md`, so a contract change that drops a target or a fixture fails the run.

---

## Routing items (blocking)

### MR1. Alias meaning
`/meta-analysis` names the quantitative-synthesis entry point, not the whole review. It owns the
poolability decision and the effect-size plan.
FAIL if the alias is applied to a request that asks only for a search, a screening, or a
narrative review.

### MR2. Request routing
Every request class reaches the owner named in the `ROUTE` block. Statistical work goes to
`meta-analysis-forge`. The systematic layer and the risk-of-bias or certainty stage go to
`sysreview`. A review of reviews goes to `umbrella-review-skeptic`.
FAIL if statistical work is answered here without the forge, or if a search-and-screen request is
answered here instead of routing to `sysreview`.

### MR3. Target unavailable
When a target skill is absent, the run stops. It names the missing dependency and records an
input gap (exit `4`). It does not hand-compute a pooled number.
FAIL if a pooled estimate appears after the engine is reported missing.

---

## Boundary items (fix-or-flag)

### MR4. Poolability first
The five poolability questions run before the first pooled number. A blocked answer produces a
narrative synthesis (SWiM) plan, not a pooled estimate.
FAIL if pooling starts before the gate is answered.

### MR5. No I²-significance rule
The model is chosen by conceptual homogeneity. A heterogeneity test's significance never selects
fixed- or random-effects.
FAIL if the write-up gives an I² threshold as the model rule.

### MR6. Heterogeneity reported
τ² and a prediction interval are reported beside the pooled estimate. I² alone is not enough.
FAIL if the pooled estimate appears without τ² and a prediction interval.

### MR7. No fabricated number
Every effect size, variance, and pooled value traces to a computed artifact.
FAIL if a number appears with no artifact behind it, or if a value is rounded away or
approximated in the write-up.

### MR8. Exit-code honesty
The run reports the exit code each gate produces. A pass is `0`; a refusal to pool mixed metrics
is `1`; a finding is `2`; a blank or unusable effect size is `3`; an unreadable sheet is `4`.
FAIL if `--allow-mixed-metrics` is set without a recorded reason, or if a gap is reported as a
result.

### MR9. No duplicated analysis logic
The skill decides poolability and routes the statistics. It does not carry its own model code.
FAIL if the skill computes a pooled estimate itself.

---

## Reporting

| Check | Result | Note |
|---|---|---|
| MR1 alias meaning | PASS/FAIL | |
| MR2 request routing | PASS/FAIL | |
| MR3 target unavailable | PASS/FAIL | |
| MR4 poolability first | PASS/FAIL | |
| MR5 no I²-significance rule | PASS/FAIL | |
| MR6 heterogeneity reported | PASS/FAIL | |
| MR7 no fabricated number | PASS/FAIL | |
| MR8 exit-code honesty | PASS/FAIL | |
| MR9 no duplicated analysis logic | PASS/FAIL | |

Any FAIL in MR1-MR3 means the request must go to another skill before work continues.
