# MECIR standards — the mandatory gates

Paraphrase of Cochrane's **Methodological Expectations of Cochrane Intervention Reviews
(MECIR)**, which sets **M** (mandatory) and **H** (highly desirable) expectations for each
stage of a review. MECIR is the authoritative checklist; this file is a paraphrased gate map,
not a reproduction (© Cochrane Collaboration). The authoritative coded list (C1…Cn) lives in
MECIR — consult it before a submission.

## Mode note — MECIR's M items are HUMAN requirements

MECIR's mandatory items presuppose human reviewers: *"(M) Two people independently screen"*,
*"(M) Data are extracted by two people"*, *"(M) … assessed independently by two people"*. An
**autonomously conducted review cannot satisfy them**, however capable the agent is — "two
people" is not "one agent twice".

So: if `/sysreview` runs in autonomous mode (the default), the output must carry the
`CONDUCT_DISCLOSURE` and must **not** be described as MECIR-compliant. This file describes
MECIR *as written*; it is not a description of what autonomous mode does. To hold the MECIR
line, run in human-in-the-loop mode.

## How to use

Every MECIR **M** expectation for the current stage is a **hard gate**: the review must not
advance until it is satisfied and logged. **H** expectations are recorded as advisory. Below,
each stage lists the M-level expectations in paraphrase.

## Setting the scope & question (protocol)

- **(M)** A protocol is written and published **before** the review is conducted.
- **(M)** The question states the population, intervention(s), comparator(s) and outcomes.
- **(M)** Inclusion/exclusion criteria are pre-specified, and it is stated how studies will be
  grouped for synthesis.
- **(M)** The search sources and strategy are pre-specified.
- **(M)** The process for deciding inclusion, and who will decide, are pre-specified.
- **(M)** The primary outcome(s) and any adverse outcomes to be assessed are pre-specified.
- **(M)** The risk-of-bias assessment tool(s) are pre-specified.
- **(M)** The synthesis approach (whether meta-analysis, and the planned comparison(s)) is
  pre-specified, including how heterogeneity will be assessed.
- **(M)** A plan for assessing reporting bias is pre-specified.
- **(M)** Changes to the protocol are recorded and reported.

## Searching

- **(M)** Multiple bibliographic databases are searched; the Cochrane Central Register of
  Controlled Trials is searched for reviews of interventions.
- **(M)** The search strategy is designed by or in consultation with a specialist (or peer
  reviewed), and is **reproducible** and reported in full.
- **(M)** Unpublished/grey literature and ongoing trials are sought.
- **(M)** The search date is recorded and reported.

## Selecting studies & collecting data

- **(M)** Two people independently screen titles/abstracts and full texts; disagreements are
  resolved by a documented process.
- **(M)** The number of records excluded at each stage, with reasons for full-text exclusions,
  is documented so the PRISMA flow diagram is generated from data.
- **(M)** Data are extracted by two people (or one person plus verification).
- **(M)** The extraction form is pre-specified.

## Risk of bias

- **(M)** Risk of bias is assessed with **RoB 2** for randomised trials; the assessment is
  done independently by two people.
- **(M)** For non-randomised studies, a design-appropriate tool (ROBINS-I/E) is used.

## Synthesis & interpretation

- **(M)** The analysis is planned and reported; the effect measure is justified.
- **(M)** Heterogeneity is assessed and interpreted (not just reported as I²).
- **(M)** Risk of bias findings are considered in the synthesis and interpretation.
- **(M)** The certainty of the evidence is assessed (GRADE) and reported.
- **(M)** Reporting bias is assessed and reported.
- **(M)** Limitations of the review are discussed; conclusions are graded to the evidence.

## Reporting

- **(M)** The review is reported consistent with **PRISMA**.
- **(M)** A **Summary of findings** table per comparison is included.
- **(M)** The review is updated, or a plan for updating is stated.

## Gate mapping in this skill (`/sysreview`)

| Stage | MECIR gate |
|---|---|
| 1 Protocol | Protocol written + pre-specified PICO/eligibility/synthesis plan |
| 2 Registration | PROSPERO (or applicable registry) + amendment rule set |
| 3 Search | Reproducible strategy + sources pre-specified + documented date |
| 4 Selection | Duplicate-independent screening + exclusions with reasons |
| 5 Extraction | Pre-specified form + dual extraction or verification |
| 6 Risk of bias | RoB 2 / ROBINS-E independent assessment |
| 7 Synthesis | Pre-specified effect measure + heterogeneity interpretation |
| 8 Certainty | GRADE + Summary of findings |
| 9 Reporting | PRISMA-complete + reporting-bias assessment + limitations |

MECIR is deliberately stricter than PRISMA: PRISMA governs **what to report**, MECIR governs
**what must have been done**. A review can be PRISMA-complete and still fail MECIR.
