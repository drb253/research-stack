#!/usr/bin/env python3
"""Machine-enforce the screening-conduct disclosure, and emit a human-confirmation worklist.

An agent-run screen cannot be made human-verified by wishing it so. What CAN be enforced
is that the deliverables never CLAIM human verification they did not have -- the exact
false claim that would make an autonomous review look MECIR-compliant.

Fails when:
  * screening_log.csv shows agent-run decisions but no CONDUCT_DISCLOSURE.txt declares
    the autonomous mode and the extent of human involvement;
  * the manuscript claims independent/human screening, or a Cochrane/MECIR/PRISMA
    compliance that the disclosure does not support.

Also writes screening_human_confirmation.csv -- the concrete worklist of decisions a
human must sign off before the review may be reported as human-conducted.

Exit codes: 0 disclosure consistent; 2 inconsistent; 1 usage error.
"""
import argparse
import csv
import os
import re
import sys

AGENT = re.compile(r"^\s*(agent|ai|llm|model)\b", re.I)
# "not human-screened" / "without independent human screening" are HONEST statements, not
# claims. Without this guard the gate blocks exactly the manuscripts it exists to permit.
NEGATION = re.compile(r"\b(not|no|never|without|non|nor)\b[\s,:-]*$", re.I)

# A claim of human verification, or of compliance that presupposes it.
CLAIMS = [
    r"independent(ly)?\s+(human\s+)?(reviewers|screening|screened)",
    r"two\s+reviewers\s+independently",
    r"human[- ]screened",
    r"dual\s+(human\s+)?screening",
    r"manually\s+screened\s+by\s+(two|both)",
    r"MECIR[- ]compliant",
    r"Cochrane[- ]compliant",
    r"PRISMA[- ]compliant",
]


def _rows(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def check(root):
    probs = []
    log = _rows(os.path.join(root, "screening_log.csv"))
    if not log:
        return ["no screening_log.csv found -- cannot verify what conducted the screening"], []

    agent_rows = [r for r in log
                  if AGENT.match((r.get("verifier") or r.get("reviewer") or r.get("auditor") or "")
                                 .strip())]
    # A log with no verifier column at all is treated as agent-run (the conservative read).
    has_verifier = any("verifier" in r or "reviewer" in r for r in log)
    agent_run = bool(agent_rows) or not has_verifier

    disc_path = os.path.join(root, "CONDUCT_DISCLOSURE.txt")
    disc = ""
    if os.path.exists(disc_path):
        disc = open(disc_path, encoding="utf-8").read()
    disc_low = disc.lower()

    if agent_run:
        if not disc:
            probs.append("DISCLOSURE: the screening log shows agent-run decisions but there is no "
                         "CONDUCT_DISCLOSURE.txt.")
        else:
            if "mode: autonomous" not in disc_low:
                probs.append("DISCLOSURE: agent-run screening without 'mode: autonomous'.")
            if "human_involvement:" not in disc_low:
                probs.append("DISCLOSURE: no 'human_involvement:' line -- the reader cannot tell "
                             "how much of this was human.")
        ms = os.path.join(root, "manuscript.md")
        text = open(ms, encoding="utf-8").read() if os.path.exists(ms) else ""
        for pat in CLAIMS:
            for m in re.finditer(pat, text, re.I):
                before = text[max(0, m.start() - 30):m.start()]
                if NEGATION.search(before):
                    continue        # an honest denial is not a claim
                probs.append("FALSE CLAIM: manuscript says %r while screening was agent-run."
                             % m.group(0))

    worklist = [{"record_id": r.get("record_id", ""), "decision": r.get("decision", ""),
                 "rule": r.get("rule", ""), "confidence": r.get("confidence", ""),
                 "requires_human_confirmation": "yes"}
                for r in log]
    return probs, worklist


def main(argv=None):
    ap = argparse.ArgumentParser(description="Enforce the screening-conduct disclosure.")
    ap.add_argument("--root", default=".")
    ap.add_argument("--worklist", default="screening_human_confirmation.csv")
    args = ap.parse_args(argv)

    probs, worklist = check(args.root)
    if worklist:
        path = os.path.join(args.root, args.worklist)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(worklist[0].keys()))
            w.writeheader()
            w.writerows(worklist)
        print("human-confirmation worklist -> %s (%d decisions)" % (path, len(worklist)))
    if probs:
        print("FAIL - screening-conduct disclosure is inconsistent (%d problem(s)):" % len(probs))
        for p in probs:
            print("  - %s" % p)
        return 2
    print("OK - the disclosure matches what actually conducted the screening")
    return 0


if __name__ == "__main__":
    sys.exit(main())
