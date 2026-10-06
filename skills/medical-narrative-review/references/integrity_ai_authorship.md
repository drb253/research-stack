# Integrity, AI Use, Authorship, and Confidentiality

## Authorship

Follow the target journal's adoption of the ICMJE criteria. All four must hold for authorship:

1. substantial contributions to conception or design, or acquisition, analysis, or interpretation;
2. drafting the work or revising it critically for important intellectual content;
3. final approval of the version to be published;
4. agreement to be accountable for all aspects of the work.

**AI systems cannot meet these criteria and cannot be authors.** No large language model, agent, or
tool appears in the author list, in the affiliations, or as a corresponding author.

Record in the ledgers and the manuscript:

- who verified each source (`verifier`, `verified_date`);
- who screened records and who performed extraction, and whether it was duplicated;
- the CRediT roles per author;
- that all authors reviewed the final version, or the current state of that approval.

## AI-use disclosure

Write the disclosure per the target journal's *current* policy, and state exactly what was done:

```text
AI use: The authors used an AI-assisted drafting tool to organise verified source material,
propose paragraph structures, and check numeric consistency against the extracted data ledger.
All sources were retrieved and verified by the named authors, who reviewed, edited, and take
responsibility for all content. No AI system is an author. No patient data or unpublished
third-party material was entered into any external service.
```

Rules that hold regardless of journal:

- Never claim that no AI was used when it was.
- Never claim a human verified content that no human checked.
- Never state that AI "wrote" a section a human substantively rewrote, or vice versa.
- Do not paste unpublished third-party manuscripts, peer-review material, or patient data into any
  external tool.

## Confidentiality and patient data

- No protected health information, ever, in any file, ledger field, prompt, or figure: no names, no
  dates of birth, no medical record or accession numbers, no identifying images, no dates of service
  that could re-identify.
- Use aggregate data from published sources. If the review uses the user's own institutional data,
  confirm ethics approval, consent status, and the data-use agreement first.
- Redaction is not de-identification. Removing names from a table does not make it safe to share;
  anything derived from identifiable data needs expert review.
- Unpublished manuscripts, grants, and peer-review material received in confidence may be read
  locally for context but must not be sent to an external service without written permission from
  the owner and a policy review.
- The bundled scripts are local and offline: they are the safe path for sensitive material.

## Plagiarism and text reuse

- No verbatim quotation longer than about 25 words; every quotation in quotation marks with a
  citation and a page or section locator.
- No text reuse from any source, including your own earlier reviews, without attribution and
  disclosure. Self-plagiarism is still plagiarism and is detected by similarity checkers.
- Paraphrase means restating the proposition in new words and a new structure, not swapping synonyms.
- Tables and figures from elsewhere need permission and attribution, with the licence recorded in the
  display provenance.
- Salami slicing and duplicate publication are integrity problems, not formatting problems.

## Image and data integrity

- Never edit a figure to hide, remove, duplicate, or misrepresent information.
- Cropping must be disclosed, applied uniformly across panels, and must not remove essential context
  such as gel lanes or scale bars.
- Never adjust brightness or contrast per panel in a way that changes the interpretation.
- Do not reuse a control image across experiments without disclosure.
- Keep original data and the transformation trail for every display.



## Predatory and low-quality outlets

Check before citing and before submitting: whether the journal is indexed where you expect, whether
it is listed in the Directory of Open Access Journals, whether it has a documented peer-review
process, and whether the publisher appears on a recognised predatory-journal list. Record
`peer_reviewed = yes|no|unknown` for every source; `unknown` raises a warning, because an unverified
peer-review status silently weakens the evidence base.

## Conflicts of interest and funding

Record per author: financial relationships with manufacturers of any product discussed, patents,
equity, advisory roles, and institutional funding. A review of a therapy must disclose relationships
with its developers even when they did not fund the review. Name funding sources and their role in
design, analysis, and writing.

## Data availability

For a review, state what is actually available: search strategies in the appendix, the extraction
ledger (minus anything sensitive), and the commands used to analyse counts. Do not promise
availability you will not honour.

## Corrections and post-publication issues

If a source is retracted, corrected, or acquires an expression of concern after your search:

1. recheck the DOI with `check_retraction`;
2. update `retraction_status` and re-run the audits;
3. if the change affects a claim, correct the prose and note the change in the record;
4. if the review is already published, follow the journal's correction procedure rather than quietly
   issuing a new version.

## Integrity checklist

- [ ] No AI system listed as an author; AI use disclosed exactly as it happened.
- [ ] `verifier` and `verified_date` present for every cited source.
- [ ] No PHI anywhere in the workspace (`POSSIBLE_PHI_*` clear).
- [ ] No quotation over ~25 words; all quotations cited with locators.
- [ ] Permission and licence recorded for every reused display.
- [ ] Conflicts, funding, data availability, and CRediT roles complete.
- [ ] Retraction status rechecked on the day of submission.
- [ ] Peer-review status recorded for every source, with no unexplained `unknown`.
- [ ] Author list and order agreed by all named authors before submission.
- [ ] Contributors who do not meet authorship criteria are named in acknowledgments, with permission.
