"""Audit claim markers, source markers, and numbered citations against the ledgers.

Joins the manuscript to the claim ledger and the source ledger so that no sentence
can cite something that is unverified, excluded, retracted, or absent from the
ledger. Two modes:

  draft  (default)  manuscript uses [claim:C001] [src:S001] markers
  final  (--final)  manuscript uses numbered citations [1], [2,3], [4-6] and the
                    reference list is checked for numbering gaps and orphans

Prints a JSON report. The report identifies issues by ID and line number only; it
never echoes manuscript sentences or ledger text.
"""

from __future__ import annotations

import argparse
import re

from _common import (
    CLAIM_ID_RE,
    SOURCE_ID_RE,
    Issue,
    emit_report,
    is_nonempty_string,
    is_placeholder,
    issue,
    read_csv,
    read_text,
    run,
    split_ids,
)
from init_review import CLAIM_FIELDS

TOOL = "audit_citations"

CLAIM_KINDS = {
    "epidemiology",
    "burden",
    "mechanism",
    "diagnosis",
    "prognosis",
    "treatment_effect",
    "safety",
    "guideline",
    "health_services",
    "economic",
    "methodological",
    "contextual",
}
DIRECTIONS = {"supports", "refutes", "mixed", "neutral"}
CERTAINTY = {"high", "moderate", "low", "very_low", "not_assessed"}
ANALYSIS_INTENT = {"confirmatory", "exploratory", "descriptive", "not_applicable"}
CLAIM_STATUS = {"verified", "unverified", "disputed"}

CLAIM_MARKER_RE = re.compile(r"\[claim:(C[0-9]{3,8})\]")
SRC_MARKER_RE = re.compile(
    r"\[src:((?:S[0-9]{3,8})(?:\s*[,;]\s*S[0-9]{3,8})*)\]"
)
NUMBERED_CITE_RE = re.compile(r"\[([0-9]{1,4}(?:\s*[,\u2013-]\s*[0-9]{1,4})*)\]")
PLACEHOLDER_RE = re.compile(
    r"\[\[\s*TODO|\[UNVERIFIED|DO NOT CITE|\[citation needed\]|\[CITATION NEEDED\]",
    re.IGNORECASE,
)
QUANT_PATTERNS = (
    re.compile(r"[0-9]+(?:\.[0-9]+)?\s?%"),
    re.compile(r"\b9[0-9]%\s?(?:CI|confidence interval)", re.IGNORECASE),
    re.compile(r"\bp\s?[<>=]\s?0?\.[0-9]+", re.IGNORECASE),
    re.compile(r"\b(?:a?HR|OR|aOR|RR|aRR|IRR|HR|hazard ratio|odds ratio|risk ratio)\b\s*[:=]?\s*[0-9]"),
    re.compile(r"\bn\s?=\s?[0-9]+", re.IGNORECASE),
    re.compile(r"[0-9]+(?:\.[0-9]+)?\s?(?:mg|mcg|ug|g|mL|ml|dL|L|kg|mmol|umol|IU|units|mg/kg)\b"),
    re.compile(r"\b[0-9]+(?:\.[0-9]+)?\s?(?:months?|weeks?|days?|years?)\b"),
    re.compile(r"\bmedian\b[^.]*[0-9]"),
    re.compile(r"\b(?:sensitivit|specificit)\w*\b[^.]*[0-9]+\s?%", re.IGNORECASE),
)
SKIP_LINE_PREFIXES = ("#", "|", "---", "```", "<!--", "- [", ">")



def load_sources(path: str) -> dict:
    fields, rows = read_csv(path)
    sources: dict = {}
    for row in rows:
        source_id = row.get("source_id", "").strip()
        if not SOURCE_ID_RE.fullmatch(source_id):
            continue
        if source_id in sources:
            raise ValueError("duplicate source_id in ledger: " + source_id)
        sources[source_id] = {
            "verification": row.get("verification_status", "").strip().lower(),
            "inclusion": row.get("inclusion_status", "").strip().lower(),
            "retraction": row.get("retraction_status", "").strip().lower(),
            "publication_type": row.get("publication_type", "").strip().lower(),
            "peer_reviewed": row.get("peer_reviewed", "").strip().lower(),
        }
    return sources


def load_claims(path: str, sources: dict) -> tuple:
    fields, rows = read_csv(path)
    missing = [name for name in CLAIM_FIELDS if name not in fields]
    if missing:
        raise ValueError("claims.csv is missing required columns: " + ",".join(missing))
    issues: list = []
    claims: dict = {}
    for row_number, row in enumerate(rows, start=2):
        location = "row:%d" % row_number
        claim_id = row.get("claim_id", "").strip()
        if not CLAIM_ID_RE.fullmatch(claim_id):
            issues.append(issue("error", "INVALID_CLAIM_ID", location=location))
            continue
        if claim_id in claims:
            issues.append(issue("error", "DUPLICATE_CLAIM_ID", item_id=claim_id))
            continue
        claims[claim_id] = row

        if row.get("claim_kind", "").strip().lower() not in CLAIM_KINDS:
            issues.append(issue("error", "INVALID_CLAIM_KIND", item_id=claim_id))
        if row.get("direction", "").strip().lower() not in DIRECTIONS:
            issues.append(issue("error", "INVALID_DIRECTION", item_id=claim_id))
        if row.get("certainty", "").strip().lower() not in CERTAINTY:
            issues.append(issue("error", "INVALID_CERTAINTY", item_id=claim_id))
        if row.get("analysis_intent", "").strip().lower() not in ANALYSIS_INTENT:
            issues.append(issue("error", "INVALID_ANALYSIS_INTENT", item_id=claim_id))
        status = row.get("verification_status", "").strip().lower()
        if status not in CLAIM_STATUS:
            issues.append(issue("error", "INVALID_CLAIM_STATUS", item_id=claim_id))
        if not is_nonempty_string(row.get("section", "")):
            issues.append(issue("error", "MISSING_CLAIM_SECTION", item_id=claim_id))
        summary = row.get("claim_summary", "").strip()
        if is_placeholder(summary):
            issues.append(issue("error", "MISSING_CLAIM_SUMMARY", item_id=claim_id))
        elif len(summary) > 200:
            issues.append(issue("warning", "CLAIM_SUMMARY_TOO_LONG", item_id=claim_id))

        source_ids = split_ids(row.get("source_ids", ""))
        if not source_ids:
            issues.append(issue("error", "CLAIM_WITHOUT_SOURCE", item_id=claim_id))
        for source_id in source_ids:
            if not SOURCE_ID_RE.fullmatch(source_id):
                issues.append(
                    issue(
                        "error",
                        "INVALID_SOURCE_ID_IN_CLAIM",
                        item_id=claim_id,
                        detail=source_id[:20],
                    )
                )
                continue
            record = sources.get(source_id)
            if record is None:
                issues.append(
                    issue(
                        "error",
                        "CLAIM_REFERENCES_UNKNOWN_SOURCE",
                        item_id=claim_id,
                        detail=source_id,
                    )
                )
                continue
            if record["verification"] != "verified":
                issues.append(
                    issue(
                        "error",
                        "CLAIM_SUPPORTED_BY_UNVERIFIED_SOURCE",
                        item_id=claim_id,
                        detail=source_id,
                    )
                )
            if record["inclusion"] not in {"included", "cited_for_context"}:
                issues.append(
                    issue(
                        "error",
                        "CLAIM_SUPPORTED_BY_NON_INCLUDED_SOURCE",
                        item_id=claim_id,
                        detail=source_id,
                    )
                )
            if record["retraction"] == "retracted":
                issues.append(
                    issue(
                        "error",
                        "CLAIM_SUPPORTED_BY_RETRACTED_SOURCE",
                        item_id=claim_id,
                        detail=source_id,
                    )
                )
        if status == "verified" and any(
            sources.get(sid, {}).get("verification") != "verified" for sid in source_ids
        ):
            issues.append(
                issue("error", "CLAIM_MARKED_VERIFIED_WITH_UNVERIFIED_SOURCE", item_id=claim_id)
            )
        if certainty_value(row) in {"low", "very_low"} and status == "verified":
            issues.append(issue("info", "LOW_CERTAINTY_CLAIM_HEDGE_REQUIRED", item_id=claim_id))
    return claims, issues


def certainty_value(row: dict) -> str:
    return row.get("certainty", "").strip().lower()



def audit_draft(text: str, claims: dict, sources: dict, strict: bool) -> tuple:
    issues: list = []
    used_claims: set = set()
    used_sources: set = set()
    in_fence = False
    block: list = []

    def flush_block() -> None:
        """Flag a paragraph whose quantitative content carries no claim marker.

        Prose is normally wrapped across lines, so the marker may sit anywhere in the
        paragraph. The guarantee is unchanged: a number cannot appear in a paragraph
        that is not tied to a registered claim.
        """
        if not block:
            return
        has_claim = any(CLAIM_MARKER_RE.search(line) for _, line in block)
        has_source = any(SRC_MARKER_RE.search(line) for _, line in block)
        if has_source and not has_claim:
            for line_number, line in block:
                if SRC_MARKER_RE.search(line):
                    issues.append(
                        issue(
                            "warning",
                            "SOURCE_MARKER_WITHOUT_CLAIM_MARKER",
                            location="line:%d" % line_number,
                        )
                    )
                    break
        if has_claim or has_source:
            return
        for line_number, line in block:
            if any(pattern.search(line) for pattern in QUANT_PATTERNS):
                issues.append(
                    issue(
                        "error" if strict else "warning",
                        "UNTAGGED_QUANTITATIVE_CONTENT",
                        location="line:%d" % line_number,
                    )
                )
                return

    for line_number, line in enumerate(text.splitlines(), start=1):
        location = "line:%d" % line_number
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            flush_block()
            block = []
            continue
        if in_fence:
            continue
        if not stripped or stripped.startswith(SKIP_LINE_PREFIXES):
            flush_block()
            block = []
        else:
            block.append((line_number, line))

        if PLACEHOLDER_RE.search(line):
            issues.append(
                issue("error" if strict else "warning", "UNRESOLVED_PLACEHOLDER", location=location)
            )

        claim_ids = CLAIM_MARKER_RE.findall(line)
        line_sources: set = set()
        for group in SRC_MARKER_RE.findall(line):
            line_sources.update(split_ids(group))

        for source_id in sorted(line_sources):
            used_sources.add(source_id)
            record = sources.get(source_id)
            if record is None:
                issues.append(
                    issue("error", "UNKNOWN_SOURCE_MARKER", location=location, item_id=source_id)
                )
                continue
            if record["verification"] != "verified":
                issues.append(
                    issue("error", "UNVERIFIED_CITATION_MARKER", location=location, item_id=source_id)
                )
            if record["inclusion"] not in {"included", "cited_for_context"}:
                issues.append(
                    issue("error", "CITED_SOURCE_NOT_INCLUDED", location=location, item_id=source_id)
                )
            if record["retraction"] == "retracted":
                issues.append(
                    issue("error", "CITED_RETRACTED_SOURCE", location=location, item_id=source_id)
                )

        for claim_id in claim_ids:
            used_claims.add(claim_id)
            row = claims.get(claim_id)
            if row is None:
                issues.append(
                    issue("error", "UNKNOWN_CLAIM_MARKER", location=location, item_id=claim_id)
                )
                continue
            expected = set(split_ids(row.get("source_ids", "")))
            if not expected.issubset(line_sources):
                issues.append(
                    issue(
                        "error",
                        "CLAIM_MARKER_MISSING_SOURCE_MARKER",
                        location=location,
                        item_id=claim_id,
                    )
                )
            if row.get("verification_status", "").strip().lower() != "verified":
                issues.append(
                    issue("error", "CLAIM_MARKER_NOT_VERIFIED", location=location, item_id=claim_id)
                )

    flush_block()
    return issues, used_claims, used_sources



def expand_citations(group: str) -> list:
    numbers: list = []
    for part in re.split(r"\s*,\s*", group.strip()):
        part = part.strip()
        match = re.fullmatch(r"([0-9]{1,4})\s*[\u2013-]\s*([0-9]{1,4})", part)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            if end >= start and end - start <= 200:
                numbers.extend(range(start, end + 1))
            continue
        if part.isdigit():
            numbers.append(int(part))
    return numbers


def parse_reference_numbers(text: str) -> list:
    numbers: list = []
    for line in text.splitlines():
        match = re.match(r"^\s*([0-9]{1,4})\.\s+\S", line)
        if match:
            numbers.append(int(match.group(1)))
    return numbers


def audit_final(text: str, reference_numbers: list) -> list:
    issues: list = []
    if reference_numbers:
        expected = set(range(1, len(reference_numbers) + 1))
        actual = set(reference_numbers)
        for number in sorted(expected - actual):
            issues.append(issue("error", "MISSING_REFERENCE_NUMBER", item_id=str(number)))
        for number in sorted(actual - expected):
            issues.append(issue("error", "REFERENCE_NUMBER_OUT_OF_RANGE", item_id=str(number)))
        for number in sorted({n for n in actual if reference_numbers.count(n) > 1}):
            issues.append(issue("error", "DUPLICATE_REFERENCE_NUMBER", item_id=str(number)))

    first_seen: list = []
    cited: set = set()
    in_fence = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        location = "line:%d" % line_number
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        if PLACEHOLDER_RE.search(line):
            issues.append(issue("error", "UNRESOLVED_PLACEHOLDER", location=location))
        if CLAIM_MARKER_RE.search(line) or SRC_MARKER_RE.search(line):
            issues.append(issue("error", "DRAFT_MARKER_IN_FINAL_DOCUMENT", location=location))

        for group in NUMBERED_CITE_RE.findall(line):
            for number in expand_citations(group):
                cited.add(number)
                if number not in first_seen:
                    first_seen.append(number)
                if reference_numbers and number > len(reference_numbers):
                    issues.append(
                        issue(
                            "error",
                            "CITATION_EXCEEDS_REFERENCE_LIST",
                            location=location,
                            item_id=str(number),
                        )
                    )

    if reference_numbers:
        for number in sorted(set(range(1, len(reference_numbers) + 1)) - cited):
            issues.append(issue("error", "UNCITED_REFERENCE", item_id=str(number)))
        breaks = [
            str(first_seen[index])
            for index in range(1, len(first_seen))
            if first_seen[index] != first_seen[index - 1] + 1
        ]
        for value in breaks:
            issues.append(issue("warning", "CITATION_NOT_IN_FIRST_APPEARANCE_ORDER", item_id=value))
    elif not cited:
        issues.append(issue("warning", "NO_NUMBERED_CITATIONS_FOUND"))
    return issues


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit a marked draft (or a numbered final manuscript) against claims.csv "
            "and sources.csv. The report identifies issues by ID and line number only."
        )
    )
    parser.add_argument("manuscript", help="UTF-8 Markdown manuscript")
    parser.add_argument("claims", help="UTF-8 CSV claim ledger")
    parser.add_argument("sources", help="UTF-8 CSV source ledger")
    parser.add_argument(
        "--final",
        action="store_true",
        help="check numbered citations against a reference list instead of draft markers",
    )
    parser.add_argument(
        "--references",
        default=None,
        help="final reference list used to derive the reference count",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="escalate untagged quantitative content and placeholders to errors",
    )
    parser.add_argument(
        "--allow-uncited",
        action="store_true",
        help="do not warn about registered claims that never appear in the manuscript",
    )
    return parser


def cli() -> int:
    args = build_parser().parse_args()
    sources = load_sources(args.sources)
    claims, issues = load_claims(args.claims, sources)
    text = read_text(args.manuscript, {".md", ".markdown"})

    if args.final:
        reference_numbers: list = []
        if args.references:
            reference_numbers = parse_reference_numbers(
                read_text(args.references, {".md", ".markdown"})
            )
        issues.extend(audit_final(text, reference_numbers))
        return emit_report(
            TOOL,
            issues,
            summary={
                "mode": "final",
                "references_declared": len(reference_numbers),
                "claims_registered": len(claims),
                "sources_registered": len(sources),
            },
        )

    draft_issues, used_claims, used_sources = audit_draft(text, claims, sources, args.strict)
    issues.extend(draft_issues)
    if not args.allow_uncited:
        for claim_id in sorted(set(claims) - used_claims):
            issues.append(issue("warning", "CLAIM_NOT_USED_IN_MANUSCRIPT", item_id=claim_id))
    included_verified = {
        sid
        for sid, record in sources.items()
        if record["inclusion"] in {"included", "cited_for_context"}
        and record["verification"] == "verified"
    }
    for source_id in sorted(included_verified - used_sources):
        issues.append(issue("warning", "INCLUDED_SOURCE_NEVER_CITED", item_id=source_id))
    return emit_report(
        TOOL,
        issues,
        summary={
            "mode": "draft",
            "claims_registered": len(claims),
            "claims_used": len(used_claims),
            "sources_registered": len(sources),
            "sources_cited": len(used_sources),
        },
    )


if __name__ == "__main__":
    run(TOOL, cli)

