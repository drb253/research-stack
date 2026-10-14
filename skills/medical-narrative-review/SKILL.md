---
name: medical-narrative-review
description: "Write, expand, or audit a medical narrative review on a supplied topic. Scopes the question, searches PubMed, Europe PMC, and trial registries through MCP tools, and verifies every citation by DOI or PMID before it enters the text. Builds a source ledger with per-claim locators and drafts a referenced manuscript with a structured abstract. Exports DOCX, PDF, and HTML, then runs a submission gate that blocks unverified, retracted, duplicated, or fabricated references. Use for narrative reviews, CME articles, or an audit."
allowed-tools: Read Write Edit Bash
license: MIT
compatibility: Python 3.9+ standard library only for the bundled CLIs, verified end to end on 3.9 and 3.11 (no third-party packages, no network, no API keys). Live literature search and DOI/PMID verification require the paper-search MCP server; without it the skill runs offline on user-supplied sources and refuses to invent references. Embedding figures into DOCX uses a local SVG rasteriser when one exists (rsvg-convert, inkscape, magick, or macOS qlmanage); the PDF draws its own figures and needs nothing.
metadata:
  version: "1.0"
  skill-author: local (custom skill)
  slash-command: /medical-narrative-review
  invocation-example: /medical-narrative-review Gut microbiome and immunotherapy response in advanced melanoma
---

# Medical Narrative Review

Produce a medical narrative review. It must be complete, accurately cited, and hard to falsify by accident.
The skill enforces one chain, and every link in it is a file on disk.

## Purpose

The chain is:

```
question -> search log -> retrieved records -> verified sources -> claims -> prose -> displays -> gate
```

The value of the skill is not fluent prose. The value is the enforced chain. If a link is missing, the
review is not finished. The gate command says so explicitly instead of quietly filling the gap.

A narrative review is a scholarly argument built from verified literature. It is not a systematic review
in disguise. It must state how the authors selected the literature, and it must not claim the
exhaustiveness of a systematic review.

## When to use

- The user says "write a review on <topic>", "draft a review article", or "narrative review of <drug, disease, biomarker>".

- The user wants a continuing-education overview, a narrative synthesis for a journal, a book chapter, or a grand-rounds background document.

- The user wants to update an existing review.

- The user wants an audit of a review for wrong citations, false claims, or missing evidence.

- Any biomedical review needs figures, tables, and a reference list that a reviewer can spot-check.

## When not to use

- A formal systematic review or meta-analysis with pooled estimates. Use a systematic-review workflow. This skill deliberately does **not** pool effect sizes.

- A primary research manuscript about a study you conducted. Use a scientific-writing workflow.

- A peer review of someone else's confidential manuscript. Use a peer-review workflow.

- A rapid single-fact answer. Answer directly. Do not scaffold a review.

## Preflight and dependencies

Check the environment first. Then fix the vocabulary of this file.

<!-- ste-allow R1,R2,R3: a markdown table is one layout block; the sentence-length, one-instruction and sentence-count rules do not apply to its cells -->

| Item | Test | Action on failure. |
|---|---|---|
| Python | `python3 --version` (3.9 or later) | Stop; report the version. |
| Toolkit | `ls scripts/gate.py scripts/init_review.py` | Stop; the skill is incomplete. |
| MCP server | Look for `search_pubmed` and `search_papers`. | Run offline on user-supplied sources. |
| Figure rasteriser | `command -v rsvg-convert inkscape magick qlmanage` | The DOCX carries a labelled placeholder. |
| Workspace | Confirm write access to the output directory. | Stop; report the path. |

The question framework is population, intervention, comparator, and outcome (PICO). It can instead be population, exposure, and outcome (PEO). The reporting standard is the Preferred Reporting Items for Systematic Reviews and Meta-Analyses (PRISMA). The appraisal scale is the Scale for the Assessment of Narrative Review Articles (SANRA). The certainty framework is Grading of Recommendations Assessment, Development and Evaluation (GRADE).

The checklist for observational syntheses is Meta-analysis Of Observational Studies in Epidemiology (MOOSE). The authorship standard is the International Committee of Medical Journal Editors (ICMJE). A drug name follows the international nonproprietary name (INN). Protected health information (PHI) never enters a file. Continuing medical education (CME) articles follow the same rules.

The World Health Organization (WHO) runs the International Clinical Trials Registry Platform (ICTRP) and the Clinical Trials Information System (CTIS). The Directory of Open Access Journals (DOAJ) and the Open Science Framework (OSF) hold further records. The export writes the figure as a Scalable Vector Graphics (SVG) file. The DOCX embeds a Portable Network Graphics (PNG) image. Report the confidence interval (CI) and the hazard ratio (HR) as the source states them.

Without the MCP server, the skill runs offline. It then uses user-supplied sources only, and it refuses to invent a reference.

## Non-negotiable rules (the anti-hallucination contract)

These rules override any request to just write it, to make it look complete, or to fill in reasonable
values.

1. **No reference exists until the tool retrieves it and verifies its identifier**. A citation may enter the review only after a live lookup returns a record with a resolvable DOI or PMID. The title, first author, journal, and year must match what the article cites. Memory, plausible author-journal-year combinations, another paper's bibliography, and search snippets are discovery aids, never citations.

2. **The identifier is the source of truth**. The tool copies bibliographic details from the retrieved record. It never reconstructs them from a citation string or from recall.

3. **Unverifiable material becomes a visible placeholder**, e.g. `[UNVERIFIED - DO NOT CITE]`, never a silently plausible citation. List every placeholder in the Unresolved items appendix. Cut a claim with no verified support, or attribute it explicitly to the absence of evidence.

4. **Copy every number. Never compute one from memory**. Every percentage, mean, confidence interval, hazard ratio, and sample size traces to one recorded value with a locator. If the paper reports 3.4%, the review says 3.4%.

5. **Never upgrade evidence**. Association is not causation, and a non-significant result is not equivalence. A preprint has no peer review. A single-centre retrospective cohort is not a landmark trial. A surrogate endpoint is not a clinical outcome. Label animal and in vitro data as such in every clinical sentence.

6. **Check retractions and corrections before you cite**, through `check_retraction` and the record's own status. A retracted source may appear only as a retracted work, in a sentence that says so.

7. **No display without recorded data**. Build tables and figures from the ledgers or the user's own data, through the bundled scripts. Never invent a trend, a decorative number, a redrawn graphic, or a significance star.

8. **No PHI, ever**. Never put a patient identifier, a date of birth, a medical record number, or an accession number in a file. Never put unpublished third-party data in a prompt either. Redaction needs user confirmation. The phrase "I removed the names" is not de-identification.

9. **AI is not an author**. The skill drafts. Named human authors decide, verify, and approve. Write the AI-use disclosure per the target journal's current policy.

10. **The gate is authoritative**. A review that fails `scripts/gate.py` is not submission-ready, however good the prose is. Report failures plainly, with issue codes.

## Decision table

Pick the route from the request.

<!-- ste-allow R1,R2,R3: a markdown table is one layout block; the sentence-length, one-instruction and sentence-count rules do not apply to its cells -->

| The request | Route | First action. |
|---|---|---|
| Write a new review. | Phases 0 to 9. | Lock the scope into `scope.md`. |
| Expand an existing draft. | Phase 5 onward, after verification. | Verify every existing citation first. |
| Audit a review for false claims. | Phases 3 and 8. | Run `audit_citations.py` and `gate.py`. |
| Fix wrong citations only. | Verification protocol, then Phase 8. | Re-run `build_reference_list.py`. |
| Pool effect sizes. | Stop. | Route to a meta-analysis workflow. |

## Workflow

Work phase by phase. Do not start Phase 6 before Phases 1 to 5 have left artifacts on disk. Ask only
the questions needed to unblock the current phase, with the defaults in `assets/topic_intake.md`. Mark
an unknown as unresolved rather than guessing.

### Phase 0 — Intake and scope lock

1. Record the topic and the exact PICO or PEO framing.

2. Record the target journal or venue and its current author instructions.

3. Record the article type and its word, table, and figure limits.

4. Record the citation style, the audience, and the clinical setting.

5. Record the review time window, the languages allowed, and the designs to include.

6. Record an explicit out-of-scope list.

7. Write these items into `scope.md`, using `assets/topic_intake.md`.

8. If the user gives only a topic, propose a default PICO, state the assumption, and proceed. Do not stall.

### Phase 1 — Scaffold

```bash
python3 scripts/init_review.py --out-dir ./review-<slug> --document-id <slug> --title "<working title>"
```

The script creates the full workspace (below). It refuses to overwrite an existing directory.

### Phase 2 — Structured search (record everything, including failures)

1. Run `plan_search_query` first.

2. Search at least three independent sources.

3. Keep the raw counts.

<!-- ste-allow R1,R2,R3: a markdown table is one layout block; the sentence-length, one-instruction and sentence-count rules do not apply to its cells -->

| Need | Tool |
|---|---|
| Broad multi-source sweep, retraction screening, ID conversion | `search_papers`, `check_retraction`, `convert_paper_ids`, `get_crossref_paper_by_doi` |
| Biomedical primary index | `search_pubmed`, `search_pmc`, `search_europepmc`, `search_bookshelf` |
| Preprints, which the review must label as such | `search_medrxiv`, `search_biorxiv` |
| Bibliographic and DOI-level records | `search_crossref`, `search_openalex`, `search_semantic`, `search_doaj` |
| Trials and registries | `search_clinicaltrials`, `search_ictrp`, `search_ctis` |
| Metrics, related work, and citing work | `get_citation_metrics`, `get_related_articles`, `get_citing_articles` |
| Regex or filtered evidence-grade search | `academic-search__search_papers`, `academic-search__search_by_author` |
| Consensus and position statements | `consensus__search` — only when the Consensus server is configured. It is not one of the three servers this repository mounts. Check for the tool first. When it is absent, use `search_pubmed` and `search_bookshelf` for statements and guidelines. |
| MeSH term control | `get_mesh_details` |

- Run the same concept blocks across databases.

- Record the exact query string, database, date, filters, and hit count in `search_log.csv`.

- Record per-source availability (`empty` vs `unavailable`), so a rate-limited database never reads as "no evidence exists".

- Log every retrieved record in `sources.csv`.

- Read the syntax, the MeSH strategy, the deduplication, and the PRISMA-S reporting in `references/search_and_retrieval.md`.

### Phase 3 — Screen and verify

Deduplicate by DOI, then by PMID, then by normalized title and year. Record include or exclude with a
reason for every record.

<!-- ste-allow R1,R2,R3: a markdown table is one layout block; the sentence-length, one-instruction and sentence-count rules do not apply to its cells -->

| State | Meaning |
|---|---|
| `included` | In the evidence base. |
| `cited_for_context` | Verified and citable, but deliberately outside the evidence base, such as an out-of-scope modelling study. |
| `excluded` | With a specific reason. |
| `pending` | Not yet decided. |

Every citable record needs `verification_status=verified`, a named `verifier`, a `verified_date`, a
`locator`, and a `retraction_status`. This phase is where reviews normally fail. Do not rush it.

### Phase 4 — Extraction

For each verified source, extract these fields into `sources.csv`. The fields are design, population,
intervention or exposure, comparator, outcomes, follow-up, size, and every effect estimate with its
uncertainty. Add the exact locator for each value.

Fill a missing item with the literal `not_reported`. Never leave a blank that could later read as zero.
Never infer a value. Every claim stays attributed to a verified source in `sources.csv`.

### Phase 5 — Claim ledger and outline

Decompose the review into atomic claims. Give each claim a `C` ID, a section, a kind, and a direction
(`supports`/`refutes`/`mixed`/`neutral`). Add a certainty, and one or more **verified** `S` IDs. Build the
thematic outline from claim clusters, not from a list of papers.

```bash
python3 scripts/validate_sources.py sources.csv --require-included
```

### Phase 6 — Draft with traceable markers

Draft in Markdown, using `assets/manuscript_scaffold.md` and `references/section_blueprints.md`. Tag
every factual or numeric sentence:

```text
Chemotherapy plus pembrolizumab improved pathological complete response ... [claim:C014] [src:S006,S011]
```

Follow `references/medical_language.md` (hedging, causal verbs, units, drug naming) and
`references/integrity_ai_authorship.md`.

The audit checks markers per paragraph. A paragraph that contains a number, a percentage, an effect
estimate, or a significance statement must carry a claim marker somewhere in that paragraph. Wrap the
prose normally. One sentence per line is still the cleanest habit. It keeps markers next to the numbers
they support, and it makes the audit location exact.

### Phase 7 — Displays

Build tables and figures from the ledgers and the user's data only:

```bash
python3 scripts/make_evidence_table.py sources.csv --group-by design --style evidence-table --out tables/table1.md
python3 scripts/make_evidence_table.py sources.csv --group-by certainty --style certainty-of-evidence --out tables/table2.md
python3 scripts/make_prisma_flow.py prisma_counts.json --out-dir figures/
```

`make_prisma_flow.py` emits Mermaid and standalone SVG. It **fails** if the flow arithmetic does not
balance, so the diagram can never disagree with the recorded counts. Read the panel, caption, alt-text,
accessibility, and prohibited-decoration rules in `references/tables_and_figures.md`.

### Phase 8 — Finalize numbering and run the gate

```bash
python3 scripts/build_reference_list.py draft.md sources.csv claims.csv --style vancouver --out-dir final/
python3 scripts/audit_citations.py final/manuscript_cited.md claims.csv sources.csv --final
python3 scripts/check_numbers.py final/manuscript_cited.md
python3 scripts/lint_manuscript.py final/manuscript_cited.md --sections
python3 scripts/gate.py --dir . --style vancouver
```

`build_reference_list.py` renumbers citations in first-appearance order. It writes `final/references.md`
and `final/citation_map.csv`. It **refuses** to emit a reference list that contains any unverified, retracted, or
excluded source, or any source without an identifier. `gate.py` aggregates every audit into one
pass-or-fail report. Every `error` issue is a blocker. Fix it and re-run until the gate passes.

### Phase 9 — Export the deliverables

```bash
python3 scripts/export_document.py final/manuscript_cited.md \
  --workspace . --out-dir final \
  --references final/references.md \
  --append tables/table1.md --append tables/table2.md \
  --figure prisma_counts.json \
  --title "<review title>" --citation-style vancouver --footer-left "<short running title>"
```

The command produces three formats from the same final Markdown, with no third-party packages.

<!-- ste-allow R1,R2,R3: a markdown table is one layout block; the sentence-length, one-instruction and sentence-count rules do not apply to its cells -->

| Output | What it contains |
|---|---|
| `final/manuscript.docx` | Word styles (Title, Heading 1-4, Caption, Table text, Reference), real Word tables with repeating header rows, hanging-indent references, page numbers in the footer, and the figure embedded as a PNG |
| `final/manuscript.pdf` | A4, Times typography with real metrics, ruled tables, running footer, and the screening flow drawn as **vectors from `prisma_counts.json`** |
| `final/manuscript.html` | Print-ready CSS (A4 page breaks before References and appendices), tables that repeat their header across pages, clickable citations linked to their reference entries, and the SVG figure shown directly |

Then confirm the delivery with the gate:

```bash
python3 scripts/gate.py --dir . --style vancouver --require-exports
```

Notes that matter:

- The PDF draws the figure itself, so it never depends on a rasteriser. The DOCX embeds a PNG. Supply one, or let the tool convert the SVG locally with `rsvg-convert`, `inkscape`, `magick`, or macOS `qlmanage`. If no rasteriser exists, the DOCX carries a labelled placeholder and the tool delivers the SVG beside it. The DOCX never pretends that a missing figure is present.

- Every run regenerates the exports, because the tool derives them from the final Markdown. Re-export after any edit.

- Page numbers come from the Word or PDF engine. When you print the HTML from a browser, enable the browser's header and footer to get page numbers.

## Verification protocol (Phase 3 detail)

Work through this list for each candidate source, in order.

1. Retrieve the record by DOI (`get_crossref_paper_by_doi`) or by PMID, and confirm that it exists.

2. Confirm that **title, first author, container, year, and volume or pages** match the citing sentence.

3. Confirm the publication type and the peer-review status. Flag preprints, editorials, letters, and conference abstracts, which carry different evidentiary weight.

4. Run `check_retraction` on the DOI and record `retraction_status`.

5. Where access is available, open the source. Confirm that it supports the claim's *direction, population, intervention, comparator, outcome, time point, and magnitude*, not merely its topic.

6. Record the exact locator: section, page, table, figure, or `abstract_only` when that is all that exists.

7. Set `verification_status=verified`, `verifier=<name>`, and `verified_date=<ISO date>`.

If a lookup fails or is unavailable, record `verification_status=unverified` and keep the item out of the
prose. Never promote an unverified item to make the gate pass. The gate exists to catch exactly that.

### How to read the tool responses

The live MCP server shows these behaviours, and they matter.

- **An unknown DOI returns an empty object `{}` with no error flag**. An empty response means the DOI did not resolve. Record `verification_status=failed` and never cite it. Treating `{}` as success is the single easiest way to fabricate a reference.

- **Compare the record, not your memory**. A DOI and a title can both look right and still belong to different papers. Always compare the title, first author, container, year, and volume or pages from the returned record against the sentence you write. A mismatch means the citation is wrong, even if the DOI resolves.

- **`check_retraction` returns loosely matched notices**. The `notices` list includes items whose `targets_this_doi` is `false`. Only `is_retracted: true` or a notice with `targets_this_doi: true` means that the source itself carries a retraction. Read `sources_checked` and `sources_unavailable`. If a source was unavailable, the retraction status is `not_checked`, not `clear`.

- **Author name formats differ by source**. Crossref returns full given names separated by semicolons (`Leena Gandhi; Delvys Rodríguez-Abreu; ...`). Convert them to the ledger's `Surname AB` form for NLM or Vancouver output. PubMed returns initials directly. Prefer PubMed for the author string, and Crossref or the DOI record for volume, issue, and pages.

- **Record the conversion you performed.** Never invent initials.

## Registries and workspace

`init_review.py` creates this tree.

```text
review-<slug>/
  scope.md                 # PICO, venue, limits, out-of-scope list, assumptions
  search_log.csv           # database, query, date, filters, hits, availability
  sources.csv              # source ledger: one row per retrieved record (S IDs)
  claims.csv               # atomic claims mapped to verified S IDs (C IDs)
  prisma_counts.json       # real screening counts used to draw the flow diagram
  draft.md                 # marked manuscript (Phase 6)
  figures/  tables/  final/
  UNRESOLVED.md            # every placeholder, conflict, and open question
  GATE_REPORT.json         # written by gate.py
```

The schemas, field by field, are in `references/evidence_ledger.md`. The ledgers contain **metadata and
the authors' own text only**. They never contain source documents, patient data, or third-party
unpublished content.

## Two ledgers, two directions

- `sources.csv` answers "is this citation real, verified, and correctly described?"

- `claims.csv` answers "is this sentence supported, by what, and how strongly?"

The audit joins the two ledgers. A claim marker whose sources lack verification is an error. A source that
the manuscript cites but the ledger omits is an error. A claim that the ledger registers but the
manuscript never uses is a warning to resolve before submission.

## Optional advisory classifier (Laya)

An optional, opt-in local decision engine can propose judgments about *text*: hedging and certainty
observations, and theme suggestions. It is **advisory only, and it can never change a gate verdict**. Its
findings appear as `info`-severity `ADVISORY_*` codes. No model output may set `verification_status`,
`retraction_status`, `inclusion_status`, or any error. The ten deterministic commands never import the
classifier, so the pipeline works identically with it absent, uninstalled, or wrong.

**Where the classifier may and may not participate is a written policy, not a preference**. Read
`references/advisory_decision_plan.md`. In short, the policy forbids the classifier structurally from
touching verification, retraction, inclusion, numbers, references, PRISMA arithmetic, and the gate
verdict. A text classifier has no retrieval and no knowledge base, so it cannot decide those things.
Each candidate text-judgment stage must clear a measured bar on at least 50 labelled records before the
skill offers it at all.

These are the measurements so far on this machine. The causality axis **missed** the worst overclaim in
a six-sentence probe (0.041, the lowest score in the set). The hedging axis **did not separate** high-
from low-certainty claims across nine real sentences. `publication_type` classification scored **1/3**,
and it defaulted to the generic label. The shipped checkpoint's own library warns that its confidence
values are **uncalibrated**. Treat the classifier as a hint generator, never as a source of accuracy.

The full contract, the prompts, the schemas, the costs, and the removal steps are in
`references/advisory_laya.md`.

## Reporting standards

PRISMA does not bind a narrative review, but transparency does. Declare in Methods which standard the
authors followed. Report the **SANRA** items in the appendix. The items are justification, aims, search
description, referencing quality, scientific reasoning, and data presentation. Where the review
contains a systematic search component, report **PRISMA 2020** items 1 to 16 and **PRISMA-S** for the
search. Read `references/reporting_guidelines.md` for GRADE-style certainty language, MOOSE for
observational syntheses, and the EQUATOR routing for CONSORT, STROBE, and CARE.

## Style, language, and integrity

- Write hedged, precise, non-promotional prose. Use no marketing adjective. "Novel", "breakthrough", and "revolutionary" appear only inside a verified quotation.

- Use an active causal verb only where the cited design supports causation. Otherwise write `was associated with`, or `cohort studies suggest`.

- State units, denominators, and uncertainty always. Report `p` values as the source reported them. Never write a bare "significant" without the test and the comparison.

- Spell out each abbreviation at first use in the abstract, the body, and every table and figure caption.

- Name a drug by its INN (generic), with one brand-name mention where that is clinically relevant. Name a device or an assay by manufacturer and version.

- Never reuse a verbatim quotation longer than ~25 words, and never reuse text from any source. Paraphrase in the authors' own words, with attribution.

- Follow the target journal's current policy for the AI-use disclosure, the authorship criteria, and the conflicts of interest.

## Worked examples

### Example 1 — a DOI that looks right and is not

The draft cites a DOI for a trial of drug X in melanoma. The record that the DOI resolves to is a trial
of drug Y in renal cancer. The title and the first author differ. The tool records
`verification_status=failed` for that item, keeps it out of the prose, and raises the mismatch for the
author. The DOI resolved, so the citation still fails.

### Example 2 — a claim with no verified support

The author wants to keep a sentence about a 30% response rate, and no retrieved record reports it. The
skill does not invent a source. It cuts the sentence, or it attributes the claim explicitly to the
absence of evidence. Record the decision in `UNRESOLVED.md`.

### Example 3 — a PRISMA figure that disagrees with the counts

The screening counts changed after the author edited `sources.csv`, and `prisma_counts.json` is stale.
`make_prisma_flow.py` exits non-zero because the flow arithmetic does not balance. The diagram cannot
disagree with the recorded counts, so the fix is a corrected counts file, not a redrawn figure.

### Example 4 — offline mode

The MCP server is absent. The skill runs offline on user-supplied sources. Every source that the user
did not supply stays `unverified`, and it stays out of the prose. The skill reports the unavailable
tools plainly, and it never fills a gap from memory.

### Example 5 — an unread source blocks the gate

A citable source has `retrieval_status` that says its text was never obtained. `gate.py` exits 3 with
`status: insufficient_evidence` and a worklist in `input_gaps[]`. It also sets `submission_ready:
false`. `--allow-insufficient` exits 0 while the report still records the condition.

## Failure modes this skill is designed to prevent

<!-- ste-allow R1,R2,R3: a markdown table is one layout block; the sentence-length, one-instruction and sentence-count rules do not apply to its cells -->

| Failure | Control |
|---|---|
| A fabricated or wrong reference. | Identifier verification before citation; the refusal in `build_reference_list.py`; `audit_citations.py`. |
| Wrong metadata (journal, year, authors). | The copy-from-record rule; duplicate detection on DOI and normalized title. |
| An overstated claim ("proves") from a weak design. | The causal-language checks in `lint_manuscript.py`; the certainty field in `claims.csv`. |
| A number that contradicts the source. | Extraction with locators; `check_numbers.py` recomputes n/N, CI, and ranges. |
| A PRISMA figure that disagrees with screening. | The arithmetic gate in `make_prisma_flow.py`. |
| Missing key literature. | Multi-database search with logged queries; availability logging; citing-article and related-article sweeps. |
| Silent gaps and unfinished sections. | Placeholder detection; the `--sections` completeness check; `UNRESOLVED.md`. |
| A citation to a retracted study. | `check_retraction` plus the `retraction_status` gate. |
| Sensitive-data leakage. | The PHI pattern lint; metadata-only ledgers. |
| Model-generated advice that silently overrides a check. | Advisories are `info`-only, prefixed `ADVISORY_*`, and labelled "not a gate input". No model output can set an error or a ledger state. |
| A figure that is missing or broken in the delivered document. | The PDF draws it as vectors from the counts; the DOCX embeds a real PNG or says plainly that it could not; the HTML shows the SVG. |
| A deliverable that a co-author cannot open. | The tool produces DOCX, PDF, and print-ready HTML from the same source, so no format is a second-class copy. |

## Failure modes and exit codes

<!-- ste-allow R1,R2,R3: a markdown table is one layout block; the sentence-length, one-instruction and sentence-count rules do not apply to its cells -->

| Symptom | Status | Exit | Fix. |
|---|---|---|---|
| An `error` issue is present. | `fail` | 1 | Fix the issue and re-run the gate. |
| A citable source has no text. | `insufficient_evidence` | 3 | Supply the source the worklist names. |
| The gate must proceed anyway. | `insufficient_evidence` | 0 | `--allow-insufficient` records the condition and exits 0. |
| A required section is absent. | `fail` | 1 | Add the section; `--sections` names it. |
| A placeholder remains. | `fail` | 1 | Verify the item, or cut the claim. |
| An unverified reference list entry. | `fail` | 1 | `build_reference_list.py` refuses to emit it. |
| The exports are stale. | `fail` | 1 | Re-run `export_document.py`, then `gate.py --require-exports`. |

Every script prints a JSON report with `status`, `summary`, and `issues[]`, and every issue carries a
stable code. The exit code is `1` when any `error`-severity issue is present. The exit code is `3` when
the input itself could not be read. One example is a citable source whose `retrieval_status` says its
text was never obtained.

That third code is `status: insufficient_evidence`. It carries a worklist in `input_gaps[]`, and never
an `issues[]` entry. The reason is that the code states a condition of the inputs, not a finding about
the review. `gate.py` also sets `submission_ready: false`. `--allow-insufficient` exits `0` while the
report still records the condition. The full flag list, the exit codes, and the issue-code index are in
`references/cli_reference.md`.

## What this does not do

- **It does not pool effect sizes**. It reports each study's estimate with its uncertainty. Use a meta-analysis workflow for a pooled estimate.

- **It does not perform the search for you**. It runs the tools and records the queries, and it refuses to describe a search that nobody executed.

- **It does not decide authorship**. Named human authors decide, verify, and approve. The skill drafts.

- **It does not certify a review**. A `submission_ready: true` report means that the machine checks passed on the recorded inputs. It does not mean that the science is right or that the venue will accept it.

- **It does not cover sources that nobody retrieved**. The evidence base is the set of verified records in `sources.csv`, plus nothing.

- **It does not replace a human pre-submission check**. Run `references/qa_checklist.md` as well as `gate.py`. The gate checks what a machine can check, and the checklist covers the rest.

## Rubric coverage

`eval.md` holds the self-check, with one id per item. `references/qa_checklist.md` holds the full human checklist. This table maps every id to the procedure that implements it.

<!-- ste-allow R1,R2,R3: a markdown table is one layout block; the sentence-length, one-instruction and sentence-count rules do not apply to its cells -->

| Item | What it checks | Implementing procedure. |
|---|---|---|
| MN1 | Scope, question and declared review type. | **Phase 0**; **Purpose**. |
| MN2 | Search and selection, recorded to reproduce. | **Phase 2**; **Phase 3**. |
| MN3 | Every included source verified and complete. | **Phase 3**; **Verification protocol (Phase 3 detail)**. |
| MN4 | Claim integrity. | **Non-negotiable rules**, rules 3 to 5; **Phase 5**. |
| MN5 | Numbers trace to a recorded value. | **Non-negotiable rule 4**; **Phase 4**; **Phase 8**. |
| MN6 | Citation mechanics. | **Phase 8**; **Verification protocol (Phase 3 detail)**. |
| MN7 | Displays from recorded data. | **Phase 7**. |
| MN8 | Language and completeness. | **Phase 6**; **Style, language, and integrity**. |
| MN9 | Integrity and policy. | **Non-negotiable rules**, rules 8 and 9; **Optional advisory classifier (Laya)**. |
| MN10 | No open item is hidden. | **Non-negotiable rule 3**; **Registries and workspace**. |
| MN11 | Exported deliverables complete and consistent. | **Phase 9**; **Failure modes and exit codes**. |

## Escalation and honesty rules for the agent

- If a tool is unavailable, rate-limited, or returns nothing, **say so** and record it. Report `unavailable` distinctly from `empty`. Never fill a gap from memory.

- If the user asks for a citation that they "know exists" and the tool cannot verify it, report exactly what the lookup returned. Offer alternatives found by related-article and citing-article sweeps.

- If the user asks to remove a placeholder, weaken the gate, or skip verification, explain the consequence. Do not silently comply. Record the decision in `UNRESOLVED.md` if the user insists.

- Never write a Methods section that describes a search nobody executed.

- Never state a percentage, an incidence, or an effect size that is not in `sources.csv`.

- Say clearly when the review is a draft with open placeholders, rather than a finished manuscript.

## Bundled files

<!-- ste-allow R1,R2,R3: a markdown table is one layout block; the sentence-length, one-instruction and sentence-count rules do not apply to its cells -->

| File | Use |
|---|---|
| `references/review_methodology.md` | narrative vs systematic vs scoping; SANRA; evidence hierarchy; which claims each design can support |
| `references/search_and_retrieval.md` | MeSH and Boolean per database, filters, dedupe, PRISMA-S reporting, availability logging |
| `references/evidence_ledger.md` | exact schemas for `sources.csv`, `claims.csv`, `search_log.csv`, `prisma_counts.json` |
| `references/citation_and_reference.md` | Vancouver, AMA, APA, and Elsevier rules, DOI and PMID formatting, retraction handling, the secondary-citation ban |
| `references/tables_and_figures.md` | table vs figure choice, evidence and certainty table columns, forest-plot rules, captions, alt text, accessibility |
| `references/medical_language.md` | hedging ladder, causal language, number and unit rules, significance wording, terminology |
| `references/reporting_guidelines.md` | PRISMA 2020 and PRISMA-S, SANRA, MOOSE, GRADE, and the EQUATOR checklists |
| `references/integrity_ai_authorship.md` | ICMJE authorship, AI disclosure wording, plagiarism and self-plagiarism, PHI, predatory outlets, image integrity |
| `references/section_blueprints.md` | paragraph-by-paragraph blueprint for every section, including the structured abstract |
| `references/qa_checklist.md` | final human pre-submission checklist |
| `references/advisory_decision_plan.md` | where the advisory classifier may and may not participate |
| `references/advisory_laya.md` | optional advisory classifier: contract, prompts, file schema, costs, removal |
| `references/cli_reference.md` | every bundled command, input schema, exit code, issue-code index |
| `scripts/_common.py` | shared bounded, offline helpers imported by every command |
| `scripts/_markdown.py` | Markdown to document-model parser shared by the exporters |
| `scripts/_docxout.py` | OOXML writer: Word styles, tables, page numbers, embedded images |
| `scripts/_pdfout.py` | PDF writer: Times metrics, A4 geometry, page furniture |
| `scripts/_pdfrender.py` | PDF layout: headings, runs, ruled tables, vector screening figure |
| `scripts/_htmlout.py` | print-ready HTML with clickable citations and embedded SVG |
| `scripts/init_review.py` | create the workspace and refuse to overwrite one |
| `scripts/validate_sources.py` | check the source ledger against the required fields |
| `scripts/make_evidence_table.py` | build an evidence or certainty table from `sources.csv` |
| `scripts/make_prisma_flow.py` | draw the screening flow, and fail when the arithmetic does not balance |
| `scripts/build_reference_list.py` | renumber citations and refuse an unverified entry |
| `scripts/audit_citations.py` | join `claims.csv` to the manuscript and to `sources.csv` |
| `scripts/check_numbers.py` | recompute n/N, CI, and ranges from the ledgers |
| `scripts/lint_manuscript.py` | section completeness and causal-language checks |
| `scripts/gate.py` | aggregate every audit into one pass-or-fail report |
| `scripts/export_document.py` | write DOCX, PDF, and print-ready HTML |
| `scripts/selftest.sh` | the offline regression harness |
| `assets/topic_intake.md` | intake questions with defaults |
| `assets/manuscript_scaffold.md` | section skeleton with marker placeholders |
| `assets/source_ledger_template.csv` | empty `sources.csv` with the exact header |
| `assets/claim_ledger_template.csv` | empty `claims.csv` with the exact header |
| `assets/search_log_template.csv` | empty `search_log.csv` with the exact header |
| `assets/prisma_counts_template.json` | counts file with the arithmetic documented |
| `assets/table_templates.md` | ready Markdown skeletons for the standard review tables |

## Commands at a glance

```bash
# 0. scope (fill with the user) -> 1. scaffold
python3 scripts/init_review.py --out-dir ./review-topic --document-id topic --title "Working title"
# 3. verify what you plan to cite
python3 scripts/validate_sources.py sources.csv --require-included
# 8. number the citations, then fail loudly if anything is unverified
python3 scripts/build_reference_list.py draft.md sources.csv claims.csv --style vancouver --out-dir final/
python3 scripts/audit_citations.py final/manuscript_cited.md claims.csv sources.csv --final
python3 scripts/check_numbers.py final/manuscript_cited.md
python3 scripts/lint_manuscript.py final/manuscript_cited.md --sections
python3 scripts/gate.py --dir .
# 9. export DOCX + PDF + print-ready HTML and confirm delivery
python3 scripts/export_document.py final/manuscript_cited.md --workspace . --out-dir final \
  --references final/references.md --append tables/table1.md --append tables/table2.md \
  --figure prisma_counts.json --title "<title>" --footer-left "<running title>"
python3 scripts/gate.py --dir . --require-exports
```

Scripts run from the skill directory, and they need no third-party package.

## Regression tests

`scripts/selftest.sh` is the offline regression harness. It runs every bundled CLI against fixtures. It
asserts **both** the PASS path and the FAIL path of each gate, because a gate that cannot fail is not a
gate. It then exercises the whole chain: `build_reference_list.py`, then `export_document.py`, then the
`gate.py` PASS. Run it after any change.

```bash
bash scripts/selftest.sh     # RESULT: 30 passed, 0 failed
```

The harness needs only `python3` and `bash`. It needs no network and no third-party package, and it is
location-independent, because it resolves the skill root from its own path.
