"""Regression tests for the locally patched academic-search MCP.

These tests are offline: no provider call is made.  Each test class maps onto
one of the four defects that were fixed.

* :class:`AuthorMatchingTests`  -- literal-substring author filter (bug 1)
* :class:`RelevanceTests`      -- Crossref relevance gate (bug 2)
* :class:`RecordQualityTests`  -- junk records passed through (bug 3)
* :class:`IdentifierTests`     -- seed identifier forms / error handling (bug 4)

Run with::

    ./.venv/bin/python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from academic_search.names import (  # noqa: E402
    author_match_diagnostic,
    filter_by_author,
    name_matches,
    parse_name,
)
from academic_search.quality import (  # noqa: E402
    completeness_score,
    filter_usable_records,
    is_usable_record,
    query_terms,
    rank_by_relevance,
    relevance_score,
)


class AuthorMatchingTests(unittest.TestCase):
    """Bug 1: 'Jennifer Doudna' returned 0 rows while the API had 227."""

    def test_full_name_matches_middle_initial(self) -> None:
        """The exact case that silently returned nothing before the fix."""
        self.assertTrue(name_matches("Jennifer Doudna", "Jennifer A. Doudna"))

    def test_full_name_matches_initial_form(self) -> None:
        self.assertTrue(name_matches("Jennifer Doudna", "J. Doudna"))

    def test_surname_only_query_matches_any_rendering(self) -> None:
        self.assertTrue(name_matches("Doudna", "Jennifer A. Doudna"))
        self.assertTrue(name_matches("Doudna", "J. Doudna"))

    def test_comma_form_matches(self) -> None:
        """Crossref renders names as 'Family, Given'."""
        self.assertTrue(name_matches("Jennifer Doudna", "Doudna, Jennifer"))

    def test_middle_name_in_query_matches_shorter_candidate(self) -> None:
        self.assertTrue(name_matches("Jennifer A. Doudna", "Jennifer Doudna"))

    def test_distinct_given_names_do_not_match(self) -> None:
        """Initial matching must not make every same-surname author a match."""
        self.assertFalse(name_matches("Jennifer Doudna", "John Doudna"))

    def test_distinct_surnames_do_not_match(self) -> None:
        self.assertFalse(name_matches("Jennifer Doudna", "Jennifer Doudnax"))

    def test_particles_stay_with_surname(self) -> None:
        self.assertTrue(name_matches("Ludwig van Beethoven", "van Beethoven, Ludwig"))

    def test_accents_are_folded(self) -> None:
        self.assertTrue(name_matches("Jose Garcia", "José García"))

    def test_initials_only_query_matches_full_name(self) -> None:
        self.assertTrue(name_matches("J. Doudna", "Jennifer Doudna"))

    def test_initial_match_can_be_disabled(self) -> None:
        self.assertFalse(
            name_matches("Jennifer Doudna", "J. Doudna", allow_initial_match=False)
        )
        self.assertTrue(
            name_matches("Jennifer Doudna", "Jennifer Doudna", allow_initial_match=False)
        )

    def test_surname_only_can_be_disabled(self) -> None:
        self.assertFalse(
            name_matches("Doudna", "Jennifer Doudna", allow_surname_only=False)
        )

    def test_parse_name_handles_empty_and_junk(self) -> None:
        self.assertEqual(parse_name("").surname, "")
        self.assertEqual(parse_name("   ").surname, "")
        self.assertEqual(parse_name("Doudna, ").surname, "doudna")

    def test_filter_by_author_reports_matched_names(self) -> None:
        papers = [
            {"authors": [{"name": "Jennifer A. Doudna"}]},
            {"authors": [{"name": "John Doudna"}]},
            {"authors": [{"name": "Someone Else"}]},
        ]
        kept, matched = filter_by_author(papers, "Jennifer Doudna")
        self.assertEqual(len(kept), 1)
        self.assertEqual(matched, ["Jennifer A. Doudna"])

    def test_filter_ignores_papers_without_authors(self) -> None:
        papers = [{}, {"authors": "not-a-list"}, {"authors": []}]
        kept, matched = filter_by_author(papers, "Jennifer Doudna")
        self.assertEqual(kept, [])
        self.assertEqual(matched, [])

    def test_diagnostic_explains_zero_matches(self) -> None:
        """A silent empty list must never be returned again."""
        diag = author_match_diagnostic(
            "Jennifer Doudna",
            [],
            227,
            candidate_names=["Jennifer A. Doudna", "J. Doudna"],
        )
        self.assertIsNotNone(diag)
        assert diag is not None
        self.assertEqual(diag["reason"], "no_name_parts_matched")
        self.assertEqual(diag["total_from_api"], 227)
        self.assertIn("Doudna", diag["suggested_queries"])
        self.assertEqual(
            diag["sample_candidate_names"], ["Jennifer A. Doudna", "J. Doudna"]
        )

    def test_diagnostic_for_empty_provider_result(self) -> None:
        diag = author_match_diagnostic("Nobody Here", [], 0)
        self.assertIsNotNone(diag)
        assert diag is not None
        self.assertEqual(diag["reason"], "provider_returned_no_candidates")


class RelevanceTests(unittest.TestCase):
    """Bug 2: Crossref returned 'denture base' for the query 'base editing'."""

    DENTURE = {
        "title": "The pontic-splinted procedure for tooth and denture base additions",
        "abstract": None,
        "journal": "The Journal of Prosthetic Dentistry",
    }
    BASE_EDITING = {
        "title": "Base editing of the human genome",
        "abstract": "Base editors perform precise base substitution.",
        "journal": "Nature",
    }

    def test_query_terms_drops_stopwords(self) -> None:
        self.assertEqual(query_terms("the base editing of"), ["base", "editing"])

    def test_irrelevant_record_scores_below_gate(self) -> None:
        """Only 'base' matches, so the record fails a full-terms gate."""
        self.assertLess(relevance_score("base editing", self.DENTURE), 1.0)

    def test_relevant_record_passes_gate(self) -> None:
        self.assertEqual(relevance_score("base editing", self.BASE_EDITING), 1.0)

    def test_whole_word_matching_only(self) -> None:
        """'base' must not match inside 'database'."""
        self.assertEqual(relevance_score("base", {"title": "Database systems"}), 0.0)

    def test_abstract_contributes_to_the_score(self) -> None:
        paper = {"title": "Unrelated title", "abstract": "base editing is precise"}
        self.assertEqual(relevance_score("base editing", paper), 1.0)

    def test_empty_query_scores_one(self) -> None:
        """Nothing to filter on, so nothing may be dropped."""
        self.assertEqual(relevance_score("", {"title": "anything"}), 1.0)

    def test_rank_by_relevance_orders_best_first(self) -> None:
        ranked = rank_by_relevance(
            [self.DENTURE, self.BASE_EDITING], "base editing"
        )
        self.assertIs(ranked[0], self.BASE_EDITING)

    def test_rank_by_relevance_is_stable_for_ties(self) -> None:
        a = {"title": "base editing one", "citationCount": 1}
        b = {"title": "base editing two", "citationCount": 1}
        ranked = rank_by_relevance([a, b], "base editing")
        self.assertEqual([id(p) for p in ranked], [id(a), id(b)])


class RecordQualityTests(unittest.TestCase):
    """Bug 3: junk records reached the top of the result list."""

    # Verbatim shape from the live response that motivated the fix. Note it
    # carries a paperId AND a CorpusId: an earlier version of the check treated
    # an identifier as evidence of quality, which made it a no-op on this very
    # record. This fixture is the regression guard for that mistake.
    JUNK = {
        "paperId": "00047d3348061683b2105ddad64563fdd73302c3",
        "externalIds": {"CorpusId": 250116566},
        "title": "GABA OF THE THALAMIC NUCLEUS REGULATE SLEEP SPINDLES: AN IN VIVO",
        "year": None,
        "authors": [],
        "abstract": None,
        "journal": None,
        "citationCount": 0,
        "referenceCount": 0,
    }
    # Sparse but real: a journal is present even though year/authors are not.
    SPARSE_BUT_USEFUL = {
        "paperId": "10.1/abc",
        "title": "A real paper",
        "year": None,
        "authors": [],
        "abstract": None,
        "externalIds": {"DOI": "10.1/abc"},
        "journal": "Journal of Real Things",
        "citationCount": 0,
        "referenceCount": 0,
    }

    def test_junk_record_is_unusable(self) -> None:
        self.assertFalse(is_usable_record(self.JUNK))

    def test_identifier_alone_does_not_make_a_record_usable(self) -> None:
        """The regression that made the first version of this check useless."""
        self.assertFalse(is_usable_record(self.JUNK))
        self.assertFalse(
            is_usable_record(
                {
                    "paperId": "abc",
                    "externalIds": {"CorpusId": 1},
                    "title": "A title",
                    "year": None,
                    "authors": [],
                    "abstract": None,
                    "journal": None,
                    "citationCount": 0,
                    "referenceCount": 0,
                }
            )
        )

    def test_sparse_record_with_a_substantive_field_is_kept(self) -> None:
        """Sparse metadata is normal; only total emptiness is junk."""
        self.assertTrue(is_usable_record(self.SPARSE_BUT_USEFUL))

    def test_citations_alone_make_a_record_usable(self) -> None:
        self.assertTrue(
            is_usable_record(
                {
                    "title": "T",
                    "year": None,
                    "authors": [],
                    "abstract": None,
                    "journal": None,
                    "citationCount": 7,
                    "referenceCount": 0,
                }
            )
        )

    def test_filter_usable_records_reports_dropped_count(self) -> None:
        kept, dropped = filter_usable_records(
            [self.JUNK, self.SPARSE_BUT_USEFUL]
        )
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, 1)

    def test_non_dict_is_unusable(self) -> None:
        self.assertFalse(is_usable_record(None))  # type: ignore[arg-type]

    def test_completeness_score_range(self) -> None:
        """Fully empty scores 0.0; one field of five present scores 0.2."""
        self.assertEqual(completeness_score({}), 0.0)
        self.assertAlmostEqual(completeness_score(self.JUNK), 0.2)  # CorpusId only
        self.assertAlmostEqual(
            completeness_score({"year": None, "title": "T", "externalIds": {"DOI": "d"}}),
            0.2,
        )
        self.assertEqual(
            completeness_score(
                {
                    "year": 2020,
                    "authors": [{"name": "A"}],
                    "abstract": "x",
                    "externalIds": {"DOI": "d"},
                    "journal": {"name": "J"},
                }
            ),
            1.0,
        )


class IdentifierTests(unittest.TestCase):
    """Bug 4: seed identifier handling and failure reporting."""

    def _provider(self):
        from academic_search.providers.semantic_scholar import (
            SemanticScholarProvider,
        )

        return SemanticScholarProvider()

    def test_normalize_doi_forms(self) -> None:
        prov = self._provider()
        expected = "DOI:10.1038/s41586-020-2649-2"
        for raw in (
            "10.1038/s41586-020-2649-2",
            "doi:10.1038/s41586-020-2649-2",
            "DOI:10.1038/s41586-020-2649-2",
            "https://doi.org/10.1038/s41586-020-2649-2",
            "https://dx.doi.org/10.1038/s41586-020-2649-2",
            "10.1038/s41586-020-2649-2.",
        ):
            self.assertEqual(prov.normalize_identifier(raw), expected, raw)

    def test_is_doi_accepts_prefixed_forms(self) -> None:
        """The 'DOI:' prefix was wrongly blamed for a throttle failure."""
        prov = self._provider()
        self.assertTrue(prov._is_doi("DOI:10.1038/s41586-020-2649-2"))
        self.assertTrue(prov._is_doi("doi:10.1038/s41586-020-2649-2"))
        self.assertFalse(prov._is_doi("Jennifer Doudna"))

    def test_normalize_arxiv_forms(self) -> None:
        prov = self._provider()
        self.assertEqual(prov.normalize_identifier("2006.10256"), "ARXIV:2006.10256")
        self.assertEqual(
            prov.normalize_identifier("arXiv:2006.10256"), "ARXIV:2006.10256"
        )
        self.assertEqual(
            prov.normalize_identifier("arXiv:2006.10256v3"), "ARXIV:2006.10256"
        )
        self.assertEqual(
            prov.normalize_identifier("https://arxiv.org/abs/2006.10256"),
            "ARXIV:2006.10256",
        )

    def test_normalize_pmid_forms(self) -> None:
        prov = self._provider()
        self.assertEqual(prov.normalize_identifier("PMID:32939066"), "PMID:32939066")
        self.assertEqual(prov.normalize_identifier("32939066"), "PMID:32939066")

    def test_normalize_corpusid_form(self) -> None:
        prov = self._provider()
        self.assertEqual(
            prov.normalize_identifier("CorpusId:219792763"), "CorpusId:219792763"
        )

    def test_normalize_semantic_scholar_url(self) -> None:
        prov = self._provider()
        sha = "024a2c03be8e468e7c4fdf9bda36cdc0eaae85fb"
        self.assertEqual(
            prov.normalize_identifier(
                f"https://www.semanticscholar.org/paper/{sha}"
            ),
            sha,
        )
        self.assertEqual(
            prov.normalize_identifier(
                f"https://api.semanticscholar.org/graph/v1/paper/{sha}?fields=title"
            ),
            sha,
        )

    def test_bare_paper_id_is_passed_through(self) -> None:
        prov = self._provider()
        sha = "024a2c03be8e468e7c4fdf9bda36cdc0eaae85fb"
        self.assertEqual(prov.normalize_identifier(sha), sha)

    def test_empty_identifier(self) -> None:
        prov = self._provider()
        self.assertEqual(prov.normalize_identifier(""), "")

    def test_failure_message_identifies_rate_limiting(self) -> None:
        """Tracking the status is what makes the error actionable."""
        prov = self._provider()
        prov._last_request_error = {"kind": "http_error", "status": 429, "attempt": 5}
        message = prov._failure_message("fetch seed paper metadata")
        self.assertIn("rate limit", message)
        self.assertIn("S2_API_KEY", message)

    def test_failure_message_for_timeout_and_unknown(self) -> None:
        prov = self._provider()
        prov._last_request_error = {"kind": "timeout", "attempt": 5}
        self.assertIn("timed out", prov._failure_message("walk"))
        prov._last_request_error = None
        self.assertIn("unknown upstream failure", prov._failure_message("walk"))

    def test_api_key_header_added_when_env_set(self) -> None:
        from academic_search.providers.semantic_scholar import _api_headers

        os.environ["S2_API_KEY"] = "secret-key"
        try:
            self.assertEqual(_api_headers()["x-api-key"], "secret-key")
        finally:
            del os.environ["S2_API_KEY"]
        self.assertNotIn("x-api-key", _api_headers())


class SemanticScholarProviderTests(unittest.TestCase):
    """End-to-end filter behaviour, with the network stubbed out."""

    def _provider(self, papers):
        from academic_search.providers.semantic_scholar import (
            SemanticScholarProvider,
        )

        prov = SemanticScholarProvider()
        # Replace the paginating fetch so no HTTP request is made.
        prov._fetch_all = lambda *a, **k: papers  # type: ignore[method-assign]
        return prov

    def test_full_name_author_search_now_finds_matches(self) -> None:
        """Regression: this returned an empty list before the fix."""
        prov = self._provider(
            [
                {
                    "paperId": "p1",
                    "title": "CRISPR technology",
                    "authors": [{"name": "Jennifer A. Doudna"}],
                },
                {
                    "paperId": "p2",
                    "title": "Other work",
                    "authors": [{"name": "Someone Else"}],
                },
            ]
        )
        papers, meta = prov.search_by_author("Jennifer Doudna", limit=10)
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["paperId"], "p1")
        self.assertEqual(meta["total_after_author_filter"], 1)
        self.assertEqual(meta["matched_author_names"], ["Jennifer A. Doudna"])

    def test_zero_match_reports_candidate_sample(self) -> None:
        prov = self._provider(
            [{"paperId": "p", "authors": [{"name": "Someone Else"}]}]
        )
        papers, meta = prov.search_by_author("Nobody Here", limit=10)
        self.assertEqual(papers, [])
        self.assertEqual(meta["candidate_name_sample"], ["Someone Else"])

    def test_initial_only_candidate_matches(self) -> None:
        prov = self._provider(
            [{"paperId": "p", "authors": [{"name": "J. Doudna"}]}]
        )
        papers, _ = prov.search_by_author("Jennifer Doudna", limit=10)
        self.assertEqual(len(papers), 1)


class CrossrefProviderTests(unittest.TestCase):
    """Bug 2: year extraction and comma-form author names."""

    def _standardize(self, item):
        from academic_search.providers.crossref import CrossrefProvider

        return CrossrefProvider._standardize(item)

    def test_issued_is_preferred_over_created(self) -> None:
        record = self._standardize(
            {
                "DOI": "10.1/x",
                "title": ["A paper"],
                "issued": {"date-parts": [[2019, 5, 1]]},
                "created": {"date-parts": [[2024, 1, 1]]},
                "author": [{"given": "Jane", "family": "Doe"}],
                "type": "journal-article",
            }
        )
        self.assertEqual(record["year"], 2019)
        self.assertEqual(record["publicationDate"], "2019-05-01")

    def test_created_used_as_fallback(self) -> None:
        record = self._standardize(
            {"DOI": "10.1/y", "title": ["P"], "created": {"date-parts": [[2021]]}}
        )
        self.assertEqual(record["year"], 2021)
        self.assertEqual(record["publicationDate"], "2021")

    def test_missing_dates_stay_none(self) -> None:
        record = self._standardize({"DOI": "10.1/z", "title": ["P"]})
        self.assertIsNone(record["year"])
        self.assertIsNone(record["publicationDate"])

    def test_standardized_author_matches_full_name(self) -> None:
        """Crossref gives 'Given Family'; the matcher must accept it."""
        record = self._standardize(
            {
                "DOI": "10.1/w",
                "title": ["P"],
                "author": [{"given": "Jennifer", "family": "Doudna"}],
            }
        )
        self.assertEqual(record["authors"], [{"name": "Jennifer Doudna"}])
        kept, _ = filter_by_author([record], "Jennifer Doudna")
        self.assertEqual(len(kept), 1)

    def test_standardize_filters_ellipsis_free_abstract_markup(self) -> None:
        record = self._standardize(
            {"DOI": "10.1/v", "title": ["P"], "abstract": "<jats:p>Base editing</jats:p>"}
        )
        self.assertEqual(record["abstract"], "Base editing")


if __name__ == "__main__":
    unittest.main(verbosity=2)


