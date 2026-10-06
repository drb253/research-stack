"""PubMed XML parsing tests.

_parse_pubmed_xml was silently losing data on several common record shapes:
titles were cut off at the first nested markup tag, only the first section of a
structured abstract was returned, authors with a collective name or only initials
were dropped entirely, and dates that use MedlineDate rather than Year/Month came
back with no publication_date at all.
"""
import pytest

from ncbi_mcp_server.server import NCBIClient


@pytest.fixture
def client():
    """An NCBIClient without constructing its httpx client.

    _parse_pubmed_xml touches no instance state, so bypassing __init__ keeps the
    test free of an unclosed HTTP connection pool.
    """
    return NCBIClient.__new__(NCBIClient)


def wrap(article_xml: str) -> str:
    return (
        "<PubmedArticleSet><PubmedArticle><MedlineCitation>"
        f"{article_xml}"
        "</MedlineCitation></PubmedArticle></PubmedArticleSet>"
    )


def test_nested_markup_is_kept_in_title(client):
    xml = wrap(
        "<Article><ArticleTitle>Effect of <i>TP53</i> on "
        "<sup>5</sup>-FU</ArticleTitle></Article>"
    )
    article = client._parse_pubmed_xml(xml)["articles"][0]
    assert article["title"] == "Effect of TP53 on 5-FU"


def test_missing_title_falls_back_to_placeholder(client):
    article = client._parse_pubmed_xml(wrap("<Article></Article>"))["articles"][0]
    assert article["title"] == "No title available"


def test_all_structured_abstract_sections_are_joined(client):
    """Only the first AbstractText used to survive."""
    xml = wrap(
        "<Article><Abstract>"
        '<AbstractText Label="BACKGROUND">First.</AbstractText>'
        '<AbstractText Label="METHODS">Second.</AbstractText>'
        '<AbstractText Label="RESULTS">Third.</AbstractText>'
        "</Abstract></Article>"
    )
    article = client._parse_pubmed_xml(xml)["articles"][0]
    assert article["abstract"] == "BACKGROUND: First. METHODS: Second. RESULTS: Third."


def test_unlabelled_abstract_has_no_label_prefix(client):
    xml = wrap("<Article><Abstract><AbstractText>Plain text.</AbstractText></Abstract></Article>")
    article = client._parse_pubmed_xml(xml)["articles"][0]
    assert article["abstract"] == "Plain text."


def test_other_abstract_is_not_mixed_in(client):
    """OtherAbstract holds a translated abstract and has no <Abstract> parent."""
    xml = wrap(
        "<Article><Abstract><AbstractText>English.</AbstractText></Abstract></Article>"
        "<OtherAbstract><AbstractText>Traduccion.</AbstractText></OtherAbstract>"
    )
    article = client._parse_pubmed_xml(xml)["articles"][0]
    assert article["abstract"] == "English."
    assert "Traduccion" not in article["abstract"]


def test_collective_author_is_kept(client):
    xml = wrap(
        "<Article><AuthorList>"
        "<Author><CollectiveName>The CONSORT Group</CollectiveName></Author>"
        "</AuthorList></Article>"
    )
    article = client._parse_pubmed_xml(xml)["articles"][0]
    assert article["authors"] == ["The CONSORT Group"]


def test_author_with_only_initials_is_kept(client):
    xml = wrap(
        "<Article><AuthorList>"
        "<Author><LastName>Smith</LastName><Initials>JA</Initials></Author>"
        "</AuthorList></Article>"
    )
    article = client._parse_pubmed_xml(xml)["articles"][0]
    assert article["authors"] == ["JA Smith"]


def test_author_with_only_last_name_is_kept(client):
    xml = wrap(
        "<Article><AuthorList><Author><LastName>Anon</LastName></Author></AuthorList></Article>"
    )
    article = client._parse_pubmed_xml(xml)["articles"][0]
    assert article["authors"] == ["Anon"]


def test_full_author_name_uses_forename(client):
    xml = wrap(
        "<Article><AuthorList>"
        "<Author><ForeName>Ann</ForeName><LastName>Jones</LastName></Author>"
        "</AuthorList></Article>"
    )
    article = client._parse_pubmed_xml(xml)["articles"][0]
    assert article["authors"] == ["Ann Jones"]


def test_medline_date_is_used_when_present(client):
    xml = wrap(
        "<Article><Journal><JournalIssue><PubDate>"
        "<MedlineDate>2024 Jan-Feb</MedlineDate>"
        "</PubDate></JournalIssue></Journal></Article>"
    )
    article = client._parse_pubmed_xml(xml)["articles"][0]
    assert article["publication_date"] == "2024 Jan-Feb"


def test_year_month_day_is_assembled(client):
    xml = wrap(
        "<Article><Journal><JournalIssue><PubDate>"
        "<Year>2024</Year><Month>Jun</Month><Day>15</Day>"
        "</PubDate></JournalIssue></Journal></Article>"
    )
    article = client._parse_pubmed_xml(xml)["articles"][0]
    assert article["publication_date"] == "2024-Jun-15"


def test_year_only_is_kept(client):
    xml = wrap(
        "<Article><Journal><JournalIssue><PubDate><Year>2019</Year>"
        "</PubDate></JournalIssue></Journal></Article>"
    )
    article = client._parse_pubmed_xml(xml)["articles"][0]
    assert article["publication_date"] == "2019"


def test_doi_and_mesh_terms_are_parsed(client):
    xml = wrap(
        "<Article><ELocationID EIdType='doi'>10.1038/abc</ELocationID></Article>"
        "<MeshHeadingList><MeshHeading><DescriptorName>Humans</DescriptorName></MeshHeading>"
        "<MeshHeading><DescriptorName>Gene Editing</DescriptorName></MeshHeading></MeshHeadingList>"
    )
    article = client._parse_pubmed_xml(xml)["articles"][0]
    assert article["doi"] == "10.1038/abc"
    assert article["mesh_terms"] == ["Humans", "Gene Editing"]


def test_citation_pmid_wins_over_reference_list_pmid(client):
    """MedlineCitation/PMID precedes any reference-list PMID in document order."""
    xml = wrap(
        "<PMID>111</PMID><Article></Article>"
        "<ReferenceList><Reference><Citation>ref</Citation></Reference></ReferenceList>"
    )
    article = client._parse_pubmed_xml(xml)["articles"][0]
    assert article["pmid"] == "111"


def test_multiple_articles_are_returned(client):
    xml = (
        "<PubmedArticleSet>"
        "<PubmedArticle><MedlineCitation><PMID>1</PMID><Article>"
        "<ArticleTitle>A</ArticleTitle></Article></MedlineCitation></PubmedArticle>"
        "<PubmedArticle><MedlineCitation><PMID>2</PMID><Article>"
        "<ArticleTitle>B</ArticleTitle></Article></MedlineCitation></PubmedArticle>"
        "</PubmedArticleSet>"
    )
    articles = client._parse_pubmed_xml(xml)["articles"]
    assert [a["pmid"] for a in articles] == ["1", "2"]


def test_malformed_xml_returns_error_not_exception(client):
    result = client._parse_pubmed_xml("<not-well-formed")
    assert result["articles"] == []
    assert "error" in result
