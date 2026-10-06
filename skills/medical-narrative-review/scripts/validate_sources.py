"""Validate the source ledger: identifiers, verification gates, and duplicates.

Reads only the user's own ledger. Prints a JSON report; no source text, no network
access, no third-party packages. Exit code 1 when any error-severity issue exists.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from typing import Any

from _common import (
    DATE_RE,
    SOURCE_ID_RE,
    InputError,
    Issue,
    emit_report,
    is_absent,
    is_nonempty_string,
    is_placeholder,
    issue,
    normalize_doi,
    normalize_title,
    read_csv,
    run,
    split_ids,
    valid_doi,
    valid_pmid,
    valid_pmcid,
)
from init_review import SOURCE_FIELDS

TOOL = "validate_sources"

PUBLICATION_TYPES = {
    "journal_article",
    "randomised_trial",
    "systematic_review",
    "meta_analysis",
    "review",
    "guideline",
    "consensus_statement",
    "cohort_study",
    "case_control_study",
    "cross_sectional_study",
    "case_report",
    "case_series",
    "editorial",
    "comment",
    "letter",
    "preprint",
    "conference_abstract",
    "registry_record",
    "book_chapter",
    "report",
    "other",
}
PEER_REVIEWED = {"yes", "no", "unknown"}
VERIFICATION = {"verified", "unverified", "failed"}
RETRACTION = {"not_checked", "clear", "retracted", "expression_of_concern", "corrected"}
INCLUSION = {"included", "excluded", "pending", "cited_for_context"}
CITABLE = {"included", "cited_for_context"}
RETRIEVAL = {"returned", "empty", "unavailable", "error", "user_supplied"}
EXTRACTION_FIELDS = [
    "study_design",
    "population",
    "intervention",
    "comparator",
    "n_participants",
    "follow_up",
    "key_outcomes",
    "main_finding",
    "effect_estimate",
    "theme",
]

PHI_PATTERNS = (
    ("EMAIL", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.(com|org|net|edu|gov|io)"),
    ("MRN", r"\b(MRN|medical record number)\b"),
    ("DOB", r"\b(DOB|date of birth)\b"),
    ("PHONE", r"\b[0-9]{3}[-.][0-9]{3}[-.][0-9]{4}\b"),
    ("NHS_NPI", r"\b(NPI|NHS number)\b"),
)

JOURNAL_LIKE_TYPES = {
    "journal_article",
    "randomised_trial",
    "systematic_review",
    "meta_analysis",
    "review",
    "guideline",
    "consensus_statement",
    "cohort_study",
    "case_control_study",
    "cross_sectional_study",
    "case_report",
    "case_series",
}
IDENTIFIER_COLUMNS = ("doi", "pmid", "pmcid")


def check_header(fields: list[str]) -> list[Issue]:
    issues: list[Issue] = []
    missing = [name for name in SOURCE_FIELDS if name not in fields]
    if missing:
        raise InputError("sources.csv is missing required columns: " + ",".join(missing))
    extra = [name for name in fields if name not in SOURCE_FIELDS]
    for name in extra:
        issues.append(issue("info", "EXTRA_COLUMN", item_id=name))
    return issues



def check_row(row: dict, row_number: int, strict: bool) -> list:
    issues: list = []
    location = "row:%d" % row_number
    source_id = row.get("source_id", "").strip()
    if not SOURCE_ID_RE.fullmatch(source_id):
        issues.append(issue("error", "INVALID_SOURCE_ID", location=location))
        return issues

    if is_placeholder(row.get("title", "")):
        issues.append(issue("error", "MISSING_TITLE", item_id=source_id))
    if not is_nonempty_string(row.get("authors", "")):
        issues.append(issue("error", "MISSING_AUTHORS", item_id=source_id))
    if not is_nonempty_string(row.get("container", "")):
        issues.append(issue("error", "MISSING_CONTAINER", item_id=source_id))

    year = row.get("year", "").strip()
    if not (len(year) == 4 and year.isdigit()):
        issues.append(issue("error", "INVALID_YEAR", item_id=source_id, detail=year[:20]))
    elif not (1500 <= int(year) <= date.today().year + 1):
        issues.append(issue("error", "YEAR_OUT_OF_RANGE", item_id=source_id, detail=year))

    has_identifier = False
    for column in IDENTIFIER_COLUMNS:
        value = row.get(column, "").strip()
        if is_absent(value):
            continue
        has_identifier = True
        if column == "doi" and not valid_doi(value):
            issues.append(issue("error", "MALFORMED_DOI", item_id=source_id, detail=value[:60]))
        if column == "pmid" and not valid_pmid(value):
            issues.append(issue("error", "MALFORMED_PMID", item_id=source_id, detail=value[:20]))
        if column == "pmcid" and not valid_pmcid(value):
            issues.append(issue("error", "MALFORMED_PMCID", item_id=source_id, detail=value[:20]))

    publication_type = row.get("publication_type", "").strip()
    if publication_type not in PUBLICATION_TYPES:
        issues.append(
            issue(
                "error",
                "INVALID_PUBLICATION_TYPE",
                item_id=source_id,
                detail=publication_type[:40],
            )
        )
    peer = row.get("peer_reviewed", "").strip().lower()
    if peer not in PEER_REVIEWED:
        issues.append(issue("error", "INVALID_PEER_REVIEWED", item_id=source_id))
    elif peer == "unknown":
        issues.append(issue("warning", "PEER_REVIEW_STATUS_UNKNOWN", item_id=source_id))

    status = row.get("verification_status", "").strip().lower()
    inclusion = row.get("inclusion_status", "").strip().lower()
    retraction = row.get("retraction_status", "").strip().lower()
    retrieval = row.get("retrieval_status", "").strip().lower()

    if status not in VERIFICATION:
        issues.append(issue("error", "INVALID_VERIFICATION_STATUS", item_id=source_id))
    if inclusion not in INCLUSION:
        issues.append(issue("error", "INVALID_INCLUSION_STATUS", item_id=source_id))
    if retraction not in RETRACTION:
        issues.append(issue("error", "INVALID_RETRACTION_STATUS", item_id=source_id))
    if retrieval not in RETRIEVAL:
        issues.append(issue("error", "INVALID_RETRIEVAL_STATUS", item_id=source_id))

    if inclusion in CITABLE and not has_identifier:
        issues.append(issue("error", "INCLUDED_WITHOUT_IDENTIFIER", item_id=source_id))
    if inclusion in CITABLE and not has_identifier and retrieval == "returned":
        issues.append(issue("warning", "RETRIEVED_WITHOUT_IDENTIFIER", item_id=source_id))

    if status == "verified":
        if not is_nonempty_string(row.get("verifier", "")):
            issues.append(issue("error", "VERIFIED_WITHOUT_VERIFIER", item_id=source_id))
        verified_date = row.get("verified_date", "").strip()
        if not DATE_RE.fullmatch(verified_date):
            issues.append(issue("error", "VERIFIED_WITHOUT_DATE", item_id=source_id))
        elif verified_date > date.today().isoformat():
            issues.append(issue("error", "VERIFIED_DATE_IN_FUTURE", item_id=source_id))
        if not is_nonempty_string(row.get("locator", "")):
            issues.append(issue("error", "VERIFIED_WITHOUT_LOCATOR", item_id=source_id))
        if not has_identifier:
            issues.append(issue("error", "VERIFIED_WITHOUT_IDENTIFIER", item_id=source_id))
    elif status in {"unverified", "failed"} and inclusion in CITABLE:
        issues.append(issue("error", "UNVERIFIED_SOURCE_INCLUDED", item_id=source_id))

    if retraction == "not_checked":
        issues.append(issue("warning", "RETRACTION_NOT_CHECKED", item_id=source_id))
    if retraction == "retracted" and inclusion in CITABLE:
        issues.append(issue("error", "RETRACTED_SOURCE_INCLUDED", item_id=source_id))
    if retraction == "retracted" and inclusion not in CITABLE:
        issues.append(issue("info", "RETRACTED_RETAINED_FOR_CONTEXT", item_id=source_id))
    if retraction == "expression_of_concern":
        issues.append(issue("warning", "EXPRESSION_OF_CONCERN", item_id=source_id))
    if publication_type == "preprint" and inclusion in CITABLE:
        issues.append(issue("warning", "PREPRINT_INCLUDED_LABEL_REQUIRED", item_id=source_id))
    if publication_type == "conference_abstract" and inclusion in CITABLE:
        issues.append(issue("warning", "ABSTRACT_INCLUDED_QUALIFY_IN_TEXT", item_id=source_id))

    if inclusion == "excluded" and not is_nonempty_string(row.get("exclusion_reason", "")):
        issues.append(issue("error", "EXCLUDED_WITHOUT_REASON", item_id=source_id))
    if inclusion == "pending":
        issues.append(issue("warning", "PENDING_INCLUSION_DECISION", item_id=source_id))

    if inclusion == "cited_for_context" and status == "verified":
        issues.append(
            issue(
                "info",
                "CONTEXT_CITATION_NOT_IN_EVIDENCE_BASE",
                item_id=source_id,
                detail="excluded from the evidence base but citable for context",
            )
        )
    if inclusion == "included" and status == "verified":
        issues.extend(_check_extraction(row, source_id, strict))
        if publication_type in JOURNAL_LIKE_TYPES:
            pages = row.get("pages", "").strip()
            if not pages or pages.lower() in {"unknown", "na", "n/a", "-"}:
                issues.append(
                    issue(
                        "warning",
                        "MISSING_PAGES_FOR_JOURNAL_ARTICLE",
                        item_id=source_id,
                        detail="record the page range or not_reported",
                    )
                )
            if is_absent(row.get("volume", "").strip()) and is_absent(row.get("issue", "").strip()):
                issues.append(
                    issue(
                        "warning",
                        "MISSING_VOLUME_AND_ISSUE",
                        item_id=source_id,
                        detail="record volume/issue or not_reported",
                    )
                )

    issues.extend(_check_phi(row, source_id))
    return issues


def _check_extraction(row: dict, source_id: str, strict: bool) -> list:
    issues: list = []
    for field in EXTRACTION_FIELDS:
        value = row.get(field, "").strip()
        if not value:
            issues.append(
                issue(
                    "error" if strict else "warning",
                    "MISSING_EXTRACTION_FIELD",
                    item_id=source_id,
                    detail=field,
                )
            )
        elif value.lower() in {"unknown", "na", "n/a", "-", "none"}:
            issues.append(
                issue("warning", "AMBIGUOUS_EXTRACTION_VALUE", item_id=source_id, detail=field)
            )

    n_value = row.get("n_participants", "").strip().lower()
    if n_value and n_value not in {"not_reported", "not_applicable"}:
        digits = n_value.replace(",", "").replace(" ", "")
        if not digits.isdigit():
            issues.append(
                issue("warning", "INVALID_N_PARTICIPANTS", item_id=source_id, detail=n_value[:40])
            )

    effect = row.get("effect_estimate", "").strip().lower()
    if effect and effect not in {"not_reported", "not_applicable"}:
        if not any(char.isdigit() for char in effect):
            issues.append(issue("warning", "EFFECT_ESTIMATE_WITHOUT_NUMBER", item_id=source_id))
    return issues


def _check_phi(row: dict, source_id: str) -> list:
    import re

    issues: list = []
    for column in ("title", "population", "key_outcomes", "notes", "main_finding"):
        for code, pattern in PHI_PATTERNS:
            if re.search(pattern, row.get(column, ""), flags=re.IGNORECASE):
                issues.append(
                    issue("error", "POSSIBLE_PHI_" + code, item_id=source_id, detail=column)
                )
    return issues



def check_duplicates(rows: list) -> list:
    issues: list = []
    doi_map: dict = {}
    title_map: dict = {}
    prefix_map: dict = {}
    for row in rows:
        source_id = row.get("source_id", "").strip()
        if not SOURCE_ID_RE.fullmatch(source_id):
            continue
        doi = normalize_doi(row.get("doi", ""))
        if doi and valid_doi(doi):
            if doi in doi_map:
                issues.append(issue("error", "DUPLICATE_DOI", item_id=source_id, detail=doi_map[doi]))
            else:
                doi_map[doi] = source_id

        title = normalize_title(row.get("title", ""))
        year = row.get("year", "").strip()
        if len(title) >= 20:
            key = (title, year)
            if key in title_map:
                issues.append(
                    issue("error", "DUPLICATE_SOURCE", item_id=source_id, detail=title_map[key])
                )
            else:
                title_map[key] = source_id
            prefix = title[:80]
            if prefix in prefix_map:
                other_id, other_year = prefix_map[prefix]
                if other_year != year:
                    issues.append(
                        issue("warning", "POSSIBLE_DUPLICATE_TITLE", item_id=source_id, detail=other_id)
                    )
            else:
                prefix_map[prefix] = (source_id, year)
    return issues


def build_summary(rows: list) -> dict:
    def tally(field: str) -> dict:
        counter = Counter(row.get(field, "").strip().lower() or "blank" for row in rows)
        return {key: counter[key] for key in sorted(counter)}

    included = [
        row for row in rows if row.get("inclusion_status", "").strip().lower() == "included"
    ]
    verified_included = [
        row
        for row in included
        if row.get("verification_status", "").strip().lower() == "verified"
    ]
    designs = Counter(row.get("study_design", "").strip().lower() or "blank" for row in included)
    themes = Counter(row.get("theme", "").strip().lower() or "blank" for row in included)
    return {
        "rows": len(rows),
        "included": len(included),
        "included_and_verified": len(verified_included),
        "excluded": sum(
            1 for row in rows if row.get("inclusion_status", "").strip().lower() == "excluded"
        ),
        "pending": sum(
            1 for row in rows if row.get("inclusion_status", "").strip().lower() == "pending"
        ),
        "preprints_included": sum(
            1 for row in included if row.get("publication_type", "").strip().lower() == "preprint"
        ),
        "verification_status": tally("verification_status"),
        "retraction_status": tally("retraction_status"),
        "inclusion_status": tally("inclusion_status"),
        "retrieval_status": tally("retrieval_status"),
        "peer_reviewed": tally("peer_reviewed"),
        "study_designs_included": {key: designs[key] for key in sorted(designs)},
        "themes_included": {key: themes[key] for key in sorted(themes)},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the source ledger: column schema, identifier formats, verification "
            "gates, retraction status, inclusion reasons, duplicates, and PHI patterns. "
            "The report never echoes ledger text beyond short field values."
        )
    )
    parser.add_argument("sources", help="UTF-8 CSV source ledger")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat missing extraction fields as errors (use before submission)",
    )
    parser.add_argument(
        "--require-included",
        action="store_true",
        help="fail when no source is marked included",
    )
    parser.add_argument(
        "--min-included",
        type=int,
        default=0,
        help="fail when fewer than N included and verified sources exist",
    )
    parser.add_argument(
        "--require-clear-retraction",
        action="store_true",
        help="fail when an included source has a retraction status other than clear",
    )
    return parser


def cli() -> int:
    args = build_parser().parse_args()
    fields, rows = read_csv(args.sources)
    issues = check_header(fields)
    for row_number, row in enumerate(rows, start=2):
        issues.extend(check_row(row, row_number, args.strict))
    issues.extend(check_duplicates(rows))
    summary = build_summary(rows)

    if args.require_included and not summary["included"]:
        issues.append(issue("error", "NO_INCLUDED_SOURCES"))
    if args.min_included and summary["included_and_verified"] < args.min_included:
        issues.append(
            issue(
                "error",
                "BELOW_MIN_INCLUDED_SOURCES",
                detail="%d of %d" % (summary["included_and_verified"], args.min_included),
            )
        )
    if args.require_clear_retraction:
        for row in rows:
            if row.get("inclusion_status", "").strip().lower() != "included":
                continue
            if row.get("retraction_status", "").strip().lower() != "clear":
                issues.append(
                    issue(
                        "error",
                        "INCLUDED_WITHOUT_CLEAR_RETRACTION_CHECK",
                        item_id=row.get("source_id", "").strip(),
                    )
                )
    if not rows:
        issues.append(issue("warning", "EMPTY_LEDGER"))
    return emit_report(TOOL, issues, summary=summary)


if __name__ == "__main__":
    run(TOOL, cli)

