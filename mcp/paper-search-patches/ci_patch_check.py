#!/usr/bin/env python3
"""ci_patch_check.py -- exercise the paper-search patch system on a throwaway copy.

The patch system edits a `paper_search_mcp` package that lives outside this repository
(a uv-tool install), so nothing on a push used to notice a patch that stopped applying or
a replacement that drifted from the vendored file it mirrors. This script supplies the
missing target: it copies the vendored package from the checkout into a temporary
directory, runs the real patch pipeline against that copy, and checks the result.

It proves four things, each with the exit status that matches what was found:

  1. every file in `replacements/` is byte-identical to the vendored file it mirrors,
     so a reinstall cannot silently revert the fix it encodes;
  2. `apply_patches.py` applies cleanly to a fresh copy (no MISSING/COULD NOT APPLY);
  3. the patched copy passes `audit_fix_check.py` and the availability invariant suite;
  4. the suite still FAILS on a copy with the invariant deliberately reintroduced, so
     the checks above are a gate rather than an assertion.

What this does NOT establish: the vendored package in this repository is kept in the
patched state, so running the patcher against it is idempotent by construction. This gate
catches drift, breakage and a toothless suite; it does not reconstruct the fixed files
from pristine upstream 0.1.4, which would need those upstream files, and they are not
vendored here.

Exit codes: 0 pass, 1 a finding (drift, a failed patch, or a toothless check),
4 insufficient_input (no `requests` to run the suite, or a missing tree).

    python3 mcp/paper-search-patches/ci_patch_check.py
    python3 mcp/paper-search-patches/ci_patch_check.py --self-test
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
VENDORED = REPO / "mcp" / "paper-search-mcp" / "paper_search_mcp"
REPLACEMENTS = HERE / "replacements"
VENDORED_TREE = REPO / "mcp" / "paper-search-mcp" / "paper_search_mcp"
AVAILABILITY_TEST = HERE / "test_availability_invariant.py"

#: The mutation that reintroduces the defect the availability layer exists to prevent:
#: an outage reported with the same name as a genuine empty answer. Applied to a copy of
#: source_status.py; the suite must reject it.
MUTATION_FROM = 'SOURCE_UNAVAILABLE = "unavailable"'
MUTATION_TO = 'SOURCE_UNAVAILABLE = "empty"'


class Finding(Exception):
    """One check failed for a reason that is about the artefact under test."""


def check(label: str, ok: bool) -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        raise Finding(label)


def drifted_replacements(replacements: Path, vendored: Path) -> list:
    """Names in `replacements/` that match no byte-identical file in `vendored`."""
    drifted = []
    for source in sorted(replacements.glob("*.py")):
        candidates = list(vendored.rglob(source.name))
        if candidates and not any(c.read_bytes() == source.read_bytes() for c in candidates):
            drifted.append(source.name)
    return drifted


def run(argv: list, env: dict | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, env=env, cwd=cwd)


def copy_tree(destination: Path) -> Path:
    """Copy the vendored package to `destination/paper_search_mcp` and return the parent."""
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(VENDORED, destination / "paper_search_mcp")
    return destination


#: What the availability suite needs to import. The suite stubs `requests`, and two of its
#: ten tests import `paper_search_mcp.server`, which imports the rest at module level.
#: `mcp.server.fastmcp` is the sharp one: the runner's `mcp` 2.x renamed it, so a machine
#: with `mcp` 2.x has the package but not that module. Probed by import, not by name.
SUITE_IMPORTS = ("requests", "httpx", "bs4", "feedparser", "pypdf", "mcp.server.fastmcp")


def check_environment(python: str) -> int:
    """Every import the suite needs must be present, or nothing is verified.

    A missing dependency is an input gap, not a failed check: this returns 4 with the
    command that closes it. Reporting the suite as passing while two of its tests never
    ran is exactly the confusion this repository exists to prevent.
    """
    probe_code = ";".join("import %s" % name for name in SUITE_IMPORTS)
    probe = run([python, "-c", probe_code])
    if probe.returncode == 0:
        return 0
    missing = probe.stderr.strip().splitlines()[-1] if probe.stderr.strip() else "unknown"
    print("STATUS: insufficient_input")
    print("nothing was verified: the availability suite cannot import what it stubs.")
    print("  %s" % missing)
    print("input_gaps:")
    print("  - kind: dependency_missing")
    print("    how_to_close: %s -m pip install requests httpx beautifulsoup4 feedparser "
          "pypdf 'mcp[cli]>=1.27.2,<2'" % python)
    return 4


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--self-test", action="store_true",
                        help="test this checker's own drift and mutation detection")
    parser.add_argument("--keep", action="store_true",
                        help="keep the temporary trees for inspection")
    parser.add_argument("--python", default=sys.executable,
                        help="interpreter used for the patch scripts and the suite")
    arguments = parser.parse_args(argv)

    if arguments.self_test:
        return self_test()

    if not VENDORED.is_dir():
        print(f"STATUS: insufficient_input\nnothing was checked: {VENDORED} is missing.")
        return 4
    gap = check_environment(arguments.python)
    if gap:
        return gap

    failures: list = []

    print("== 1. replacements match the vendored files they mirror ==")
    try:
        drifted = drifted_replacements(REPLACEMENTS, VENDORED_TREE)
        check("every replacement is byte-identical to its vendored file",
              not drifted)
    except Finding as exc:
        failures.append(str(exc))
        print(f"    drifted: {drifted}")

    root = Path(tempfile.mkdtemp(prefix="ps-patch-"))
    try:
        target = copy_tree(root / "clean")
        print(f"\n== 2. the patch pipeline runs clean on a fresh copy ({target}) ==")
        patch = run([arguments.python, str(HERE / "apply_patches.py"), "--package", str(target)])
        print("    " + "\n    ".join(patch.stdout.strip().splitlines()[-3:] or [""]))
        try:
            check("apply_patches.py exits 0", patch.returncode == 0)
            check("the patch summary reports no failures", "failed=0" in patch.stdout)
        except Finding as exc:
            failures.append(str(exc))
            print("    " + "\n    ".join(patch.stdout.strip().splitlines()[-6:]))
            if patch.stderr.strip():
                print("    stderr: " + patch.stderr.strip().splitlines()[-1])

        print("\n== 3. the patched copy carries the fixes ==")
        audit = run([arguments.python, str(HERE / "audit_fix_check.py"), "--package", str(target)])
        try:
            check("audit_fix_check.py exits 0", audit.returncode == 0)
        except Finding as exc:
            failures.append(str(exc))
        print("    " + "\n    ".join(audit.stdout.strip().splitlines()[-2:] or [""]))

        print("\n== 4. the availability invariant holds in the patched copy ==")
        clean_env = dict(os.environ, PAPER_SEARCH_MCP_PATH=str(target),
                         PYTHONPATH=str(target))
        suite = run([arguments.python, str(AVAILABILITY_TEST)], env=clean_env)
        try:
            check("the availability suite passes on the patched copy", suite.returncode == 0)
        except Finding as exc:
            failures.append(str(exc))
            print("    " + "\n    ".join(suite.stderr.strip().splitlines()[-6:] or [""]))

        print("\n== 5. the same suite still rejects the defect (mutation probe) ==")
        mutant = copy_tree(root / "mutant")
        status_file = mutant / "paper_search_mcp" / "source_status.py"
        text = status_file.read_text(encoding="utf-8")
        if MUTATION_FROM not in text:
            check("the mutation target is present (the probe is not silently skipped)", False)
        else:
            status_file.write_text(text.replace(MUTATION_FROM, MUTATION_TO, 1), encoding="utf-8")
            mutant_env = dict(os.environ, PAPER_SEARCH_MCP_PATH=str(mutant),
                              PYTHONPATH=str(mutant))
            probe = run([arguments.python, str(AVAILABILITY_TEST)], env=mutant_env)
            try:
                check("the suite fails on a copy where an outage is named 'empty'",
                      probe.returncode != 0)
            except Finding as exc:
                failures.append(str(exc))
    finally:
        if arguments.keep:
            print(f"\ntemporary trees kept: {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)

    print("\npaper-search patch check: %s" % ("OK" if not failures else "FAILED"))
    return 1 if failures else 0


def self_test() -> int:
    """Pin the two detections this script depends on: drift and mutation."""
    failures = []
    root = Path(tempfile.mkdtemp(prefix="ps-patch-selftest-"))
    try:
        rep = root / "replacements"
        vend = root / "vendored" / "pkg"
        rep.mkdir(parents=True)
        vend.mkdir(parents=True)
        (rep / "same.py").write_text("x = 1\n", encoding="utf-8")
        (vend / "same.py").write_text("x = 1\n", encoding="utf-8")
        (rep / "differs.py").write_text("x = 2\n", encoding="utf-8")
        (vend / "differs.py").write_text("x = 1\n", encoding="utf-8")
        (vend / "nested").mkdir()
        (rep / "nested.py").write_text("y = 3\n", encoding="utf-8")
        (vend / "nested" / "nested.py").write_text("y = 3\n", encoding="utf-8")

        drifted = drifted_replacements(rep, vend)
        checks = [
            ("identical files are not reported as drift", "same.py" not in drifted),
            ("a byte difference is reported as drift", drifted == ["differs.py"]),
            ("a nested vendored match counts", "nested.py" not in drifted),
        ]
        # The mutation itself: the constant must be present and change behaviour.
        mutant = root / "mutant" / "paper_search_mcp"
        mutant.mkdir(parents=True)
        src = VENDORED_TREE / "source_status.py"
        if src.exists():
            text = src.read_text(encoding="utf-8")
            checks.append(("the mutation target exists in source_status.py", MUTATION_FROM in text))
            (mutant / "source_status.py").write_text(
                text.replace(MUTATION_FROM, MUTATION_TO, 1), encoding="utf-8")
            mutated = (mutant / "source_status.py").read_text(encoding="utf-8")
            checks.append(("the mutation changes the constant",
                           MUTATION_TO in mutated and MUTATION_FROM not in mutated))
        else:
            checks.append(("source_status.py is present", False))

        for label, ok in checks:
            print(f"  {'PASS' if ok else 'FAIL'}  {label}")
            if not ok:
                failures.append(label)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("ci_patch_check self-test: %s" % ("OK" if not failures else "FAILED"))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
