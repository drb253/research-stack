#!/usr/bin/env bash
# verify.sh -- acceptance check for a research-stack install.
#   bash verify.sh [--targets cline,claude,opencode]
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGETS="cline"
while [ $# -gt 0 ]; do
  case "$1" in
    --targets) TARGETS="$2"; shift 2;;
    --targets=*) TARGETS="${1#*=}"; shift;;
    *) shift;;
  esac
done
pass=0; fail=0
ok()  { printf '  PASS  %s\n' "$1"; pass=$((pass+1)); }
bad() { printf '  FAIL  %s\n' "$1"; fail=$((fail+1)); }

skills_dir_for() {
  case "$1" in
    cline) echo "$HOME/.cline/skills";; claude) echo "$HOME/.claude/skills";;
    opencode) echo "$HOME/.config/opencode/skills";; gemini) echo "$HOME/.gemini/skills";;
    lmstudio) echo "$HOME/.lmstudio/skills";; *) echo "";;
  esac
}
config_for() {
  case "$1" in
    cline) echo "$HOME/.cline/data/settings/cline_mcp_settings.json";;
    claude) if [ "$(uname)" = "Darwin" ]; then echo "$HOME/Library/Application Support/Claude/claude_desktop_config.json"; else echo "$HOME/.config/Claude/claude_desktop_config.json"; fi;;
    opencode) echo "$HOME/.config/opencode/opencode.json";;
    gemini) echo "$HOME/.gemini/settings.json";;
    lmstudio) echo "$HOME/.lmstudio/mcp.json";; *) echo "";;
  esac
}

echo "== 1. paper-search MCP =="
if command -v paper-search-mcp >/dev/null 2>&1; then
  ok "paper-search-mcp on PATH"
else
  bad "paper-search-mcp NOT on PATH (run install.sh)"
fi
if [ -f "$HOME/.local/share/paper-search-mcp-patches/apply_patches.py" ]; then
  ok "patch system deployed"
else
  bad "patch system not deployed"
fi
AUD="$ROOT/mcp/paper-search-patches/audit_fix_check.py"
if [ -f "$AUD" ] && command -v python3 >/dev/null 2>&1; then
  python3 "$AUD" >/tmp/rs_audit.out 2>&1 && ok "audit-fix self-check passed (MeSH)" \
    || { bad "audit-fix self-check FAILED"; tail -4 /tmp/rs_audit.out | sed 's/^/        /'; }
fi

echo "== 2. skills =="
SKILLS="sysreview meta-analysis evidence-synthesis-forge meta-analysis-forge \
medical-narrative-review umbrella-review-skeptic meta-ml-screener \
environment-life-review-forge paper-search citecheck humanizerdrb originality-check"
IFS=',' read -ra TLIST <<< "$TARGETS"
for t in "${TLIST[@]}"; do
  t="$(echo "$t" | tr -d '[:space:]')"; sdir="$(skills_dir_for "$t")"
  [ -z "$sdir" ] && continue
  missing=0
  for s in $SKILLS; do [ -e "$sdir/$s/SKILL.md" ] || missing=$((missing+1)); done
  if [ "$missing" -eq 0 ]; then ok "$t: all 12 review skills present"; else bad "$t: $missing skill(s) missing in $sdir"; fi
done

echo "== 3. MCP config =="
for t in "${TLIST[@]}"; do
  t="$(echo "$t" | tr -d '[:space:]')"; cfg="$(config_for "$t")"
  [ -z "$cfg" ] && continue
  if [ -f "$cfg" ] && python3 -c "import json,sys;json.load(open(sys.argv[1]))" "$cfg" 2>/dev/null; then
    ok "$t config valid JSON"
    for s in paper-search consensus google-scholar; do
      python3 -c "
import json,sys
d=json.load(open('$cfg'))
box=d.get('mcpServers') or d.get('mcp') or {}
sys.exit(0 if '$s' in box else 1)" 2>/dev/null \
        && ok "$t: server '$s' present" || bad "$t: server '$s' MISSING"
    done
  else
    bad "$t config missing or invalid: $cfg"
  fi
done

echo
printf 'RESULT: %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ] && echo "RESEARCH-STACK VERIFIED" || echo "INCOMPLETE - see failures above"
exit $((fail>0))
