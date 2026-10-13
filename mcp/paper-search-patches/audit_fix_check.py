#!/usr/bin/env python3
"""audit_fix_check.py -- prove the MeSH audit fix is present in a patched package.

Checks the files, and additionally asserts the live behaviour through the uv-tool python
when that interpreter exists. Two exit vocabularies, kept apart on purpose:

    0  the fix is present
    1  a finding: a patched file is there but the fix is missing from it
    4  insufficient_input: there is no package to check (nothing was verified either way)

The fourth case used to be reported as exit 1 with an "install the uv tool first" line,
which put "there is nothing here" in the same channel as "here is what is wrong with it".
Point the check at any tree with `--package <path>` or `PAPER_SEARCH_MCP_PATH=<path>`; the
CI gate uses that to check a throwaway copy made from the checkout.
"""
from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
PKG_GLOBS = [
    str(HOME / ".local/share/uv/tools/paper-search-mcp/lib/python*/site-packages/paper_search_mcp"),
]
TOOL_PY = HOME / ".local/share/uv/tools/paper-search-mcp/bin/python"
PACKAGE_ENV = "PAPER_SEARCH_MCP_PATH"

failures: list = []


def check(label: str, ok: bool) -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        failures.append(label)


def resolve(explicit: str | None) -> Path | None:
    """The package to inspect: `--package`, then the env var, then the uv install."""
    for label, raw in (("--package", explicit), ("$" + PACKAGE_ENV, os.environ.get(PACKAGE_ENV, ""))):
        raw = (raw or "").strip()
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if candidate.name != "paper_search_mcp" and (candidate / "paper_search_mcp").is_dir():
            candidate = candidate / "paper_search_mcp"
        if candidate.is_dir():
            return candidate
        # An explicit instruction that does not resolve is an input gap, not a licence to
        # inspect a different install.
        print(f"nothing was checked: {label} names {raw}, which is not a package directory.")
        return None
    for pattern in PKG_GLOBS:
        for hit in glob.glob(pattern):
            return Path(hit)
    return None


def missing_package(explicit: str | None) -> int:
    print("STATUS: insufficient_input")
    print("nothing was checked: no paper_search_mcp package was found.")
    print("input_gaps:")
    print("  - kind: package_not_found")
    print("    how_to_close: install the uv tool (`uv tool install paper-search-mcp`)")
    print(f"      or pass --package <path> / set {PACKAGE_ENV}=<path>")
    if explicit:
        print(f"    searched: {explicit} (--package)")
    override = os.environ.get(PACKAGE_ENV, "").strip()
    if override:
        print(f"    searched: {override} (${PACKAGE_ENV})")
    print(f"    searched: {PKG_GLOBS[0]}")
    return 4


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check that the MeSH audit fix is present in a paper_search_mcp package."
    )
    parser.add_argument(
        "--package",
        default=None,
        help="path to the paper_search_mcp package (or its parent); "
             f"defaults to the uv-tool install or ${PACKAGE_ENV}",
    )
    arguments = parser.parse_args()

    pkg = resolve(arguments.package)
    if pkg is None:
        return missing_package(arguments.package)

    qp = pkg / "query_planning.py"
    srv = pkg / "server.py"
    check("query_planning.py present", qp.exists())
    check("server.py present", srv.exists())
    if qp.exists():
        text = qp.read_text(encoding="utf-8", errors="ignore")
        check("query_planning has _MESH_TERM_RE (authoritative MeSH)",
              "_MESH_TERM_RE" in text and "[MeSH Terms]" in text)
        check("query_planning skips qualifier subheadings",
              "ds_recordtype" in text and "qualifier" in text)
    if srv.exists():
        text = srv.read_text(encoding="utf-8", errors="ignore")
        check("get_mesh_details skips qualifier subheadings",
              "ds_recordtype" in text and "qualifier" in text)

    # Live behavioural check through the tool venv. This tier is a property of the
    # machine, not of the package under test, so an absent interpreter is reported as
    # unchecked -- never as a failure of the fix. It also only runs when the package being
    # checked IS the one that interpreter imports (the uv install); otherwise the check
    # would report on a tree nobody asked about.
    overridden = bool((arguments.package or "").strip() or os.environ.get(PACKAGE_ENV, "").strip())
    if not TOOL_PY.exists():
        print("  SKIP  live behaviour: no uv-tool interpreter here, so it is not checked")
    elif overridden:
        print("  SKIP  live behaviour: a --package/${%s} tree is checked from files only"
              % PACKAGE_ENV)
    else:
        code = (
            "from paper_search_mcp.query_planning import mesh_terms as m;"
            "assert m('screening')==['mass screening','early detection of cancer'], m('screening');"
            "assert m('heart attack')==['myocardial infarction'], m('heart attack');"
            "print('ok')"
        )
        r = subprocess.run([str(TOOL_PY), "-c", code], capture_output=True, text=True)
        check("live mesh_terms(screening) == descriptors", r.returncode == 0)
        if r.returncode != 0:
            print("      " + (r.stderr or r.stdout).strip().splitlines()[-1])

    print(f"\naudit-fix check: {'OK' if not failures else 'FAILED'}")
    print(f"package: {pkg}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
