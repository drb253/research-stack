#!/usr/bin/env python3
"""claim_guard.py -- refuse an absolute claim about a bounded measurement.

The skills measure bounded things. "No overlap found against the sources
checked" is a result. "Plagiarism-free" is not: it is a universal negative that
no check can establish, because the corpus the tool did not see is unbounded.
The same is true of "error-free", "perfect" and "medical grade".

This gate makes the overclaim impossible to ship. It reads text (a report, a
skill, a README) and fails when:

  1. an absolute claim appears at all (FORBIDDEN), or
  2. a clean result is reported without the sentence that bounds it
     (UNBOUNDED).

It is deliberately blunt: a false positive here costs a rewording, and a false
negative ships a claim the measurement does not support.

Exit codes (the repository's convention):
  0  no finding
  1  at least one finding
  4  input gap -- no input (never a pass)

Usage:
  python3 tools/claim_guard.py report.md skills/*/SKILL.md
  python3 tools/claim_guard.py --json out.json README.md
  python3 tools/claim_guard.py --self-test
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Claims no bounded measurement can support.
FORBIDDEN = [
    (r"plagiari[sz]m[\s-]?free",
     "use the defined form: add the definition, the scope and the exception "
     "(python3 tools/attribution.py --definition)"),
    (r"\berror[\s-]?free\b", "say the measured error rate and the classes tested"),
    (r"\bperfect(?:ly)?\b", "state the measured result, not a judgement"),
    (r"\bmedical[\s-]?grade\b", "regulatory status is not a code property"),
    (r"\bcertified?\b", "nothing here certifies; name the check that passed"),
    (r"\bclearance\b", "a clean report is not a clearance"),
    (r"\bguarantee[ds]?\b", "a guarantee needs a bound and a population"),
    (r"\bflawless\b", "state the measured result"),
    (r"\bbulletproof\b", "state the measured result"),
    (r"\b100%\s*(?:accurate|correct|reliable)\b", "give the n, the CI and the classes tested"),
    (r"\bproves? (?:that )?(?:it|the tool) (?:is )?(?:correct|safe)\b", "a test bounds an error rate"),
]

# A clean result must carry one of these bounds.
CLEAN_RESULT = [
    r"\bno (?:overlap|match(?:es)?|passage|finding)s? (?:was|were|is|are)? ?(?:found|detected|above)\b",
    r"\bclean report\b",
    r"\b0 findings\b",
    r"\ball checks? passed\b",
    r"\bnothing was flagged\b",
    r"\bno (?:defect|error)s? (?:was|were) found\b",
]

BOUND = [
    r"against the sources? (?:checked|supplied|read)",
    r"not a clearance",
    r"is not a clearance",
    r"cannot certify",
    r"does not cover",
    r"is not covered",
    r"known limitation",
    r"bounded by",
    r"on the (?:classes|set|cases) tested",
    r"measured on",
    r"input gap",
    r"could not be (?:read|checked|resolved)",
    r"not (?:a )?(?:claim|guarantee|proof)",
    r"limitations",
]

FORBIDDEN_RE = [(re.compile(p, re.I), why) for p, why in FORBIDDEN]
CLEAN_RE = [re.compile(p, re.I) for p in CLEAN_RESULT]
BOUND_RE = [re.compile(p, re.I) for p in BOUND]

# "This is not a clearance" is the sentence the gate wants, not a violation.
NEGATION = re.compile(r"(?i)\b(?:not|no|never|without|cannot|can't|isn't|aren't|doesn't)\b[^.]{0,24}$")


def _negated(line, start):
    return bool(NEGATION.search(line[max(0, start - 30):start]))


def _strip_code(text):
    out, fence = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        out.append("" if fence else line)
    return "\n".join(out)


def _defined_attribution(text):
    """True when the text carries the whole definition of the term.

    "Plagiarism-free" is a universal negative on its own, and this gate refuses
    it. With its definition, its scope and its one exception attached it is a
    defined, auditable claim, and the reader can see the boundary. The three
    anchors live in tools/attribution.py so the wording cannot drift.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from attribution import DEFINITION_ANCHOR, SCOPE_ANCHOR, EXCEPTION_ANCHOR
    except Exception:
        return False
    return all(anchor in text for anchor in (DEFINITION_ANCHOR, SCOPE_ANCHOR, EXCEPTION_ANCHOR))


def scan(text, where="<text>"):
    """Return a list of findings: {kind, rule, line, message}."""
    body = _strip_code(text)
    defined = _defined_attribution(body)
    findings = []
    for i, line in enumerate(body.splitlines(), start=1):
        if line.strip().startswith("<!--") or line.lstrip().startswith("# ste-allow"):
            continue
        for pattern, why in FORBIDDEN_RE:
            m = pattern.search(line)
            if not m or _negated(line, m.start()):
                continue
            # The defined term is allowed; the bare phrase is not.
            if pattern.pattern.startswith(r"plagiari[sz]m") and defined:
                continue
            findings.append({
                "kind": "FORBIDDEN", "rule": pattern.pattern, "line": i,
                "message": "'%s' -- %s" % (m.group(0), why), "where": where,
            })
    clean_hit = None
    for pattern in CLEAN_RE:
        m = pattern.search(body)
        if m:
            clean_hit = m
            break
    if clean_hit and not any(p.search(body) for p in BOUND_RE):
        line = body[:clean_hit.start()].count("\n") + 1
        findings.append({
            "kind": "UNBOUNDED", "rule": "clean-result-without-bound", "line": line,
            "message": "a clean result is reported without its bound: add what was checked "
                       "and state that it is not a clearance",
            "where": where,
        })
    return findings


SELF_TEST = [
    ("The tool is plagiarism-free.\n", True),
    ("No overlap was found against the sources checked. This is not a clearance.\n", False),
    ("No overlap was found.\n", True),
    ("The report is error-free.\n", True),
    ("All checks passed on the 186 labelled cases; limitations are in section 5.\n", False),
    ("Medical grade performance.\n", True),
    ("The tool proves that it is correct.\n", True),
    ("Nothing was flagged. The corpus could not be read, so this is an input gap.\n", False),
    # A quoted example inside code must not trip the gate.
    ("```\nThe tool is plagiarism-free.\n```\n", False),
]

# The defined term is allowed; the same words without the definition, the scope and
# the exception are not. Both directions are pinned here.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from attribution import DEFINITION, G4_EXCEPTION, SCOPE_ANCHOR  # noqa: E402

    _DEFINED_TEXT = ("\n".join(DEFINITION) + "\n\n" + SCOPE_ANCHOR +
                     " 5 source(s) checked; 3 supplied document(s) read; 0 document(s) could not "
                     "be read; " + G4_EXCEPTION + ".\n\n"
                     "The draft is plagiarism-free (against the sources checked).\n")
    SELF_TEST.append((_DEFINED_TEXT, False))
    # The definition without its scope is still the bare claim.
    SELF_TEST.append(("\n".join(DEFINITION) + "\n\nThe draft is plagiarism-free.\n", True))
except Exception:  # pragma: no cover - the gate must still run standalone
    pass


def self_test():
    failures = []
    for i, (text, expect) in enumerate(SELF_TEST):
        got = bool(scan(text))
        if got != expect:
            failures.append("case %d: expected finding=%s, got %s" % (i, expect, got))
    for msg in failures:
        print("FAIL  %s" % msg)
    print("claim_guard self-test: %d checks, %d failed" % (len(SELF_TEST), len(failures)))
    return 1 if failures else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.paths:
        print("claim_guard: no input files (input gap, not a pass)", file=sys.stderr)
        return 4
    findings = []
    for p in args.paths:
        path = Path(p)
        if not path.is_file():
            continue
        findings += scan(path.read_text(encoding="utf-8", errors="replace"), where=str(path))
    for f in findings:
        print("%-10s %-46s line %-4d %s" % (f["kind"], f["where"], f["line"], f["message"]))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps({"findings": findings}, indent=1), encoding="utf-8")
    print("claim_guard: %d finding(s)" % len(findings))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
