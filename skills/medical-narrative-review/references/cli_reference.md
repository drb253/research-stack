# Local CLI Reference

All bundled commands use only the Python standard library (3.9+). They:

- accept explicit UTF-8 JSON, CSV, or Markdown files;
- reject symbolic-link inputs and cap file size, rows, fields, and JSON depth;
- make no network calls, read no environment variables, load no pickle, and run no dynamic code;
- never rewrite a source document and never edit a ledger in place;
- report issues as `severity`, `code`, `location`, `item_id`, `detail` — never as manuscript text.

Run them from the skill directory:

```bash
cd <skills-dir>/medical-narrative-review
python3 scripts/validate_sources.py <workspace>/sources.csv --strict
```

Exit code is `0` when no `error`-severity issue exists, `1` otherwise. Every command prints a JSON
object with `tool`, `status`, `summary`, and `issues`.

## `init_review.py` — scaffold a workspace

```bash
python3 scripts/init_review.py --out-dir ./review-sepsis --document-id sepsis \
  --title "Biomarkers of sepsis in the emergency department" \
  --review-type narrative_with_systematic_search --style vancouver
```

Creates `scope.md`, `README.md`, `UNRESOLVED.md`, `draft.md`, `sources.csv`, `claims.csv`,
`search_log.csv`, `prisma_counts.json`, and the `figures/ tables/ final/` folders. The output
directory must not exist. `--review-type` accepts `narrative`,
`narrative_with_systematic_search`, or `scoping_informed`; `--style` accepts `vancouver`, `ama`,
`apa`, or `elsevier`.

## `validate_sources.py` — the verification gate

```bash
python3 scripts/validate_sources.py sources.csv \
  --strict --require-included --min-included 15 --require-clear-retraction
```

Checks the column schema, identifier formats, verification requirements, retraction status,
inclusion reasons, duplicate detection by DOI and by normalized title+year, PHI-like patterns, and
extraction completeness. `--strict` escalates missing extraction fields to errors. The summary
reports counts by publication type, design, theme, verification, and retraction status.

Issue codes: `INVALID_SOURCE_ID`, `MISSING_TITLE`, `MISSING_AUTHORS`, `MISSING_CONTAINER`,
`INVALID_YEAR`, `YEAR_OUT_OF_RANGE`, `MALFORMED_DOI`, `MALFORMED_PMID`, `MALFORMED_PMCID`,
`INVALID_PUBLICATION_TYPE`, `INVALID_PEER_REVIEWED`, `PEER_REVIEW_STATUS_UNKNOWN`,
`INVALID_VERIFICATION_STATUS`, `INVALID_INCLUSION_STATUS`, `INVALID_RETRACTION_STATUS`,
`INVALID_RETRIEVAL_STATUS`, `INCLUDED_WITHOUT_IDENTIFIER`, `RETRIEVED_WITHOUT_IDENTIFIER`,
`VERIFIED_WITHOUT_VERIFIER`, `VERIFIED_WITHOUT_DATE`, `VERIFIED_DATE_IN_FUTURE`,
`VERIFIED_WITHOUT_LOCATOR`, `VERIFIED_WITHOUT_IDENTIFIER`, `UNVERIFIED_SOURCE_INCLUDED`,
`RETRACTION_NOT_CHECKED`, `RETRACTED_SOURCE_INCLUDED`, `RETRACTED_RETAINED_FOR_CONTEXT`,
`EXPRESSION_OF_CONCERN`, `PREPRINT_INCLUDED_LABEL_REQUIRED`, `ABSTRACT_INCLUDED_QUALIFY_IN_TEXT`,
`EXCLUDED_WITHOUT_REASON`, `PENDING_INCLUSION_DECISION`, `MISSING_EXTRACTION_FIELD`,
`AMBIGUOUS_EXTRACTION_VALUE`, `INVALID_N_PARTICIPANTS`, `EFFECT_ESTIMATE_WITHOUT_NUMBER`,
`MISSING_PAGES_FOR_JOURNAL_ARTICLE`, `MISSING_VOLUME_AND_ISSUE`, `POSSIBLE_PHI_*`,
`DUPLICATE_DOI`, `DUPLICATE_SOURCE`, `POSSIBLE_DUPLICATE_TITLE`, `NO_INCLUDED_SOURCES`,
`BELOW_MIN_INCLUDED_SOURCES`, `INCLUDED_WITHOUT_CLEAR_RETRACTION_CHECK`, `EMPTY_LEDGER`,
`EXTRA_COLUMN`, `INVALID_INPUT`.

## `audit_citations.py` — claim, citation, and numbering audit

```bash
python3 scripts/audit_citations.py draft.md claims.csv sources.csv --strict
python3 scripts/audit_citations.py final/manuscript_cited.md claims.csv sources.csv \
  --final --references final/references.md
```

Draft mode joins every `[claim:Cxxx] [src:Sxxx]` marker to both ledgers. The quantitative check is
**paragraph-level**: prose may be wrapped across lines, but a paragraph containing a number, a
percentage, an effect estimate, or a significance statement must carry a claim marker somewhere in
that paragraph (`UNTAGGED_QUANTITATIVE_CONTENT`). Lines starting with `#`, `|`, `>`, or a code fence
are excluded, because headings and generated tables are not prose claims. Final mode checks numbered
citations against the reference list: numbering gaps, out-of-range numbers, uncited references,
leftover draft markers, placeholders, and first-appearance order.

## `build_reference_list.py` — number citations, render references

```bash
python3 scripts/build_reference_list.py draft.md sources.csv claims.csv \
  --style vancouver --out-dir final/
```

Writes `final/references.md`, `final/manuscript_cited.md`, and `final/citation_map.csv`. Nothing is
written when any cited source is unknown, unverified, excluded, retracted, or lacks a DOI/PMID.
`--check-only` prints the plan without writing. `--allow-placeholders` downgrades the placeholder
error to a warning (never use it for a submission build).

Issue codes: `CITED_SOURCE_NOT_IN_LEDGER`, `CITED_SOURCE_NOT_VERIFIED`,
`CITED_SOURCE_NOT_INCLUDED`, `CITED_SOURCE_RETRACTED`, `CITED_SOURCE_EXPRESSION_OF_CONCERN`,
`CITED_SOURCE_RETRACTION_UNCHECKED`, `CITED_SOURCE_WITHOUT_IDENTIFIER`,
`DUPLICATE_DOI_SHARES_CITATION_NUMBER`, `DUPLICATE_SOURCE_ID_IN_LEDGER`,
`PLACEHOLDERS_PRESENT`, `NO_SOURCE_MARKERS_FOUND`, `MISSING_CONTAINER_IN_REFERENCE`,
`MISSING_YEAR_IN_REFERENCE`, `MISSING_VOLUME_IN_REFERENCE`, `MISSING_PAGES_IN_REFERENCE`,
`AUTHOR_LIST_TRUNCATED_FOR_APA`, `AUTHOR_FORMAT_UNEXPECTED_FOR_APA`.

Citation rendering: `vancouver` and `ama` differ in author truncation (first 6 vs first 3, then
`et al`); `apa` converts `Surname AB` to `Surname, A. B.` and flags truncated author lists, because
APA requires the complete author list and a ledger that records `et al.` cannot satisfy it without
a citation manager; `elsevier` uses `Journal Year Volume(Issue):Pages. https://doi.org/...`.

## `check_numbers.py` — numeric integrity

```bash
python3 scripts/check_numbers.py final/manuscript_cited.md
```

Recomputes percentages from `n/N (p%)` pairs, verifies that confidence intervals contain their
point estimates, checks significance wording against reported p values, flags percentages above
100, detects effect-value drift within one claim, and notes mixed unit systems.

Issue codes: `PERCENTAGE_MISMATCH`, `ZERO_DENOMINATOR`, `NUMERATOR_EXCEEDS_DENOMINATOR`,
`CI_BOUNDS_INVERTED`, `CI_DOES_NOT_CONTAIN_ESTIMATE`, `PERCENTAGE_OUT_OF_RANGE`,
`SIGNIFICANCE_WITHOUT_STATISTIC`, `SIGNIFICANCE_WITH_NON_SIGNIFICANT_P`,
`NON_SIGNIFICANCE_WITH_SIGNIFICANT_P`, `CONTRADICTORY_SIGNIFICANCE_WORDING`,
`P_VALUE_REPORTED_AS_ZERO`, `P_VALUE_BELOW_REPORTING_FLOOR`, `EFFECT_VALUE_DRIFT_WITHIN_CLAIM`,
`MULTIPLE_PERCENTAGES_IN_CLAIM`, `MIXED_UNIT_SYSTEMS`.

`EFFECT_VALUE_DRIFT_WITHIN_CLAIM` is the abstract-versus-body check: if one claim ID carries
`HR 0.49` on one line and `HR 0.58` on another, that is an error, not a rounding difference.

## `make_evidence_table.py` — tables from the ledger

```bash
python3 scripts/make_evidence_table.py sources.csv --style evidence-table \
  --group-by theme --out tables/table1.md
python3 scripts/make_evidence_table.py sources.csv --style certainty-of-evidence \
  --claims claims.csv --out tables/table2.md
python3 scripts/make_evidence_table.py sources.csv --style excluded-log --out tables/table3.md
```

Styles: `evidence-table`, `characteristics`, `certainty-of-evidence`, `excluded-log`.
`--group-by` accepts `none`, `theme`, `study_design`, `publication_type`, `year`, `peer_reviewed`.
Missing values print as `not_reported`, never as a blank or a zero. The command refuses to include
an unverified or retracted source (`TABLE_SOURCE_NOT_VERIFIED`, `TABLE_SOURCE_RETRACTED`) and
warns about sources whose inclusion is still undecided (`SOURCE_NOT_YET_DECIDED`).

## `make_prisma_flow.py` — screening flow figure

```bash
python3 scripts/make_prisma_flow.py prisma_counts.json --check-only
python3 scripts/make_prisma_flow.py prisma_counts.json --out-dir figures/
```

Writes `prisma_flow.svg`, `prisma_flow.mmd`, and `prisma_flow.md`. Refuses to write when the flow
arithmetic does not balance (`FLOW_ARITHMETIC_MISMATCH`), when no records are identified
(`NO_RECORDS_IDENTIFIED`), or when more studies are included than assessed
(`MORE_INCLUDED_THAN_ASSESSED`). `--out-dir` is optional with `--check-only`.

## `lint_manuscript.py` — prose and completeness lint

```bash
python3 scripts/lint_manuscript.py final/manuscript_cited.md --sections --max-word-count 4500
python3 scripts/lint_manuscript.py final/manuscript_cited.md --sections --advisory advisory.json
```

Issue codes: `UNRESOLVED_PLACEHOLDER`, `POSSIBLE_PHI_*`, `OVERCLAIMING_LANGUAGE`,
`ABSOLUTE_LANGUAGE`, `CAUSAL_CLAIM_WITHOUT_HEDGE`, `VERY_LONG_SENTENCE`,
`TABLE_REFERENCE_WITHOUT_CAPTION`, `FIGURE_REFERENCE_WITHOUT_CAPTION`,
`CAPTION_NEVER_REFERENCED_IN_TEXT`, `MISSING_SECTION`, `MISSING_DECLARATION`,
`CITATION_IN_ABSTRACT`, `CITATION_IN_CONCLUSIONS`, `ABBREVIATION_NOT_DEFINED`,
`WORD_COUNT_EXCEEDED`. `--allow-abbrev ABBR` (repeatable) suppresses a definition warning for a
term the target journal expects unexpanded. `--sections` requires the standard sections plus a
declarations block covering funding, conflicts, author contributions, data availability, and AI use.

**`--advisory FILE`** consumes an optional JSON of model-generated findings (see
`references/advisory_laya.md`). Every finding is reported as `info` with an `ADVISORY_*` code whose
detail text ends "advisory, model-generated, not a gate input". A malformed, unreadable, or
wrongly-shaped file produces `ADVISORY_FILE_UNREADABLE` as a warning and is otherwise ignored: an
optional input can never block a submission. `gate.py` passes this flag automatically when
`advisory.json` exists in the workspace, so the findings appear in `GATE_REPORT.json` under
`checks[].advisories` without ever affecting `submission_ready`.

## `gate.py` — the submission gate

```bash
python3 scripts/gate.py --dir . --style vancouver --require-exports
```

Runs the source validator, both citation audits, the numeric check, the prose lint, and the
screening-flow check, writes `GATE_REPORT.json`, and prints one verdict with a per-check table.
`submission_ready` is `true` only when every check passes and `final/manuscript_cited.md` exists.
`--skip-final` allows a pre-finalisation run. `--require-exports` makes a missing DOCX/PDF/HTML export
an error rather than an informational note, which is what you want before sending the review to
co-authors. `CHECK_UNAVAILABLE` means a bundled script could not be executed — treat it as a failure,
not as a pass.

## `export_document.py` — DOCX, PDF, and print-ready HTML

```bash
python3 scripts/export_document.py final/manuscript_cited.md \
  --workspace . --out-dir final \
  --references final/references.md \
  --append tables/table1.md --append tables/table2.md \
  --figure prisma_counts.json \
  --title "Review title" --citation-style vancouver --footer-left "Short running title"
```

One command, three deliverables from the same final Markdown. No pandoc, no LibreOffice, no
third-party packages: the DOCX is hand-written OOXML, the PDF is written directly, and the HTML is
plain text with print CSS. Files are overwritten on each run because they are derived artifacts;
nothing else in the workspace is touched.

| Flag | Effect |
|---|---|
| `--format docx,pdf,html` | choose a subset (`all` is the default) |
| `--append FILE` | append extra Markdown, typically generated tables (repeatable) |
| `--figure prisma_counts.json` | PDF draws the screening flow as vectors; HTML embeds the SVG; DOCX looks for a PNG |
| `--no-rasterise` | skip SVG to PNG conversion for the DOCX figure |
| `--references FILE` | appended under a `References` heading that starts a new page |
| `--title`, `--author`, `--footer-left` | document metadata and the running footer |

Figure handling, in order of preference: an existing PNG or JPEG beside the SVG is embedded; otherwise
the SVG is converted locally with `rsvg-convert`, `inkscape`, `magick`, `convert`, or macOS `qlmanage`;
otherwise the DOCX carries a labelled placeholder naming the figure file. The report says which path
was used, and an `EXPORT_NOTE` issue records it.

Report fields worth reading: `images_embedded`, `tables`, `pages` (PDF), `reference_entries` (HTML),
and `substituted_characters`, which lists any character the PDF's standard fonts could not represent
(for example a rare mathematical symbol) so it can be rewritten rather than silently replaced.

The helper modules (`_markdown.py`, `_docxout.py`, `_pdfout.py`, `_pdfrender.py`, `_htmlout.py`) are
implementation details of this command; they are imported, not run directly.

leftover draft markers, placeholders, and first-appearance order.

Issue codes: `INVALID_CLAIM_ID`, `DUPLICATE_CLAIM_ID`, `INVALID_CLAIM_KIND`, `INVALID_DIRECTION`,
`INVALID_CERTAINTY`, `INVALID_ANALYSIS_INTENT`, `INVALID_CLAIM_STATUS`, `MISSING_CLAIM_SECTION`,
`MISSING_CLAIM_SUMMARY`, `CLAIM_SUMMARY_TOO_LONG`, `CLAIM_WITHOUT_SOURCE`,
`INVALID_SOURCE_ID_IN_CLAIM`, `CLAIM_REFERENCES_UNKNOWN_SOURCE`,
`CLAIM_SUPPORTED_BY_UNVERIFIED_SOURCE`, `CLAIM_SUPPORTED_BY_NON_INCLUDED_SOURCE`,
`CLAIM_SUPPORTED_BY_RETRACTED_SOURCE`, `CLAIM_MARKED_VERIFIED_WITH_UNVERIFIED_SOURCE`,
`LOW_CERTAINTY_CLAIM_HEDGE_REQUIRED`, `UNKNOWN_SOURCE_MARKER`, `UNVERIFIED_CITATION_MARKER`,
`CITED_SOURCE_NOT_INCLUDED`, `CITED_RETRACTED_SOURCE`, `SOURCE_MARKER_WITHOUT_CLAIM_MARKER`,
`UNKNOWN_CLAIM_MARKER`, `CLAIM_MARKER_MISSING_SOURCE_MARKER`, `CLAIM_MARKER_NOT_VERIFIED`,
`UNTAGGED_QUANTITATIVE_CONTENT`, `UNRESOLVED_PLACEHOLDER`, `CLAIM_NOT_USED_IN_MANUSCRIPT`,
`INCLUDED_SOURCE_NEVER_CITED`, `MISSING_REFERENCE_NUMBER`, `REFERENCE_NUMBER_OUT_OF_RANGE`,
`DUPLICATE_REFERENCE_NUMBER`, `CITATION_EXCEEDS_REFERENCE_LIST`, `UNCITED_REFERENCE`,
`CITATION_NOT_IN_FIRST_APPEARANCE_ORDER`, `DRAFT_MARKER_IN_FINAL_DOCUMENT`,
`NO_NUMBERED_CITATIONS_FOUND`.
