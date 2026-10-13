"""Offline tests for the evidence invariant in the academic-search server.

Measured pre-fix, for a 429, a 500 and a refused connection alike::

    isError=false, "returned_count": 0, "total_from_api": 0, "papers": []

A failed request was indistinguishable from "no papers exist on this topic".
These tests stub the HTTP layer (raise, or answer 429) and assert the tool
answers with an explicit ``error``/``unavailable`` field, while a genuine zero
result stays a successful empty result.  No provider call leaves the machine.

Run with::

    PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from academic_search import server  # noqa: E402
from academic_search.names import author_match_diagnostic  # noqa: E402

PROVIDERS = ("crossref", "openalex", "pubmed", "semantic_scholar")

EMPTY_JSON = {
    "message": {"items": [], "next-cursor": None},
    "meta": {"next_cursor": None},
    "results": [],
    "esearchresult": {"idlist": [], "count": "0"},
    "data": [],
    "token": None,
}


class FakeResponse:
    """Minimal ``requests.Response`` stand-in."""

    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = EMPTY_JSON if payload is None else payload
        self.headers: dict = {}
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error

    def json(self):
        return self._payload


def _raise_connection(*args, **kwargs):
    raise requests.ConnectionError("stubbed refused connection")


def _answer_429(*args, **kwargs):
    return FakeResponse(429)


class SearchPapersOutageTests(unittest.TestCase):
    """A provider outage must not be reported as a zero-result success."""

    def _run(self, provider: str, http):
        # time.sleep is stubbed too: the retry loop would otherwise wait ~21s.
        with mock.patch("requests.get", side_effect=http), \
                mock.patch("time.sleep", lambda *a, **k: None):
            return server.search_papers(
                "CRISPR base editing", provider=provider, limit=5, max_retrieval=20
            )

    def test_connection_error_is_not_a_zero_result(self):
        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                result = self._run(provider, _raise_connection)
                self.assertEqual(result["returned_count"], 0)
                self.assertEqual(result.get("error"), "unavailable")
                self.assertTrue(result.get("unavailable"))

    def test_429_is_not_a_zero_result(self):
        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                result = self._run(provider, _answer_429)
                self.assertEqual(result["returned_count"], 0)
                self.assertEqual(result.get("error"), "unavailable")
                self.assertEqual(result["unavailable"].get("status"), 429)

    def test_genuine_zero_result_stays_successful(self):
        """The API answered 200 with no records: a real empty result."""
        def empty_ok(*args, **kwargs):
            return FakeResponse(200)

        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                result = self._run(provider, empty_ok)
                self.assertEqual(result["returned_count"], 0)
                self.assertNotIn("error", result)
                self.assertNotIn("unavailable", result)

    def test_doi_404_is_a_clean_empty_for_semantic_scholar(self):
        """A 404 answers "no such record" -- it is not an outage."""
        def not_found(*args, **kwargs):
            return FakeResponse(404)

        result = self._run("semantic_scholar", not_found)
        self.assertEqual(result["returned_count"], 0)
        self.assertNotIn("error", result)


class SearchByAuthorOutageTests(unittest.TestCase):
    """The author diagnostic must name an outage, not 'no candidates'."""

    def _run(self, provider: str):
        with mock.patch("requests.get", side_effect=_raise_connection), \
                mock.patch("time.sleep", lambda *a, **k: None):
            return server.search_by_author(
                author_name="Jennifer Doudna", provider=provider, limit=5
            )

    def test_outage_is_reported_as_unavailable(self):
        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                result = self._run(provider)
                self.assertEqual(result.get("error"), "unavailable")
                self.assertEqual(result["diagnostic"]["reason"], "provider_unavailable")

    def test_diagnostic_reason_distinguishes_outage_from_no_candidates(self):
        outage = author_match_diagnostic(
            "Jennifer Doudna", [], 0, unavailable={"kind": "connection_error"}
        )
        genuine = author_match_diagnostic("Jennifer Doudna", [], 0)
        self.assertEqual(outage["reason"], "provider_unavailable")
        self.assertEqual(genuine["reason"], "provider_returned_no_candidates")
        self.assertNotEqual(outage["reason"], genuine["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
