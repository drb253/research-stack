---
name: sysreview
description: "Orchestrates a systematic review from question to citation-verified manuscript: it sequences the stages, runs the ledger and the gates, and keeps every count traceable. Use when the user asks to run, plan, or conduct a systematic review, a systematic literature review, a scoping review, an evidence map, a rapid review, an umbrella review, or a PRISMA 2020 review. It routes design to evidence-synthesis-forge, screening to meta-ml-screener, and pooling to meta-analysis; it does not design eligibility criteria or compute a pooled estimate itself, and it invents no study, count, or citation."
allowed-tools: Read Write Edit Bash
license: MIT
metadata:
  version: "1.1"
  orchestrates: "evidence-synthesis-forge, meta-ml-screener, umbrella-review-skeptic, meta-analysis, citecheck, humanizerdrb, paper-search"
---

# /sysreview — Systematic Review Orchestrator

This skill is the single entry point for a systematic-review-shaped task. It does not
reimplement review methodology. It **sequences** the installed EvidenceForge skills, the MCP
fleet, and the gate scripts.

## Terms

Short forms used below. Preferred Reporting Items for Systematic Reviews and Meta-Analyses (PRISMA). A systematic literature review (SLR). Population-intervention-comparator-outcome (PICO). Population-exposure-comparator-outcome (PECO). Methodological Expectations of Cochrane Intervention Reviews (MECIR).

More short forms. Grading of Recommendations Assessment Development and Evaluation (GRADE). A MeaSurement Tool to Assess systematic Reviews (AMSTAR). Risk Of Bias In Non-randomised Studies of Interventions (ROBINS). Indian Council of Medical Research (ICMR).

## When this fires

The request matches one of these shapes. The alias `/sysreview` also fires it.

- "systematic review", "SLR", or "PRISMA 2020".
- "scoping review", "evidence map", or "rapid review".
- "screen these papers" or "build a search strategy".
- "run a review on ...".
- An explicit `/sysreview`.

## Execution modes — human sign-off is OPTIONAL

Two modes exist. **Autonomous is the default.** Ask which mode the user wants at Stage 0, and
do not block on the answer. If the user gives no answer, proceed autonomously and log that
fact.

| Mode | Gate approval | Use for |
|---|---|---|
| **Autonomous** (default) | The agent resolves and logs each gate. | Throughput. |
| **Human-in-the-loop** (opt-in) | A named human approves each gate. | A human-conducted review. |

In autonomous mode the agent records the decision, the rule or evidence, the confidence, and
the model id and version for every gate. No human step blocks progress. In human-in-the-loop
mode a named human approves each gate before the next stage starts.

### Mandatory disclosure (autonomous mode) — this is NOT optional

The removal of the human step changes what the document is. MECIR's mandatory items require
independent human screening, extraction, and appraisal. PRISMA 2020 item 8 asks how many
reviewers screened each record and whether they worked independently. An autonomously
conducted review therefore cannot claim a Cochrane or MECIR-compliant label, or a
human-conducted label. Every autonomous output must carry this block:

```
CONDUCT_DISCLOSURE:
  mode: autonomous
  gates_resolved_by: agent  {model id + version, per stage}
  human_involvement: none | partial (state what)
  compliance: NOT MECIR-compliant (human screening/extraction/appraisal requirements unmet);
              NOT reportable under PRISMA 2020 item 8 as independent human screening
  audit_trail: <path to the decision log>
  reviewer_hours_saved_estimate: <n>
```

Autonomous mode must not describe the output as "Cochrane-compliant", "MECIR-compliant", or
"PRISMA-compliant" without the qualifier. It must not state or imply that independent human
reviewers screened the records. That claim would be false. Write *"AI-assisted, autonomously
conducted; not human-screened"* and let the reader decide.

### What does NOT change (machine gates stay mandatory)

Autonomy removes the human approval step, not the error detection. These checks still fail
loudly, and no mode waives them. The checks are citation resolution and retraction, PRISMA
count reconciliation, numeric provenance, search reproducibility, coding-sheet validation, and
the κ agreement computation. In autonomous mode the κ value comes from the agent's own pilot
decisions. An autonomous run that fails a machine gate is still a failed run.

## Non-negotiable rules (empirical integrity)

These rules come from the `empirical-integrity` discipline. Never write a number, date, hit
count, citation, or finding into a deliverable from memory or training knowledge. Check it
against a live authoritative source when one exists.

1. Never invent a record, a count, an effect size, or a citation. A row exists because a lookup or the user returned it.
2. Copy bibliographic fields from the retrieved record, never from recall.
3. Use `not_reported` for a field the source omits. Never leave it blank.

4. Record `verification_status=verified` only with a `verifier`, a `verified_date`, and a `locator`. In autonomous mode the verifier is the agent id plus the model version.
5. Record a source that is down as `unavailable`, never as `0 results`. The gate enforces that rank.
6. Distinguish PRISMA, a reporting guideline, from how the team conducts the review.

7. Admit no claim into the manuscript without a resolvable, non-retracted source. See Gate D.
8. Run `../evidence-synthesis-forge/scripts/check_review_integrity.py --root <project>` for cross-artifact integrity.

Rule 5 in full. A logged source can report that the tool did not reach it. The value is
`unavailable`, `error`, `failed`, `timeout`, or an unrecognised value.
`../evidence-synthesis-forge/scripts/prisma_s_appendix.py` then renders
`unavailable (not reached)` in the Records column instead of a count.

That script and `../evidence-synthesis-forge/scripts/check_completeness.py` then exit **3**
with the sources named. The identified total is a floor, not a total, and the gate says so.
`--allow-insufficient` exits 0 while it still records the condition.

Rule 8 in full. `check_review_integrity.py` runs a fixed list of checks. The list is the
reference list against the included set, and the claims-ledger numeric sync. It also covers
the manuscript numeric sync, the eligibility red-flags, CSV well-formedness, and the PRISMA
reconciliation. A stale "N studies" count anywhere is a failed run.

## The pipeline (10 stages, gated)

| # | Stage | Owner |
|---|---|---|
| 0 | Mode and kickoff | This skill. |
| 1 | Question and protocol | `evidence-synthesis-forge`. |
| 2 | Registration | `../evidence-synthesis-forge/scripts/prospero_search.py`. |
| 3 | Search strategy | `paper-search` MCP (`plan_search_query`). |
| 4 | Retrieval and dedup | `paper-search` MCP and `ncbi` MCP. |

| # | Stage | Owner |
|---|---|---|
| 5 | Screening calibration pilot | `meta-ml-screener` and this skill. |
| 6 | Title, abstract, and full-text screening | `meta-ml-screener`. |
| 7 | Data extraction and coding | `evidence-synthesis-forge` or `meta-analysis-forge`. |
| 8 | Risk of bias and quality | RoB 2, ROBINS-I, NOS, AMSTAR-2, or GRADE. |

| # | Stage | Owner |
|---|---|---|
| 9 | Synthesis | The `meta-analysis` skill. |
| 10 | PRISMA flow, report, and citations | This skill, `citecheck`, and `humanizerdrb`. |

Gate names per stage. Stage 0 sets the mode to NEW, UPDATE, or RETRO-QA. Stage 1 needs an
approved protocol. Stage 2 sets the novelty and amendment rule. Stage 3 is **Gate 1**, the
strategy approval. Stage 5 is **Gate 2a**, the criteria lock.

Stage 6 is **Gate 2**, the screening audit. Stage 7 is **Gate 3**, the dataset lock. Stage 8
is **Gate 4**, the appraisal confirmation. Stage 9 is **Gate 5**, the synthesis plan approval.
Stage 10 is **Gate D**, the citation gate.

## Routing

- Design, eligibility, protocol, and search structure go to `evidence-synthesis-forge`.
- ML-assisted screening, extraction, and triage go to `meta-ml-screener`.
- The statistical pooling leg goes to the **`meta-analysis`** skill. Do not pool here.

- The synthesis of existing reviews goes to `umbrella-review-skeptic`.
- An environmental, ecological, or life-science domain goes to `environment-life-review-forge`.
- Every search, DOI lookup, and registry query goes to the `paper-search` and `ncbi` MCPs.

Use `sources="auto"` for topic-routed search. Never use `sources="all"`, which burns paid
quota. A PubMed-only search is a single-source search, and the completeness gate fails it.
Bibliographic databases cannot see registered-but-unpublished trials, or terminated trials.
Publication bias lives in that blind spot.

Route at least one **registry** source as well (`search_clinicaltrials`, `search_ictrp`, or
`search_ctis`). Record every source with its hit count in `search_log.csv`. For the
ventilatory-pneumonia question, the registry search returned 8 registered trials. One trial
terminated at 740 patients, and several completed trials have no posted results. None of them
appear in any database search.

Citation verification goes to `citecheck` and
`../evidence-synthesis-forge/scripts/cross_verify_citations.py`. The final prose register goes
to `humanizerdrb`, for attribution and not for evasion.

## Routing contract

The alias `/sysreview` means one thing: the full gated review pipeline. It does not mean
"answer a review-like question". This skill dispatches each request class to its owner, and it
reads the block below at self-test time.

```
ROUTE systematic-review,slr,prisma,scoping-review,evidence-map,rapid-review -> self
ROUTE design-protocol,eligibility-criteria,search-strategy,coding-manual -> evidence-synthesis-forge
ROUTE screen,screening,deduplication,triage -> meta-ml-screener
ROUTE pool,pooling,effect-size,forest-plot,funnel-plot,heterogeneity -> meta-analysis
ROUTE umbrella,review-of-reviews,second-order -> umbrella-review-skeptic
ROUTE environment,ecological,life-science -> environment-life-review-forge
ROUTE search-sources,retrieve-records,registry-search -> paper-search
ROUTE citation-verification,resolve-doi,retraction -> citecheck
ROUTE humanize,register,final-prose -> humanizerdrb
FALLBACK no-route -> stop and ask the user; record an input gap (exit 4); never guess a target
```

Two rules keep the routing honest. First, the pooling request goes to the `meta-analysis`
skill, never to `meta-analysis-forge` from here. Second, a request that matches no route stops.
It does not fall through to the first target.

When a target skill is unavailable, stop and report the missing dependency as an input gap
(exit 4). Do not run the stage by hand.

## The artifact ledger (create these; every count comes from them)

```
<review>/search_log.csv          one row per executed query: source, query, date, hits, source_status
<review>/sources.csv             one row per retrieved record: S-ID, DOI, PMID, title, year, retraction_status, verification_status, verifier, verified_date, locator
<review>/screening_log.csv       one row per screened record: record_id, decision, rule, confidence, reason
<review>/claims.csv              one row per atomic claim: C-ID, claim text, supporting S-IDs
                                 (quote the S-ID cell when a claim has more than one: "S001,S004")
<review>/prisma_counts.json      the PRISMA flow counts
<review>/eligibility_rules_registry.json   versioned boundary rules (see screening-governance.md)
<review>/ledgers/extraction.csv  one row per included study
<review>/ledgers/rob_assessment.csv  one row per included study
<review>/ledgers/sources_included.csv   one row per included study
<review>/manuscript.md           the draft; included studies must appear in its reference list
<review>/GATE_REPORT.json        result of the citation gate; must be all-clear
```

`prisma_counts.json` accepts two shapes. The nested shape has identification, screening,
retrieval, eligibility, and included. The flat shape has identified_databases, screened,
excluded_ta, sought, assessed, not_retrieved, excluded_ft, included_studies, and
in_meta_analysis. Every gate reads both.

`../evidence-synthesis-forge/scripts/check_review_integrity.py` requires `sources.csv`,
`claims.csv`, `manuscript.md`, and `prisma_counts.json`. A missing one is a finding, not a
traceback. The citation gate writes `GATE_REPORT.json`. An autonomous run also writes
`CONDUCT_DISCLOSURE.txt`. A waived gap needs an entry in `completeness_waivers.json`. The
human sign-off worklist is `screening_human_confirmation.csv`.

Draft with `[claim:C001] [src:S001,S004]` markers. The reference builder renumbers by first
appearance (ICMJE or Vancouver) and strips the claim markers.

## Load (read before working the stage)

**Standards layer (Cochrane, MECIR, and GRADE, paraphrased and cited):**

- `../evidence-synthesis-forge/references/cochrane-handbook-map.md` — the 26 chapters, and the four amateur-versus-expert failure points.
- `../evidence-synthesis-forge/references/mecir-standards.md` — the mandatory gates per stage.
- MECIR governs what must be done; PRISMA governs what the report must state.
- `../evidence-synthesis-forge/references/search-reporting-prisma-s.md` — the 16 search-reporting items that make a search reproducible.
- `../evidence-synthesis-forge/references/rob-tool-selection.md` — the risk-of-bias tool by design.
- `../evidence-synthesis-forge/references/grade-certainty.md` — certainty and SoF.

- `../evidence-synthesis-forge/references/cochrane-figures-tables.md` — Handbook III.S1 figure rules.
- `../evidence-synthesis-forge/references/icmr-systematic-review-guide.md` — the ICMR *Beginner's Guide for Systematic Reviews*.
- Use the ICMR guide alongside Cochrane, never instead of Cochrane.
- `references/screening-governance.md` — the pilot, κ gate, and criteria-lock protocol.
- `references/cross-model-verification.md` — the optional, consent-gated second-family check.
- `../evidence-synthesis-forge/references/prospero-and-citation-verification.md` — PROSPERO and citation integrity.

- `../evidence-synthesis-forge/references/prisma-2020-manuscript-reporting.md` — the 27-item PRISMA 2020 checklist.
- `../evidence-synthesis-forge/references/reporting-guideline-checklists.md` — 49 reporting instruments.

**Scripts:**

- `../evidence-synthesis-forge/scripts/doctor.sh` — verify the toolchain before the start.
- `../evidence-synthesis-forge/scripts/prospero_search.py` — registration and novelty.
- `../evidence-synthesis-forge/scripts/prisma_flow.py` — the PRISMA 2020 flow from counts.
- It fails when the stages do not add up.
- `../evidence-synthesis-forge/scripts/prisma_s_appendix.py` — the PRISMA-S search appendix.
- It fails when a search lacks a date or a hit count.

- `../evidence-synthesis-forge/scripts/sof_table.py` — the summary of findings. It validates certainty.
- `../evidence-synthesis-forge/scripts/cross_verify_citations.py` — the citation gate.
- `../evidence-synthesis-forge/scripts/numbers_provenance.py` — no number without provenance.
- `../evidence-synthesis-forge/scripts/generate_prisma_flow.py` — the minimal Mermaid flow (legacy).
- `../evidence-synthesis-forge/scripts/check_review_integrity.py` — cross-artifact integrity, with codes R, C, C2, D, M, E, X, T, W, and P.

- `../evidence-synthesis-forge/scripts/check_ledger_completeness.py` — screening-ledger completeness.
- `../evidence-synthesis-forge/scripts/check_appraisal.py` — appraisal honesty. It rejects a placeholder risk-of-bias entry.
- `../evidence-synthesis-forge/scripts/check_completeness.py` — it refuses an incomplete review.

- `../evidence-synthesis-forge/scripts/fetch_pubmed_complete.py` — it paginates the search and batch-fetches every record.
- `../evidence-synthesis-forge/scripts/gate2a_calibration.py` — the Gate 2a pilot κ and PABAK agreement gate.
- `../evidence-synthesis-forge/scripts/regression_suite.py` — one fixture per defect class.
- `../evidence-synthesis-forge/scripts/check_screening_disclosure.py` — the conduct-disclosure gate.
- `../evidence-synthesis-forge/scripts/check_selftest_coverage.py` — the gate-coverage check.

## Quality gates (must pass before anything is reported)

Each gate below fails loudly. None is optional. The registry is machine-readable; the routing
and gate self-test reads it.

```
GATE toolchain | script: ../evidence-synthesis-forge/scripts/doctor.sh | pass-exit: 0 | fail-exit: declared
GATE search-reproducibility | script: ../evidence-synthesis-forge/scripts/prisma_s_appendix.py | pass-exit: 0 | fail-exit: 2
GATE prisma-counts | script: ../evidence-synthesis-forge/scripts/prisma_flow.py | pass-exit: 0 | fail-exit: 2
GATE citation-integrity | script: ../evidence-synthesis-forge/scripts/cross_verify_citations.py | pass-exit: 0 | fail-exit: declared
GATE numeric-provenance | script: ../evidence-synthesis-forge/scripts/numbers_provenance.py | pass-exit: 0 | fail-exit: 2
GATE cross-artifact-integrity | script: ../evidence-synthesis-forge/scripts/check_review_integrity.py | pass-exit: 0 | fail-exit: 2
GATE ledger-completeness | script: ../evidence-synthesis-forge/scripts/check_ledger_completeness.py | pass-exit: 0 | fail-exit: 2
GATE review-completeness | script: ../evidence-synthesis-forge/scripts/check_completeness.py | pass-exit: 0 | fail-exit: 2
GATE screening-disclosure | script: ../evidence-synthesis-forge/scripts/check_screening_disclosure.py | pass-exit: 0 | fail-exit: 2
GATE gate-coverage | script: ../evidence-synthesis-forge/scripts/check_selftest_coverage.py | pass-exit: 0 | fail-exit: 2
GATE appraisal-honesty | script: ../evidence-synthesis-forge/scripts/check_appraisal.py | pass-exit: 0 | fail-exit: 2
GATE screening-calibration | script: ../evidence-synthesis-forge/scripts/gate2a_calibration.py | pass-exit: 0 | fail-exit: 2
GATE certainty | script: ../evidence-synthesis-forge/scripts/sof_table.py | pass-exit: 0 | fail-exit: 2
GATE defect-regressions | script: ../evidence-synthesis-forge/scripts/regression_suite.py | pass-exit: 0 | fail-exit: declared
GATE acceptance-live | script: ../evidence-synthesis-forge/scripts/acceptance_test.py | pass-exit: 0 | fail-exit: declared
```

The gate list.

- Toolchain (`doctor.sh`): a core dependency is missing.
- Search reproducibility (`prisma_s_appendix.py`): a search lacks a date or a hit count.
- PRISMA counts (`prisma_flow.py`): the stages do not add up.
- Citation integrity (`cross_verify_citations.py`): the gate finds an unresolved or retracted cited DOI. With `--resolve-pmid-doi`, a resolvable DOI missing from the ledger is also a failure, and it is not waivable.

- Certainty (`sof_table.py`): a row lacks certainty, or a ratio effect lacks a baseline risk.
- Numeric provenance (`numbers_provenance.py`): a draft number has no computed artifact.
- Cross-artifact integrity (`check_review_integrity.py`): an included study is missing from the references. A claim's supporting_sids is not a real source id.
- Cross-artifact integrity, continued: the artifacts disagree on a shared number. A template marker leaks into the deliverable.

- The retrieval shows zero duplicates across overlapping sources. The PRISMA stages do not reconcile. The codes are R, C, C2, D, M, E, X, T, W, and P.
- Ledger completeness (`check_ledger_completeness.py`): the screening ledger is shorter than the flow claims. An excluded record has no reason. An INCLUDE carries an exclusion reason.

- **Review completeness** (`check_completeness.py`): `removed_other` or `not_retrieved` is non-zero without an attributed, value-matched waiver in `completeness_waivers.json`. This gate stops an incomplete review from passing on a prose limitation alone.
- **Screening-conduct disclosure** (`check_screening_disclosure.py`): agent-run screening presented as human or independent, or no `CONDUCT_DISCLOSURE.txt` that declares the mode. The script also emits `screening_human_confirmation.csv`.

- **Gate coverage** (`check_selftest_coverage.py`): a gate runs on only one path. A gate that cannot fail is not a gate.
- **Acceptance (live)** (`acceptance_test.py`): it runs the toolchain on a live query, and then it tries to break each guard. Every adversarial case must fail. Exit 1 means a guard misbehaved.

- Appraisal honesty (`check_appraisal.py`): the Methods name a risk-of-bias tool, but the appraisal ledger is a placeholder.
- Screening calibration (`references/screening-governance.md`): κ < 0.60, or the criteria are not locked.
- Defect regressions (`regression_suite.py`): a previously seen defect class stops being caught.

Run the whole EvidenceForge suite with `../evidence-synthesis-forge/scripts/selftest.sh` (16
sections). Every gate runs on its pass path and on its fail path.

## Preflight (before Stage 1)

Run these checks before the first stage. Report every gap as an input gap, never as a result.

1. `../evidence-synthesis-forge/scripts/doctor.sh` reports the core toolchain.
2. The `paper-search` and `ncbi` MCPs answer a trivial query.
3. The output directory exists and is writable.
4. The user's mode answer is known, or the run records the default.

If a dependency is absent, stop. Do not start Stage 1 on a broken toolchain.

## Decision tables

### Which mode?

| Situation | Mode |
|---|---|
| The user names human-in-the-loop | Human-in-the-loop. |
| The user wants throughput and accepts the disclosure | Autonomous. |
| The user gives no answer | Autonomous, and log the default. |

### Which review type?

| Request | Route |
|---|---|
| A new review with primary studies | `evidence-synthesis-forge`. |
| A review of existing reviews | `umbrella-review-skeptic`. |
| An ecological or environmental question | `environment-life-review-forge`. |
| A statistical pooling question only | `meta-analysis`. |

## Worked examples

### Example 1 — an autonomous systematic review

The user asks to run a PRISMA 2020 review on a clinical question. Set AUTONOMOUS mode. Run
Stages 0 to 10 in order. Emit the `CONDUCT_DISCLOSURE` block. Fail the run if any machine gate
fails. Report the exit code of each gate.

### Example 2 — a request that routes away

The user asks for a search strategy and eligibility criteria, with no review pipeline. Route
to `evidence-synthesis-forge`. Do not start the ledger.

### Example 3 — an unavailable target

`meta-ml-screener` is not installed. Stop at Stage 5. Report the missing dependency as an
input gap (exit 4). Do not screen the records by hand, and do not skip to Stage 7.

## Failure modes and exit codes

| Condition | Result |
|---|---|
| The toolchain lacks a core dependency | `doctor.sh` exits non-zero. |
| A search lacks a date or a hit count | `prisma_s_appendix.py` exits `2`. |
| The PRISMA stages do not add up | `prisma_flow.py` exits `2`. |
| The gate finds an unresolved or retracted cited DOI | `cross_verify_citations.py` exits `2`. |
| A source was never reached | `prisma_s_appendix.py` and `check_completeness.py` exit `3`. |

| Condition | Result |
|---|---|
| A draft number has no artifact | `numbers_provenance.py` exits `2`. |
| An included study is missing from the references | `check_review_integrity.py` exits `2`. |
| The screening ledger is short | `check_ledger_completeness.py` exits `2`. |
| The screening claims a human conductor | `check_screening_disclosure.py` exits `2`. |
| The appraisal ledger is a placeholder | `check_appraisal.py` exits `2`. |

## What this does not do

- It does not design the protocol or the eligibility criteria. `evidence-synthesis-forge` does.
- It does not run the screen. `meta-ml-screener` does.
- It does not pool the effect sizes. The `meta-analysis` skill does.

- It does not invent a study, a count, an effect size, or a citation.
- It does not label an autonomous review as human-conducted or MECIR-compliant.

## Rubric coverage

Every item of `eval.md` maps to the section that implements it.

| Check | Section |
|---|---|
| SR1 alias meaning | Routing contract. |
| SR2 request routing | Routing contract and Routing. |
| SR3 target unavailable | Routing contract and Worked examples. |
| SR4 no duplicated analysis logic | What this does not do and The pipeline (10 stages, gated). |
| SR5 machine gates not waived | What does NOT change (machine gates stay mandatory) and the Quality gates list. |

| Check | Section |
|---|---|
| SR6 disclosure emitted | Mandatory disclosure (autonomous mode) — this is NOT optional. |
| SR7 ledger and counts | The artifact ledger (create these; every count comes from them). |
| SR8 exit-code honesty | Failure modes and exit codes. |
| SR9 preflight before Stage 1 | Preflight (before Stage 1). |
| SR10 mode selection | Decision tables and Execution modes — human sign-off is OPTIONAL. |

## Guardrails

- Do not start a stage before the prior gate has a log entry. In autonomous mode the log entry is the approval. In human-in-the-loop mode it must name the approving human.
- Emit the `CONDUCT_DISCLOSURE` block on every autonomous output.
- Do not label an autonomous review "Cochrane-compliant", "MECIR-compliant", or "PRISMA-compliant", and do not imply independent human screening.

- Do not present PRISMA counts as final. They are final only when the search, dedup, and screening logs support them.
- Do not let a classifier or an LLM replace the authoritative screen. It is a labelled aid only.
- Do not claim identical results on a re-run for an AI-assisted step.

- Claim what is true. Every decision carries documentation, a criterion reference, an evidence quote, an audit trail, a hashed prompt version, and a logged model version.
- Do not write conclusions before the protocol, search, screening, extraction, and appraisal exist.

## Provenance

Merges methodology from four sources (see `NOTICE.md`). AngelChen-HC/systematic-review-skill (Apache-2.0) supplies the screening governance. barah123/Claude-Biomedical-Research-Skills (MIT) supplies the integrity and PROSPERO material. keemanxp/slr-prisma (MIT) supplies the PRISMA 2020 manuscript layer. Aperivue/medsci-skills (MIT) supplies the reporting-guideline checklists.
Local EvidenceForge skills keep their own MIT licence.
