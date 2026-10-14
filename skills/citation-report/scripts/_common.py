"""Shared, dependency-free safety helpers for citation-report CLIs.

PROVENANCE: the bounded-IO and issue-reporting helpers in this module are derived
from `medical-narrative-review/scripts/_common.py` (same repository, MIT), so that
this skill behaves identically at its edges: bounded inputs, a single JSON verdict
envelope, and the same error/warning/info severity model. Skills are installed and
symlinked individually (install.sh:235, install.sh:273-284) and no skill may import
another skill's directory at run time, so this is a deliberate, provenance-noted
copy. Parity is not assumed. `scripts/check_common_drift.py` compares every shared
primitive against the upstream file, and `scripts/selftest.sh` runs it, so a silent
divergence fails the harness. A difference is a failure unless the check's ALLOWED
table lists it with a reason. The current allowlist is the four size limits (this
skill reads larger inputs) and three envelope helpers (`emit_report`,
`emit_input_error`, `write_text_lf`) that this copy extends. A module-level
constant whose value is a literal is compared by value, so reformatting is not
drift.

Everything here is local, deterministic, bounded, and network-free. Compatible with
Python 3.9+ (standard library only).
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
import unicodedata
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MAX_FILE_BYTES = 12_000_000
MAX_RECORDS = 10_000
MAX_JSON_NODES = 500_000
MAX_JSON_DEPTH = 60
MAX_CSV_FIELD_BYTES = 200_000
MAX_SENTENCE_CHARS = 4_000

DOI_RE = re.compile(r"^10\.[0-9]{4,9}/\S+$", re.IGNORECASE)
PMID_RE = re.compile(r"^[1-9][0-9]{0,8}$")
PMCID_RE = re.compile(r"^PMC[1-9][0-9]{0,8}$", re.IGNORECASE)
SOURCE_ID_RE = re.compile(r"^S[0-9]{3,8}$")
CLAIM_ID_RE = re.compile(r"^C[0-9]{3,8}$")
SENTENCE_ID_RE = re.compile(r"^N[0-9]{4,8}$")

# --------------------------------------------------------------------------- #
# Controlled vocabularies — the report schema. Nothing outside these sets is
# accepted anywhere, so a typo can never become a quiet new category.
# --------------------------------------------------------------------------- #

#: Channel D — deterministic, gate-grade. Paint colour is driven ONLY by these.
#:
#: `unverifiable` is not in the four-colour scheme of the reference report, and it
#: is the point: when a citation resolves to an identified source but we hold no
#: evidence for it, the honest answer is neither "supported" (silent green) nor
#: "unsupported" (an unearned accusation). It is "this report cannot tell", stated
#: plainly and counted separately.
VERDICT_STATES = (
    "no_citation_needed",
    "attributed",
    "synthesis",
    "unverifiable",
    "unattributed",
    "conflict",
)
VERDICT_STATE_SET = frozenset(VERDICT_STATES)

#: Severity each deterministic state contributes to the gate.
STATE_SEVERITY = {
    "no_citation_needed": "info",
    "attributed": "info",
    "synthesis": "info",
    "unverifiable": "info",
    "unattributed": "warning",
    "conflict": "error",
}

#: Channel A — advisory. Model-generated. Can never set, change or veto a verdict.
ADVISORY_GRADES = ("direct_support", "synthesis", "unsupported", "contradictory")
ADVISORY_GRADE_SET = frozenset(ADVISORY_GRADES)
ADVISORY_DISCLOSURE = "advisory, model-generated, not a gate input"

#: How much evidence we actually hold for a source. Mirrors the repository's
#: existing retrieval_status discipline: unavailable is recorded, never inferred.
EVIDENCE_AVAILABILITY = ("full_text", "abstract", "metadata_only", "unavailable")
EVIDENCE_AVAILABILITY_SET = frozenset(EVIDENCE_AVAILABILITY)

#: Strength order, weakest last. Used to choose the best evidence for a source.
EVIDENCE_RANK = {"full_text": 3, "abstract": 2, "metadata_only": 1, "unavailable": 0}

#: How good the evidence is, which is a different question from how much of it
#: there is. `full_text` from a ledger's prose `main_finding` is plenty of text and
#: still a human's summary, so availability alone cannot decide what a verdict may
#: claim. Only `primary` and `recorded_estimate` may support a red finding.
#:
#: * primary            - text extracted from the source itself (supplied file or acquired full text)
#: * recorded_estimate   - a value the ledger records verbatim (effect_estimate, n_participants, follow_up)
#: * prose_summary       - a human's own words about the source (main_finding, key_outcomes)
#: * abstract            - the published abstract, which is the source's own words but abridged
#: * none                - nothing readable
EVIDENCE_STRENGTH = ("primary", "recorded_estimate", "prose_summary", "abstract", "none")
EVIDENCE_STRENGTH_SET = frozenset(EVIDENCE_STRENGTH)

#: Strength order, best first.
EVIDENCE_STRENGTH_RANK = {
    "primary": 4,
    "recorded_estimate": 3,
    "prose_summary": 2,
    "abstract": 1,
    "none": 0,
}

#: Strengths that may support a check of a sentence's numbers at all.
CHECKABLE_STRENGTH = frozenset({"primary", "recorded_estimate", "abstract"})

#: Strengths that may support a RED finding. An accusation requires machine-comparable
#: evidence: the source's own text, or a value the ledger copied verbatim. A prose
#: summary is an interpretation, and convicting on it would make the tool's worst
#: failure -- a confident false accusation -- reachable through one bad summary.
RED_CAPABLE_STRENGTH = frozenset({"primary", "recorded_estimate"})

#: How a citation was joined to a source. Red requires `exact`: a marker that names
#: the source, or a DOI the source's identity was confirmed against. A title or year
#: match is a guess about identity, and a guess may not convict.
LINK_CONFIDENCE = ("exact", "inferred", "none")
LINK_CONFIDENCE_SET = frozenset(LINK_CONFIDENCE)
VERIFIED_LINK_METHODS = frozenset({"doi", "user_supplied", "ledger", "declared"})

#: Top-line run status. `pass` and `fail` are findings about the document;
#: `insufficient_evidence` and `insufficient_input` are statements about our inputs
#: and must never be presented in the same shape as a finding.
RUN_STATUSES = ("pass", "fail", "insufficient_evidence", "insufficient_input")
STATUS_PRECEDENCE = {
    "insufficient_input": 3,
    "insufficient_evidence": 2,
    "fail": 1,
    "pass": 0,
}
STATUS_EXIT_CODE = {
    "pass": 0,
    "fail": 1,
    "insufficient_evidence": 3,
    "insufficient_input": 4,
}

#: Source verification status, reusing the medical-narrative-review vocabulary.
VERIFICATION_STATUS = ("verified", "unverified", "failed")
RETRACTION_STATUS = ("not_checked", "clear", "retracted", "expression_of_concern", "corrected")

#: Citation marker grammars the intake layer can bind.
CITATION_STYLES = ("numeric", "author-year", "ledger")

NONE_VALUES = {"none", "na", "n/a", "not_applicable", "not-applicable", "null", ""}


class InputError(ValueError):
    """Raised when a local input fails a bounded safety check."""


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    location: str | None = None
    item_id: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, str]:
        return {key: value for key, value in asdict(self).items() if value is not None}


def _checked_file(path_value: str | Path, suffixes: Iterable[str]) -> Path:
    path = Path(path_value)
    allowed = {suffix.lower() for suffix in suffixes}
    if path.is_symlink():
        raise InputError("symbolic-link inputs are not accepted")
    if not path.is_file():
        raise InputError("input must be an existing regular file")
    if path.suffix.lower() not in allowed:
        raise InputError("input extension must be one of: " + ", ".join(sorted(allowed)))
    if path.stat().st_size > MAX_FILE_BYTES:
        raise InputError("input exceeds %d bytes" % MAX_FILE_BYTES)
    return path


def read_text(path_value: str | Path, suffixes: Iterable[str]) -> str:
    path = _checked_file(path_value, suffixes)
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise InputError("input must be UTF-8 text") from exc


def _reject_duplicate_keys(pairs: list) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise InputError("JSON contains a duplicate object key")
        result[key] = value
    return result


def _reject_nonfinite_json(_value: str) -> None:
    raise InputError("JSON non-finite numbers are not accepted")


def _check_json_bounds(value: Any, depth: int = 0) -> int:
    if depth > MAX_JSON_DEPTH:
        raise InputError("JSON nesting exceeds %d levels" % MAX_JSON_DEPTH)
    count = 1
    if isinstance(value, dict):
        for child in value.values():
            count += _check_json_bounds(child, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_RECORDS:
            raise InputError("JSON array exceeds %d records" % MAX_RECORDS)
        for child in value:
            count += _check_json_bounds(child, depth + 1)
    if count > MAX_JSON_NODES:
        raise InputError("JSON exceeds %d nodes" % MAX_JSON_NODES)
    return count


def read_json(path_value: str | Path) -> Any:
    text = read_text(path_value, {".json"})
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except (json.JSONDecodeError, RecursionError) as exc:
        raise InputError("input is not valid bounded JSON") from exc
    _check_json_bounds(value)
    return value


def read_csv(path_value: str | Path) -> tuple[list[str], list[dict[str, str]]]:
    text = read_text(path_value, {".csv"})
    csv.field_size_limit(MAX_CSV_FIELD_BYTES)
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        fields = list(reader.fieldnames or [])
        if not fields or any(not field for field in fields):
            raise InputError("CSV requires a non-empty header row")
        if len(set(fields)) != len(fields):
            raise InputError("CSV contains duplicate header names")
        rows: list[dict[str, str]] = []
        for index, row in enumerate(reader, start=1):
            if index > MAX_RECORDS:
                raise InputError("CSV exceeds %d data rows" % MAX_RECORDS)
            if None in row:
                raise InputError("CSV row has more fields than the header")
            rows.append({key: (value or "") for key, value in row.items()})
    except csv.Error as exc:
        raise InputError("input is not valid bounded CSV") from exc
    return fields, rows


def issue(
    severity: str,
    code: str,
    *,
    location: str | None = None,
    item_id: str | None = None,
    detail: str | None = None,
) -> Issue:
    if severity not in {"error", "warning", "info"}:
        raise ValueError("unsupported issue severity")
    return Issue(
        severity=severity, code=code, location=location, item_id=item_id, detail=detail
    )


def emit_report(
    tool: str,
    issues: Iterable[Issue],
    *,
    summary: dict | None = None,
    extra: dict | None = None,
    status_override: str | None = None,
    exit_override: int | None = None,
) -> int:
    """Print the JSON envelope and return the process exit code.

    `status_override` exists so a condition caused by missing inputs can be reported as
    such rather than being flattened into pass/fail. Status and exit code are kept
    separate deliberately: `--allow-insufficient` lets a caller *choose* to continue
    while the status still records `insufficient_evidence`, so the override is visible
    in the artefact and not only in a log line.
    """
    ordered = sorted(
        issues,
        key=lambda item: (
            {"error": 0, "warning": 1, "info": 2}[item.severity],
            item.code,
            item.location or "",
            item.item_id or "",
        ),
    )
    error_count = sum(item.severity == "error" for item in ordered)
    warning_count = sum(item.severity == "warning" for item in ordered)
    derived = "fail" if error_count else "pass"
    if status_override is not None:
        if status_override not in RUN_STATUSES:
            raise ValueError("unsupported run status: %r" % status_override)
        # A finding is never downgraded by an input status, and an input status is
        # never upgraded to a pass. The more severe of the two names the run.
        status = (
            status_override
            if STATUS_PRECEDENCE[status_override] >= STATUS_PRECEDENCE[derived]
            else derived
        )
    else:
        status = derived
    payload = {
        "tool": tool,
        "status": status,
        "summary": {
            "errors": error_count,
            "warnings": warning_count,
            **(summary or {}),
        },
        "issues": [item.to_dict() for item in ordered],
    }
    if extra is not None:
        payload.update(extra)
    print(json.dumps(payload, indent=2, sort_keys=True))
    if exit_override is not None:
        return int(exit_override)
    if status in ("insufficient_evidence", "insufficient_input"):
        return STATUS_EXIT_CODE[status]
    return 1 if error_count else 0


def emit_input_error(tool: str, exc: Exception) -> int:
    return emit_report(
        tool,
        [
            issue(
                "error",
                "INVALID_INPUT",
                location=type(exc).__name__,
                detail=str(exc)[:200],
            )
        ],
    )


def emit_unreadable_document(tool: str, exc: Exception) -> int:
    """Report a document that could not be read *at all* as an input condition.

    ``insufficient_input`` (exit 4) is the status this skill promises for "the document
    itself could not be read well enough to make findings". Reporting it as an
    ``INVALID_INPUT`` error (exit 1) puts a statement about our inputs in the finding
    channel, where a reader takes it for a result about the document.

    The condition is repeated in ``input_gaps[]`` with its kind and the worklist that would
    close it, so a caller can act on the gap without parsing the sentence, and so an absent
    extractor and an unreadable file are distinguishable without prose. Both entry points --
    the report CLI and the gate -- route through here so they cannot drift apart.
    """
    kind = getattr(exc, "kind", "") or "unreadable_document"
    how_to_close = getattr(exc, "how_to_close", "")
    gap = {"kind": kind, "detail": str(exc)[:400]}
    if how_to_close:
        gap["how_to_close"] = how_to_close
    return emit_report(
        tool,
        [
            issue(
                "error",
                "INSUFFICIENT_INPUT",
                location="intake",
                detail=str(exc)[:400],
            )
        ],
        status_override="insufficient_input",
        extra={"input_gaps": [gap]},
    )


def require_object(value: Any, label: str = "root") -> dict:
    if not isinstance(value, dict):
        raise InputError(label + " must be a JSON object")
    return value


def require_list(value: Any, label: str) -> list:
    if not isinstance(value, list):
        raise InputError(label + " must be a JSON array")
    if len(value) > MAX_RECORDS:
        raise InputError(label + " exceeds %d records" % MAX_RECORDS)
    return value


def is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def write_text_lf(path_value: str | Path, content: str) -> Path:
    """Write UTF-8 text with LF endings. Never writes through a symlink."""
    path = Path(path_value)
    if path.is_symlink():
        raise InputError("refusing to write through a symbolic link")
    parent = path.parent
    if str(parent) and not parent.is_dir():
        parent.mkdir(parents=True, exist_ok=True)
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_FILE_BYTES:
        raise InputError("output exceeds %d bytes" % MAX_FILE_BYTES)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    return path


def write_bytes(path_value: str | Path, payload: bytes) -> Path:
    """Write raw bytes for an artifact (PDF, DOCX). Never writes through a symlink."""
    path = Path(path_value)
    if path.is_symlink():
        raise InputError("refusing to write through a symbolic link")
    parent = path.parent
    if str(parent) and not parent.is_dir():
        parent.mkdir(parents=True, exist_ok=True)
    if len(payload) > MAX_FILE_BYTES:
        raise InputError("output exceeds %d bytes" % MAX_FILE_BYTES)
    with path.open("wb") as handle:
        handle.write(payload)
    return path


def write_json(path_value: str | Path, value: Any) -> Path:
    return write_text_lf(
        path_value, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )


def normalize_doi(value: str) -> str:
    normalized = (value or "").strip().lower()
    for prefix in ("https://dx.doi.org/", "https://doi.org/", "http://doi.org/", "doi:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return normalized.rstrip(".,;)")


def valid_doi(value: str) -> bool:
    return bool(DOI_RE.fullmatch(normalize_doi(value)))


def valid_pmid(value: str) -> bool:
    return bool(PMID_RE.fullmatch((value or "").strip()))


def normalize_title(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "").casefold()
    return " ".join(re.findall(r"[a-z0-9]+", decomposed))


def is_absent(value: str) -> bool:
    return (value or "").strip().lower() in NONE_VALUES


def split_ids(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[;,]", value or "") if part.strip()]


def sentence_id(index: int) -> str:
    """Stable, zero-padded sentence identifier: N0001, N0002, ..."""
    return "N%04d" % index


def main_guard(tool: str, callback: Any) -> int:
    try:
        return int(callback())
    except (InputError, OSError, ValueError) as exc:
        return emit_input_error(tool, exc)


def run(tool: str, callback: Any) -> None:
    raise SystemExit(main_guard(tool, callback))


if __name__ == "__main__":
    print("This module is imported by the citation-report command-line tools.")
    sys.exit(0)
