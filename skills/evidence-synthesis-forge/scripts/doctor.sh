#!/usr/bin/env bash
# doctor.sh -- verify the Cochrane-grade toolchain. Prints versions; non-zero exit if a
# CORE dependency is missing. Run before trusting /sysreview or /meta-analysis.
set -u
# Location-independent: resolve the skills root from this script's own path.
SKILLS="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fail=0
ok()   { printf '  \033[32mOK\033[0m   %s\n' "$1"; }
bad()  { printf '  \033[31mMISS\033[0m %s\n' "$1"; fail=1; }
warn() { printf '  \033[33mWARN\033[0m %s\n' "$1"; }

echo "== Core interpreters =="
command -v Rscript >/dev/null && ok "Rscript $(Rscript -e 'cat(as.character(getRversion()))' 2>/dev/null)" || bad "Rscript not found"
command -v python3 >/dev/null && ok "python3 $(python3 -V 2>&1 | awk '{print $2}')" || bad "python3 not found"

echo "== R packages (meta-analysis core) =="
for p in metafor meta netmeta robumeta clubSandwich robvis esc mvmeta ggplot2; do
  if Rscript -e "quit(status=!requireNamespace('$p', quietly=TRUE))" >/dev/null 2>&1; then ok "$p"; else bad "$p"; fi
done
# optional (heavy build deps: cmake / poppler)
for p in metaSEM pdftools; do
  if Rscript -e "quit(status=!requireNamespace('$p', quietly=TRUE))" >/dev/null 2>&1; then ok "$p (optional)"; else warn "$p (optional) not installed"; fi
done

echo "== Python venv (evidence-toolchain) =="
PYV="$HOME/.local/share/evidence-toolchain/.venv/bin/python"
if [ -x "$PYV" ]; then
  ok "venv present"
  for m in scipy pandas numpy matplotlib seaborn pingouin statsmodels yaml jinja2 docx pptx lxml; do
    if "$PYV" -c "import $m" >/dev/null 2>&1; then ok "  $m"; else warn "  $m missing"; fi
  done
else
  warn "evidence-toolchain venv not found (only needed for optional Python helpers)"
fi

echo "== Render toolchain =="
command -v node >/dev/null && ok "node $(node -v)" || warn "node not found (PDF render via browser-probe)"
[ -x "$HOME/.local/share/browser-probe/.venv/bin/python" ] && ok "browser-probe venv" || warn "browser-probe venv not found"

echo "== Network reachability (citation gate + registry search) =="
check_url() {
  local name="$1" url="$2" code
  if ! command -v curl >/dev/null 2>&1; then warn "curl not found; cannot preflight $name"; return; fi
  code="$(curl -s -o /dev/null -m 8 -w '%{http_code}' "$url" 2>/dev/null || echo 000)"
  case "$code" in
    2*|3*) ok "$name (HTTP $code)" ;;
    000)   warn "$name unreachable -- offline? the citation gate will fail loudly, never silently" ;;
    *)     warn "$name returned HTTP $code" ;;
  esac
}
check_url "Crossref"    "https://api.crossref.org/works/10.1136/bmj.n71"
check_url "OpenAlex"    "https://api.openalex.org/works/doi:10.1136/bmj.n71"
check_url "Europe PMC"  "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=pmid:34265844&format=json"
check_url "NCBI eutils" "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&retmode=json&id=34265844"
check_url "PROSPERO"    "https://www.crd.york.ac.uk/PROSPERO/"

echo "== Skills =="
for s in sysreview meta-analysis evidence-synthesis-forge meta-analysis-forge \
         medical-narrative-review umbrella-review-skeptic meta-ml-screener \
         environment-life-review-forge paper-search citecheck humanizerdrb originality-check; do
  [ -f "$SKILLS/$s/SKILL.md" ] && ok "$s" || bad "$s"
done
# Upstream scientific skills (installed with --with-upstream-skills) are optional.
for s in statistical-analysis citation-management literature-review peer-review scientific-writing; do
  [ -f "$SKILLS/$s/SKILL.md" ] && ok "$s (upstream)" \
    || warn "$s (upstream) not installed -- add with --with-upstream-skills"
done

echo
if [ "$fail" -eq 0 ]; then echo "DOCTOR: core toolchain OK"; else echo "DOCTOR: core dependencies MISSING (see above)"; fi
exit "$fail"
