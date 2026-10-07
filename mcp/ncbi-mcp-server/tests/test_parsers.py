"""Parser tests for the payload shapes that previously leaked raw NCBI data.

Two tools returned whatever NCBI happened to send rather than the structure their
docstrings promised:

* get_related_articles returned the raw ELink document (~22k characters of nested
  link IDs, truncated by the transport) instead of related_pmids/total_related.
* search_mesh_terms returned the esearch envelope (a list of UIDs) instead of
  descriptors with labels, synonyms and scope notes.

These tests pin the parsed contracts. They use synthetic fixtures, so no network.
"""
import pytest

from ncbi_mcp_server.server import NCBIClient

parse_elink = NCBIClient._parse_elink_related
parse_mesh = NCBIClient._parse_mesh_summary


ELINK_PAYLOAD = {
    "header": {"type": "elink", "version": "0.3"},
    "linksets": [{
        "dbfrom": "pubmed",
        "ids": ["38308006"],
        "linksetdbs": [
            # ELink echoes the query PMID back as the first element of every set.
            {"dbto": "pubmed", "linkname": "pubmed_pubmed",
             "links": ["38308006", "31227932", "31759123", "34942274"]},
            {"dbto": "pubmed", "linkname": "pubmed_pubmed_reviews",
             "links": ["38308006", "29958882", "29958882"]},
            {"dbto": "pubmed", "linkname": "pubmed_pubmed_reviews_five",
             "links": ["38308006"]},
        ],
    }],
}


class TestElinkRelatedArticles:
    def test_returns_parsed_shape_not_raw_elink(self):
        result = parse_elink(ELINK_PAYLOAD, "38308006", 10)
        assert "linksets" not in result
        assert "header" not in result
        assert result["related_pmids"] == ["31227932", "31759123", "34942274"]

    def test_seed_pmid_is_excluded(self):
        result = parse_elink(ELINK_PAYLOAD, "38308006", 10)
        assert "38308006" not in result["related_pmids"]
        assert "38308006" not in result["reviews"]

    def test_max_results_truncates_but_total_is_full(self):
        result = parse_elink(ELINK_PAYLOAD, "38308006", 2)
        assert result["related_pmids"] == ["31227932", "31759123"]
        assert result["total_related"] == 3

    def test_max_results_zero_returns_nothing(self):
        result = parse_elink(ELINK_PAYLOAD, "38308006", 0)
        assert result["related_pmids"] == []
        assert result["total_related"] == 3

    def test_invalid_max_results_falls_back_to_default(self):
        result = parse_elink(ELINK_PAYLOAD, "38308006", None)
        assert len(result["related_pmids"]) == 3

    def test_duplicates_are_removed(self):
        result = parse_elink(ELINK_PAYLOAD, "38308006", 10)
        assert result["reviews"] == ["29958882"]

    def test_primary_link_set_prefers_pubmed_pubmed(self):
        result = parse_elink(ELINK_PAYLOAD, "38308006", 10)
        assert result["primary_link_set"] == "pubmed_pubmed"
        assert result["link_sets"] == [
            "pubmed_pubmed",
            "pubmed_pubmed_reviews",
            "pubmed_pubmed_reviews_five",
        ]

    def test_falls_back_when_pubmed_pubmed_absent(self):
        payload = {"linksets": [{
            "ids": ["1"],
            "linksetdbs": [{"linkname": "pubmed_pubmed_citedin", "links": ["1", "5"]}],
        }]}
        result = parse_elink(payload, "1", 10)
        assert result["primary_link_set"] == "pubmed_pubmed_citedin"
        assert result["related_pmids"] == ["5"]

    def test_ignores_linksets_for_other_seed_ids(self):
        payload = {"linksets": [
            {"ids": ["999"], "linksetdbs": [{"linkname": "pubmed_pubmed", "links": ["7"]}]},
            {"ids": ["1"], "linksetdbs": [{"linkname": "pubmed_pubmed", "links": ["8"]}]},
        ]}
        result = parse_elink(payload, "1", 10)
        assert result["related_pmids"] == ["8"]

    def test_empty_payload_is_handled_not_raised(self):
        result = parse_elink({"linksets": []}, "1", 10)
        assert result["related_pmids"] == []
        assert result["total_related"] == 0
        assert result["link_sets"] == []
        assert "note" in result

    def test_tolerates_malformed_linksets(self):
        payload = {"linksets": [
            "not-a-dict",
            {"ids": ["1"],
             "linksetdbs": ["nope", {"linkname": "pubmed_pubmed", "links": ["1", "2"]}]},
        ]}
        result = parse_elink(payload, "1", 10)
        assert result["related_pmids"] == ["2"]

    def test_integer_link_ids_are_stringified(self):
        payload = {"linksets": [{
            "ids": ["1"],
            "linksetdbs": [{"linkname": "pubmed_pubmed", "links": [1, 42]}],
        }]}
        result = parse_elink(payload, "1", 10)
        assert result["related_pmids"] == ["42"]


MESH_PAYLOAD = {
    "result": {
        "uids": ["2016765"],
        "2016765": {
            "uid": "2016765",
            "ds_meshui": "D000072669",
            "ds_meshterms": [
                "Gene Editing", "Editing, Gene", "Genome Editing", "Base Editing",
            ],
            "ds_scopenote": "Genetic engineering or molecular biology techniques ...",
            "ds_yearintroduced": "2017",
            "ds_recordtype": "descriptor",
            "ds_idxlinks": [{"parent": 68005818, "treenum": "E05.393.420.270", "children": []}],
        },
    }
}


class TestMeshDescriptors:
    def test_returns_descriptors_not_an_esearch_envelope(self):
        descriptors = parse_mesh(MESH_PAYLOAD, ["2016765"], "base editing")
        assert isinstance(descriptors, list) and descriptors
        assert "uid" in descriptors[0]

    def test_documented_descriptor_fields_are_present(self):
        descriptor = parse_mesh(MESH_PAYLOAD, ["2016765"], "base editing")[0]
        assert descriptor["label"] == "Gene Editing"
        assert descriptor["mesh_ui"] == "D000072669"
        assert descriptor["scope_note"].startswith("Genetic engineering")
        assert descriptor["synonyms"] == ["Editing, Gene", "Genome Editing", "Base Editing"]

    def test_synonyms_exclude_the_preferred_heading(self):
        descriptor = parse_mesh(MESH_PAYLOAD, ["2016765"], "base editing")[0]
        assert descriptor["label"] not in descriptor["synonyms"]

    def test_matched_term_records_the_entry_term_that_matched(self):
        """'base editing' is an entry term of Gene Editing, not a loose mapping."""
        descriptor = parse_mesh(MESH_PAYLOAD, ["2016765"], "base editing")[0]
        assert descriptor["matched_term"] == "Base Editing"

    def test_matched_term_is_case_and_space_insensitive(self):
        descriptor = parse_mesh(MESH_PAYLOAD, ["2016765"], "  BASE   editing ")[0]
        assert descriptor["matched_term"] == "Base Editing"

    def test_matched_term_is_none_when_nothing_matches_exactly(self):
        descriptor = parse_mesh(MESH_PAYLOAD, ["2016765"], "genome engineering")[0]
        assert descriptor["matched_term"] is None
        assert descriptor["label"] == "Gene Editing"

    def test_tree_numbers_extracted(self):
        descriptor = parse_mesh(MESH_PAYLOAD, ["2016765"], "base editing")[0]
        assert descriptor["tree_numbers"] == ["E05.393.420.270"]

    def test_record_type_and_year_exposed(self):
        descriptor = parse_mesh(MESH_PAYLOAD, ["2016765"], "base editing")[0]
        assert descriptor["record_type"] == "descriptor"
        assert descriptor["year_introduced"] == "2017"

    def test_records_reporting_an_error_are_skipped(self):
        payload = {"result": {"uids": ["1"], "1": {"error": "Invalid uid"}}}
        assert parse_mesh(payload, ["1"], "x") == []

    def test_missing_uid_is_skipped(self):
        assert parse_mesh({"result": {"uids": ["9"]}}, ["9"], "x") == []

    def test_empty_terms_do_not_crash(self):
        payload = {"result": {"uids": ["1"], "1": {"ds_meshterms": []}}}
        descriptor = parse_mesh(payload, ["1"], "x")[0]
        assert descriptor["label"] is None
        assert descriptor["synonyms"] == []

    def test_result_block_missing(self):
        assert parse_mesh({}, ["1"], "x") == []

    def test_non_string_terms_are_ignored(self):
        payload = {"result": {"uids": ["1"], "1": {"ds_meshterms": [None, "  ", "Real Term"]}}}
        descriptor = parse_mesh(payload, ["1"], "x")[0]
        assert descriptor["label"] == "Real Term"
