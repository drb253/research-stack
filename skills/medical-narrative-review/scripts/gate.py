"""Run every bundled audit against a review workspace and report one verdict.

The gate is the authority on readiness. It runs the validators, the citation audit,
the numeric check, the prose lint, and the screening-flow arithmetic check, then
prints a single pass/fail report and, unless disabled, writes GATE_REPORT.json.

Exit code 0 means every check passed. Anything else means the review is not
submission-ready, regardless of how finished the prose looks.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from _common import emit_report, issue, run, write_text_lf

TOOL = "gate"

CHECKS = (
    ("sources", "validate_sources.py", ["--strict", "--require-included"]),
    ("citations_draft", "audit_citations.py", ["--strict"]),
    ("citations_final", "audit_citations.py", ["--final", "--strict"]),
    ("numbers", "check_numbers.py", []),
    ("prose", "lint_manuscript.py", ["--sections"]),
    ("screening_flow", "make_prisma_flow.py", ["--check-only"]),
)


def run_script(script: str, args: list) -> tuple:
    script_path = Path(__file__).resolve().parent / script
    if not script_path.is_file():
        return None, "missing bundled script: " + script
    completed = subprocess.run(
        [sys.executable, str(script_path)] + args,
        capture_output=True,
        text=True,
        check=False,
    )
    if not completed.stdout.strip():
        return None, (completed.stderr.strip().splitlines() or ["no output"])[-1]
    try:
        return json.loads(completed.stdout), None
    except json.JSONDecodeError:
        return None, "could not parse the report from " + script


def main_guard_failures(report: dict) -> list:
    return [item for item in report.get("issues", []) if item.get("severity") == "error"]


def collect_checks(base: Path, style: str) -> list:
    workspace = Path(base)
    sources = workspace / "sources.csv"
    claims = workspace / "claims.csv"
    draft = workspace / "draft.md"
    final_doc = workspace / "final" / "manuscript_cited.md"
    final_refs = workspace / "final" / "references.md"
    counts = workspace / "prisma_counts.json"

    plan: list = []
    if sources.is_file():
        plan.append(
            ("sources", "validate_sources.py", [str(sources), "--strict", "--require-included"])
        )
    if draft.is_file() and claims.is_file() and sources.is_file():
        plan.append(
            (
                "citations_draft",
                "audit_citations.py",
                [str(draft), str(claims), str(sources), "--strict"],
            )
        )
    if final_doc.is_file() and claims.is_file() and sources.is_file():
        arguments = [str(final_doc), str(claims), str(sources), "--final", "--strict"]
        if final_refs.is_file():
            arguments += ["--references", str(final_refs)]
        plan.append(("citations_final", "audit_citations.py", arguments))
    if final_doc.is_file():
        plan.append(("numbers", "check_numbers.py", [str(final_doc)]))
        plan.append(("prose", "lint_manuscript.py", _prose_arguments(workspace, final_doc)))
    elif draft.is_file():
        plan.append(("numbers", "check_numbers.py", [str(draft)]))
        plan.append(("prose", "lint_manuscript.py", _prose_arguments(workspace, draft)))
    if counts.is_file():
        plan.append(("screening_flow", "make_prisma_flow.py", [str(counts), "--check-only"]))
    return plan


def _prose_arguments(workspace: Path, manuscript: Path) -> list:
    """Prose-lint arguments, including an advisory file when one exists.

    Advisory findings come from an optional local classifier and are reported as info
    only; they can never change the verdict. See references/advisory_laya.md.
    """
    arguments = [str(manuscript), "--sections"]
    advisory = workspace / "advisory.json"
    if advisory.is_file():
        arguments += ["--advisory", str(advisory)]
    return arguments


def cli() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run every bundled audit against a review workspace and print one verdict. "
            "Exit code 0 only when every check passes."
        )
    )
    parser.add_argument("--dir", default=".", help="review workspace directory")
    parser.add_argument(
        "--style",
        default="vancouver",
        choices=["vancouver", "ama", "apa", "elsevier"],
        help="citation style recorded in the report",
    )
    parser.add_argument(
        "--skip-final",
        action="store_true",
        help="do not require final/manuscript_cited.md to exist",
    )
    parser.add_argument(
        "--require-exports",
        action="store_true",
        help="fail when no DOCX, PDF, or HTML export is present in final/",
    )
    args = parser.parse_args()

    base = Path(args.dir)
    if not base.is_dir():
        raise ValueError("workspace directory not found: " + args.dir)

    checks = collect_checks(base, args.style)
    issues: list = []
    results: list = []
    for name, script, script_args in checks:
        report, failure = run_script(script, script_args)
        if report is None:
            issues.append(issue("error", "CHECK_UNAVAILABLE", item_id=name, detail=failure))
            results.append({"check": name, "status": "unavailable", "detail": failure})
            continue
        errors = main_guard_failures(report)
        warnings = [
            item for item in report.get("issues", []) if item.get("severity") == "warning"
        ]
        advisories = [
            item
            for item in report.get("issues", [])
            if item.get("severity") == "info"
            and str(item.get("code", "")).startswith("ADVISORY_")
        ]
        results.append(
            {
                "check": name,
                "status": report.get("status", "unknown"),
                "errors": len(errors),
                "warnings": len(warnings),
                "advisories": len(advisories),
            }
        )
        for item in errors:
            issues.append(
                issue(
                    "error",
                    item.get("code", "UNKNOWN"),
                    item_id=name + ":" + str(item.get("item_id", "")),
                    detail=item.get("detail", ""),
                )
            )
        for item in warnings + advisories:
            issues.append(
                issue(
                    item.get("severity", "warning"),
                    item.get("code", "UNKNOWN"),
                    item_id=name + ":" + str(item.get("item_id", "")),
                    detail=item.get("detail", ""),
                )
            )

    if not (base / "final" / "manuscript_cited.md").is_file() and not args.skip_final:
        issues.append(
            issue(
                "error",
                "FINAL_MANUSCRIPT_MISSING",
                detail="run build_reference_list.py to produce final/manuscript_cited.md",
            )
        )
    if not (base / "search_log.csv").is_file():
        issues.append(issue("error", "SEARCH_LOG_MISSING"))
    unresolved = base / "UNRESOLVED.md"
    if unresolved.is_file():
        text = unresolved.read_text(encoding="utf-8", errors="replace")
        if "_none yet_" not in text:
            issues.append(
                issue(
                    "warning",
                    "UNRESOLVED_ITEMS_RECORDED",
                    detail="review UNRESOLVED.md before submission",
                )
            )

    final_dir = base / "final"
    exports = (
        sorted(
            path.name
            for path in final_dir.iterdir()
            if path.suffix.lower() in {".docx", ".pdf", ".html"}
        )
        if final_dir.is_dir()
        else []
    )
    if exports:
        issues.append(issue("info", "EXPORTS_PRESENT", detail=", ".join(exports)[:140]))
    else:
        issues.append(
            issue(
                "error" if args.require_exports else "info",
                "NO_EXPORTED_DOCUMENT",
                detail=(
                    "run export_document.py to produce DOCX, PDF, and HTML output "
                    "from final/manuscript_cited.md"
                ),
            )
        )

    error_count = sum(item.severity == "error" for item in issues)
    payload_summary = {
        "checks_run": len(results),
        "citation_style": args.style,
        "submission_ready": error_count == 0,
        "exports": exports,
    }
    report_path = base / "GATE_REPORT.json"
    write_text_lf(
        report_path,
        json.dumps(
            {
                "tool": TOOL,
                "status": "fail" if error_count else "pass",
                "summary": payload_summary,
                "checks": results,
                "issues": [item.to_dict() for item in issues],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    return emit_report(TOOL, issues, summary=payload_summary, extra={"checks": results})


if __name__ == "__main__":
    run(TOOL, cli)

