#!/usr/bin/env bash
# Short wrapper for the originality toolkit (option 2: run it yourself).
#
#   ./check.sh draft.html                      report to stdout
#   ./check.sh draft.html --out report.md      write a report
#   ./check.sh --help
#
# Every argument is forwarded to originality_check.py unchanged.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$HERE/originality_check.py" "$@"
