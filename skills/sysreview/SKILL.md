---
name: sysreview
description: "End-to-end systematic review entry point (alias /sysreview). Use when the user asks to run, plan, or conduct a systematic review, systematic literature review (SLR), scoping review, evidence map, rapid review, umbrella review, or a PRISMA 2020 review — from question and protocol through registered search, deduplication, calibrated dual screening, data extraction, risk-of-bias appraisal, PRISMA flow diagram, and a citation-verified manuscript. Orchestrates evidence-synthesis-forge, meta-ml-screener, umbrella-review-skeptic, the meta-analysis skill (for the pooling leg), the paper-search and ncbi MCPs, citecheck for citation verification, and humanizerdrb for the final prose pass. Every stage is gated and ledgered (sources.csv, claims.csv, search_log.csv, prisma_counts.json, GATE_REPORT.json). It never invents studies, counts, or citations, and it does not claim detector evasion."
allowed-tools: Read Write Edit Bash
license: MIT
metadata:
  version: "1.0"
  orchestrates: "evidence-synthesis-forge, meta-ml-screener, umbrella-review-skeptic, meta-analysis, citecheck, humanizerdrb, paper-search"
---

# /sysreview — Systematic Review Orchestrator

This is the single entry point for any systematic-review-shaped task. It does not
reimplement review methodology; it **sequences** the installed EvidenceForge skills,
the MCP fleet, and two gate scripts, and it enforces the ledger and gates at every
stage. Do not jump stages.

## When this fires

"systematic review", "SLR", "PRISMA", "PRISMA 2020", "scoping review", "evidence map",
"rapid review", "screen these papers", "build a search strategy", "run a review on …",
or an explicit `/sysreview`.

## Execution modes — human sign-off is OPTIONAL

Two modes. **AUTONOMOUS is the default.**

| Mode | How a gate is approved | Use for |
|---|---|---|
| **AUTONOMOUS** (default) | The agent resolves each gate itself and records the decision, the rule/evidence it applied, the confidence, and the model id + version. **No human step blocks progress.** | Throughput, drafting, exploratory reviews, autonomous pipelines |
| **HUMAN-IN-THE-LOOP** (opt-in) | A named human approves each gate before the next stage begins. | Reviews that must be reported as *human-conducted* |

Ask which mode is wanted at Stage 0, but **do not block on the answer**: if none is given,
proceed autonomously and log it.

### Mandatory disclosure (autonomous mode) — this is NOT optional

Removing the human step changes what the document *is*. MECIR's mandatory items require
independent **human** screening, extraction and appraisal, and PRISMA 2020 item 8 asks how many
*reviewers* screened each record and whether they worked independently. So an autonomously
conducted review **cannot be reported as a Cochrane/MECIR-compliant or human-conducted
systematic review.** Every autonomous output must carry:

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

Prohibited in autonomous mode: describing the output as "Cochrane-compliant", "MECIR-compliant",
"PRISMA-compliant" without the qualifier, or stating or implying that independent human reviewers
screened the records. That would be a false claim. Write it as *"AI-assisted, autonomously
conducted; not human-screened"* and let the reader decide.

### What does NOT change (machine gates stay mandatory)

Autonomy removes the **human approval** step, not the **error detection**. These still fail loud
and cannot be waived by the mode: citation resolution/retraction, PRISMA count reconciliation,
numeric provenance, search reproducibility, coding-sheet validation, and the κ agreement
computation (now measured against the agent's own pilot decisions). An autonomous run that fails
a machine gate is still a failed run.

## Non-negotiable rules (empirical integrity)

Borrowed in spirit from the `empirical-integrity` discipline: **never write a number,
date, hit count, citation, or finding into a deliverable from memory or training
knowledge.** If it can be checked against a live authoritative source, check it now.

1. Never invent a record, a count, an effect size, or a citation. A row exists because a
   lookup or the user returned it.
2. Copy bibliographic fields from the retrieved record, never from recall.
3. Use `not_reported` for fields the source omits — never blank.
4. `verification_status=verified` requires a `verifier` (a human id, **or** the agent id +
   model version in autonomous mode), a `verified_date`, and a `locator`.
5. A source that is **down must never look like a source that found nothing** — record
   `unavailable`, never `0 results`.
6. Distinguish PRISMA (a *reporting* guideline) from how the review is *conducted*.
7. No claim enters the manuscript without a resolvable, non-retracted source (see Gate D).
 8. Cross-artifact integrity is enforced by `../evidence-synthesis-forge/scripts/check_review_integrity.py`
    (`--root <project>`): reference-list completeness vs the included set, claims-ledger numeric
    sync, manuscript-numeric sync (screened/excluded/included/RoB counts), eligibility red-flags
    (perception-only outcomes, preliminary data), CSV well-formedness, and PRISMA reconciliation.
    A stale "N studies" count anywhere is a failed run.



## The pipeline (10 stages, gated)

| # | Stage | Owner skill / tool | Gate (auto-resolved in autonomous mode) |
|---|---|---|---|
| 0 | Mode + kickoff | this skill | Mode: NEW / UPDATE / RETRO-QA |
| 1 | Question (PICO/PECO) + protocol | `evidence-synthesis-forge` | Protocol approved |
| 2 | Registration (PROSPERO / applicable registry) | `../evidence-synthesis-forge/scripts/prospero_search.py` | Novelty + amendment rule set |
| 3 | Search strategy + known-item validation | `paper-search` MCP (`plan_search_query`) | **Gate 1**: strategy approved |
| 4 | Retrieval + dedup + stable IDs | `paper-search` MCP (bibliographic **and registry** sources), `ncbi` MCP | Export integrity reconciled |
| 5 | Screening calibration pilot (κ gate) | `meta-ml-screener` + this skill | **Gate 2a**: criteria LOCKED |
| 6 | Title/abstract + full-text screening | `meta-ml-screener` | **Gate 2 / 2b**: complete audit — human, or agent-logged in autonomous mode |
| 7 | Data extraction + coding | `evidence-synthesis-forge` / `meta-analysis-forge` | **Gate 3**: dataset locked |
| 8 | Risk of bias / quality | RoB 2 / ROBINS-I / NOS / AMSTAR-2 / GRADE | **Gate 4**: appraisal confirmed |
| 9 | Synthesis (narrative / SWiM / meta-analysis) | `meta-analysis` skill | **Gate 5**: plan approved |
| 10 | PRISMA flow + report + citations | this skill, `citecheck`, `humanizerdrb` | **Gate D**: citation gate passes |

## Routing

- Design, eligibility, protocol, search structure → `evidence-synthesis-forge`.
- ML-assisted screening / extraction / triage → `meta-ml-screener`.
- Statistical pooling leg → invoke the **`meta-analysis`** skill (do not pool here).
- Synthesising existing reviews → `umbrella-review-skeptic`.
- Environmental / ecological / life-science domain → `environment-life-review-forge`.
- Every search, DOI lookup, registry query → the `paper-search` and `ncbi` MCPs.
  Use `sources="auto"` (topic-routed); never `sources="all"` (burns paid quota).
- **A PubMed-only search is a single-source search, and the completeness gate now fails it.**
  Bibliographic databases cannot see trials that were registered but never published, or that were
  terminated — which is precisely where publication bias lives. Route at least one **registry**
  source as well (`search_clinicaltrials`, `search_ictrp`, `search_ctis`) and record every source
  with its hit count in `search_log.csv`. For the ventilatory-pneumonia question, the registry
  search returned 8 registered trials, one terminated at 740 patients and several completed with
  no posted results — none of which appear in any database search.
- Citation verification → `citecheck` and `../evidence-synthesis-forge/scripts/cross_verify_citations.py`.
- Final prose register → `humanizerdrb` (attribution, not evasion).

## The artifact ledger (create these; every count comes from them)

```
<review>/search_log.csv          one row per executed query: source, query, date, hits, source_status
<review>/sources.csv             one row per retrieved record: S-ID, DOI, PMID, title, year, retraction_status, verification_status, verifier, verified_date, locator
<review>/screening_log.csv       one row per screened record: record_id, decision, rule, confidence, reason
<review>/claims.csv              one row per atomic claim: C-ID, claim text, supporting S-IDs
                                 (quote the S-ID cell when a claim has more than one: "S001,S004")
<review>/prisma_counts.json      the PRISMA flow counts. Two shapes are accepted by every gate:
                                 nested (identification/screening/retrieval/eligibility/included)
                                 or flat (identified_databases/screened/excluded_ta/sought/assessed/
                                 not_retrieved/excluded_ft/included_studies/in_meta_analysis).
<review>/eligibility_rules_registry.json   versioned boundary rules (see screening-governance.md)
<review>/ledgers/extraction.csv  one row per included study: source_id, primary_outcome, effect_primary, extraction_note
<review>/ledgers/rob_assessment.csv  one row per included study: source_id, tool, domain_summary
<review>/ledgers/sources_included.csv   source_id, one row per included study
<review>/manuscript.md           the draft; included studies must appear in its reference list
<review>/GATE_REPORT.json        result of ../evidence-synthesis-forge/scripts/cross_verify_citations.py -- must be all-clear
```

`../evidence-synthesis-forge/scripts/check_review_integrity.py` requires sources.csv, claims.csv,
manuscript.md and prisma_counts.json to exist; a missing one is reported as a finding, not a traceback.

Draft with `[claim:C001] [src:S001,S004]` markers; the reference builder renumbers by
first appearance (ICMJE/Vancouver) and strips the claim markers.

## Load (read before working the stage)

**Standards layer (Cochrane / MECIR / GRADE — paraphrased, cited):**
- `../evidence-synthesis-forge/references/cochrane-handbook-map.md` — which of the 26 chapters
  governs each decision, and the four amateur-vs-expert failure points it prevents.
- `../evidence-synthesis-forge/references/mecir-standards.md` — the mandatory (M) gates per
  stage. MECIR is stricter than PRISMA: PRISMA governs what to *report*, MECIR what must have
  been *done*.
- `../evidence-synthesis-forge/references/search-reporting-prisma-s.md` — the 16 search-reporting
  items that make a search reproducible.
- `../evidence-synthesis-forge/references/rob-tool-selection.md` — RoB tool by design.
- `../evidence-synthesis-forge/references/grade-certainty.md` — certainty + SoF.
- `../evidence-synthesis-forge/references/cochrane-figures-tables.md` — Handbook III.S1 figures.
- `../evidence-synthesis-forge/references/icmr-systematic-review-guide.md` — **ICMR** *Beginner's
  Guide for Systematic Reviews* (Government of India): India-facing conduct guidance, a
  ready-made extraction form, and policy-dissemination framing. Use alongside Cochrane, never
  instead of it (Cochrane governs contested method decisions).

**Stage references (as before):**
- `references/screening-governance.md` — pilot / κ-gate / criteria-lock protocol.
- `references/cross-model-verification.md` — optional, consent-gated second-family check.
- `../evidence-synthesis-forge/references/prospero-and-citation-verification.md` — PROSPERO +
  citation integrity.
- `../evidence-synthesis-forge/references/prisma-2020-manuscript-reporting.md` — 27-item PRISMA.
- `../evidence-synthesis-forge/references/reporting-guideline-checklists.md` — 49 instruments.

**Scripts:**
- `../evidence-synthesis-forge/scripts/doctor.sh` — verify the toolchain before starting.
- `../evidence-synthesis-forge/scripts/prospero_search.py` — registration / novelty.
- `../evidence-synthesis-forge/scripts/prisma_flow.py` — PRISMA 2020 flow from counts (reconciles
  the arithmetic and fails if the stages do not add up).
- `../evidence-synthesis-forge/scripts/prisma_s_appendix.py` — PRISMA-S search appendix; fails if
  any search lacks a date or hit count.
- `../evidence-synthesis-forge/scripts/sof_table.py` — Summary of findings; validates certainty.
- `../evidence-synthesis-forge/scripts/cross_verify_citations.py` — the citation gate.
- `../evidence-synthesis-forge/scripts/numbers_provenance.py` — no number without provenance.
- `../evidence-synthesis-forge/scripts/generate_prisma_flow.py` — minimal Mermaid flow (legacy).
- `../evidence-synthesis-forge/scripts/check_review_integrity.py` — cross-artifact integrity (R/C/C2/D/M/E/X/T/W/P).
- `../evidence-synthesis-forge/scripts/check_ledger_completeness.py` — screening-ledger completeness.
- `../evidence-synthesis-forge/scripts/check_appraisal.py` — appraisal honesty (no placeholder RoB).
- `../evidence-synthesis-forge/scripts/check_completeness.py` — refuses an incomplete review (see below).
- `../evidence-synthesis-forge/scripts/fetch_pubmed_complete.py` — paginates the search and batch-fetches
  every record, so the completeness gate can actually be satisfied instead of waived.
- `../evidence-synthesis-forge/scripts/gate2a_calibration.py` — GATE 2a pilot κ / PABAK agreement gate.
- `../evidence-synthesis-forge/scripts/regression_suite.py` — one fixture per defect class.

## Quality gates (must pass before anything is reported)

Each of these **fails loudly**; none may be skipped or hand-waved.

| Gate | Script | Fails when |
|---|---|---|
| Toolchain | `../evidence-synthesis-forge/scripts/doctor.sh` | a core dependency is missing |
| Search reproducibility | `../evidence-synthesis-forge/scripts/prisma_s_appendix.py` | any search lacks a date or a hit count |
| PRISMA counts | `../evidence-synthesis-forge/scripts/prisma_flow.py` | the stages do not arithmetically add up |
| Citation integrity | `../evidence-synthesis-forge/scripts/cross_verify_citations.py` | a cited DOI is unresolved or retracted — or, with `--resolve-pmid-doi`, a DOI that IS resolvable from the row's PMID is missing from the ledger (not waivable) |
| Certainty | `../evidence-synthesis-forge/scripts/sof_table.py` | a row lacks certainty, or a ratio effect lacks a baseline risk |
| Numeric provenance | `../evidence-synthesis-forge/scripts/numbers_provenance.py` | a number in the draft is not traceable to a computed artifact |
| Cross-artifact integrity | `../evidence-synthesis-forge/scripts/check_review_integrity.py` | an included study is missing from the references; a claim's `supporting_sids` is not a real source id (e.g. prose from an unquoted embedded comma); artifacts disagree on a shared number; a template marker leaks into the deliverable; the retrieval shows zero duplicates across overlapping sources; or the PRISMA stages do not reconcile. Codes: R/C/C2/D/M/E/X/T/W/P |
| Ledger completeness | `../evidence-synthesis-forge/scripts/check_ledger_completeness.py` | the screening ledger is shorter than the PRISMA flow claims was screened, an excluded record has no reason, or an INCLUDE carries an exclusion reason |
| **Review completeness** | `../evidence-synthesis-forge/scripts/check_completeness.py` | `removed_other` (identified but never screened) or `not_retrieved` (sought but never assessed) is non-zero without an explicit, attributed, value-matched waiver in `completeness_waivers.json`. **This is the gate that stops an incomplete review from passing on a prose limitation alone.** |
| **Screening-conduct disclosure** | `../evidence-synthesis-forge/scripts/check_screening_disclosure.py` | agent-run screening is described as human/independent (or as MECIR/Cochrane/PRISMA-compliant) in the manuscript, or no `CONDUCT_DISCLOSURE.txt` declares the mode and the extent of human involvement. Also emits `screening_human_confirmation.csv`, the worklist a human must sign off. |
| **Gate coverage** | `../evidence-synthesis-forge/scripts/check_selftest_coverage.py` | any gate is exercised on only one path — a gate that cannot fail is not a gate |
| **Acceptance (live)** | `../evidence-synthesis-forge/scripts/acceptance_test.py` | run before trusting a release: it runs the whole toolchain on a **live** query and then deliberately tries to break each guard (a real retracted DOI, an unregistered DOI, a false human-screening claim, an unwaived completeness gap, a stale waiver, mixed estimands). Every adversarial case must FAIL; the test passes only when each one does. Exit 1 = a guard misbehaved. |
| Appraisal honesty | `../evidence-synthesis-forge/scripts/check_appraisal.py` | the Methods name a risk-of-bias tool but the appraisal ledger is a placeholder (e.g. "PROBAST (conceptual)") or records no domain judgement |
| Screening calibration | `references/screening-governance.md` | κ < 0.60, or criteria not locked |
| Defect regressions | `../evidence-synthesis-forge/scripts/regression_suite.py` | any previously-seen defect class stops being caught (one fixture per defect) |

Run the whole suite with `../evidence-synthesis-forge/scripts/selftest.sh` (16 sections; every
gate is checked on both its pass and its fail path — a gate that cannot fail is not a gate).

## Guardrails

- Do not begin a stage before the prior gate is **logged**. In autonomous mode the log entry
  *is* the approval; in human-in-the-loop mode it must name the approving human.
- Emit the `CONDUCT_DISCLOSURE` block (above) on every autonomous output, and never label an
  autonomous review "Cochrane/MECIR/PRISMA-compliant" or imply independent human screening.
- Do not present PRISMA counts as final unless traceable to search + dedup + screening logs.
- Do not let a classifier/LLM replace the authoritative screen; it is a labelled aid only.
- Do not claim "identical results on re-run" for AI-assisted steps; claim what is true:
  every decision is documented, criterion-referenced, evidence-quoted, audited (by a human, or
  by the agent in autonomous mode with the disclosure attached), and
  traceable to a hashed prompt version and a logged model version.
- Do not write conclusions before protocol, search, screening, extraction, and appraisal exist.

## Provenance

Merges methodology from (see `NOTICE.md`): AngelChen-HC/systematic-review-skill (Apache-2.0,
screening governance), barah123/Claude-Biomedical-Research-Skills (MIT, integrity +
PROSPERO), keemanxp/slr-prisma (MIT, PRISMA 2020 manuscript), Aperivue/medsci-skills
(MIT, reporting-guideline checklists). Local EvidenceForge skills retain their own MIT licence.

