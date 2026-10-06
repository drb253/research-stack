# Final Quality Checklist

Run this before submission, alongside `scripts/gate.py`. The gate checks what a machine can check;
this list is what a human must check. Both must be clean.

## 1. Scope and question

- [ ] `scope.md` is complete, including the PICO, the venue limits, and the assumptions made.
- [ ] The abstract's objective and the Introduction's aim are the same statement.
- [ ] The review answers the question it sets; nothing in the body is off-topic.
- [ ] The declared review type matches what was actually done.

## 2. Search and selection

- [ ] `search_log.csv` has one row per executed query, with the exact strings and dates.
- [ ] At least three independent sources were searched, or the limitation is stated in Methods.
- [ ] Unavailable databases are recorded and disclosed.
- [ ] The date of the last search is in Methods and is recent enough for the topic.
- [ ] Deduplication was performed by DOI, then PMID, then title and year, and the count is recorded.
- [ ] Every excluded record that reached full text has a specific exclusion reason.
- [ ] `prisma_counts.json` matches the summary counts of `sources.csv`.
- [ ] Citation chasing (forward and backward) was performed on the landmark sources.

## 3. Sources and verification

- [ ] `validate_sources.py --strict --require-included` passes with zero errors.
- [ ] Every included source is `verified` with a named `verifier`, a `verified_date`, and a `locator`.
- [ ] Every included source has a resolvable DOI or PMID.
- [ ] No included source is retracted; expressions of concern are disclosed in the text.
- [ ] Preprints, abstracts, and registry records are labelled wherever they appear.
- [ ] No duplicate rows (same DOI, or same title and year).
- [ ] Peer-review status is recorded for every source; no unexplained `unknown`.
- [ ] The reference list is within the venue's limit, and nothing was dropped to fit it.

## 4. Claim integrity

- [ ] Every factual sentence has a `[claim:Cxxx]` marker with verified sources, or was deliberately
      written as the authors' interpretation and is recognisable as such.
- [ ] Every registered claim appears in the manuscript, or is deliberately removed from the ledger.
- [ ] Claim certainty matches the hedging language used.
- [ ] Conflicting evidence is presented, not hidden.
- [ ] Null and negative findings are reported.
- [ ] No claim exceeds its evidence: check the association/causation, non-significance/equivalent, and
      surrogate/outcome conversions specifically.

## 5. Numbers

- [ ] `check_numbers.py` passes.
- [ ] Every number in the manuscript traces to a `sources.csv` row with a locator.
- [ ] Percentages recompute from the numerator and denominator shown.
- [ ] Every effect estimate carries its interval and its comparator.
- [ ] Abstract numbers equal the body numbers (the drift check catches per-claim differences).
- [ ] Units are consistent and stated; conversions are noted.
- [ ] Randomised, analysed, and evaluable populations are not conflated.

## 6. Citation mechanics

- [ ] `build_reference_list.py` ran without errors, and `final/references.md` is the current list.
- [ ] `audit_citations.py --final` passes: no gaps, no uncited references, no orphan numbers.
- [ ] No leftover `[claim:]` or `[src:]` markers in the final document.
- [ ] Every reference is cited in the text, in first-appearance order where the style requires it.
- [ ] DOIs resolve; spot-check at least five by hand.
- [ ] Reference style matches the venue's current instructions.

## 7. Displays

- [ ] Every table and figure is referenced in the text, in order, and has a caption.
- [ ] Captions define the population, units, uncertainty, and abbreviations.
- [ ] `make_prisma_flow.py --check-only` passes.
- [ ] No significance marks, trend lines, or pooled estimates that were not in the source.
- [ ] Tables remain readable as text and are not images.
- [ ] Provenance recorded for every display (source IDs and generating command).

## 8. Language and completeness

- [ ] `lint_manuscript.py --sections` passes with no errors.
- [ ] No placeholders, TODOs, or `[UNVERIFIED]` markers remain.
- [ ] Every required section and declaration is present.
- [ ] Abbreviations are defined at first use everywhere, including captions.
- [ ] Consistent terminology, one term per concept.
- [ ] Word count within the venue limit.
- [ ] No overclaiming or absolute language that survived from the draft.
- [ ] No quotation over ~25 words.
- [ ] If an advisory classifier was used, its findings were reviewed as *hints*, and any disagreement
      with a deterministic check was resolved in favour of the deterministic check.

## 9. Integrity and policy

- [ ] No PHI anywhere in the workspace.
- [ ] Funding, conflicts, CRediT roles, data availability, and AI-use disclosure complete.
- [ ] AI disclosure matches what was actually done.
- [ ] Permissions and licences recorded for any reused display.
- [ ] Author instructions (retrieved on a dated occasion) satisfied for format, structure, and length.

## 10. Unresolved items

- [ ] `UNRESOLVED.md` contains only items that are closed, or the open ones are disclosed to co-authors
      and accepted deliberately as limitations.
- [ ] Any claim withdrawn for lack of verified support is recorded in Appendix C.
- [ ] The gate report (`GATE_REPORT.json`) shows `submission_ready: true`.

## 11. Exported deliverables

- [ ] `export_document.py` ran without errors for every wanted format.
- [ ] The DOCX opens in Word with headings intact (test `Home > Navigation Pane`) and page numbers
      in the footer.
- [ ] The DOCX contains every table as a real table (not an image) and every figure as an embedded
      image, or says plainly in the export report that it could not.
- [ ] The PDF is A4, has the running footer, and shows the screening-flow figure.
- [ ] `substituted_characters` in the PDF report is empty; anything listed has been rewritten.
- [ ] The HTML displays the figure and its citation links jump to the right reference entries.
- [ ] Table and figure numbering matches between DOCX, PDF, and HTML.
- [ ] `gate.py --require-exports` passes.
- [ ] Co-authors received the DOCX, the reference list, the tables, and the figures in a form they can
      edit and comment on.

## Sign-off

| Role | Name | Date | Confirms |
|---|---|---|---|
| Corresponding author | | | Whole manuscript, accuracy of all citations |
| Verifier(s) | | | Source verification and locators |
| Statistician (if involved) | | | Numeric statements and intervals |
| All authors | | | Final approval of the version to be published |
