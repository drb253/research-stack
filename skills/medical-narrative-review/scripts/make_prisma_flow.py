"""Draw a screening flow diagram (PRISMA 2020 layout) from recorded counts.

The counts file must balance arithmetically; if it does not, the command reports the
exact equation that fails and writes nothing, so the figure can never disagree with
the screening log. Emits Mermaid, standalone SVG, and a Markdown caption block.

Offline, deterministic, standard library only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _common import emit_report, issue, read_json, require_object, run, write_text_lf

TOOL = "make_prisma_flow"

WIDTH = 1080
BOX_W = 560
LEFT_X = 250
SIDE_X = 850
SIDE_W = 200
BOX_H = 118
GAP = 62
TOP = 70
LINE_H = 17
CHAR_W = 6.6


def fmt(value) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("counts must be numbers")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError("counts must be whole numbers")
    return "{:,}".format(int(value))


def xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def wrap(text: str, width_chars: int) -> list:
    words = text.split()
    lines: list = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        if len(candidate) <= width_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def check_counts(counts: dict) -> list:
    issues: list = []
    ident = require_object(counts.get("identification"), "identification")
    screening = require_object(counts.get("screening"), "screening")
    retrieval = require_object(counts.get("retrieval"), "retrieval")
    eligibility = require_object(counts.get("eligibility"), "eligibility")
    included = require_object(counts.get("included"), "included")

    from_databases = ident.get("records_from_databases", 0)
    from_registers = ident.get("records_from_registers", 0)
    from_other = ident.get("records_from_other_methods", 0)
    duplicates = ident.get("duplicates_removed", 0)
    screened = screening.get("records_screened", 0)
    screened_excluded = screening.get("records_excluded", 0)
    sought = retrieval.get("reports_sought", 0)
    not_retrieved = retrieval.get("reports_not_retrieved", 0)
    assessed = eligibility.get("reports_assessed", 0)
    excluded = eligibility.get("reports_excluded", 0)
    reasons = require_object(eligibility.get("exclusion_reasons", {}), "exclusion_reasons")
    studies = included.get("studies_included", 0)

    total_identified = from_databases + from_registers + from_other
    if total_identified <= 0:
        issues.append(
            issue(
                "error",
                "NO_RECORDS_IDENTIFIED",
                detail="report the actual number of records the searches returned",
            )
        )
    equations = [
        (
            "records_screened = databases + registers + other - duplicates_removed",
            screened,
            total_identified - duplicates,
        ),
        (
            "reports_sought = records_screened - records_excluded",
            sought,
            screened - screened_excluded,
        ),
        (
            "reports_assessed = reports_sought - reports_not_retrieved",
            assessed,
            sought - not_retrieved,
        ),
        (
            "studies_included = reports_assessed - reports_excluded",
            studies,
            assessed - excluded,
        ),
        (
            "sum(exclusion_reasons) = reports_excluded",
            sum(int(value) for value in reasons.values()) if reasons else 0,
            excluded,
        ),
    ]
    for label, actual, expected in equations:
        if int(actual) != int(expected):
            issues.append(
                issue(
                    "error",
                    "FLOW_ARITHMETIC_MISMATCH",
                    detail="%s: recorded %s, expected %s" % (label, fmt(actual), fmt(expected)),
                )
            )
    if studies > assessed:
        issues.append(issue("error", "MORE_INCLUDED_THAN_ASSESSED"))
    if not studies:
        issues.append(
            issue("warning", "NO_STUDIES_INCLUDED", detail="verify the screening log before finalising")
        )
    if not reasons and excluded:
        issues.append(
            issue(
                "warning",
                "EXCLUSION_REASONS_MISSING",
                detail="list at least one reason per excluded full-text report",
            )
        )
    return issues


def build_boxes(counts: dict) -> list:
    ident = counts["identification"]
    screening = counts["screening"]
    retrieval = counts["retrieval"]
    eligibility = counts["eligibility"]
    included = counts["included"]
    reasons = eligibility.get("exclusion_reasons", {}) or {}
    reason_lines = [
        "  %s (n = %s)" % (str(key).replace("_", " "), fmt(value))
        for key, value in sorted(reasons.items())
    ]
    return [
        (
            "Identification",
            [
                "Records identified from databases (n = %s)"
                % fmt(ident["records_from_databases"]),
                "Records identified from registers (n = %s)"
                % fmt(ident["records_from_registers"]),
                "Records identified from other methods (n = %s)"
                % fmt(ident["records_from_other_methods"]),
                "Duplicates removed before screening (n = %s)"
                % fmt(ident["duplicates_removed"]),
            ],
        ),
        (
            "Screening",
            [
                "Records screened (n = %s)" % fmt(screening["records_screened"]),
                "Records excluded (n = %s)" % fmt(screening["records_excluded"]),
            ],
        ),
        (
            "Screening",
            [
                "Reports sought for retrieval (n = %s)" % fmt(retrieval["reports_sought"]),
                "Reports not retrieved (n = %s)" % fmt(retrieval["reports_not_retrieved"]),
            ],
        ),
        (
            "Screening",
            [
                "Reports assessed for eligibility (n = %s)"
                % fmt(eligibility["reports_assessed"]),
                "Reports excluded (n = %s):" % fmt(eligibility["reports_excluded"]),
            ]
            + (reason_lines if reason_lines else ["  reasons not recorded"]),
        ),
        (
            "Included",
            [
                "Studies included in review (n = %s)" % fmt(included["studies_included"]),
                "Sources verified for citation (n = %s)"
                % fmt(included.get("sources_verified", included["studies_included"])),
            ],
        ),
    ]


def render_svg(counts: dict) -> str:
    boxes = build_boxes(counts)
    heights = [max(BOX_H, 30 + LINE_H * len(lines)) for _, lines in boxes]
    total = TOP + sum(heights) + GAP * (len(boxes) - 1) + 50
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
        'role="img" aria-label="Screening flow diagram of records identified, screened, and included">'
        % (WIDTH, total, WIDTH, total),
        '  <defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" '
        'fill="#1a1a1a"/></marker></defs>',
        '  <rect width="100%" height="100%" fill="#ffffff"/>',
        '  <g font-family="Helvetica, Arial, sans-serif" font-size="13" fill="#1a1a1a">',
    ]
    y = TOP
    for index, (stage, lines) in enumerate(boxes):
        height = heights[index]
        out.append(
            '    <rect x="%d" y="%d" width="%d" height="%d" fill="#f7f7f7" stroke="#1a1a1a" '
            'stroke-width="1.2" rx="3"/>' % (LEFT_X, y, BOX_W, height)
        )
        out.append(
            '    <text x="24" y="%d" font-size="12" font-weight="600" fill="#444444">%s</text>'
            % (y + 20, xml_escape(stage))
        )
        offset = y + 22
        for line_index, line in enumerate(lines):
            weight = ' font-weight="600"' if line_index == 0 else ""
            out.append(
                '    <text x="%d" y="%d"%s>%s</text>'
                % (LEFT_X + 14, offset, weight, xml_escape(line))
            )
            offset += LINE_H
        if index < len(boxes) - 1:
            out.append(
                '    <line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#1a1a1a" stroke-width="1.2" '
                'marker-end="url(#a)"/>'
                % (LEFT_X + BOX_W // 2, y + height, LEFT_X + BOX_W // 2, y + height + GAP)
            )
        y += height + GAP
    out.append(
        '    <text x="24" y="%d" font-size="11" fill="#444444">Counts come from '
        "prisma_counts.json and are checked arithmetically before this figure is written.</text>"
        % (TOP - 28)
    )
    out.extend(["  </g>", "</svg>"])
    return "\n".join(out) + "\n"


def render_mermaid(counts: dict) -> str:
    ident = counts["identification"]
    screening = counts["screening"]
    retrieval = counts["retrieval"]
    eligibility = counts["eligibility"]
    included = counts["included"]
    reasons = eligibility.get("exclusion_reasons", {}) or {}
    reason_text = "<br/>".join(
        "%s (n = %s)" % (str(key).replace("_", " "), fmt(value))
        for key, value in sorted(reasons.items())
    )
    return (
        "\n".join(
            [
                "flowchart TD",
                '  A["Records identified from databases (n = %s); registers (n = %s); '
                'other methods (n = %s)<br/>Duplicates removed (n = %s)"]'
                % (
                    fmt(ident["records_from_databases"]),
                    fmt(ident["records_from_registers"]),
                    fmt(ident["records_from_other_methods"]),
                    fmt(ident["duplicates_removed"]),
                ),
                '  B["Records screened (n = %s)"]' % fmt(screening["records_screened"]),
                '  B1["Records excluded (n = %s)"]' % fmt(screening["records_excluded"]),
                '  C["Reports sought for retrieval (n = %s)"]'
                % fmt(retrieval["reports_sought"]),
                '  C1["Reports not retrieved (n = %s)"]'
                % fmt(retrieval["reports_not_retrieved"]),
                '  D["Reports assessed for eligibility (n = %s)"]'
                % fmt(eligibility["reports_assessed"]),
                '  D1["Reports excluded (n = %s)<br/>%s"]'
                % (fmt(eligibility["reports_excluded"]), reason_text or "reasons not recorded"),
                '  E["Studies included in review (n = %s)"]' % fmt(included["studies_included"]),
                "  A --> B",
                "  B --> B1",
                "  B --> C",
                "  C --> C1",
                "  C --> D",
                "  D --> D1",
                "  D --> E",
            ]
        )
        + "\n"
    )


def render_markdown(counts: dict, caption: str) -> str:
    mermaid = render_mermaid(counts)
    return (
        "<!-- Generated by make_prisma_flow.py from prisma_counts.json. Do not edit by hand. -->\n\n"
        "```mermaid\n" + mermaid + "```\n\n"
        "**" + caption + "**\n\n"
        "Counts reflect the searches recorded in `search_log.csv` up to "
        + str(counts.get("search_date_range") or "the date recorded in scope.md")
        + ". The review is declared as `"
        + str(counts.get("review_type") or "narrative")
        + "`; the flow reports how records were identified and screened without claiming "
        "systematic-review exhaustiveness unless a systematic search was performed.\n"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate screening counts and draw a PRISMA-style flow diagram. Writes nothing "
            "unless every arithmetic identity holds."
        )
    )
    parser.add_argument("counts", help="UTF-8 JSON file of screening counts")
    parser.add_argument(
        "--out-dir",
        default=None,
        help="directory for the generated figure (not needed with --check-only)",
    )
    parser.add_argument("--caption", default=None, help="figure caption")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="validate the counts without writing files",
    )
    return parser


def cli() -> int:
    args = build_parser().parse_args()
    counts = require_object(read_json(args.counts), "counts")
    issues = check_counts(counts)
    caption = args.caption or ("Screening flow for " + (counts.get("review_title") or "this review"))
    error_count = sum(item.severity == "error" for item in issues)
    ident = counts["identification"]
    if not error_count and not args.check_only and not args.out_dir:
        issues.append(
            issue(
                "error",
                "OUT_DIR_REQUIRED",
                detail="pass --out-dir to write the figure, or --check-only to validate only",
            )
        )
        error_count = 1
    if error_count or args.check_only:
        return emit_report(
            TOOL,
            issues,
            summary={"wrote_files": False},
            extra={"recorded_studies_included": counts["included"].get("studies_included")},
        )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    svg_path = out_dir / "prisma_flow.svg"
    mmd_path = out_dir / "prisma_flow.mmd"
    md_path = out_dir / "prisma_flow.md"
    write_text_lf(svg_path, render_svg(counts))
    write_text_lf(mmd_path, render_mermaid(counts))
    write_text_lf(md_path, render_markdown(counts, caption))
    return emit_report(
        TOOL,
        issues,
        summary={
            "wrote_files": True,
            "records_identified": ident["records_from_databases"]
            + ident["records_from_registers"]
            + ident["records_from_other_methods"],
            "files": [str(svg_path), str(mmd_path), str(md_path)],
        },
    )


if __name__ == "__main__":
    run(TOOL, cli)

