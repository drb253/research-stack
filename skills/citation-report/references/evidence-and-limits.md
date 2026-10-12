# Evidence: how it is obtained, how strong it is, and what it may claim

Four separate questions, answered separately. Conflating any two of them is how a citation report
becomes reassuring without being useful.

| Question | Recorded as |
|---|---|
| Where did this text come from? | `evidence_origin`, `acquisition_method`, `acquisition_endpoint`, `acquired_at` |
| Was the work's identity confirmed? | `identity_check`, and `link_method` / `link_verified` per citation |
| How strong is the evidence? | `evidence_strength` |
| Could we check the sentences that needed checking? | the `insufficient_evidence` status and the worklist |

---

## Acquisition: what the tool will and will not do

Tried in order for every source that lacks usable evidence. Every attempt is recorded, successful or
not, using the vocabulary this repository already uses for "we tried and this is what happened"
(`returned`, `empty`, `unavailable`, `error`, `user_supplied`).

| Tier | Mechanism | Strength | Locator | Enabled by |
|---|---|---|---|---|
| A | a supplied file: a BibTeX `file = {...}` manifest, `--pdf-dir`, or a `.txt` sidecar | `primary` | page-accurate (`p.13`) | always |
| B | open-access full text from Europe PMC (`fullTextXML`, keyless, requires `isOpenAccess == "Y"`) | `primary` | section-based (`Results`) | `--acquire api` |
| C | open-access PDF resolved through OpenAlex, read with the `pdftotext`/`pypdf` cascade, cached under `--cache-dir` | `primary` | page-accurate | `--acquire pdf` |
| D | the vendored `paper-search` package, invoked as an optional subprocess when it is installed | `primary` | `full text (no page numbers)` — its stdout carries no page boundaries | `--acquire cli` |
| E | the published abstract (Europe PMC, else Crossref) — this is the pre-existing `_resolve` path, **not** part of `_acquire`; it runs whenever metadata resolution runs | `abstract` | `abstract` | not offline |
| F | a ledger's recorded extraction | `recorded_estimate` or `prose_summary` | `ledger record` | always |
| G | nothing obtained | `none` | — | → the worklist |

Tier B is the one that pays. Tier C actively disappoints: publisher `/pdf` endpoints answer a
non-browser client with `403` or an HTML error page, and where OpenAlex has no `pdf_url` the fallback
`oa_url` is a bare `doi.org` resolver, which is a landing page rather than a file — the module records
`unavailable` rather than fetching it. Tier D only works by re-reading a PMCID that tier B has already
established is open access, because the package's other routes fail by design or return `403`. C and D
are kept because they cost nothing when they fail and they carry other corpora, but they are not the
reason to switch acquisition on.

**Measured on a real 60-DOI clinical reference list: 20/60 = 33.3% usable full text, all 20 from tier
B. Tier C scored 0/60 and tier D 0/60, with zero identity mismatches.** The failures break down as 26
records Europe PMC reports as not open access, 13 with no Europe PMC record at all, and — from OpenAlex
— 28 with no `pdf_url` plus 12 whose `pdf_url` sits on a publisher host that refuses a non-browser
client. That fraction is specific to a corpus; an earlier probe of 14 of the same DOIs suggested about
14%, which is why the figure in this file is the measured 20/60 rather than an extrapolation.

**Never, in any tier:** bypassing a paywall, using credentials you did not provide, or scraping a
publisher's page. A paywalled source becomes a worklist entry naming what to supply.

**Why this is not a fix for everything.** It roughly doubles coverage on an open-access-heavy list and
does nothing on a subscription-only one, and it can never be relied on to complete a bibliography. That
is why the tool blocks and hands over a worklist rather than reporting a low coverage figure. It will
never overstate: a tier that cannot obtain text records `unavailable` with the reason, and a source
that stays at `none` appears on the worklist.

### Identity is verified before text is used

Before any acquired text may support a verdict: the DOI must match the source's DOI, and where a title
is available it must pass the title-agreement test against the entry the document cites. On any
disagreement the text is **discarded**, `identity_check` is set to `mismatch`, and nothing is concluded
from it. Grading a sentence against the wrong paper and reporting the result confidently is the worst
outcome this tool can produce, so the check is strict and discarding is the default.

---

## Strength: what each kind of evidence may claim

| Strength | What it is | May check a value? | May convict a contradiction? |
|---|---|---|---|
| `primary` | text extracted from the source itself | yes | **yes** |
| `recorded_estimate` | a value the ledger copied verbatim (`effect_estimate`, `n_participants`, `follow_up`) | yes | **yes** |
| `prose_summary` | the extractor's own words (`main_finding`, `key_outcomes`) | yes | **no** |
| `abstract` | the published abstract | yes | **no** |
| `none` | nothing readable | no | no |

A value copied verbatim is machine-comparable: `HR 0.80` either appears in the record or it does not.
A sentence the extractor wrote — "statin therapy reduced events" — is an interpretation, and an
interpretation may not convict. Abstract evidence is the source's own words but abridged, so a value
missing from it says nothing about whether the paper contains it.

Coverage reports green support broken down by strength
(`attributed_by_strength`), and support that rests only on a prose summary raises a countable gate
warning (`SUMMARY_ONLY_SUPPORT`) rather than blending into the total.

---

## The red bar

A red finding asserts that a citation resolves to nothing, that a cited source is retracted, or that
the document's value contradicts the source's. Each is an accusation, so each must clear three bars:

1. **Verified identity.** A DOI that was resolved, a file the user supplied, or a ledger's declared
   `S` id. A link inferred from a title or year match is a guess about *which work this is*, and a
   guess may not convict.
2. **Machine-comparable evidence.** `primary` text or a `recorded_estimate`. Never a prose summary.
3. **Positive evidence.** The same named measure with a different value, quoted, with a locator.

Failing bar 1 produces rule `D11`; failing bar 2 produces `D12`. Both land on `unverifiable` with the
reason and with what would confirm it, so the finding is disclosed without being asserted.

`report_gate.py` re-checks all three from the recorded verdicts, so a hand-edited file cannot smuggle
an unsupported accusation past the gate either
(`CONFLICT_LINK_INFERRED`, `CONFLICT_EVIDENCE_TOO_WEAK`).

**Accepted cost:** conflict recall drops. Some genuine contradictions visible only through a prose
summary are no longer red. That is the intended trade: the benchmark reports the change rather than
absorbing it, and conflict precision stays at 1.000.

---

## Sufficiency: when the inputs cannot support findings

- `citing_sources` — the sources at least one graded sentence resolves to.
- `checkable` — those with evidence strong enough to test a value.

**Default policy (`strict`): every citing source must be checkable.** Otherwise the run is
`insufficient_evidence`, exits **3**, and writes `evidence_worklist.csv`. `--require-evidence 0.6`
offers a share policy for teams that prefer one; it is not the default, because a report that checked
90% of its citations and says "pass" is the reassurance this tool refuses to give.

`--allow-insufficient` proceeds. The status in the JSON stays `insufficient_evidence` and the issue
becomes a warning, so the override is visible in the artefact rather than only in a shell history.

A caveat worth reading: if none of the affected sentences assert a checkable value, supplying the
missing sources moves them from `unverifiable` to a **synthesis** judgement rather than to a checked
result. The report says so in as many words, because "supply the PDFs and this sentence will be
verified" would be a promise the tool cannot keep.

### A failed lookup is not an absent source

The worklist's instruction depends on **why** the source is unreadable, because the two cases need
different actions:

| What happened | Worklist wording |
|---|---|
| every attempt failed with an error (e.g. the API returned `HTTP 503`) | "a lookup failed rather than the source being absent … retry the run first" |
| the source is genuinely not open access, or holds no finding | "drop the source file into `--pdf-dir` …" |

This distinction was added after a real run in which Europe PMC rate-limited sixty consecutive abstract
lookups and every one was recorded as `abstract unavailable`. The worklist then advised the user to go
and find sixty PDFs, when waiting a minute and re-running was the correct action. Telling someone to
supply files they may not need is a false instruction, and it is the same class of error as reporting a
gap as a finding. DOI resolution is now paced (0.35 s between sources) to avoid earning the 503 in the
first place, and `_resolve.Resolution.abstract_error` stores the failure separately from
`abstract == ""` so the two can never be confused again.

### Closing the loop

```bash
# 1. the run blocks and writes the worklist
python3 scripts/report.py report --document draft.docx --bib refs.bib --out-dir citation-report/
#    exit 3; citation-report/evidence_worklist.csv names what is missing

# 2. supply what you can (a PDF, or a text export named with the DOI or the title)
python3 scripts/report.py worklist --document draft.docx --bib refs.bib \
    --pdf-dir sources/ --worklist citation-report/evidence_worklist.csv
#    exits non-zero while any gap remains, zero once they are all closed

# 3. the same run now grades what it could not grade before
python3 scripts/report.py report --document draft.docx --bib refs.bib \
    --pdf-dir sources/ --out-dir citation-report/
```

A file is matched to a source by a DOI-shaped filename (slashes written as `_` or `-`), by a source id
or citekey in the name, by a title fragment, or by a DOI mined from the file's own text. That is how
"drop the file in and re-run" actually works.

---

## Intake preconditions

Before any finding is reported, four questions about whether the tool understood the document:

| Code | Fails when | Blocks |
|---|---|---|
| `CITATION_STYLE_UNRECOGNISED` | ≥10 reference entries and no citation marker in the prose | yes |
| `TRIGGER_LANGUAGE_UNSUPPORTED` | ≥50 sentences and under 2% matched any attribution signal | yes |
| `SENTENCE_SPLIT_SUSPECT` | median sentence over 400 characters, or one sentence over 20% of a large document | yes |
| `NO_SOURCE_LIST` | the prose cites something and there is no reference list, bib, ledger or DOI list | yes |

Each records its observed value whether it passes or fails, so the artefact shows not only the findings
but the basis on which they were made. The language check also reports whether any *language-dependent*
signal fired (superlative, vague attribution, borrowed definition), because a non-English document full
of numbers clears the percentage test while never matching a phrase.

A failure makes the run `insufficient_input` and exits **4**. Findings are still listed, marked
provisional in the banner, because a reader diagnosing a parser problem needs to see what the parser
produced.
