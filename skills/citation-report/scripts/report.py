"""citation-report command line: build the source bundle, grade the sentences, render.

Four modes, following the same shape as the repository's other skills:

* ``report`` (default) — grade and render the report in one or more formats.
* ``sources`` — build and validate the source registry without rendering.
* ``verify`` — re-validate a recorded ``verdicts.json`` against the document and the
  sources, without re-classifying. This is the reproducibility check.
* ``audit`` — print the findings as text, no rendering. For agents and CI.

Everything is local and deterministic. Network access is used only to resolve DOIs
and is disabled entirely by ``--offline``, which is the mode the test suite runs in.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

import _bundle
import _common
import _evidence
import _highlight
import _intake
import coverage
import preconditions
import sufficiency
import verdicts

FORMATS = ("pdf", "docx", "html", "table", "json")
SCHEMA = "citation-report/verdicts/1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="report.py",
        description="build an auditable per-sentence citation report",
    )
    parser.add_argument("mode", nargs="?", default="report", choices=("report", "sources", "verify", "audit", "worklist"))
    parser.add_argument("--document", required=True, help="the document to grade (md/txt/docx/tex/pdf)")
    parser.add_argument("--bib", help="BibTeX file; its file={...} field links to supplied PDFs")
    parser.add_argument("--pdf-dir", help="directory of source PDFs (or .txt sidecars)")
    parser.add_argument("--sources", help="a sources.csv ledger from this repository's review skills")
    parser.add_argument("--claims", help="a claims.csv claim ledger, so [claim:C001] resolves")
    parser.add_argument("--dois", help="a plain list of DOIs or PMIDs")
    parser.add_argument("--style", default="all", choices=("numeric", "author-year", "ledger", "all"))
    parser.add_argument("--offline", action="store_true", help="make no network calls at all")
    parser.add_argument(
        "--acquire",
        default="all",
        choices=("all", "api", "pdf", "cli", "none"),
        help="which open-access acquisition tiers to try for sources with no evidence "
        "(default all): keyless full-text API, open-access PDF download, the optional "
        "paper-search CLI. Never bypasses a paywall.",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="never download a file, leaving only the keyless API and abstract tiers",
    )
    parser.add_argument(
        "--cache-dir",
        help="where acquired source files are cached (default: <out-dir>/sources). "
        "Without a cache directory the download tiers are skipped by design.",
    )
    parser.add_argument("--mailto", default="", help="contact address sent to Crossref/OpenAlex")
    parser.add_argument("--advisory", default="off", help="off (default) or a path to an advisory grades file")
    parser.add_argument("--verdicts", help="read this verdicts.json instead of re-classifying")
    parser.add_argument("--out-dir", default="citation-report", help="where artifacts are written")
    parser.add_argument("--format", default="pdf,docx,html", help="comma-separated: pdf,docx,html,table,json")
    parser.add_argument("--limit", type=int, default=0, help="grade only the first N sentences (debugging)")
    parser.add_argument("--check", action="store_true", help="run report_gate.py after rendering")
    parser.add_argument(
        "--allow-insufficient",
        action="store_true",
        help="proceed when cited sources have no readable evidence (the status stays "
        "insufficient_evidence in the JSON, so the override is logged rather than silent)",
    )
    parser.add_argument(
        "--require-evidence",
        default="strict",
        help="'strict' (default: every cited source must be checkable) or a share such "
        "as 0.6, meaning that fraction of cited sources must be checkable",
    )
    parser.add_argument(
        "--worklist",
        help="re-check a previously written evidence_worklist.csv; exits non-zero while any gap remains",
    )
    return parser


def _acquire_policy(value: str, no_download: bool) -> tuple:
    """Which acquisition tiers to run.

    `--no-download` removes the two tiers that write a file, which is the difference
    between "query an API for open-access text" and "fetch a document onto this disk".
    """
    if value == "none":
        return ()
    tiers = ("api", "pdf", "cli") if value == "all" else (value,)
    if no_download:
        tiers = tuple(tier for tier in tiers if tier == "api")
    return tiers


def _evidence_policy(value: str) -> tuple:
    """Parse --require-evidence into (policy, share)."""
    text = (value or "strict").strip().lower()
    if text in ("strict", "all", "1", "1.0"):
        return "strict", 1.0
    try:
        share = float(text)
    except ValueError:
        raise _common.InputError(
            "--require-evidence must be 'strict' or a share between 0 and 1 (got %r)" % value
        )
    if not 0.0 < share <= 1.0:
        raise _common.InputError("--require-evidence share must be greater than 0 and at most 1")
    return "share", share


def _styles(value: str) -> tuple:
    if value == "all":
        return ("numeric", "author-year", "ledger")
    return (value,)


def _advisory_grades(value: str, verdict_list=None) -> dict:
    """Load advisory grades. ``off`` means the channel is absent, never empty-but-on."""
    if not value or value == "off":
        return {}
    return verdicts.load_advisory(value)


def build_all(arguments):
    """Read the document, build the bundle, classify. Returns the working set."""
    document = _intake.read_document(arguments.document)
    if arguments.style != "all":
        document.sentences = _intake._sentences.split_sentences(
            document.text, styles=_styles(arguments.style)
        )
    tiers = _acquire_policy(arguments.acquire, arguments.no_download)
    # With --offline nothing is attempted, and the tier list is emptied rather than
    # merely ignored, so the bundle cannot report a misleading skip message.
    offline = arguments.offline
    cache_dir = arguments.cache_dir or (Path(arguments.out_dir) / "sources")
    bundle = _bundle.build_bundle(
        document=document,
        bib_path=arguments.bib,
        pdf_dir=arguments.pdf_dir,
        ledger_path=arguments.sources,
        claims_path=arguments.claims,
        doi_path=arguments.dois,
        offline=offline,
        mailto=arguments.mailto,
        acquire=() if offline else tiers,
        cache_dir=None if offline else cache_dir,
    )
    if offline and arguments.acquire != "all":
        bundle.warnings.append(
            "--offline was given, so --acquire %s was not attempted; no network call was made"
            % arguments.acquire
        )
    if not offline and not tiers:
        bundle.warnings.append(
            "acquisition is disabled, so only supplied files and ledger evidence were used"
        )
    indexes = _evidence.build_indexes(bundle)
    advisory = _advisory_grades(arguments.advisory)
    recorded = getattr(arguments, "verdicts", None)
    if recorded and arguments.mode in ("report", "audit"):
        # Render from the recorded file instead of re-classifying. This is the documented
        # reproducibility path: a reviewer corrects a verdict by hand, re-renders, and the
        # classifier does not run. It was accepted and silently ignored before, which made
        # a hand-correction look applied while the artifact showed the machine's answer.
        graded = verdicts.from_dict(_common.read_json(recorded))
        if arguments.limit:
            graded = graded[: arguments.limit]
        mismatched = sum(
            1 for verdict in graded if document.text[verdict.char_start:verdict.char_end] != verdict.text
        )
        if mismatched:
            bundle.warnings.append(
                "%d recorded verdict(s) no longer locate their sentence in this document; "
                "the report was still rendered from the file, but re-run `verify` to see which"
                % mismatched
            )
        bundle.warnings.append(
            "rendered from the recorded verdicts file %s: the classifier was NOT run, so the "
            "findings are exactly what that file says" % recorded
        )
    else:
        graded = verdicts.classify(document, bundle, indexes, advisory=advisory)
        if arguments.limit:
            graded = graded[: arguments.limit]
    summary = coverage.compute(graded, bundle)
    return document, bundle, graded, summary


def _errors_and_warnings(graded) -> tuple:
    errors = [verdict for verdict in graded if verdict.severity == "error"]
    warnings = [verdict for verdict in graded if verdict.severity == "warning"]
    return errors, warnings


def _verdict_payload(document, bundle, graded, summary, meta, evidence=None) -> dict:
    errors, warnings = _errors_and_warnings(graded)
    result = evidence or {}
    status = result.get("status") if result.get("blocking") else ("fail" if errors else "pass")
    return {
        "schema": SCHEMA,
        "generated": meta["generated"],
        "status": status,
        "document": document.to_dict(),
        "bundle": bundle.to_dict(),
        "coverage": summary,
        "evidence": {key: value for key, value in result.items() if key != "worklist"},
        # The intake basis is part of the record: a reader of verdicts.json must be able
        # to see whether the tool was in a position to make these findings, not only what
        # the sources contained.
        "preconditions": list(meta.get("preconditions", []) or []),
        "gate": {
            "status": "fail" if errors else "pass",
            "errors": len(errors),
            "warnings": len(warnings),
        },
        "verdicts": [verdict.to_dict() for verdict in graded],
    }


def _combine_status(evidence: dict, intake: dict) -> str | None:
    """The more severe of the two input conditions, or None when there is neither.

    `insufficient_input` outranks `insufficient_evidence`: if the tool could not
    understand the document, what it found in the sources is beside the point.
    """
    if intake.get("blocking"):
        return intake["status"]
    if evidence.get("blocking"):
        return evidence["status"]
    return None


def _input_banner(evidence: dict, intake: dict) -> str:
    if intake.get("blocking"):
        return preconditions.banner(list(intake.get("records", [])))
    return sufficiency.banner(evidence)


def _meta(document, bundle, summary, graded, sufficiency_result=None, intake_result=None) -> dict:
    errors, _ = _errors_and_warnings(graded)
    result = sufficiency_result or {}
    intake = intake_result or {}
    gate_status = "fail" if errors else "pass"
    input_bound = bool(result.get("blocking")) or bool(intake.get("blocking"))
    reasons = list(intake.get("reason", []) or []) + list(result.get("reason", []) or [])
    return {
        "title": document.title or "Citation report",
        "document_path": document.path,
        "generated": datetime.date.today().isoformat(),
        "gate_status": gate_status,
        "warnings": list(bundle.warnings) + list(document.warnings),
        "advisory_enabled": any(verdict.advisory for verdict in graded),
        "coverage": summary,
        # The input side, carried into every artifact so a reader cannot see the
        # findings without also seeing whether the tool was in a position to make them.
        "input_bound": input_bound,
        "input_bound_reason": " ".join(reasons),
        "input_bound_banner": _input_banner(result, intake),
        "coverage_caveat": sufficiency.coverage_caveat(result),
        "preconditions": list(intake.get("records", []) or []),
        "evidence": {
            "policy": result.get("policy"),
            "citing_sources": result.get("citing_sources"),
            "citing_sources_checkable": result.get("citing_sources_checkable"),
            "unverifiable_sentences": result.get("unverifiable_sentences"),
            "undecided_sentences": result.get("undecided_sentences"),
            "detail": result.get("detail"),
            "preconditions_failed": list(intake.get("failed", []) or []),
        },
    }


def _issue_from_verdict(verdict) -> _common.Issue:
    detail = verdict.note[:220] if verdict.note else None
    return _common.issue(
        verdict.severity,
        verdict.rule_id,
        location="%s:%d" % (verdict.sentence_id, verdict.char_start),
        item_id=verdict.sentence_id,
        detail=detail,
    )


def render_formats(formats: list, out_dir: Path, layout, summary, bundle, meta, graded) -> tuple:
    """Render each requested format. Returns (artifacts, issues)."""
    issues: list = []
    artifacts: dict = {}
    for name in formats:
        if name in ("table", "json"):
            continue
        try:
            if name == "pdf":
                import _pdfrender

                payload, report = _pdfrender.render(layout, summary, bundle, meta)
                target = out_dir / "report.pdf"
            elif name == "docx":
                import _docxout

                payload, report = _docxout.render(layout, summary, bundle, meta)
                target = out_dir / "report.docx"
            else:
                import _htmlout

                payload, report = _htmlout.render(layout, summary, bundle, meta)
                target = out_dir / "report.html"
        except ImportError as exc:
            issues.append(
                _common.issue(
                    "error",
                    "RENDERER_UNAVAILABLE",
                    item_id=name,
                    detail="renderer module is missing: %s" % exc,
                )
            )
            continue
        except Exception as exc:  # noqa: BLE001 - a renderer failure must be reported, not swallowed
            issues.append(
                _common.issue(
                    "error",
                    "RENDER_FAILED",
                    item_id=name,
                    detail="%s: %s" % (type(exc).__name__, str(exc)[:200]),
                )
            )
            continue
        _common.write_bytes(target, payload)
        artifacts[name] = {"path": str(target), **report}
        expected_notes = len(graded)
        if report.get("segments") != expected_notes:
            issues.append(
                _common.issue(
                    "error",
                    "SEGMENT_COUNT_MISMATCH",
                    item_id=name,
                    detail="renderer saw %s segments, %d verdicts were supplied"
                    % (report.get("segments"), expected_notes),
                )
            )
    return artifacts, issues


def cmd_report(arguments) -> int:
    document, bundle, graded, summary = build_all(arguments)
    policy, share = _evidence_policy(arguments.require_evidence)
    evidence = sufficiency.evaluate(graded, summary, bundle, policy=policy, share=share)
    intake = preconditions.summarise(preconditions.evaluate(document, bundle, graded))
    intake["records"] = preconditions.evaluate(document, bundle, graded)
    # The caveat travels inside the summary so every renderer prints the same sentence
    # beside the same coverage figure, with no per-renderer wording to drift apart.
    caveat = sufficiency.coverage_caveat(evidence)
    if caveat:
        summary = dict(summary)
        summary["coverage_caveat"] = caveat
    meta = _meta(document, bundle, summary, graded, evidence, intake)
    out_dir = Path(arguments.out_dir)
    layout = _highlight.build_layout(document, graded)
    formats = [piece.strip().lower() for piece in arguments.format.split(",") if piece.strip()]
    unknown = [piece for piece in formats if piece not in FORMATS]
    if unknown:
        raise _common.InputError("unknown format(s): " + ", ".join(unknown))

    artifacts, issues = render_formats(formats, out_dir, layout, summary, bundle, meta, graded)

    _common.write_json(
        out_dir / "verdicts.json",
        _verdict_payload(document, bundle, graded, summary, meta, evidence),
    )
    _common.write_json(out_dir / "coverage.json", summary)
    bundle.write_csv(out_dir / "sources_report.csv")
    sufficiency.write_worklist(out_dir / "evidence_worklist.csv", evidence["worklist"])

    if "table" in formats:
        _common.write_text_lf(out_dir / "findings.md", findings_table(graded, summary))

    for verdict in graded:
        if verdict.severity in ("error", "warning"):
            issues.append(_issue_from_verdict(verdict))

    # The input condition is reported as its own issue, at a severity that matches the
    # policy: an error when it blocks, an informational note when overridden. It is
    # never omitted, because "we could not check this" must always be visible.
    if evidence["blocking"]:
        issues.append(
            _common.issue(
                "error" if not arguments.allow_insufficient else "warning",
                evidence["status"].upper(),
                item_id="evidence",
                detail=" ".join(intake["reason"] + evidence["reason"])[:400],
            )
        )
    if arguments.allow_insufficient and evidence["blocking"]:
        override_note = (
            "insufficient evidence was overridden by --allow-insufficient; the status "
            "remains %s and the findings are provisional" % evidence["status"]
        )
        meta["warnings"] = list(meta.get("warnings", [])) + [override_note]

    combined_status = _combine_status(evidence, intake)
    status_override = combined_status
    payload = _common.emit_report(
        "citation-report",
        issues,
        summary={
            "sentences": summary["sentences_total"],
            "requiring_citation": summary["sentences_requiring_citation"],
            "coverage_percent": summary["citation_coverage"]["percent"],
            "coverage": "%d/%d"
            % (
                summary["citation_coverage"]["numerator"],
                summary["citation_coverage"]["denominator"],
            ),
            "states": summary["states"],
            "citing_sources": evidence["citing_sources"],
            "citing_sources_checkable": evidence["citing_sources_checkable"],
            "evidence_gaps": len(evidence["worklist"]),
            "artifacts": {name: item["path"] for name, item in artifacts.items()},
        },
        extra={
            "artifacts": artifacts,
            "evidence": {
                key: value for key, value in evidence.items() if key != "worklist"
            },
            "worklist_rows": len(evidence["worklist"]),
            "worklist": str(out_dir / "evidence_worklist.csv"),
        },
        status_override=status_override,
        # With --allow-insufficient the status still names the condition, but the exit
        # code reflects the caller's decision to continue: findings decide it, not the
        # input gap. Without the flag, the input gap decides the exit code.
        exit_override=(
            (1 if any(item.severity == "error" for item in issues) else 0)
            if (arguments.allow_insufficient and combined_status)
            else None
        ),
    )
    if arguments.check:
        import report_gate

        return max(payload, report_gate.check_directory(out_dir, document=document, bundle=bundle))
    return payload


def cmd_worklist(arguments) -> int:
    """Re-check a worklist: how many previously missing sources can now be read.

    Exits non-zero while any gap remains, so this doubles as a completeness check in
    CI: a worklist that is never closed is the same silent limitation one step later.
    """
    document, bundle, graded, summary = build_all(arguments)
    report = sufficiency.recheck_worklist(arguments.worklist, bundle)
    issues: list = []
    for row in report.get("remaining_rows") or []:
        issues.append(
            _common.issue(
                "error",
                "EVIDENCE_GAP_OPEN",
                item_id=str(row.get("source_id")),
                detail="%s. %s" % (row.get("reason"), row.get("suggested_action") or ""),
            )
        )
    if report["checked"] == 0:
        issues.append(
            _common.issue(
                "warning",
                "WORKLIST_EMPTY",
                detail="the worklist file has no rows, so there is nothing to re-check",
            )
        )
    elif report["remaining"] == 0:
        issues.append(
            _common.issue(
                "info",
                "EVIDENCE_GAPS_CLOSED",
                detail="every source on the worklist now has readable evidence",
            )
        )
    return _common.emit_report(
        "citation-report/worklist",
        issues,
        summary={
            "checked": report["checked"],
            "closed": report["closed"],
            "remaining": report["remaining"],
            "closed_keys": report.get("closed_keys", []),
            "remaining_keys": report.get("remaining_keys", []),
        },
    )


def cmd_sources(arguments) -> int:
    document = _intake.read_document(arguments.document)
    tiers = _acquire_policy(arguments.acquire, arguments.no_download)
    # With --offline nothing is attempted, and the tier list is emptied rather than
    # merely ignored, so the bundle cannot report a misleading skip message.
    offline = arguments.offline
    cache_dir = arguments.cache_dir or (Path(arguments.out_dir) / "sources")
    bundle = _bundle.build_bundle(
        document=document,
        bib_path=arguments.bib,
        pdf_dir=arguments.pdf_dir,
        ledger_path=arguments.sources,
        claims_path=arguments.claims,
        doi_path=arguments.dois,
        offline=offline,
        mailto=arguments.mailto,
        acquire=() if offline else tiers,
        cache_dir=None if offline else cache_dir,
    )
    if offline and arguments.acquire != "all":
        bundle.warnings.append(
            "--offline was given, so --acquire %s was not attempted; no network call was made"
            % arguments.acquire
        )
    if not offline and not tiers:
        bundle.warnings.append(
            "acquisition is disabled, so only supplied files and ledger evidence were used"
        )
    out_dir = Path(arguments.out_dir)
    bundle.write_csv(out_dir / "sources_report.csv")
    # This is the mode a user runs *to fix* the gaps, so it reports the worklist and
    # never blocks: a blocker here would be circular.
    indexes = _evidence.build_indexes(bundle)
    policy, share = _evidence_policy(arguments.require_evidence)
    graded = verdicts.classify(document, bundle, indexes)
    if arguments.limit:
        graded = graded[: arguments.limit]
    summary = coverage.compute(graded, bundle)
    evidence = sufficiency.evaluate(graded, summary, bundle, policy=policy, share=share)
    sufficiency.write_worklist(out_dir / "evidence_worklist.csv", evidence["worklist"])
    issues: list = []
    for source in bundle.sources:
        if source.retraction_status == "retracted":
            issues.append(
                _common.issue(
                    "error",
                    "SOURCE_RETRACTED",
                    item_id=source.source_id,
                    detail="%s (%s)" % (source.title or source.title_claimed, source.doi),
                )
            )
        elif source.evidence_availability in ("metadata_only", "unavailable"):
            issues.append(
                _common.issue(
                    "info",
                    "SOURCE_NO_EVIDENCE",
                    item_id=source.source_id,
                    detail="evidence availability is %s; sentences citing it cannot be graded"
                    % source.evidence_availability,
                )
            )
        for warning in source.warnings:
            issues.append(
                _common.issue("warning", "SOURCE_WARNING", item_id=source.source_id, detail=warning)
            )
    return _common.emit_report(
        "citation-report/sources",
        issues,
        summary={
            "sources": len(bundle.sources),
            "with_evidence": sum(
                1 for source in bundle.sources if source.evidence_availability in ("full_text", "abstract")
            ),
            "evidence": bundle.counts_by_evidence(),
            "retraction": bundle.counts_by_retraction(),
            "reference_entries": len(bundle.reference_entries),
            "claims": len(bundle.claims),
            "csv": str(out_dir / "sources_report.csv"),
            "citing_sources": evidence["citing_sources"],
            "citing_sources_checkable": evidence["citing_sources_checkable"],
            "evidence_gaps": len(evidence["worklist"]),
            "worklist": str(out_dir / "evidence_worklist.csv"),
            "blocking": False,
            "blocking_note": "sources mode never blocks: it is the mode you run to fix "
            "the gaps",
        },
        extra={"sources": [source.to_dict() for source in bundle.sources]},
    )


def cmd_verify(arguments) -> int:
    """Re-validate a recorded verdicts.json. Never re-classifies."""
    if not arguments.verdicts:
        raise _common.InputError("verify mode needs --verdicts <verdicts.json>")
    record = _common.read_json(arguments.verdicts)
    graded = verdicts.from_dict(record)
    document = _intake.read_document(arguments.document)
    issues: list = []

    # Every span must still locate its own sentence in the document.
    for verdict in graded:
        if verdict.char_end > len(document.text):
            issues.append(
                _common.issue(
                    "error",
                    "SPAN_BEYOND_DOCUMENT",
                    item_id=verdict.sentence_id,
                    detail="span %d-%d exceeds document length %d"
                    % (verdict.char_start, verdict.char_end, len(document.text)),
                )
            )
            continue
        located = document.text[verdict.char_start : verdict.char_end]
        if located != verdict.text:
            issues.append(
                _common.issue(
                    "error",
                    "SPAN_NOT_RELOCATABLE",
                    item_id=verdict.sentence_id,
                    detail="document text at that offset is %r" % located[:80],
                )
            )

    # Recompute coverage from the verdict list and require it to match the file.
    recorded = record.get("coverage")
    if isinstance(recorded, dict):
        rebuilt = coverage.compute(graded, type("B", (), {"sources": [], "counts_by_evidence": lambda s: {}, "counts_by_retraction": lambda s: {}, "claims": {}})())
        for key in ("sentences_total", "sentences_requiring_citation"):
            if recorded.get(key) != rebuilt.get(key):
                issues.append(
                    _common.issue(
                        "error",
                        "COVERAGE_MISMATCH",
                        item_id=key,
                        detail="recorded %s, recomputed %s" % (recorded.get(key), rebuilt.get(key)),
                    )
                )
        if recorded.get("states") != rebuilt.get("states"):
            issues.append(
                _common.issue(
                    "error",
                    "COVERAGE_STATE_MISMATCH",
                    detail="recorded states %s, recomputed %s"
                    % (recorded.get("states"), rebuilt.get("states")),
                )
            )

    errors, warnings = _errors_and_warnings(graded)
    issues.append(
        _common.issue(
            "info",
            "GATE_STATUS",
            detail="%d sentence(s) at error severity, %d at warning severity"
            % (len(errors), len(warnings)),
        )
    )
    return _common.emit_report(
        "citation-report/verify",
        issues,
        summary={
            "verdicts": len(graded),
            "errors": len(errors),
            "warnings": len(warnings),
            "gate_status": "fail" if errors else "pass",
        },
    )


def cmd_audit(arguments) -> int:
    document, bundle, graded, summary = build_all(arguments)
    policy, share = _evidence_policy(arguments.require_evidence)
    evidence = sufficiency.evaluate(graded, summary, bundle, policy=policy, share=share)
    intake_records = preconditions.evaluate(document, bundle, graded)
    intake = preconditions.summarise(intake_records)
    combined_status = _combine_status(evidence, intake)
    issues = []
    # The input condition is reported here too, not only in `report` mode. `audit` is
    # the mode a CI job and an agent call, so leaving the sufficiency policy out of it
    # would let the honest blocker be bypassed by choosing a different mode.
    for verdict in graded:
        if verdict.severity in ("error", "warning"):
            issues.append(_issue_from_verdict(verdict))
    if combined_status:
        issues.append(
            _common.issue(
                "error" if not arguments.allow_insufficient else "warning",
                combined_status.upper(),
                item_id="evidence",
                detail=" ".join(intake["reason"] + evidence["reason"])[:400],
            )
        )
    # Machine-readable envelope only on stdout: a human-readable block printed beside it
    # would make the output unparseable, and gate.py parses these envelopes.
    return _common.emit_report(
        "citation-report/audit",
        issues,
        summary={
            "sentences": summary["sentences_total"],
            "coverage_percent": summary["citation_coverage"]["percent"],
            "coverage": "%d/%d"
            % (
                summary["citation_coverage"]["numerator"],
                summary["citation_coverage"]["denominator"],
            ),
            "states": summary["states"],
            "citing_sources": evidence["citing_sources"],
            "citing_sources_checkable": evidence["citing_sources_checkable"],
            "evidence_gaps": len(evidence["worklist"]),
        },
        extra={
            "coverage": summary,
            "preconditions": intake_records,
            "evidence": {key: value for key, value in evidence.items() if key != "worklist"},
            "worklist": evidence["worklist"],
            "text_summary": coverage.render_text(summary),
        },
        status_override=combined_status,
        exit_override=(
            (1 if any(item.severity == "error" for item in issues) else 0)
            if (arguments.allow_insufficient and combined_status)
            else None
        ),
    )


def findings_table(graded, summary) -> str:
    """A Markdown findings table, one row per non-passing sentence."""
    lines = [
        "# Citation report findings",
        "",
        coverage.render_text(summary),
        "",
        "| # | Sentence | Rule | State | Severity | Finding |",
        "|---|---|---|---|---|---|",
    ]
    index = 0
    for verdict in graded:
        if verdict.severity == "info":
            continue
        index += 1
        text = verdict.text.replace("|", "\\|")
        if len(text) > 160:
            text = text[:157] + "..."
        note = (verdict.note or "").replace("|", "\\|").replace("\n", " ")
        lines.append(
            "| %d | %s | %s | %s | %s | %s |"
            % (index, text, verdict.rule_id, verdict.state, verdict.severity, note)
        )
    if index == 0:
        lines.append("| - | (no findings) | - | - | - | - |")
    return "\n".join(lines) + "\n"


COMMANDS = {
    "report": cmd_report,
    "sources": cmd_sources,
    "verify": cmd_verify,
    "audit": cmd_audit,
    "worklist": cmd_worklist,
}


def _unreadable_document(exc: Exception) -> int:
    """Report a document that could not be read at all as an input condition.

    ``insufficient_input`` (exit 4) is the status this skill promises for "the document
    itself could not be read well enough to make findings". Reporting it as an
    ``INVALID_INPUT`` error (exit 1) put a statement about our inputs in the finding
    channel, where a reader would take it for a result about the document.
    """
    return _common.emit_report(
        "citation-report",
        [
            _common.issue(
                "error",
                "INSUFFICIENT_INPUT",
                location="intake",
                detail=str(exc)[:400],
            )
        ],
        status_override="insufficient_input",
    )


def main() -> int:
    arguments = build_parser().parse_args()

    def run_mode() -> int:
        try:
            return COMMANDS[arguments.mode](arguments)
        except _intake.UnreadableDocument as exc:
            return _unreadable_document(exc)

    return _common.main_guard("citation-report", run_mode)


if __name__ == "__main__":
    sys.exit(main())
