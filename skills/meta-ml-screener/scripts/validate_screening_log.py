#!/usr/bin/env python3
"""Validate an EvidenceForge ML-assisted screening log.

Exit codes follow docs/EVIDENCE-INVARIANT.md, so a gap in the input is never reported in
the same channel, shape or status as a finding about the log:

  0  the log passed validation;
  1  a finding about the log (N row/column errors);
  2  the input could not be read (missing file, unparsable CSV);
  3  an input gap: insufficient_input -- the log carries no data rows to validate. The
     gap is named and given a JSON worklist on stderr, and stdout is left empty.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import sys
import tempfile
from pathlib import Path


REQUIRED_COLUMNS = [
    "record_id",
    "source_database",
    "title",
    "abstract_available",
    "dedup_status",
    "ml_task",
    "human_decision",
    "reviewer",
]

ALLOWED_DECISIONS = {"include", "exclude", "maybe", "retrieve_full_text", "pending"}
ALLOWED_DEDUP = {"unique", "duplicate", "unclear"}

#: An input gap exits 3, never 1: an empty log is not a finding about screening it does not
#: contain, and a caller must be able to tell the two apart by status alone.
INSUFFICIENT_INPUT = 3


class InsufficientInput(Exception):
    """The log exists but holds no rows to validate -- an input gap, not a finding."""


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV has no header row.")
        return list(reader)


def validate(path: Path) -> tuple[list[str], list[str]]:
    rows = read_rows(path)
    errors: list[str] = []
    warnings: list[str] = []

    if not rows:
        # Not an error: a gap in the inputs. Raised so main() can route it to its own
        # status, channel and exit code instead of the findings channel.
        raise InsufficientInput("Screening log has no data rows.")

    columns = set(rows[0].keys())
    for column in REQUIRED_COLUMNS:
        if column not in columns:
            errors.append(f"Missing required column: {column}")

    if errors:
        return errors, warnings

    record_ids: set[str] = set()

    for i, row in enumerate(rows, start=2):
        record_id = row.get("record_id", "").strip()
        decision = row.get("human_decision", "").strip()
        dedup = row.get("dedup_status", "").strip()
        reviewer = row.get("reviewer", "").strip()

        if not record_id:
            errors.append(f"Row {i}: record_id is blank.")
        elif record_id in record_ids:
            errors.append(f"Row {i}: duplicate record_id: {record_id}")
        record_ids.add(record_id)

        if decision not in ALLOWED_DECISIONS:
            errors.append(f"Row {i}: invalid human_decision: {decision}")
        if dedup not in ALLOWED_DEDUP:
            errors.append(f"Row {i}: invalid dedup_status: {dedup}")
        if not reviewer:
            errors.append(f"Row {i}: reviewer is blank.")

        if decision == "exclude" and not row.get("exclusion_reason", "").strip():
            errors.append(f"Row {i}: excluded record lacks exclusion_reason.")
        if row.get("ml_label", "").strip() and not row.get("ml_model", "").strip():
            warnings.append(f"Row {i}: ml_label exists but ml_model is blank.")
        if decision in {"maybe", "retrieve_full_text", "pending"}:
            warnings.append(f"Row {i}: record requires follow-up: {record_id}")

    return errors, warnings


def input_gap_worklist(path: Path, reason: str) -> dict:
    """What is missing, why, and what to do -- the machine-readable input worklist."""
    return {
        "status": "insufficient_input",
        "input_gaps": [
            {
                "input": str(path),
                "reason": reason,
                "action": (
                    "supply a screening log with at least one data row and re-run "
                    "validate_screening_log.py --input <log>; nothing in this file was "
                    "validated"
                ),
            }
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate an EvidenceForge ML screening log.")
    parser.add_argument("--input", help="Path to screening log CSV.")
    parser.add_argument("--self-test", action="store_true",
                        help="offline check of the four exit paths; no files are read")
    args = parser.parse_args(argv)

    if args.self_test:
        return _self_test()
    if not args.input:
        print("ERROR: --input is required (or use --self-test)", file=sys.stderr)
        return 2

    path = Path(args.input)
    if not path.exists():
        print(f"ERROR: input file not found: {path}", file=sys.stderr)
        return 2

    try:
        errors, warnings = validate(path)
    except InsufficientInput as gap:
        # An input gap: its own status, its own channel (stderr, leaving stdout empty) and
        # its own exit code, so a script can never read it as a pass or as a finding.
        print(f"INSUFFICIENT INPUT: {gap}", file=sys.stderr)
        print(f"status: insufficient_input -- nothing in {path} was validated",
              file=sys.stderr)
        print(json.dumps(input_gap_worklist(path, str(gap))), file=sys.stderr)
        return INSUFFICIENT_INPUT
    except Exception as exc:  # noqa: BLE001 - CLI should report malformed files cleanly.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")

    if errors:
        print(f"Validation failed: {len(errors)} error(s), {len(warnings)} warning(s).")
        return 1

    print(f"Validation passed: 0 errors, {len(warnings)} warning(s).")
    return 0


def _self_test() -> int:
    """Offline assertions for the four exit paths, calling main() itself.

    This script runs nowhere else in CI, so the paths are pinned here: valid -> 0, a bad
    row -> 1, no data rows -> 3 (an input gap, with a worklist and no "Validation failed"),
    and a missing file -> 2. Every fixture is written to and removed from a temporary
    directory; nothing is read from the network or from the repository.
    """
    def run(argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    header = ",".join(REQUIRED_COLUMNS) + "\n"
    good_row = "R1,PubMed,Title one,yes,unique,screening,include,AB\n"
    bad_row = "R1,PubMed,Title one,yes,unique,screening,banana,AB\n"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        valid = root / "valid.csv"
        valid.write_text(header + good_row, encoding="utf-8")
        bad = root / "bad.csv"
        bad.write_text(header + bad_row, encoding="utf-8")
        no_rows = root / "no_rows.csv"
        no_rows.write_text(header, encoding="utf-8")
        missing = root / "missing.csv"

        # (a) a good log passes
        code, out, _ = run(["--input", str(valid)])
        assert code == 0, (code, out)
        assert "Validation passed" in out, out

        # (b) a bad row is a FINDING: exit 1, and the finding wording is unchanged
        code, out, _ = run(["--input", str(bad)])
        assert code == 1, (code, out)
        assert "Validation failed: 1 error(s)" in out, out

        # (c) no data rows is an INPUT GAP: exit 3, its own status and worklist on stderr,
        #     no finding wording anywhere, and the finding channel (stdout) left empty
        code, out, err = run(["--input", str(no_rows)])
        assert code == INSUFFICIENT_INPUT, (code, out, err)
        assert out == "", out
        assert "insufficient_input" in err, err
        assert "Validation failed" not in out + err, (out, err)
        assert "Validation passed" not in out + err, (out, err)
        assert "no data rows" in err, err
        worklist = json.loads([line for line in err.splitlines() if line.startswith("{")][-1])
        assert worklist["status"] == "insufficient_input", worklist
        gap = worklist["input_gaps"][0]
        assert gap["reason"] and gap["action"], gap
        assert gap["input"] == str(no_rows), gap

        # (d) a missing file still exits 2
        code, out, err = run(["--input", str(missing)])
        assert code == 2, (code, out, err)

    print("self-test: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
