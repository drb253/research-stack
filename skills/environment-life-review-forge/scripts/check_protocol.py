#!/usr/bin/env python3
"""check_protocol.py -- the protocol gate for environment-life-review-forge.

The skill declares eight gates over a review protocol. This script decides each
gate mechanically, so a protocol that is missing a framework, an exposure, an
outcome unit, an eligible design, a heterogeneity source, an appraisal tool, a
synthesis mode, or a pooling rationale fails before any review work starts.

Input shapes (both accepted):
  * JSON -- an object with the keys below;
  * Markdown -- "Key: value" lines, or the "| Key | value |" table of
    templates/peco-framework.md.

Keys: framework, population, exposure (or intervention), comparator, outcomes,
units, designs, heterogeneity, risk_of_bias (or appraisal), synthesis,
comparability.

Exit codes (the repository's convention):
  0  every declared gate passes
  1  at least one gate fails (a finding)
  4  input gap -- the protocol file is missing, empty, or unreadable
     (never a pass, and never a result)

Usage:
  python3 scripts/check_protocol.py --input protocol.json
  python3 scripts/check_protocol.py --input protocol.md --json out.json
  python3 scripts/check_protocol.py --self-test
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# The declared gates. The id, the name and the rule are the contract the skill
# documents; selftest.sh pins one pass fixture and one fail fixture per gate.
GATES = [
    ("G1", "framework", "the protocol names a PECO or PICO framework"),
    ("G2", "exposure", "the protocol names the exposure or the intervention"),
    ("G3", "outcome", "the outcome families carry a unit"),
    ("G4", "design", "the protocol names the eligible study designs"),
    ("G5", "heterogeneity", "the protocol names a heterogeneity source"),
    ("G6", "appraisal", "the protocol names a risk-of-bias or quality tool"),
    ("G7", "synthesis", "the synthesis mode is narrative, evidence map, or meta-analysis"),
    ("G8", "pooling", "a meta-analysis plan carries a comparability rationale"),
]

SYNTHESIS_MODES = ("narrative", "evidence map", "meta-analysis")


def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")


def _text(value) -> str:
    """Flatten a scalar or a list into one trimmed string."""
    if isinstance(value, (list, tuple)):
        return "; ".join(str(v).strip() for v in value if str(v).strip())
    if value is None:
        return ""
    return str(value).strip()


def parse_markdown(text: str) -> dict:
    """Read "Key: value" lines and "| Key | value |" rows into one mapping."""
    data: dict = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 2 and not set("".join(cells)) <= set("-: "):
                key, value = cells[0], " ".join(c for c in cells[1:] if c)
                if key and value:
                    data.setdefault(_norm_key(key), value)
            continue
        m = re.match(r"^([A-Za-z][A-Za-z0-9 _/-]*):\s*(.+)$", line)
        if m:
            data.setdefault(_norm_key(m.group(1)), m.group(2).strip())
    return data


def load_protocol(path: str):
    """Return (data, gap_reason). A gap is never a result."""
    p = Path(path)
    if not p.exists():
        return None, "the protocol file does not exist: %s" % path
    if p.is_dir():
        return None, "the input path is a directory, not a protocol file: %s" % path
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, "the protocol file could not be read: %s" % exc
    if not text.strip():
        return None, "the protocol file is empty: %s" % path
    stripped = text.lstrip()
    if p.suffix.lower() == ".json" or stripped.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError as exc:
            return None, "the protocol file is not valid JSON: %s" % exc
        if not isinstance(data, dict):
            return None, "the JSON root is not an object: %s" % path
        return data, None
    data = parse_markdown(text)
    if not data:
        return None, "no protocol field was found in the file: %s" % path
    return data, None


def evaluate(data: dict):
    """Return [(gate_id, name, ok, detail), ...] for every declared gate."""
    results = []

    framework = _text(data.get("framework")).lower()
    results.append(("G1", "framework", framework in ("peco", "pico"),
                    "framework=%s" % (framework or "none")))

    exposure = _text(data.get("exposure")) or _text(data.get("intervention"))
    results.append(("G2", "exposure", bool(exposure),
                    "exposure=%s" % (exposure[:60] or "none")))

    outcomes = _text(data.get("outcomes")) or _text(data.get("outcome"))
    units = _text(data.get("units")) or _text(data.get("outcome_units"))
    results.append(("G3", "outcome", bool(outcomes) and bool(units),
                    "outcomes=%s units=%s" % (outcomes[:40] or "none", units[:30] or "none")))

    designs = _text(data.get("designs")) or _text(data.get("design"))
    results.append(("G4", "design", bool(designs),
                    "designs=%s" % (designs[:60] or "none")))

    heterogeneity = _text(data.get("heterogeneity")) or _text(data.get("moderators"))
    results.append(("G5", "heterogeneity", bool(heterogeneity),
                    "heterogeneity=%s" % (heterogeneity[:60] or "none")))

    appraisal = (_text(data.get("risk_of_bias")) or _text(data.get("appraisal"))
                 or _text(data.get("quality_tool")))
    results.append(("G6", "appraisal", bool(appraisal),
                    "appraisal=%s" % (appraisal[:60] or "none")))

    synthesis = _text(data.get("synthesis")).lower()
    results.append(("G7", "synthesis", synthesis in SYNTHESIS_MODES,
                    "synthesis=%s" % (synthesis or "none")))

    # G8 applies only to a pooling plan. A narrative review needs no rationale.
    if synthesis == "meta-analysis":
        comparability = _text(data.get("comparability")) or _text(data.get("pooling_rationale"))
        ok = bool(comparability)
        detail = "comparability=%s" % (comparability[:60] or "none")
    else:
        ok = True
        detail = "not a pooling plan (synthesis=%s)" % (synthesis or "none")
    results.append(("G8", "pooling", ok, detail))
    return results


def report(results, json_out=None):
    failed = [r for r in results if not r[2]]
    for gid, name, ok, detail in results:
        print("%-4s %-4s %-14s %s" % ("PASS" if ok else "FAIL", gid, name, detail))
    print("RESULT: %d gates, %d passed, %d failed"
          % (len(results), len(results) - len(failed), len(failed)))
    if json_out:
        payload = {
            "status": "pass" if not failed else "fail",
            "gates": [{"id": g, "name": n, "status": "pass" if ok else "fail", "detail": d}
                      for g, n, ok, d in results],
            "failed": [g for g, _n, ok, _d in results if not ok],
        }
        Path(json_out).write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return 1 if failed else 0


VALID = {
    "framework": "PECO",
    "population": "dryland soil fauna",
    "exposure": "ant and termite activity",
    "comparator": "fauna exclusion",
    "outcomes": "soil organic carbon stock",
    "units": "g C per kg soil",
    "designs": "field exclusion experiment; paired site comparison",
    "heterogeneity": "climate zone; soil texture; baseline carbon",
    "risk_of_bias": "SYRCLE-style internal validity checklist",
    "synthesis": "meta-analysis",
    "comparability": "one carbon-stock unit per study after a documented conversion",
}


def self_test() -> int:
    checks, failures = 0, []
    base = evaluate(dict(VALID))
    checks += 1
    if [g for _g, _n, ok, _d in base if not ok]:
        failures.append("the valid protocol did not pass every gate")

    # Every gate must be able to fail. Drop the field it reads and check the gate.
    drop = {
        "G1": "framework", "G2": "exposure", "G3": "units", "G4": "designs",
        "G5": "heterogeneity", "G6": "risk_of_bias", "G7": "synthesis",
        "G8": "comparability",
    }
    for gid, key in drop.items():
        checks += 1
        data = dict(VALID)
        data.pop(key, None)
        status = {g: ok for g, _n, ok, _d in evaluate(data)}
        if status.get(gid):
            failures.append("%s passed without its field '%s'" % (gid, key))

    # A non-pooling plan must not fail G8.
    checks += 1
    data = dict(VALID)
    data["synthesis"] = "narrative"
    data.pop("comparability", None)
    if not {g: ok for g, _n, ok, _d in evaluate(data)}["G8"]:
        failures.append("G8 failed for a narrative review with no pooling plan")

    # Markdown input must reach the same verdict as JSON input.
    checks += 1
    md = "\n".join("| %s | %s |" % (k.replace("_", " ").title(), v) for k, v in VALID.items())
    if [g for _g, _n, ok, _d in evaluate(parse_markdown(md)) if not ok]:
        failures.append("the markdown table shape did not pass every gate")

    # A gap must never be returned as data.
    checks += 1
    data, gap = load_protocol("/nonexistent/protocol-does-not-exist.json")
    if data is not None or not gap:
        failures.append("a missing file was not reported as an input gap")

    for msg in failures:
        print("FAIL  %s" % msg)
    print("check_protocol self-test: %d checks, %d failed" % (checks, len(failures)))
    return 1 if failures else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="The environment-life-review-forge protocol gate.")
    ap.add_argument("--input", help="the protocol file to check")
    ap.add_argument("--json", dest="json_out", help="write the gate report to this file")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.input:
        print("check_protocol: no --input given (input gap, not a pass)", file=sys.stderr)
        return 4
    data, gap = load_protocol(args.input)
    if gap:
        print("INPUT GAP: %s" % gap, file=sys.stderr)
        return 4
    return report(evaluate(data), args.json_out)


if __name__ == "__main__":
    sys.exit(main())
