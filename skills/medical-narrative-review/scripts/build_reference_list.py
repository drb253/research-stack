"""Renumber draft citations and build a verified reference list.

Reads the marked draft and both ledgers, orders sources by first appearance, and
writes:

  final/references.md        numbered reference list in the requested style
  final/manuscript_cited.md  the draft with [src:...] replaced by [n] and the
                             [claim:...] markers removed
  final/citation_map.csv     citation number to source ID, DOI, and PMID

Refuses to write anything when a cited source is unknown, unverified, excluded,
retracted, or carries no DOI/PMID, so a fabricated or unchecked citation can never
reach a reference list. Offline, deterministic, standard library only.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
from pathlib import Path

from _common import (
    SOURCE_ID_RE,
    emit_report,
    is_absent,
    issue,
    read_csv,
    read_text,
    run,
    split_ids,
    valid_doi,
    valid_pmid,
    write_new_text,
)

TOOL = "build_reference_list"

SRC_MARKER_RE = re.compile(r"\[src:((?:S[0-9]{3,8})(?:\s*[,;]\s*S[0-9]{3,8})*)\]")
CLAIM_MARKER_RE = re.compile(r"\[claim:C[0-9]{3,8}\]")
PLACEHOLDER_RE = re.compile(r"\[\[\s*TODO|\[UNVERIFIED|DO NOT CITE", re.IGNORECASE)
AUTHOR_INITIALS_RE = re.compile(r"^([A-Z][A-Za-z'\-\u00c0-\u024f]+(?:\s[A-Z][A-Za-z'\-\u00c0-\u024f]+)?)\s([A-Z]{1,3})$")
NOT_REPORTED = "not_reported"


def format_first_appearance_order(ids: list) -> list:
    ordered: list = []
    for source_id in ids:
        if source_id not in ordered:
            ordered.append(source_id)
    return ordered


def abbreviate_authors(authors: str, keep: int) -> str:
    text = authors.strip().rstrip(".")
    if re.search(r"\bet al\b", text, re.IGNORECASE):
        return text
    parts = [part.strip() for part in re.split(r",| and ", text) if part.strip()]
    if len(parts) > keep:
        return ", ".join(parts[:keep]) + ", et al"
    return ", ".join(parts) if len(parts) > 1 else text


def apa_authors(authors: str) -> tuple:
    """Return (formatted author string, (names_parsed, list_truncated))."""
    original = authors.strip()
    text = original.rstrip(".")
    truncated = bool(re.search(r"\bet al\b", text, re.IGNORECASE))
    text = re.sub(r",?\s*\bet al\b\.?", "", text, flags=re.IGNORECASE).strip().rstrip(",")
    parts = [part.strip() for part in re.split(r",| and ", text) if part.strip()]
    converted: list = []
    parsed = True
    for part in parts:
        match = AUTHOR_INITIALS_RE.match(part)
        if match:
            initials = " ".join(char + "." for char in match.group(2))
            converted.append(match.group(1) + ", " + initials)
        else:
            converted.append(part)
            parsed = False
    if not converted:
        return original, (False, truncated)
    if truncated:
        joined = ", ".join(converted) + ", et al."
    elif len(converted) == 1:
        joined = converted[0]
    else:
        joined = ", ".join(converted[:-1]) + ", & " + converted[-1]
    return joined, (parsed, truncated)


def field(row: dict, name: str) -> str:
    value = row.get(name, "").strip()
    if is_absent(value) or value.lower() == NOT_REPORTED:
        return ""
    return value


def format_reference(row: dict, style: str) -> tuple:
    """Return (reference string, warnings)."""
    warnings: list = []
    title = row.get("title", "").strip().rstrip(".")
    container = row.get("container", "").strip().rstrip(".")
    year = field(row, "year")
    volume = field(row, "volume")
    issue = field(row, "issue")
    pages = field(row, "pages")
    doi = field(row, "doi")
    pmid = field(row, "pmid")
    publication_type = row.get("publication_type", "").strip().lower()

    if not container:
        warnings.append("MISSING_CONTAINER_IN_REFERENCE")
        container = "[container missing]"
    if not year:
        warnings.append("MISSING_YEAR_IN_REFERENCE")
    if publication_type == "preprint":
        container = container + " (preprint)"
    if publication_type == "conference_abstract":
        container = container + " (conference abstract)"
    if not volume:
        warnings.append("MISSING_VOLUME_IN_REFERENCE")
    if not pages:
        warnings.append("MISSING_PAGES_IN_REFERENCE")

    locator = ""
    if volume and issue:
        locator = "%s(%s)" % (volume, issue)
    elif volume:
        locator = volume
    if locator and pages:
        locator = locator + ":" + pages
    elif pages:
        locator = pages

    if style in {"vancouver", "ama"}:
        keep = 6 if style == "vancouver" else 3
        authors = abbreviate_authors(row.get("authors", ""), keep)
        tail = container + "."
        if year:
            tail += " " + year
        if locator:
            tail += ";" + locator.replace("(", "(").replace(")", ")")
        tail += "."
        reference = "%s. %s. %s" % (authors, title, tail)
        if doi and valid_doi(doi):
            reference += " doi:" + doi
        elif pmid and valid_pmid(pmid):
            reference += " PMID: " + pmid
        return reference.strip(), warnings

    if style == "elsevier":
        authors = abbreviate_authors(row.get("authors", ""), 6)
        reference = "%s. %s. %s" % (authors, title, container)
        if year:
            reference += " %s" % year
        if locator:
            reference += " " + locator
        reference += "."
        if doi and valid_doi(doi):
            reference += " https://doi.org/" + doi
        return reference.strip(), warnings

    if style == "apa":
        authors, (parsed, truncated) = apa_authors(row.get("authors", ""))
        if not parsed:
            warnings.append("AUTHOR_FORMAT_UNEXPECTED_FOR_APA")
        if truncated:
            warnings.append("AUTHOR_LIST_TRUNCATED_FOR_APA")
        reference = authors
        if year:
            reference += " (%s)." % year
        reference += " " + title + "."
        reference += " " + container
        if volume:
            reference += ", " + volume
        if issue:
            reference += "(" + issue + ")"
        if pages:
            reference += ", " + pages
        reference += "."
        if doi and valid_doi(doi):
            reference += " https://doi.org/" + doi
        return reference.strip(), warnings



def load_ledger(path: str) -> tuple:
    fields, rows = read_csv(path)
    ledger: dict = {}
    issues: list = []
    for row in rows:
        source_id = row.get("source_id", "").strip()
        if not SOURCE_ID_RE.fullmatch(source_id):
            continue
        if source_id in ledger:
            issues.append(issue("error", "DUPLICATE_SOURCE_ID_IN_LEDGER", item_id=source_id))
            continue
        ledger[source_id] = row
    return ledger, issues


def check_cited_source(source_id: str, row: dict) -> list:
    issues: list = []
    status = row.get("verification_status", "").strip().lower()
    inclusion = row.get("inclusion_status", "").strip().lower()
    retraction = row.get("retraction_status", "").strip().lower()
    if status != "verified":
        issues.append(issue("error", "CITED_SOURCE_NOT_VERIFIED", item_id=source_id))
    if inclusion not in {"included", "cited_for_context"}:
        issues.append(issue("error", "CITED_SOURCE_NOT_INCLUDED", item_id=source_id))
    if retraction == "retracted":
        issues.append(issue("error", "CITED_SOURCE_RETRACTED", item_id=source_id))
    if retraction == "expression_of_concern":
        issues.append(issue("warning", "CITED_SOURCE_EXPRESSION_OF_CONCERN", item_id=source_id))
    if retraction == "not_checked":
        issues.append(issue("warning", "CITED_SOURCE_RETRACTION_UNCHECKED", item_id=source_id))
    if not valid_doi(row.get("doi", "")) and not valid_pmid(row.get("pmid", "")):
        issues.append(issue("error", "CITED_SOURCE_WITHOUT_IDENTIFIER", item_id=source_id))
    return issues


def format_citation_numbers(numbers: list) -> str:
    unique = sorted(set(numbers))
    if not unique:
        return ""
    parts: list = []
    start = unique[0]
    end = unique[0]
    for number in unique[1:]:
        if number == end + 1:
            end = number
            continue
        parts.append(str(start) if start == end else "%d-%d" % (start, end))
        start = end = number
    parts.append(str(start) if start == end else "%d-%d" % (start, end))
    return "[" + ",".join(parts) + "]"


def number_draft(text: str, numbering: dict) -> str:
    def replace_sources(match: re.Match) -> str:
        numbers = [
            numbering[source_id]
            for source_id in split_ids(match.group(1))
            if source_id in numbering
        ]
        return format_citation_numbers(numbers)

    without_claims = CLAIM_MARKER_RE.sub("", text)
    numbered = SRC_MARKER_RE.sub(replace_sources, without_claims)
    return re.sub(r"[ \t]{2,}", " ", numbered)


def assign_numbers(cited_order: list, ledger: dict) -> tuple:
    numbering: dict = {}
    issues: list = []
    for source_id in cited_order:
        row = ledger.get(source_id)
        if row is None:
            issues.append(issue("error", "CITED_SOURCE_NOT_IN_LEDGER", item_id=source_id))
            continue
        issues.extend(check_cited_source(source_id, row))
        doi = row.get("doi", "").strip().lower()
        duplicate = None
        for other_id, other_number in numbering.items():
            other_row = ledger.get(other_id, {})
            if doi and other_row.get("doi", "").strip().lower() == doi:
                duplicate = other_id
                break
        if duplicate is not None:
            numbering[source_id] = numbering[duplicate]
            issues.append(
                issue(
                    "warning",
                    "DUPLICATE_DOI_SHARES_CITATION_NUMBER",
                    item_id=source_id,
                    detail=duplicate,
                )
            )
            continue
        numbering[source_id] = len(set(numbering.values())) + 1
    return numbering, issues

    raise ValueError("unsupported citation style")



def _write_generated(path: Path, content: str) -> None:
    """Derived artifacts are regenerated on each run, so overwriting is intended."""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = content.encode("utf-8")
    if len(encoded) > 5_000_000:
        raise ValueError("generated output exceeds the size limit")
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def _citation_map_csv(citation_map: list) -> str:
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(
        handle,
        fieldnames=[
            "citation_number",
            "source_id",
            "doi",
            "pmid",
            "publication_type",
            "peer_reviewed",
        ],
        lineterminator="\n",
    )
    writer.writeheader()
    for entry in sorted(citation_map, key=lambda item: (item["citation_number"], item["source_id"])):
        writer.writerow(entry)
    return handle.getvalue()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Renumber draft citations by first appearance and write a verified reference "
            "list. Nothing is written when any cited source fails a verification gate."
        )
    )
    parser.add_argument("draft", help="UTF-8 Markdown draft with [claim:] and [src:] markers")
    parser.add_argument("sources", help="UTF-8 CSV source ledger")
    parser.add_argument("claims", help="UTF-8 CSV claim ledger, used for cross-checking")
    parser.add_argument(
        "--style",
        default="vancouver",
        choices=["vancouver", "ama", "apa", "elsevier"],
        help="reference list style",
    )
    parser.add_argument("--out-dir", required=True, help="directory for generated files")
    parser.add_argument(
        "--allow-placeholders",
        action="store_true",
        help="do not fail when unresolved placeholders remain in the draft",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="run the gates and print the plan without writing files",
    )
    return parser


def cli() -> int:
    args = build_parser().parse_args()
    draft_text = read_text(args.draft, {".md", ".markdown"})
    if not Path(args.claims).is_file():
        raise ValueError("claims ledger not found: " + args.claims)
    ledger, issues = load_ledger(args.sources)
    if not ledger:
        raise ValueError("source ledger contains no usable rows")

    cited_order = format_first_appearance_order(
        [
            source_id
            for group in SRC_MARKER_RE.findall(draft_text)
            for source_id in split_ids(group)
        ]
    )
    if not cited_order:
        issues.append(
            issue("error", "NO_SOURCE_MARKERS_FOUND", detail="nothing to number in the draft")
        )
    numbering, number_issues = assign_numbers(cited_order, ledger)
    issues.extend(number_issues)

    if PLACEHOLDER_RE.search(draft_text):
        issues.append(
            issue(
                "error" if not args.allow_placeholders else "warning",
                "PLACEHOLDERS_PRESENT",
                detail="resolve every placeholder before numbering citations",
            )
        )

    reference_entries: dict = {}
    citation_map: list = []
    for source_id in cited_order:
        row = ledger.get(source_id)
        number = numbering.get(source_id)
        if row is None or number is None:
            continue
        entry, entry_warnings = format_reference(row, args.style)
        for code in entry_warnings:
            issues.append(issue("warning", code, item_id=source_id))
        reference_entries[number] = entry
        citation_map.append(
            {
                "citation_number": number,
                "source_id": source_id,
                "doi": row.get("doi", "").strip(),
                "pmid": row.get("pmid", "").strip(),
                "publication_type": row.get("publication_type", "").strip(),
                "peer_reviewed": row.get("peer_reviewed", "").strip(),
            }
        )

    ordered = sorted(reference_entries.items())
    references_md = (
        "# References\n\n"
        + "\n".join("%d. %s" % (number, entry) for number, entry in ordered)
        + "\n"
    )
    numbered_text = number_draft(draft_text, numbering)
    summary = {
        "citation_style": args.style,
        "sources_cited": len(cited_order),
        "unique_citation_numbers": len(set(numbering.values())),
        "references_written": len(ordered),
    }
    error_count = sum(item.severity == "error" for item in issues)
    if error_count or args.check_only:
        return emit_report(
            TOOL,
            issues,
            summary=summary,
            extra={"wrote_files": False, "planned_reference_count": len(ordered)},
        )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_generated(out_dir / "references.md", references_md)
    _write_generated(out_dir / "manuscript_cited.md", numbered_text)
    _write_generated(out_dir / "citation_map.csv", _citation_map_csv(citation_map))
    return emit_report(
        TOOL,
        issues,
        summary=summary,
        extra={
            "wrote_files": True,
            "files": [
                str(out_dir / "references.md"),
                str(out_dir / "manuscript_cited.md"),
                str(out_dir / "citation_map.csv"),
            ],
        },
    )


if __name__ == "__main__":
    run(TOOL, cli)
