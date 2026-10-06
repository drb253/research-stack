"""Build review tables from the ledgers only: evidence table, study characteristics,
certainty-of-evidence summary, and the log of excluded records.

Every cell comes from a recorded field. Missing values are printed as
`not_reported` rather than left blank, so a reader can never mistake absence of
data for a zero. Tables refuse to include a source that is unverified, excluded,
or retracted.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path

from _common import (
    SOURCE_ID_RE,
    emit_report,
    is_absent,
    is_not_reported,
    issue,
    read_csv,
    run,
    write_text_lf,
)

TOOL = "make_evidence_table"

STYLES = ("evidence-table", "characteristics", "certainty-of-evidence", "excluded-log")
GROUP_BY = ("none", "theme", "study_design", "publication_type", "year", "peer_reviewed")

EVIDENCE_COLUMNS = [
    ("Source", "source_id"),
    ("Study (first author, year)", "study_citation"),
    ("Design", "study_design"),
    ("Population", "population"),
    ("Intervention / exposure", "intervention"),
    ("Comparator", "comparator"),
    ("n", "n_participants"),
    ("Follow-up", "follow_up"),
    ("Outcomes", "key_outcomes"),
    ("Main finding", "main_finding"),
    ("Effect estimate", "effect_estimate"),
    ("Verified by", "verifier"),
]

CHARACTERISTICS_COLUMNS = [
    ("Source", "source_id"),
    ("Study (first author, year)", "study_citation"),
    ("Journal / source", "container"),
    ("Type", "publication_type"),
    ("Peer reviewed", "peer_reviewed"),
    ("Design", "study_design"),
    ("Population", "population"),
    ("Intervention / exposure", "intervention"),
    ("Comparator", "comparator"),
    ("n", "n_participants"),
    ("Follow-up", "follow_up"),
    ("Outcomes", "key_outcomes"),
    ("Main finding", "main_finding"),
    ("Effect estimate", "effect_estimate"),
    ("Theme", "theme"),
    ("Locator", "locator"),
]

EXCLUDED_COLUMNS = [
    ("Source", "source_id"),
    ("Study (first author, year)", "study_citation"),
    ("Type", "publication_type"),
    ("Reason excluded", "exclusion_reason"),
    ("Retrieval", "retrieval_status"),
    ("Verification", "verification_status"),
]


def first_author_year(row: dict) -> str:
    authors = row.get("authors", "").strip()
    year = row.get("year", "").strip()
    surname = authors.split(",")[0].split(" and ")[0].split(" ")[0].strip() if authors else ""
    if not surname:
        return "[" + row.get("source_id", "").strip() + "]"
    return surname + " et al., " + (year or "year not reported")


def cell(row: dict, key: str) -> str:
    if key == "study_citation":
        return escape_md(first_author_year(row))
    value = row.get(key, "").strip()
    if not value or is_absent(value) or is_not_reported(value):
        return "not_reported"
    return escape_md(value)


def escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def total_participants(rows: list) -> int:
    total = 0
    for row in rows:
        value = row.get("n_participants", "").strip().replace(",", "")
        if value.isdigit():
            total += int(value)
    return total



def render_table(rows: list, columns: list, title: str, notes: str) -> str:
    header = "| " + " | ".join(name for name, _ in columns) + " |"
    divider = "|" + "|".join("---" for _ in columns) + "|"
    body: list = []
    for row in rows:
        body.append("| " + " | ".join(cell(row, key) for _, key in columns) + " |")
    lines: list = []
    if title:
        lines.append("**" + title + "**")
        lines.append("")
    lines.append(header)
    lines.append(divider)
    lines.extend(body)
    if notes:
        lines.append("")
        lines.append(notes)
    return "\n".join(lines) + "\n"


def group_rows(rows: list, group_by: str) -> list:
    if group_by == "none":
        return [("", rows)]
    buckets: dict = defaultdict(list)
    for row in rows:
        key = row.get(group_by, "").strip()
        if not key or is_absent(key) or is_not_reported(key):
            key = "not_reported"
        buckets[key].append(row)
    return [(key, buckets[key]) for key in sorted(buckets)]


def render_grouped(rows: list, columns: list, title: str, group_by: str, notes: str) -> tuple:
    sections: list = []
    warnings: list = []
    for key, group in group_rows(rows, group_by):
        if group_by != "none":
            if key == "not_reported":
                warnings.append(
                    issue(
                        "warning",
                        "GROUPING_FIELD_NOT_REPORTED",
                        detail=group_by + " missing for " + str(len(group)) + " source(s)",
                    )
                )
            sections.append(render_table(group, columns, "Group: " + key, ""))
        else:
            sections.append(render_table(group, columns, "", ""))
    header = ("# " + title + "\n\n") if title else ""
    body = "\n".join(sections)
    if notes:
        body += "\n" + notes + "\n"
    return header + body, warnings


def render_certainty_table(sources: list, claims: list, title: str) -> tuple:
    warnings: list = []
    by_theme: dict = defaultdict(list)
    for row in sources:
        by_theme[row.get("theme", "").strip() or "not_reported"].append(row)

    claims_by_source: dict = defaultdict(list)
    for row in claims:
        for source_id in [
            part.strip() for part in row.get("source_ids", "").split(";") if part.strip()
        ]:
            claims_by_source[source_id].append(row)

    header = (
        "| Theme | Included sources | Participants (sum of reported n) | Highest certainty | "
        "Direction of evidence | Designs | Caveat |"
    )
    divider = "|---|---|---|---|---|---|---|"
    order = {"high": 0, "moderate": 1, "low": 2, "very_low": 3, "not_assessed": 4}
    body: list = []
    for theme in sorted(by_theme):
        group = by_theme[theme]
        related = [
            claim
            for row in group
            for claim in claims_by_source.get(row.get("source_id", "").strip(), [])
        ]
        certainties = [claim.get("certainty", "").strip().lower() for claim in related]
        known = [value for value in certainties if value in order]
        if not known:
            warnings.append(issue("warning", "THEME_WITHOUT_ASSESSED_CERTAINTY", item_id=theme))
        highest = sorted(known, key=lambda value: order[value])[0] if known else "not_assessed"
        directions = Counter(
            claim.get("direction", "").strip().lower() or "unspecified" for claim in related
        )
        direction_text = ", ".join("%s %d" % (key, directions[key]) for key in sorted(directions))
        designs = Counter(row.get("study_design", "").strip() or "not_reported" for row in group)
        design_text = ", ".join("%s (%d)" % (key, designs[key]) for key in sorted(designs))
        caveat_parts: list = []
        if any(row.get("peer_reviewed", "").strip().lower() != "yes" for row in group):
            caveat_parts.append("includes non-peer-reviewed material")
        if any(row.get("publication_type", "").strip().lower() == "preprint" for row in group):
            caveat_parts.append("preprint evidence")
        if any(
            row.get("retraction_status", "").strip().lower() == "expression_of_concern"
            for row in group
        ):
            caveat_parts.append("expression of concern")
        body.append(
            "| %s | %d | %d | %s | %s | %s | %s |"
            % (
                escape_md(theme),
                len(group),
                total_participants(group),
                highest.replace("_", " "),
                direction_text or "no claims registered",
                design_text,
                "; ".join(caveat_parts) or "none recorded",
            )
        )
    text = "# " + title + "\n\n" + header + "\n" + divider + "\n" + "\n".join(body) + "\n"
    return text, warnings



DEFAULT_TITLES = {
    "evidence-table": "Summary of included evidence",
    "characteristics": "Study characteristics of included sources",
    "certainty-of-evidence": "Certainty of evidence by theme",
    "excluded-log": "Records excluded at full-text assessment",
}


def select_rows(rows: list, mode: str, allow_unverified: bool) -> tuple:
    """mode: 'included' (evidence base only) or 'excluded' (excluded records only)."""
    issues: list = []
    selected: list = []
    for row in rows:
        source_id = row.get("source_id", "").strip()
        if not SOURCE_ID_RE.fullmatch(source_id):
            continue
        inclusion = row.get("inclusion_status", "").strip().lower()
        if mode == "excluded":
            if inclusion == "excluded":
                selected.append(row)
            continue
        if inclusion == "excluded":
            continue
        if inclusion == "cited_for_context":
            issues.append(
                issue(
                    "info",
                    "CONTEXT_CITATION_NOT_IN_TABLE",
                    item_id=source_id,
                    detail="excluded from the evidence base; not listed as an included study",
                )
            )
            continue
        if inclusion != "included":
            issues.append(issue("warning", "SOURCE_NOT_YET_DECIDED", item_id=source_id))
            continue
        state = row.get("verification_status", "").strip().lower()
        if state != "verified" and not allow_unverified:
            issues.append(issue("error", "TABLE_SOURCE_NOT_VERIFIED", item_id=source_id))
            continue
        if row.get("retraction_status", "").strip().lower() == "retracted":
            issues.append(issue("error", "TABLE_SOURCE_RETRACTED", item_id=source_id))
            continue
        selected.append(row)
    return selected, issues


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate review tables from sources.csv (plus claims.csv for the certainty "
            "table). Tables never include an unverified or retracted source."
        )
    )
    parser.add_argument("sources", help="UTF-8 CSV source ledger")
    parser.add_argument(
        "--style",
        default="evidence-table",
        choices=list(STYLES),
        help="table layout to generate",
    )
    parser.add_argument(
        "--group-by",
        default="none",
        choices=list(GROUP_BY),
        help="insert a sub-heading before each group of rows",
    )
    parser.add_argument("--claims", default=None, help="CSV claim ledger, required for certainty table")
    parser.add_argument("--out", default=None, help="Markdown output file (default: stdout)")
    parser.add_argument(
        "--title",
        default=None,
        help="table caption (default depends on --style)",
    )
    parser.add_argument(
        "--include-excluded",
        action="store_true",
        help="(deprecated) use --style excluded-log to list excluded records instead",
    )
    parser.add_argument(
        "--allow-unverified",
        action="store_true",
        help="permit unverified rows in the table (not for submission)",
    )
    parser.add_argument(
        "--notes",
        default="",
        help="table footnote, for example the denominator definition",
    )
    return parser


def cli() -> int:
    args = build_parser().parse_args()
    args.title = args.title or DEFAULT_TITLES.get(args.style, "Summary of included evidence")
    fields, rows = read_csv(args.sources)
    issues: list = []
    selected: list = []

    if args.style == "certainty-of-evidence":
        if not args.claims:
            raise ValueError("--claims is required for the certainty-of-evidence table")
        _, claim_rows = read_csv(args.claims)
        selected, select_issues = select_rows(rows, "included", args.allow_unverified)
        issues.extend(select_issues)
        table_text, table_issues = render_certainty_table(selected, claim_rows, args.title)
        issues.extend(table_issues)
    else:
        mode = "excluded" if args.style == "excluded-log" else "included"
        selected, select_issues = select_rows(rows, mode, args.allow_unverified)
        issues.extend(select_issues)
        if args.style == "characteristics":
            columns = CHARACTERISTICS_COLUMNS
        elif args.style == "excluded-log":
            columns = EXCLUDED_COLUMNS
        else:
            columns = EVIDENCE_COLUMNS
        table_text, group_issues = render_grouped(
            selected, columns, args.title, args.group_by, args.notes
        )
        issues.extend(group_issues)

    if not selected:
        issues.append(issue("error", "NO_ROWS_FOR_TABLE"))
    if any(item.severity == "error" for item in issues):
        return emit_report(TOOL, issues, summary={"rows_available": len(rows)})

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_lf(path, table_text)
    else:
        print(table_text)
    return emit_report(
        TOOL,
        issues,
        summary={
            "rows_available": len(rows),
            "rows_in_table": len(selected),
            "style": args.style,
            "group_by": args.group_by,
            "output": args.out or "stdout",
        },
    )


if __name__ == "__main__":
    run(TOOL, cli)
