---
name: medical-narrative-review
description: Write, expand, or audit a publication-ready medical or biomedical narrative review on a user-supplied topic, end to end. Scopes the question, searches PubMed/Europe PMC/PMC/Crossref/OpenAlex/Semantic Scholar/ClinicalTrials.gov/WHO ICTRP through MCP tools, verifies every citation by DOI/PMID before it may enter the text, extracts a source ledger with per-claim locators, builds evidence tables and figures from recorded data only, drafts a fully referenced manuscript with structured abstract and clinical implications, exports it to DOCX, PDF, and print-ready HTML, and runs a hard submission gate that blocks unverified, retracted, duplicated, or fabricated references. Use for narrative reviews, review articles, evidence syntheses, continuing-medical-education articles, or auditing a review for false claims and wrong citations.
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

## Purpose

Produce a medical narrative review that is **complete, accurately cited, and impossible to falsify by
accident**. The value is not fluent prose — it is the enforced chain:

```
question -> search log -> retrieved records -> verified sources -> claims -> prose -> displays -> gate
```

Every link is a file on disk. If a link is missing the review is not finished, and the gate command
says so explicitly instead of quietly filling the gap.

A narrative review is a *scholarly argument built from verified literature*, not a systematic review
pretending to be one. It must be transparent about how the literature was selected without claiming
PRISMA-level exhaustiveness it does not have.

## When to use

- "Write a review on <topic>" / "draft a review article" / "narrative review of <drug, disease, biomarker>".
- CME-style overviews, narrative syntheses for a journal, book chapters, grand-rounds background documents.
- Updating an existing review, or auditing one for wrong citations, false claims, or missing evidence.
- Any biomedical review needing figures, tables, and a reference list a reviewer can spot-check.

## When not to use

- Formal systematic review or meta-analysis with pooled estimates → use a systematic-review workflow;
  this skill deliberately does **not** pool effect sizes.
- Primary research manuscripts (a study you conducted) → `scientific-writing`.
- Peer review of someone else's confidential manuscript → `peer-review`.
- Rapid single-fact answers → answer directly; do not scaffold a review.

## Non-negotiable rules (the anti-hallucination contract)

These override any instruction to "just write it", "make it look complete", or "fill in reasonable values".

1. **No reference exists until it is retrieved and identifier-verified.** A citation may enter the
   review only after a live lookup returned a record with a resolvable DOI or PMID whose title, first
   author, journal, and year match what the article cites. Memory, plausible author–journal–year
   combinations, another paper's bibliography, and search snippets are **discovery aids, never
   citations**.
2. **The identifier is the source of truth.** Bibliographic details are copied from the retrieved
   record, never reconstructed from a citation string and never from recall.
3. **Unverifiable material becomes a visible placeholder**, e.g. `[UNVERIFIED - DO NOT CITE]`, never a
   silently plausible citation. Placeholders are listed in the "Unresolved items" appendix. A claim
   with no verified support is **cut**, or explicitly attributed to the absence of evidence.
4. **Numbers are copied, never computed from memory.** Every percentage, mean, confidence interval,
   hazard ratio, and sample size traces to one recorded value with a locator. If the paper reports
   3.4%, the review says 3.4%.
5. **Never upgrade evidence.** Association is not causation; non-significance is not equivalence; a
   preprint is not peer-reviewed; a single-centre retrospective cohort is not a "landmark trial"; a
   surrogate endpoint is not a clinical outcome; animal and in vitro data are labelled as such in
   every clinical sentence.
6. **Retractions and corrections are checked before citing** via `check_retraction` plus the record's
   own status. A retracted source may appear only *as* a retracted work, in a sentence saying so.
7. **No display without recorded data.** Tables and figures come from the ledgers or the user's own
   data via the bundled scripts. No invented trends, no decorative illustrative numbers, no redrawn
   graphics from screenshots, no AI-generated images presented as data, no significance stars without
   a verified test.
8. **No PHI, ever.** No patient identifiers, dates of birth, medical record or accession numbers, or
   unpublished third-party data in any file or prompt. Redaction requires user confirmation;
   "I removed the names" is not de-identification.
9. **AI is not an author.** The skill drafts; named human authors decide, verify, and approve, and the
   AI-use disclosure is written per the target journal's current policy.
10. **The gate is authoritative.** A review that fails `scripts/gate.py` is not submission-ready,
    regardless of how good the prose is. Report failures plainly, with issue codes.

## Workflow

Work phase by phase. Do not start Phase 6 (drafting) before Phases 1–5 have left artifacts on disk.
Ask only the questions needed to unblock the current phase (defaults in `assets/topic_intake.md`);
mark unknowns unresolved rather than guessing.

### Phase 0 — Intake and scope lock

Record: topic and exact **PICO or PEO** framing; target journal/venue and its current author
instructions; article type and word/table/figure limits; citation style; audience and clinical
setting; review time window; languages allowed; designs to include; explicit out-of-scope list. Write
these into `scope.md` using `assets/topic_intake.md`. If the user gives only a topic, propose a default
PICO, state the assumption, and proceed — do not stall.

### Phase 1 — Scaffold

```bash
python3 scripts/init_review.py --out-dir ./review-<slug> --document-id <slug> --title "<working title>"
```

Creates the full workspace (below) and refuses to overwrite an existing directory.

### Phase 2 — Structured search (record everything, including failures)

Run `plan_search_query` first, then search at least three independent sources and keep the raw counts.
Use the MCP tools in this order of preference:

| Need | Tool |
|---|---|
| Broad multi-source sweep, retraction screening, ID conversion | `search_papers`, `check_retraction`, `convert_paper_ids`, `get_crossref_paper_by_doi` |
| Biomedical primary index | `search_pubmed`, `search_pmc`, `search_europepmc`, `search_bookshelf` |
| Preprints (must be labelled as such) | `search_medrxiv`, `search_biorxiv` |
| Bibliographic/DOI-level records | `search_crossref`, `search_openalex`, `search_semantic`, `search_doaj` |
| Trials and registries | `search_clinicaltrials`, `search_ictrp`, `search_ctis` |
| Metrics, related and citing work | `get_citation_metrics`, `get_related_articles`, `get_citing_articles` |
| Regex/filtered evidence-grade search | `academic-search__search_papers`, `academic-search__search_by_author` |
| Consensus and position statements | `consensus__search` |
| MeSH term control | `get_mesh_details` |

Rules: run the same concept blocks across databases; record the **exact query string, database, date,
filters, and hit count** in `search_log.csv`; record per-source availability (`empty` vs `unavailable`)
so a rate-limited database is never reported as "no evidence exists"; log every retrieved record in
`sources.csv`. Syntax, MeSH strategy, deduplication, and PRISMA-S reporting:
`references/search_and_retrieval.md`.

### Phase 3 — Screen and verify

Deduplicate by DOI, then PMID, then normalized title+year. Record include/exclude with a reason for
every record. Each record ends in one of four states: `included` (evidence base), `cited_for_context`
(verified and citable but deliberately outside the evidence base, such as an out-of-scope modelling
study), `excluded` (with a specific reason), or `pending`. Every citable record (`included` or
`cited_for_context`) must be verified with `verification_status=verified`, a named `verifier`, a
`verified_date`, a `locator`, and a `retraction_status`. This is where reviews normally fail; do not
rush it.

### Phase 4 — Extraction

For each verified source, extract into `sources.csv`: design, population, intervention/exposure,
comparator, outcomes, follow-up, size, effect estimates with uncertainty, and the exact locator for
each value. Missing items get the literal `not_reported` — never a blank that could later read as
zero, and never an inferred value.

### Phase 5 — Claim ledger and outline

Decompose the review into atomic claims; each claim gets a `C` ID, section, kind, direction
(`supports`/`refutes`/`mixed`/`neutral`), certainty, and one or more **verified** `S` IDs. Build the
thematic outline from *claim clusters*, not from a list of papers. Then:

```bash
python3 scripts/validate_sources.py sources.csv --require-included
```


### Phase 6 — Draft with traceable markers

Draft in Markdown using `assets/manuscript_scaffold.md` and `references/section_blueprints.md`. Tag
every factual or numeric sentence:

```text
Chemotherapy plus pembrolizumab improved pathological complete response ... [claim:C014] [src:S006,S011]
```

Follow `references/medical_language.md` (hedging, causal verbs, units, drug naming) and
`references/integrity_ai_authorship.md`.

Markers are checked per paragraph: a paragraph that contains a number, percentage, effect estimate,
or significance statement must carry a claim marker somewhere in that paragraph. Prose may be wrapped
normally — one sentence per line is still the cleanest habit, because it keeps markers next to the
numbers they support and makes the audit location exact.

### Phase 7 — Displays

Build tables and figures only from the ledgers and the user's data:

```bash
python3 scripts/make_evidence_table.py sources.csv --group-by design --style evidence-table --out tables/table1.md
python3 scripts/make_evidence_table.py sources.csv --group-by certainty --style certainty-of-evidence --out tables/table2.md
python3 scripts/make_prisma_flow.py prisma_counts.json --out-dir figures/
```

`make_prisma_flow.py` emits Mermaid and standalone SVG and **fails** if the flow arithmetic does not
balance, so the diagram can never disagree with the recorded counts. Panel, caption, alt-text,
accessibility, and prohibited-decoration rules: `references/tables_and_figures.md`.

### Phase 8 — Finalize numbering and run the gate

```bash
python3 scripts/build_reference_list.py draft.md sources.csv claims.csv --style vancouver --out-dir final/
python3 scripts/audit_citations.py final/manuscript_cited.md claims.csv sources.csv --final
python3 scripts/check_numbers.py final/manuscript_cited.md
python3 scripts/lint_manuscript.py final/manuscript_cited.md --sections
python3 scripts/gate.py --dir . --style vancouver
```

`build_reference_list.py` renumbers citations in first-appearance order, writes `final/references.md`
and `final/citation_map.csv`, and **refuses** to emit a reference list containing any source that is
unverified, retracted, excluded, or missing an identifier. `gate.py` aggregates every audit into one
pass/fail report; every `error` issue is a blocker — fix it and re-run until the gate passes.

### Phase 9 — Export the deliverables

```bash
python3 scripts/export_document.py final/manuscript_cited.md \
  --workspace . --out-dir final \
  --references final/references.md \
  --append tables/table1.md --append tables/table2.md \
  --figure prisma_counts.json \
  --title "<review title>" --citation-style vancouver --footer-left "<short running title>"
```

Produces, from the same final Markdown and with no third-party packages:

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

- The PDF draws the figure itself, so it never depends on a rasteriser. The DOCX embeds a PNG: supply
  one, or let the tool convert the SVG locally with any of `rsvg-convert`, `inkscape`, `magick`, or
  macOS `qlmanage`. If no rasteriser exists, the DOCX carries a labelled placeholder and the SVG is
  delivered beside it — it never pretends a missing figure is present.
- Exports are regenerated on every run (they are derived artifacts), so re-export after any edit.
- Page numbers come from the Word/PDF engine. When printing the HTML from a browser, enable the
  browser's header and footer to get page numbers.

## Verification protocol (Phase 3 detail)

For each candidate source, in order:

1. Retrieve the record by DOI (`get_crossref_paper_by_doi`) or PMID and confirm it exists.
2. Confirm **title, first author, container, year, volume/pages** match the citing sentence.
3. Confirm publication type and peer-review status; flag preprints, editorials, letters, and
   conference abstracts, which carry different evidentiary weight.
4. Run `check_retraction` on the DOI and record `retraction_status`.
5. Where access is available, open the source and confirm it supports the claim's *direction,
   population, intervention, comparator, outcome, time point, and magnitude* — not merely its topic.
6. Record the exact locator (section, page, table, figure, or `abstract_only` when that is all that
   exists).
7. Set `verification_status=verified`, `verifier=<name>`, `verified_date=<ISO date>`.

If a lookup fails or is unavailable, record `verification_status=unverified` and keep the item out of
the prose. Never promote an unverified item to make the gate pass — the gate exists to catch exactly that.

### How to read the tool responses

These behaviours were confirmed against the live MCP server and they matter:

- **An unknown DOI returns an empty object `{}` with no error flag.** An empty response means the DOI
  did not resolve: record `verification_status=failed` and never cite it. Treating `{}` as success is
  the single easiest way to fabricate a reference.
- **Compare the record, not your memory.** A DOI and a title can both look right and still belong to
  different papers. Always compare title, first author, container, year, volume/issue/pages from the
  returned record against the sentence being written. A mismatch means the citation is wrong even if
  the DOI resolves.
- **`check_retraction` returns loosely matched notices.** The `notices` list includes items whose
  `targets_this_doi` is `false`; only `is_retracted: true` or a notice with `targets_this_doi: true`
  means the source itself is retracted. Read `sources_checked` and `sources_unavailable`: if a source
  was unavailable, the retraction status is `not_checked`, not `clear`.
- **Author name formats differ by source.** Crossref returns full given names separated by semicolons
  (`Leena Gandhi; Delvys Rodríguez-Abreu; ...`), which must be converted to the ledger's
  `Surname AB` form for NLM/Vancouver output; PubMed returns initials directly. Prefer PubMed for the
  author string and Crossref (or the DOI record) for volume, issue, and pages. Record the conversion
  you performed rather than inventing initials.

## Registries and workspace

`init_review.py` creates:

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

Ledger schemas, field by field: `references/evidence_ledger.md`. The ledgers contain **metadata and
the authors' own text only** — never source documents, patient data, or third-party unpublished content.

## Two ledgers, two directions

- `sources.csv` answers *"is this citation real, verified, and correctly described?"*
- `claims.csv` answers *"is this sentence supported, by what, and how strongly?"*

The audit joins them: a claim marker whose sources are unverified is an error; a source cited in the
manuscript but absent from the ledger is an error; a claim registered but never used is a warning to
resolve before submission.

## Optional advisory classifier (Laya)

An optional, opt-in local decision engine can propose judgments about *text* — hedging and
certainty observations, theme suggestions. It is **advisory only and can never change a gate verdict**:
its findings appear as `info`-severity `ADVISORY_*` codes, and no model output may set
`verification_status`, `retraction_status`, `inclusion_status`, or any error. The ten deterministic
commands never import it, so the pipeline works identically with it absent, uninstalled, or wrong.

**Where it may and may not participate is a written policy, not a preference**:
`references/advisory_decision_plan.md`. In short — verification, retraction, inclusion, numbers,
references, PRISMA arithmetic, and the gate verdict are **structurally forbidden** (a text classifier
has no retrieval and no knowledge base, so it cannot decide them), while each candidate text-judgment
stage must clear a measured bar on at least 50 labelled records before it is offered at all.

Measured so far on this machine: the causality axis **missed** the worst overclaim in a six-sentence
probe (0.041, the lowest score in the set); the hedging axis **did not separate** high- from
low-certainty claims across nine real sentences; `publication_type` classification scored **1/3**,
defaulting to the generic label; and the shipped checkpoint's own library warns that its confidence
values are **uncalibrated**. Treat it as a hint generator, never as a source of accuracy.

Full contract, prompts, schemas, costs, and removal steps: `references/advisory_laya.md`.

## Reporting standards

Narrative reviews are not PRISMA-bound, but they must be transparent. Declare in Methods which standard
was followed and report **SANRA** items (justification, aims, search description, referencing quality,
scientific reasoning, presentation of data) in the appendix. Where the review contains a systematic
search component, report **PRISMA 2020** items 1–16 and **PRISMA-S** for the search. GRADE-style
certainty language, MOOSE for observational syntheses, and EQUATOR routing:
`references/reporting_guidelines.md`.


## Style, language, and integrity

- Hedged, precise, non-promotional prose; no marketing adjectives. "Novel", "breakthrough",
  "revolutionary" appear only inside a verified quotation.
- Active causal verbs only where the cited design supports causation; otherwise "was associated with",
  "cohort studies suggest".
- Units, denominators, and uncertainty always explicit; `p` values reported as the source reported
  them; no bare "significant" without the test and comparison.
- Spell out each abbreviation at first use in the abstract, the body, and every table/figure caption.
- Drug names by INN (generic), with one brand-name mention where clinically relevant; devices and
  assays by manufacturer and version.
- No verbatim quotation longer than ~25 words and no text reuse from any source; paraphrase in the
  authors' own words with attribution.
- AI-use disclosure, authorship criteria, and conflicts follow the target journal's current policy.

## Bundled files

| File | Use |
|---|---|
| `references/review_methodology.md` | narrative vs systematic vs scoping; SANRA; evidence hierarchy; which claims each design can support |
| `references/search_and_retrieval.md` | MeSH/Boolean per database, filters, dedupe, PRISMA-S reporting, availability logging |
| `references/evidence_ledger.md` | exact schemas for `sources.csv`, `claims.csv`, `search_log.csv`, `prisma_counts.json` |
| `references/citation_and_reference.md` | Vancouver/AMA/APA/Elsevier rules, DOI/PMID formatting, retraction handling, secondary-citation ban |
| `references/tables_and_figures.md` | table vs figure choice, evidence and certainty table columns, forest-plot rules, captions, alt text, accessibility |
| `references/medical_language.md` | hedging ladder, causal language, number and unit rules, significance wording, terminology |
| `references/reporting_guidelines.md` | PRISMA 2020/S, SANRA, MOOSE, GRADE, CONSORT/STROBE/CARE pointers, EQUATOR |
| `references/integrity_ai_authorship.md` | ICMJE authorship, AI disclosure wording, plagiarism/self-plagiarism, PHI, predatory outlets, image integrity |
| `references/section_blueprints.md` | paragraph-by-paragraph blueprint for every section, including the structured abstract |
| `references/qa_checklist.md` | final human pre-submission checklist |
| `references/advisory_laya.md` | optional advisory classifier: contract, prompts, file schema, costs, removal |
| `references/cli_reference.md` | every bundled command, input schema, exit code, issue-code index |
| `scripts/_common.py` | shared bounded, offline helpers imported by every command |
| `scripts/_markdown.py` | Markdown to document-model parser shared by the exporters |
| `scripts/_docxout.py` | OOXML writer: Word styles, tables, page numbers, embedded images |
| `scripts/_pdfout.py` | PDF writer: Times metrics, A4 geometry, page furniture |
| `scripts/_pdfrender.py` | PDF layout: headings, runs, ruled tables, vector screening figure |
| `scripts/_htmlout.py` | print-ready HTML with clickable citations and embedded SVG |
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

Every script prints a JSON report with `status`, `summary`, and `issues[]` carrying stable codes; the
exit code is `1` when any `error`-severity issue is present. Full flag list and issue-code index:
`references/cli_reference.md`. Scripts run from the skill directory and need no third-party packages.

## Failure modes this skill is designed to prevent

| Failure | Prevented by |
|---|---|
| Fabricated or wrong reference | identifier verification before citation; `build_reference_list.py` refusal; `audit_citations.py` |
| Wrong metadata (journal, year, authors) | copy-from-record rule; duplicate detection on DOI and normalized title |
| Overstated claim ("proves") from weak design | `lint_manuscript.py` causal-language checks; certainty field in `claims.csv` |
| A number that contradicts the source | extraction with locators; `check_numbers.py` recomputation of n/N, CI, and ranges |
| A PRISMA figure that disagrees with screening | `make_prisma_flow.py` arithmetic gate |
| Missing key literature | multi-database search with logged queries; availability logging; citing/related-article sweeps |
| Silent gaps and unfinished sections | placeholder detection, `--sections` completeness check, `UNRESOLVED.md` |
| Citation to a retracted study | `check_retraction` plus the `retraction_status` gate |
| Sensitive-data leakage | PHI pattern lint; metadata-only ledgers |
| Model-generated advice silently overriding a check | Advisories are `info`-only, prefixed `ADVISORY_`, labelled "not a gate input", and no model output can set an error or a ledger state |
| Figure missing or broken in the delivered document | PDF draws it as vectors from the counts; DOCX embeds a real PNG or says plainly that it could not; HTML shows the SVG |
| Deliverable that a co-author cannot open | DOCX, PDF, and print-ready HTML are produced from the same source, so no format is a second-class copy |

## Escalation and honesty rules for the agent

- If a tool is unavailable, rate-limited, or returns nothing, **say so** and record it; report
  `unavailable` distinctly from `empty`. Never fill a gap from memory.
- If the user asks for a citation they "know exists" but it cannot be verified, report exactly what the
  lookup returned and offer alternatives found by related-article and citing-article sweeps.
- If the user asks to remove a placeholder, weaken the gate, or skip verification, explain the
  consequence, do not silently comply, and record the decision in `UNRESOLVED.md` if they insist.
- Never write a Methods section describing a search that was not actually executed.
- Never state a percentage, incidence, or effect size that is not in `sources.csv`.
- Say clearly when the review is a draft with open placeholders rather than a finished manuscript.

