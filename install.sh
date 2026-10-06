#!/usr/bin/env bash
# research-stack installer
#   Installs the review/synthesis MCP servers + skills and wires them into
#   Cline, Claude, OpenCode (and optionally Gemini / LM Studio).
#
# Usage:
#   ./install.sh [options]
# Options:
#   --targets LIST     comma list: cline,claude,opencode,gemini,lmstudio  (default: cline)
#   --no-mcp           install skills only
#   --no-skills        configure MCP only
#   --with-upstream-skills  also clone the 160+ K-Dense scientific skills
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

VERSION="1.0.0"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STORE="$HOME/.research-stack"
DRY_RUN=0
TARGETS="cline"
DO_SKILLS=1
DO_MCP=1
COPY_SKILLS=0
WITH_UPSTREAM=1
INSTALL_NCBI=1
INSTALL_ACADEMIC=1
INSTALL_RENDER=1
INSTALL_R=1
REINSTALL=0
WITH_RUNTIME=0
NCBI_REPO="${NCBI_REPO:-https://github.com/vitorpavinato/ncbi-mcp-server.git}"
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

usage() {
  cat <<'EOF'
research-stack installer -- review MCPs + skills for Cline / Claude / OpenCode.

Usage: ./install.sh [options]
Options:
  --targets LIST     cline,claude,opencode,gemini,lmstudio  (default: cline)
  --no-mcp           install skills only
  --no-skills        configure MCP only
  --with-upstream-skills   (default) also clone the 160+ K-Dense scientific skills
  --no-upstream-skills     skip the upstream scientific skills
  --copy-skills      copy skills instead of symlinking
  --reinstall        reinstall/upgrade the paper-search tool first
  --no-ncbi / --no-academic-search / --no-render / --no-r   skip a default step
  --minimal          skip ncbi, academic-search, render toolchain and R packages
  --ncbi-repo URL    override the ncbi source repo (default upstream)
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
    --with-ncbi) INSTALL_NCBI=1; shift;;
    --with-academic-search) INSTALL_ACADEMIC=1; shift;;
    --no-ncbi) INSTALL_NCBI=0; shift;;
    --no-academic-search) INSTALL_ACADEMIC=0; shift;;
    --no-render) INSTALL_RENDER=0; shift;;
    --no-r) INSTALL_R=0; shift;;
    --minimal) INSTALL_NCBI=0; INSTALL_ACADEMIC=0; INSTALL_RENDER=0; INSTALL_R=0; shift;;
    --ncbi-repo) NCBI_REPO="$2"; shift 2;;
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
    codex)     echo "$HOME/.codex/skills";;
    *)         echo "";;
  esac
}

# ---- optional component installers ----------------------------------------- #
install_ncbi() {
  DEST="$HOME/.local/share/ncbi-mcp-server"
  if [ -x "$DEST/.venv/bin/python" ] && [ -d "$DEST/src/ncbi_mcp_server" ]; then
    info "ncbi already installed"; return 0
  fi
  info "installing ncbi MCP (clone + reliability patch + venv)..."
  run "rm -rf '$DEST'"
  run "git clone --depth 1 '$NCBI_REPO' '$DEST'" || { warn "ncbi clone failed (skipping)"; return 1; }
  run "git -C '$DEST' apply '$ROOT/mcp/optional/ncbi-mcp-server.patch' 2>/dev/null || patch -d '$DEST' -p1 -N < '$ROOT/mcp/optional/ncbi-mcp-server.patch' >/dev/null 2>&1 || true"
  run "uv venv '$DEST/.venv'" || { warn "ncbi venv failed"; return 1; }
  run "uv pip install --python '$DEST/.venv/bin/python' mcp httpx typing-extensions python-dotenv redis aiofiles" \
    || warn "ncbi dependency install failed"
  info "ncbi -> $DEST"
}

install_academic_search() {
  DEST="$HOME/.local/share/academic-search-mcp"
  if [ -x "$DEST/.venv/bin/academic-search" ]; then
    info "academic-search already installed"; return 0
  fi
  SRC="$ROOT/mcp/optional/academic-search-mcp"
  [ -d "$SRC" ] || { warn "academic-search source missing in repo (skipping)"; return 1; }
  info "installing academic-search MCP (copy + venv)..."
  run "rm -rf '$DEST' && cp -R '$SRC' '$DEST'"
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
  step "1. paper-search MCP (uv tool) + reliability patches"
  if [ "$REINSTALL" = 1 ]; then
    run "uv tool install --reinstall paper-search-mcp --force"
  elif have paper-search-mcp; then
    info "paper-search-mcp already on PATH (use --reinstall to upgrade)"
  else
    run "uv tool install paper-search-mcp"
  fi

  PATCHES="$ROOT/mcp/paper-search-patches"
  [ -f "$PATCHES/apply_patches.py" ] || die "patch system missing at $PATCHES"
  if [ "$DRY_RUN" = 1 ]; then
    info "[dry-run] python3 $PATCHES/apply_patches.py"
  else
    info "applying connector patches (idempotent)..."
    python3 "$PATCHES/apply_patches.py" | tail -4
    # carry the audit fix proof
    if [ -f "$PATCHES/audit_fix_check.py" ]; then
      python3 "$PATCHES/audit_fix_check.py" || warn "mesh audit-fix self-check FAILED"
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
  run "cp -R '$ROOT/skills/'* '$STORE/skills/'"
  run "find '$STORE/skills' -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true"
  info "installed $(ls -1 "$STORE/skills" 2>/dev/null | grep -vc 'VENDORED') skills"

  # ship the originality-check toolkit (the skill depends on it)
  if [ -d "$ROOT/tools/originality-toolkit" ]; then
    run "rm -rf '$STORE/originality-toolkit' && cp -R '$ROOT/tools/originality-toolkit' '$STORE/originality-toolkit'"
    info "installed originality-toolkit -> $STORE/originality-toolkit"
  fi

  if [ "$WITH_UPSTREAM" = 1 ]; then
    UP="$HOME/.local/share/scientific-agent-skills"
    if [ -d "$UP/.git" ]; then
      info "upstream scientific skills already present ($UP)"
    else
      run "git clone --depth 1 https://github.com/K-Dense-AI/scientific-agent-skills.git '$UP'"
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
      name="$(basename "$d")"
      if [ "$COPY_SKILLS" = 1 ]; then
        run "rm -rf '$sdir/$name' && cp -R '$d' '$sdir/$name'"
      else
        run "rm -rf '$sdir/$name' && ln -s '$d' '$sdir/$name'"
      fi
    done
    # link upstream skills too, when fetched
    if [ "$WITH_UPSTREAM" = 1 ] && [ -d "$HOME/.local/share/scientific-agent-skills/skills" ]; then
      for d in "$HOME/.local/share/scientific-agent-skills/skills"/*/; do
        name="$(basename "$d")"
        [ -e "$sdir/$name" ] && continue
        run "ln -s '$d' '$sdir/$name'"
      done
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
      cline|claude|opencode|gemini|lmstudio|trae|cursor|windsurf) ;;
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


