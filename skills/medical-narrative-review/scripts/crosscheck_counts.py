#!/usr/bin/env python3
"""Reconcile the four files that describe the same review from different angles.

`make_prisma_flow.py` proves the screening arithmetic is internally consistent. It cannot know
whether the numbers agree with the ledger. This command closes that gap: PRISMA totals, the
source ledger, the claim ledger and the reference list must describe the same evidence base.

Checks
  PRISMA_INCLUDED_MISMATCH   studies_included differs from the ledger's included rows
  PRISMA_VERIFIED_MISMATCH   sources_verified differs from verified citable rows
  REFERENCE_COUNT_MISMATCH   the reference list length differs from verified citable sources
  CLAIM_SOURCE_MISSING       a claim cites a source id absent from the ledger
  CITABLE_SOURCE_NO_CLAIM    a citable source is never used by any claim
  CLAIM_UNVERIFIED_SOURCE    a claim marked verified rests on an unverified source

By default a count mismatch is a warning, because a workspace can be mid-flight. With --strict it
is an error, which is the mode to use before submission.

Usage
  python3 scripts/crosscheck_counts.py --workspace .
  python3 scripts/crosscheck_counts.py --workspace . --strict
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from _common import emit_report, issue, read_csv, read_text, run

TOOL = "crosscheck_counts"
REF_RE = re.compile(r"(?m)^(\d+)\.\s+\S")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def cli():
    parser = argparse.ArgumentParser(description="Cross-check PRISMA, ledger, claims and references.")
    parser.add_argument("--workspace", default=".", help="review workspace directory")
    parser.add_argument("--strict", action="store_true",
                        help="treat a count mismatch as an error (use before submission)")
    args = parser.parse_args()

    base = Path(args.workspace)
    issues, summary = [], {"workspace": str(base.resolve())}

    counts_path = base / "prisma_counts.json"
    sources_path = base / "sources.csv"
    if not counts_path.is_file() or not sources_path.is_file():
        return emit_report(TOOL, [issue("error", "INPUT_MISSING",
                                        detail="prisma_counts.json and sources.csv are both required")],
                           summary=summary)

    counts = read_json(counts_path)
    _, rows = read_csv(sources_path)

    included = [r for r in rows if r.get("inclusion_status") == "included"]
    citable = [r for r in rows if r.get("inclusion_status") in {"included", "cited_for_context"}]
    verified = [r for r in citable if r.get("verification_status") == "verified"]

    prisma_included = int((counts.get("included") or {}).get("studies_included", 0) or 0)
    prisma_verified = int((counts.get("included") or {}).get("sources_verified", 0) or 0)

    summary.update({
        "prisma_studies_included": prisma_included,
        "ledger_included": len(included),
        "prisma_sources_verified": prisma_verified,
        "ledger_verified_citable": len(verified),
    })

    severity = "error" if args.strict else "warning"
    if prisma_included != len(included):
        issues.append(issue(severity, "PRISMA_INCLUDED_MISMATCH",
                            detail="prisma %d vs ledger %d" % (prisma_included, len(included))))
    if prisma_verified != len(verified):
        issues.append(issue(severity, "PRISMA_VERIFIED_MISMATCH",
                            detail="prisma %d vs ledger %d" % (prisma_verified, len(verified))))

    refs_path = base / "final" / "references.md"
    if refs_path.is_file():
        references = len(REF_RE.findall(read_text(refs_path, {".md"})))
        summary["references"] = references
        if references != len(verified):
            issues.append(issue(severity, "REFERENCE_COUNT_MISMATCH",
                                detail="references %d vs verified citable %d" % (references, len(verified))))
    else:
        issues.append(issue("info", "REFERENCES_SKIPPED", detail="final/references.md not built yet"))

    claims_path = base / "claims.csv"
    if claims_path.is_file():
        _, claims = read_csv(claims_path)
        known = {r.get("source_id") for r in rows}
        used = set()
        for claim in claims:
            ids = [part.strip() for part in re.split(r"[,;\s]+", claim.get("source_ids", "")) if part.strip()]
            used.update(ids)
            for source_id in ids:
                if source_id not in known:
                    issues.append(issue("error", "CLAIM_SOURCE_MISSING", item_id=claim.get("claim_id"),
                                        detail=source_id))
                else:
                    row = next(r for r in rows if r.get("source_id") == source_id)
                    if (claim.get("verification_status") == "verified"
                            and row.get("verification_status") != "verified"):
                        issues.append(issue("error", "CLAIM_UNVERIFIED_SOURCE",
                                            item_id=claim.get("claim_id"), detail=source_id))
        summary["claims"] = len(claims)
        summary["sources_used_by_claims"] = len(used)
        for row in citable:
            if row.get("source_id") not in used:
                issues.append(issue("warning", "CITABLE_SOURCE_NO_CLAIM", item_id=row.get("source_id")))
    else:
        issues.append(issue("info", "CLAIMS_SKIPPED", detail="claims.csv not present"))

    return emit_report(TOOL, issues, summary=summary)


if __name__ == "__main__":
    run(TOOL, cli)
