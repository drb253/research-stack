# eval.md — self-check for /medical-narrative-review

Run this before the gate, and again before submission. It names the rubric item behind every
check the skill makes, so a reader can tell which procedure decides each one.

Two files carry the rubric, and they are not replacements for each other:

* `references/qa_checklist.md` — the full human pre-submission checklist, section by section.
* this file — the same eleven items with an id, the check that decides each one, and the
  severity of a failure.

Each item is marked **blocking** or **flag**. A blocking failure means the review is not
submission-ready: `scripts/gate.py` reports it as an `error` issue and exits 1, and no command
choice waives it. A flag failure is a human judgement: fix it, or record in `UNRESOLVED.md` why
it stands.

---

### MN1. The scope, the question and the declared review type agree. **Flag.**

`scope.md` holds the PICO or PEO framing, the venue limits and the assumptions. The abstract's
objective and the Introduction's aim are the same statement, and the declared review type
matches what was done. *Fails when:* the review answers a different question from the one it
sets, or declares a systematic review and runs a narrative one.

### MN2. The search is recorded well enough to reproduce. **Flag.**

`search_log.csv` carries one row per executed query with the exact string, the database, the
date, the filters and the hit count. At least three independent sources were searched, or
Methods states the limitation. Unavailable databases are recorded, not silently dropped, and
deduplication by DOI, then PMID, then title and year is recorded with its count. *Fails when:* a
Methods section describes a search that was not executed, or an unavailable source is reported
as "no evidence exists".

### MN3. Every included source is verified and complete. **Blocking.**

`python3 scripts/validate_sources.py sources.csv --strict --require-included` passes with zero
errors: each included source is `verified` with a named `verifier`, a `verified_date` and a
`locator`, carries a resolvable DOI or PMID, has a recorded `retraction_status`, and is not a
duplicate row. Preprints, registry records and abstracts are labelled wherever they appear.
*Fails when:* a citation enters the review on recall, on a search snippet, or on a title match
that was never confirmed against the identifier.

### MN4. Claim integrity holds. **Blocking.**

Every factual sentence carries a `[claim:Cxxx]` marker bound to verified sources, or is
deliberately written as the authors' interpretation and reads as such. Every registered claim
appears in the manuscript or was removed from the ledger. Certainty language matches the
`certainty` field, conflicting evidence is presented rather than hidden, and null or negative
findings are reported. *Fails when:* a claim exceeds its evidence — association written as
causation, non-significance written as equivalence, a surrogate endpoint written as a clinical
outcome.

### MN5. Every number traces to a recorded value. **Blocking.**

`python3 scripts/check_numbers.py final/manuscript_cited.md` passes. Each percentage recomputes
from its numerator and denominator, each effect estimate carries its interval and its
comparator, and every number traces to a `sources.csv` row with a locator. Abstract numbers
equal the body numbers. *Fails when:* a value was computed from memory, a percentage does not
recompute, or an interval lost its comparator.

### MN6. Citation mechanics are complete. **Blocking.**

`python3 scripts/build_reference_list.py` ran without errors and
`audit_citations.py --final` passes: no uncited reference, no citation without an entry, no
orphan number, and no leftover `[claim:]` or `[src:]` marker in the final document. DOIs
resolve. *Fails when:* the reference list is not the one the text cites, or an unverified entry
reached it — the builder refuses to emit such an entry.

### MN7. Displays come from recorded data. **Flag.**

`python3 scripts/make_prisma_flow.py --check-only` passes, so the flow arithmetic balances.
Every table and figure is referenced in the text in order and has a caption that defines the
population, units, uncertainty and abbreviations. No significance mark, trend line or pooled
estimate appears that was not in the source, tables stay readable as text rather than images,
and the source IDs and the generating command are recorded. *Fails when:* a display invents a
number, or a caption cannot be read without the text.

### MN8. Language and completeness are submission-ready. **Flag.**

`python3 scripts/lint_manuscript.py final/manuscript_cited.md --sections` passes with no errors:
every required section and declaration is present, no placeholder or TODO remains, abbreviations
are defined at first use everywhere including captions, terminology is consistent, the word
count is inside the venue limit, and no quotation runs over about 25 words. *Fails when:* a
section is missing, a placeholder survived, or an absolute claim outlived the draft.

### MN9. Integrity and policy are complete. **Flag.**

No PHI anywhere in the workspace. Funding, conflicts, CRediT roles, data availability and the
AI-use disclosure are complete, and the disclosure matches what was actually done. Permissions
and licences are recorded for any reused display, and the author instructions (retrieved on a
dated occasion) are satisfied for format, structure and length. *Fails when:* the disclosure
describes a different process from the one that ran, or third-party material is reused without a
licence.

### MN10. No open item is hidden. **Blocking.**

`UNRESOLVED.md` contains only closed items, or the open ones are disclosed to co-authors and
accepted as limitations. Any claim withdrawn for lack of verified support is recorded in the
appendix. `GATE_REPORT.json` shows `submission_ready: true`. *Fails when:* a placeholder, a
conflict or a missing source survives into a document presented as finished.

### MN11. The exported deliverables are complete and consistent. **Blocking.**

`python3 scripts/export_document.py` ran for every wanted format, and
`gate.py --require-exports` passes. The DOCX opens with headings and page numbers intact and
carries every table as a real table; the PDF is A4 with the running footer and the screening
figure; the HTML displays the figure and its citation links jump to the right entries. Table and
figure numbering matches across the three formats. *Fails when:* one format is a second-class
copy, or a figure is missing and the export does not say so.

---

## Reporting

Keep this internal unless the user asks for it. If asked, give the table:

| Item | What decides it | Severity |
|---|---|---|
| MN1 | `scope.md` and the manuscript's own question | flag |
| MN2 | `search_log.csv`; the availability records in the gate report | flag |
| MN3 | `validate_sources.py --strict --require-included` | blocking |
| MN4 | `audit_citations.py`; the certainty fields in `claims.csv` | blocking |
| MN5 | `check_numbers.py` | blocking |
| MN6 | `build_reference_list.py`; `audit_citations.py --final` | blocking |
| MN7 | `make_prisma_flow.py --check-only`; caption review | flag |
| MN8 | `lint_manuscript.py --sections` | flag |
| MN9 | the PHI lint; disclosure and licence review | flag |
| MN10 | `UNRESOLVED.md`; `GATE_REPORT.json` | blocking |
| MN11 | `export_document.py`; `gate.py --require-exports` | blocking |

A blocking failure means the review must not be presented as submission-ready until it is
fixed. A flag failure is a judgement for the named human authors, recorded in `UNRESOLVED.md`
when they decide to let it stand.

## Commands

```bash
python3 scripts/validate_sources.py sources.csv --strict --require-included   # MN3
python3 scripts/audit_citations.py final/manuscript_cited.md claims.csv sources.csv --final  # MN4, MN6
python3 scripts/check_numbers.py final/manuscript_cited.md                    # MN5
python3 scripts/build_reference_list.py draft.md sources.csv claims.csv --style vancouver --out-dir final/  # MN6
python3 scripts/make_prisma_flow.py prisma_counts.json --check-only           # MN7
python3 scripts/lint_manuscript.py final/manuscript_cited.md --sections       # MN8
python3 scripts/export_document.py final/manuscript_cited.md --workspace . --out-dir final/  # MN11
python3 scripts/gate.py --dir . --style vancouver --require-exports           # MN10, MN11
```

`references/qa_checklist.md` remains the full human checklist; this file does not replace it.
