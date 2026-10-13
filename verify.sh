#!/usr/bin/env bash
# verify.sh -- acceptance check for a research-stack install.
#   bash verify.sh [--targets cline,claude,opencode,dsh]
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGETS="cline"
while [ $# -gt 0 ]; do
  case "$1" in
    --targets) TARGETS="$2"; shift 2;;
    --targets=*) TARGETS="${1#*=}"; shift;;
    -h|--help)
      sed -n '2,3p' "$0"
      cat <<'EOF'
Usage: bash verify.sh [--targets cline,claude,opencode,gemini,lmstudio,dsh,...]

Checks an existing install and prints PASS/FAIL for: the paper-search MCP and
its patch system, the gated review skills, the originality toolkit, the
narrative-review harness, the client MCP configs (including the DeepSeek Harness
cordis patch layer), and optional components.
Third-party skill packs are listed as information and never change the verdict.
EOF
      exit 0;;
    *) shift;;
  esac
done
pass=0; fail=0
ok()  { printf '  PASS  %s\n' "$1"; pass=$((pass+1)); }
bad() { printf '  FAIL  %s\n' "$1"; fail=$((fail+1)); }
info(){ printf '  INFO  %s\n' "$1"; }

skills_dir_for() {
  case "$1" in
    cline) echo "$HOME/.cline/skills";; claude) echo "$HOME/.claude/skills";;
    opencode) echo "$HOME/.config/opencode/skills";; gemini) echo "$HOME/.gemini/skills";;
    lmstudio) echo "$HOME/.lmstudio/skills";; codex) echo "$HOME/.codex/skills";;
    dsh) echo "$HOME/.dsh/skills";; *) echo "";;
  esac
}
config_for() {
  case "$1" in
    cline) echo "$HOME/.cline/data/settings/cline_mcp_settings.json";;
    claude) if [ "$(uname)" = "Darwin" ]; then echo "$HOME/Library/Application Support/Claude/claude_desktop_config.json"; else echo "$HOME/.config/Claude/claude_desktop_config.json"; fi;;
    opencode) echo "$HOME/.config/opencode/opencode.json";;
    gemini) echo "$HOME/.gemini/settings.json";;
    lmstudio) echo "$HOME/.lmstudio/mcp.json";;
    trae) if [ "$(uname)" = "Darwin" ]; then echo "$HOME/Library/Application Support/Trae/User/mcp.json"; else echo "$HOME/.config/Trae/User/mcp.json"; fi;;
    cursor) echo "$HOME/.cursor/mcp.json";;
    windsurf) echo "$HOME/.codeium/windsurf/mcp_config.json";; *) echo "";;
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
environment-life-review-forge paper-search citecheck humanizerdrb originality-check \
citation-report"
NSKILLS="$(echo $SKILLS | wc -w | tr -d ' ')"
IFS=',' read -ra TLIST <<< "$TARGETS"
for t in "${TLIST[@]}"; do
  t="$(echo "$t" | tr -d '[:space:]')"; sdir="$(skills_dir_for "$t")"
  [ -z "$sdir" ] && continue
  missing=0
  for s in $SKILLS; do [ -e "$sdir/$s/SKILL.md" ] || missing=$((missing+1)); done
  if [ "$missing" -eq 0 ]; then ok "$t: all $NSKILLS review skills present"; else bad "$t: $missing skill(s) missing in $sdir"; fi
done

echo "== 2b. originality toolkit (required by originality-check) =="
# The skill resolves ~/.research-stack/originality-toolkit, so the deployed copy
# is what decides whether originality-check can run. But "not deployed" and "not
# in this checkout either" are different conditions and must not share a message:
# the first is an install step away, the second means the checkout is incomplete.
TOOLKIT_DEPLOYED="$HOME/.research-stack/originality-toolkit/originality_check.py"
TOOLKIT_CHECKOUT="$ROOT/tools/originality-toolkit/originality_check.py"
if [ -f "$TOOLKIT_DEPLOYED" ]; then
  ok "originality-toolkit present ($HOME/.research-stack/originality-toolkit)"
  # The deployed copy is what originality-check actually runs, so assert its behaviour
  # rather than only its existence.
  if env PYTHONDONTWRITEBYTECODE=1 python3 "$TOOLKIT_DEPLOYED" --self-test >/tmp/rs_toolkit.out 2>&1; then
    ok "originality-toolkit self-test passes ($(tail -1 /tmp/rs_toolkit.out))"
  else
    bad "originality-toolkit self-test FAILED"
    tail -4 /tmp/rs_toolkit.out | sed 's/^/        /'
  fi
elif [ -f "$TOOLKIT_CHECKOUT" ]; then
  bad "originality-toolkit not installed: $HOME/.research-stack/originality-toolkit is absent, so originality-check cannot run. It IS present in this checkout ($ROOT/tools/originality-toolkit) -> run ./install.sh"
else
  bad "originality-toolkit MISSING from both the checkout and $HOME/.research-stack -> originality-check cannot run"
fi

echo "== 2c. medical-narrative-review harness =="
MNR=""
for cand in "$ROOT/skills/medical-narrative-review/scripts/selftest.sh" \
            "$HOME/.research-stack/skills/medical-narrative-review/scripts/selftest.sh"; do
  [ -f "$cand" ] && { MNR="$cand"; break; }
done
if [ -n "$MNR" ]; then
  if bash "$MNR" >/tmp/mnr_selftest.out 2>&1; then
    ok "narrative-review selftest passes ($(grep -oE 'RESULT: [0-9]+ passed, [0-9]+ failed' /tmp/mnr_selftest.out | tail -1))"
  else
    bad "narrative-review selftest FAILED"
    tail -4 /tmp/mnr_selftest.out | sed 's/^/        /'
  fi
else
  info "narrative-review selftest not found"
fi

echo "== 2d. citation-report harness =="
CR=""
for cand in "$ROOT/skills/citation-report/scripts/selftest.sh" \
            "$HOME/.research-stack/skills/citation-report/scripts/selftest.sh"; do
  [ -f "$cand" ] && { CR="$cand"; break; }
done
if [ -n "$CR" ]; then
  if bash "$CR" >/tmp/cr_selftest.out 2>&1; then
    ok "citation-report selftest passes ($(grep -oE 'RESULT: [0-9]+ passed, [0-9]+ failed' /tmp/cr_selftest.out | tail -1))"
  else
    bad "citation-report selftest FAILED"
    grep -E 'FAIL' /tmp/cr_selftest.out | head -6 | sed 's/^/        /'
  fi
else
  info "citation-report selftest not found"
fi

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

echo "== 3b. DeepSeek Harness (dsh) =="
# DSH is the one non-JSON target: its config is a cordis patch layer, so it is
# checked here rather than by the JSON block above. Two of its failure modes are
# silent in the client, which is why they are asserted rather than assumed: a
# comments-only patch file fails DSH boot, and rows that are not wrapped in an
# `insert:` entry are dropped with a warning instead of registering their tools.
case ",$TARGETS," in
  *,dsh,*)
    DSH_PATCH="$HOME/.dsh/cordis.patch.yml"
    if [ -f "$DSH_PATCH" ]; then
      ok "dsh patch present ($DSH_PATCH)"
      while IFS='|' read -r verdict label; do
        case "$verdict" in
          PASS) ok "dsh: $label";;
          FAIL) bad "dsh: $label";;
          *)    info "dsh: $label";;
        esac
      done < <(python3 - "$DSH_PATCH" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
rows = [l for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
print(("PASS" if rows else "FAIL") + "|patch has rows (an empty or comments-only patch fails DSH boot)")
print(("PASS" if any(l.strip() == "- insert:" or l.strip() == "insert:" for l in rows) else "FAIL")
      + "|rows are wrapped in an insert: patch entry")
print(("PASS" if re.search(r"name:\s*['\"]@deepseek-ai/dsh-mcp-client['\"]", text) else "FAIL")
      + "|rows use the @deepseek-ai/dsh-mcp-client plugin")
for server in ("paper-search",):
    found = re.search(r"serverName:\s*['\"]?" + re.escape(server) + r"['\"]?\s*$", text, re.M)
    print(("PASS" if found else "FAIL") + "|server '%s' configured" % server)
# Only paper-search is required: --servers can restrict an install to any subset
# (ncbi and academic-search are optional, and consensus/google-scholar are npx
# servers many users skip), so the rest are reported rather than demanded.
configured = sorted(set(re.findall(r"serverName:\s*['\"]?([A-Za-z0-9_-]+)['\"]?\s*$", text, re.M)))
print("INFO|servers configured: %s" % (", ".join(configured) if configured else "none"))
for server in ("consensus", "google-scholar"):
    if server not in configured:
        print("INFO|optional server '%s' not configured (add it via --servers)" % server)
PY
      )
    else
      bad "dsh patch missing: $DSH_PATCH (run ./install.sh --targets dsh)"
    fi
    ;;
  *) info "dsh not in --targets; skipping its patch check";;
esac

echo "== 4. optional components =="
[ -x "$HOME/.local/share/ncbi-mcp-server/.venv/bin/python" ] && ok "ncbi installed" || info "ncbi not installed (optional)"
[ -x "$HOME/.local/share/academic-search-mcp/.venv/bin/academic-search" ] && ok "academic-search installed" || info "academic-search not installed (optional)"
[ -x "$HOME/.local/share/browser-probe/.venv/bin/python" ] && ok "render toolchain installed" || info "render toolchain not installed (optional)"

echo "== 4b. third-party skill packs (informational) =="
for t in "${TLIST[@]}"; do
  t="$(echo "$t" | tr -d '[:space:]')"; sdir="$(skills_dir_for "$t")"
  [ -d "$sdir" ] || continue
  links="$(find "$sdir" -maxdepth 1 -type l -exec readlink {} \; 2>/dev/null || true)"
  kd=$(printf '%s\n' "$links" | grep -c 'scientific-agent-skills' || true)
  ap=$(printf '%s\n' "$links" | grep -c 'aipoch-medical-research-skills' || true)
  if [ "${kd:-0}" -eq 0 ] && [ "${ap:-0}" -eq 0 ]; then
    info "$t: no third-party packs (gated core only)"
  else
    info "$t: third-party — K-Dense ${kd:-0}, AIPOCH ${ap:-0}"
    if [ "${ap:-0}" -gt 0 ]; then
      printf '%s\n' "$links" | grep 'aipoch-medical-research-skills' \
        | sed 's#.*/scientific-skills/##; s#/.*##' | sort | uniq -c | sort -rn \
        | while read -r c cat; do [ -n "${cat:-}" ] && info "      AIPOCH · $cat: $c"; done
    fi
  fi
done

echo
printf 'RESULT: %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ] && echo "RESEARCH-STACK VERIFIED" || echo "INCOMPLETE - see failures above"
exit $((fail>0))
