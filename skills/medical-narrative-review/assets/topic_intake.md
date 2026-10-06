# Intake: Scope Lock Questionnaire

Ask these before searching. Fill `scope.md` with the answers. Where the user does not specify, use
the default shown in brackets, **state the assumption in `scope.md`**, and add the item to
`UNRESOLVED.md` so it cannot be forgotten.

## 1. The topic and the question

1. Topic in one sentence.
2. Draft title.
3. Population (default: the population of the main trials on the topic).
4. Intervention or exposure.
5. Comparator (default: standard care or placebo, as used by the main studies).
6. Outcomes of interest, ranked (default: the primary endpoint plus safety).
7. Time frame or follow-up of interest.
8. Clinical setting and audience (default: general specialists in the field).

## 2. Type and scope

9. Review type: `narrative`, `narrative_with_systematic_search`, or `scoping_informed`
   (default: `narrative_with_systematic_search`, because it is auditable and safe to publish).
10. Years to cover (default: the last 10 years, plus any landmark earlier work).
11. Languages (default: English only, stated as a limitation).
12. Designs to include (default: randomised trials, systematic reviews, guidelines, and large
    observational cohorts; mechanistic studies only for the mechanism section).
13. Publication types to include (default: peer-reviewed articles and guidelines; preprints and
    abstracts only if labelled and only when nothing else exists).
14. Human, animal, or in vitro (default: human for clinical claims, with preclinical evidence labelled
    and confined to the mechanism section).
15. Explicitly out of scope: list anything the user does **not** want covered.

## 3. Venue and limits

16. Target journal or venue.
17. Article type and word limit.
18. Maximum tables and figures.
19. Citation style: `vancouver`, `ama`, `apa`, or `elsevier` (default: `vancouver`).
20. Reference limit, if any.
21. Author instructions: retrieve the current version and record the access date. Never rely on
    remembered requirements.

## 4. Sources the user already has

22. Any papers, PDFs, BibTeX, or reference-manager exports to include?
23. Any prior search, protocol, or grant text to build on?
24. Any institutional or proprietary data (requires ethics, consent, and data-use confirmation
    before use)?
25. Any named authors or verifiers who will perform source verification?

## 5. Verification

26. Who performs the human verification of sources (`verifier`), and on what date?
27. How will inaccessible full texts be handled (default: verify from the record and record
    `locator = abstract_only`, and say so if only the abstract was available)?
28. Is `check_retraction` to be run on every DOI at drafting time and again at the gate? (default: yes)

## 6. Deliverables

29. Which outputs are wanted: manuscript Markdown, numbered reference list, tables, screening-flow
    figure, unresolved-items appendix, gate report, DOCX or PDF conversion?
30. Any journal template to match for conversion (retrieve it, do not reconstruct it)?
31. Deadline and any intermediate checkpoint the user wants reviewed.

## 7. Red lines to confirm

Confirm explicitly, in writing, in `scope.md`:

- [ ] No reference will be cited that was not identifier-verified in this session.
- [ ] No number will be stated that is not in `sources.csv` with a locator.
- [ ] Unverifiable material becomes a visible placeholder, never a plausible citation.
- [ ] Section-level or whole-document drafting will not begin before the ledgers exist.
- [ ] The gate must pass before the review is described as submission-ready.
- [ ] No patient-identifiable data will be entered into any file or external service.

## Default assumptions to state when the user is silent

```text
Review type          narrative_with_systematic_search
Languages            English only (stated as a limitation)
Years                last 10 years plus landmark earlier work
Citation style       vancouver
Search date          the date the searches were actually executed
Verification         performed by the requesting author
Certainty scheme     GRADE-compatible four levels
Displays             one evidence table, one certainty table, one screening-flow figure,
                     plus the excluded-records log in the appendix when a systematic search ran
```
