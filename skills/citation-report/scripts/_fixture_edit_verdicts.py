"""Test helper: rewrite one verdict in a recorded file.

Used by `selftest.sh` to prove that `report --verdicts` renders the recorded file rather
than re-classifying, and that a file contradicting the rule table is rejected on load.
Lives here rather than being inlined as a heredoc because the harness already uses heredocs
to build fixtures, and nesting them is how a test silently stops testing anything.

Usage: _fixture_edit_verdicts.py <in.json> <rule_id> <state> <out.json>
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    if len(sys.argv) != 5:
        print("usage: _fixture_edit_verdicts.py <in.json> <rule_id> <state> <out.json>")
        return 2
    source, rule_id, state, target = sys.argv[1:5]
    payload = json.load(open(source, encoding="utf-8"))
    changed = False
    for row in payload.get("verdicts", []):
        if row.get("state") == "conflict":
            row["rule_id"], row["state"] = rule_id, state
            changed = True
            break
    if not changed:
        # Nothing to rewrite: fall back to the first verdict so the fixture still exists
        # and the assertion fails on its own terms rather than on a missing file.
        if payload.get("verdicts"):
            payload["verdicts"][0]["rule_id"], payload["verdicts"][0]["state"] = rule_id, state
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
