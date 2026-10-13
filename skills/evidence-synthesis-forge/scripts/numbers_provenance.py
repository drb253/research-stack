#!/usr/bin/env python3
"""Numeric-provenance checker -- the "no number without provenance" gate (stdlib only).

Scans a draft for numeric claims and verifies each one appears in the review's own
computed artifacts (results.json, model outputs, tables). Any number in the draft that
CANNOT be traced to an artifact is flagged: it was not computed by the analysis, so it
must not appear in a deliverable.

By default only decimal numbers are checked (they are the effect sizes, CIs, I^2, p --
the ones that must be computed). Use --include-integers to also audit whole numbers
(expect false positives from citation markers, years and section numbers).

Usage:
  python3 numbers_provenance.py --draft results_section.md \
      --artifacts out/results.json out/models.csv out/sof_table.md \
      [--include-integers] [--allow '^20\\d\\d$']

Exit 0 = every checked number is traceable; 2 = at least one unaudited number.
"""
import argparse
import os
import re
import sys

NUM = re.compile(r"(?<![\w.\-])(-?\d+(?:\.\d+)?)(?![\w])")


def decimals(tok):
    return len(tok.split(".", 1)[1]) if "." in tok else 0


def numbers(text):
    return [m.group(1) for m in NUM.finditer(text)]


def to_floats(text):
    out = []
    for t in numbers(text):
        try:
            out.append(float(t))
        except ValueError:
            pass
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check every draft number against computed artifacts.")
    ap.add_argument("--draft", required=True, help="the draft section to audit")
    ap.add_argument("--artifacts", nargs="+", required=True, help="computed outputs to check against")
    ap.add_argument("--include-integers", action="store_true")
    ap.add_argument("--allow", default=None, help="regex; matching tokens are ignored")
    ap.add_argument("--allow-incomplete", action="store_true",
                    help="proceed when a supplied artifact could not be read. The input gap is "
                         "still reported, so the override is logged rather than silent.")
    args = ap.parse_args(argv)

    # An unreadable input is not a finding about the draft. This used to be ap.error() -> exit 2,
    # the same code a genuine untraceable number gets.
    if not os.path.exists(args.draft):
        print("insufficient_input: the draft could not be read: %s" % args.draft)
        print("  nothing was checked, so this is not a finding about the draft")
        return 4

    allowed = []
    missing = []
    for a in args.artifacts:
        if not os.path.exists(a):
            # Skipping it with a warning and then printing "every checked number is traceable"
            # is the failure this repository exists to prevent: the artifact set was incomplete,
            # so the check covered less than it says it did.
            missing.append(a)
            continue
        with open(a, encoding="utf-8", errors="ignore") as fh:
            allowed += to_floats(fh.read())

    if not allowed:
        print("insufficient_evidence: no numbers could be read from the supplied artifacts")
        print("  nothing was checked against, so no statement about the draft's numbers is possible")
        if missing:
            print("  not read (%d):" % len(missing))
            for a in missing:
                print("    - %s" % a)
        print("  action: supply the computed artifacts, then re-run")
        return 3

    allow_re = re.compile(args.allow) if args.allow else None
    with open(args.draft, encoding="utf-8", errors="ignore") as fh:
        draft = fh.read()

    checked = 0
    unaudited = []
    for tok in numbers(draft):
        if allow_re and allow_re.search(tok):
            continue
        k = decimals(tok)
        if k == 0 and not args.include_integers:
            continue
        val = float(tok)
        checked += 1
        if not any(round(a, k) == round(val, k) for a in allowed):
            unaudited.append(tok)

    print("numeric provenance: %d number(s) checked against %d artifact value(s)."
          % (checked, len(allowed)))
    if missing:
        print("insufficient_evidence: %d supplied artifact(s) could not be read, so this check "
              "does NOT cover them:" % len(missing))
        for a in missing:
            print("  - %s" % a)
        print("  action: supply these artifacts and re-run; the numbers they contain were never "
              "compared against the draft")
    if unaudited:
        print("UNAUDITED NUMBERS (not traceable to any artifact):")
        for u in dict.fromkeys(unaudited):
            print("  -", u)
        print("Every such number must be computed or removed before this draft is reported.")
        return 2 if not missing else 3
    if missing and not args.allow_incomplete:
        # The findings are clean for what was read; the run is still not a pass, because part of
        # the comparison never happened.
        return 3
    if missing:
        print("  --allow-incomplete given: the unread artifact(s) stay reported above")
    print("OK: every checked number is traceable to a computed artifact.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
