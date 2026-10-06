"""Shared, dependency-free safety helpers for medical-narrative-review CLIs.

Every bundled command is local, deterministic, bounded, and network-free. Nothing
here reads environment variables, calls a network service, or evaluates code.
Compatible with Python 3.9+ (standard library only).
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

MAX_FILE_BYTES = 5_000_000
MAX_RECORDS = 10_000
MAX_JSON_NODES = 100_000
MAX_JSON_DEPTH = 50
MAX_CSV_FIELD_BYTES = 100_000

DOI_RE = re.compile(r"^10\.[0-9]{4,9}/\S+$", re.IGNORECASE)
PMID_RE = re.compile(r"^[1-9][0-9]{0,8}$")
PMCID_RE = re.compile(r"^PMC[1-9][0-9]{0,8}$", re.IGNORECASE)
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
SOURCE_ID_RE = re.compile(r"^S[0-9]{3,8}$")
CLAIM_ID_RE = re.compile(r"^C[0-9]{3,8}$")
NONE_VALUES = {"none", "na", "n/a", "not_applicable", "not-applicable", "null", ""}
NOT_REPORTED_VALUES = {"not_reported", "not reported", "nr", "n.r."}


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
) -> int:
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
    payload = {
        "tool": tool,
        "status": "fail" if error_count else "pass",
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


def is_placeholder(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.strip().lower()
    return (
        not lowered
        or "[[todo" in lowered
        or "todo" in lowered
        or "tbd" in lowered
        or lowered in {"tk", "replace_me", "unknown", "xxx", "-"}
    )


def write_new_text(path_value: str | Path, content: str, suffixes: Iterable[str]) -> Path:
    path = Path(path_value)
    allowed = {suffix.lower() for suffix in suffixes}
    if path.suffix.lower() not in allowed:
        raise InputError("output extension must be one of: " + ", ".join(sorted(allowed)))
    if path.exists() or path.is_symlink():
        raise InputError("output already exists; refusing to overwrite")
    parent = path.parent
    if str(parent) and not parent.is_dir():
        parent.mkdir(parents=True, exist_ok=True)
    if parent.is_symlink():
        raise InputError("output parent must be a regular directory")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_FILE_BYTES:
        raise InputError("output exceeds %d bytes" % MAX_FILE_BYTES)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    return path


def write_text_lf(path_value: str | Path, content: str) -> Path:
    """Write UTF-8 text with LF endings.

    Uses ``Path.open`` rather than ``Path.write_text`` because the ``newline``
    argument of ``write_text`` only exists from Python 3.10 and this skill targets
    3.9 as well.
    """
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


def valid_pmcid(value: str) -> bool:
    return bool(PMCID_RE.fullmatch((value or "").strip()))


def normalize_title(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "").casefold()
    return " ".join(re.findall(r"[a-z0-9]+", decomposed))


def is_absent(value: str) -> bool:
    return (value or "").strip().lower() in NONE_VALUES


def is_not_reported(value: str) -> bool:
    return (value or "").strip().lower() in NOT_REPORTED_VALUES


def split_ids(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[;,]", value or "") if part.strip()]


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug or "review"


def main_guard(tool: str, callback: Any) -> int:
    try:
        return int(callback())
    except (InputError, OSError, ValueError) as exc:
        return emit_input_error(tool, exc)


def run(tool: str, callback: Any) -> None:
    raise SystemExit(main_guard(tool, callback))


if __name__ == "__main__":
    print("This module is imported by the medical-narrative-review command-line tools.")
    sys.exit(0)
