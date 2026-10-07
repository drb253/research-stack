"""Analytics recording tests.

These lock in the fix for the defect that made every counter in
get_analytics_summary read back 0. The cause was not the counters themselves but
how track_usage located its manager: it went through
sys.modules['ncbi_mcp_server.server'], a key that does not exist when the server
is started the way the MCP host starts it (`python -m ncbi_mcp_server.server`
runs the module as __main__). A bare `except Exception: pass` hid the failure.
"""
import json
import sys
from pathlib import Path

import pytest

import ncbi_mcp_server.analytics as analytics
from ncbi_mcp_server.analytics import AnalyticsManager, track_usage


@pytest.fixture
def manager(tmp_path):
    """A registered AnalyticsManager that cleans up after the test."""
    mgr = AnalyticsManager(analytics_file=str(tmp_path / "analytics.json"))
    analytics.set_analytics_manager(mgr)
    yield mgr
    analytics.set_analytics_manager(None)


async def test_registry_returns_manager(manager):
    assert analytics.get_analytics_manager() is manager


async def test_records_event_with_result_count(manager):
    @track_usage("search_pubmed", "search")
    async def tool(query: str):
        return {"esearchresult": {"idlist": ["1", "2"]}}

    await tool(query="crispr")

    assert manager.stats.total_requests == 1
    assert manager.stats.total_search_queries == 1
    assert manager.stats.unique_queries == 1
    assert len(manager.events) == 1
    event = manager.events[0]
    assert event.operation == "search_pubmed"
    assert event.result_count == 2
    assert event.query_hash is not None


async def test_records_without_dotted_module_in_sys_modules(manager, monkeypatch):
    """The regression itself.

    Under `python -m`, 'ncbi_mcp_server.server' is absent from sys.modules. The
    old guard keyed off exactly that, so recording must not depend on it.
    """
    monkeypatch.delitem(sys.modules, "ncbi_mcp_server.server", raising=False)
    assert "ncbi_mcp_server.server" not in sys.modules

    @track_usage("search_pubmed", "search")
    async def tool(query: str):
        return {"esearchresult": {"idlist": []}}

    await tool(query="something")

    assert manager.stats.total_requests == 1


async def test_returns_error_dict_counts_as_an_error(manager):
    """MCP tools swallow their exceptions and return {'error': ...}."""

    @track_usage("get_related_articles", "search")
    async def tool(pmid: str):
        return {"error": "boom"}

    await tool(pmid="1")

    assert manager.stats.total_errors == 1
    assert manager.stats.total_requests == 1
    assert manager.events[0].error == "boom"


async def test_raised_exception_is_counted_and_propagated(manager):
    @track_usage("search_pubmed", "search")
    async def tool(query: str):
        raise RuntimeError("network down")

    with pytest.raises(RuntimeError):
        await tool(query="x")

    assert manager.stats.total_errors == 1
    assert manager.stats.total_requests == 1


async def test_positional_query_is_still_hashed(manager):
    """Only kwargs were inspected before, so positional calls lost unique_queries."""

    @track_usage("search_pubmed", "search")
    async def tool(query: str):
        return {"esearchresult": {"idlist": []}}

    await tool("positional query")

    assert manager.stats.unique_queries == 1


async def test_mesh_term_argument_is_hashed(manager):
    """search_mesh_terms names its argument 'term', not 'query'."""

    @track_usage("search_mesh_terms", "search")
    async def tool(term: str):
        return {"descriptors": [{"label": "Gene Editing"}]}

    await tool(term="base editing")

    assert manager.stats.total_mesh_searches == 1
    assert manager.stats.unique_queries == 1


async def test_result_count_reads_new_payload_shapes(manager):
    """Each fixed tool returns a different top-level key."""
    for operation, payload in [
        ("get_related_articles", {"related_pmids": ["1", "2", "3"]}),
        ("search_mesh_terms", {"descriptors": [{"label": "X"}]}),
        ("batch_get_article_details", {"articles": [{"pmid": "1"}]}),
    ]:
        @track_usage(operation, "search")
        async def tool(_payload=payload):
            return _payload

        await tool()

    counts = [event.result_count for event in manager.events]
    assert counts == [3, 1, 1]


async def test_cache_events_do_not_inflate_request_count(manager):
    """A cache lookup happens inside an already-counted request."""
    manager.record_cache_event(True)
    manager.record_cache_event(False)

    assert manager.stats.cache_hits == 1
    assert manager.stats.cache_misses == 1
    assert manager.stats.total_requests == 0


async def test_reset_clears_state_and_persists_it(manager):
    manager.record_event("search", "search_pubmed", duration_ms=5)
    manager.record_cache_event(True)
    assert manager.stats.total_requests == 1

    await manager.reset()

    assert manager.stats.total_requests == 0
    assert manager.stats.cache_hits == 0
    assert manager.stats.last_updated is None
    assert len(manager.events) == 0

    # reset() must actually clear the file, which the old stop()+start() dance did
    # not: start() reloads the previous counters immediately.
    persisted = json.loads(Path(manager.analytics_file).read_text())
    assert persisted["stats"]["total_requests"] == 0
    assert persisted["stats"]["cache_hits"] == 0


async def test_summary_reports_error_rate_over_zero_requests(manager):
    """No division-by-zero before the first request is recorded."""
    summary = await manager.get_analytics_summary()
    assert summary["overview"]["total_requests"] == 0
    assert summary["overview"]["error_rate_percent"] == 0
