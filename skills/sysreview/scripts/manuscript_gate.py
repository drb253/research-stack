#!/usr/bin/env python3
"""manuscript_gate.py -- the sysreview manuscript gate's attribution claim.

The gate decides whether a review manuscript may carry the defined term
"plagiarism-free (against the sources checked)". It does not grade the
manuscript. It reads the results the upstream gates already wrote and hands them
to `tools/attribution.py`, which holds the definition in one place so the three
consumers cannot drift.

FACT -> THE GATE THAT DECIDES IT

  passage_findings     `coverage.json` state `unattributed` (the citation grading
                       report); else `claims.csv` rows with no supporting S-id
  open_reviews         `coverage.json` state `unverifiable`; else `claims.csv` rows
                       whose supporting S-id is absent from `sources.csv`, or whose
                       row is present and not `verification_status=verified`
  citations_unresolved `GATE_REPORT.json` `unresolved` plus `no_identifier`
  retracted_cited      `GATE_REPORT.json` `retracted`
  sources_checked      `GATE_REPORT.json` `checked`; else the `sources.csv` row count
  corpus_docs          the `ledgers/sources_included.csv` row count
  corpus_unreadable    `prisma_counts.json` `not_retrieved`, plus every declared
                       included study the full-text ledger does not show as read

A gate that did not run, or a ledger that is absent, never counts as a condition
met. The citation facts become None, which the definition refuses to assume; an
absent corpus ledger is counted as an unread document. The statement is then
WITHHELD and the blocker is named.

Exit codes (the repository's convention):
  0  the statement is issued
  1  the statement is withheld (at least one condition failed)
  4  input gap -- no --root, no --facts, or tools/attribution.py was not found

Usage:
  python3 skills/sysreview/scripts/manuscript_gate.py --root <review> --out block.md
  python3 skills/sysreview/scripts/manuscript_gate.py --facts facts.json --json gate.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


def _load_attribution():
    """Import tools/attribution.py by walking up from this script. None if absent."""
    here = Path(__file__).resolve()
    for base in here.parents:
        candidate = base / "tools" / "attribution.py"
        if candidate.is_file():
            sys.path.insert(0, str(candidate.parent))
            import attribution  # noqa: E402
            return attribution
    return None


def _read_json(path):
    """The parsed JSON, or None when the artifact is absent or unreadable."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _rows(path):
    """CSV data rows, or None when the ledger is absent or unreadable."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))
    except (OSError, csv.Error):
        return None


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _split_ids(cell):
    """The supporting S-ids in one claims.csv cell, comma-separated and quoted."""
    return [part.strip().strip('"').strip("'")
            for part in (cell or "").split(",") if part.strip()]


def _prisma_counts(prisma):
    """The flat `not_retrieved` and `included_studies`, from either accepted shape."""
    if not isinstance(prisma, dict):
        return None, None
    not_retrieved = prisma.get("not_retrieved")
    included = prisma.get("included_studies")
    if not_retrieved is None:
        retrieval = prisma.get("retrieval")
        if isinstance(retrieval, dict):
            not_retrieved = retrieval.get("reports_not_retrieved")
    if included is None:
        box = prisma.get("included")
        if isinstance(box, dict):
            included = box.get("studies_included")
    return _as_int(not_retrieved) if not_retrieved is not None else None, \
        _as_int(included) if included is not None else None


def collect_facts(root):
    """Read the gate results and ledger. Return (facts, where-each-fact-came-from)."""
    root = Path(root)
    facts, where = {}, {}

    # --- citation integrity and retraction: GATE_REPORT.json -----------------
    report = _read_json(root / "GATE_REPORT.json")
    if report is None:
        facts["citations_unresolved"] = None
        facts["retracted_cited"] = None
        where["citations_unresolved"] = ("GATE_REPORT.json is absent: the citation-integrity "
                                         "gate did not run")
        where["retracted_cited"] = ("GATE_REPORT.json is absent: the retraction gate did not run")
    elif report.get("input_gaps") or report.get("status") == "insufficient_evidence":
        # The gate could not ask. A partial check is not a verified condition.
        facts["citations_unresolved"] = None
        facts["retracted_cited"] = None
        where["citations_unresolved"] = ("GATE_REPORT.json is INCOMPLETE (input gaps): the gate "
                                         "could not reach every identifier")
        where["retracted_cited"] = where["citations_unresolved"]
    else:
        unresolved = list(report.get("unresolved") or [])
        no_identifier = list(report.get("no_identifier") or [])
        facts["citations_unresolved"] = len(unresolved) + len(no_identifier)
        facts["retracted_cited"] = len(report.get("retracted") or [])
        where["citations_unresolved"] = "GATE_REPORT.json:unresolved + no_identifier"
        where["retracted_cited"] = "GATE_REPORT.json:retracted"
    if isinstance(report, dict) and isinstance(report.get("checked"), int):
        facts["sources_checked"] = report["checked"]
        where["sources_checked"] = "GATE_REPORT.json:checked"

    # --- passage states: the citation grading report, else the claims ledger --
    grading = _read_json(root / "coverage.json") or _read_json(root / "citation_report.json")
    states = grading.get("states") if isinstance(grading, dict) else None
    if isinstance(states, dict):
        facts["passage_findings"] = _as_int(states.get("unattributed"))
        facts["open_reviews"] = _as_int(states.get("unverifiable"))
        where["passage_findings"] = "coverage.json:states.unattributed"
        where["open_reviews"] = "coverage.json:states.unverifiable"
    else:
        claims = _rows(root / "claims.csv")
        sources = _rows(root / "sources.csv")
        if claims is None:
            # No passage was assessed. One open review is the smallest honest count:
            # the condition "every assessed passage is attributed" was never decided.
            facts["passage_findings"] = 0
            facts["open_reviews"] = 1
            where["passage_findings"] = "no citation grading report and no claims.csv"
            where["open_reviews"] = ("the citation grading gate did not run: no passage was "
                                     "assessed")
        else:
            verified, known = {}, set()
            for row in sources or []:
                sid = (row.get("source_id") or "").strip()
                if not sid:
                    continue
                known.add(sid)
                status = (row.get("verification_status") or "").strip().lower()
                verified[sid] = status in ("verified", "")
            findings = reviews = 0
            have_status = sources is not None and any(
                "verification_status" in row for row in sources)
            for row in claims:
                ids = _split_ids(row.get("supporting_sids"))
                if not ids:
                    findings += 1
                elif sources is not None and any(sid not in known for sid in ids):
                    findings += 1
                elif have_status and any(not verified.get(sid, False) for sid in ids):
                    reviews += 1
            facts["passage_findings"] = findings
            facts["open_reviews"] = reviews
            where["passage_findings"] = ("claims.csv: rows with no supporting S-id, or an S-id "
                                         "absent from sources.csv")
            where["open_reviews"] = ("claims.csv: rows whose source is not "
                                     "verification_status=verified")

    # --- the corpus: the full-text ledger and the PRISMA counts ---------------
    included_rows = _rows(root / "ledgers" / "sources_included.csv")
    prisma = _read_json(root / "prisma_counts.json")
    not_retrieved, declared = _prisma_counts(prisma)
    if declared is None:
        sources = _rows(root / "sources.csv")
        if sources is not None:
            declared = sum(1 for row in sources
                           if (row.get("inclusion_status") or "").strip() == "included")
    facts["corpus_docs"] = len(included_rows) if included_rows is not None else 0
    if included_rows is None:
        # The ledger is absent, so no supplied document is shown as read. Count at
        # least one unread document so the condition is never assumed to hold.
        facts["corpus_unreadable"] = max(not_retrieved or 0, declared or 0, 1)
        where["corpus_docs"] = "ledgers/sources_included.csv is absent"
        where["corpus_unreadable"] = ("ledgers/sources_included.csv is absent: the supplied "
                                      "corpus is not shown as read")
    else:
        facts["corpus_docs"] = len(included_rows)
        facts["corpus_unreadable"] = (not_retrieved or 0) + max(0, (declared or 0) - len(included_rows))
        where["corpus_docs"] = "ledgers/sources_included.csv row count"
        where["corpus_unreadable"] = ("prisma_counts.json:not_retrieved + declared included "
                                      "studies the full-text ledger does not show as read")

    # --- sources checked: the gate count, else the retrieved-record ledger ----
    if "sources_checked" not in facts:
        sources = _rows(root / "sources.csv")
        facts["sources_checked"] = len(sources) if sources is not None else 0
        where["sources_checked"] = ("sources.csv row count" if sources is not None
                                    else "no GATE_REPORT.json and no sources.csv")

    return facts, where


FACT_ORDER = ("passage_findings", "open_reviews", "citations_unresolved", "retracted_cited",
              "sources_checked", "corpus_docs", "corpus_unreadable")


def facts_from_file(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    facts = {key: data.get(key) for key in FACT_ORDER}
    where = {key: "--facts" for key in FACT_ORDER}
    return facts, where


def render(attribution, result):
    """The block: the definition, the statement, and always the scope line.

    The scope is appended when the statement does not carry it (the withheld
    form does not), so the term never appears without its boundary.
    """
    block = attribution.render_block(result)
    if attribution.SCOPE_ANCHOR not in block:
        block = block.rstrip() + "\n\n" + result["scope"] + "\n"
    return block


def main(argv=None):
    ap = argparse.ArgumentParser(description="The sysreview manuscript gate's attribution claim.")
    ap.add_argument("--root", help="the review project directory the gates wrote into")
    ap.add_argument("--facts", "--attribution-evidence", dest="facts",
                    help="a JSON file with the seven facts (skips --root); the alias matches "
                         "the action attribution.py names when a fact was not verified")
    ap.add_argument("--out", help="write the rendered markdown block here")
    ap.add_argument("--json", dest="json_out", help="write the full result as JSON here")
    args = ap.parse_args(argv)

    attribution = _load_attribution()
    if attribution is None:
        print("manuscript_gate: tools/attribution.py not found (input gap, not a pass)",
              file=sys.stderr)
        return 4
    if args.facts:
        try:
            facts, where = facts_from_file(args.facts)
        except (OSError, ValueError) as exc:
            print("manuscript_gate: cannot read --facts: %s (input gap, not a pass)" % exc,
                  file=sys.stderr)
            return 4
    elif args.root:
        if not Path(args.root).is_dir():
            print("manuscript_gate: --root is not a directory: %s (input gap, not a pass)"
                  % args.root, file=sys.stderr)
            return 4
        facts, where = collect_facts(args.root)
    else:
        print("manuscript_gate: supply --root or --facts (input gap, not a pass)",
              file=sys.stderr)
        return 4

    result = attribution.evaluate(**facts)
    block = render(attribution, result)
    print(block)
    if not result["issuable"]:
        print("manuscript_gate: withheld. Run the gate named in each blocker, then re-run. "
              "Each fact and its source are in --json fact_sources.", file=sys.stderr)
    payload = {
        "tool": "sysreview_manuscript_gate",
        "root": args.root,
        "attribution": result,
        "facts": facts,
        "fact_sources": where,
        "block": block,
    }
    if args.out:
        Path(args.out).write_text(block + ("" if block.endswith("\n") else "\n"), encoding="utf-8")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return 0 if result["issuable"] else 1


if __name__ == "__main__":
    sys.exit(main())
