# PROSPERO registration and citation verification

Adapted from barah123/Claude-Biomedical-Research-Skills (MIT): the
`empirical-integrity`, `grounded-citations`, `verifying-citations`, and
`systematic-review` rules, plus `scripts/prospero_search.py`.

## Registration (do it before screening, not after)

Register the protocol on PROSPERO (or the applicable registry) **before** screening begins.
Run a duplicate/novelty check first — registering a near-duplicate of an active registration
is the single most avoidable failure at this stage. A change to scope, eligibility, or
objectives during drafting must propagate to: the protocol document, the search-strategy
document, the registered record (via an **amendment**, not a silent edit), and any already-
drafted rationale text that references the old scope.

Use `scripts/prospero_search.py` (stdlib-only) to search PROSPERO's internal endpoint:

```
python3 prospero_search.py "breastfeeding AND microbiome"          # field: ALL (default)
python3 prospero_search.py "gut microbiome AND infant" TI          # TI/RQ/PA/AN fields
python3 prospero_search.py CRD42024530071 AN                        # full RIS record
```

The endpoint is undocumented and may change; repeat key searches on the PROSPERO website
before relying on them for a submission, and cite the date each search was run.

## Empirical integrity — the umbrella rule

Never write a number, date, hit count, citation, or factual claim from memory or training
knowledge. If it can be checked against a live authoritative source, check it — every time.

- **Search hit counts** are executed results, not estimates. If a database, query, or date
  range changes, re-run and replace the number. Never hand-edit a count to fit a narrative.
- **Dates/version facts** (when a MeSH heading entered the vocabulary, a trial completed, a
  tool released) → verify against the source of record, not recollection.
- **Findings attributed to a paper** → the two rules below.

Two failure modes look identical in the final document: *confident but wrong* (the training
data holds a superseded count or a retracted figure) and *right at the time, stale now*
(re-indexed database, updated trial status, preprint since published). Both are invisible to
a reader; the only defence is re-verification at write time.

## Grounded citations — at insertion time

Never write a citation from memory of what a paper "probably says." Resolve the actual
source, read the actual claim, then write the sentence. **Fetch first, write second.**

1. Resolve the source: PMID/DOI lookup or library item, **not a search snippet**. A snippet
   tells you a paper exists, not what it found — it can resolve to an erratum, commentary,
   or companion paper.
2. Fetch the abstract at minimum; fetch full text when the claim needs a specific number,
   a quoted phrase, or a subgroup/secondary result.
3. Confirm the fetched text actually contains the claim. A title implying a finding the
   abstract doesn't support is a common trap.
4. Attach the stable identifier (DOI or PMID) as the anchor, not a rot-prone URL.
5. Be a well-behaved API citizen (~0.35 s between NCBI E-utilities calls).

## Verifying citations — at audit time

Apply the same bar retroactively to a finished draft. Decide fetch depth by **claim type**,
not by how confident the prose sounds:

- **Quoted text or a specific number** (effect size, β, exact %, p-value) → always full text.
- **Qualitative direction of effect** ("X associated with higher Y") → abstract usually
  suffices, but the draft's hedging must match the paper's hedging.
- **Methodological/population claim** ("this cohort excluded preterm infants") → check the
  methods section specifically.
- **Absence claim** ("no prior review has examined X") → cannot be verified from one source;
  route to a novelty/search-completeness check.

Flag the **specific discrepancy** (what the source says vs what the draft says), not just
"unsupported." Do not silently soften the claim or drop the citation — surface it.

## Anti-patterns

Treating "the paper is real and on-topic" as sufficient (that clears retrieval, not support);
reusing a prior verification for a since-reworded claim; verifying the first of three
adjacent citations and assuming the others.

## The cross-verification gate (see the script)

`scripts/cross_verify_citations.py` turns these rules into a machine gate over the review
ledger: it resolves each cited DOI at Crossref, flags retractions (OpenAlex `is_retracted`),
and fails loudly on unresolved or retracted citations, emitting `GATE_REPORT.json`.
