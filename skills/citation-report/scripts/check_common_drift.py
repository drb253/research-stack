#!/usr/bin/env python3
"""Check that this skill's copy of the shared helpers has not drifted silently.

`_common.py` here is a deliberate, provenance-noted copy of
`medical-narrative-review/scripts/_common.py`: skills are installed and symlinked
individually, and no skill may import another skill's directory at run time. Because the
copy is deliberate, parity cannot come from an import -- it has to be checked. This script
is that check, and `scripts/selftest.sh` runs it, so the claim in `_common.py`'s docstring
is backed by an executable test rather than by prose.

How a primitive is compared:

* a module-level constant whose value is a literal is compared by VALUE, so a reformat is
  not drift (this is how `STATUS_EXIT_CODE` differs between the two files: same values,
  different layout);
* every other primitive is compared by source text.

A primitive that differs on purpose is listed in `ALLOWED` with its reason. Anything that
differs and is not listed is unexpected drift: exit 1. Exit 0 means parity. Exit 4 means a
file or an argument is missing -- an input gap, never a pass.

Usage:
  python3 check_common_drift.py
  python3 check_common_drift.py --self-test
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
COPY = HERE / "_common.py"
UPSTREAM = HERE.parent.parent / "medical-narrative-review" / "scripts" / "_common.py"

# Primitives that differ on purpose, with the reason. Adding a name here is the only way
# to accept a difference, so every entry is a decision someone made and can defend.
ALLOWED = {
    "MAX_FILE_BYTES": "citation-report reads larger documents than a narrative review",
    "MAX_CSV_FIELD_BYTES": "a citation-report source table carries longer fields",
    "MAX_JSON_DEPTH": "the verdict envelope here nests deeper",
    "MAX_JSON_NODES": "a report envelope holds more nodes than a review checklist",
    "emit_report": "this copy carries status_override/exit_override; the review copy does not",
    "emit_input_error": "this copy delegates to emit_report with the override arguments",
    "write_text_lf": "this copy refuses to write through a symlink",
}


def primitives(path):
    """Top-level constants, functions and classes: name -> (kind, node, source)."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out[node.name] = ("def", node, ast.get_source_segment(source, node))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = ("const", node, ast.get_source_segment(source, node))
    return out


def literal_of(kind, node):
    if kind != "const":
        return None
    try:
        return ast.literal_eval(node.value)
    except Exception:
        return None


def compare(copy_path, upstream_path):
    """Return (identical, allowed, unexpected, only_in_copy, only_in_upstream)."""
    a = primitives(copy_path)
    b = primitives(upstream_path)
    identical, allowed, unexpected = [], [], []
    for name in sorted(set(a) & set(b)):
        ka, na, sa = a[name]
        kb, nb, sb = b[name]
        la, lb = literal_of(ka, na), literal_of(kb, nb)
        same = (la == lb) if (la is not None and lb is not None) else (sa == sb)
        if same:
            identical.append(name)
        elif name in ALLOWED:
            allowed.append(name)
        else:
            unexpected.append(name)
    return identical, allowed, unexpected, sorted(set(a) - set(b)), sorted(set(b) - set(a))


def run(copy_path, upstream_path, quiet=False):
    if not copy_path.is_file() or not upstream_path.is_file():
        missing = [str(p) for p in (copy_path, upstream_path) if not p.is_file()]
        print("check_common_drift: missing input %s (input gap, not a pass)"
              % ", ".join(missing), file=sys.stderr)
        return 4
    identical, allowed, unexpected, only_copy, only_up = compare(copy_path, upstream_path)
    if not quiet:
        print("shared primitives: %d identical, %d allowlisted, %d unexpected"
              % (len(identical), len(allowed), len(unexpected)))
        for name in allowed:
            print("  allowed    %-22s %s" % (name, ALLOWED[name]))
        for name in unexpected:
            print("  DRIFTED    %-22s not in ALLOWED" % name)
        if only_copy:
            print("  local-only %s" % ", ".join(only_copy))
        if only_up:
            print("  upstream-only %s" % ", ".join(only_up))
    if unexpected:
        print("check_common_drift: FAIL -- %d unexpected difference(s); align them or add "
              "each to ALLOWED with a reason" % len(unexpected), file=sys.stderr)
        return 1
    print("check_common_drift: OK -- no unexpected drift from %s" % upstream_path.name)
    return 0


SELFTEST_CASES = [
    # (upstream body, copy body, allowed set, expected exit)
    ("MAX_X = 1\n", "MAX_X = 1\n", {}, 0),                       # identical
    ("MAX_X = 1\n", "MAX_X  =  1\n", {}, 0),                      # reformat: value compare
    ("MAX_X = 1\n", "MAX_X = 2\n", {}, 1),                        # real drift
    ("MAX_X = 1\n", "MAX_X = 2\n", {"MAX_X": "tuned"}, 0),        # allowlisted
    ("def f():\n    return 1\n", "def f():\n    return 2\n", {}, 1),   # body drift
]


def self_test():
    import tempfile
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for i, (up, cp, allowed, want) in enumerate(SELFTEST_CASES):
            (tmp / "up.py").write_text(up)
            (tmp / "cp.py").write_text(cp)
            saved = dict(ALLOWED)
            ALLOWED.clear()
            ALLOWED.update(allowed)
            got = run(tmp / "cp.py", tmp / "up.py", quiet=True)
            ALLOWED.clear()
            ALLOWED.update(saved)
            if got != want:
                failures.append("case %d expected exit %d, got %d" % (i, want, got))
        got = run(tmp / "nope.py", tmp / "up.py", quiet=True)
        if got != 4:
            failures.append("a missing copy should exit 4, got %d" % got)
    for message in failures:
        print("FAIL  %s" % message)
    print("check_common_drift self-test: %d checks, %d failed"
          % (len(SELFTEST_CASES) + 1, len(failures)))
    return 1 if failures else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    return run(COPY, UPSTREAM, quiet=args.quiet)


if __name__ == "__main__":
    sys.exit(main())
