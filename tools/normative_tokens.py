#!/usr/bin/env python3
"""normative_tokens.py -- prove a rewrite did not lose a rule.

A skill is a contract: exit codes, flags, tool names, thresholds, verdict
strings and MUST/MUST NOT clauses. A rewrite that reads better but drops one of
them is a regression, and prose review does not catch that reliably. This tool
extracts every normative token from a skill file, stores a snapshot, and then
fails if any token disappears.

Adding tokens is allowed (an expansion adds rules). Losing one is an error.

Exit codes (the repository's convention):
  0  no loss
  1  at least one token disappeared
  4  input gap -- no snapshot or no files (never a pass)

Usage:
  python3 tools/normative_tokens.py --snapshot tools/normative-baseline.json skills/*/SKILL.md
  python3 tools/normative_tokens.py --check tools/normative-baseline.json
  python3 tools/normative_tokens.py --show skills/citecheck/SKILL.md
  python3 tools/normative_tokens.py --self-test
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

# The verdict vocabulary the deterministic channels emit. A rewrite must not
# rename a state that the scripts already produce.
VERDICTS = [
    "QUOTE + CITE (verbatim)", "QUOTED", "PARAPHRASE + CITE", "REVIEW (topical overlap)",
    "ok", "attributed", "synthesis", "unverifiable here", "unattributed", "conflict",
    "no citation needed", "insufficient_evidence", "unavailable", "empty", "INPUT-BOUND",
    "submission_ready", "unresolved", "retracted", "missing",
]

PATTERNS = {
    "exit_code": re.compile(r"\b(?:exit|exits|rc|return code)\s*=?\s*([0-9])\b", re.I),
    "flag": re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]{1,30})"),
    "tool": re.compile(r"\b([a-z0-9-]+__[a-z0-9_]+)\b"),
    "mcp_tool": re.compile(r"\b(mcp__[a-z0-9-]+__[a-z0-9_]+)\b"),
    "home_path": re.compile(r"(~/[A-Za-z0-9._/-]+)"),
    "file_name": re.compile(r"\b([A-Za-z0-9_.-]+\.(?:py|sh|json|md|yml|yaml|csv|bib|txt|docx|pdf|html))\b"),
    "number": re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?:%|words?|word|sentences?|seconds?|s\b|min|hours?|pages?|chars?|bytes?|KB|MB)?"),
    "check_id": re.compile(r"\b([A-Z]{1,3}\d{1,2}[a-z]?)\b"),
    "verdict": re.compile("|".join(re.escape(v) for v in VERDICTS)),
}

CLAUSE = re.compile(r"\b(MUST NOT|MUST|SHALL NOT|SHALL|NEVER|DO NOT|ALWAYS)\b")


def _strip_code(text):
    out, fence = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        out.append("" if fence else re.sub(r"`([^`]*)`", r"\1", line))
    return "\n".join(out)


def _norm(text):
    return re.sub(r"\s+", " ", text).strip()


def extract(path):
    """Return {kind: sorted unique tokens} plus the normative clauses."""
    text = _strip_code(Path(path).read_text(encoding="utf-8", errors="replace"))
    tokens = {}
    for kind, pattern in PATTERNS.items():
        if kind == "number":
            # Only numbers that carry a unit or a percent sign: a bare "3" in prose
            # is not a contract, a "0.30 threshold" is.
            found = set()
            for m in re.finditer(
                r"(?<![\w.])(\d+(?:\.\d+)?)\s*(%|words?|sentences?|seconds?|min|hours?|pages?|chars?|bytes?|KB|MB)",
                text, re.I,
            ):
                found.add(m.group(1) + " " + m.group(2).lower())
            tokens[kind] = sorted(found)
            continue
        if kind == "check_id":
            # Keep only the ids this repository uses as gate labels.
            found = {m for m in pattern.findall(text) if re.match(r"^(?:C|H|S|R|K|D|F)\d", m)}
            tokens[kind] = sorted(found)
            continue
        tokens[kind] = sorted(set(pattern.findall(text)))
    clauses = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if CLAUSE.search(sentence):
            norm = _norm(sentence)
            clauses.append({"hash": hashlib.sha1(norm.lower().encode()).hexdigest()[:12],
                            "text": norm[:120]})
    seen, unique = set(), []
    for c in clauses:
        if c["hash"] in seen:
            continue
        seen.add(c["hash"])
        unique.append(c)
    tokens["clause"] = unique
    tokens["heading"] = sorted(
        {_norm(l.lstrip("# ").lower()) for l in text.splitlines() if l.startswith("#")}
    )
    return tokens


def snapshot(paths, out):
    data = {"files": {}}
    for p in paths:
        if Path(p).is_file():
            data["files"][str(p)] = extract(p)
    Path(out).write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    return data


def compare(snapshot_path):
    """Report every token present in the snapshot but missing now."""
    snap = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    losses = []
    for path, expected in snap.get("files", {}).items():
        if not Path(path).is_file():
            losses.append((path, "file", "the file no longer exists"))
            continue
        current = extract(path)
        for kind, want in expected.items():
            have = current.get(kind, [])
            if kind in ("clause", "heading"):
                have_keys = {c["hash"] if isinstance(c, dict) else c for c in have}
                for item in want:
                    key = item["hash"] if isinstance(item, dict) else item
                    if key not in have_keys:
                        label = item.get("text") if isinstance(item, dict) else item
                        losses.append((path, kind, label))
                continue
            for token in want:
                if token not in have:
                    losses.append((path, kind, token))
    return losses


SELF_TEST = [
    # (baseline text, current text, must the loss be detected?)
    ("Run it. Exit 3 on a gap. Use --json.\n", "Run it. Exit 3 on a gap. Use --json.\n", False),
    ("Run it. Exit 3 on a gap.\n", "Run it. Exit 3 on a gap. Use --json.\n", False),
    ("Run it. Exit 3 on a gap.\n", "Run it. Exit 0 on a gap.\n", True),
    ("Run it. Use --json.\n", "Run it.\n", True),
    ("You MUST cite every source.\n", "Cite every source.\n", True),
    ("Call paper-search__check_retraction.\n", "Check for retraction.\n", True),
]


def self_test():
    failures = []
    tmp = Path("/tmp") / "normative-tokens-selftest"
    tmp.mkdir(parents=True, exist_ok=True)
    for i, (base, cur, expect_loss) in enumerate(SELF_TEST):
        b, c = tmp / ("b%d.md" % i), tmp / ("c%d.md" % i)
        b.write_text(base, encoding="utf-8")
        c.write_text(cur, encoding="utf-8")
        snap = tmp / ("s%d.json" % i)
        snapshot([str(b)], str(snap))
        data = json.loads(snap.read_text())
        data["files"][str(c)] = data["files"].pop(str(b))
        snap.write_text(json.dumps(data), encoding="utf-8")
        losses = compare(str(snap))
        if expect_loss and not losses:
            failures.append("case %d: loss not detected" % i)
        if not expect_loss and losses:
            failures.append("case %d: false loss %s" % (i, losses))
    for msg in failures:
        print("FAIL  %s" % msg)
    print("normative_tokens self-test: %d checks, %d failed" % (len(SELF_TEST), len(failures)))
    return 1 if failures else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--snapshot", metavar="OUT.json")
    ap.add_argument("--check", metavar="SNAPSHOT.json")
    ap.add_argument("--show", metavar="FILE")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.show:
        print(json.dumps(extract(args.show), indent=1, sort_keys=True))
        return 0
    if args.check:
        if not Path(args.check).is_file():
            print("normative_tokens: snapshot missing (input gap, not a pass)", file=sys.stderr)
            return 4
        losses = compare(args.check)
        for path, kind, token in losses:
            print("LOST  %-46s %-10s %s" % (path, kind, token))
        if losses:
            print("normative_tokens: %d token(s) lost" % len(losses))
            return 1
        print("normative_tokens: no normative token lost")
        return 0
    if args.snapshot:
        if not args.paths:
            print("normative_tokens: no input files (input gap, not a pass)", file=sys.stderr)
            return 4
        data = snapshot(args.paths, args.snapshot)
        total = sum(sum(len(v) for v in t.values()) for t in data["files"].values())
        print("normative_tokens: snapshot of %d file(s), %d token(s) -> %s"
              % (len(data["files"]), total, args.snapshot))
        return 0
    print("normative_tokens: give --snapshot, --check, --show or --self-test", file=sys.stderr)
    return 4


if __name__ == "__main__":
    sys.exit(main())
