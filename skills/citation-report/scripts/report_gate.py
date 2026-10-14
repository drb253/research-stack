"""Gate and artifact verification.

A gate that cannot fail is not a gate, and a report nobody re-reads is not evidence.
This module does two things:

1. **Re-validates the recorded verdicts.** Every span must still locate its own
   sentence in the document; the coverage arithmetic is recomputed from the verdict
   list and must match the recorded summary; rule/state/severity pairings must obey
   the rule table. Any disagreement is an error.
2. **Re-opens the artifacts and counts what is actually in them.** Not what the
   renderer said it wrote — what is in the bytes. For the PDF this matters most:
   the whole design choice is that notes are *printed* rather than attached as
   annotations, so the check extracts the PDF's text layer and requires the note
   bodies to be findable there. If a renderer regressed to annotations, this fails.

The document is verified against itself, so the gate needs no network and no model.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import zipfile
import zlib
from pathlib import Path
from xml.etree import ElementTree

import _common
import coverage
import verdicts

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
ARTIFACT_NAMES = {"pdf": "report.pdf", "docx": "report.docx", "html": "report.html"}
MAX_REPORTED_ERRORS = 40
#: The repository tools directory, four levels above this file:
#: ``<repo>/skills/citation-report/scripts/report_gate.py``.
TOOLS_DIR = Path(__file__).resolve().parents[3] / "tools"


# --------------------------------------------------------------------------- #
# The honesty step
# --------------------------------------------------------------------------- #


def load_honesty_scanner():
    """Return ``tools/claim_guard.py``'s ``scan()``, or None when that file is absent.

    The honesty gate is repository furniture, not skill furniture. A skill installed
    on its own does not carry ``tools/``, so the gate reports the missing check
    instead of pretending that the check ran.
    """
    module_path = TOOLS_DIR / "claim_guard.py"
    if not module_path.is_file():
        return None
    if str(TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(TOOLS_DIR))
    import claim_guard

    return claim_guard.scan


def honesty_findings(text, scanner=None, where="report prose"):
    """Findings for one piece of report prose. ``None`` means the scanner is absent."""
    if scanner is None:
        scanner = load_honesty_scanner()
    if scanner is None:
        return None
    return scanner(text, where=where)


def report_prose(graded, record=None) -> str:
    """Every claim the report itself prints, joined into one document.

    ``claim_guard`` decides a clean result at document level, so a bound anywhere in
    the report bounds a clean statement elsewhere in it. Joining the notes keeps that
    semantics and stops the gate firing on a note that a reader would bound.

    The recorded attribution block is part of this prose. Without it the block's own
    use of the defined term would look like the bare universal negative to
    ``claim_guard``, and the gate would refuse the report the tool just wrote.
    """
    import _attribution
    import _highlight

    parts = [_highlight.note_text(verdict) for verdict in graded]
    document = (record or {}).get("document")
    if isinstance(document, dict) and document.get("transcribed"):
        parts.append("the document text was transcribed by %s" % document.get("transcription", "ocr"))
    block = _attribution.markdown_from_record((record or {}).get("attribution"))
    if block:
        parts.append(block)
    return "\n".join(parts)


def check_honesty(graded, record=None, scanner=None, out_dir=None) -> list:
    """The gate's honesty step: no universal negative may ship in a generated report.

    A report that says "plagiarism-free" claims something no bounded check can
    establish, and a clean result must name what it was checked against.
    ``tools/claim_guard.py`` owns that rule, so the gate calls it rather than
    re-implementing the rule and letting the two drift apart.

    The artifacts are scanned as well as the recorded prose, each as its own document:
    a term that the definition does not bound, added to an artifact by hand, then has
    nothing to exempt it.
    """
    if scanner is None:
        scanner = load_honesty_scanner()
    if scanner is None:
        return [
            _common.issue(
                "warning",
                "HONESTY_CHECK_UNAVAILABLE",
                detail="tools/claim_guard.py is not installed beside the skill, so the "
                "report's own claims were not scanned for a universal negative",
            )
        ]
    corpora = [("the report's own notes", report_prose(graded, record))]
    html = Path(out_dir) / "report.html" if out_dir else None
    if html is not None and html.is_file():
        corpora.append((str(html), html.read_text(encoding="utf-8", errors="replace")))
    issues: list = []
    for where, text in corpora:
        for finding in honesty_findings(text, scanner, where) or []:
            code = "HONESTY_UNBOUNDED" if finding["kind"] == "UNBOUNDED" else "HONESTY_CLAIM"
            issues.append(
                _common.issue(
                    "error",
                    code,
                    item_id=finding["kind"],
                    detail="%s: %s" % (where, finding["message"]),
                )
            )
    return issues


def check_attribution(graded, record, out_dir=None, rebuilt=None) -> list:
    """Recompute the defined claim, and check the artifact carries it.

    The gate recomputes the facts from the recorded verdicts, calls the shared
    definition, and compares. A hand-edited ``attribution`` object then cannot claim a
    statement that the run's own numbers do not support.

    The HTML artifact must carry the definition's three anchors. The claim a reader
    sees is the claim that has to be bounded, so a report that prints the term without
    the definition, the scope and the exception is an error even if the recorded file
    looks well formed.
    """
    import _attribution

    module = _attribution.load_module()
    if module is None:
        return [
            _common.issue(
                "warning",
                "ATTRIBUTION_DEFINITION_UNAVAILABLE",
                detail="tools/attribution.py is not installed beside the skill, so the "
                "recorded claim could not be recomputed",
            )
        ]
    if rebuilt is None:
        rebuilt = _attribution.build(record.get("coverage") or {}, graded)
    if not rebuilt.get("available"):
        return [
            _common.issue(
                "warning",
                "ATTRIBUTION_DEFINITION_UNAVAILABLE",
                detail=str(rebuilt.get("reason") or "the definition could not be loaded"),
            )
        ]
    result = rebuilt["result"]
    stored = record.get("attribution") or {}
    issues: list = []
    if stored and not stored.get("available", False):
        issues.append(
            _common.issue(
                "error",
                "ATTRIBUTION_MISMATCH",
                item_id="available",
                detail="the record says the definition was unavailable, but it is installed "
                "and the run's facts can be evaluated",
            )
        )
    elif stored:
        for key in ("issuable", "statement", "scope"):
            if stored.get(key) != result.get(key):
                issues.append(
                    _common.issue(
                        "error",
                        "ATTRIBUTION_MISMATCH",
                        item_id=key,
                        detail="recorded %r, recomputed %r" % (stored.get(key), result.get(key)),
                    )
                )
        if sorted(stored.get("blockers") or []) != sorted(result.get("blockers") or []):
            issues.append(
                _common.issue(
                    "error",
                    "ATTRIBUTION_MISMATCH",
                    item_id="blockers",
                    detail="recorded %r, recomputed %r"
                    % (stored.get("blockers"), result.get("blockers")),
                )
            )
    html = Path(out_dir) / "report.html" if out_dir else None
    if html is not None and html.is_file():
        text = html.read_text(encoding="utf-8", errors="replace")
        # The block is required when the record carries one, and whenever the artifact
        # uses the term. A report that never makes the claim needs no block: the rule is
        # that the term must not appear without its definition, not that every artifact
        # must print the definition.
        if stored.get("available") or "plagiarism-free" in text.lower():
            missing = [anchor for anchor in _attribution.anchors(module) if anchor not in text]
            if missing:
                issues.append(
                    _common.issue(
                        "error",
                        "ATTRIBUTION_BLOCK_MISSING",
                        item_id="html",
                        detail="report.html does not carry the whole definition; missing: %s"
                        % "; ".join(missing),
                    )
                )
    return issues


def _empty_bundle_stub():
    """A stand-in for coverage.compute, which only reads source counts."""

    class _Stub:
        sources: list = []
        claims: dict = {}

        @staticmethod
        def counts_by_evidence() -> dict:
            return {}

        @staticmethod
        def counts_by_retraction() -> dict:
            return {}

    return _Stub()


# --------------------------------------------------------------------------- #
# Artifact verification
# --------------------------------------------------------------------------- #


def verify_html(path: Path, expected_highlights: int, expected_notes: int) -> tuple:
    text = path.read_text(encoding="utf-8", errors="replace")
    highlights = text.count('class="v v-')
    notes = len(re.findall(r'<span class="v v-[a-z_]+"[^>]*title="', text))
    details: list = []
    ok = True
    if highlights != expected_highlights:
        ok = False
        details.append("coloured spans %d != expected %d" % (highlights, expected_highlights))
    if notes != expected_notes:
        ok = False
        details.append("hover notes %d != expected %d" % (notes, expected_notes))
    if "<script" in text.lower():
        ok = False
        details.append("output contains a script element; the report must be static")
    return ok, "; ".join(details) or "html spans and notes match", {
        "highlights": highlights,
        "notes": notes,
    }


def verify_docx(path: Path, expected_highlights: int, expected_notes: int) -> tuple:
    ok = True
    details: list = []
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            # OPC places the relationships for `word/document.xml` at
            # `word/_rels/document.xml.rels` — not `word/document.xml.rels`, which is
            # the shape a naive writer produces and which Word silently ignores.
            required = {
                "[Content_Types].xml",
                "_rels/.rels",
                "word/document.xml",
                "word/_rels/document.xml.rels",
                "word/styles.xml",
                "word/comments.xml",
            }
            missing = required - names
            if missing:
                ok = False
                details.append("missing parts: " + ", ".join(sorted(missing)))
            document = ElementTree.fromstring(archive.read("word/document.xml"))
            comments = (
                ElementTree.fromstring(archive.read("word/comments.xml"))
                if "word/comments.xml" in names
                else ElementTree.fromstring("<w:comments xmlns:w='%s'/>" % W[1:-1])
            )
            if "word/_rels/document.xml.rels" in names:
                relationships = archive.read("word/_rels/document.xml.rels").decode(
                    "utf-8", "replace"
                )
                if "comments.xml" not in relationships:
                    ok = False
                    details.append(
                        "document relationships do not reference comments.xml, so Word "
                        "will not load the comments"
                    )
    except (zipfile.BadZipFile, ElementTree.ParseError) as exc:
        return False, "docx is unreadable: %s" % type(exc).__name__, {}

    # Run-level shading only: a coverage bar or a legend swatch shades a table cell
    # (`w:tcPr/w:shd`) and must not be counted as a highlighted sentence.
    highlights = 0
    for properties in document.iter(W + "rPr"):
        for child in properties:
            if child.tag == W + "shd" and child.get(W + "fill"):
                highlights += 1
    comment_ids = {element.get(W + "id") for element in comments.iter(W + "comment")}
    starts = [element.get(W + "id") for element in document.iter(W + "commentRangeStart")]
    ends = [element.get(W + "id") for element in document.iter(W + "commentRangeEnd")]
    references = [element.get(W + "id") for element in document.iter(W + "commentReference")]

    if highlights != expected_highlights:
        ok = False
        details.append("shaded runs %d != expected %d" % (highlights, expected_highlights))
    if len(comment_ids) != expected_notes:
        ok = False
        details.append("comments %d != expected %d" % (len(comment_ids), expected_notes))
    if sorted(starts) != sorted(comment_ids):
        ok = False
        details.append("comment range starts do not match the comment ids")
    if sorted(ends) != sorted(comment_ids):
        ok = False
        details.append("comment range ends do not match the comment ids")
    if sorted(references) != sorted(comment_ids):
        ok = False
        details.append("comment references do not match the comment ids")
    return ok, "; ".join(details) or "docx shading and comments match", {
        "highlights": highlights,
        "notes": len(comment_ids),
    }


def _pdf_streams(payload: bytes) -> str:
    """Decompress every content stream so fill operations can be counted."""
    pieces: list = []
    for match in re.finditer(rb"stream\r?\n", payload):
        start = match.end()
        end = payload.find(b"endstream", start)
        if end < 0:
            continue
        chunk = payload[start:end].rstrip(b"\r\n")
        try:
            pieces.append(zlib.decompress(chunk).decode("latin-1"))
        except zlib.error:
            pieces.append(chunk.decode("latin-1", "replace"))
    return "\n".join(pieces)


def verify_pdf(path: Path, expected_highlights: int, expected_notes: int, sample_notes: list) -> tuple:
    payload = path.read_bytes()
    ok = True
    details: list = []

    if not payload.startswith(b"%PDF-"):
        return False, "file does not start with a PDF header", {}

    # Structural validity: the startxref offset must point at the xref table.
    tail = payload[-2048:]
    match = re.search(rb"startxref\s+(\d+)", tail)
    if not match:
        ok = False
        details.append("no startxref offset")
    else:
        offset = int(match.group(1))
        if payload[offset : offset + 4] != b"xref":
            ok = False
            details.append("startxref does not point at an xref table")
    if not payload.rstrip().endswith(b"%%EOF"):
        ok = False
        details.append("file does not end with %%EOF")

    content = _pdf_streams(payload)
    fills = len(re.findall(r"\bre\s+f\b", content)) + len(re.findall(r"\bre\s+f\s", content))
    if fills < expected_highlights:
        ok = False
        details.append(
            "only %d filled rectangles in the content streams, fewer than the %d "
            "sentences to highlight" % (fills, expected_highlights)
        )

    # The design decision under test: notes are PRINTED, not attached. Find them in
    # the text layer. Without pdftotext this check cannot run, and that is reported
    # rather than passed silently.
    extracted = ""
    extraction = "unavailable"
    if shutil.which("pdftotext"):
        try:
            completed = subprocess.run(
                ["pdftotext", "-layout", str(path), "-"],
                capture_output=True,
                timeout=180,
                check=False,
            )
            if completed.returncode == 0:
                extracted = completed.stdout.decode("utf-8", "replace")
                extraction = "pdftotext"
        except (OSError, subprocess.SubprocessError):
            extraction = "failed"
    if extracted:
        normalized = " ".join(extracted.split())
        found = 0
        for note in sample_notes:
            probe = " ".join(str(note).split())[:60]
            if probe and probe in normalized:
                found += 1
        if sample_notes and found == 0:
            ok = False
            details.append(
                "no sampled margin note could be found in the PDF text layer; notes "
                "may have regressed to annotations"
            )
        else:
            details.append("printed notes found in the text layer: %d/%d sampled" % (found, len(sample_notes)))
    else:
        details.append("pdf text layer not checked (pdftotext %s)" % extraction)
    return ok, "; ".join(details) or "pdf structure and highlights verified", {
        "fills": fills,
        "extraction": extraction,
    }


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #


def _note_samples(graded, limit: int = 5) -> list:
    import _highlight

    samples: list = []
    for verdict in graded:
        if verdict.severity == "info" and not verdict.sources:
            continue
        body = _highlight.note_text(verdict)
        for line in body.split("\n"):
            stripped = line.strip().strip('"')
            if len(stripped) >= 30:
                samples.append(stripped)
                break
        if len(samples) >= limit:
            break
    return samples


def check_directory(out_dir, *, document=None, bundle=None) -> int:
    """Verify a rendered report directory. Returns an exit code."""
    out_dir = Path(out_dir)
    issues: list = []
    expected_highlights = 0
    expected_notes = 0
    artifact_reports: dict = {}

    verdicts_path = out_dir / "verdicts.json"
    if not verdicts_path.is_file():
        return _common.emit_report(
            "citation-report/gate",
            [_common.issue("error", "VERDICTS_MISSING", detail=str(verdicts_path))],
        )
    record = _common.read_json(verdicts_path)
    graded = verdicts.from_dict(record)
    expected_highlights = len(graded)
    expected_notes = len(graded)

    # 1. Spans must still locate their own sentences.
    if document is not None:
        for verdict in graded:
            if verdict.char_end > len(document.text):
                issues.append(
                    _common.issue(
                        "error",
                        "SPAN_BEYOND_DOCUMENT",
                        item_id=verdict.sentence_id,
                        detail="span ends at %d, document is %d characters"
                        % (verdict.char_end, len(document.text)),
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
                        detail="document text at that offset is %r" % located[:70],
                    )
                )

    # 2. Coverage arithmetic must reproduce.
    recorded = record.get("coverage")
    if isinstance(recorded, dict):
        rebuilt = coverage.compute(graded, bundle if bundle is not None else _empty_bundle_stub())
        for key in ("sentences_total", "sentences_requiring_citation", "states", "rules"):
            if recorded.get(key) != rebuilt.get(key):
                issues.append(
                    _common.issue(
                        "error",
                        "COVERAGE_MISMATCH",
                        item_id=key,
                        detail="recorded %r, recomputed %r" % (recorded.get(key), rebuilt.get(key)),
                    )
                )
        coverage_path = out_dir / "coverage.json"
        if coverage_path.is_file():
            stored = _common.read_json(coverage_path)
            if stored != recorded:
                issues.append(
                    _common.issue(
                        "error",
                        "COVERAGE_FILE_DISAGREES",
                        detail="coverage.json does not match the summary inside verdicts.json",
                    )
                )

    # 3. Sentence-level findings.
    errors = [verdict for verdict in graded if verdict.severity == "error"]
    warnings = [verdict for verdict in graded if verdict.severity == "warning"]

    # 3a. The red bar, enforced at the gate rather than only in the classifier. These
    #     are errors, not warnings: a red that fails either bar is an accusation the
    #     evidence does not support, and that is the one output this tool must never
    #     produce. Asserting it here means a hand-edited verdicts.json cannot smuggle
    #     one through either.
    for verdict in graded:
        if verdict.state != "conflict":
            continue
        if verdict.link_confidence != "exact":
            issues.append(
                _common.issue(
                    "error",
                    "CONFLICT_LINK_INFERRED",
                    item_id=verdict.sentence_id,
                    detail="a conflict rests on a link with confidence %r; red requires an "
                    "identity-verified link" % verdict.link_confidence,
                )
            )
        if verdict.evidence_strength not in _common.RED_CAPABLE_STRENGTH:
            issues.append(
                _common.issue(
                    "error",
                    "CONFLICT_EVIDENCE_TOO_WEAK",
                    item_id=verdict.sentence_id,
                    detail="rule %s produced a conflict from %r evidence; red requires "
                    "primary text or a recorded value"
                    % (verdict.rule_id, verdict.evidence_strength),
                )
            )

    # 3a-bis. A value contradiction may not rest on a transcription. The classifier
    #     enforces this with D13, but a hand-edited verdicts.json could pair D08 with OCR
    #     evidence, and the gate is the last place that can catch it. Only D08 is checked:
    #     D04 rests on a source's retraction status, which is read from the registry rather
    #     than from transcribed text.
    document_transcribed = bool((record.get("document") or {}).get("transcribed"))
    for verdict in graded:
        if verdict.state != "conflict" or verdict.rule_id != "D08":
            continue
        transcribed_source = [
            str(entry.get("source_id") or "?")
            for entry in verdict.sources
            if isinstance(entry, dict) and entry.get("transcribed")
        ]
        if document_transcribed or transcribed_source:
            side = (
                "the sentence's own text was transcribed by OCR"
                if document_transcribed
                else "the evidence held for %s was transcribed by OCR" % ", ".join(transcribed_source)
            )
            issues.append(
                _common.issue(
                    "error",
                    "CONFLICT_TRANSCRIBED_EVIDENCE",
                    item_id=verdict.sentence_id,
                    detail="rule D08 produced a conflict, but %s; a transcription may not "
                    "support an accusation, so this must be D13/unverifiable" % side,
                )
            )

    # 3b. Evidence may never appear without provenance. A verdict whose evidence cannot
    #     be traced to an acquisition record is a hallucination risk by construction.    for verdict in graded:
        if verdict.evidence_strength in ("none", "") and not verdict.evidence_origin:
            continue
        if verdict.evidence_strength not in ("none", "") and not verdict.evidence_origin:
            issues.append(
                _common.issue(
                    "error",
                    "EVIDENCE_WITHOUT_PROVENANCE",
                    item_id=verdict.sentence_id,
                    detail="evidence strength %r with no recorded origin"
                    % verdict.evidence_strength,
                )
            )
        for record in verdict.sources:
            strength = record.get("evidence_strength", "none")
            origin = record.get("evidence_origin", "")
            if strength not in ("none", "") and not origin:
                issues.append(
                    _common.issue(
                        "error",
                        "EVIDENCE_WITHOUT_PROVENANCE",
                        item_id=record.get("source_id"),
                        location=verdict.sentence_id,
                        detail="source evidence strength %r with no recorded origin" % strength,
                    )
                )

    # 3c. Support that rests only on an extractor's prose is legitimate but weaker, and
    #     a reader must be able to count it.
    summary_only = [
        verdict
        for verdict in graded
        if verdict.state == "attributed" and verdict.evidence_strength == "prose_summary"
    ]
    if summary_only:
        issues.append(
            _common.issue(
                "warning",
                "SUMMARY_ONLY_SUPPORT",
                item_id="prose_summary",
                detail="%d attributed sentence(s) rest only on a ledger's prose summary, "
                "not on the source's own text or a value copied from it" % len(summary_only),
            )
        )

    # 3d. The report's own prose must stay honest. A generated report may not carry a
    #     universal negative ("plagiarism-free"), and a clean result must state what it
    #     was checked against. `tools/claim_guard.py` is the repository's authority on
    #     that, so the gate calls it instead of re-implementing the rule.
    issues.extend(check_honesty(graded, record, out_dir=out_dir))
    # 3e. The defined claim is recomputed from the recorded verdicts, and the artifact
    #     must carry the definition it rests on.
    import _attribution

    attribution_built = _attribution.build(record.get("coverage") or {}, graded)
    issues.extend(check_attribution(graded, record, out_dir, attribution_built))

    for verdict in errors[:MAX_REPORTED_ERRORS]:
        issues.append(
            _common.issue(
                "error",
                verdict.rule_id,
                location=verdict.sentence_id,
                item_id=verdict.rule_id,
                detail=(verdict.note or "")[:200],
            )
        )
    if len(errors) > MAX_REPORTED_ERRORS:
        issues.append(
            _common.issue(
                "info",
                "FINDINGS_TRUNCATED",
                detail="%d further error-severity sentences not listed individually"
                % (len(errors) - MAX_REPORTED_ERRORS),
            )
        )

    # 4. Artifacts: re-open and count.
    present = [name for name, filename in ARTIFACT_NAMES.items() if (out_dir / filename).is_file()]
    if not present:
        issues.append(
            _common.issue(
                "error",
                "NO_ARTIFACTS",
                detail="none of report.pdf, report.docx, report.html was found in %s" % out_dir,
            )
        )
    notes_sample = _note_samples(graded)
    for name in present:
        path = out_dir / ARTIFACT_NAMES[name]
        if name == "html":
            ok, detail, counts = verify_html(path, expected_highlights, expected_notes)
        elif name == "docx":
            ok, detail, counts = verify_docx(path, expected_highlights, expected_notes)
        else:
            ok, detail, counts = verify_pdf(path, expected_highlights, expected_notes, notes_sample)
        artifact_reports[name] = {"ok": ok, "detail": detail, **counts}
        issues.append(
            _common.issue(
                "info" if ok else "error",
                "ARTIFACT_OK" if ok else "ARTIFACT_MISMATCH",
                item_id=name,
                detail=detail,
            )
        )

    return _common.emit_report(
        "citation-report/gate",
        issues,
        summary={
            "verdicts": len(graded),
            "error_severity_sentences": len(errors),
            "warning_severity_sentences": len(warnings),
            "artifacts_verified": len(present),
            "coverage_percent": (recorded or {}).get("citation_coverage", {}).get("percent"),
            "attribution_issuable": (
                attribution_built.get("result") or {}
            ).get("issuable"),
        },
        extra={
            "artifacts": artifact_reports,
            "attribution": _attribution.record(attribution_built),
        },
    )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="report_gate.py", description="verify a rendered citation report")
    parser.add_argument("--dir", required=True, help="the directory report.py wrote")
    parser.add_argument("--document", help="the graded document, to re-locate every span")
    arguments = parser.parse_args()

    def run_check() -> int:
        document = None
        if arguments.document:
            import _intake

            try:
                document = _intake.read_document(arguments.document)
            except _intake.UnreadableDocument as exc:
                # The gate cannot re-locate spans in a document nobody could read. That is
                # a gap in the inputs, not a finding about the report, so it takes the same
                # status, exit code and `input_gaps[]` shape as the report CLI: exit 1 here
                # would read as "the report is wrong" when nothing was verified at all.
                return _common.emit_unreadable_document("citation-report/gate", exc)
        return check_directory(arguments.dir, document=document)

    return _common.main_guard("citation-report/gate", run_check)


if __name__ == "__main__":
    raise SystemExit(main())
