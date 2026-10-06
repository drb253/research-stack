#!/usr/bin/env bash
# publish.sh -- set your GitHub owner everywhere and push research-stack.
#
# Usage:
#   ./publish.sh --user <github-user> [--repo research-stack] [--branch main] [--no-push]
#
# Replaces every REPLACE_ME in README.md + bootstrap.sh with <github-user>,
# commits, sets the origin remote, and pushes. With --no-push it prints the exact
# push command instead (use it when you have not authenticated yet).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER=""; REPO="research-stack"; BRANCH="main"; PUSH=1
while [ $# -gt 0 ]; do
  case "$1" in
    --user) USER="$2"; shift 2;;
    --repo) REPO="$2"; shift 2;;
    --branch) BRANCH="$2"; shift 2;;
    --no-push) PUSH=0; shift;;
    -h|--help) sed -n '2,9p' "$0"; exit 0;;
    *) echo "unknown option: $1" >&2; exit 1;;
  esac
done
[ -n "$USER" ] || { echo "ERROR: --user <github-user> is required" >&2; exit 1; }

cd "$ROOT"
echo "Owner: $USER   Repo: $REPO   Branch: $BRANCH"

# 1. Stamp the owner into the docs / bootstrap (portable in-place sed).
sed -i.bak "s/REPLACE_ME/$USER/g" README.md bootstrap.sh && rm -f README.md.bak bootstrap.sh.bak
if grep -rq 'REPLACE_ME' README.md bootstrap.sh; then
  echo "ERROR: REPLACE_ME still present after substitution" >&2; exit 1
fi
echo "  stamped owner into README.md + bootstrap.sh"

# 2. Commit the change.
git add -A
if git diff --cached --quiet; then
  echo "  (owner already set -- nothing to commit)"
else
  git commit -q -m "set repo owner to $USER"
  echo "  committed"
fi

# 3. Point origin at the new repo.
URL="https://github.com/$USER/$REPO.git"
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$URL"
else
  git remote add origin "$URL"
fi
git branch -M "$BRANCH" 2>/dev/null || true
echo "  origin -> $URL"

# 4. Push (or explain how).
if [ "$PUSH" = 0 ]; then
  echo
  echo "Not pushing (--no-push). Next:"
  echo "  # create the repo once (web: https://github.com/new  OR:  brew install gh && gh auth login)"
  echo "  gh repo create $REPO --public --source=. --push"
  echo "  # or, if the repo already exists:"
  echo "  git push -u origin $BRANCH"
  exit 0
fi

if git push -u origin "$BRANCH"; then
  echo
  echo "Pushed. Anyone can now install with:"
  echo "  curl -fsSL https://raw.githubusercontent.com/$USER/$REPO/$BRANCH/bootstrap.sh | bash"
else
  echo "Push failed -- authenticate first (gh auth login, or a PAT/SSH key), then: git push -u origin $BRANCH" >&2
  exit 1
fi
