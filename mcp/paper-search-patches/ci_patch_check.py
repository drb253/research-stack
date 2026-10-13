#!/usr/bin/env python3
"""ci_patch_check.py -- exercise the paper-search patch system on a throwaway copy.

The patch system edits a `paper_search_mcp` package that lives outside this repository
(a uv-tool install), so nothing on a push used to notice a patch that stopped applying or
a replacement that drifted from the vendored file it mirrors. This script supplies the
missing target: it copies the vendored package from the checkout into a temporary
directory, runs the real patch pipeline against that copy, and checks the result.

It proves four things, each with the exit status that matches what was found:

  1. every file the patch system's own registry writes is byte-identical to the vendored
     file it mirrors, so a reinstall cannot silently revert the fix it encodes, and no file
     in `replacements/` is dead weight that a maintainer could edit expecting an effect;
  2. `apply_patches.py` applies cleanly to a fresh copy (no MISSING/COULD NOT APPLY);
  3. the patched copy passes `audit_fix_check.py` and the availability invariant suite, and
     that suite is asserted to have actually collected its tests;
  4. the suite still FAILS on a copy with either defect deliberately reintroduced -- an
     outage named like an empty answer, and a success named like an outage -- so the checks
     above are a gate rather than an assertion in both directions.

What this does NOT establish: the vendored package in this repository is kept in the
patched state, so running the patcher against it is idempotent by construction. This gate
catches drift, breakage and a toothless suite; it does not reconstruct the fixed files
from pristine upstream 0.1.4, which would need those upstream files, and they are not
vendored here.

Exit codes: 0 pass, 1 a finding (drift, a failed patch, or a toothless check),
4 insufficient_input (a missing tree, or an import the suite needs is unavailable -- probed,
not assumed, so a partial environment cannot quietly reduce ten tests to eight).

    python3 mcp/paper-search-patches/ci_patch_check.py
    python3 mcp/paper-search-patches/ci_patch_check.py --self-test
"""
from __future__ import annotations

import argparse
import os
import re
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

#: The mutations that reintroduce the two defects the availability layer exists to prevent.
#: Applied to a copy of source_status.py; the suite must reject each one.
#:
#: Both directions are needed. The first makes an outage look like a genuine empty answer
#: (the sensitivity half). The second makes every success look like an outage (the
#: specificity half) -- and it is the one that mattered: the suite passed it until the
#: review added `AggregateStatusTests.test_success_is_not_reported_as_unavailable`.
MUTATIONS = (
    (
        "an outage is named 'empty'",
        'SOURCE_UNAVAILABLE = "unavailable"',
        'SOURCE_UNAVAILABLE = "empty"',
    ),
    (
        "a success is named 'unavailable'",
        'SOURCE_OK = "ok"',
        'SOURCE_OK = "unavailable"',
    ),
)


class Finding(Exception):
    """One check failed for a reason that is about the artefact under test."""


def check(label: str, ok: bool) -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        raise Finding(label)


#: Files kept in sync with a vendored file but never written by the patch system, because
#: upstream already ships them. Each needs a written reason: an unexplained unconsumed file
#: is how a directory that calls itself the single source of truth accumulates dead code.
MIRRORS = {
    "chemrxiv.py": "upstream 0.1.4 already ships academic_platforms/chemrxiv.py; this copy is "
                   "kept byte-identical so a re-vendor cannot silently drop the fix",
}

#: Floor on the availability suite's collected test count -- the number it defines. A
#: suite that collects nothing exits 0, which would make every check below a pass with no
#: tests behind it; the floor is the count itself so a *reduction* is a finding.
MIN_AVAILABILITY_TESTS = 15


def registry_pairs(replacements: Path, vendored: Path) -> list:
    """`(source, vendored target)` for every file the patch system writes.

    Driven by `apply_patches.py`'s own `COPIES`/`NEWFILES` registry rather than by globbing
    `replacements/`: the registry is what actually runs, so a vendored file that was deleted
    or renamed is a finding here, whereas a filename glob would silently skip it.
    """
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import apply_patches

    pairs = []
    for item in list(apply_patches.COPIES) + list(apply_patches.NEWFILES):
        pairs.append((replacements.parent / item["copy"], vendored / item["target"]))
    return pairs


def replacement_problems(pairs: list, repo: Path) -> list:
    """Every way a registry entry can fail to mirror the vendored file it encodes."""
    problems = []
    for source, target in pairs:
        label = source.name
        if not source.exists():
            problems.append("%s: named by the registry but not present in replacements/" % label)
            continue
        if not target.exists():
            try:
                where = target.relative_to(repo)
            except ValueError:
                where = target
            problems.append("%s: the vendored file it mirrors is gone (%s)" % (label, where))
            continue
        if source.read_bytes() != target.read_bytes():
            problems.append("%s: drifted from %s" % (label, target.name))
    return problems


def mirror_problems(mirrors: dict, replacements: Path, vendored: Path) -> list:
    """Byte-identity for files deliberately kept in sync but never applied."""
    problems = []
    for name, why in sorted(mirrors.items()):
        source = replacements / name
        if not source.exists():
            problems.append("%s: declared a mirror (%s) but missing" % (name, why))
            continue
        hits = list(vendored.rglob(name))
        if not hits:
            problems.append("%s: declared a mirror but has no vendored counterpart" % name)
        elif not any(hit.read_bytes() == source.read_bytes() for hit in hits):
            problems.append("%s: declared a mirror but drifted from its vendored counterpart" % name)
    return problems


def unconsumed_replacements(pairs: list, replacements: Path, mirrors: dict) -> list:
    """Files in `replacements/` that nothing reads: not applied, not a declared mirror."""
    consumed = {source.name for source, _ in pairs}
    return sorted(
        path.name
        for path in replacements.glob("*.py")
        if path.name not in consumed and path.name not in mirrors
    )


def ran_test_count(stderr: str) -> int:
    """The `Ran N tests` count unittest prints, or 0 if it printed none."""
    match = re.search(r"Ran (\d+) tests?", stderr or "")
    return int(match.group(1)) if match else 0


def run(argv: list, env: dict | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, env=env, cwd=cwd)


def copy_tree(destination: Path) -> Path:
    """Copy the vendored package to `destination/paper_search_mcp` and return the parent."""
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(VENDORED, destination / "paper_search_mcp")
    return destination


#: What the availability suite needs to import. The suite stubs `requests`, and several of
#: its tests import `paper_search_mcp.server`, which imports the rest at module level.
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
    print("== 1. every applied file mirrors its vendored counterpart ==")
    try:
        pairs = registry_pairs(REPLACEMENTS, VENDORED_TREE)
    except Exception as exc:  # noqa: BLE001 - the registry is itself under test here
        # Same class as the missing-mutation-target case: a checker that dies with a
        # traceback tells the reader nothing about what to fix. The registry is what step 1
        # checks, so failing to read it is a finding about the patch system, not a crash.
        print(f"  FAIL  the patch registry could not be read: {type(exc).__name__}: {exc}")
        failures.append("the patch registry could not be read")
        pairs = None

    if pairs is not None:
        problems = replacement_problems(pairs, REPO) + mirror_problems(MIRRORS, REPLACEMENTS, VENDORED_TREE)
        try:
            check("every replacement the registry writes matches its vendored file", not problems)
        except Finding as exc:
            failures.append(str(exc))
            for problem in problems:
                print(f"    {problem}")

        unconsumed = unconsumed_replacements(pairs, REPLACEMENTS, MIRRORS)
        try:
            check("no file in replacements/ is read by nothing", not unconsumed)
        except Finding as exc:
            failures.append(str(exc))
            for name in unconsumed:
                print(f"    {name}: applied by no registry entry and not a declared mirror")

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
        ran = ran_test_count(suite.stderr)
        try:
            check("the availability suite passes on the patched copy", suite.returncode == 0)
            # A suite that collected nothing also exits 0. Assert the tests exist, or every
            # check above is a pass with no tests behind it.
            check("the suite collected its tests (ran %d, floor %d)" % (ran, MIN_AVAILABILITY_TESTS),
                  ran >= MIN_AVAILABILITY_TESTS)
        except Finding as exc:
            failures.append(str(exc))
            print("    " + "\n    ".join(suite.stderr.strip().splitlines()[-6:] or [""]))

        print("\n== 5. the same suite still rejects both defects (mutation probes) ==")
        for index, (label, before, after) in enumerate(MUTATIONS, start=1):
            mutant = copy_tree(root / ("mutant%d" % index))
            status_file = mutant / "paper_search_mcp" / "source_status.py"
            text = status_file.read_text(encoding="utf-8")
            if before not in text:
                try:
                    check("the mutation target is present for '%s' (not silently skipped)"
                          % label, False)
                except Finding as exc:
                    failures.append(str(exc))
                continue
            status_file.write_text(text.replace(before, after, 1), encoding="utf-8")
            mutant_env = dict(os.environ, PAPER_SEARCH_MCP_PATH=str(mutant),
                              PYTHONPATH=str(mutant))
            probe = run([arguments.python, str(AVAILABILITY_TEST)], env=mutant_env)
            probe_ran = ran_test_count(probe.stderr)
            try:
                check("the suite fails on a copy where %s" % label, probe.returncode != 0)
                # ...and fails because a test failed, not because the copy could not be
                # imported: a crash on import also exits non-zero and would look like a
                # working probe.
                check("the mutant for '%s' failed its tests rather than failing to import "
                      "(ran %d)" % (label, probe_ran),
                      probe_ran >= MIN_AVAILABILITY_TESTS)
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
    """Pin the detections this script depends on: registry drift, dead files, the count."""
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
        (rep / "gone.py").write_text("z = 1\n", encoding="utf-8")          # target missing
        (rep / "unlisted.py").write_text("q = 1\n", encoding="utf-8")      # read by nothing
        (rep / "mirrored.py").write_text("m = 1\n", encoding="utf-8")
        (vend / "mirrored.py").write_text("m = 1\n", encoding="utf-8")
        (vend / "nested").mkdir()
        (rep / "nested.py").write_text("y = 3\n", encoding="utf-8")
        (vend / "nested" / "nested.py").write_text("y = 3\n", encoding="utf-8")

        pairs = [
            (rep / "same.py", vend / "same.py"),
            (rep / "differs.py", vend / "differs.py"),
            (rep / "gone.py", vend / "gone.py"),
            (rep / "nested.py", vend / "nested" / "nested.py"),
            (rep / "mirrored.py", vend / "mirrored.py"),
        ]
        problems = replacement_problems(pairs, repo=root)
        mirrors = {"mirrored.py": "kept in sync on purpose"}

        checks = [
            ("an identical pair is not reported", not any("same.py" in p for p in problems)),
            ("a byte difference is reported", any("differs.py" in p for p in problems)),
            ("a missing vendored target is reported", any("gone.py" in p for p in problems)),
            ("a nested vendored match counts", not any("nested.py" in p for p in problems)),
            ("a declared mirror is checked for drift",
             mirror_problems(mirrors, rep, vend) == []),
            ("a dead file is reported",
             unconsumed_replacements(pairs, rep, mirrors) == ["unlisted.py"]),
            ("a file read by nothing is not silently allowed",
             "unlisted.py" in unconsumed_replacements(pairs, rep, {})),
            ("a drifted mirror is reported",
             mirror_problems({"mirrored.py": "why"}, rep, vend / "nested") != []),
            ("the test-count parser reads unittest output",
             ran_test_count("Ran 10 tests in 0.3s\n\nOK\n") == 10),
            ("the test-count parser reports zero when nothing ran",
             ran_test_count("ModuleNotFoundError: No module named 'mcp'\n") == 0),
        ]
        # Every mutation must have a target that exists and that changes the constant.
        mutant = root / "mutant" / "paper_search_mcp"
        mutant.mkdir(parents=True)
        src = VENDORED_TREE / "source_status.py"
        if src.exists():
            text = src.read_text(encoding="utf-8")
            for label, before, after in MUTATIONS:
                checks.append(("the mutation target for '%s' exists" % label, before in text))
                mutated = text.replace(before, after, 1)
                checks.append(("the mutation for '%s' changes the constant" % label,
                               after in mutated and before not in mutated))
        else:
            checks.append(("source_status.py is present", False))
        # The registry this gate is driven by must itself be non-empty, or step 1 would
        # pass vacuously over zero pairs.
        real_pairs = registry_pairs(REPLACEMENTS, VENDORED_TREE)
        checks.append(("the patch registry names files to check", len(real_pairs) >= 30))

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
