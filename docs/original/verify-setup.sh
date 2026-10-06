#!/usr/bin/env bash
# verify-setup.sh — acceptance test for the Cline research workstation.
# Run: bash verify-setup.sh
#
# Notes learned the hard way (see VERIFY.md):
#   * verify_fixes.py imports paper_search_mcp, so it MUST run with the
#     uv-tool venv's python, not the system python3.
#   * Its 13 checks make live network calls and take ~2.5 minutes.
#   * It buffers stdout when redirected -> run it with `python -u`.
#   * macOS has no `setsid`; `(nohup ... &)` is the working detach idiom.
#   * pytest is not a runtime dep of academic-search; install it separately.
set -u
pass=0; fail=0
ok()  { printf '  PASS  %s\n' "$1"; pass=$((pass+1)); }
bad() { printf '  FAIL  %s\n' "$1"; fail=$((fail+1)); }

echo "== 1. Cline config =="
CFG="$HOME/.cline/data/settings/cline_mcp_settings.json"
if [ -f "$CFG" ] && python3 -c "import json,sys;json.load(open(sys.argv[1]))" "$CFG" 2>/dev/null; then
  ok "MCP config exists and is valid JSON"
  perms=$(stat -f '%Lp' "$CFG" 2>/dev/null || stat -c '%a' "$CFG" 2>/dev/null)
  [ "$perms" = "600" ] && ok "config perms 600" || bad "config perms are $perms (want 600)"
  for s in paper-search ncbi academic-search; do
    python3 -c "import json,sys;d=json.load(open('$CFG'))['mcpServers'];sys.exit(0 if '$s' in d else 1)" \
      && ok "server '$s' present" || bad "server '$s' MISSING"
  done
  if grep -q '__[A-Z_]*__' "$CFG"; then bad "unreplaced __PLACEHOLDER__ remains in config"
  else ok "no placeholders left in config"; fi
else
  bad "MCP config missing or invalid JSON"
fi

echo "== 2. Skills =="
n=$(ls -1 "$HOME/.cline/skills" 2>/dev/null | wc -l | tr -d ' ')
[ "$n" -eq 176 ] && ok "176 skills present" || bad "$n skills present (want 176)"
links=$(find "$HOME/.cline/skills" -maxdepth 1 -type l 2>/dev/null | wc -l | tr -d ' ')
[ "$links" -eq 166 ] && ok "166 scientific symlinks" || bad "$links symlinks (want 166)"
for s in medical-narrative-review paper-search humanizerdrb citecheck originality-check \
         evidence-synthesis-forge meta-analysis-forge umbrella-review-skeptic meta-ml-screener \
         environment-life-review-forge; do
  [ -f "$HOME/.cline/skills/$s/SKILL.md" ] && ok "custom skill '$s'" || bad "custom skill '$s' MISSING"
done
badfm=0
for f in "$HOME"/.cline/skills/*/SKILL.md; do
  [ "$(head -1 "$f")" = "---" ] || badfm=$((badfm+1))
done
[ "$badfm" -eq 0 ] && ok "all SKILL.md frontmatter opens with ---" || bad "$badfm bad frontmatter files"

echo "== 3. paper-search =="
command -v paper-search-mcp >/dev/null && ok "paper-search-mcp on PATH" || bad "paper-search-mcp NOT on PATH"
if [ -f "$HOME/.local/share/paper-search-mcp-patches/apply_patches.py" ]; then
  ok "patch system deployed"
  TOOLPY="$HOME/.local/share/uv/tools/paper-search-mcp/bin/python"
  if [ -x "$TOOLPY" ]; then
    ok "uv-tool python found"
    VF="$HOME/.local/share/paper-search-mcp-patches/verify_fixes.py"
    OUT=/tmp/verify_fixes.out
    echo "        (running 13 live network checks; takes ~2.5 min)"
    ( cd "$(dirname "$VF")" && nohup "$TOOLPY" -u "$VF" > "$OUT" 2>&1 </dev/null & )
    for i in $(seq 1 120); do
      pgrep -f 'verify_fixes.py' >/dev/null 2>&1 || break
      sleep 2
    done
    if pgrep -f 'verify_fixes.py' >/dev/null 2>&1; then
      bad "verify_fixes.py still running after 240s (network hang?)"
    else
      tail -3 "$OUT" | sed 's/^/        /'
      grep -q '13/13 checks passed' "$OUT" && ok "verify_fixes.py: 13/13 checks passed" \
        || bad "verify_fixes.py did not report 13/13 (see $OUT)"
      grep -q '0/0 checks' "$OUT" && bad "verifier reported 0/0 -> OLD verifier, re-copy it"
    fi
  else
    bad "uv-tool python missing at $TOOLPY -- is paper-search-mcp installed as a uv tool?"
  fi
else
  bad "patch system NOT deployed"
fi
ENV="$HOME/.config/paper-search-mcp/.env"
[ -f "$ENV" ] && ok "paper-search .env present" || bad "paper-search .env MISSING"
grep -q 'PAPER_SEARCH_MCP_UNPAYWALL_EMAIL=.\+' "$ENV" 2>/dev/null \
  && ok "Unpaywall email set (PDF resolution enabled)" \
  || bad "Unpaywall email NOT set -> PDF fallback is skipped"
grep -q 'PAPER_SEARCH_MCP_OPENALEX_EMAIL=.\+' "$ENV" 2>/dev/null \
  && ok "OpenAlex email set (polite pool)" \
  || bad "OpenAlex email NOT set -> anonymous 429s expected"

echo "== 4. ncbi =="
NCBI="$HOME/.local/share/ncbi-mcp-server"
if [ -d "$NCBI" ]; then
  patched=$(grep -rc 'PATCHED' "$NCBI/src" 2>/dev/null | awk -F: '{s+=$2} END{print s+0}')
  [ "$patched" -ge 3 ] && ok "ncbi patches applied ($patched markers)" \
    || bad "ncbi NOT patched (found $patched, want 3)"
  if "$NCBI/.venv/bin/python" -c "import pytest" 2>/dev/null; then
    ( cd "$NCBI" && .venv/bin/python -m pytest -q >/dev/null 2>&1 ) \
      && ok "ncbi tests pass (52)" || bad "ncbi tests FAIL"
  else
    bad "pytest missing -> uv pip install --python $NCBI/.venv pytest pytest-asyncio pytest-cov"
  fi
else bad "ncbi server MISSING"; fi

echo "== 5. academic-search =="
AS="$HOME/.local/share/academic-search-mcp"
if [ -d "$AS" ]; then
  [ -x "$AS/.venv/bin/academic-search" ] && ok "academic-search entry point" \
    || bad "academic-search entry point MISSING"
  if "$AS/.venv/bin/python" -c "import pytest" 2>/dev/null; then
    ( cd "$AS" && .venv/bin/python -m pytest -q >/dev/null 2>&1 ) \
      && ok "academic-search tests pass (51)" || bad "academic-search tests FAIL"
  else
    bad "pytest missing -> uv pip install --python $AS/.venv pytest"
  fi
else bad "academic-search MISSING"; fi

echo "== 6. Render toolchain =="
BP="$HOME/.local/share/browser-probe/.venv/bin/python"
if [ -x "$BP" ]; then
  "$BP" -c "import playwright,pypdf,pypdfium2,reportlab,PIL" 2>/dev/null \
    && ok "render toolchain imports" || bad "render toolchain import FAIL"
else bad "browser-probe venv MISSING"; fi

echo
printf 'RESULT: %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ] && echo "SETUP VERIFIED" || echo "SETUP INCOMPLETE - see failures above"
exit $((fail>0))
