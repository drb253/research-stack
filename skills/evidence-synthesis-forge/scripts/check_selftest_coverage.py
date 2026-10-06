#!/usr/bin/env python3
"""Verification of the verification: every gate must be exercised on BOTH paths.

A gate that has only ever been run on its passing path is not a gate -- it is an
assertion. This reads selftest.sh, groups each `expect_exit <code> "<name>" <cmd>` by the
script it invokes, and fails if any gate script is never exercised with a NON-ZERO
expectation (its fail path) or never with a zero one (its pass path).

Exit codes: 0 every gate has both paths; 2 a gate has only one; 1 usage error.
"""
import argparse
import collections
import os
import re
import sys

CALL = re.compile(r"expect_exit\s+(\d+)\s+\"([^\"]+)\"\s+(.*?)(?=\n\s*(?:expect_exit|if |echo|printf|fi|mkdir|cat |Rscript|python3)\b|\Z)",
                  re.S)
SCRIPT = re.compile(r"([\w./-]+\.(?:py|R|sh))")


def coverage(selftest_path):
    text = open(selftest_path, encoding="utf-8").read()
    per = collections.defaultdict(lambda: {"pass": 0, "fail": 0, "names": []})
    for code, name, body in CALL.findall(text):
        m = SCRIPT.search(body)
        if not m:
            continue
        key = os.path.basename(m.group(1))
        per[key]["pass" if code == "0" else "fail"] += 1
        per[key]["names"].append((code, name.strip()))
    return per


# A gate that is itself a meta-suite cannot have a one-line fail fixture; it is
# exercised by running the fixtures it owns. Each exemption needs a written reason.
EXEMPT = {
    "regression_suite.py":
        "meta-suite: it runs one fixture per defect class and fails if any stops being "
        "caught, so its own fail path is exercised by breaking a gate, not by a CLI flag",
    "check_selftest_coverage.py":
        "meta-gate: this script; its fail path is exercised by removing a fixture from "
        "selftest.sh, which cannot be done from inside the suite it is checking",
}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Every gate must have a pass and a fail fixture.")
    ap.add_argument("--selftest", required=True)
    args = ap.parse_args(argv)
    if not os.path.exists(args.selftest):
        print("ERROR: not found: %s" % args.selftest, file=sys.stderr)
        return 1

    per = coverage(args.selftest)
    one_sided = []
    for script, c in sorted(per.items()):
        if c["pass"] == 0 or c["fail"] == 0:
            if script not in EXEMPT:
                one_sided.append((script, c))

    print("gate scripts exercised by %s: %d" % (os.path.basename(args.selftest), len(per)))
    for script, c in sorted(per.items()):
        if script in EXEMPT and (c["pass"] == 0 or c["fail"] == 0):
            flag = "EXEMPT"
        elif c["pass"] and c["fail"]:
            flag = "OK"
        else:
            flag = "ONLY"
        print("  %-38s pass=%-2d fail=%-2d  %s" % (script, c["pass"], c["fail"], flag))
    if EXEMPT:
        print("\nexemptions (each justified, not silently skipped):")
        for k, v in sorted(EXEMPT.items()):
            print("  - %s: %s" % (k, v))
    if one_sided:
        print("\nFAIL - %d gate(s) are exercised on only one path:" % len(one_sided))
        for script, c in one_sided:
            missing = "fail" if c["fail"] == 0 else "pass"
            print("  - %s has no %s-path fixture; a gate that cannot fail is not a gate."
                  % (script, missing))
        return 2
    print("\nOK - every gate script has both a pass and a fail fixture (or a justified exemption)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
