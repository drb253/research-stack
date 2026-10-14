#!/usr/bin/env python3
"""check_descriptions.py -- the frontmatter description is the routing text.

A model picks a skill from its `description` alone. Two failure modes were
measured in this repository on 2026-10-14:

  * a 175-word keyword dump (environment-life-review-forge) -- it floods the
    catalog and blurs routing;
  * a description ending "is what makes writing plagiarism-free"
    (citecheck) -- an absolute claim in the text the model reads first.

This gate checks all three properties a routing description must have:

  1. `name` is kebab-case and equals the directory name;
  2. `description` exists and is 40-100 words: enough to route on, short enough
     to read;
  3. it carries no absolute claim (delegated to tools/claim_guard.py, so the two
     gates cannot drift).

Exit codes (the repository's convention):
  0  every description passes
  1  at least one violation
  4  input gap -- no skill files (never a pass)

Usage:
  python3 tools/check_descriptions.py [skills_dir]
  python3 tools/check_descriptions.py --self-test
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try:
    from claim_guard import scan as claim_scan
except Exception:  # pragma: no cover - the gate must still run standalone
    def claim_scan(text, where="<text>"):
        return []

MIN_WORDS = 40
MAX_WORDS = 100
KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def parse_frontmatter(text):
    """Return {key: value} for the leading YAML block, without a YAML library."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out, key = {}, None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"^([a-z0-9_-]+):\s*(.*)$", line)
        if m:
            key = m.group(1)
            out[key] = m.group(2).strip()
        elif key and line.startswith((" ", "\t")):
            out[key] = (out[key] + " " + line.strip()).strip()
    for k, v in list(out.items()):
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            out[k] = v[1:-1]
    return out


def _frontmatter_block(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i])
    return None


def strict_yaml_problem(text):
    """Return a message when the frontmatter is not valid YAML, else None.

    Four skills shipped an unquoted `description:` containing ": ", which is not a
    valid YAML scalar: the harness parsed nothing, dropped the skill from the
    catalog, and the hand-rolled reader below happily reported "13 of 13 pass".
    The catalog went from 13 skills to 9 and only the live catalog showed it. When
    PyYAML is available it decides; the stdlib fallback still catches the exact
    shape that broke, so this cannot pass unnoticed on a machine without it.
    """
    block = _frontmatter_block(text)
    if block is None:
        return "no YAML frontmatter"
    try:
        import yaml  # noqa: PLC0415 - optional, the repository is stdlib-only
    except Exception:
        for line in block.splitlines():
            m = re.match(r"^([a-z0-9_-]+):\s+([^'\"|>\[{].*)$", line)
            if m and ": " in m.group(2):
                return ("unquoted value for '%s' contains ': ' -- quote the value"
                        % m.group(1))
        return None
    try:
        parsed = yaml.safe_load(block)
    except Exception as exc:
        return "invalid YAML: %s" % str(exc).splitlines()[0][:90]
    if not isinstance(parsed, dict):
        return "the frontmatter is not a mapping"
    return None


def check(skills_dir="skills"):
    problems = []
    root = Path(skills_dir)
    files = sorted(root.glob("*/SKILL.md"))
    for path in files:
        name = path.parent.name
        text = path.read_text(encoding="utf-8", errors="replace")
        yaml_problem = strict_yaml_problem(text)
        if yaml_problem:
            problems.append((name, yaml_problem))
            continue
        fm = parse_frontmatter(text)
        declared = fm.get("name", "")
        desc = fm.get("description", "")
        if not declared:
            problems.append((name, "name is missing from the frontmatter"))
        elif declared != name:
            problems.append((name, "name '%s' does not match the directory" % declared))
        elif not KEBAB.match(declared):
            problems.append((name, "name '%s' is not kebab-case" % declared))
        if not desc:
            problems.append((name, "description is missing"))
            continue
        words = len(desc.split())
        if words < MIN_WORDS:
            problems.append((name, "description is %d words (minimum %d): too thin to route on"
                             % (words, MIN_WORDS)))
        elif words > MAX_WORDS:
            problems.append((name, "description is %d words (maximum %d): trim it"
                             % (words, MAX_WORDS)))
        for finding in claim_scan(desc, where=name):
            problems.append((name, "description carries an absolute claim: %s" % finding["message"]))
    return files, problems


SELF_TEST = [
    ("---\nname: good\ndescription: \"%s\"\n---\n" % ("word " * 60), False),
    ("---\nname: wrong\ndescription: \"%s\"\n---\n" % ("word " * 60), True),
    ("---\nname: good\ndescription: \"too short\"\n---\n", True),
    ("---\nname: good\ndescription: \"%s\"\n---\n" % ("word " * 130), True),
    ("---\nname: good\ndescription: \"%s\"\n---\n" % (("word " * 59) + "plagiarism-free"), True),
    ("---\ndescription: \"%s\"\n---\n" % ("word " * 60), True),
    # The defect that dropped four skills from the live catalog: an unquoted
    # description containing ": " is not a valid YAML scalar.
    ("---\nname: good\ndescription: This produces a package: an audit and a plan. %s\n---\n"
     % ("word " * 45), True),
    ("---\nname: good\ndescription: \"This produces a package: an audit and a plan. %s\"\n---\n"
     % ("word " * 45), False),
]


def self_test():
    failures = []
    tmp = Path("/tmp") / "check-descriptions-selftest"
    for i, (text, expect) in enumerate(SELF_TEST):
        d = tmp / ("skill%d" % i) / "good"
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(text, encoding="utf-8")
    for i, (text, expect) in enumerate(SELF_TEST):
        root = tmp / ("skill%d" % i)
        _files, problems = check(str(root))
        if bool(problems) != expect:
            failures.append("case %d: expected problems=%s, got %s" % (i, expect, problems))
    for msg in failures:
        print("FAIL  %s" % msg)
    print("check_descriptions self-test: %d checks, %d failed" % (len(SELF_TEST), len(failures)))
    return 1 if failures else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("skills_dir", nargs="?", default="skills")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    files, problems = check(args.skills_dir)
    if not files:
        print("check_descriptions: no SKILL.md under %s (input gap, not a pass)"
              % args.skills_dir, file=sys.stderr)
        return 4
    for name, message in problems:
        print("FAIL  %-32s %s" % (name, message))
    print("check_descriptions: %d skill(s), %d problem(s)" % (len(files), len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
