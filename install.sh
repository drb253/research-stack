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
WITH_UPSTREAM=0
WITH_NCBI=0
WITH_ACADEMIC=0
REINSTALL=0
WITH_R=0
WITH_RUNTIME=0
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

usage() { sed -n '2,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --targets) TARGETS="$2"; shift 2;;
    --targets=*) TARGETS="${1#*=}"; shift;;
    --no-mcp) DO_MCP=0; shift;;
    --no-skills) DO_SKILLS=0; shift;;
    --with-upstream-skills) WITH_UPSTREAM=1; shift;;
    --with-ncbi) WITH_NCBI=1; shift;;
    --with-academic-search) WITH_ACADEMIC=1; shift;;
    --copy-skills) COPY_SKILLS=1; shift;;
    --reinstall) REINSTALL=1; shift;;
    --email) NCBI_EMAIL="$2"; shift 2;;
    --ncbi-key) NCBI_API_KEY="$2"; shift 2;;
    --s2-key) S2_API_KEY="$2"; shift 2;;
    --with-r) WITH_R=1; shift;;
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
    *)         echo "";;
  esac
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

# ---- 3. MCP client config -------------------------------------------------- #
if [ "$DO_MCP" = 1 ]; then
  step "3. MCP client config"
  SERVERS="paper-search,consensus,google-scholar"
  if [ "$WITH_NCBI" = 1 ]; then
    SERVERS="$SERVERS,ncbi"
    [ -x "$HOME/.local/share/ncbi-mcp-server/.venv/bin/python" ] \
      || warn "ncbi configured but the ncbi fork is not installed at ~/.local/share/ncbi-mcp-server (server will not start until it is)."
  fi
  if [ "$WITH_ACADEMIC" = 1 ]; then
    SERVERS="$SERVERS,academic-search"
    [ -x "$HOME/.local/share/academic-search-mcp/.venv/bin/academic-search" ] \
      || warn "academic-search configured but its fork is not installed at ~/.local/share/academic-search-mcp."
  fi
  IFS=',' read -ra TLIST <<< "$TARGETS"
  for t in "${TLIST[@]}"; do
    t="$(echo "$t" | tr -d '[:space:]')"
    case "$t" in
      cline|claude|opencode|gemini|lmstudio) ;;
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
if [ -n "$NCBI_EMAIL" ] || [ -n "$S2_API_KEY" ]; then
  run "mkdir -p '$(dirname "$ENV_FILE")'"
  if [ "$DRY_RUN" = 0 ]; then
    { echo "# written by research-stack on $(date +%F)";
      [ -n "$NCBI_EMAIL" ] && echo "PAPER_SEARCH_MCP_OPENALEX_EMAIL=$NCBI_EMAIL";
      [ -n "$NCBI_EMAIL" ] && echo "PAPER_SEARCH_MCP_UNPAYWALL_EMAIL=$NCBI_EMAIL";
      [ -n "$S2_API_KEY" ]  && echo "PAPER_SEARCH_MCP_S2_API_KEY=$S2_API_KEY";
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

# ---- 5. optional runtime deps --------------------------------------------- #
if [ "$WITH_R" = 1 ] || [ "$WITH_RUNTIME" = 1 ]; then
  step "5. Runtime dependencies"
  if [ "$WITH_R" = 1 ]; then
    if command -v Rscript >/dev/null 2>&1; then
      info "installing R meta-analysis packages (several minutes)..."
      run "Rscript '$STORE/skills/meta-analysis-forge/scripts/install_r_packages.R'"
    else
      warn "Rscript not found -- install R (brew install r) then re-run with --with-r"
    fi
  fi
  if [ "$WITH_RUNTIME" = 1 ]; then
    VENV="$HOME/.local/share/evidence-toolchain/.venv"
    run "uv venv '$VENV'"
    run "uv pip install --python '$VENV/bin/python' scipy pandas numpy matplotlib seaborn pingouin statsmodels pyyaml jinja2"
    info "python toolchain venv -> $VENV"
  fi
fi

# ---- done ------------------------------------------------------------------ #
step "Done (research-stack $VERSION)"
info "restart your client(s) so the MCP servers are spawned."
info "verify:  bash '$ROOT/verify.sh'"
printf '%s\n' "$BELL" >/dev/null 2>&1 || true


