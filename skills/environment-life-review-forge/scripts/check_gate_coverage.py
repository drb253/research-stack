#!/usr/bin/env python3
"""check_gate_coverage.py -- every declared gate must have both fixtures.

A gate that was only ever run on its passing path is not a gate; it is an
assertion. This reads the gate table of SKILL.md, reads selftest.sh, and fails
when a declared gate has no pass fixture (expect_exit 0) or no fail fixture
(expect_exit non-zero).

Exit codes (the repository's convention):
  0  every declared gate has both paths
  1  at least one declared gate is one-sided
  4  input gap -- SKILL.md or selftest.sh is missing (never a pass)

Usage:
  python3 scripts/check_gate_coverage.py --skill . 
  python3 scripts/check_gate_coverage.py --selftest scripts/selftest.sh --skill SKILL.md
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# | G1 | framework | the protocol names a PECO or PICO framework |
GATE_ROW = re.compile(r"^\|\s*(G\d)\s*\|", re.M)
FIXTURE = re.compile(r"expect_exit\s+(\d+)\s+\"([^\"]*)\"")


def declared_gates(skill_md: str):
    text = Path(skill_md).read_text(encoding="utf-8", errors="replace")
    seen, out = set(), []
    for gid in GATE_ROW.findall(text):
        if gid not in seen:
            seen.add(gid)
            out.append(gid)
    return out


def fixtures(selftest: str):
    text = Path(selftest).read_text(encoding="utf-8", errors="replace")
    per: dict = {}
    for code, name in FIXTURE.findall(text):
        for gid in re.findall(r"\bG\d\b", name):
            slot = per.setdefault(gid, {"pass": 0, "fail": 0, "names": []})
            slot["pass" if code == "0" else "fail"] += 1
            slot["names"].append((code, name.strip()))
    return per


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Every declared gate needs a pass and a fail fixture.")
    ap.add_argument("--skill", default="SKILL.md", help="the SKILL.md that declares the gates")
    ap.add_argument("--selftest", default="scripts/selftest.sh")
    args = ap.parse_args(argv)
    for path in (args.skill, args.selftest):
        if not Path(path).exists():
            print("INPUT GAP: %s does not exist (never a pass)" % path, file=sys.stderr)
            return 4
    gates = declared_gates(args.skill)
    if not gates:
        print("INPUT GAP: no gate row (| G1 | ... |) was found in %s" % args.skill, file=sys.stderr)
        return 4
    per = fixtures(args.selftest)
    print("declared gates: %d" % len(gates))
    one_sided = []
    for gid in gates:
        slot = per.get(gid, {"pass": 0, "fail": 0})
        if slot["pass"] and slot["fail"]:
            flag = "OK"
        elif slot["pass"] or slot["fail"]:
            flag = "ONLY"
            one_sided.append((gid, "fail" if slot["fail"] == 0 else "pass"))
        else:
            flag = "NONE"
            one_sided.append((gid, "both paths"))
        print("  %-4s pass=%-2d fail=%-2d  %s" % (gid, slot["pass"], slot["fail"], flag))
    if one_sided:
        print("\nFAIL - %d declared gate(s) are not pinned on both paths:" % len(one_sided))
        for gid, missing in one_sided:
            print("  - %s has no %s fixture; a gate that cannot fail is not a gate." % (gid, missing))
        return 1
    print("OK: every declared gate has a pass fixture and a fail fixture.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
