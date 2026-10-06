#!/usr/bin/env python3
"""audit_fix_check.py -- prove the MeSH audit fix is present and working.

Run after apply_patches.py. Exit 0 = fix present in files; if the uv-tool python
exists it also asserts the live behaviour (screening -> descriptors).
"""
from __future__ import annotations

import glob
import os
import subprocess
import sys
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
PKGS = glob.glob(str(HOME / ".local/share/uv/tools/paper-search-mcp/lib/python*/"
                     "site-packages/paper_search_mcp"))

failures = []


def check(label: str, ok: bool) -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        failures.append(label)


def main() -> int:
    if not PKGS:
        print("paper-search package not found -- install the uv tool first.")
        return 1
    pkg = Path(PKGS[0])

    qp = (pkg / "query_planning.py")
    srv = (pkg / "server.py")
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

    # live behavioural check via the tool venv (best effort)
    tool_py = HOME / ".local/share/uv/tools/paper-search-mcp/bin/python"
    if tool_py.exists():
        code = (
            "from paper_search_mcp.query_planning import mesh_terms as m;"
            "assert m('screening')==['mass screening','early detection of cancer'], m('screening');"
            "assert m('heart attack')==['myocardial infarction'], m('heart attack');"
            "print('ok')"
        )
        r = subprocess.run([str(tool_py), "-c", code],
                           capture_output=True, text=True)
        check("live mesh_terms(screening) == descriptors", r.returncode == 0)
        if r.returncode != 0:
            print("      " + (r.stderr or r.stdout).strip().splitlines()[-1])

    print(f"\naudit-fix check: {'OK' if not failures else 'FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
