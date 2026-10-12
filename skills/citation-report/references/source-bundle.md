# Source bundle: how sources are linked, and what each link is worth

The report is only as strong as this step. Every source ends in one of four
`evidence_availability` states, and nothing is ever dropped silently — a source we could not read is
recorded as such and its sentences are reported as unverifiable rather than being quietly treated as
unsupported.

---

## Inputs, in order of preference

### 1. BibTeX with `file = {...}` — the strongest link

A BibTeX file exported from a reference manager records the filenames of the PDFs the author actually
uploaded:

```bibtex
@article{5667954,
  title = {Postoperative complications and their association with post-traumatic stress disorder},
  doi = {10.1016/j.jvs.2022.10.056},
  file = {1-s2.0-S0741521422025332-main.pdf}
}
```

That `file` field is an author-supplied manifest: it says *this entry is this PDF*. It is the only
input where the link between a citation and a source document is declared rather than inferred, so it
is tried first. Zotero's `description:path:format` form is handled.

### 2. A directory of source PDFs

When filenames are opaque (Elsevier's `1-s2.0-S0741521422025332-main.pdf` is a PII, not a DOI), the
DOI is mined from page 1 of each PDF. Page-1-only extraction keeps this cheap: roughly 0.03 s per
file, so sixty sources cost about two seconds. Failing that, a DOI-shaped filename is used.

Only sources with no declared manifest are mined from the directory, so the manifest always wins.

### 3. The document's own numbered reference list

Every reference entry's DOI is read out of its text, and the entry's number becomes the
`citation_number` the prose actually uses. This is what lets a numeric-style document be graded with
no bibliography file at all.

**Entries are matched to a BibTeX source by content, never by position.** A BibTeX file is commonly
ordered by citekey while a reference list is alphabetical. Positional matching would silently attribute
citation `[1]` to the wrong paper — the worst possible failure for this tool, because it produces a
confident wrong answer. The order is: DOI, then title containment, then first-author surname plus
year. When a match happens by something other than DOI and the DOIs disagree, that is recorded as a
warning rather than resolved quietly.

If no bib file is supplied, each reference entry becomes its own source.

### 4. A `sources.csv` ledger from this repository's review skills

Already verified, with locators and recorded findings. The ledger's own `verification_status` and
`retraction_status` stand.

The recorded extraction is used as evidence, but **not all of it is equally strong**, and the
distinction decides whether a sentence can come out green:

| Columns | Availability | Can it support a result claim? |
|---|---|---|
| `main_finding`, `effect_estimate`, `key_outcomes` | `full_text` | yes — these are what the study found |
| only `population`, `intervention`, `comparator` | `metadata_only` | **no** — this describes the study, not its results |

A ledger row whose finding fields are all `not_reported`/`not_applicable` is metadata, not evidence:
sentences citing it are `unverifiable` (D05), not green. Treating a study description as evidence
would let a citation to a source whose findings were never extracted pass as supported, which is the
substitution this skill exists to prevent. `not_reported` and `not_applicable` are placeholders, never
findings, and are filtered out rather than searched.

### 5. A plain DOI/PMID list

One per line or comma-separated. `#` comments and blank lines are ignored.

---

## The claim ledger

`--claims claims.csv` makes `[claim:C001]` markers resolve to the sources the claim ledger records for
them. This is what makes a manuscript drafted by this repository's review skills a first-class input:

```text
Statin therapy reduced events (HR 0.80) [claim:C001] [src:S001].
```

Here `[src:S001]` resolves directly, and `[claim:C001]` resolves through the ledger to `S001`. Both
paths reach the same source, which is deduplicated before the rule ladder runs.

A claim marker **is not a citation on its own**. `[claim:C006]` with no `[src:...]` says "this is
claim 6", not "this is who established it". Such a sentence is `unattributed` (D02), not verifiable
and not a conflict — the claim is the author's own registered assertion.

A claim naming a `source_id` the ledger does not contain is recorded in `unresolved_tokens` with the
reason, rather than being dropped.

---

## Evidence attachment

For each source, in order:

1. the file named in its BibTeX `file` field, matched against the supplied directory by exact
   basename, then by stem, then by containment;
2. a PDF whose page-1 text contains the source's DOI;
3. a same-stem `.txt` or `.md` sidecar (pre-extracted text, useful for scanned papers you have already
   run OCR on yourself);
4. with the network enabled, a Europe PMC abstract for the DOI;
5. otherwise `metadata_only`.

PDF text is extracted by `_pdftext.py`, which tries `pdftotext -layout` (poppler) and falls back to
the optional `pypdf` package. When neither is available it **refuses**, with a message naming both
routes, rather than returning an empty string — an empty string would silently turn a tooling problem
into an accusation against the writer.

The refusal text:

> cannot read the text layer of {name}: no PDF text extractor is available. Install poppler
> (`brew install poppler` / `apt install poppler-utils`) or the optional Python package
> (`pip install pypdf`), or export the document to .txt and pass that instead. Refusing to grade
> against unreadable evidence.

### Scanned PDFs

A text layer yielding fewer than 50 characters per page is treated as failure, not as thin evidence,
and recorded as `unavailable` with the reason. There is no OCR: inventing text for a source and then
grading a claim against it would be worse than admitting the source could not be read.

### Page-accurate locators

`pdftotext` page breaks are preserved, so every extracted offset maps to a page number and every note
can cite `p.13`. This is what makes a red verdict checkable: the note gives the source, the page and
the quoted value, and a reader can open the PDF and confirm it in seconds.

---

## Automatic acquisition

When a source has no readable evidence, the tool tries open-access routes in tiers and records every
attempt. Tiers, endpoints, strength levels and the identity check that gates their use are documented
in `evidence-and-limits.md`; this file describes the *linking* of sources to files, which is a different
question and comes first.

Measured on one real 60-DOI clinical reference list: **20/60 = 33.3%** yielded usable full text, all of
it from the Europe PMC full-text tier; the open-access-PDF and CLI tiers contributed nothing on that
corpus. Acquisition roughly doubles coverage on an open-access-heavy list and does nothing on a
subscription-only one, so it can never be relied on to complete a bibliography. That is why a gap blocks
the run and produces a worklist rather than a low coverage figure.

## DOI resolution

`_resolve.py` consults three keyless authorities:

| Authority | Used for |
|---|---|
| Crossref | DOI metadata; `update-to` and `relation` retraction/correction signals |
| OpenAlex | `is_retracted`, and a second opinion on the title |
| Europe PMC | an abstract, usually the only evidence available for a paywalled source |

A failed lookup is recorded as `failed` or `unverified` with the reason. A network failure and a
nonexistent DOI are **different findings** and are never conflated: the first is our problem, the
second is a finding about the document.

### `--offline`

Makes no network call at all. Every source is graded on local evidence only, which is the
reproducible mode the test suite runs in. In offline mode:

* a DOI we hold locally still identifies the source, but the source stays `unverified`, because
  verification means an authority confirmed it;
* `retraction_status` stays `not_checked` and that is recorded per source;
* the report discloses that no DOI was resolved over the network.

Consequences to expect: with `--offline` and no supplied PDFs, every cited sentence is
`unverifiable` (D05). That is the correct outcome, not a bug.

---

## Why `unverifiable` exists

Four states are not enough. Consider a sentence citing a real, identified, correctly cited paper whose
PDF you did not supply. It is not `attributed` — nothing was checked. It is not `unattributed` — the
citation is there. It is certainly not `conflict`. The honest answer is "this report cannot tell", and
folding that into green is exactly how a citation report becomes reassuring without being useful.
