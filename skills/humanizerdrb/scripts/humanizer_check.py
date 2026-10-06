#!/usr/bin/env python3
"""Mechanical checks for /humanizerdrb (stdlib only, no network, no dependencies).

Runs the machine-checkable subset of eval.md on a before/after pair:

  H1  no added content  -- a number in the rewrite that is not in the original
  H2  no dropped claim  -- a number in the original that is missing from the rewrite
  H4  no new AI tells   -- chat leftovers / method narration introduced by the rewrite

Plus a heuristic sweep for named patterns from references/patterns.md, reported as
warnings (fix-or-flag). A warning is not a verdict: one weak tell is not proof.

What this CANNOT do, and must never be read as doing:
  * judge meaning, voice, or whether a claim survived in different words;
  * score "AI-ness" or predict any AI detector;
  * replace the editorial judgement in eval.md.

Usage:
  python3 humanizer_check.py --before draft_v1.md --after draft_v2.md
  python3 humanizer_check.py --before a.md --after b.md --json

Exit codes: 0 no hard error; 2 hard error (H1/H2/H4); 1 usage error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- H1 / H2 ---
NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?%?(?![\w])")


def numbers(text: str) -> set[str]:
    """Normalised numeric tokens ('1,000' -> '1000'), so formatting is not a diff."""
    return {m.group(0).replace(",", "").rstrip("%") for m in NUMBER.finditer(text)}


# --------------------------------------------------------------- patterns ---
EMDASH = "\u2014"
# (label, regex, is_hard_when_new)
PATTERNS = [
    ("chat leftover", r"\b(As an AI|I hope this helps|Let me know if|Feel free to|"
                      r"I'd be happy to|Hope this helps)\b", True),
    ("method narration", r"\b(This (section|article) will (explore|discuss|cover)|"
                         r"In this (section|article),? we)\b", True),
    ("throat-clearing opener", r"(?m)^\s*(Here's the thing|Let me be clear|"
                               r"What nobody tells you|At its core|It's worth noting)", False),
    ("importance puffery", r"\b(a testament to|marks a pivotal moment|"
                           r"plays a (vital|crucial|key) role|stands as a)\b", False),
    ("weasel attribution", r"\b(experts agree|studies show|research shows|"
                           r"many believe|it is widely (known|believed))\b", False),
    ("summary-recap ending", r"(?m)^\s*(In conclusion|Ultimately|In summary|"
                             r"To sum up|All in all)\b", False),
    ("trailing -ing clause", r",\s+(highlighting|underscoring|showcasing|emphasizing|"
                             r"reflecting|demonstrating|illustrating|signaling|cementing)\b", False),
    ("dramatic fragment", r"That's it\.\s*That's the whole thing", False),
    ("binary contrast", r"\b(is|are|was|were)n't\b[^.!?]{0,80}[.!?]\s*(It|That|This)('s| is| was)\b", False),
    ("colon reveal", r"\b\w+:\s+(it|this|that|they)\s+\w+", False),
]
EMOJI_HEADING = re.compile(r"(?m)^#{1,6}\s.*[\U0001F300-\U0001FAFF\u2600-\u27BF]")
MID_BOLD = re.compile(r"\S\s\*\*[^*\n]+\*\*\s\S")


def hits(text: str, pattern: str) -> int:
    return len(re.findall(pattern, text, re.IGNORECASE))


def check(before: str, after: str) -> dict:
    nb, na = numbers(before), numbers(after)
    added = sorted(na - nb)
    dropped = sorted(nb - na)

    warnings, hard_new = [], []
    for label, pat, is_hard in PATTERNS:
        n_after, n_before = hits(after, pat), hits(before, pat)
        if n_after > n_before:
            (hard_new if is_hard else warnings).append(
                {"pattern": label, "before": n_before, "after": n_after})

    em_b, em_a = before.count(EMDASH), after.count(EMDASH)
    if em_a > em_b:
        warnings.append({"pattern": "em dash added", "before": em_b, "after": em_a})
    if EMOJI_HEADING.search(after) and not EMOJI_HEADING.search(before):
        warnings.append({"pattern": "emoji in heading", "before": 0, "after": 1})
    if MID_BOLD.search(after) and not MID_BOLD.search(before):
        warnings.append({"pattern": "bold mid-sentence", "before": 0, "after": 1})

    hard = []
    if added:
        hard.append({"check": "H1 no added content",
                     "detail": "number(s) in the rewrite absent from the original",
                     "values": added})
    if dropped:
        hard.append({"check": "H2 no dropped claim",
                     "detail": "number(s) in the original missing from the rewrite",
                     "values": dropped})
    for w in hard_new:
        hard.append({"check": "H4 no new AI tells",
                     "detail": f"{w['pattern']} introduced by the rewrite",
                     "values": [f"before={w['before']} after={w['after']}"]})
    return {"hard_errors": hard, "warnings": warnings,
            "numbers_before": len(nb), "numbers_after": len(na)}


def _self_test():
    """Fixture suite: the heuristics are MEASURED, not assumed.

    Every pattern regex can both miss a real tell (false negative) and fire on clean
    prose (false positive). These fixtures pin the behaviour of each on known inputs so
    a future edit that widens or narrows a pattern shows up as a failed test rather
    than as quietly different advice to a writer.
    """
    positives = [  # (label, text that MUST be flagged)
        ("chat leftover", "As an AI, I hope this helps."),
        ("chat leftover", "Let me know if you want more detail."),
        ("method narration", "This section will explore the results."),
        ("throat-clearing opener", "Here's the thing: nobody asked."),
        ("importance puffery", "The launch marks a pivotal moment for the field."),
        ("importance puffery", "It stands as a testament to their work."),
        ("weasel attribution", "Experts agree that this is the best approach."),
        ("summary-recap ending", "In conclusion, the project succeeded."),
        ("summary-recap ending", "Ultimately, it changed everything."),
        ("trailing -ing clause", "Costs fell, highlighting the value of the reform."),
        ("dramatic fragment", "That's it. That's the whole thing."),
        ("colon reveal", "The best part: it learns as you use it."),
    ]
    negatives = [  # prose that must NOT be flagged by the swept patterns
        "The trial enrolled 240 patients across three sites.",
        "Readmissions fell by 32% in the intervention arm.",
        "We compared two doses and reported the difference.",
        "The committee met on Tuesday and approved the budget.",
    ]
    misses, false_pos = [], []
    for label, text in positives:
        for name, pat, _ in PATTERNS:
            if name == label and not re.search(pat, text, re.IGNORECASE):
                misses.append("%s: %r" % (label, text))
    for text in negatives:
        for name, pat, _ in PATTERNS:
            if re.search(pat, text, re.IGNORECASE):
                false_pos.append("%s fired on %r" % (name, text))
    # H1/H2 numeric diffing
    assert numbers("enrolled 240 patients, 1,000 doses") == {"240", "1000"}
    res = check("Readmissions fell by 32%.", "Readmissions fell by 45%.")
    assert len(res["hard_errors"]) == 2, res
    assert check("Same 32% here.", "Same 32% here.")["hard_errors"] == []

    print("pattern fixtures: %d positives, %d negatives" % (len(positives), len(negatives)))
    if misses:
        print("  MISSES (false negatives):")
        for m in misses:
            print("   ", m)
    if false_pos:
        print("  FALSE POSITIVES:")
        for f in false_pos:
            print("   ", f)
    assert not misses, "%d pattern(s) failed to fire on a known tell" % len(misses)
    assert not false_pos, "%d false positive(s) on clean prose" % len(false_pos)
    print("self-test: OK (all pattern fixtures behave as documented)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Mechanical eval.md checks for /humanizerdrb.")
    ap.add_argument("--before", help="the original draft")
    ap.add_argument("--after", help="the rewritten draft")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--self-test", action="store_true", help="offline fixture check, no files")
    args = ap.parse_args(argv)

    if args.self_test:
        _self_test()
        return 0
    if not args.before or not args.after:
        print("ERROR: --before and --after are required (or use --self-test)", file=sys.stderr)
        return 1

    try:
        before = Path(args.before).read_text(encoding="utf-8")
        after = Path(args.after).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    res = check(before, after)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"numbers: {res['numbers_before']} in original, {res['numbers_after']} in rewrite")
        for h in res["hard_errors"]:
            print(f"[FAIL] {h['check']} -- {h['detail']}: {', '.join(h['values'])}")
        for w in res["warnings"]:
            print(f"[warn] {w['pattern']}: before={w['before']} after={w['after']}")
        if not res["hard_errors"] and not res["warnings"]:
            print("No mechanical problems found.")
        if not res["hard_errors"]:
            print("NOTE: no H1/H2/H4 hard error. Meaning, voice and claim preservation "
                  "still require editorial judgement -- this tool does not score AI-ness.")
    return 2 if res["hard_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
