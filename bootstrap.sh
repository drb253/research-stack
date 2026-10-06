#!/usr/bin/env bash
# bootstrap.sh -- one-command installer for research-stack.
#
#   curl -fsSL https://raw.githubusercontent.com/<you>/research-stack/main/bootstrap.sh | bash
#
# Pass install flags after `-s --`, e.g.:
#   ... | bash -s -- --targets cline,claude,opencode --email you@org
#
# Env: RESEARCH_STACK_REPO (git url), RESEARCH_STACK_REF (branch/tag, default main),
#      RESEARCH_STACK_HOME (clone dir, default ~/.research-stack-src)
set -euo pipefail
REPO="${RESEARCH_STACK_REPO:-https://github.com/REPLACE_ME/research-stack.git}"
REF="${RESEARCH_STACK_REF:-main}"
DEST="${RESEARCH_STACK_HOME:-$HOME/.research-stack-src}"

echo "research-stack bootstrap"
echo "  repo: $REPO"
echo "  ref:  $REF"
echo "  dest: $DEST"

command -v git >/dev/null 2>&1 || { echo "ERROR: git is required" >&2; exit 1; }

if [ -d "$DEST/.git" ]; then
  git -C "$DEST" fetch --depth 1 origin "$REF"
  git -C "$DEST" checkout -q FETCH_HEAD
else
  git clone --depth 1 --branch "$REF" "$REPO" "$DEST"
fi

exec bash "$DEST/install.sh" "$@"
