from typing import List
import difflib
import html
import os
import re
import sys
import requests
from urllib.parse import quote
from datetime import datetime, timedelta
from ..paper import Paper
from .base import PaperSource
from ..source_status import (  # paper-search-mcp-patches: Tier 1/7
    SourceUnavailable,
    assert_not_botwall,
    assert_usable_bytes,
    request_json,
)
from pypdf import PdfReader

# PATCHED-BY-paper-search-mcp-patches: Europe PMC keyword search. v4
# bioRxiv's own API is date-interval only (it cannot answer a keyword query),
# so keyword search is served by Europe PMC, which indexes the full bioRxiv
# archive as preprints (SRC:PPR) with relevance ranking.
EUROPE_PMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
DETAILS_API = "https://api.biorxiv.org/details"
PUBS_API = "https://api.biorxiv.org/pubs"
_TAG_RE = re.compile(r"<[^>]+>")

#: bioRxiv subject categories (snapshot 2026-09-29).
#:
#: The listing API accepts these case-insensitively and treats '_' or '-' as a
#: space, but it SILENTLY IGNORES anything it does not recognise and answers with
#: unfiltered records.  This list therefore exists for discoverability and
#: "did you mean" hints; the real guard is _assert_category_applied(), which
#: checks the response and so cannot go stale.
BIORXIV_CATEGORIES = (
    "Animal Behavior and Cognition", "Biochemistry", "Bioengineering",
    "Bioinformatics", "Biophysics", "Cancer Biology", "Cell Biology",
    "Developmental Biology", "Ecology", "Evolutionary Biology", "Genetics",
    "Genomics", "Immunology", "Microbiology", "Molecular Biology",
    "Neuroscience", "Paleontology", "Pathology",
    "Pharmacology and Toxicology", "Physiology", "Plant Biology",
    "Scientific Communication and Education", "Synthetic Biology",
    "Systems Biology", "Zoology",
)


def _norm_category(value) -> str:
    """Normalise a category for comparison ('cancer-biology' == 'Cancer Biology')."""
    return " ".join(
        str(value or "").replace("_", " ").replace("-", " ").lower().split()
    )


def _jats_body(xml: str) -> str:
    """The article body from JATS XML, without front/back matter.

    Raw JATS opens with journal metadata (titles, ISSN, publisher, keywords),
    which is noise when the text is quoted or summarised, so prefer <body> and
    drop the reference list in <back>.
    """
    text = xml or ""
    match = re.search(r"<body[^>]*>(.*?)</body>", text, re.S | re.I)
    if match:
        text = match.group(1)
    text = re.sub(r"<back[^>]*>.*?</back>", " ", text, flags=re.S | re.I)
    return " ".join(_clean_text(text).split())


def _clean_text(value) -> str:
    """Strip markup/entities that Europe PMC sometimes leaves in fields."""
    if not value:
        return ""
    return html.unescape(_TAG_RE.sub("", str(value))).strip()


def _matches_terms(item: dict, terms) -> bool:
    """True when every query term appears in the record's title/abstract/authors.

    Europe PMC searches full text, so without this a multi-word query can return
    papers that never mention the topic in their title or abstract.
    """
    haystack = " ".join([
        str(item.get("title") or ""),
        str(item.get("abstractText") or ""),
        str(item.get("authorString") or ""),
    ]).lower().replace("-", " ")
    return all(term in haystack for term in terms)


class BioRxivSearcher(PaperSource):
    """Searcher for bioRxiv preprints (keyword search, full archive)."""

    BASE_URL = "https://api.biorxiv.org/details/biorxiv"
    SERVER = "bioRxiv"
    SITE = "https://www.biorxiv.org"
    SOURCE = "biorxiv"
    DEFAULT_DAYS = 30

    def __init__(self):
        self.session = requests.Session()
        self.session.proxies = {'http': None, 'https': None}
        self.timeout = 30
        self.max_retries = 3

    def search(self, query: str, max_results: int = 10, days: int = 30,
               category: str = "") -> List[Paper]:
        """
        Search bioRxiv preprints by keyword and/or subject category.

        Args:
            query: Keyword query (e.g., "CRISPR base editing").
            max_results: Maximum number of papers to return.
            days: Window used by the listing (date) API.
            category: Optional subject category (e.g. "Cancer Biology").

        Returns:
            List of Paper objects ranked by relevance.

        A category filter is served by the listing API, the only interface that
        carries the category field and filters it server-side.  Europe PMC ranks
        by relevance but does not expose bioRxiv's category, so the two are not
        mixed: a category request goes straight to the listing API, where the
        filter is verified rather than assumed.
        """
        if category:
            return self._search_recent_window(
                query, max_results, days, category=category
            )

        # Tier 1: only claim unavailability when both paths fail; otherwise the
        # date-window fallback still returns (less precise) results.
        try:
            papers = self._search_europe_pmc(query, max_results, require_terms=True)
        except SourceUnavailable as exc:
            print(f"{self.SERVER} Europe PMC search unavailable ({exc}); falling back to the date API", file=sys.stderr)
            papers = []
        if papers:
            return papers
        return self._search_recent_window(query, max_results, days)

    def _search_europe_pmc(self, query: str, max_results: int, require_terms: bool = True) -> List[Paper]:
        terms = [term for term in re.split(r'\s+', (query or "").strip().lower().replace("-", " ")) if term]
        params = {
            "query": f'({query}) AND SRC:PPR AND PUBLISHER:"{self.SERVER}"',
            "format": "json",
            # Over-fetch so filtering cannot starve the result count.
            "pageSize": min(max(max_results * 3, 25), 100),
            "resultType": "core",
        }
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(EUROPE_PMC_SEARCH, params=params, timeout=self.timeout)
                response.raise_for_status()
                results = response.json().get("resultList", {}).get("result", []) or []
            except (requests.exceptions.RequestException, ValueError) as exc:
                if attempt == self.max_retries - 1:
                    print(f"{self.SERVER} keyword search failed, falling back to date API: {exc}", file=sys.stderr)
                continue

            papers = []
            for item in results:
                if require_terms and terms and not _matches_terms(item, terms):
                    continue
                paper = self._map_epmc_item(item)
                if paper is not None:
                    papers.append(paper)
                if len(papers) >= max_results:
                    break
            return papers

        raise SourceUnavailable(
            f"{self.SERVER.lower()}",
            "keyword search failed after retries",
        )

    def _map_epmc_item(self, item: dict):
        try:
            doi = (item.get("doi") or "").strip()
            if not doi:
                return None

            published = None
            raw_date = item.get("firstPublicationDate") or item.get("dateOfCreation")
            if raw_date:
                try:
                    published = datetime.strptime(raw_date, "%Y-%m-%d")
                except ValueError:
                    published = None

            authors = [
                name.strip()
                for name in (item.get("authorString") or "").rstrip(".").split(",")
                if name.strip()
            ]

            keywords = []
            keyword_list = (item.get("keywordList") or {}).get("keyword") or []
            if isinstance(keyword_list, list):
                keywords = [str(k).strip() for k in keyword_list if str(k).strip()]

            return Paper(
                paper_id=doi,
                title=_clean_text(item.get("title")),
                authors=authors,
                abstract=_clean_text(item.get("abstractText")),
                url=f"{self.SITE}/content/{doi}v1",
                pdf_url=f"{self.SITE}/content/{doi}v1.full.pdf",
                published_date=published,
                updated_date=published,
                source=self.SOURCE,
                categories=[],
                keywords=keywords,
                doi=doi,
                citations=0,
                extra={
                    "server": self.SERVER,
                    "epmc_id": item.get("id", ""),
                    "pub_type": item.get("pubType", ""),
                },
            )
        except Exception as exc:
            print(f"Error parsing {self.SERVER} entry: {exc}", file=sys.stderr)
            return None

    def _search_recent_window(self, query: str, max_results: int, days: int,
                              category: str = "") -> List[Paper]:
        """Listing-API window: fetch records and keep keyword matches only.

        Unlike the upstream behaviour this never returns unrelated papers: when a
        keyword query is present, a record must contain every query term in its
        title or abstract.  This is also the only path that can filter by subject
        category, which the API applies server-side.
        """
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=max(days, 1))).strftime('%Y-%m-%d')

        terms = [term for term in re.split(r'\s+', (query or "").strip().lower()) if term]
        if not terms and not category:
            return []

        seen_categories = set()

        matches: List[Paper] = []
        cursor = 0
        pages = 0
        last_error = None
        while len(matches) < max_results and pages < 5:
            pages += 1
            url = f"{self.BASE_URL}/{start_date}/{end_date}/{cursor}"
            if category:
                # Filtered server-side.  An unrecognised value is silently
                # ignored by the API, so the response is verified afterwards.
                url = f"{url}?category={quote(category)}"
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                collection = response.json().get('collection', []) or []
            except (requests.exceptions.RequestException, ValueError) as exc:
                print(f"{self.SERVER} date-API fallback failed: {exc}", file=sys.stderr)
                last_error = exc
                break

            if not collection:
                break

            for item in collection:
                seen_categories.add(item.get('category', ''))
                haystack = f"{item.get('title', '')} {item.get('abstract', '')}".lower()
                if terms and not all(term in haystack for term in terms):
                    continue
                try:
                    date = datetime.strptime(item['date'], '%Y-%m-%d')
                    version = item.get('version', '1')
                    matches.append(Paper(
                        paper_id=item['doi'],
                        title=item['title'],
                        authors=item['authors'].split('; '),
                        abstract=item['abstract'],
                        url=f"{self.SITE}/content/{item['doi']}v{version}",
                        pdf_url=f"{self.SITE}/content/{item['doi']}v{version}.full.pdf",
                        published_date=date,
                        updated_date=date,
                        source=self.SOURCE,
                        categories=[item.get('category', '')],
                        keywords=[],
                        doi=item['doi'],
                    ))
                except Exception as exc:
                    print(f"Error parsing {self.SERVER} entry: {exc}", file=sys.stderr)
                if len(matches) >= max_results:
                    break

            if len(collection) < 100:
                break
            cursor += 100

        if category:
            # A category filter is verified, never assumed: the API answers an
            # unrecognised category with UNFILTERED records.
            self._assert_category_applied(category, seen_categories)

        # Tier 1: an empty result is only trustworthy when no request failed.
        if not matches and last_error is not None:
            raise SourceUnavailable(
                f"{self.SERVER.lower()}",
                f"keyword search and date-API fallback both failed: "
                f"{last_error}"[:200],
            )
        return matches

    #: Subject categories the listing API filters on.
    CATEGORIES = BIORXIV_CATEGORIES

    def _assert_category_applied(self, requested: str, seen_categories) -> None:
        """Raise when the listing API did not actually apply the category.

        Measured 2026-09-29: ``?category=NOT_A_CATEGORY`` is silently ignored and
        the API answers with *unfiltered* records, whereas
        ``?category=cancer_biology`` returns 30/30 'cancer biology'.  Presenting
        unfiltered records as category-filtered would be worse than returning
        nothing, so every category call is checked against the response.
        """
        wanted = _norm_category(requested)
        seen = {_norm_category(value) for value in seen_categories if value}
        if not seen or wanted in seen:
            return

        known = [_norm_category(value) for value in self.CATEGORIES]
        suggestions = difflib.get_close_matches(wanted, known, n=3, cutoff=0.4)
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        raise SourceUnavailable(
            f"{self.SERVER.lower()}",
            f"category {requested!r} was not applied by the listing API -- it "
            f"returned unfiltered results ({', '.join(sorted(seen)[:4])})."
            f"{hint}",
        )

    def list_categories(self) -> List[str]:
        """The subject categories the listing API filters on."""
        return list(self.CATEGORIES)

    def get_preprint_record(self, doi: str) -> dict:
        """The listing API's record for one DOI (includes the ``jatsxml`` URL)."""
        if not doi:
            raise ValueError("Invalid doi: doi is empty")

        payload = request_json(
            self.session,
            f"{DETAILS_API}/{self.SERVER.lower()}/{doi}",
            f"{self.SERVER.lower()}",
            timeout=self.timeout,
        )
        collection = (payload or {}).get("collection") or []
        return collection[0] if collection else {}

    def get_published_version(self, doi: str) -> dict:
        """Resolve a preprint DOI to its journal version, when one exists.

        Verified 2026-09-29: 10.1101/2025.09.29.679222 ->
        published_doi 10.1162/IMAG.a.1376, journal "Imaging Neuroscience".  This
        lets a write-up cite the journal version instead of the preprint.
        """
        if not doi:
            raise ValueError("Invalid doi: doi is empty")

        payload = request_json(
            self.session,
            f"{PUBS_API}/{self.SERVER.lower()}/{doi}",
            f"{self.SERVER.lower()}",
            timeout=self.timeout,
        )
        collection = (payload or {}).get("collection") or []
        if not collection:
            return {}

        record = collection[0]
        return {
            "preprint_doi": record.get("preprint_doi", doi),
            "published_doi": record.get("published_doi", ""),
            "published_journal": record.get("published_journal", ""),
            "preprint_title": record.get("preprint_title", ""),
        }

    def get_fulltext(self, doi: str) -> str:
        """The preprint body as text, taken from the JATS XML the API links.

        Measured 2026-09-29: the rendered article page answers HTTP 403 to
        non-browser clients and the PDF is bot-walled, but the record's
        ``jatsxml`` URL returns HTTP 200 with the complete JATS article
        (~85 KB), so no browser and no PDF extraction are needed.
        """
        record = self.get_preprint_record(doi)
        jats_url = (record or {}).get("jatsxml") or ""
        if not jats_url:
            raise SourceUnavailable(
                f"{self.SERVER.lower()}",
                f"listing API exposed no jatsxml URL for {doi}",
            )

        response = self.session.get(jats_url, timeout=self.timeout)
        assert_not_botwall(
            f"{self.SERVER.lower()}", response.text, response.status_code
        )
        if response.status_code != 200:
            raise SourceUnavailable(
                f"{self.SERVER.lower()}",
                f"JATS XML unavailable (HTTP {response.status_code})",
                http_status=response.status_code,
            )
        assert_usable_bytes(
            f"{self.SERVER.lower()}", response.content, 2000, label="JATS XML"
        )
        # JATS markup stripped to the article body: no front/back matter noise.
        return _jats_body(response.text)

    def download_pdf(self, paper_id: str, save_path: str) -> str:
        """
        Download a PDF for a given paper ID.

        Args:
            paper_id: The DOI of the paper.
            save_path: Directory to save the PDF.

        Returns:
            Path to the downloaded PDF file.
        """
        if not paper_id:
            raise ValueError("Invalid paper_id: paper_id is empty")

        pdf_url = f"{self.SITE}/content/{paper_id}v1.full.pdf"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
        }
        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(pdf_url, timeout=self.timeout, headers=headers)
                response.raise_for_status()
                os.makedirs(save_path, exist_ok=True)
                output_file = f"{save_path}/{paper_id.replace('/', '_')}.pdf"
                with open(output_file, 'wb') as f:
                    f.write(response.content)
                return output_file
            except requests.exceptions.RequestException as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    print(f"Attempt {attempt + 1} failed, retrying...", file=sys.stderr)

        raise Exception(f"Failed to download PDF after {self.max_retries} attempts: {last_error}")

    def read_paper(self, paper_id: str, save_path: str = "./downloads") -> str:
        """Return the preprint body as text.

        Prefers the JATS XML -- no bot wall and no PDF parsing -- and falls back
        to the PDF only when the API exposes no JATS URL.
        """
        try:
            text = self.get_fulltext(paper_id)
            if text:
                return text
        except (SourceUnavailable, ValueError) as exc:
            print(f"{self.SERVER} JATS full text unavailable ({exc}); trying the PDF", file=sys.stderr)

        pdf_path = f"{save_path}/{paper_id.replace('/', '_')}.pdf"
        if not os.path.exists(pdf_path):
            pdf_path = self.download_pdf(paper_id, save_path)

        try:
            reader = PdfReader(pdf_path)
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
            return text.strip()
        except Exception as exc:
            print(f"Error reading PDF for paper {paper_id}: {exc}", file=sys.stderr)
            return ""
