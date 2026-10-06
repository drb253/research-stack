# Citation and Reference Rules

## The one rule that matters

**A reference may be written only after a live lookup returned a record with a resolvable DOI or
PMID whose title, first author, container, and year match the sentence it supports.** Everything
below is detail on how to obey that rule and what to do when it cannot be obeyed.

## Verification loop

```text
candidate citation
  -> retrieve by DOI (get_crossref_paper_by_doi) or by PMID (search_pubmed / convert_paper_ids)
  -> compare title, first author, container, year, volume/issue/pages with what you are about to write
  -> check_retraction(doi)
  -> confirm the source actually supports the claim's direction, population, and magnitude
  -> copy the bibliographic fields into sources.csv
  -> verification_status = verified, verifier = <human name>, verified_date = <today>, locator = <where>
```

If any step fails: `verification_status = unverified`, keep it out of the prose, and put it in
`UNRESOLVED.md`. The most common failure is a citation that looks right in memory but whose record
cannot be found — that is a fabricated reference, even when nobody intended to fabricate it.

## Never do this

| Prohibited | Why it happens | What to do instead |
|---|---|---|
| Citing a paper you have not retrieved | It "must exist" | Search for it. If it is not found, say so and offer verified alternatives |
| Reconstructing authors, volume, or pages from a citation string | Looks plausible | Copy from the retrieved record; leave `not_reported` and let the warning flag it |
| Citing a review for a primary finding | The review was easier to find | Retrieve and cite the primary report; if unobtainable, cite the review and write "as reported in" |
| Citing a preprint as a published study | The DOI resolves | Label it: "in a preprint that has not been peer reviewed" |
| Citing a retracted paper | The finding is memorable | Cite it only in a sentence stating that it was retracted, or exclude it |
| Citing a conference abstract for an effect size | The abstract has a headline number | Cite it, label it as an abstract, and never let it carry a central claim |
| Padding the reference list with uncited entries | Looks thorough | The audit fails on `UNCITED_REFERENCE` |
| Citing several papers for a claim only one supports | Sounds strong | One claim, one verified support set; add others only if they genuinely support it |

## Retraction and correction handling

1. Run `check_retraction` on every DOI before citing.
2. Record `retraction_status` as `clear`, `retracted`, `expression_of_concern`, or `corrected`.
3. A `retracted` source may appear only as a retracted work, in a sentence that says so; otherwise
   it is excluded.
4. An `expression_of_concern` source may be cited only with that status disclosed in the text.
5. A `corrected` source must be cited in its corrected version, and the correction noted if it
   changes a number you use.
6. Recheck retraction status at the final gate: retractions happen during writing.

## In-text citation mechanics

While drafting, use machine-readable markers on every factual line:

```text
Pembrolizumab plus chemotherapy prolonged overall survival (HR 0.49, 95% CI 0.38 to 0.64).
[claim:C001] [src:S001,S004]
```

`build_reference_list.py` converts markers into numbered citations in order of first appearance and
strips the claim markers, producing `final/manuscript_cited.md`. Numbering rules the audit enforces:

- every reference is cited at least once;
- every number 1..N exists exactly once in the reference list;
- citations appear in first-appearance order (`CITATION_NOT_IN_FIRST_APPEARANCE_ORDER` is a warning
  when they do not, which matters for order-of-appearance styles);
- consecutive runs render as `[1-3]`, non-consecutive as `[1,4,7]`.



## Reference formats produced by the tooling

Given `Gandhi L, Rodriguez-Abreu D, Gadgeel S, Esteban E, Felip E, De Angelis F, et al.`, container
`N Engl J Med`, 2018, volume 378, issue 22, pages 2078-2092, DOI `10.1056/NEJMoa1801005`:

**Vancouver / NLM** (first 6 authors, then `et al`):

```text
Gandhi L, Rodriguez-Abreu D, Gadgeel S, Esteban E, Felip E, De Angelis F, et al.
Pembrolizumab plus chemotherapy in metastatic non-small-cell lung cancer.
N Engl J Med. 2018;378(22):2078-2092. doi:10.1056/NEJMoa1801005
```

**AMA 11th** (first 3 authors, then `et al`):

```text
Gandhi L, Rodriguez-Abreu D, Gadgeel S, et al.
Pembrolizumab plus chemotherapy in metastatic non-small-cell lung cancer.
N Engl J Med. 2018;378(22):2078-2092. doi:10.1056/NEJMoa1801005
```

**APA 7th** (all authors required; `Surname AB` is converted to `Surname, A. B.`):

```text
Gandhi, L., Rodriguez-Abreu, D., Gadgeel, S., Esteban, E., Felip, E., De Angelis, F., et al.
(2018). Pembrolizumab plus chemotherapy in metastatic non-small-cell lung cancer.
N Engl J Med, 378(22), 2078-2092. https://doi.org/10.1056/NEJMoa1801005
```

**Elsevier**:

```text
Gandhi L, Rodriguez-Abreu D, Gadgeel S, Esteban E, Felip E, De Angelis F, et al.
Pembrolizumab plus chemotherapy in metastatic non-small-cell lung cancer.
N Engl J Med 2018 378(22):2078-2092. https://doi.org/10.1056/NEJMoa1801005
```

Journal-name abbreviation style, whether DOIs or URLs are required, and whether the venue wants
`et al` after 3 or after 6 authors vary. Copy the target journal's *current* instructions; do not
infer them. All four formats above are generated mechanically from `sources.csv`. When something is
missing or wrong, fix the ledger field and regenerate — never hand-edit the generated list.

Because APA requires the complete author list, a ledger that records `et al.` cannot produce a fully
compliant APA reference. The tool formats what is recorded, appends `et al.`, and raises
`AUTHOR_LIST_TRUNCATED_FOR_APA` so the gap is visible rather than silent. Fill in all authors, or
export from a citation manager.

## Identifiers

- DOI: `10.xxxx/...`, no surrounding punctuation; `doi:` and `https://doi.org/` prefixes are
  normalized automatically.
- PMID: digits only. PMCID: `PMC` + digits.
- Use `convert_paper_ids` when you have one identifier and need another.
- A source with no DOI or PMID may be recorded (for example an older book chapter) but cannot be
  cited: `build_reference_list.py` fails with `CITED_SOURCE_WITHOUT_IDENTIFIER`.

## Supplementary citation hygiene

- Cite guidelines and consensus statements as sources of recommendations, not as evidence of effect.
- Prefer the current version of a guideline; when superseded, exclude it or cite it explicitly as an
  earlier version with its date.
- Check the self-citation share before submission: a review that mostly cites one group is a
  reviewer objection waiting to happen.
- Do not cite a paper for a fact it merely repeats: trace the fact to the source that reported it.
- Keep the reference list within the venue's limit, but never drop a citation that supports a claim
  to satisfy a limit — compress the prose instead.
