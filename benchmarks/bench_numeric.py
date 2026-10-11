#!/usr/bin/env python3
"""Labelled benchmark for the medical-narrative-review arithmetic gate (check_numbers.py).

Deterministic and offline. Each case is a one-claim manuscript with a known label:
  should_fail = True   -> the gate MUST report at least one error (a real defect)
  should_fail = False  -> the gate MUST report zero errors (no false alarm)

Measures sensitivity (defects caught) and specificity (clean text left clean),
with Wilson 95% intervals, plus a per-rule breakdown.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GATE = REPO / "skills/medical-narrative-review/scripts/check_numbers.py"
PY = sys.executable

# (id, manuscript text, should_fail, category)
CASES = [
    # ---- correct statements: must stay clean ------------------------------
    ("ok-pct-basic",     "We included 45/120 (37.5%) of records.",                  False, "percentage"),
    ("ok-pct-quarter",   "A subset of 10/40 (25.0%) reported it.",                  False, "percentage"),
    ("ok-pct-zero",      "None of 0/50 (0.0%) responded.",                          False, "percentage"),
    ("ok-pct-full",      "All of 50/50 (100.0%) responded.",                        False, "percentage"),
    ("ok-ci-contains",   "The estimate was 1.25 (95% CI 1.05 to 1.48).",            False, "interval"),
    ("ok-ci-negative",   "The estimate was -0.40 (95% CI -0.80 to -0.10).",         False, "interval"),
    ("ok-sig-consistent",   "The effect was significantly higher (p = 0.01).",      False, "significance"),
    ("ok-nonsig-consistent","The effect was not significantly higher (p = 0.40).",  False, "significance"),
    ("ok-plain-prose",   "The intervention reduced length of stay.",                False, "prose"),

    # ---- injected defects: must be caught ---------------------------------
    ("bad-pct-high",     "We included 45/120 (40.0%) of records.",                  True,  "percentage"),
    ("bad-pct-low",      "We included 45/120 (30.0%) of records.",                  True,  "percentage"),
    ("bad-pct-subset",   "A subset of 10/40 (50.0%) reported it.",                  True,  "percentage"),
    ("bad-ci-excludes",  "The estimate was 1.25 (95% CI 1.30 to 1.48).",            True,  "interval"),
    ("bad-ci-excludes2", "The estimate was 0.80 (95% CI 0.10 to 0.50).",            True,  "interval"),
    ("bad-sig-vs-p",     "The effect was significantly higher (p = 0.40).",         True,  "significance"),
    ("bad-nonsig-vs-p",  "The effect was not significantly higher (p = 0.001).",    True,  "significance"),
    # The same contradiction with the p-value wrapped onto the next line.
    # Measured separately because it is a known coverage gap, not a pass.
    ("bad-sig-crossline", "The effect was significantly higher\n(p = 0.40).",       True,  "significance-crossline"),
]


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def run_case(text: str):
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(text + "\n")
        path = fh.name
    p = subprocess.run([PY, str(GATE), path], capture_output=True, text=True)
    try:
        payload = json.loads(p.stdout)
    except json.JSONDecodeError:
        return None, []
    errors = [i for i in payload.get("issues", []) if i.get("severity") == "error"]
    return payload.get("status"), [i.get("code") for i in errors]


def main():
    rows, tp, fn, tn, fp = [], 0, 0, 0, 0
    for cid, text, should_fail, category in CASES:
        status, codes = run_case(text)
        caught = bool(codes)
        correct = (caught == should_fail)
        if should_fail and caught:
            tp += 1
        elif should_fail and not caught:
            fn += 1
        elif not should_fail and caught:
            fp += 1
        else:
            tn += 1
        rows.append({"id": cid, "category": category, "should_fail": should_fail,
                     "status": status, "errors": ";".join(codes), "caught": caught,
                     "correct": correct})

    print("=== ARITHMETIC GATE (check_numbers.py) — LABELLED BENCHMARK ===\n")
    print(f"  {'case':22s} {'expect':7s} {'caught':7s} {'verdict':8s} codes")
    print("  " + "-" * 78)
    for r in rows:
        exp = "fail" if r["should_fail"] else "clean"
        got = "yes" if r["caught"] else "no"
        print(f"  {r['id']:22s} {exp:7s} {got:7s} "
              f"{'CORRECT' if r['correct'] else 'WRONG':8s} {r['errors'] or '-'}")

    sens = tp / (tp + fn) if (tp + fn) else float("nan")
    spec = tn / (tn + fp) if (tn + fp) else float("nan")
    acc = (tp + tn) / len(rows)
    ls, hs = wilson(tp, tp + fn)
    lp, hp = wilson(tn, tn + fp)
    la, ha = wilson(tp + tn, len(rows))

    print(f"\n  injected defects caught (sensitivity) : {tp}/{tp+fn} = {sens:.1%}"
          f"  95% CI [{ls:.1%}, {hs:.1%}]")
    print(f"  clean text left clean  (specificity)  : {tn}/{tn+fp} = {spec:.1%}"
          f"  95% CI [{lp:.1%}, {hp:.1%}]")
    print(f"  overall agreement                     : {tp+tn}/{len(rows)} = {acc:.1%}"
          f"  95% CI [{la:.1%}, {ha:.1%}]")

    print("\n  by category:")
    cats = {}
    for r in rows:
        c = cats.setdefault(r["category"], [0, 0])
        c[0] += 1
        c[1] += int(r["correct"])
    for c, (n, ok) in sorted(cats.items()):
        print(f"    {c:24s} {ok}/{n}")

    Path("/tmp/bench/numeric_scored.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print("\n  detail -> /tmp/bench/numeric_scored.json")


if __name__ == "__main__":
    main()
