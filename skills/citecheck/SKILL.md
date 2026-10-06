---
name: citecheck
description: "Audit and build citations so a document is properly attributed - the real fix for 'plagiarism'. Four modes: audit (find claims that need a citation, orphan in-text citations, incomplete reference lists, and retracted sources), build (turn DOIs / PMIDs / arXiv ids / titles into an authoritative, style-correct reference list), verify (check an existing .bib or reference list against Crossref/OpenAlex for a wrong year, author, or a retraction), scan (pull every DOI / arXiv id / PMID out of a draft and emit the reference list). Resolves metadata via Crossref and OpenAlex with no API key and flags retracted works. Formats citations in APA 7, MLA 9, Chicago, Vancouver, IEEE, Harvard, and BibTeX. It does NOT rewrite prose to dodge similarity detectors - correct attribution, not rewording, is what makes writing plagiarism-free. Use when a draft needs citations added or checked, a reference list built or verified, or a bibliography cleaned."
allowed-tools: Read Write Edit Bash
license: MIT
compatibility: "Instructions plus one stdlib-only Python 3.8+ script (scripts/citecheck.py). No third-party packages and no API key. Needs network access to api.crossref.org and api.openalex.org. Works in any agent that supports SKILL.md."
metadata:
  version: "1.0"
  skill-author: local (custom skill)
  slash-command: /citecheck
  invocation-example: /citecheck <paste the draft, the reference list, or the DOIs>
  modes: audit, build, verify, scan
  styles: APA 7, MLA 9, Chicago, Vancouver, IEEE, Harvard, BibTeX
  sources:
    - https://api.crossref.org
    - https://api.openalex.org
---

# citecheck

Check and build citations so every borrowed idea is attributed. This is the part that actually makes
writing "plagiarism-free": a correct quotation plus a correct citation. Reworded text that is not cited
is still plagiarism, however low it scans on a similarity report.

## What this skill is, and is not

**It is.** An attribution engine. It finds claims that need a citation, resolves works to authoritative
metadata (Crossref, OpenAlex, arXiv), checks for retractions, and formats a reference list correctly.

**It is not.** A similarity-evasion tool. It will not paraphrase text to lower a Turnitin/iThenticate
score, strip C2PA/zero-width metadata, or promise a detector result. When text is borrowed, the fix is a
citation, not darker wording. If the user asks for evasion, say so plainly and offer to cite the passage
instead.

**It will not.** Invent a source, DOI, page range, or author. If a work cannot be resolved, it says so
and marks the entry `[UNRESOLVED]` rather than guessing.

## Four modes

1. **audit (default).** The user gives a draft (with or without a reference list). Find every external
   claim that lacks a citation, check the in-text/reference-list bijection, resolve the cited works,
   flag retractions, and report a findings table with fixes. See `references/audit-rules.md`. Do not
   rewrite the prose; fix the attribution.
2. **build.** The user gives identifiers (DOIs, PMIDs, arXiv ids, or titles). Resolve each, format a
   reference list in the requested style, and flag any retracted or unresolved entry. Never emit an
   entry you could not resolve as if it were verified.
3. **verify.** The user gives an existing `.bib` file or a list of identifiers. Resolve each and compare
   against the record: report year/author/title mismatches and retractions. De-duplicate repeated works.
4. **scan (bib-from-draft).** The user gives a draft. Pull every DOI (plus `arXiv:` and `PMID:` ids) out
   of the text in order, resolve them, merge duplicates of the same work, and emit the reference list.
   Report unresolved and retracted entries on stderr - never silently. See the Workflow below.

## Resolution engine

- **Crossref** (`api.crossref.org`) - primary metadata source for DOIs.
- **OpenAlex** (`api.openalex.org`) - title search and the retraction flag (`is_retracted`).
- **arXiv** (`export.arxiv.org`) - arXiv ids.

All are keyless. Title resolution is best-effort discovery: always confirm the DOI and venue before
citing a title-resolved record.

## Styles

APA 7 (default), MLA 9, Chicago, Vancouver, IEEE, Harvard, BibTeX - templates and examples in
`references/styles.md`. One style per deliverable. Numbered styles (Vancouver, IEEE) number by first
appearance in the text, not alphabetically.

## Hard rules

- **Never invent metadata.** Every author, year, title, journal, volume, page, DOI, and URL traces to a
  resolved record or the user's own input.
- **Never cite a retracted source silently.** Flag it (`[RETRACTED]`) and point to the retraction notice.
- **Never present an unresolved identifier as a normal reference.** Mark it `[UNRESOLVED]` and say why.
- **Confirm title-resolved records.** Title search returns a candidate; verify the DOI/venue before citing.
- **Attribute, do not conceal.** A paraphrase still needs a citation. That is the entire point here.

## Commands

```text
/citecheck <draft or reference list>                     # audit (default)
/citecheck build 10.1038/s41586-021-03819-2, PMID:34265844 --style apa
/citecheck verify refs.bib
/citecheck scan draft.md --style apa --out refs.bib       # pull DOIs from a draft into a list
/citecheck duplicates draft.md                            # repeat / inconsistent in-text citations
```

Bundled script (stdlib only, no key):

```bash
python scripts/citecheck.py resolve 10.1038/s41586-021-03819-2 --format apa
python scripts/citecheck.py resolve "Attention is all you need" --format bibtex
python scripts/citecheck.py resolve 34265844 --format ieee          # PMID
python scripts/citecheck.py resolve 1706.03762 --format vancouver   # arXiv
python scripts/citecheck.py resolve 10.xxxx/yyy --json              # normalized record
python scripts/citecheck.py verify refs.bib                         # or a list of ids
python scripts/citecheck.py verify refs.bib --format json
python scripts/citecheck.py bib-from-draft draft.md --style apa --out refs.bib   # scan a draft
python scripts/citecheck.py duplicates draft.md                     # citation consistency
python scripts/citecheck.py scan draft.md --ids-only                # just the DOIs in the draft

# MCP interlock: fetch with paper-search/ncbi, format with the script
echo "$EXPORT_CITATIONS_JSON" | python scripts/citecheck.py format --style apa
python scripts/citecheck.py format --style vancouver --file mcp_records.json
```

Styles: `apa` (default), `mla`, `chicago`, `vancouver`, `ieee`, `harvard`, `bibtex`, `json`.

## Workflow

### audit
1. Read the draft. Extract every in-text citation and every listed reference.
2. Find external claims with no citation (rule A1 in `references/audit-rules.md`).
3. Resolve each cited DOI/identifier with the script; note retractions (A4) and metadata mismatches (A5).
4. Check the bijection: cited-but-not-listed, and listed-but-never-cited (A2).
5. Check quotes and locators (A6); run `duplicates` for repeated works (A7) and inconsistent in-text
   wording (A10).
6. Return the findings table plus a short **Notes** list; offer to build the corrected reference list.

### build
1. Collect the identifiers (comma/space separated, or one per line).
2. Resolve each with `resolve`.
3. Format in the requested style (§Styles).
4. Flag retracted (`[RETRACTED]`) and unresolved (`[UNRESOLVED]`) entries.
5. Return the reference list, then **Notes**.

### verify
1. Run `verify` on the `.bib` or identifier file.
2. Report each entry's status: `OK` / `WARN` / `FAIL` / `RETRACTED`.
3. For WARN/FAIL, give the field and the actual value from the record.
4. De-duplicate repeated works and re-check.

### scan (bib-from-draft)
1. Run `bib-from-draft` on the draft (or paste the text). It pulls every DOI, plus `arXiv:` and `PMID:`
   ids, in document order, and de-duplicates them.
2. It resolves each, merges duplicates of the same work, formats the list, and reports unresolved and
   retracted entries on stderr - never silently.
3. For a long draft, prefer resolving the DOIs in one call with `paper-search__export_citations`, then
   pipe its JSON through `format`.
4. Still run the `audit` checks (A1, A2): a list built from a draft does not tell you which in-text
   claims are uncited.

## Self-check

Run `eval.md` before returning output. **C1** (no invented metadata) and **C2** (no unverified citation
presented as verified) are hard errors - never ship output that fails them.

## Reference files

- `references/styles.md` - format templates and worked examples for each style.
- `references/audit-rules.md` - the citation-audit checklist (A1-A10) and reporting format.
- `references/mcp-tools.md` - MCP tool routing, exact args, return shapes, and fallback rules.

## Tool routing (MCP-first)

If the runtime exposes the `paper-search` / `ncbi` MCP tools, **prefer them over the script** - they are
DOI-verified and retraction-checked. The script is the keyless fallback *and* the formatter. The full
table, exact args, return shapes, and verified quirks are in `references/mcp-tools.md`.

Fast map:

- DOI → metadata: `paper-search__get_crossref_paper_by_doi`
- DOI batch → citations + retraction: `paper-search__export_citations` (`check_retractions=true`)
- retraction (with notice DOI): `paper-search__check_retraction`
- title/author → candidates: `paper-search__search_papers` (confirm the DOI before citing)
- PMID → metadata: `ncbi__get_article_details`
- formatting: `python scripts/citecheck.py format --style <style>` (pipe the MCP JSON in)

**Interlock.** Fetch with MCP, format with the script:
`<MCP JSON> | python scripts/citecheck.py format --style apa`. `format` accepts a record, a list, or an
envelope keyed `entries` / `articles` / `papers` / `results` / `data`.

**Batch-resolving a draft.** For a draft with many DOIs, do not resolve one at a time: list them with
`scan <draft> --ids-only`, pass the list to `paper-search__export_citations`
(`check_retractions=true`), then pipe its JSON through `format`. One round trip instead of N.

If no MCP tools are present, everything falls back to `scripts/citecheck.py` (keyless, stdlib only,
Python 3.8+).


