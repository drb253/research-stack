#!/usr/bin/env python3
"""Offline regression test for the evidence invariant in paper-search-mcp.

The invariant: a lookup that FAILED because the network or the remote API was
unavailable must never be reported as "no results found".  These tests stub the
HTTP layer -- raise a connection error, or answer 429 -- and assert the affected
tool returns an explicit availability marker rather than an empty success.

Offline and deterministic: no real request is made.  Runs either against the
installed patched package or, when ``PAPER_SEARCH_MCP_PATH`` is set, against
that *parent directory* (the one containing ``paper_search_mcp/``), which is
how a reverted copy is proved to fail the suite.

    <tool-venv>/bin/python test_availability_invariant.py
    PAPER_SEARCH_MCP_PATH=/tmp/mutant <venv>/bin/python test_availability_invariant.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

logging.disable(logging.CRITICAL)

# The caller may point us at a mutated copy; otherwise prefer the installed
# package and fall back to the sibling vendored tree in this repository.
_override = os.environ.get("PAPER_SEARCH_MCP_PATH")
if _override:
    sys.path.insert(0, _override)
else:
    try:  # pragma: no cover - depends on how the interpreter is invoked
        import paper_search_mcp  # noqa: F401
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "paper-search-mcp"))

import requests  # noqa: E402

from paper_search_mcp.academic_platforms import openaire as openaire_module  # noqa: E402
from paper_search_mcp.academic_platforms.openaire import OpenAiresearcher  # noqa: E402
from paper_search_mcp.academic_platforms.unpaywall import (  # noqa: E402
    UnpaywallResolver,
    UnpaywallSearcher,
)
from paper_search_mcp.source_status import (  # noqa: E402
    SOURCE_OK,
    SOURCE_UNAVAILABLE,
    SourceUnavailable,
    is_unavailable_marker,
    split_markers,
    unavailable_marker,
)

TOOL = "10.1038/s41586-020-2649-2"


class FakeResponse:
    """Minimal stand-in for ``requests.Response``."""

    def __init__(self, status_code: int, payload=None, content: bytes = b""):
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self.content = content
        self.text = content.decode("utf-8", "replace") if content else ""
        self.headers: dict = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"HTTP {self.status_code}", response=self
            )

    def json(self):
        return self._payload


@contextmanager
def _no_sleep():
    with mock.patch.object(openaire_module.time, "sleep", lambda *a, **k: None):
        yield


def _raise_connection(*args, **kwargs):
    raise requests.ConnectionError("stubbed refused connection")


def _return(status, payload=None, content=b""):
    def _inner(*args, **kwargs):
        return FakeResponse(status, payload, content)
    return _inner


class OpenAireAvailabilityTests(unittest.TestCase):
    """openaire.search() must raise, not return [], when every path fails."""

    def _searcher(self):
        searcher = OpenAiresearcher()
        return searcher

    def test_connection_error_is_not_an_empty_result(self):
        searcher = self._searcher()
        with mock.patch.object(searcher.session, "get", _raise_connection), \
                mock.patch.object(openaire_module.requests, "get", _raise_connection), \
                _no_sleep():
            with self.assertRaises(SourceUnavailable):
                searcher.search("CRISPR base editing", 3)

    def test_429_is_not_an_empty_result(self):
        searcher = self._searcher()
        with mock.patch.object(searcher.session, "get", _return(429)), \
                mock.patch.object(openaire_module.requests, "get", _return(429)), \
                _no_sleep():
            with self.assertRaises(SourceUnavailable):
                searcher.search("CRISPR base editing", 3)

    def test_500_is_not_an_empty_result(self):
        searcher = self._searcher()
        with mock.patch.object(searcher.session, "get", _return(500)), \
                mock.patch.object(openaire_module.requests, "get", _return(500)), \
                _no_sleep():
            with self.assertRaises(SourceUnavailable):
                searcher.search("CRISPR base editing", 3)

    def test_genuine_empty_answer_is_still_empty(self):
        """A path that answered 200 with no records is a real zero result."""
        searcher = self._searcher()
        empty_legacy = {"response": {"results": {"result": []}}}
        with mock.patch.object(searcher, "_search_graph_api", lambda *a, **k: []), \
                mock.patch.object(searcher, "_search_with_retry", lambda *a, **k: []), \
                mock.patch.object(searcher.session, "get", _return(200, empty_legacy)):
            self.assertEqual(searcher.search("nothing here", 3), [])


class UnpaywallAvailabilityTests(unittest.TestCase):
    """A 404 is a real "no record"; a transport failure is an outage."""

    def _searcher(self):
        resolver = UnpaywallResolver(email="stub@example.com")
        return UnpaywallSearcher(resolver=resolver)

    def test_connection_error_is_not_an_empty_result(self):
        searcher = self._searcher()
        with mock.patch.object(searcher.resolver.session, "get", _raise_connection):
            with self.assertRaises(SourceUnavailable):
                searcher.search(TOOL, 5)

    def test_429_is_not_an_empty_result(self):
        searcher = self._searcher()
        with mock.patch.object(searcher.resolver.session, "get", _return(429)):
            with self.assertRaises(SourceUnavailable):
                searcher.search(TOOL, 5)

    def test_404_is_a_real_no_record(self):
        searcher = self._searcher()
        with mock.patch.object(searcher.resolver.session, "get", _return(404)):
            self.assertEqual(searcher.search(TOOL, 5), [])

    def test_marker_shape(self):
        marker = unavailable_marker(SourceUnavailable("unpaywall", "boom", 429))
        self.assertTrue(is_unavailable_marker(marker[0]))
        self.assertEqual(marker[0]["error"], "unavailable")


class ToolBoundaryTests(unittest.TestCase):
    """The MCP tool must not hand the agent an indistinguishable empty list."""

    def test_search_openaire_marks_unavailable(self):
        from paper_search_mcp import server

        with mock.patch.object(server.openaire_searcher.session, "get", _raise_connection), \
                mock.patch.object(openaire_module.requests, "get", _raise_connection), \
                _no_sleep():
            result = asyncio.run(server.search_openaire("CRISPR base editing", 3))
        self.assertTrue(result, "an outage produced an empty list")
        self.assertTrue(is_unavailable_marker(result[0]))
        self.assertEqual(result[0]["error"], "unavailable")

    def test_search_unpaywall_marks_unavailable(self):
        from paper_search_mcp import server

        server.unpaywall_searcher.resolver.email = "stub@example.com"
        with mock.patch.object(
            server.unpaywall_searcher.resolver.session, "get", _raise_connection
        ):
            result = asyncio.run(server.search_unpaywall(TOOL, 3))
        self.assertTrue(result, "an outage produced an empty list")
        self.assertTrue(is_unavailable_marker(result[0]))
        self.assertEqual(result[0]["error"], "unavailable")


class MarkerShapeTests(unittest.TestCase):
    """A marker is a marker, and a paper is never one -- in both directions."""

    def test_split_markers_separates_papers_from_markers(self):
        marker = unavailable_marker(SourceUnavailable("openaire", "boom", 429))[0]
        paper = {"title": "A real paper", "doi": "10.1000/x"}
        papers, markers = split_markers([paper, marker])
        self.assertEqual(papers, [paper])
        self.assertEqual(markers, [marker])

    def test_a_paper_with_an_error_field_is_not_a_marker(self):
        # A record that merely carries an `error` key -- and has a title -- is a paper.
        # Without the title check, a real record would be swallowed as an outage.
        self.assertFalse(is_unavailable_marker(
            {"title": "A real paper", "error": SOURCE_UNAVAILABLE, "paper_id": "x"}
        ))
        self.assertFalse(is_unavailable_marker({"title": "A real paper"}))
        self.assertFalse(is_unavailable_marker({"error": SOURCE_UNAVAILABLE, "paper_id": "x"}))
        self.assertTrue(is_unavailable_marker(
            unavailable_marker(SourceUnavailable("openaire", "boom", 429))[0]
        ))


class AggregateStatusTests(unittest.TestCase):
    """`search_papers` must put an outage in `source_status`, never in the paper list.

    This is the user-visible consequence the module docstring claims -- "so a failed lookup
    is never mistaken for absent literature" -- and nothing asserted it before.
    """

    def _run(self, factory):
        from paper_search_mcp import server

        with mock.patch.object(server, "_build_task_map",
                               lambda *a, **k: {"openaire": factory()}):
            return asyncio.run(server.search_papers("CRISPR base editing", 3,
                                                    sources="openaire"))

    def test_outage_is_recorded_as_a_status_not_as_papers(self):
        async def outage():
            raise SourceUnavailable("openaire", "connection refused", None)

        result = self._run(outage)
        status = result["source_status"]["openaire"]
        self.assertEqual(status["status"], SOURCE_UNAVAILABLE)
        self.assertTrue(status.get("message"), "the outage must carry a reason")
        self.assertEqual([p for p in result["papers"] if is_unavailable_marker(p)], [])

    def test_success_is_not_reported_as_unavailable(self):
        """The specificity half: an outage marker must not appear on a working lookup.

        Without this, a mutation that reported *everything* as unavailable would pass the
        whole suite: every test asserted an outage is caught, none that a success is left
        alone.
        """
        async def success():
            return [{"title": "A real paper", "doi": "10.1000/x", "source": "openaire"}]

        result = self._run(success)
        status = result["source_status"]["openaire"]
        self.assertEqual(status["status"], SOURCE_OK)
        self.assertNotEqual(status["status"], SOURCE_UNAVAILABLE)
        self.assertTrue(result["papers"], "a successful lookup returned no papers")
        self.assertEqual([p for p in result["papers"] if is_unavailable_marker(p)], [])

    def test_empty_is_neither_unavailable_nor_a_paper(self):
        async def empty():
            return []

        result = self._run(empty)
        status = result["source_status"]["openaire"]
        self.assertNotEqual(status["status"], SOURCE_UNAVAILABLE)
        self.assertEqual(result["papers"], [])


def main(argv=None) -> int:
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
