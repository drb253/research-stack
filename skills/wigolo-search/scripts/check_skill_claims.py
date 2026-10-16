#!/usr/bin/env python3
"""check_skill_claims.py -- pin the claims in skills/wigolo-search/SKILL.md.

The skill is instructions a model acts on, so its tool list, its keyed engines and
its Scholar limit are the parts a rewrite can silently drop. This gate holds the
file to those claims.

Five invariants, per run:
  1. every canonical tool name of the server appears in the file;
  2. the file states the tool count, and that count agrees with the list here;
  3. every keyed engine names its own environment variable;
  4. every canonical engine name appears in the file;
  5. the file denies the Google Scholar reading of itself.

The canonical lists come from the live server: `wigolo doctor` printed the engine
table, and the MCP `tools/list` printed the ten tool names on 2026-10-16. Update
this file and `SKILL.md` together when the server changes. CI runs no server, so a
stale constant must fail loudly here instead of passing quietly.

Exit codes (the repository's convention):
  0  every invariant holds
  1  at least one invariant failed
  4  input gap -- the skill file is missing or unreadable   (never a pass)

Usage:
  python3 check_skill_claims.py                       # the skill beside this script
  python3 check_skill_claims.py --check FILE          # any candidate
  python3 check_skill_claims.py --self-test
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SKILL = os.path.join(HERE, os.pardir, "SKILL.md")

# Verified against the live server on 2026-10-16 (`tools/list`, `wigolo doctor`).
TOOLS = ("search", "fetch", "crawl", "cache", "extract", "find_similar",
         "research", "agent", "diff", "watch")
ENGINES = ("bing", "duckduckgo", "mojeek", "marginalia", "wikipedia", "devdocs",
           "mdn", "stackoverflow", "bing_news", "hn-algolia", "lobsters",
           "arxiv", "semantic-scholar", "ddg-image")
KEYED_ENGINES = {"brave": "BRAVE_API_KEY", "github-code": "WIGOLO_GITHUB_TOKEN"}
TOOL_COUNT_WORDS = {10: "ten"}
DEFAULT_VARIABLE = "WIGOLO_GITHUB_TOKEN"
SCHOLAR_DENIAL = re.compile(r"not\s+google\s+scholar", re.I)


def read(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def check_text(text):
    """Return a list of (name, ok, detail) rows for one candidate file."""
    rows = []
    for tool in TOOLS:
        ok = re.search(r"`%s`" % re.escape(tool), text) is not None
        rows.append(("tool `%s`" % tool, ok, "" if ok else "the name is absent"))

    count = len(TOOLS)
    word = TOOL_COUNT_WORDS.get(count, str(count))
    stated = re.search(r"\b(%s|%d)\s+tools\b" % (word, count), text, re.I) is not None
    rows.append(("the tool count is stated", stated,
                 "" if stated else "no '%s tools' phrase for a list of %d" % (word, count)))

    for engine, variable in sorted(KEYED_ENGINES.items()):
        named = re.search(r"`%s`" % re.escape(engine), text) is not None
        has_var = variable in text
        detail = ""
        if not named:
            detail = "the engine name is absent"
        elif not has_var:
            detail = "%s is absent" % variable
        rows.append(("the keyed engine `%s` names %s" % (engine, variable),
                     named and has_var, detail))

    for engine in ENGINES:
        ok = re.search(r"`%s`" % re.escape(engine), text) is not None
        rows.append(("engine `%s`" % engine, ok, "" if ok else "the name is absent"))

    denial = SCHOLAR_DENIAL.search(text) is not None
    rows.append(("the file denies the Scholar reading", denial,
                 "" if denial else "no 'not Google Scholar' sentence"))
    return rows


# --- main -------------------------------------------------------------------- #
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Pin the claims of the wigolo-search skill.")
    parser.add_argument("--check", default=DEFAULT_SKILL, help="the candidate SKILL.md")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    try:
        text = read(args.check)
    except OSError as exc:
        print("check_skill_claims: input gap: %s" % exc, file=sys.stderr)
        return 4

    rows = check_text(text)
    bad = [row for row in rows if not row[1]]
    if not args.quiet:
        for name, ok, detail in rows:
            print("  %s %s%s" % ("PASS" if ok else "FAIL", name,
                                 " -- %s" % detail if detail else ""))
    if bad:
        print("check_skill_claims: %d of %d claim(s) failed in %s"
              % (len(bad), len(rows), args.check))
        return 1
    print("check_skill_claims: %d claim(s) hold in %s" % (len(rows), args.check))
    return 0


# --- offline self-test ------------------------------------------------------- #
def _run(argv) -> int:
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return main(argv)


def self_test() -> int:
    passed = failed = 0

    def check(name, got, want):
        nonlocal passed, failed
        if got == want:
            passed += 1
            print("  PASS %s" % name)
        else:
            failed += 1
            print("  FAIL %s (want %r, got %r)" % (name, want, got))

    try:
        live = read(DEFAULT_SKILL)
    except OSError as exc:
        print("check_skill_claims: input gap: %s" % exc, file=sys.stderr)
        return 4

    check("the live skill satisfies every claim", _run(["--check", DEFAULT_SKILL, "--quiet"]), 0)
    check("a missing file is an input gap",
          _run(["--check", "/nonexistent/SKILL.md", "--quiet"]), 4)

    with tempfile.TemporaryDirectory() as tmp:
        dropped_tool = os.path.join(tmp, "no_tool.md")
        with open(dropped_tool, "w", encoding="utf-8") as handle:
            handle.write(live.replace("| `watch` |", ""))
        check("a dropped tool name fails", _run(["--check", dropped_tool, "--quiet"]), 1)

        no_denial = os.path.join(tmp, "no_denial.md")
        with open(no_denial, "w", encoding="utf-8") as handle:
            handle.write(re.sub(r"not\s+google\s+scholar", "a search index", live, flags=re.I))
        check("a dropped Scholar denial fails", _run(["--check", no_denial, "--quiet"]), 1)

        no_variable = os.path.join(tmp, "no_variable.md")
        with open(no_variable, "w", encoding="utf-8") as handle:
            handle.write(live.replace(DEFAULT_VARIABLE, "SOME_OTHER_VARIABLE"))
        check("a dropped key variable fails", _run(["--check", no_variable, "--quiet"]), 1)

    print("check_skill_claims: %d passed, %d failed" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
