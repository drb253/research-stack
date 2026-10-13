#!/usr/bin/env python3
"""Validate an EvidenceForge meta-analysis coding sheet.

This validator is intentionally conservative. It checks structure and basic
pre-pooling conditions; it does not decide that pooling is scientifically valid.

Exit codes follow the repository vocabulary (docs/EVIDENCE-INVARIANT.md): ``0`` pass,
``1`` a finding about the sheet (malformed structure, blank ids, duplicate keys, mixed
metrics), ``3`` ``insufficient_evidence`` (the sheet was read but some rows are
unusable), ``4`` ``insufficient_input`` (the file could not be read or parsed at all).
An input gap is never reported with a finding's status.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import Counter
from pathlib import Path


REQUIRED_COLUMNS = ["study_id", "effect_id", "effect_metric", "estimate", "se"]
RECOMMENDED_COLUMNS = [
    "citation",
    "population",
    "design",
    "outcome",
    "risk_of_bias",
    "extraction_source",
]


def is_number(value: str) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV has no header row.")
        return list(reader)


def validate(path: Path, require_single_metric: bool = True) -> tuple[list[str], list[str], list[str]]:
    """Return ``(errors, warnings, input_conditions)``.

    ``errors`` are findings about the sheet (a malformed structure, a blank id, a
    duplicate key). ``input_conditions`` are rows the analysis cannot use at all
    (an unusable effect size or standard error). The two are kept apart because the
    invariant (docs/EVIDENCE-INVARIANT.md) forbids reporting an input gap in the same
    channel or exit status as a finding about the artefact under test.
    """
    rows = read_rows(path)
    errors: list[str] = []
    warnings: list[str] = []
    input_conditions: list[str] = []

    if not rows:
        errors.append("Coding sheet has no data rows.")
        return errors, warnings, input_conditions

    columns = set(rows[0].keys())
    for column in REQUIRED_COLUMNS:
        if column not in columns:
            errors.append(f"Missing required column: {column}")

    for column in RECOMMENDED_COLUMNS:
        if column not in columns:
            warnings.append(f"Missing recommended audit column: {column}")

    if errors:
        return errors, warnings, input_conditions

    keys: Counter[str] = Counter()
    metrics: set[str] = set()

    for i, row in enumerate(rows, start=2):
        study_id = row.get("study_id", "").strip()
        effect_id = row.get("effect_id", "").strip()
        metric = row.get("effect_metric", "").strip()
        estimate = row.get("estimate", "").strip()
        se = row.get("se", "").strip()

        if not study_id:
            errors.append(f"Row {i}: study_id is blank.")
        if not effect_id:
            errors.append(f"Row {i}: effect_id is blank.")
        if not metric:
            errors.append(f"Row {i}: effect_metric is blank.")
        else:
            metrics.add(metric)

        key = f"{study_id}::{effect_id}"
        keys[key] += 1

        if not is_number(estimate):
            input_conditions.append(f"Row {i}: effect size unusable -- estimate is not numeric.")
        if not is_number(se):
            input_conditions.append(f"Row {i}: effect size unusable -- se is not numeric.")
        elif float(se) <= 0:
            input_conditions.append(f"Row {i}: effect size unusable -- se <= 0.")

        if "risk_of_bias" in columns and not row.get("risk_of_bias", "").strip():
            warnings.append(f"Row {i}: risk_of_bias is blank.")
        if "extraction_source" in columns and not row.get("extraction_source", "").strip():
            warnings.append(f"Row {i}: extraction_source is blank.")

    for key, count in keys.items():
        if count > 1:
            errors.append(f"Duplicate study_id/effect_id key: {key}")

    if require_single_metric and len(metrics) > 1:
        errors.append(
            "Multiple effect metrics found: "
            + ", ".join(sorted(metrics))
            + ". Harmonize or filter before pooling."
        )

    dependency_groups = [row.get("dependency_group", "").strip() for row in rows if "dependency_group" in columns]
    repeated_studies = [study for study, count in Counter(row.get("study_id", "").strip() for row in rows).items() if count > 1]
    if repeated_studies and not any(dependency_groups):
        warnings.append(
            "Some studies contribute multiple effects, but dependency_group is blank. "
            "Plan multilevel/RVE/selection before pooling."
        )

    return errors, warnings, input_conditions


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an EvidenceForge meta-analysis coding sheet.")
    parser.add_argument("--input", required=True, help="Path to coding sheet CSV.")
    parser.add_argument(
        "--allow-mixed-metrics",
        action="store_true",
        help="Allow multiple effect_metric values. Use only before a conversion/harmonization step.",
    )
    args = parser.parse_args()

    path = Path(args.input)
    if not path.exists():
        print(f"ERROR: input file not found: {path}", file=sys.stderr)
        return 4

    try:
        errors, warnings, input_conditions = validate(path, require_single_metric=not args.allow_mixed_metrics)
    except Exception as exc:  # noqa: BLE001 - CLI should report malformed files cleanly.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4

    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")

    if input_conditions:
        print(
            f"INPUT CONDITION: insufficient_evidence -- {len(input_conditions)} row(s) "
            "could not be used; this is a statement about the coding sheet, not a finding "
            "about the analysis."
        )
        for condition in input_conditions:
            print(f"  {condition}")
        if errors:
            print(f"Also recorded: {len(errors)} finding(s) about the sheet (see ERROR lines above).")
        print("  Worklist: supply or correct these rows and re-run; the analysis must not "
              "proceed on the usable subset alone.")
        return 3

    if errors:
        print(f"Validation failed: {len(errors)} error(s), {len(warnings)} warning(s).")
        return 1

    print(f"Validation passed: 0 errors, {len(warnings)} warning(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
