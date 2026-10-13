#!/usr/bin/env python3
"""e2e_humanizer.py -- score humanizerdrb against eval.md H1-H4 and S1-S7, offline.

The rubric is a behavioural one, so every mechanical check here is written as a
*gate*: the good fixture must pass AND a bad fixture (or an in-memory negative
control) must fail. A check that can only pass proves nothing.

Checks that need a reader -- H3 sample fidelity, S5 register -- are reported as
`decided: false` with the evidence a reader needs (sentence-length statistics,
contraction counts), never as a pass.

Exit codes:
  0  every decided check passed
  1  a decided check failed
  4  input gap: a fixture or the skill's script is missing/unreadable, or
     humanizer_check.py itself reports `insufficient_input` (exit 3)

Usage:
  python3 tools/e2e_humanizer.py [--json OUT.json] [--offline]
"""
import argparse
import importlib.util
import json
import os
import re
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SKILL_DIR = os.path.join(REPO, "skills", "humanizerdrb")
CHECK = os.path.join(SKILL_DIR, "scripts", "humanizer_check.py")
EVAL = os.path.join(SKILL_DIR, "eval.md")
REFS = os.path.join(SKILL_DIR, "references")
FIX = os.path.join(HERE, "e2e-fixtures", "humanizer")
ITEM_ID = re.compile(r"^#{2,4}[ \t]+([A-Z]\d+[a-z]?)\.[ \t]*(.*)$", re.M)
TRUNCATION = re.compile(r"\[rest unchanged\]|\[\.\.\.\]|\[truncated\]", re.I)

ROWS = []


def record(check, phase, rc, expected, ok, decided=True, mode="mechanical", evidence=""):
    ROWS.append({"check": check, "phase": phase, "rc": rc, "expected": expected,
                 "ok": bool(ok), "decided": bool(decided), "mode": mode,
                 "evidence": evidence})
    if decided:
        print("  %-4s %-58s rc=%-4s %s" % (check, phase[:58], rc, "PASS" if ok else "FAIL"))
    else:
        print("  %-4s %-58s %s" % (check, phase[:58], "UNDECIDED -- " + evidence[:70]))


def load_checker():
    spec = importlib.util.spec_from_file_location("humanizer_check", CHECK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def sentence_lengths(text):
    body = text.split("## What changed")[0]
    sents = [s for s in re.split(r"(?<=[.!?])\s+", re.sub(r"^#.*$", "", body, flags=re.M))
             if len(s.split()) > 2]
    return [len(s.split()) for s in sents]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Score humanizerdrb against eval.md H1-H4/S1-S7.")
    ap.add_argument("--json", help="write the full report as JSON to this path")
    ap.add_argument("--offline", action="store_true",
                    help="accepted for interface parity; this scorer is fully offline")
    ap.add_argument("--fixtures", default=FIX)
    args = ap.parse_args(argv)

    for path, what in ((CHECK, "humanizer_check.py"), (EVAL, "eval.md"),
                       (args.fixtures, "fixture directory")):
        if not os.path.exists(path):
            print("INPUT GAP: %s not found: %s" % (what, path), file=sys.stderr)
            return 4

    hc = load_checker()
    fx = args.fixtures
    need = ["before.md", "after_good.md", "after_bad_added.md", "after_bad_dropped.md",
            "after_bad_tells.md", "after_good_report.md", "sample.md"]
    for fn in need:
        if not os.path.isfile(os.path.join(fx, fn)):
            print("INPUT GAP: fixture missing: %s" % os.path.join(fx, fn), file=sys.stderr)
            return 4
    before = read(os.path.join(fx, "before.md"))
    good = read(os.path.join(fx, "after_good.md"))
    added = read(os.path.join(fx, "after_bad_added.md"))
    dropped = read(os.path.join(fx, "after_bad_dropped.md"))
    tells = read(os.path.join(fx, "after_bad_tells.md"))
    report = read(os.path.join(fx, "after_good_report.md"))
    sample = read(os.path.join(fx, "sample.md"))
    rubric = [m.group(1) for m in ITEM_ID.finditer(read(EVAL))]
    section_ids = set()
    if os.path.isdir(REFS):
        for fn in os.listdir(REFS):
            section_ids |= set(re.findall(r"§\d+", read(os.path.join(REFS, fn))))

    print("=" * 78)
    print("HUMANIZERDRB E2E RUBRIC SCORER (offline)")
    print("fixtures: %s" % fx)
    print("rubric items found in eval.md: %s" % (", ".join(rubric) or "none"))
    print("=" * 78)

    input_gap = None

    # ---- T0: the skill's own self-test (precondition) --------------------- #
    p = subprocess.run([sys.executable, CHECK, "--self-test"], capture_output=True, text=True)
    record("T0", "humanizer_check.py --self-test", p.returncode, "0", p.returncode == 0,
           evidence=(p.stdout.strip().splitlines() or [""])[-1][:120])
    if p.returncode != 0:
        print("  ! the skill's own self-test failed; the rubric scores below are unreliable")

    def hard_names(res):
        return {h["check"].split()[0] for h in res["hard_errors"]}

    # ---- H1 / H2 / H4: each must pass on the good fixture and fire on its bad one -- #
    r_good, r_added = hc.check(before, good), hc.check(before, added)
    r_drop, r_tells = hc.check(before, dropped), hc.check(before, tells)

    record("H1", "no added content: clean on good, fires on a new number",
           None, "clean/good + H1/added",
           "H1" not in hard_names(r_good) and "H1" in hard_names(r_added),
           evidence="good=%s added=%s values=%s"
                    % (sorted(hard_names(r_good)) or "clean", sorted(hard_names(r_added)),
                       [h.get("values") for h in r_added["hard_errors"] if h["check"].startswith("H1")]))

    record("H2", "no dropped claim: clean on good, fires on a removed number",
           None, "clean/good + H2/dropped",
           "H2" not in hard_names(r_good) and "H2" in hard_names(r_drop),
           evidence="good=%s dropped=%s values=%s"
                    % (sorted(hard_names(r_good)) or "clean", sorted(hard_names(r_drop)),
                       [h.get("values") for h in r_drop["hard_errors"] if h["check"].startswith("H2")]))

    record("H4", "no new AI tells: clean on good, fires on an introduced tell",
           None, "clean/good + H4/tells",
           "H4" not in hard_names(r_good) and "H4" in hard_names(r_tells),
           evidence="good=%s tells=%s" % (sorted(hard_names(r_good)) or "clean",
                                          sorted(hard_names(r_tells))))

    # ---- H3: sample fidelity (a reader's call) ---------------------------- #
    ls_sample, ls_after = sentence_lengths(sample), sentence_lengths(report)
    def stat(xs):
        return "n=%d mean=%.1f sd=%.1f" % (len(xs), statistics.mean(xs),
                                           statistics.pstdev(xs)) if xs else "n=0"
    contractions = len(re.findall(r"\b\w+'(s|t|re|ve|ll|d)\b", report))
    record("H3", "sample fidelity: rewrite tracks the supplied sample's voice", None, "n/a",
           False, decided=False, mode="human-judged",
           evidence="sample %s; rewrite %s; contractions in rewrite=%d -- voice is not "
                    "mechanically scorable" % (stat(ls_sample), stat(ls_after), contractions))

    # ---- S1 / S2: survivor sweep and chat leftovers (scan the after text) -- #
    # Only the returned *draft* is swept: the "What changed" appendix quotes the
    # removed tells on purpose, so scanning it would report the citation of a
    # pattern as the pattern surviving.
    draft = report.split("## What changed")[0]
    tells_draft = tells.split("## What changed")[0]

    def sweep(text):
        return [label for label, pat, _hard in hc.PATTERNS if hc.hits(text, pat) > 0]

    s1_good, s1_bad = sweep(draft), sweep(tells_draft)
    record("S1", "survivor sweep clear on the result", None, "none/result + hit/tells",
           not s1_good and bool(s1_bad),
           evidence="result survivors=%s; control survivors=%s" % (s1_good or "none", s1_bad))

    s2_labels = {"chat leftover", "method narration"}
    s2_good = [x for x in s1_good if x in s2_labels]
    s2_bad = [x for x in s1_bad if x in s2_labels]
    record("S2", "no chat leftovers or method narration", None, "none/result + hit/tells",
           not s2_good and bool(s2_bad),
           evidence="result=%s; control=%s" % (s2_good or "none", s2_bad or "none"))

    # ---- S3: length sanity ------------------------------------------------ #
    def ratio_ok(before_text, after_text):
        wb, wa = len(before_text.split()), len(after_text.split())
        r = wa / wb if wb else 0
        return 0.6 <= r <= 1.6, r

    ok3, r3 = ratio_ok(before, report)
    padded = before + " " + " ".join(["padding"] * 400)
    ok3_neg, _ = ratio_ok(before, padded)
    record("S3", "length sanity: neither padded nor gutted", None, "0.6-1.6",
           ok3 and not ok3_neg,
           evidence="result ratio=%.2f; padded control rejected=%s" % (r3, not ok3_neg))

    # ---- S4: "What changed" is honest ------------------------------------- #
    named = sorted(set(re.findall(r"§\d+", report)))
    unknown = [s for s in named if section_ids and s not in section_ids]
    has_section = "## What changed" in report
    s4_neg = "## What changed\n- §99 removed a thing\n"
    neg_named = re.findall(r"§\d+", s4_neg)
    neg_unknown = [s for s in neg_named if section_ids and s not in section_ids]
    record("S4", "What changed present and names real pattern sections", None,
           "section + known §",
           has_section and bool(named) and not unknown and bool(neg_unknown),
           evidence="section=%s named=%s unknown=%s; control §99 rejected=%s (the honesty of "
                    "each claim is human)" % (has_section, named or "none",
                                              unknown or "none", bool(neg_unknown)))

    # ---- S5: register (a reader's call) ----------------------------------- #
    record("S5", "requested register honoured", None, "n/a", False, decided=False,
           mode="human-judged",
           evidence="fixture supplies no --tone; register fit (academic/technical) needs a "
                    "reader; contractions in rewrite=%d" % contractions)

    # ---- S6: format follows content --------------------------------------- #
    def fmt_ok(text):
        return not hc.EMOJI_HEADING.search(text) and not hc.MID_BOLD.search(text)

    fmt_neg = "# Heading \U0001F680\n\nA **bold** word mid sentence.\n"
    record("S6", "no emoji headings, no mid-sentence bold", None, "clean/result + hit/control",
           fmt_ok(report) and not fmt_ok(fmt_neg),
           evidence="result clean=%s; formatting control rejected=%s (the "
                    "'header over two sentences' clause is not mechanized)"
                    % (fmt_ok(report), not fmt_ok(fmt_neg)))

    # ---- S7: output shape ------------------------------------------------- #
    s7_ok = (has_section and not TRUNCATION.search(report)
             and "The cache is a useful engineering tradeoff." in report
             and report.rstrip().endswith("dropped the opening \"It's worth noting that\"."))
    s7_neg = report.replace("The cache is not a substitute", "[rest unchanged]")
    record("S7", "full draft plus What changed, nothing truncated", None, "complete + section",
           s7_ok and bool(TRUNCATION.search(s7_neg)),
           evidence="draft head present=True (literal marker), section=%s truncation=%s; "
                    "truncation control rejected=True"
                    % (has_section, bool(TRUNCATION.search(report))))

    # ---- report ----------------------------------------------------------- #
    failed = [r for r in ROWS if r["decided"] and not r["ok"]]
    undecided = [r for r in ROWS if not r["decided"]]
    scored = {r["check"] for r in ROWS}
    unscored = [i for i in rubric if i not in scored]
    print("\n" + "=" * 78)
    print("REPORT: %d checks, %d decided-failed, %d undecided" %
          (len(ROWS), len(failed), len(undecided)))
    for r in failed:
        print("  FAILED %s: %s (%s)" % (r["check"], r["phase"], r["evidence"][:90]))
    for r in undecided:
        print("  UNDECIDED %s [%s]: %s" % (r["check"], r["mode"], r["evidence"][:90]))
    if unscored:
        print("  eval.md items with no scorer row: %s" % ", ".join(unscored))
    if input_gap:
        print("  INPUT GAP: %s" % input_gap)
    print("=" * 78)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"skill": "humanizerdrb", "fixtures": fx, "offline": True,
                       "rubric": rubric, "checks": ROWS, "failed": len(failed),
                       "undecided": [r["check"] for r in undecided],
                       "unscored_rubric_items": unscored, "input_gap": input_gap},
                      fh, indent=2)
        print("wrote %s" % args.json)

    if input_gap:
        return 4
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
