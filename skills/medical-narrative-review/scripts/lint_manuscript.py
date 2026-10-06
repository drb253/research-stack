"""Lint medical review prose for overclaiming, missing sections, undefined
abbreviations, unresolved placeholders, PHI-like strings, and dangling
table/figure references.

Advisory by design: warnings point at line numbers and never rewrite text. Use
`--sections` before submission. Offline, deterministic, standard library only.
"""

from __future__ import annotations

import argparse
import re

from _common import emit_report, issue, read_text, run

TOOL = "lint_manuscript"

PLACEHOLDER_RE = re.compile(r"\[\[\s*TODO|\[UNVERIFIED|DO NOT CITE|\[citation needed\]", re.IGNORECASE)
OVERCLAIM_RE = re.compile(
    r"\b(breakthrough|revolutionary|miracle|game[- ]chang\w+|cutting[- ]edge|"
    r"unprecedented|paradigm shift|state[- ]of[- ]the[- ]art|miracle cure|"
    r"dramatically (?:reduced|improved|cured)|cure[sd]? all|completely safe|"
    r"no side effects|risk[- ]free|proves? that|cures? (?:cancer|the disease))\b",
    re.IGNORECASE,
)
ABSOLUTE_RE = re.compile(
    r"\b(always|never|invariably|in all patients|every patient|guarantee[sd]?|"
    r"conclusively (?:proves|demonstrates)|definitively establishes)\b",
    re.IGNORECASE,
)
CAUSAL_RE = re.compile(
    r"\b(causes?|caused|causing|leads? to|led to|result(?:s|ed) in|because of the treatment)\b"
    r"(?!\s+of\b)",
    re.IGNORECASE,
)
NOUN_CAUSE_RE = re.compile(
    r"\b(?:leading|common|major|principal|main|underlying|possible|likely|only|no|a|the)\s+causes?\b",
    re.IGNORECASE,
)
HEDGE_WORDS = (
    "associated with",
    "may",
    "might",
    "suggests",
    "suggest",
    "appears",
    "possible",
    "potentially",
    "cannot",
    "did not",
    "no evidence",
)
PHI_RE = (
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("PHONE", re.compile(r"\b(?:\+?[0-9]{1,3}[ -]?)?(?:\([0-9]{3}\)|[0-9]{3})[ -][0-9]{3}[ -][0-9]{4}\b")),
    ("MRN", re.compile(r"\b(MRN|medical record number|hospital number|accession number)\b", re.IGNORECASE)),
    ("DOB", re.compile(r"\b(date of birth|DOB|born on)\b", re.IGNORECASE)),
    ("PATIENT_INITIALS", re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Dr)\.?\s+[A-Z]\b")),
    ("NAMED_PATIENT", re.compile(r"\bpatient\s+[A-Z]{1,3}[0-9]{1,4}\b")),
)
TABLE_REF_RE = re.compile(r"\bTable\s+([0-9]{1,2})\b")
FIGURE_REF_RE = re.compile(r"\bFig(?:ure)?\.?\s+([0-9]{1,2})\b")
CAPTION_RE = re.compile(
    r"^\s*#{0,6}\s*(?:\*\*)?(Table|Figure|Fig\.)\s*([0-9]{1,2})\b", re.IGNORECASE
)
DECLARATION_PATTERNS = (
    ("funding", re.compile(r"\bfunding\b|\bfunded by\b", re.IGNORECASE)),
    (
        "conflict of interest",
        re.compile(r"conflict(?:s)? of interest|competing interest|declaration of interest", re.IGNORECASE),
    ),
    (
        "author contributions",
        re.compile(r"author contribution|CRediT", re.IGNORECASE),
    ),
    ("data availability", re.compile(r"data availability|data sharing", re.IGNORECASE)),
    (
        "AI use",
        re.compile(r"\bAI\b|artificial intelligence|large language model|generative model", re.IGNORECASE),
    ),
)
CITE_RE = re.compile(r"\[[0-9]{1,4}(?:\s*[,-]\s*[0-9]{1,4})*\]")
ABBREV_RE = re.compile(r"\b([A-Z][A-Z0-9-]{1,6})\b")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

REQUIRED_SECTIONS = (
    "abstract",
    "introduction",
    "methods",
    "discussion",
    "conclusion",
    "reference",
    "declaration",
)
ABBREV_ALLOWLIST = {
    "AI",
    "PMC",
    "PMID",
    "DOI",
    "ORCID",
    "PRISMA",
    "GRADE",
    "PICO",
    "CREDIT",
    "DNA",
    "RNA",
    "HIV",
    "MRI",
    "CT",
    "BMI",
    "ICU",
    "PCR",
    "MRNA",
    "IGG",
    "USA",
    "UK",
    "EU",
    "WHO",
    "FDA",
    "EMA",
    "NICE",
    "COVID",
    "SARS",
    "AIDS",
    "TNF",
    "IL",
    "CD",
    "PD",
    "ALK",
    "EGFR",
    "CI",
    "SD",
    "IQR",
    "HR",
    "OR",
    "RR",
    "ITT",
    "MD",
    "PhD",
}



def check_lines(text: str) -> tuple:
    issues: list = []
    captions: set = set()
    table_refs: list = []
    figure_refs: list = []
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
        for code, pattern in PHI_RE:
            if pattern.search(line):
                issues.append(issue("error", "POSSIBLE_PHI_" + code, location=location))
        if OVERCLAIM_RE.search(line):
            issues.append(issue("warning", "OVERCLAIMING_LANGUAGE", location=location))
        if ABSOLUTE_RE.search(line):
            issues.append(issue("warning", "ABSOLUTE_LANGUAGE", location=location))
        if CAUSAL_RE.search(line) and not NOUN_CAUSE_RE.search(line):
            if not any(word in line.lower() for word in HEDGE_WORDS):
                issues.append(issue("warning", "CAUSAL_CLAIM_WITHOUT_HEDGE", location=location))
        for token in SENTENCE_SPLIT_RE.split(stripped):
            if len(token.split()) > 55:
                issues.append(issue("info", "VERY_LONG_SENTENCE", location=location))
                break
        caption = CAPTION_RE.match(stripped)
        if caption:
            captions.add((caption.group(1).lower().rstrip("."), caption.group(2)))
        table_refs.extend((number, location) for number in TABLE_REF_RE.findall(line))
        figure_refs.extend((number, location) for number in FIGURE_REF_RE.findall(line))
    return issues, captions, table_refs, figure_refs


def check_displays(captions: set, table_refs: list, figure_refs: list) -> list:
    issues: list = []
    caption_keys = set(captions)
    for number, location in table_refs:
        if ("table", number) not in caption_keys:
            issues.append(
                issue("error", "TABLE_REFERENCE_WITHOUT_CAPTION", location=location, item_id=number)
            )
    for number, location in figure_refs:
        if ("figure", number) not in caption_keys and ("fig", number) not in caption_keys:
            issues.append(
                issue("error", "FIGURE_REFERENCE_WITHOUT_CAPTION", location=location, item_id=number)
            )
    for kind, number in sorted(captions):
        refs = table_refs if kind == "table" else figure_refs
        if not any(reference == number for reference, _ in refs):
            issues.append(
                issue("warning", "CAPTION_NEVER_REFERENCED_IN_TEXT", item_id=kind + " " + number)
            )
    return issues


def check_sections(text: str) -> tuple:
    issues: list = []
    headings = [
        line.lstrip("#").strip().lower() for line in text.splitlines() if line.startswith("#")
    ]
    joined = " | ".join(headings)
    for section in REQUIRED_SECTIONS:
        if section not in joined:
            issues.append(issue("error", "MISSING_SECTION", item_id=section))

    declarations_block: list = []
    collecting = False
    for line in text.splitlines():
        if line.startswith("#"):
            collecting = "declaration" in line.lstrip("#").strip().lower()
            continue
        if collecting:
            declarations_block.append(line)
    if not declarations_block:
        return issues, headings
    block = "\n".join(declarations_block)
    for label, pattern in DECLARATION_PATTERNS:
        if not pattern.search(block):
            issues.append(issue("error", "MISSING_DECLARATION", item_id=label))
    return issues, headings


def check_citations_by_section(text: str) -> list:
    issues: list = []
    scope = ""
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line.startswith("#"):
            scope = line.lstrip("#").strip().lower()
            continue
        if not CITE_RE.search(line):
            continue
        if scope.startswith("abstract"):
            issues.append(issue("warning", "CITATION_IN_ABSTRACT", location="line:%d" % line_number))
        elif scope.startswith(("conclusion", "conclusions")):
            issues.append(
                issue(
                    "warning",
                    "CITATION_IN_CONCLUSIONS",
                    location="line:%d" % line_number,
                    detail="conclusions should not introduce new sources",
                )
            )
    return issues


def check_abbreviations(text: str, allow: set) -> list:
    issues: list = []
    body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    defined: set = set()
    for match in re.finditer(r"\(([^()]{2,80})\)", body):
        for token in ABBREV_RE.findall(match.group(1)):
            defined.add(token.upper())
    for match in re.finditer(r"\b([A-Z][A-Z0-9-]{1,6})\b\s*(?:[,:=]|\s-\s)\s*[a-z]", body):
        defined.add(match.group(1).upper())
    seen: set = set()
    for match in ABBREV_RE.finditer(body):
        token = match.group(1).upper()
        if token in seen or token in defined or token in allow or token in ABBREV_ALLOWLIST:
            continue
        seen.add(token)
        if len(re.findall(r"\b" + re.escape(token) + r"\b", body)) >= 2:
            issues.append(
                issue(
                    "warning",
                    "ABBREVIATION_NOT_DEFINED",
                    item_id=token,
                    detail="define at first use as 'expanded form (%s)'" % token,
                )
            )
    return issues


def check_advisory(path: str) -> list:
    """Read optional model-generated advisory findings. Never errors, never blocks.

    The file is produced out of band (for example by a local classifier via MCP) and
    is reported as info-severity only, tagged with its generator so a reader always
    knows the finding is model-generated and advisory.
    """
    from _common import InputError, read_json, require_list, require_object

    issues: list = []
    try:
        data = require_object(read_json(path), "advisory")
        findings = require_list(data.get("findings", []), "findings")
    except (InputError, OSError, ValueError) as exc:
        # Fail open: an optional, non-authoritative input must never block a submission.
        return [
            issue(
                "warning",
                "ADVISORY_FILE_UNREADABLE",
                detail="advisory ignored: " + type(exc).__name__,
            )
        ]
    generator = str(data.get("generator", "unspecified"))[:80]
    model = str(data.get("model", "unspecified"))[:80]
    generated_on = str(data.get("generated_on", ""))[:20]
    issues.append(
        issue(
            "info",
            "ADVISORY_FINDINGS_INCLUDED",
            detail="generator=%s model=%s date=%s count=%d"
            % (generator, model, generated_on, len(findings)),
        )
    )
    for index, raw in enumerate(findings):
        try:
            finding = require_object(raw, "findings[%d]" % index)
        except InputError:
            issues.append(
                issue("warning", "ADVISORY_FINDING_NOT_AN_OBJECT", item_id=str(index))
            )
            continue
        kind = str(finding.get("type", "")).strip()
        if not kind:
            issues.append(issue("warning", "ADVISORY_FINDING_WITHOUT_TYPE", item_id=str(index)))
            continue
        code = "ADVISORY_" + re.sub(r"[^A-Za-z0-9]+", "_", kind).upper().strip("_")[:40]
        location = str(finding.get("location", "")).strip()[:60] or None
        claim_id = str(finding.get("claim_id", "")).strip()[:20] or None
        details: list = []
        for key in ("probability", "score", "hedging_score"):
            if key in finding:
                try:
                    value = float(finding[key])
                except (TypeError, ValueError):
                    issues.append(
                        issue("warning", "ADVISORY_INVALID_VALUE", item_id=code, detail=key)
                    )
                    continue
                if not 0.0 <= value <= 1.0:
                    issues.append(
                        issue("warning", "ADVISORY_VALUE_OUT_OF_RANGE", item_id=code, detail=key)
                    )
                else:
                    details.append("%s=%.2f" % (key, value))
        for key in ("certainty", "note", "model_label"):
            if finding.get(key):
                details.append("%s=%s" % (key, str(finding[key])[:120]))
        details.append("advisory, model-generated, not a gate input")
        issues.append(issue("info", code, location=location, item_id=claim_id, detail="; ".join(details)))
    return issues


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Lint a medical review manuscript: overclaiming, absolute and unhedged causal "
            "language, placeholders, PHI-like strings, section and declaration completeness, "
            "undefined abbreviations, and dangling table or figure references."
        )
    )
    parser.add_argument("manuscript", help="UTF-8 Markdown manuscript")
    parser.add_argument(
        "--advisory",
        default=None,
        help=(
            "optional JSON of model-generated advisory findings; reported as info only "
            "(see references/advisory_laya.md)"
        ),
    )
    parser.add_argument(
        "--sections",
        action="store_true",
        help="require the standard sections and declarations (use before submission)",
    )
    parser.add_argument(
        "--allow-abbrev",
        action="append",
        default=[],
        help="abbreviation to accept without a definition (repeatable)",
    )
    parser.add_argument(
        "--max-word-count",
        type=int,
        default=0,
        help="warn when the manuscript exceeds this word count",
    )
    return parser


def cli() -> int:
    args = build_parser().parse_args()
    text = read_text(args.manuscript, {".md", ".markdown"})
    issues, captions, table_refs, figure_refs = check_lines(text)
    issues.extend(check_displays(captions, table_refs, figure_refs))
    headings: list = []
    if args.sections:
        section_issues, headings = check_sections(text)
        issues.extend(section_issues)
    issues.extend(check_citations_by_section(text))
    issues.extend(check_abbreviations(text, {item.upper() for item in args.allow_abbrev}))
    advisories = 0
    if args.advisory:
        from pathlib import Path as _Path

        if not _Path(args.advisory).is_file():
            issues.append(
                issue(
                    "warning",
                    "ADVISORY_FILE_MISSING",
                    detail="no advisory findings file at " + str(args.advisory)[:80],
                )
            )
        else:
            advisory_issues = check_advisory(args.advisory)
            advisories = sum(
                1 for item in advisory_issues if item.code.startswith("ADVISORY_") and item.severity == "info"
            )
            issues.extend(advisory_issues)

    words = len(re.findall(r"[A-Za-z][A-Za-z'\u2019-]*", text))
    if args.max_word_count and words > args.max_word_count:
        issues.append(
            issue(
                "warning",
                "WORD_COUNT_EXCEEDED",
                detail="%d words against a limit of %d" % (words, args.max_word_count),
            )
        )
    return emit_report(
        TOOL,
        issues,
        summary={
            "words": words,
            "headings": len(headings),
            "tables_captioned": sum(1 for kind, _ in captions if kind == "table"),
            "figures_captioned": sum(1 for kind, _ in captions if kind != "table"),
            "numbered_citations": len(CITE_RE.findall(text)),
            "advisory_findings": advisories,
        },
    )


if __name__ == "__main__":
    run(TOOL, cli)

