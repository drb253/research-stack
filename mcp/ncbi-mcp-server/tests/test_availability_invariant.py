"""Offline tests for the evidence invariant in search_mesh_terms.

Measured pre-fix, with esummary failing::

    {"count": 0, "descriptors": [], "note": "…the term may not exist in the
     MeSH controlled vocabulary."}

A descriptor-fetch FAILURE was presented as evidence that the term does not
exist.  The fix makes that failure an explicit ``error`` field (as
``search_pubmed`` already returned), while a genuine "the API answered with
nothing" keeps the non-existence note.  No network: the HTTP layer is stubbed.
"""
from __future__ import annotations

import httpx
import pytest

from ncbi_mcp_server import server as server_module
from ncbi_mcp_server.server import search_mesh_terms

ESEARCH_OK = {
    "esearchresult": {
        "idlist": ["2016765"],
        "querytranslation": '"base editing"[MeSH Terms]',
    }
}


class _FakeResponse:
    """Minimal httpx.Response stand-in for the fields the client touches."""

    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", "https://eutils.ncbi.nlm.nih.gov"),
                response=self,
            )

    def json(self):
        return self._payload


def _stub_http(monkeypatch, esummary):
    """Answer esearch normally; route esummary to *esummary* (callable/raises).

    The module-level ``ncbi_client`` is a caching wrapper; the tests reach the
    wrapped :class:`NCBIClient` and neutralise the on-disk cache so a previous
    run can never decide the result.
    """
    wrapper = server_module.ncbi_client
    inner = wrapper.ncbi_client
    monkeypatch.setattr(inner, "min_interval", 0)

    async def _cache_get(key):
        return None

    async def _cache_set(key, value, ttl=None):
        return None

    monkeypatch.setattr(wrapper.cache, "get", _cache_get)
    monkeypatch.setattr(wrapper.cache, "set", _cache_set)

    async def fake_get(url, params=None, **kwargs):
        target = str(url)
        if "esummary.fcgi" in target:
            return esummary()
        if "esearch.fcgi" in target:
            return _FakeResponse(200, ESEARCH_OK)
        raise AssertionError(f"unexpected URL in offline test: {target}")

    monkeypatch.setattr(inner.client, "get", fake_get)
    return inner


async def test_descriptor_connection_error_is_not_nonexistence(monkeypatch):
    def connection_refused():
        raise httpx.ConnectError("stubbed connection refused")

    _stub_http(monkeypatch, connection_refused)
    result = await search_mesh_terms("base editing")

    assert result.get("error"), "a refused esummary read as success: %r" % (result,)
    assert "note" not in result, "a fetch failure asserted non-existence: %r" % (result,)


async def test_descriptor_429_is_not_nonexistence(monkeypatch):
    _stub_http(monkeypatch, lambda: _FakeResponse(429))
    result = await search_mesh_terms("base editing")

    assert result.get("error"), "a 429 read as success: %r" % (result,)
    assert "note" not in result, "a rate limit asserted non-existence: %r" % (result,)


async def test_descriptor_500_is_not_nonexistence(monkeypatch):
    _stub_http(monkeypatch, lambda: _FakeResponse(500))
    result = await search_mesh_terms("base editing")

    assert result.get("error"), "a 500 read as success: %r" % (result,)
    assert "note" not in result, "a server error asserted non-existence: %r" % (result,)


async def test_genuine_absent_term_keeps_existence_note(monkeypatch):
    """The API answered with no UIDs: that really is 'no such descriptor'."""

    async def fake_get(url, params=None, **kwargs):
        return _FakeResponse(200, {"esearchresult": {"idlist": []}})

    wrapper = server_module.ncbi_client
    inner = wrapper.ncbi_client
    monkeypatch.setattr(inner, "min_interval", 0)

    async def _cache_get(key):
        return None

    async def _cache_set(key, value, ttl=None):
        return None

    monkeypatch.setattr(wrapper.cache, "get", _cache_get)
    monkeypatch.setattr(wrapper.cache, "set", _cache_set)
    monkeypatch.setattr(inner.client, "get", fake_get)

    result = await search_mesh_terms("not a real mesh heading zzzz")
    assert "error" not in result
    assert result["count"] == 0
    assert "may not exist" in result["note"]


async def test_descriptor_fetch_answering_nothing_keeps_note(monkeypatch):
    """esummary answered but carried no records: still a genuine zero."""
    _stub_http(monkeypatch, lambda: _FakeResponse(200, {"result": {}}))
    result = await search_mesh_terms("base editing")

    assert "error" not in result
    assert result["count"] == 0
    assert "may not exist" in result["note"]
