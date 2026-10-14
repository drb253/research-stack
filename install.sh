#!/usr/bin/env bash
# research-stack installer
#   Installs the review/synthesis MCP servers + skills and wires them into
#   Cline, Claude, OpenCode, DeepSeek Harness (and optionally Gemini / LM Studio).
#
# Usage:
#   ./install.sh [options]
# Options:
#   --targets LIST     comma list: cline,claude,opencode,gemini,lmstudio,dsh  (default: cline)
#   --no-mcp           install skills only
#   --no-skills        configure MCP only
#   --with-upstream-skills  clone the K-Dense scientific skills (default)
#   --no-upstream-skills    skip the upstream scientific skills
#   --with-ncbi / --with-academic-search   include those servers in the config
#   --copy-skills      copy skills instead of symlinking
#   --reinstall        reinstall/upgrade the paper-search tool first
#   --with-r           install the R meta-analysis packages (slow; needs R)
#   --with-runtime     also create the Python toolchain venv (scipy/pandas/...)
#   --email ADDR       NCBI/polite-pool email        (env NCBI_EMAIL)
#   --ncbi-key KEY     NCBI API key                  (env NCBI_API_KEY)
#   --s2-key KEY       Semantic Scholar key          (env S2_API_KEY)
#   --dry-run          print what would happen, change nothing
#   -h|--help
set -euo pipefail

VERSION="1.1.1"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STORE="$HOME/.research-stack"
DRY_RUN=0
TARGETS="cline"
DO_SKILLS=1
DO_MCP=1
COPY_SKILLS=0
WITH_UPSTREAM=1
WITH_AIPOCH=0
INSTALL_NCBI=1
INSTALL_ACADEMIC=1
INSTALL_RENDER=1
INSTALL_R=1
REINSTALL=0
WITH_RUNTIME=0
FROM_PYPI=0
NCBI_EMAIL="${NCBI_EMAIL:-}"
NCBI_API_KEY="${NCBI_API_KEY:-}"
S2_API_KEY="${S2_API_KEY:-}"
BELL=$'\a'

info() { printf '  %s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
warn() { printf '  ! %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
run()  { if [ "$DRY_RUN" = 1 ]; then printf '  [dry-run] %s\n' "$*"; else eval "$@"; fi; }
have() { command -v "$1" >/dev/null 2>&1; }

# Back up a path that is about to be replaced, with the same ordinal-backup
# convention as install_skill: a second-resolution timestamp can collide, and
# `mv dir existing-dir` would then nest the tree instead of backing it up. The
# store (~/.research-stack) is regenerated on every install, so a user edit there
# used to vanish silently; this keeps the previous copy and says so.
backup_store() {
  [ -e "$1" ] || return 0
  local bak n
  bak="$1.bak-$(date +%Y%m%d%H%M%S)"; n=1
  while [ -e "$bak" ]; do bak="$1.bak-$(date +%Y%m%d%H%M%S)-$n"; n=$((n+1)); done
  [ "$DRY_RUN" = 1 ] || warn "  $1 is replaced -> kept as $(basename "$bak")"
  run "mv '$1' '$bak'"
}

# Install one skill into a target directory without ever destroying something a
# user put there. The target is only rewritten when it is a symlink (ours, or a
# leftover) or an out-of-date copy: a real file or directory that differs is
# moved aside to <name>.bak-<timestamp> first, the same way the MCP config
# writers back up a config they rewrite. A target that already matches the
# requested mode is left alone, so re-running install.sh neither churns the tree
# nor accumulates backups. Switching modes (symlink <-> --copy-skills) does
# convert an existing target rather than silently keeping the old mode.
install_skill() {
  src="$1"; sdir="$2"; name="$3"; dest="$sdir/$name"
  if [ -L "$dest" ]; then
    # A correct symlink satisfies symlink mode; copy mode must replace it.
    # Compare with trailing slashes stripped: install-dsh.sh writes the same
    # link without one, and alternating the two installers must not churn.
    cur="$(readlink "$dest")"; cur="${cur%/}"; want="${src%/}"
    if [ "$COPY_SKILLS" != 1 ] && [ "$cur" = "$want" ]; then return 0; fi
    run "rm -f '$dest'"
  elif [ -e "$dest" ]; then
    # An identical copy satisfies copy mode. Compare the trees rather than a
    # timestamp: cp -R does not preserve mtimes, so a time test would churn.
    if [ "$COPY_SKILLS" = 1 ] && [ -d "$dest" ] && diff -rq "$src" "$dest" >/dev/null 2>&1; then
      return 0
    fi
    # Unique backup name: a second-resolution timestamp can collide, and
    # `mv dir existing-dir` would then nest the tree instead of backing it up.
    bak="$dest.bak-$(date +%Y%m%d%H%M%S)"; n=1
    while [ -e "$bak" ]; do bak="$dest.bak-$(date +%Y%m%d%H%M%S)-$n"; n=$((n+1)); done
    warn "  $dest does not match the requested install -> kept as $(basename "$bak")"
    run "mv '$dest' '$bak'"
  fi
  if [ "$COPY_SKILLS" = 1 ]; then
    run "cp -R '$src' '$dest'"
  else
    run "ln -s '$src' '$dest'"
  fi
}

usage() {
  cat <<'EOF'
research-stack installer -- review MCPs + skills for Cline / Claude / OpenCode / DeepSeek Harness.

Usage: ./install.sh [options]
Options:
  --targets LIST     cline,claude,opencode,gemini,lmstudio,dsh  (default: cline)
  --no-mcp           install skills only
  --no-skills        configure MCP only
  --with-upstream-skills   (default) also clone the 160+ K-Dense scientific skills
  --no-upstream-skills     skip the upstream scientific skills
  --with-aipoch-skills     also clone AIPOCH medical-research-skills (460+, third-party, not gated)
  --copy-skills      copy skills instead of symlinking
  --reinstall        reinstall/upgrade the paper-search tool first
  --no-ncbi / --no-academic-search / --no-render / --no-r   skip a default step
  --minimal          skip ncbi, academic-search, render toolchain and R packages
  --from-pypi        install paper-search from PyPI + apply patches (legacy) instead of vendored
  --with-runtime     also create the Python toolchain venv (scipy/pandas/...)
  --email ADDR       NCBI / polite-pool email         (env NCBI_EMAIL)
  --ncbi-key KEY     NCBI API key                     (env NCBI_API_KEY)
  --s2-key KEY       Semantic Scholar key             (env S2_API_KEY)
  --dry-run          print what would happen, change nothing
  -h|--help
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --targets) TARGETS="$2"; shift 2;;
    --targets=*) TARGETS="${1#*=}"; shift;;
    --no-mcp) DO_MCP=0; shift;;
    --no-skills) DO_SKILLS=0; shift;;
    --with-upstream-skills) WITH_UPSTREAM=1; shift;;
    --no-upstream-skills) WITH_UPSTREAM=0; shift;;
    --with-aipoch-skills) WITH_AIPOCH=1; shift;;
    --with-ncbi) INSTALL_NCBI=1; shift;;
    --with-academic-search) INSTALL_ACADEMIC=1; shift;;
    --no-ncbi) INSTALL_NCBI=0; shift;;
    --no-academic-search) INSTALL_ACADEMIC=0; shift;;
    --no-render) INSTALL_RENDER=0; shift;;
    --no-r) INSTALL_R=0; shift;;
    --minimal) INSTALL_NCBI=0; INSTALL_ACADEMIC=0; INSTALL_RENDER=0; INSTALL_R=0; shift;;
    --from-pypi) FROM_PYPI=1; shift;;
    --copy-skills) COPY_SKILLS=1; shift;;
    --reinstall) REINSTALL=1; shift;;
    --email) NCBI_EMAIL="$2"; shift 2;;
    --ncbi-key) NCBI_API_KEY="$2"; shift 2;;
    --s2-key) S2_API_KEY="$2"; shift 2;;
    --with-r) INSTALL_R=1; shift;;
    --with-runtime) WITH_RUNTIME=1; shift;;
    --dry-run) DRY_RUN=1; shift;;
    -h|--help) usage; exit 0;;
    *) die "unknown option: $1 (try --help)";;
  esac
done
export NCBI_EMAIL NCBI_API_KEY S2_API_KEY

# ---- platform maps --------------------------------------------------------- #
skills_dir_for() {
  case "$1" in
    cline)     echo "$HOME/.cline/skills";;
    claude)    echo "$HOME/.claude/skills";;
    opencode)  echo "$HOME/.config/opencode/skills";;
    gemini)    echo "$HOME/.gemini/skills";;
    lmstudio)  echo "$HOME/.lmstudio/skills";;
    dsh)       echo "$HOME/.dsh/skills";;
    codex)     echo "$HOME/.codex/skills";;
    *)         echo "";;
  esac
}

# ---- optional component installers ----------------------------------------- #
install_ncbi() {
  DEST="$HOME/.local/share/ncbi-mcp-server"
  SRC="$ROOT/mcp/ncbi-mcp-server"
  [ -d "$SRC/src/ncbi_mcp_server" ] || { warn "vendored ncbi source missing in repo (skipping)"; return 1; }
  if [ -x "$DEST/.venv/bin/python" ] && [ -d "$DEST/src/ncbi_mcp_server" ]; then
    info "ncbi already installed"; return 0
  fi
  info "installing ncbi MCP (vendored source + venv)..."
  run "rm -rf '$DEST' && mkdir -p '$(dirname "$DEST")' && cp -R '$SRC' '$DEST'"
  run "uv venv '$DEST/.venv'" || { warn "ncbi venv failed"; return 1; }
  run "uv pip install --python '$DEST/.venv/bin/python' 'mcp>=1.0.0,<2' 'httpx>=0.25.0' typing-extensions python-dotenv aiofiles" \
    || warn "ncbi dependency install failed"
  info "ncbi -> $DEST"
}

install_academic_search() {
  DEST="$HOME/.local/share/academic-search-mcp"
  if [ -x "$DEST/.venv/bin/academic-search" ]; then
    info "academic-search already installed"; return 0
  fi
  SRC="$ROOT/mcp/academic-search-mcp"
  [ -d "$SRC" ] || { warn "academic-search source missing in repo (skipping)"; return 1; }
  info "installing academic-search MCP (vendored source + venv)..."
  run "rm -rf '$DEST' && mkdir -p '$(dirname "$DEST")' && cp -R '$SRC' '$DEST'"
  run "uv venv '$DEST/.venv'" || { warn "academic-search venv failed"; return 1; }
  run "uv pip install --python '$DEST/.venv/bin/python' -e '$DEST'" \
    || warn "academic-search dependency install failed"
  info "academic-search -> $DEST"
}

install_render() {
  DEST="$HOME/.local/share/browser-probe"
  REQ="$ROOT/mcp/optional/browser-probe.requirements.txt"
  [ -f "$REQ" ] || { warn "browser-probe requirements missing (skipping)"; return 1; }
  if [ -x "$DEST/.venv/bin/python" ] && \
     "$DEST/.venv/bin/python" -c 'import playwright,pypdf,pypdfium2,reportlab,PIL' >/dev/null 2>&1; then
    info "render/PDF toolchain already installed"; return 0
  fi
  info "installing render/PDF toolchain (browser-probe; downloads chromium)..."
  run "uv venv '$DEST/.venv'" || { warn "render venv failed"; return 1; }
  run "uv pip install --python '$DEST/.venv/bin/python' -r '$REQ'" \
    || { warn "render deps install failed"; return 1; }
  run "'$DEST/.venv/bin/playwright' install chromium" || warn "chromium download failed"
  info "render toolchain -> $DEST"
}

# ---- prerequisites --------------------------------------------------------- #
step "0. Prerequisites"
[ "$(uname)" = "Darwin" ] && OS=mac || OS=linux
info "OS: $OS   arch: $(uname -m)"

have git  || die "git is required"
have curl || die "curl is required"
have python3 || die "python3 is required"

if ! have uv; then
  warn "uv not found -> installing (astral.sh)"
  run "curl -LsSf https://astral.sh/uv/install.sh | sh"
  export PATH="$HOME/.local/bin:$PATH"
fi
have uv && info "uv: $(uv --version 2>/dev/null || echo present)"

if ! have npx; then
  warn "node/npx not found -- 'consensus' and 'google-scholar' servers need it."
  warn "install Node.js 18+ (brew install node, or https://nodejs.org)."
else
  info "node: $(node --version)"
fi

# ---- 1. paper-search MCP --------------------------------------------------- #
if [ "$DO_MCP" = 1 ]; then
  step "1. paper-search MCP (vendored, pre-patched)"
  VENDORED="$ROOT/mcp/paper-search-mcp"
  if [ "$FROM_PYPI" = 1 ]; then
    info "legacy path: PyPI base + apply_patches"
    if [ "$REINSTALL" = 1 ]; then
      run "uv tool install --reinstall --force paper-search-mcp"
    else
      run "uv tool install paper-search-mcp"
    fi
    run "python3 '$ROOT/mcp/paper-search-patches/apply_patches.py' | tail -4"
  else
    [ -d "$VENDORED/paper_search_mcp" ] || die "vendored package missing at $VENDORED"
    if [ "$REINSTALL" = 1 ]; then
      run "uv tool install --force '$VENDORED'"
    elif have paper-search-mcp; then
      info "paper-search-mcp already on PATH (use --reinstall to refresh from the vendored copy)"
    else
      info "installing paper-search-mcp from the vendored, pre-patched source..."
      run "uv tool install '$VENDORED'"
    fi
  fi

  if [ "$DRY_RUN" = 0 ]; then
    PY="$HOME/.local/share/uv/tools/paper-search-mcp/bin/python"
    [ -x "$PY" ] && "$PY" -c "import paper_search_mcp; print('paper_search_mcp import OK')" || true
    AUD="$ROOT/mcp/paper-search-patches/audit_fix_check.py"
    if [ -f "$AUD" ]; then
      # Exit 4 means "there was no package to check", which is not a failed check: saying
      # FAILED there would report an environment gap as a defect in the fix.
      if python3 "$AUD"; then :; else
        rc=$?
        if [ "$rc" -eq 4 ]; then
          info "mesh audit-fix self-check: skipped (no paper_search_mcp package to check)"
        else
          warn "mesh audit-fix self-check FAILED (exit $rc)"
        fi
      fi
    fi
  fi

  step "1b. optional MCP servers (ncbi, academic-search)"
  if [ "$INSTALL_NCBI" = 1 ]; then install_ncbi || true; else info "ncbi: skipped (--no-ncbi)"; fi
  if [ "$INSTALL_ACADEMIC" = 1 ]; then install_academic_search || true; else info "academic-search: skipped"; fi
fi

# ---- 2. skills ------------------------------------------------------------- #
if [ "$DO_SKILLS" = 1 ]; then
  step "2. Review skills -> $STORE/skills"
  run "mkdir -p '$STORE/skills'"
  # Strip bytecode caches first: they are not part of the comparison below and
  # would otherwise make every re-run look like a change.
  run "find '$STORE/skills' -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true"
  # A store copy that already matches the repo is left alone, so a re-run neither
  # churns the tree nor accumulates backups. When it differs, the previous copy
  # is kept: the store is an install destination, but a user may have edited a
  # file there, and `cp -R` used to overwrite it silently.
  if diff -rq -x '__pycache__' "$ROOT/skills" "$STORE/skills" >/dev/null 2>&1; then
    info "skills store already matches the repo (no copy, no backup)"
  else
    backup_store "$STORE/skills"
    run "mkdir -p '$STORE/skills'"
    run "cp -R '$ROOT/skills/'* '$STORE/skills/'"
  fi
  run "find '$STORE/skills' -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true"
  info "installed $(ls -1 "$STORE/skills" 2>/dev/null | grep -vc 'VENDORED') skills"

  # ship the originality-check toolkit (the skill depends on it)
  if [ -d "$ROOT/tools/originality-toolkit" ]; then
    run "find '$STORE/originality-toolkit' -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true"
    # `attribution.py` is a SIBLING of the toolkit in the repo and is copied in
    # below, so it is excluded from the comparison: counting it would make every
    # re-run look like a change and accumulate backups. The old code `rm -rf`d
    # this directory outright, so a user edit inside it was destroyed.
    if diff -rq -x '__pycache__' -x 'attribution.py' \
         "$ROOT/tools/originality-toolkit" "$STORE/originality-toolkit" >/dev/null 2>&1; then
      info "originality-toolkit already matches the repo (no copy, no backup)"
    else
      backup_store "$STORE/originality-toolkit"
      run "cp -R '$ROOT/tools/originality-toolkit' '$STORE/originality-toolkit'"
    fi
    # The toolkit asks tools/attribution.py for the defined "plagiarism-free"
    # claim. That file is a SIBLING of the toolkit directory, so copying the
    # directory alone shipped a toolkit that could not evaluate the claim at all:
    # every run reported an input gap and never issued or withheld per condition.
    # Ship the definition beside the toolkit, which is the loader's first
    # candidate. It fails safe without it, but it does not work without it.
    if [ -f "$ROOT/tools/attribution.py" ]; then
      if ! cmp -s "$ROOT/tools/attribution.py" "$STORE/originality-toolkit/attribution.py"; then
        run "cp '$ROOT/tools/attribution.py' '$STORE/originality-toolkit/attribution.py'"
      fi
    else
      warn "tools/attribution.py is missing; the deployed toolkit cannot evaluate the defined claim"
    fi
    # Strip bytecode caches the same way the skills copy does. `cp -R` does not
    # preserve mtimes, so shipping a stale __pycache__ imports bytecode whose
    # recorded source time no longer matches the file beside it.
    run "find '$STORE/originality-toolkit' -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true"
    info "installed originality-toolkit -> $STORE/originality-toolkit"
  fi

  # Ship docs/ into the store. Five skills cite docs/EVIDENCE-INVARIANT.md as the
  # rule they are built on, and the installer used to copy no docs at all, so the
  # reference was dead in an installed tree. The citation is written
  # repo-root-relative; after install the same file is at $STORE/docs. The file
  # itself says so at the top.
  if [ -d "$ROOT/docs" ]; then
    run "mkdir -p '$STORE/docs'"
    if diff -rq -x '__pycache__' "$ROOT/docs" "$STORE/docs" >/dev/null 2>&1; then
      info "docs already match the repo (no copy, no backup)"
    else
      backup_store "$STORE/docs"
      run "mkdir -p '$STORE/docs'"
      run "cp -R '$ROOT/docs/'* '$STORE/docs/'"
    fi
    info "installed docs -> $STORE/docs"
  fi

  if [ "$WITH_UPSTREAM" = 1 ]; then
    UP="$HOME/.local/share/scientific-agent-skills"
    if [ -d "$UP/.git" ]; then
      info "upstream scientific skills already present ($UP)"
    elif [ -e "$UP" ]; then
      # The same interrupted-clone shape as AIPOCH below. This is the DEFAULT
      # path, so an abort here left the target with no skills and no MCP patch
      # at all. Keep the directory and say how to repair it.
      warn "$UP exists but is not a git clone (interrupted clone?)"
      if [ -d "$UP/skills" ]; then
        # The link loop below still links whatever is on disk, so the message
        # must not claim the pack was skipped.
        warn "  linking the skills already present; remove the directory and re-run to re-clone for updates"
      else
        warn "  upstream scientific skills skipped; remove that directory and re-run to fetch them"
      fi
    else
      # Optional third-party pack: being offline, or having no usable git, must
      # not fail an install whose own skills are already on disk.
      run "git clone --depth 1 https://github.com/K-Dense-AI/scientific-agent-skills.git '$UP'" \
        || warn "upstream scientific skills clone failed (optional) -> skipping"
    fi
  fi

  AIPOCH=""
  if [ "$WITH_AIPOCH" = 1 ]; then
    AIPOCH="$HOME/.local/share/aipoch-medical-research-skills"
    if [ -d "$AIPOCH/.git" ]; then
      info "AIPOCH medical-research-skills already cloned ($AIPOCH)"
    elif [ -e "$AIPOCH" ]; then
      # An interrupted clone leaves the directory behind without .git. `git clone`
      # refuses a non-empty destination, so the fallback failed too and `set -e`
      # killed the whole install (rc=128) on every re-run until the directory was
      # removed by hand. Keep the user's directory, skip the pack, and say how to
      # repair it rather than deleting something we did not create.
      warn "$AIPOCH exists but is not a git clone (interrupted clone?)"
      warn "  AIPOCH skills skipped; remove that directory and re-run to fetch them"
      AIPOCH=""
    else
      info "cloning AIPOCH medical-research-skills (scientific-skills subset, ~120 MB)..."
      run "git clone --depth 1 --filter=blob:none --sparse https://github.com/aipoch/medical-research-skills.git '$AIPOCH' && git -C '$AIPOCH' sparse-checkout set scientific-skills" \
        || run "git clone --depth 1 https://github.com/aipoch/medical-research-skills.git '$AIPOCH'" \
        || { warn "AIPOCH clone failed (third-party and optional) -> skipping"; AIPOCH=""; }
    fi
  fi

  IFS=',' read -ra TLIST <<< "$TARGETS"
  for t in "${TLIST[@]}"; do
    t="$(echo "$t" | tr -d '[:space:]')"
    sdir="$(skills_dir_for "$t")"
    if [ -z "$sdir" ]; then warn "unknown target '$t' (skills skipped)"; continue; fi
    run "mkdir -p '$sdir'"
    # link each research-stack skill
    for d in "$STORE"/skills/*/; do
      # Guard against an unexpanded glob: with no skills present, bash leaves the
      # pattern literal (".../skills/*/"), which is not a directory. Without this
      # the loop would run once and create a symlink literally named "*".
      [ -d "$d" ] || continue
      name="$(basename "$d")"
      install_skill "$d" "$sdir" "$name"
    done
    # link upstream skills too, when fetched
    if [ "$WITH_UPSTREAM" = 1 ] && [ -d "$HOME/.local/share/scientific-agent-skills/skills" ]; then
      for d in "$HOME/.local/share/scientific-agent-skills/skills"/*/; do
        # Same unexpanded-glob guard as above: an empty upstream skills/ dir must
        # be a no-op, not a symlink named "*".
        [ -d "$d" ] || continue
        name="$(basename "$d")"
        # -L matters as much as -e: a broken symlink is not "-e", so the guard
        # would fall through to `ln -s` and abort the whole install under
        # `set -e` with "File exists" until someone removes the link by hand.
        if [ -e "$sdir/$name" ] || [ -L "$sdir/$name" ]; then continue; fi
        run "ln -s '$d' '$sdir/$name'"
      done
    fi
    # link AIPOCH third-party skills (550+), when fetched
    if [ "$WITH_AIPOCH" = 1 ]; then
      if [ -z "$AIPOCH" ]; then
        info "  $t: AIPOCH skills skipped (not cloned; see the warning above)"
      elif [ "$DRY_RUN" = 1 ]; then
        info "  $t: [dry-run] symlink AIPOCH skills → $sdir"
      elif [ -d "$AIPOCH" ]; then
        n=0
        while IFS= read -r skill_md; do
          d="$(dirname "$skill_md")"; name="$(basename "$d")"
          # -L as well as -e, for the same broken-symlink reason as the upstream loop.
          if [ -e "$sdir/$name" ] || [ -L "$sdir/$name" ]; then continue; fi
          ln -s "$d" "$sdir/$name" 2>/dev/null && n=$((n+1))
        done < <(find "$AIPOCH" -name SKILL.md -type f -not -path '*/.git/*' 2>/dev/null)
        info "  $t: +$n AIPOCH skills (third-party, NOT gated by research-stack)"
      fi
    fi
    info "  $t -> $sdir"
  done
fi

# ---- 2b. render/PDF toolchain ---------------------------------------------- #
if [ "$INSTALL_RENDER" = 1 ]; then
  step "2b. render/PDF toolchain"
  install_render || true
fi

# ---- 3. MCP client config -------------------------------------------------- #
if [ "$DO_MCP" = 1 ]; then
  step "3. MCP client config"
  SERVERS="paper-search,consensus,google-scholar"
  if [ "$INSTALL_NCBI" = 1 ]; then
    if [ -x "$HOME/.local/share/ncbi-mcp-server/.venv/bin/python" ]; then
      SERVERS="$SERVERS,ncbi"
    else
      warn "ncbi not installed -> omitted from config (re-run without --no-ncbi to install)"
    fi
  fi
  if [ "$INSTALL_ACADEMIC" = 1 ]; then
    if [ -x "$HOME/.local/share/academic-search-mcp/.venv/bin/academic-search" ]; then
      SERVERS="$SERVERS,academic-search"
    else
      warn "academic-search not installed -> omitted from config"
    fi
  fi
  IFS=',' read -ra TLIST <<< "$TARGETS"
  for t in "${TLIST[@]}"; do
    t="$(echo "$t" | tr -d '[:space:]')"
    case "$t" in
      cline|claude|opencode|gemini|lmstudio|dsh|trae|cursor|windsurf) ;;
      *) warn "no MCP schema for target '$t' (skills only)"; continue;;
    esac
    info "configuring $t ..."
    if [ "$DRY_RUN" = 1 ]; then
      python3 "$ROOT/bin/mcp_config.py" --platform "$t" --servers "$SERVERS" --dry-run
    else
      python3 "$ROOT/bin/mcp_config.py" --platform "$t" --servers "$SERVERS"
    fi
  done
fi

# ---- 4. api keys ----------------------------------------------------------- #
step "4. API keys (optional but recommended)"
ENV_FILE="$HOME/.config/paper-search-mcp/.env"
if [ -n "$NCBI_EMAIL" ] || [ -n "$S2_API_KEY" ] || [ -n "$NCBI_API_KEY" ]; then
  run "mkdir -p '$(dirname "$ENV_FILE")'"
  if [ "$DRY_RUN" = 0 ]; then
    { echo "# written by research-stack on $(date +%F)";
      if [ -n "$NCBI_EMAIL" ]; then
        echo "PAPER_SEARCH_MCP_OPENALEX_EMAIL=$NCBI_EMAIL";
        echo "PAPER_SEARCH_MCP_UNPAYWALL_EMAIL=$NCBI_EMAIL";
        echo "PAPER_SEARCH_MCP_NCBI_EMAIL=$NCBI_EMAIL";
        echo "NCBI_EMAIL=$NCBI_EMAIL";
      fi
      if [ -n "$S2_API_KEY" ]; then
        echo "PAPER_SEARCH_MCP_SEMANTIC_SCHOLAR_API_KEY=$S2_API_KEY";
        echo "SEMANTIC_SCHOLAR_API_KEY=$S2_API_KEY";
      fi
      if [ -n "$NCBI_API_KEY" ]; then
        echo "PAPER_SEARCH_MCP_NCBI_API_KEY=$NCBI_API_KEY";
        echo "NCBI_API_KEY=$NCBI_API_KEY";
      fi
    } >> "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    info "appended keys -> $ENV_FILE (chmod 600)"
  else
    info "[dry-run] would write $ENV_FILE"
  fi
else
  info "no keys passed; the free sources work without them."
  info "add later:  $ROOT/install.sh --targets '${TARGETS}' --email you@org --s2-key <key>"
fi

# ---- 5. runtime deps ------------------------------------------------------- #
if [ "$INSTALL_R" = 1 ] || [ "$WITH_RUNTIME" = 1 ]; then
  step "5. Runtime dependencies"
  if [ "$INSTALL_R" = 1 ]; then
    if command -v Rscript >/dev/null 2>&1; then
      info "installing R meta-analysis packages (first run can take several minutes)..."
      run "Rscript '$STORE/skills/meta-analysis-forge/scripts/install_r_packages.R'" \
        || warn "R package install failed -- re-run: Rscript $STORE/skills/meta-analysis-forge/scripts/install_r_packages.R"
    else
      warn "Rscript not found -- install R (macOS: brew install r; Linux: apt install r-base) then re-run without --no-r"
    fi
  fi
  if [ "$WITH_RUNTIME" = 1 ]; then
    VENV="$HOME/.local/share/evidence-toolchain/.venv"
    run "uv venv '$VENV'"
    run "uv pip install --python '$VENV/bin/python' scipy pandas numpy matplotlib seaborn pingouin statsmodels pyyaml jinja2" \
      || warn "python toolchain venv install failed"
    info "python toolchain venv -> $VENV"
  fi
fi

# ---- done ------------------------------------------------------------------ #
step "Done (research-stack $VERSION)"
info "restart your client(s) so the MCP servers are spawned."
info "verify:  bash '$ROOT/verify.sh'"
printf '%s\n' "$BELL" >/dev/null 2>&1 || true


