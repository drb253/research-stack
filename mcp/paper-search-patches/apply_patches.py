#!/usr/bin/env python3
"""Re-appliable fixes for paper-search-mcp 0.1.4 (macOS uv tool install).

Upstream defects addressed:
  1. Paper.to_dict() raises AttributeError when a connector supplies a date as a
     str -> broke Zenodo and HAL ("'str' object has no attribute 'isoformat'").
  2. The arXiv connector used python-requests, which arXiv's bot mitigation
     answers with HTTP 406, so arXiv search silently returned zero results.
     Replaced with a curl-backed transport (see replacements/arxiv.py).
  3. The OpenAlex connector ignored OPENALEX_API_KEY / OPENALEX_EMAIL, leaving a
     valid API key and polite-pool email completely inert.

Idempotent: safe to run repeatedly. Re-run after any `uv tool install/upgrade`.
"""
from __future__ import annotations

import glob
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG_GLOBS = [
    str(Path.home() / ".local/share/uv/tools/paper-search-mcp/lib/python*/site-packages/paper_search_mcp"),
]


def find_pkg() -> Path:
    for pattern in PKG_GLOBS:
        for hit in glob.glob(pattern):
            return Path(hit)
    sys.exit("ERROR: could not locate paper_search_mcp package. Is the uv tool installed?")


DATE_HELPERS = '''from typing import List, Dict, Optional


def _parse_date_value(value):
    """Coerce raw date strings from connectors into datetimes when possible."""
    if not value or not isinstance(value, str):
        return value
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return value


def _iso_or_str(value) -> str:
    """Serialize a date that may be a datetime, a date, or already a string."""
    if not value:
        return ""
    if isinstance(value, str):
        return value
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)


@dataclass
class Paper:'''

# Whole-file replacements: {"copy": <source in replacements/>, "target": ..., "marker": ..., "why": ...}
COPIES = [
    {
        "copy": "replacements/arxiv.py",
        "target": "academic_platforms/arxiv.py",
        "marker": "PATCHED-BY-paper-search-mcp-patches: curl-backed HTTP transport. retries=4. stderr-diagnostics",
        "why": "arxiv: curl transport (arXiv 406s Python TLS stacks)",
    },
    {
        "copy": "replacements/biorxiv.py",
        "target": "academic_platforms/biorxiv.py",
        "marker": "# PATCHED-BY-paper-search-mcp-patches: Europe PMC keyword search. v4",
        "why": "biorxiv: real keyword search via Europe PMC (was a query-blind date feed)",
    },
    {
        "copy": "replacements/medrxiv.py",
        "target": "academic_platforms/medrxiv.py",
        "marker": "# PATCHED-BY-paper-search-mcp-patches: Europe PMC keyword search. v6",
        "why": "medrxiv: real keyword search via Europe PMC (was a query-blind date feed)",
    },
    {
        "copy": "replacements/ssrn.py",
        "target": "academic_platforms/ssrn.py",
        "marker": "PATCHED-BY-paper-search-mcp-patches: SSRN search via OpenAlex/Crossref.",
        "why": "ssrn: keyword search via OpenAlex/Crossref (SSRN's own web search is 403)",
    },
    {
        "copy": "replacements/plos.py",
        "target": "academic_platforms/plos.py",
        "marker": "PATCHED-BY-paper-search-mcp-patches: PLOS Search API connector.",
        "why": "plos: new source (search + OA PDF + read)",
    },
    {
        "copy": "replacements/jstage.py",
        "target": "academic_platforms/jstage.py",
        "marker": "PATCHED-BY-paper-search-mcp-patches: J-STAGE WebAPI connector.",
        "why": "jstage: new source (text= query, PDF + read)",
    },
    {
        "copy": "replacements/figshare.py",
        "target": "academic_platforms/figshare.py",
        "marker": "PATCHED-BY-paper-search-mcp-patches: figshare API connector.",
        "why": "figshare: new source (search + author enrichment + files)",
    },
    {
        "copy": "replacements/datacite.py",
        "target": "academic_platforms/datacite.py",
        "marker": "PATCHED-BY-paper-search-mcp-patches: DataCite REST API connector.",
        "why": "datacite: new source (datasets/software/theses metadata)",
    },
    {
        "copy": "replacements/whoris.py",
        "target": "academic_platforms/whoris.py",
        "marker": "PATCHED-BY-paper-search-mcp-patches: WHO IRIS (DSpace 7) connector.",
        "why": "whoris: new source (WHO repository, PDF via bundles)",
    },
    {
        "copy": "replacements/osf.py",
        "target": "academic_platforms/osf.py",
        "marker": "PATCHED-BY-paper-search-mcp-patches: SHARE (share.osf.io) search connector.",
        "why": "osf: new source (OSF Preprints via SHARE, real search + PDF)",
    },
    # --- Tier 2: field-scoped query ladders (whole-file, surgically derived) ---
    {
        "copy": "replacements/openalex.py",
        "target": "academic_platforms/openalex.py",
        "marker": "paper-search-mcp-patches: Tier 1/2 helpers",
        "why": "openalex: title.search ladder + availability (was loose search=)",
    },
    {
        "copy": "replacements/zenodo.py",
        "target": "academic_platforms/zenodo.py",
        "marker": "paper-search-mcp-patches: Tier 1/2 helpers",
        "why": "zenodo: title-scoped ladder (was 237k loose matches)",
    },
    {
        "copy": "replacements/hal.py",
        "target": "academic_platforms/hal.py",
        "marker": "paper-search-mcp-patches: Tier 1/2 helpers",
        "why": "hal: title_t-scoped ladder + availability",
    },
    {
        "copy": "replacements/pmc.py",
        "target": "academic_platforms/pmc.py",
        "marker": "paper-search-mcp-patches: Tier 1/2 helpers",
        "why": "pmc: [Title/Abstract] + relevance ladder + availability",
    },
    # --- Tiers 1/3/4/5/6: server (fan-out, status, ranking, routing, new tools) ---
    {
        "copy": "replacements/server.py",
        "target": "server.py",
        "marker": "paper-search-mcp-patches: Tier 1",
        "why": "server: source_status, relevance ranking, routing, retraction tools",
    },
    # --- Tier 1: upstream connectors that silently returned [] on failure ---
    {
        "copy": "replacements/core.py",
        "target": "academic_platforms/core.py",
        "marker": "paper-search-mcp-patches: Tier 1",
        "why": "core: raise on failure (was: return partial/empty silently)",
    },
    {
        "copy": "replacements/crossref.py",
        "target": "academic_platforms/crossref.py",
        "marker": "paper-search-mcp-patches: Tier 1",
        "why": "crossref: raise on failure",
    },
    {
        "copy": "replacements/europepmc.py",
        "target": "academic_platforms/europepmc.py",
        "marker": "paper-search-mcp-patches: Tier 1",
        "why": "europepmc: raise on failure",
    },
    {
        "copy": "replacements/doaj.py",
        "target": "academic_platforms/doaj.py",
        "marker": "paper-search-mcp-patches: Tier 1",
        "why": "doaj: raise on failure (incl. API 'error' payload)",
    },
    {
        "copy": "replacements/semantic.py",
        "target": "academic_platforms/semantic.py",
        "marker": "paper-search-mcp-patches: Tier 1",
        "why": "semantic: raise on rate-limit/failure",
    },
    {
        "copy": "replacements/iacr.py",
        "target": "academic_platforms/iacr.py",
        "marker": "paper-search-mcp-patches: Tier 1",
        "why": "iacr: raise on failure",
    },
    # --- NCBI E-utilities API key (3 req/s -> 10 req/s) ---
    {
        "copy": "replacements/config.py",
        "target": "config.py",
        "marker": "def ncbi_eutils_params() -> dict:",
        "why": "config: shared NCBI E-utilities credentials (key + email + tool)",
    },
    {
        "copy": "replacements/pubmed.py",
        "target": "academic_platforms/pubmed.py",
        "marker": "ncbi_eutils_params()",
        "why": "pubmed: send the NCBI API key on esearch/efetch + raise on non-200",
    },
    # --- Source #24: ClinicalTrials.gov (trial registry, PRISMA-required) ---
    {
        "copy": "replacements/clinicaltrials.py",
        "target": "academic_platforms/clinicaltrials.py",
        "marker": "PATCHED-BY-paper-search-mcp-patches: source #24 (trial registry).",
        "why": "clinicaltrials: new source (registered studies, structured records)",
    },
    {
        "copy": "replacements/bookshelf.py",
        "target": "academic_platforms/bookshelf.py",
        "marker": "PATCHED-BY-paper-search-mcp-patches: source #25",
        "why": "bookshelf: new source (NCBI monographs, reports, chapters)",
    },
    {
        "copy": "replacements/ictrp.py",
        "target": "academic_platforms/ictrp.py",
        "marker": "PATCHED-BY-paper-search-mcp-patches: source #26",
        "why": "ictrp: new source (WHO trial-registry aggregator, ~20 registries)",
    },
    {
        "copy": "replacements/ctis.py",
        "target": "academic_platforms/ctis.py",
        "marker": "PATCHED-BY-paper-search-mcp-patches: source #27",
        "why": "ctis: new source (EU CTIS registry, mandatory EU trials since 2022)",
    },
    {
        "copy": "replacements/cli.py",
        "target": "cli.py",
        "marker": '"osf", "clinicaltrials", "bookshelf"]',
        "why": "cli: whole-file replacement (was a chain of fragile marker patches)",
    },
]

# Whole-file creations for files upstream does not ship (our own modules).
# Unlike COPIES these are always refreshed when their content changes, so
# editing replacements/<name>.py and re-running is the update path.
NEWFILES = [
    {
        "copy": "replacements/source_status.py",
        "target": "source_status.py",
        "why": "Tier 1/2: availability layer + field-scoped query builders",
    },
    {
        "copy": "replacements/query_planning.py",
        "target": "query_planning.py",
        "why": "Tier 3/4/5: relevance ranking + query planning + source routing",
    },
    {
        "copy": "replacements/retraction.py",
        "target": "retraction.py",
        "why": "Tier 6: free retraction lookup (OpenAlex + Crossref)",
    },
    {
        "copy": "replacements/springer.py",
        "target": "academic_platforms/springer.py",
        "why": "source #28: Springer Nature Meta API + Open Access JATS full text (free key)",
    },
    {
        "copy": "replacements/elsevier.py",
        "target": "academic_platforms/elsevier.py",
        "why": "source #29: Elsevier Scopus metadata search (free key; entitlement for full text)",
    },
    {
        "copy": "replacements/citation.py",
        "target": "citation.py",
        "why": "Tier 8: DOI-verified BibTeX/RIS/text citation export with retraction flags",
    },
]

# Snippets injected verbatim before an anchor line (avoids escaping large code blocks).
INJECTS = [
    {
        "source": "replacements/openaire_graph.py",
        "target": "academic_platforms/openaire.py",
        "anchor": "    def _parse_openaire_xml_result(self, node: ET.Element) -> Optional[Paper]:",
        "marker": "'type': 'publication',",
        "why": "openaire: inject Graph API v1 search + parser",
    },
]

PATCHES = [
    # --- date serialization safety (fixes Zenodo + HAL) ---
    {
        "file": "paper.py",
        "marker": "def _iso_or_str(value) -> str:",
        "old": "from typing import List, Dict, Optional\n\n@dataclass\nclass Paper:",
        "new": DATE_HELPERS,
        "why": "zenodo/hal: add str-tolerant date serialization",
    },
    {
        "file": "paper.py",
        "marker": "# Some connectors (notably Zenodo and HAL) pass raw date strings.",
        "old": "        if self.extra is None:\n            self.extra = {}\n",
        "new": (
            "        if self.extra is None:\n"
            "            self.extra = {}\n"
            "        # Some connectors (notably Zenodo and HAL) pass raw date strings.\n"
            "        # Normalize them so downstream consumers get consistent types.\n"
            "        self.published_date = _parse_date_value(self.published_date)\n"
            "        self.updated_date = _parse_date_value(self.updated_date)\n"
        ),
        "why": "zenodo/hal: normalize str dates at construction",
    },
    {
        "file": "paper.py",
        "marker": "'published_date': _iso_or_str(self.published_date),",
        "old": "            'published_date': self.published_date.isoformat() if self.published_date else '',",
        "new": "            'published_date': _iso_or_str(self.published_date),",
        "why": "zenodo/hal: published_date serialization guard",
    },
    {
        "file": "paper.py",
        "marker": "'updated_date': _iso_or_str(self.updated_date),",
        "old": "            'updated_date': self.updated_date.isoformat() if self.updated_date else '',",
        "new": "            'updated_date': _iso_or_str(self.updated_date),",
        "why": "zenodo/hal: updated_date serialization guard",
    },
    # --- OpenAlex API key + polite-pool email support ---
    {
        "file": "academic_platforms/openalex.py",
        "marker": "from ..config import get_env",
        "old": "from ..utils import extract_doi\n\nlogger = logging.getLogger(__name__)",
        "new": "from ..utils import extract_doi\nfrom ..config import get_env\n\nlogger = logging.getLogger(__name__)",
        "why": "openalex: import get_env",
    },
    {
        "file": "academic_platforms/openalex.py",
        "marker": 'self.api_key = get_env("OPENALEX_API_KEY", "").strip()',
        "old": (
            "        self.session = requests.Session()\n"
            "        # OpenAlex encourages providing an email in User-Agent for the \"polite pool\"\n"
            "        self.session.headers.update(\n"
            "            {\"User-Agent\": \"paper-search-mcp/1.0 (mailto:openags@example.com)\"}\n"
            "        )"
        ),
        "new": (
            "        self.session = requests.Session()\n"
            "        # OpenAlex encourages an email in the User-Agent for the \"polite pool\".\n"
            "        # An API key (OPENALEX_API_KEY) is optional and raises rate limits.\n"
            "        self.api_key = get_env(\"OPENALEX_API_KEY\", \"\").strip()\n"
            "        mailto = get_env(\"OPENALEX_EMAIL\", \"\").strip() or \"openags@example.com\"\n"
            "        self.session.headers.update(\n"
            "            {\"User-Agent\": f\"paper-search-mcp/1.0 (mailto:{mailto})\"}\n"
            "        )"
        ),
        "why": "openalex: read API key and email from env",
    },
    {
        "file": "academic_platforms/openalex.py",
        "marker": 'params["api_key"] = self.api_key',
        "old": "            response = self.session.get(self.BASE_URL, params=params, timeout=30)",
        "new": (
            "            if self.api_key:\n"
            "                params[\"api_key\"] = self.api_key\n"
            "            response = self.session.get(self.BASE_URL, params=params, timeout=30)"
        ),
        "why": "openalex: send the API key with every search",
    },
    # --- OpenAIRE: switch to the Graph API v1 (the v2 XML endpoints hang) ---
    {
        "file": "academic_platforms/openaire.py",
        "marker": "import re\nimport xml.etree.ElementTree as ET",
        "old": "import logging\nimport xml.etree.ElementTree as ET",
        "new": "import logging\nimport re\nimport xml.etree.ElementTree as ET",
        "why": "openaire: import re (used to strip markup from descriptions)",
    },
    {
        "file": "academic_platforms/openaire.py",
        "marker": 'GRAPH_URL = f"{BASE_URL}/graph/v1/researchProducts"',
        "old": '    RESEARCH_PRODUCTS_URL = f"{BASE_URL}/search/researchProducts"\n',
        "new": (
            '    RESEARCH_PRODUCTS_URL = f"{BASE_URL}/search/researchProducts"\n'
            '    # Graph API v1: the legacy v2 /search/* endpoints hang; this answers in ~1s.\n'
            '    GRAPH_URL = f"{BASE_URL}/graph/v1/researchProducts"\n'
        ),
        "why": "openaire: add the Graph API v1 URL",
    },
    {
        "file": "academic_platforms/openaire.py",
        "marker": "papers = self._search_graph_api(query, max_results, **kwargs)",
        "old": (
            "        papers: List[Paper] = []\n"
            "\n"
            "        try:\n"
            "            papers = self._search_with_retry(query, max_results, **kwargs)"
        ),
        "new": (
            "        papers: List[Paper] = []\n"
            "\n"
            "        # Graph API v1 first: the legacy /search/researchProducts endpoint hangs.\n"
            "        try:\n"
            "            papers = self._search_graph_api(query, max_results, **kwargs)\n"
            "            logger.info(\n"
            "                f\"Found {len(papers)} papers from OpenAIRE Graph API for query: {query}\"\n"
            "            )\n"
            "            if papers:\n"
            "                return papers\n"
            "        except Exception as exc:\n"
            "            logger.warning(\"OpenAIRE Graph API search failed, trying v2 XML: %s\", exc)\n"
            "\n"
            "        try:\n"
            "            papers = self._search_with_retry(query, max_results, **kwargs)"
        ),
        "why": "openaire: try the Graph API before the hanging v2 XML path",
    },
    # --- Retire the upstream-broken sources: dblp, base, citeseerx, google_scholar ---
    # --- Register the 5 new verified sources in both registries ---
    # --- Register OSF (SHARE) as a 6th new source ---
]


def main() -> int:
    pkg = find_pkg()
    backup_dir = pkg / ".patch-backups"
    backup_dir.mkdir(exist_ok=True)

    applied = skipped = failed = 0

    # Whole-file replacements and new modules: the file in replacements/ is the
    # single source of truth, so editing it and re-running is the update path.
    for item in list(NEWFILES) + list(COPIES):
        target = pkg / item["target"]
        source = HERE / item["copy"]
        if not source.exists():
            print(f"MISSING SOURCE  {item['copy']}")
            failed += 1
            continue

        snippet = source.read_text(encoding="utf-8")
        current = target.read_text(encoding="utf-8") if target.exists() else ""

        if current == snippet:
            skipped += 1
            continue

        backup = backup_dir / f"{target.name}.orig"
        if target.exists() and not backup.exists():
            shutil.copy2(target, backup)

        target.write_text(snippet, encoding="utf-8")
        print(f"wrote    {item['target']}: {item['why']}")
        applied += 1

    for patch in PATCHES:
        path = pkg / patch["file"]
        if not path.exists():
            print(f"MISSING FILE  {patch['file']}")
            failed += 1
            continue

        text = path.read_text(encoding="utf-8")

        if patch["marker"] in text:
            skipped += 1
            continue

        if patch["old"] not in text:
            print(f"COULD NOT APPLY  {patch['file']}: {patch['why']}")
            failed += 1
            continue

        backup = backup_dir / f"{path.name}.orig"
        if not backup.exists():
            shutil.copy2(path, backup)

        path.write_text(text.replace(patch["old"], patch["new"], 1), encoding="utf-8")
        print(f"applied  {patch['file']}: {patch['why']}")
        applied += 1

    for item in INJECTS:
        target = pkg / item["target"]
        source = HERE / item["source"]
        if not target.exists() or not source.exists():
            print(f"MISSING FILE  {item['target']} / {item['source']}")
            failed += 1
            continue

        text = target.read_text(encoding="utf-8")
        if item["marker"] in text:
            skipped += 1
            continue

        anchor = item["anchor"]
        if anchor not in text:
            print(f"COULD NOT APPLY  {item['target']}: anchor not found ({item['why']})")
            failed += 1
            continue

        backup = backup_dir / f"{target.name}.orig"
        if not backup.exists():
            shutil.copy2(target, backup)

        snippet = source.read_text(encoding="utf-8")
        target.write_text(text.replace(anchor, snippet + anchor, 1), encoding="utf-8")
        print(f"injected {item['target']}: {item['why']}")
        applied += 1

    # Syntax-check every file we touch so a bad patch fails loudly.
    broken = []
    touched = (
        {item["target"] for item in COPIES}
        | {item["target"] for item in NEWFILES}
        | {item["target"] for item in INJECTS}
        | {patch["file"] for patch in PATCHES}
    )
    for rel in sorted(touched):
        target = pkg / rel
        if not target.exists():
            continue
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(target)],
            capture_output=True,
        )
        if result.returncode != 0:
            broken.append((rel, result.stderr.decode(errors="replace").strip()[-400:]))

    for rel, err in broken:
        print(f"SYNTAX ERROR in {rel}:\n{err}")
    failed += len(broken)

    print(f"\napplied={applied} already_applied={skipped} failed={failed}")
    print(f"package: {pkg}")
    print(f"pristine copies: {backup_dir}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
