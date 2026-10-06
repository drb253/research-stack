# paper_search_mcp/sources/arxiv.py
# PATCHED-BY-paper-search-mcp-patches: curl-backed HTTP transport. retries=4. stderr-diagnostics
import shutil
import subprocess
import sys
from typing import List
from datetime import datetime
import feedparser
import time
from ..paper import Paper
from ..utils import extract_doi
from .base import PaperSource
from ..source_status import (  # paper-search-mcp-patches: Tier 1/2 helpers
    SourceUnavailable,
    search_terms,
)
from pypdf import PdfReader
import os

# arXiv's bot mitigation answers Python TLS stacks (requests=always, httpx=often)
# with HTTP 406 while the system curl succeeds consistently for the same URL.
CURL = shutil.which("curl") or "/usr/bin/curl"


class _CurlResponse:
    """Minimal requests-like response shim for the curl transport."""

    def __init__(self, content: bytes, status_code: int):
        self.content = content
        self.status_code = status_code


def _curl_request(url: str, params: dict = None) -> _CurlResponse:
    """Fetch a URL with the system curl and return a response shim."""
    cmd = [CURL, "-sS", "-L", "--max-time", "30", "-w", "\n%{http_code}"]
    if params:
        cmd.append("-G")
        for key, value in params.items():
            cmd += ["--data-urlencode", f"{key}={value}"]
    cmd.append(url)

    try:
        proc = subprocess.run(cmd, capture_output=True, check=False)
    except OSError:
        return _CurlResponse(b"", 0)

    body, _, status_text = proc.stdout.rpartition(b"\n")
    try:
        status = int(status_text.strip())
    except ValueError:
        status = 0
    return _CurlResponse(body, status)


class ArxivSearcher(PaperSource):
    """Searcher for arXiv papers"""
    BASE_URL = "https://export.arxiv.org/api/query"

    def __init__(self):
        # No persistent client: TLS fingerprinting is what arXiv objects to.
        pass

    def search(self, query: str, max_results: int = 10, sort_by: str = 'relevance', sort_order: str = 'descending') -> List[Paper]:
        # Tier 2: 'all:<query>' ranks loosely (a garbage query still returned 5
        # papers), while 'ti:a AND ti:b' gave an on-target top-2 and 0 for
        # garbage. Try the title-scoped form first, then fall back to all:.
        terms = search_terms(query)
        candidates: list = []
        if len(terms) >= 2:
            candidates.append(" AND ".join(f"ti:{term}" for term in terms))
        candidates.append(f"all:{query}")

        feed = None
        papers = []
        last_status = None
        for candidate in candidates:
            params = {
                'search_query': candidate,
                'max_results': max_results,
                'sortBy': sort_by,
                'sortOrder': sort_order,
            }
            response = None
            for attempt in range(4):
                response = _curl_request(self.BASE_URL, params)
                if response.status_code == 200:
                    break
                if response.status_code in (406, 429, 500, 502, 503, 504):
                    time.sleep((attempt + 1) * 1.5)
                    continue
                break

            if response is None:
                raise SourceUnavailable(
                    "arxiv", "no response from the arXiv API"
                )
            if response.status_code != 200:
                last_status = response.status_code
                continue

            feed = feedparser.parse(response.content)
            if feed.entries:
                break

        if feed is None:
            raise SourceUnavailable(
                "arxiv",
                f"search failed with status {last_status}",
                last_status,
            )
        for entry in feed.entries:
            try:
                authors = [author.name for author in entry.authors]
                published = datetime.strptime(entry.published, '%Y-%m-%dT%H:%M:%SZ')
                updated = datetime.strptime(entry.updated, '%Y-%m-%dT%H:%M:%SZ')
                pdf_url = next((link.href for link in entry.links if link.type == 'application/pdf'), '')

                # Try to extract DOI from entry.doi or links or summary
                doi = entry.get('doi', '') or extract_doi(entry.summary) or extract_doi(entry.id)
                for link in entry.links:
                    if link.get('title') == 'doi':
                        doi = doi or extract_doi(link.href)

                papers.append(Paper(
                    paper_id=entry.id.split('/')[-1],
                    title=entry.title,
                    authors=authors,
                    abstract=entry.summary,
                    url=entry.id,
                    pdf_url=pdf_url,
                    published_date=published,
                    updated_date=updated,
                    source='arxiv',
                    categories=[tag.term for tag in entry.tags],
                    keywords=[],
                    doi=doi
                ))
            except Exception as e:
                print(f"Error parsing arXiv entry: {e}", file=sys.stderr)

        # Tier 2 precision: the all: rung matches loosely (measured: a garbage
        # query still returned 3 papers), so keep only entries containing every
        # query term in the title or abstract.
        terms_lower = [t.lower() for t in search_terms(query)]
        if len(terms_lower) >= 2:
            papers = [
                paper for paper in papers
                if all(
                    term in f"{paper.title or ''} {paper.abstract or ''}".lower()
                    for term in terms_lower
                )
            ]
        return papers

    def download_pdf(self, paper_id: str, save_path: str) -> str:
        pdf_url = f"https://arxiv.org/pdf/{paper_id}.pdf"
        os.makedirs(save_path, exist_ok=True)
        output_file = f"{save_path}/{paper_id}.pdf"
        subprocess.run(
            [CURL, "-sS", "-L", "--max-time", "120", "-o", output_file, pdf_url],
            check=False,
        )
        return output_file

    def read_paper(self, paper_id: str, save_path: str = "./downloads") -> str:
        """Read a paper and convert it to text format.

        Args:
            paper_id: arXiv paper ID
            save_path: Directory where the PDF is/will be saved

        Returns:
            str: The extracted text content of the paper
        """
        # First ensure we have the PDF
        pdf_path = f"{save_path}/{paper_id}.pdf"
        if not os.path.exists(pdf_path):
            pdf_path = self.download_pdf(paper_id, save_path)

        # Read the PDF
        try:
            reader = PdfReader(pdf_path)
            text = ""

            # Extract text from each page
            for page in reader.pages:
                text += page.extract_text() + "\n"

            return text.strip()
        except Exception as e:
            print(f"Error reading PDF for paper {paper_id}: {e}", file=sys.stderr)
            return ""


if __name__ == "__main__":
    # 测试 ArxivSearcher 的功能
    searcher = ArxivSearcher()

    # 测试搜索功能
    print("Testing search functionality...")
    query = "machine learning"
    max_results = 5
    try:
        papers = searcher.search(query, max_results=max_results)
        print(f"Found {len(papers)} papers for query '{query}':")
        for i, paper in enumerate(papers, 1):
            print(f"{i}. {paper.title} (ID: {paper.paper_id})")
    except Exception as e:
        print(f"Error during search: {e}")

    # 测试 PDF 下载功能
    if papers:
        print("\nTesting PDF download functionality...")
        paper_id = papers[0].paper_id
        save_path = "./downloads"  # 确保此目录存在
        try:
            os.makedirs(save_path, exist_ok=True)
            pdf_path = searcher.download_pdf(paper_id, save_path)
            print(f"PDF downloaded successfully: {pdf_path}")
        except Exception as e:
            print(f"Error during PDF download: {e}")

    # 测试论文阅读功能
    if papers:
        print("\nTesting paper reading functionality...")
        paper_id = papers[0].paper_id
        try:
            text_content = searcher.read_paper(paper_id)
            print(f"\nFirst 500 characters of the paper content:")
            print(text_content[:500] + "...")
            print(f"\nTotal length of extracted text: {len(text_content)} characters")
        except Exception as e:
            print(f"Error during paper reading: {e}")
