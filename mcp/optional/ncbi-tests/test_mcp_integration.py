"""End-to-end tests over the real MCP stdio transport, against the live NCBI API.

The server is launched as `python -m ncbi_mcp_server.server` -- exactly how the
MCP host launches it -- and that detail matters. The analytics defect only
reproduced under `-m` (the module runs as __main__, so the old
sys.modules['ncbi_mcp_server.server'] lookup never fired), and the old startup
wiring was never exercised because main() never called it.

Marked `integration`: it needs network access and NCBI credentials, so it is
excluded from the default run (see `-m "not integration"` in pyproject.toml).
Run it with:
    pytest -m integration
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[1]
PY = Path(sys.executable)
ENV_FILE = REPO / ".env"

SEED_PMID = "38308006"
SECOND_PMID = "30835493"
BOGUS_PMID = "99999999"
QUERY = "CRISPR base editing"

EXPECTED_TOOLS = {
    "search_pubmed",
    "get_article_details",
    "search_mesh_terms",
    "get_related_articles",
    "advanced_search",
    "cache_stats",
    "clear_cache",
    "batch_search_multiple_queries",
    "batch_get_article_details",
    "get_analytics_summary",
    "get_detailed_metrics",
    "reset_analytics",
}


def _credentials() -> dict:
    """Read credentials straight from .env; load_dotenv() uses the child's cwd."""
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def build_env(tmp: Path) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "src")
    env["NCBI_MCP_CACHE_DIR"] = str(tmp / "cache")
    env["NCBI_MCP_DATA_DIR"] = str(tmp / "data")
    (tmp / "cache").mkdir(parents=True, exist_ok=True)
    (tmp / "data").mkdir(parents=True, exist_ok=True)
    for key, value in _credentials().items():
        env.setdefault(key, value)
    return env


async def _call(session, name: str, arguments: dict) -> dict:
    result = await session.call_tool(name, arguments)
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured.get("result", structured)
    text = "".join(c.text for c in result.content if getattr(c, "type", "") == "text")
    return json.loads(text)


async def _run_observed(env: dict) -> dict:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    observed = {}
    params = StdioServerParameters(
        command=str(PY), args=["-m", "ncbi_mcp_server.server"], env=env
    )
    with open(os.devnull, "w") as errlog:
        async with stdio_client(params, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                observed["tools"] = sorted(
                    tool.name for tool in (await session.list_tools()).tools
                )
                # Called twice so the second hits the cache, exercising both a
                # miss and a hit in the recorded cache counters.
                observed["search1"] = await _call(
                    session, "search_pubmed", {"query": QUERY, "max_results": 3})
                observed["search2"] = await _call(
                    session, "search_pubmed", {"query": QUERY, "max_results": 3})
                observed["mesh"] = await _call(
                    session, "search_mesh_terms", {"term": "base editing"})
                observed["related"] = await _call(
                    session, "get_related_articles",
                    {"pmid": SEED_PMID, "max_results": 5})
                observed["batch"] = await _call(
                    session, "batch_get_article_details",
                    {"pmids": [SEED_PMID, SECOND_PMID, BOGUS_PMID]})
                observed["articles"] = await _call(
                    session, "get_article_details", {"pmids": [SEED_PMID]})
                observed["summary"] = await _call(session, "get_analytics_summary", {})
                observed["metrics"] = await _call(
                    session, "get_detailed_metrics", {"hours": 24})
    # The stdio context has exited, so the server's lifespan shutdown hook has run
    # and flushed analytics.json.
    return observed


@pytest.fixture(scope="module")
def observed():
    """Run one server session and return everything it answered.

    Deliberately a *sync* fixture driving asyncio.run(): a module-scoped async
    fixture would need a module-scoped event loop and would clash with
    pytest-asyncio's function-scoped default.
    """
    try:
        import httpx
        httpx.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi", timeout=10
        ).raise_for_status()
    except Exception as exc:  # pragma: no cover - depends on the environment
        pytest.skip(f"NCBI E-utilities unreachable: {exc}")

    tmp = Path(tempfile.mkdtemp(prefix="ncbi-integration-")).resolve()
    env = build_env(tmp)
    if not env.get("NCBI_EMAIL") and not env.get("NCBI_API_KEY"):
        pytest.skip("no NCBI credentials configured")
    result = asyncio.run(_run_observed(env))
    result["_env"] = env
    return result


# --- server wiring ---------------------------------------------------------

def test_all_tools_are_exposed(observed):
    assert set(observed["tools"]) == EXPECTED_TOOLS


def test_search_returns_pmids(observed):
    idlist = observed["search1"]["esearchresult"]["idlist"]
    assert len(idlist) == 3


def test_article_details_are_populated(observed):
    articles = observed["articles"]["articles"]
    assert articles
    assert articles[0]["title"]
    assert articles[0]["authors"]
    assert articles[0]["abstract"]


# --- defect 1: get_related_articles ----------------------------------------

def test_related_articles_returns_parsed_shape(observed):
    related = observed["related"]
    assert "linksets" not in related
    assert "header" not in related
    assert isinstance(related["related_pmids"], list)
    assert isinstance(related["total_related"], int)


def test_related_articles_payload_is_small(observed):
    """The raw ELink document ran to ~22k characters and was truncated."""
    assert len(json.dumps(observed["related"])) < 2000


def test_related_articles_respects_max_results(observed):
    assert len(observed["related"]["related_pmids"]) <= 5


def test_related_articles_excludes_the_seed(observed):
    assert SEED_PMID not in observed["related"]["related_pmids"]


def test_related_articles_reports_link_sets(observed):
    assert "pubmed_pubmed" in observed["related"]["link_sets"]


# --- defect 2: search_mesh_terms -------------------------------------------

def test_mesh_returns_descriptors_not_esearch(observed):
    mesh = observed["mesh"]
    assert "esearchresult" not in mesh
    assert isinstance(mesh["descriptors"], list)
    assert mesh["descriptors"]


def test_mesh_descriptor_carries_documented_fields(observed):
    descriptor = observed["mesh"]["descriptors"][0]
    for field in ("label", "mesh_ui", "synonyms", "scope_note"):
        assert field in descriptor
    assert descriptor["label"]
    assert descriptor["mesh_ui"]
    assert isinstance(descriptor["synonyms"], list)


def test_mesh_matched_term_explains_the_mapping(observed):
    """'base editing' is an entry term of Gene Editing, so the mapping is exact."""
    assert observed["mesh"]["descriptors"][0]["matched_term"] == "Base Editing"


# --- defect 3: batch accounting --------------------------------------------

def test_batch_article_counts_reconcile(observed):
    batch = observed["batch"]
    assert batch["success_count"] == len(batch["articles"]) == batch["total_articles"]
    assert batch["success_count"] + batch["failure_count"] == batch["pmids_requested"] == 3


def test_batch_reports_the_bogus_pmid(observed):
    batch = observed["batch"]
    assert batch["failure_count"] == 1
    assert any(BOGUS_PMID in error for error in batch["errors"])


def test_batch_keeps_chunk_detail(observed):
    chunks = observed["batch"]["chunks"]
    assert chunks["total"] == 1
    assert chunks["succeeded"] == 1


# --- defect 4: analytics ---------------------------------------------------

def test_analytics_records_requests(observed):
    """Every counter read 0 before the fix, because nothing was ever recorded."""
    overview = observed["summary"]["overview"]
    assert overview["total_requests"] > 0
    assert overview["avg_response_time_ms"] > 0
    assert observed["summary"]["system_health"]["last_updated"] is not None


def test_analytics_counts_each_operation(observed):
    operations = observed["summary"]["operations"]
    assert operations["search_queries"] >= 2
    assert operations["mesh_searches"] >= 1
    assert operations["related_searches"] >= 1
    assert operations["batch_operations"] >= 1
    assert operations["article_fetches"] >= 1
    assert operations["unique_queries"] >= 1


def test_analytics_records_cache_hits_and_misses(observed):
    cache = observed["summary"]["cache_performance"]
    assert cache["total_cache_operations"] > 0
    assert cache["cache_hits"] >= 1, "second identical search should be a cache hit"
    assert cache["cache_misses"] >= 1


def test_analytics_detailed_metrics_have_events(observed):
    metrics = observed["metrics"]
    assert metrics["total_events"] > 0
    assert "search_pubmed" in metrics["operation_metrics"]


def test_analytics_persisted_on_shutdown(observed):
    """Proves the FastMCP lifespan hook ran; main() never used to call startup()."""
    analytics_file = Path(observed["_env"]["NCBI_MCP_DATA_DIR"]) / "analytics.json"
    assert analytics_file.exists()
    data = json.loads(analytics_file.read_text())
    assert data["stats"]["total_requests"] > 0
    assert data.get("last_flush")


# --- reset -----------------------------------------------------------------

async def _run_reset(env: dict):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(
        command=str(PY), args=["-m", "ncbi_mcp_server.server"], env=env
    )
    with open(os.devnull, "w") as errlog:
        async with stdio_client(params, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                before = await _call(session, "get_analytics_summary", {})
                await session.call_tool("reset_analytics", {})
                after = await _call(session, "get_analytics_summary", {})
                return before, after


def test_reset_analytics_actually_resets(observed):
    """The old implementation rebuilt the manager, whose start() reloaded the
    previous counters straight back off disk."""
    before, after = asyncio.run(_run_reset(observed["_env"]))
    assert before["overview"]["total_requests"] > 0
    assert after["overview"]["total_requests"] == 0
    assert after["cache_performance"]["total_cache_operations"] == 0
