# Audit rules — checking a draft's citations

Run these in **audit** mode. The output is a table of findings plus concrete fixes; you do not rewrite
the prose, you fix attribution.

---

## A1. Uncited external claims
Flag any sentence stating a fact, figure, quote, method, or another's idea that is not the author's own
common knowledge and carries no citation. Heuristics that often mark a needed citation:

- a specific number, percentage, date, or named dataset;
- a superlative ("the largest," "the first");
- a claim attributed vaguely ("studies show," "experts agree," "research suggests");
- a definition of a technical term borrowed from the literature;
- anything that would change if a different source were consulted.

Common knowledge (widely known, stable, non-controversial facts) does not need a citation; a specific
figure almost always does.

## A2. In-text / reference-list bijection
- Every in-text citation resolves to exactly one reference-list entry.
- Every reference-list entry is cited at least once in the text.
- List both directions of orphans: "cited but not listed" and "listed but never cited."

## A3. Reference entry completeness
Each entry carries the fields its type requires (authors, year, title, venue, volume/issue, pages, DOI).
Flag missing fields; do **not** fill them from memory. A missing DOI for an old print work is fine; a
missing year or author is not.

## A4. Retraction status
Resolve every DOI and check OpenAlex `is_retracted`. A retracted source is flagged loudly and never
silently left in the list. Suggest the retraction notice or a replacement where one exists.

## A5. Metadata accuracy
For each resolvable entry, compare the list against the authoritative record: year, author order and
spelling, journal name, volume, issue, pages. Report each mismatch as `field: listed=… actual=…`.

## A6. Quote fidelity and locators
- Every quoted string must match the source wording exactly (no silent edits inside quotes).
- Direct quotes need a page/paragraph locator where the style requires one.
- Quotes you cannot verify are flagged as unverified, not passed.

## A7. Duplicates and near-duplicates
Same DOI, or same title/author/year under two keys, is a duplicate: flag it and de-duplicate. Watch for
the same work cited once as a preprint and once as the journal version.

## A8. Paraphrase still needs a citation (the core rule)
Rewording a source does not remove the need to cite it. A close paraphrase with no citation is a
citation gap, not a style issue — flag it like A1. This is the point of the whole skill: attribution is
what makes writing "plagiarism-free," not rewording.

## A9. Self-plagiarism / reuse
Text recycled from the author's own prior publication still needs citation unless the venue permits
reuse. Flag verbatim reuse of the author's own earlier text.

## A10. Style consistency
In-text and list format must be one style, applied consistently (see `styles.md`). Flag mixed styles
(e.g. APA in text, MLA in the list).

---

## Reporting format

Return a table, one row per finding, plus a short **Notes** section:

| # | Location | Rule | Finding | Fix |
|---|---|---|---|---|
| 1 | ¶3 "37% of…" | A1 | statistic with no citation | add source for the 37% figure |
| 2 | ref "Smith 2019" | A2 | in list, never cited in text | cite or remove |
| 3 | ref "Wakefield 1998" | A4 | source is retracted | remove; cite the retraction notice |
