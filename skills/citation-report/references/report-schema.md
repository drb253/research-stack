# Report schema

Three files carry every machine-checkable fact. The renderers read `verdicts.json` and nothing else,
which is what makes the report reproducible: correct a verdict by hand, re-render, and no
classification runs.

All three are written into `--out-dir`.

---

## 1. `verdicts.json` — the report's source of truth

```json
{
  "schema": "citation-report/verdicts/1",
  "generated": "2026-01-01",
  "document": {
    "path": "draft.docx", "format": "docx", "method": "native",
    "chars": 242418, "paragraphs": 163, "sentences": 1338,
    "narrative_sentences": 1027, "warnings": []
  },
  "bundle": {
    "sources": [ "...see sources_report.csv..." ],
    "reference_entries": 48, "claims": 6, "offline": true,
    "evidence": {"metadata_only": 62},
    "retraction": {"not_checked": 62},
    "warnings": []
  },
  "coverage": { "...see coverage.json..." },
  "gate": {"status": "pass", "errors": 0, "warnings": 174},
  "verdicts": [ "one entry per graded sentence" ]
}
```

`bundle.sources` is the full `Source.to_dict()` for every source, so the file is self-contained: a
reader can see exactly what evidence each verdict rested on without reopening the inputs.

### A verdict entry

```json
{
  "sentence_id": "N0002",
  "text": "Statin therapy reduced major adverse cardiovascular events (HR 0.80) [src:S001].",
  "char_start": 244,
  "char_end": 320,
  "paragraph": 5,
  "section": "Results",
  "state": "attributed",
  "rule_id": "D09",
  "severity": "info",
  "requires_citation": true,
  "triggers": [{"code": "STATISTIC", "match": "", "start": 0, "end": 0}],
  "markers": [{"kind": "ledger_source", "raw": "[src:S001]", "values": ["S001"], "start": 62, "end": 72}],
  "quantities": [{"kind": "measure", "raw": "HR 0.80", "values": [0.8], "measure": "HR", "start": 55, "end": 62}],
  "unresolved_tokens": [],
  "sources": [
    {
      "source_id": "S001", "citekey": "S001", "citation_number": "",
      "marker": "S001", "marker_kind": "ledger_source",
      "doi": "10.1056/nejmoa1234567",
      "title": "Statin therapy and cardiovascular events",
      "verification_status": "verified", "retraction_status": "clear",
      "evidence_availability": "full_text", "evidence_method": "ledger",
      "locator": "abstract",
      "quote": "in therapy reduced major adverse cardiovascular events HR 0.80 ..."
    }
  ],
  "missing_numbers": [],
  "note": "Every value in the sentence (HR 0.80) is present in the evidence of S001."
}
```

| Field | Meaning |
|---|---|
| `sentence_id` | `N` + digits, unique, stable within a run |
| `char_start` / `char_end` | offsets into `document.text`; **must** still locate `text` on re-validation |
| `state` | one of the six states in `_common.VERDICT_STATES` |
| `rule_id` | one of the ids in `RULES`; determines `state` and `severity` |
| `severity` | derived from the rule, not stored independently — a mismatch is rejected on load |
| `requires_citation` | whether an attribution-requiring signal fired; the coverage denominator |
| `triggers` | why it fired, so the count is auditable |
| `markers` | every citation marker found, typed (`numeric`, `parenthetical`, `bracket`, `ledger_source`, `ledger_claim`, `author_year`) |
| `quantities` | every numeric assertion, typed, with its measure label where it has one, and a `checkable` flag saying whether it is distinctive enough to test against evidence (see `verdict-rules.md`) |
| `unresolved_tokens` | markers no source matched, with the reason |
| `sources` | the resolved sources, each with locator and a quoted evidence span |
| `missing_numbers` | values not found in the evidence (populated for D07 only) |
| `contradiction` | present only for D08: `measure`, `sentence_value`, `evidence_value`, `source_id`, `locator`, `quote` |
| `note` | the human-readable finding, identical in every output format |
| `advisory` | absent unless the advisory channel is on; never affects `state`, `rule_id` or `severity` |

`verdicts.from_dict` validates on load and **rejects** rather than renders:

* an unknown `state` or `rule_id`;
* a `state` that does not match the `rule_id`'s required state;
* a duplicate or malformed `sentence_id`;
* a missing or non-integer `char_start` / `char_end`;
* an advisory grade outside the controlled vocabulary.

---

### Statuses and exit codes

Precedence: `insufficient_input` > `insufficient_evidence` > `fail` > `pass`.

| Status | Exit | Meaning |
|---|---|---|
| `pass` | 0 | findings, if any, are warnings only, and the evidence was adequate |
| `fail` | 1 | error-severity findings about the document |
| `insufficient_evidence` | 3 | the document was readable; not enough source text was held |
| `insufficient_input` | 4 | the document itself could not be read well enough to make findings |

`--allow-insufficient` keeps the status and restores the findings-based exit code, so the override is
recorded in the artefact rather than only in a shell history. `2` remains an argparse usage error.

### `input_gaps[]`

A run that cannot read the document at all is `insufficient_input` and carries a top-level
`input_gaps[]` array alongside the `INSUFFICIENT_INPUT` issue:

```json
"input_gaps": [
  {
    "kind": "no_pdf_extractor",
    "detail": "cannot read the text layer of paper.pdf: no PDF text extractor is available. …",
    "how_to_close": "install poppler (`brew install poppler` / `apt install poppler-utils`) or …"
  }
]
```

`kind` is one of:

| `kind` | what happened | what closes it |
|---|---|---|
| `no_text_layer` | an extractor ran and the file is a scan | install tesseract and export the scan, or supply a text export |
| `no_pdf_extractor` | nothing on the machine can read a PDF | install poppler or `pypdf`, or pass a `.txt` export |
| `unreadable_pdf` | an extractor is installed but could not decode the file | supply a readable copy or a text export |
| `no_pdf_rasterizer` | tesseract is installed but no page rasteriser is | install poppler, or supply a text export |
| `ocr_failed` | OCR was attempted and the engine or the rasteriser failed | the detail names the failure |
| `ocr_empty` | OCR read the pages and found no text | check the scan is legible and the language data matches |
| `ocr_page_limit` | the scan is longer than `--ocr-max-pages` | raise the limit, or supply a text export |
| `ocr_language_missing` | the requested language data is not installed | install it, or pass `--ocr-lang` with one that is |

`how_to_close` is the action that removes the gap.

A run that *did* read a scan carries a `transcription` block instead, and never blocks for it:

```json
"transcription": {
  "document_transcribed": true,
  "document_transcription": "tesseract:eng",
  "sentences_resting_on_ocr": 2
}
```

Each source record carries `transcribed` and `transcription`, and a transcribed source's
`evidence_origin` begins `ocr:` rather than `file:` — so a reader can see which findings rest on a
machine's reading without parsing a method name. A contradiction where either side was transcribed is
`unverifiable` under rule D13, never `conflict`. The field exists so that "we could not read
this" is never a shape a caller could mistake for a finding, and so a gap can be closed without
parsing the prose.

### New per-verdict fields

| Field | Meaning |
|---|---|
| `evidence_strength` | `primary`, `recorded_estimate`, `prose_summary`, `abstract`, `none` |
| `evidence_origin` | where the text came from, e.g. `file:paper.pdf`, `europepmc:fullTextXML`, `ledger:effect_estimate` |
| `link_confidence` | `exact` (declared or DOI-verified), `inferred` (title or year match), `none` |

Each entry in a verdict's `sources[]` carries the same three, plus `link_method` and `link_verified`, so
a reader can see the quality of what each colour rested on rather than only that evidence existed.

A top-level `evidence` block carries the input side: `citing_sources`, `citing_sources_checkable`,
`unverifiable_sentences`, `undecided_sentences`, `policy`, `blocking`, and the `reason` list. A
`preconditions` array carries the four intake checks with their observed values.

### `evidence_worklist.csv`

One row per source that could not be read:
`source_id, citation_number, citekey, doi, pmid, title, sentences_referencing,
sentences_needing_evidence, retrieval_status, evidence_strength, evidence_availability, attempts,
reason, suggested_action, worklist_key, resolved`.

## 2. `coverage.json` — the arithmetic, validated to balance

```json
{
  "sentences_total": 9,
  "sentences_requiring_citation": 6,
  "sentences_with_support_claim": 8,
  "sentences_not_requiring": 3,
  "states": {"attributed": 1, "synthesis": 2, "unverifiable": 1,
             "unattributed": 1, "conflict": 2, "no_citation_needed": 0},
  "rules": {"D02": 1, "D03": 1, "D04": 1, "D07": 1, "D09": 1, "D10": 2},
  "severity": {"error": 2, "warning": 2, "info": 3},
  "citation_coverage": {
    "numerator": 3, "denominator": 8, "ratio": 0.375, "percent": 37.5,
    "definition": "(attributed + synthesis) / all sentences carrying a claim",
    "excluded_from_denominator": 1
  },
  "attributed_share_of_all_sentences": {
    "numerator": 1, "denominator": 9, "ratio": 0.1111,
    "definition": "attributed / all graded sentences; the honest single scalar"
  },
  "attributed_by_strength": {"primary": 1, "recorded_estimate": 0, "prose_summary": 0},
  "uncheckable_by_reason": {"D05": 1, "D07": 1},
  "conflict_link_confidence": {"exact": 1},
  "uncheckable": {"numerator": 2, "denominator": 9,
                  "detail": "cited and identified, but no evidence was held to check against"},
  "sources": {
    "total": 2, "by_evidence": {"full_text": 2}, "by_retraction": {"clear": 1, "retracted": 1},
    "with_evidence": 2, "retracted": 1
  },
  "claims": {"registered": 6}
}
```

`coverage.validate` refuses to emit a summary whose parts do not sum to its total: state counts
against `sentences_total`, requiring plus not-requiring against the total, the coverage numerator
against the state counts, the denominator against `sentences_with_support_claim`, rule counts and
severity counts against the total, and any unknown rule id.

**Why the denominator is "carrying a claim" rather than "requiring a citation".** The trigger count
is informative but it is the wrong denominator. A cited sentence containing no statistic — a
conclusion, a comparison — fires no trigger, yet it is plainly a claim that needs its citation. Using
the trigger count would place such a sentence in the numerator while excluding it from the
denominator, so the numerator would not be a subset and the ratio could in principle exceed 100%. The
denominator is therefore every sentence the report had something to say about, which is exactly
`sentences_total - states["no_citation_needed"]`. `sentences_requiring_citation` is still reported,
because a reader wants to know how many sentences demanded attribution on their own terms. `report_gate.py` recomputes the whole thing from
the verdict list and fails if the recorded file disagrees — so a hand-edited `coverage.json` cannot
pass the gate.

**There is no scalar "quality score".** A number a reader cannot recompute is decoration. If one is
wanted, the honest definition is `attributed_share_of_all_sentences`, which is printed under that
name. Note it is deliberately harsh: a document of unverifiable sentences scores zero rather than
being flattered by its light-green synthesis.

---

## 3. `sources_report.csv` — the registry

One row per source. Columns, in order:

```text
source_id,citekey,citation_number,doi,pmid,title,year,container,resolution,
verification_status,retraction_status,evidence_availability,evidence_method,
evidence_chars,evidence_locator,file_path,title_claimed,title_match,warnings
```

| Column | Allowed values |
|---|---|
| `source_id` | `S` + 3 digits, unique |
| `resolution` | `ledger`, `bib`, `pdf-folder`, `reference-list`, `doi-list` |
| `verification_status` | `verified`, `unverified`, `failed` |
| `retraction_status` | `not_checked`, `clear`, `retracted`, `expression_of_concern`, `corrected` |
| `evidence_availability` | `full_text`, `abstract`, `metadata_only`, `unavailable` |
| `evidence_method` | `pdftotext`, `pypdf`, `text`, `europepmc`, `ledger` |
| `evidence_locator` | `p.1`, `abstract`, `reference list`, `ledger record` |
| `title_match` | `match`, `mismatch`, `not_checked` |
| `link_method` | `doi`, `title`, `author-year`, `unlinked` (recorded when a reference-list entry was matched to a bib source) |

`evidence_availability` is the column that governs what the report can conclude:

* `full_text` — a supplied PDF or text file was read; page-accurate locators are available;
* `abstract` — Europe PMC returned an abstract; locators say `abstract`, and every note relying on it
  discloses that;
* `metadata_only` — the work is identified but nothing readable was held. Sentences citing it become
  `unverifiable` (D05), never green;
* `unavailable` — a source file was supplied but could not be read, with the reason in `warnings`.

A source with `evidence_availability` of `metadata_only` or `unavailable` can never produce an
`attributed` verdict. That is the mechanism behind the promise that the report never paints green
without evidence.

---

## Advisory file

Passed with `--advisory <path>`. Not part of `verdicts.json`'s required shape; when present, each
verdict gains an `advisory` object.

```json
{
  "grades": {
    "N0002": {
      "grade": "direct_support",
      "quote": "Statin therapy reduced major adverse cardiovascular events",
      "source_id": "S001",
      "model": "local-classifier-v1"
    }
  }
}
```

The `disclosure` field is forced to `advisory, model-generated, not a gate input` on load, regardless
of what the file says. An unknown `grade` is rejected.
