#!/usr/bin/env python3
"""e2e_citecheck.py -- score a citecheck run against skills/citecheck/eval.md C1-C9.

This is an end-to-end rubric scorer, not a wording test. It runs the skill's own
offline CLI surface against a fixture draft that carries one of each defect the
rubric names, and decides each check from the tool's output where the tool can
decide it. Checks the tool cannot decide are reported as `decided: false` with
the evidence attached and the reason named -- never silently as a pass.

Fixture (repo/tools/e2e-fixtures/citecheck/draft.md): a duplicate work (one DOI
twice), a retracted DOI, a non-resolving DOI, a quoted passage with a locator,
two orphan in-text citations, and an uncited reference-list entry.

Exit codes:
  0  every decided check passed
  1  a decided check failed (a rubric outcome is wrong)
  4  input gap: fixture/script missing, or a registry needed for C2/C3 was not
     reached at run time. A network failure is never a pass.

Usage:
  python3 tools/e2e_citecheck.py [--json OUT.json] [--offline]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SKILL = os.path.join(REPO, "skills", "citecheck", "scripts", "citecheck.py")
EVAL = os.path.join(REPO, "skills", "citecheck", "eval.md")
FIXTURE = os.path.join(HERE, "e2e-fixtures", "citecheck", "draft.md")
ITEM_ID = re.compile(r"^#{2,4}[ \t]+([A-Z]\d+[a-z]?)\.[ \t]*(.*)$", re.M)
DOI = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+")

RETRACTED_DOI = "10.1016/S0140-6736(20)31180-6"
MISSING_DOI = "10.9999/definitely-not-real.1"
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


def run(argv, cwd=None):
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


def norm_doi(doi):
    return doi.rstrip(".,;:)]").lower()


def parse_bijection(text):
    """In-text author-year citations vs reference-list entries (fixture contract)."""
    body, _, refs = text.partition("## References")
    cited = set()
    for m in re.finditer(r"\(([^()]*?\b(?:19|20)\d{2}[a-z]?(?:\s*,\s*p\.\s*\d+)?)\)", body):
        inner = m.group(1)
        for part in re.split(r";", inner):
            mm = re.search(r"([A-Z][A-Za-z'\-]+)(?:\s+et al\.?)?,?\s*((?:19|20)\d{2})", part)
            if mm:
                cited.add((mm.group(1).lower(), mm.group(2)))
    listed = set()
    for line in refs.splitlines():
        mm = re.match(r"([A-Z][A-Za-z'\-]+),[^\n]*?\(((?:19|20)\d{2})\)", line.strip())
        if mm:
            listed.add((mm.group(1).lower(), mm.group(2)))
    return sorted(cited - listed), sorted(listed - cited)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Score citecheck against eval.md C1-C9.")
    ap.add_argument("--json", help="write the full report as JSON to this path")
    ap.add_argument("--offline", action="store_true",
                    help="run only local checks; C2/C3 (registry) are reported as "
                         "undecided-by-declaration, not as a pass")
    ap.add_argument("--fixture", default=FIXTURE)
    args = ap.parse_args(argv)

    for path, what in ((SKILL, "citecheck.py"), (EVAL, "eval.md"), (args.fixture, "fixture draft")):
        if not os.path.isfile(path):
            print("INPUT GAP: %s not found: %s" % (what, path), file=sys.stderr)
            return 4

    text = open(args.fixture, encoding="utf-8").read()
    eval_text = open(EVAL, encoding="utf-8").read()
    rubric = [m.group(1) for m in ITEM_ID.finditer(eval_text)]
    print("=" * 78)
    print("CITECHECK E2E RUBRIC SCORER  (%s)" % ("offline" if args.offline else "online"))
    print("fixture: %s" % args.fixture)
    print("rubric items found in eval.md: %s" % (", ".join(rubric) or "none"))
    print("=" * 78)

    input_gap = None
    tmp = tempfile.mkdtemp(prefix="e2e-citecheck-")
    py = sys.executable

    # ---- C8: duplicates caught (offline) ---------------------------------- #
    p = run([py, SKILL, "duplicates", args.fixture, "--json"])
    dup = {}
    try:
        dup = json.loads(p.stdout)
    except ValueError:
        dup = {"findings": []}
    work = " ".join("%s %s" % (f.get("work", ""), " ".join(f.get("forms", [])))
                    for f in dup.get("findings", []))
    smith = [f for f in dup.get("findings", []) if "smith" in f.get("work", "").lower()]
    record("C8", "duplicate work named by `duplicates --json`", p.returncode, "0",
           p.returncode == 0 and bool(smith),
           evidence="findings=%s" % json.dumps(dup.get("findings", []))[:300])

    # ---- C1 / C9: scan fidelity and output shape (offline) ---------------- #
    p = run([py, SKILL, "scan", args.fixture, "--ids-only"])
    printed = [norm_doi(x) for x in DOI.findall(p.stdout)]
    in_fixture = [norm_doi(x) for x in DOI.findall(text)]
    invented = sorted(set(printed) - set(in_fixture))
    missed = sorted(set(in_fixture) - set(printed))
    record("C1", "every printed identifier traces to the fixture text", p.returncode, "0",
           p.returncode == 0 and not invented and not missed,
           evidence="printed=%d fixture=%d invented=%s missed=%s"
                    % (len(printed), len(in_fixture), invented or "none", missed or "none"))

    trunc = bool(TRUNCATION.search(p.stdout))
    complete = len(set(printed)) == len(set(in_fixture)) and not trunc
    record("C9", "complete identifier list, no truncation marker", p.returncode, "0",
           p.returncode == 0 and complete,
           evidence="ids=%d unique=%d truncation=%s"
                    % (len(printed), len(set(printed)), trunc))

    # ---- C2 / C3: unresolved and retracted rendering (needs the registry) -- #
    if args.offline:
        st = run([py, SKILL, "--self-test"])
        record("C2", "unresolved identifier is not rendered as verified", st.returncode,
               "n/a", False, decided=False, mode="deferred(offline)",
               evidence="offline: the fixture's registry outcome was not exercised; "
                        "citecheck --self-test rc=%d covers the routing offline only"
                        % st.returncode)
        record("C3", "retraction check that could not run says so", st.returncode, "n/a",
               False, decided=False, mode="deferred(offline)",
               evidence="offline: the retraction lookup was not made; a check that did not "
                        "run is not a clean check")
    else:
        refs = os.path.join(tmp, "refs.txt")
        p = run([py, SKILL, "scan", args.fixture, "--out", refs, "--format", "apa",
                 "--allow-unresolved"])
        out = p.stdout + (open(refs, encoding="utf-8").read() if os.path.exists(refs) else "")
        if p.returncode == 3:
            input_gap = "the registry was not reached (citecheck exit 3)"
            record("C2", "unresolved identifier is not rendered as verified", 3, "0",
                   False, decided=False, mode="input-gap", evidence=input_gap)
            record("C3", "retraction checked and the source named", 3, "0", False,
                   decided=False, mode="input-gap", evidence=input_gap)
        else:
            c2 = ("[UNRESOLVED]" in out and MISSING_DOI in out)
            # scan mode flags a retraction with a warning line naming the work
            # (`[!] RETRACTED: <doi>`) and a `RETRACTED:` entry prefix; the
            # bracketed `[RETRACTED]` tag belongs to resolve/verify mode.
            retract_lines = [ln.strip() for ln in (p.stderr + "\n" + out).splitlines()
                             if "RETRACTED" in ln.upper()]
            named = any(RETRACTED_DOI in ln.lower() or
                        RETRACTED_DOI.rstrip(")").lower() in ln.lower()
                        for ln in retract_lines)
            c3 = bool(retract_lines) and named
            src = "retraction_source" in out or "per OpenAlex" in out
            record("C2", "unresolved identifier tagged, not rendered as verified",
                   p.returncode, "0", c2, evidence="[UNRESOLVED]+id present=%s" % c2)
            record("C3", "retraction warning names the retracted work", p.returncode, "0",
                   c3, evidence="warning lines=%s; source-of-flag clause=%s"
                                % (retract_lines[:2] or "none",
                                   "shown" if src else
                                   "not exercised by scan mode (source shown only in "
                                   "resolve mode's retraction_source)"))

    # ---- C6: in-text / list bijection ------------------------------------- #
    cited_not_listed, listed_not_cited = parse_bijection(text)
    record("C6", "bijection: both orphan directions present in the fixture", None, "0",
           bool(cited_not_listed) and bool(listed_not_cited), decided=False,
           mode="fixture-contract (audit verdict is human-judged)",
           evidence="cited-not-listed=%s listed-not-cited=%s -- the tool surface has no "
                    "offline bijection command, so the audit verdict stays human"
                    % (cited_not_listed, listed_not_cited))

    # ---- human-judged checks, with evidence attached ---------------------- #
    record("C4", "one citation style used throughout", None, "n/a", False, decided=False,
           mode="human-judged",
           evidence="fixture mixes author-year prose with a plain list; style conformance "
                    "needs a reader")
    record("C5", "every entry complete where the work possesses the fields", None, "n/a",
           False, decided=False, mode="human-judged",
           evidence="fixture entries lack page ranges for two works; whether that is a "
                    "flag or a fabrication is a judgement")
    record("C7", "quotes verify against the cited source wording", None, "n/a", False,
           decided=False, mode="human-judged",
           evidence='quote in fixture: "memory is reconstructive, not reproductive" '
                    "(Chen, 2020, p. 44) -- needs the source text to verify")

    # ---- report ----------------------------------------------------------- #
    failed = [r for r in ROWS if r["decided"] and not r["ok"]]
    undecided = [r for r in ROWS if not r["decided"]]
    scored = {r["check"] for r in ROWS}
    print("\n" + "=" * 78)
    print("REPORT: %d checks, %d decided-failed, %d undecided" %
          (len(ROWS), len(failed), len(undecided)))
    for r in failed:
        print("  FAILED %s: %s (%s)" % (r["check"], r["phase"], r["evidence"][:90]))
    for r in undecided:
        print("  UNDECIDED %s [%s]: %s" % (r["check"], r["mode"], r["evidence"][:90]))
    missing_items = [i for i in rubric if i not in scored]
    if missing_items:
        print("  eval.md items with no scorer row: %s" % ", ".join(missing_items))
    if input_gap:
        print("  INPUT GAP: %s" % input_gap)
    print("=" * 78)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"skill": "citecheck", "fixture": args.fixture, "offline": args.offline,
                       "rubric": rubric, "checks": ROWS, "failed": len(failed),
                       "undecided": [r["check"] for r in undecided],
                       "unscored_rubric_items": missing_items,
                       "input_gap": input_gap}, fh, indent=2)
        print("wrote %s" % args.json)

    if input_gap:
        return 4
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
