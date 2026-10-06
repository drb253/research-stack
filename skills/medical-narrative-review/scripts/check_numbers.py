"""Check numeric consistency inside a marked manuscript: fractions, percentages,
intervals, direction of significance statements, and abstract-versus-body drift.

Deterministic, offline, no third-party packages. Every finding names the line or
claim ID; the report never echoes a full sentence.
"""

from __future__ import annotations

import argparse
import re

from _common import Issue, emit_report, issue, read_text, run

TOOL = "check_numbers"

CLAIM_MARKER_RE = re.compile(r"\[claim:(C[0-9]{3,8})\]")
PCT_FRACTION_RE = re.compile(r"(\d[\d,]*)\s*/\s*(\d[\d,]*)\s*\((\d+(?:\.\d+)?)\s*%")
PCT_FRACTION_REVERSED_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*\((\d[\d,]*)\s*/\s*(\d[\d,]*)\)")
CI_RE = re.compile(
    r"(?P<est>-?\d+(?:\.\d+)?)\s*\((?P<level>9[0-9])%\s*(?:CI|confidence interval)[^0-9-]{0,6}"
    r"(?P<lo>-?\d+(?:\.\d+)?)\s*(?:to|and|[-\u2013,])\s*(?P<hi>-?\d+(?:\.\d+)?)\)",
    re.IGNORECASE,
)
CI_BARE_RE = re.compile(
    r"(?P<est>-?\d+(?:\.\d+)?)\s*[,;]?\s*"
    r"(?:(?P<level>9[0-9])%\s*(?:CI|CrI|confidence interval)|CI)\s*[:]?\s*"
    r"(?P<lo>-?\d+(?:\.\d+)?)\s*(?:to|and|[\u2013-])\s*(?P<hi>-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
EFFECT_RE = re.compile(
    r"\b(?P<label>a?HR|a?OR|a?RR|IRR|HR|hazard ratio|odds ratio|risk ratio)\b[^0-9]{0,24}"
    r"(?P<value>\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
P_VALUE_RE = re.compile(r"\bp\s*(?P<op>[<>=]|\u2264|\u2265)\s*(?P<value>\d*\.?\d+)", re.IGNORECASE)
ANY_PCT_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*%")
SIGNIFICANCE_RE = re.compile(r"\bsignifican\w*", re.IGNORECASE)
NEGATION_WINDOW_RE = re.compile(
    r"\bnot\b|\bno\b|\bnon-|\bwithout\b|\bnever\b|failed to|did not|\bneither\b|\bnonsignifican",
    re.IGNORECASE,
)
THRESHOLD_RE = re.compile(
    r"criterion|criteria|threshold|pre-?specified|alpha level|powered for|\binterim\b",
    re.IGNORECASE,
)

EFFECT_LABELS = (
    ("hazard ratio", "hr"),
    ("hr", "hr"),
    ("ahr", "hr"),
    ("odds ratio", "or"),
    ("or", "or"),
    ("aor", "or"),
    ("risk ratio", "rr"),
    ("rr", "rr"),
    ("arr", "rr"),
    ("irr", "irr"),
)

UNIT_PAIRS = (
    ("mg/dL", "mmol/L"),
    ("mg/dl", "mmol/l"),
    ("ng/mL", "pmol/L"),
    ("ug/mL", "nmol/L"),
    ("mcg/mL", "nmol/L"),
)

TOLERANCE = 0.6


def check_fraction(line: str, location: str) -> list:
    issues: list = []
    for match in PCT_FRACTION_RE.finditer(line):
        numerator = float(match.group(1).replace(",", ""))
        denominator = float(match.group(2).replace(",", ""))
        reported = float(match.group(3))
        issues.extend(_compare(numerator, denominator, reported, location))
    for match in PCT_FRACTION_REVERSED_RE.finditer(line):
        reported = float(match.group(1))
        numerator = float(match.group(2).replace(",", ""))
        denominator = float(match.group(3).replace(",", ""))
        issues.extend(_compare(numerator, denominator, reported, location))
    return issues


def _compare(numerator: float, denominator: float, reported: float, location: str) -> list:
    issues: list = []
    if denominator <= 0:
        issues.append(issue("error", "ZERO_DENOMINATOR", location=location))
        return issues
    if numerator > denominator:
        issues.append(issue("error", "NUMERATOR_EXCEEDS_DENOMINATOR", location=location))
        return issues
    expected = 100.0 * numerator / denominator
    if abs(expected - reported) > TOLERANCE:
        issues.append(
            issue(
                "error",
                "PERCENTAGE_MISMATCH",
                location=location,
                detail="%.1f vs %.1f" % (reported, expected),
            )
        )
    return issues



def check_interval(line: str, location: str) -> list:
    issues: list = []
    spans: set = set()
    for regex in (CI_RE, CI_BARE_RE):
        for match in regex.finditer(line):
            if match.span("est") in spans:
                continue
            spans.add(match.span("est"))
            estimate = float(match.group("est"))
            lower = float(match.group("lo"))
            upper = float(match.group("hi"))
            if lower > upper:
                issues.append(issue("error", "CI_BOUNDS_INVERTED", location=location))
                continue
            if not (lower <= estimate <= upper):
                issues.append(
                    issue(
                        "error",
                        "CI_DOES_NOT_CONTAIN_ESTIMATE",
                        location=location,
                        detail="%s not in %s to %s" % (estimate, lower, upper),
                    )
                )
    return issues


def check_percentages(line: str, location: str) -> list:
    issues: list = []
    for match in ANY_PCT_RE.finditer(line):
        value = float(match.group("value"))
        if value > 100:
            issues.append(
                issue("error", "PERCENTAGE_OUT_OF_RANGE", location=location, detail=str(value))
            )
    return issues


def classify_significance(line: str) -> tuple:
    """Count significant-word occurrences that are asserted versus negated."""
    positive = 0
    negative = 0
    for match in SIGNIFICANCE_RE.finditer(line):
        window = line[max(0, match.start() - 32) : match.start()]
        if NEGATION_WINDOW_RE.search(window):
            negative += 1
        else:
            positive += 1
    return positive, negative


def check_significance(line: str, location: str) -> list:
    issues: list = []
    positive, negative = classify_significance(line)
    if not (positive or negative):
        return issues
    if positive and negative:
        issues.append(issue("warning", "CONTRADICTORY_SIGNIFICANCE_WORDING", location=location))
    p_values = list(P_VALUE_RE.finditer(line))
    if not p_values and not CI_RE.search(line) and not CI_BARE_RE.search(line):
        issues.append(issue("warning", "SIGNIFICANCE_WITHOUT_STATISTIC", location=location))
        return issues
    for match in p_values:
        operator = match.group("op")
        value = float(match.group("value"))
        if value >= 0.05 and positive and not negative and operator in ("=", ">", "\u2265"):
            issues.append(issue("error", "SIGNIFICANCE_WITH_NON_SIGNIFICANT_P", location=location))
        if value < 0.05 and negative and not positive and operator in ("=", "<", "\u2264"):
            # A stricter pre-specified threshold makes p < 0.05 legitimately non-significant,
            # which is how trials such as KEYNOTE-671 are reported.
            if not THRESHOLD_RE.search(line):
                issues.append(
                    issue("error", "NON_SIGNIFICANCE_WITH_SIGNIFICANT_P", location=location)
                )
            else:
                issues.append(
                    issue(
                        "info",
                        "NON_SIGNIFICANCE_EXPLAINED_BY_THRESHOLD",
                        location=location,
                        detail="verify the pre-specified threshold in the source",
                    )
                )
        if operator == "=" and value == 0:
            issues.append(issue("warning", "P_VALUE_REPORTED_AS_ZERO", location=location))
        if operator in ("<", "\u2264") and value < 0.001:
            issues.append(issue("warning", "P_VALUE_BELOW_REPORTING_FLOOR", location=location))
    return issues



def normalize_effect_label(label: str) -> str:
    lowered = label.strip().lower()
    for name, canonical in EFFECT_LABELS:
        if lowered == name:
            return canonical
    return lowered


def check_claim_drift(text: str) -> list:
    """The same claim ID must not carry two different effect values."""
    issues: list = []
    effects: dict = {}
    percentages: dict = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        claim_ids = CLAIM_MARKER_RE.findall(line)
        if not claim_ids:
            continue
        location = "line:%d" % line_number
        for match in EFFECT_RE.finditer(line):
            key = (claim_ids[-1], normalize_effect_label(match.group("label")))
            value = match.group("value")
            if key in effects and effects[key][0] != value:
                issues.append(
                    issue(
                        "error",
                        "EFFECT_VALUE_DRIFT_WITHIN_CLAIM",
                        location=location,
                        item_id=claim_ids[-1],
                        detail="%s vs %s" % (effects[key][0], value),
                    )
                )
            else:
                effects[key] = (value, location)
        for match in ANY_PCT_RE.finditer(line):
            percentages.setdefault(claim_ids[-1], []).append(match.group("value"))
    for claim_id, values in percentages.items():
        distinct = sorted(set(values))
        if len(distinct) > 1:
            issues.append(
                issue(
                    "warning",
                    "MULTIPLE_PERCENTAGES_IN_CLAIM",
                    item_id=claim_id,
                    detail=",".join(distinct[:4]),
                )
            )
    return issues


def check_units(text: str) -> list:
    issues: list = []
    lowered = text.lower()
    for first, second in UNIT_PAIRS:
        if first.lower() in lowered and second.lower() in lowered:
            issues.append(issue("info", "MIXED_UNIT_SYSTEMS", detail=first + " and " + second))
    return issues


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Recompute percentages from recorded numerators and denominators, verify that "
            "confidence intervals contain their point estimates, check significance wording "
            "against reported p values, and detect drift within a single claim."
        )
    )
    parser.add_argument("manuscript", help="UTF-8 Markdown manuscript")
    parser.add_argument(
        "--include-headings",
        action="store_true",
        help="also scan lines that start with '#' or '|'",
    )
    return parser


def cli() -> int:
    args = build_parser().parse_args()
    text = read_text(args.manuscript, {".md", ".markdown"})
    issues: list = []
    in_fence = False
    scanned = 0
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not args.include_headings and stripped.startswith(("#", "|")):
            continue
        location = "line:%d" % line_number
        found = (
            check_fraction(line, location)
            + check_interval(line, location)
            + check_percentages(line, location)
            + check_significance(line, location)
        )
        issues.extend(found)
        if found or ANY_PCT_RE.search(line) or "CI" in line:
            scanned += 1
    issues.extend(check_claim_drift(text))
    issues.extend(check_units(text))
    return emit_report(TOOL, issues, summary={"numeric_lines_reviewed": scanned})


if __name__ == "__main__":
    run(TOOL, cli)
