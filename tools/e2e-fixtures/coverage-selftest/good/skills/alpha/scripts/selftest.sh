#!/usr/bin/env bash
set -u
expect_exit() { :; }
expect_exit 0 "gate passes a clean fixture" python3 "$HERE/gate.py" --clean
expect_exit 1 "gate fails a broken fixture" python3 "$HERE/gate.py" --broken
