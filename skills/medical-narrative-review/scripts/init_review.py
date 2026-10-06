"""Scaffold a medical narrative review workspace with empty, validated ledgers.

Creates a new directory (never overwrites) containing the source ledger, claim
ledger, search log, PRISMA count file, marked manuscript draft, and the display
and final-output folders. No network access, no third-party packages.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from _common import (
    InputError,
    run,
    slugify,
    write_new_text,
)

TOOL = "init_review"

SOURCE_FIELDS = [
    "source_id",
    "title",
    "authors",
    "container",
    "year",
    "volume",
    "issue",
    "pages",
    "doi",
    "pmid",
    "pmcid",
    "publication_type",
    "peer_reviewed",
    "study_design",
    "population",
    "intervention",
    "comparator",
    "n_participants",
    "follow_up",
    "key_outcomes",
    "main_finding",
    "effect_estimate",
    "verification_status",
    "verifier",
    "verified_date",
    "locator",
    "retraction_status",
    "inclusion_status",
    "exclusion_reason",
    "retrieval_status",
    "theme",
    "notes",
]

CLAIM_FIELDS = [
    "claim_id",
    "section",
    "claim_kind",
    "direction",
    "claim_summary",
    "source_ids",
    "verification_status",
    "certainty",
    "analysis_intent",
    "notes",
]

SEARCH_FIELDS = [
    "search_id",
    "database",
    "platform",
    "query_string",
    "filters",
    "date_run",
    "hits_retrieved",
    "availability",
    "records_screened",
    "records_included",
    "notes",
]

PRISMA_TEMPLATE = {
    "review_type": "narrative",
    "review_title": "",
    "search_date_range": "",
    "databases_searched": [],
    "registers_searched": [],
    "identification": {
        "records_from_databases": 0,
        "records_from_registers": 0,
        "records_from_other_methods": 0,
        "duplicates_removed": 0,
    },
    "screening": {
        "records_screened": 0,
        "records_excluded": 0,
    },
    "retrieval": {
        "reports_sought": 0,
        "reports_not_retrieved": 0,
    },
    "eligibility": {
        "reports_assessed": 0,
        "reports_excluded": 0,
        "exclusion_reasons": {},
    },
    "included": {
        "studies_included": 0,
        "sources_verified": 0,
    },
}


def _csv_text(fields: list[str]) -> str:
    import io

    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    return handle.getvalue()


def _ledger_readme(title: str) -> str:
    return (
        "# Ledger conventions\n\n"
        "Review title: " + title + "\n\n"
        "## IDs\n\n"
        "- `S` IDs: one per retrieved record in `sources.csv` (for example `S001`).\n"
        "- `C` IDs: one per atomic claim in `claims.csv` (for example `C001`).\n\n"
        "## Markers used in `draft.md`\n\n"
        "```text\n"
        "Sentence stating a verified finding. [claim:C001] [src:S001,S004]\n"
        "```\n\n"
        "Both markers stay on the same line while drafting. `build_reference_list.py`\n"
        "replaces `[src:...]` with numbered citations in first-appearance order and strips\n"
        "the `[claim:...]` markers to produce `final/manuscript_cited.md`.\n\n"
        "## Rules\n\n"
        "1. Never invent a row. A row exists because a lookup or the user returned it.\n"
        "2. Copy bibliographic fields from the retrieved record, never from recall.\n"
        "3. Use `not_reported` for fields the source does not report. Never leave blank.\n"
        "4. `verification_status=verified` requires `verifier`, `verified_date`, and `locator`.\n"
        "5. Keep only metadata and your own words here. No source documents, no patient data.\n"
    )


def _unresolved(title: str) -> str:
    return (
        "# Unresolved items\n\n"
        "Review: " + title + "\n\n"
        "Every placeholder, failed lookup, conflicting source, and unverifiable claim is\n"
        "recorded here until a human resolves or removes it. An empty placeholder list is a\n"
        "prerequisite for submission; a non-empty one must be disclosed to co-authors.\n\n"
        "## Placeholders in the manuscript\n\n"
        "| Marker | Section | Why unresolved | Owner | Status |\n"
        "|---|---|---|---|---|\n"
        "| _none yet_ |  |  |  |  |\n\n"
        "## Failed or unavailable lookups\n\n"
        "| Source attempt | Tool | Result | Date | Alternative found |\n"
        "|---|---|---|---|---|\n"
        "| _none yet_ |  |  |  |  |\n\n"
        "## Conflicting evidence\n\n"
        "| Claim (C ID) | Conflict | Sources | Decision |\n"
        "|---|---|---|---|\n"
        "| _none yet_ |  |  |  |  |\n\n"
        "## Deliberate limitations accepted\n\n"
        "- \n"
    )



def _scope(doc_id: str, title: str, style: str, review_type: str) -> str:
    return (
        "# Scope lock\n\n"
        "Document ID: " + doc_id + "\n"
        "Working title: " + title + "\n"
        "Review type: " + review_type + "\n"
        "Citation style: " + style + "\n\n"
        "Fill every line. Write `not_specified` rather than leaving a blank, and add the\n"
        "item to `UNRESOLVED.md` so it cannot be forgotten.\n\n"
        "## Question framing\n\n"
        "- Population: \n"
        "- Intervention or exposure: \n"
        "- Comparator: \n"
        "- Outcome(s): \n"
        "- Time frame / follow-up of interest: \n"
        "- Clinical setting and audience: \n\n"
        "## Venue and limits\n\n"
        "- Target journal / venue: \n"
        "- Article type and word limit: \n"
        "- Maximum tables / figures: \n"
        "- Citation style and reference limit: \n"
        "- Author instructions retrieved on (date): \n"
        "- Funding / conflict-of-interest requirements: \n\n"
        "## Eligibility\n\n"
        "- Years searched (from - to): \n"
        "- Languages: \n"
        "- Designs included: \n"
        "- Publication types included: \n"
        "- Human / animal / in vitro: \n"
        "- Explicitly out of scope: \n\n"
        "## Assumptions made when the user was not specific\n\n"
        "- \n\n"
        "## Success criteria\n\n"
        "- The gate (`scripts/gate.py`) passes with zero error-severity issues.\n"
        "- No citation appears that was not identifier-verified at drafting time.\n"
        "- Every numeric value traces to a `sources.csv` row with a locator.\n"
        "- `UNRESOLVED.md` contains no open placeholders.\n"
    )


def _draft(doc_id: str, title: str) -> str:
    return (
        "<!-- Replace each [[TODO]] with content plus markers on the same line:\n"
        "     [claim:C001] [src:S001,S004] -->\n\n"
        "# " + title + "\n\n"
        "[[TODO author list and affiliations, per the target journal's authorship criteria]]\n\n"
        "## Abstract\n\n"
        "### Background\n\n[[TODO 2-3 sentences, no citations]]\n\n"
        "### Objective\n\n[[TODO one sentence: question and population]]\n\n"
        "### Methods\n\n[[TODO databases, date range, search date, selection approach, source count]]\n\n"
        "### Results\n\n[[TODO key findings, strongest designs named; numbers only with markers]]\n\n"
        "### Conclusions\n\n[[TODO proportionate and hedged; no new information]]\n\n"
        "Keywords: [[TODO 4-8 terms; mirror MeSH where the journal requires it]]\n\n"
        "## Introduction\n\n[[TODO clinical importance, what is known, the gap, the objective]]\n\n"
        "## Methods\n\n"
        "### Search strategy\n\n[[TODO databases, exact queries (see search_log.csv), dates, filters]]\n\n"
        "### Selection and verification\n\n[[TODO inclusion criteria, screening, deduplication, verification]]\n\n"
        "### Data extracted\n\n[[TODO what was extracted and how certainty was judged]]\n\n"
        "## [[TODO thematic section 1: mechanism and biology]]\n\n"
        "## [[TODO thematic section 2: clinical evidence]]\n\n"
        "## [[TODO thematic section 3: safety and special populations]]\n\n"
        "## [[TODO thematic section 4: guidelines, implementation, and cost]]\n\n"
        "## Discussion\n\n"
        "### Summary of main findings\n\n### Clinical implications\n\n"
        "### Comparison with other reviews\n\n### Strengths and limitations\n\n"
        "### Future research\n\n"
        "## Conclusions\n\n"
        "[[TODO no new claims, no numerical values, no citations to new sources]]\n\n"
        "## Declarations\n\n"
        "- Funding: \n- Conflicts of interest: \n- Author contributions (CRediT): \n"
        "- Data availability: \n- Use of AI tools: [[TODO exact wording per journal policy]]\n\n"
        "## Appendix A: Search strategy\n\n[[TODO paste the search_log.csv queries verbatim]]\n\n"
        "## Appendix B: Screening flow\n\n[[TODO figure generated from prisma_counts.json]]\n\n"
        "## Appendix C: Unresolved items\n\n[[TODO mirror UNRESOLVED.md and list every placeholder]]\n"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a medical narrative review workspace with empty validated ledgers. "
            "The output directory must not exist; nothing is ever overwritten."
        )
    )
    parser.add_argument("--out-dir", required=True, help="new workspace directory")
    parser.add_argument("--document-id", required=True, help="short slug, for example sepsis-biomarkers")
    parser.add_argument("--title", required=True, help="working title")
    parser.add_argument(
        "--review-type",
        default="narrative",
        choices=["narrative", "narrative_with_systematic_search", "scoping_informed"],
        help="declared review type; recorded in scope.md and prisma_counts.json",
    )
    parser.add_argument(
        "--style",
        default="vancouver",
        choices=["vancouver", "ama", "apa", "elsevier"],
        help="citation style used by build_reference_list.py",
    )
    return parser


def cli() -> int:
    args = build_parser().parse_args()
    out_dir = Path(args.out_dir)
    if out_dir.exists() or out_dir.is_symlink():
        raise InputError("output directory already exists; refusing to overwrite")
    out_dir.mkdir(parents=True)
    for name in ("figures", "tables", "final"):
        (out_dir / name).mkdir()

    doc_id = slugify(args.document_id)
    write_new_text(
        out_dir / "scope.md", _scope(doc_id, args.title, args.style, args.review_type), {".md"}
    )
    write_new_text(out_dir / "README.md", _ledger_readme(args.title), {".md"})
    write_new_text(out_dir / "UNRESOLVED.md", _unresolved(args.title), {".md"})
    write_new_text(out_dir / "draft.md", _draft(doc_id, args.title), {".md"})
    write_new_text(out_dir / "sources.csv", _csv_text(SOURCE_FIELDS), {".csv"})
    write_new_text(out_dir / "claims.csv", _csv_text(CLAIM_FIELDS), {".csv"})
    write_new_text(out_dir / "search_log.csv", _csv_text(SEARCH_FIELDS), {".csv"})

    counts = json.loads(json.dumps(PRISMA_TEMPLATE))
    counts["review_type"] = args.review_type
    counts["review_title"] = args.title
    counts["document_id"] = doc_id
    write_new_text(out_dir / "prisma_counts.json", json.dumps(counts, indent=2) + "\n", {".json"})

    print(
        json.dumps(
            {
                "tool": TOOL,
                "status": "pass",
                "workspace": str(out_dir),
                "document_id": doc_id,
                "citation_style": args.style,
                "review_type": args.review_type,
                "next_steps": [
                    "Fill scope.md, then run searches and append rows to sources.csv.",
                    "Verify every included source, then fill claims.csv.",
                    "Draft in draft.md with [claim:Cxxx] [src:Sxxx] markers on each factual line.",
                    "Run gate.py before describing the review as submission-ready.",
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    run(TOOL, cli)

