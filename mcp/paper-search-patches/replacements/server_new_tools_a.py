@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_plos(query: str, max_results: int = 10) -> List[Dict]:
    """Search PLOS open-access journals (PLOS ONE, Biology, Genetics, Medicine...).

    Args:
        query: Search query string (e.g., 'CRISPR base editing').
        max_results: Maximum number of papers to return (default: 10).
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(plos_searcher, query, max_results)
    return papers if papers else []


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_jstage(query: str, max_results: int = 10) -> List[Dict]:
    """Search J-STAGE, the aggregator of Japanese academic journals.

    Args:
        query: Search query string (e.g., 'CRISPR base editing').
        max_results: Maximum number of papers to return (default: 10).
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(jstage_searcher, query, max_results)
    return papers if papers else []


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_figshare(query: str, max_results: int = 10) -> List[Dict]:
    """Search figshare research outputs (articles, figures, datasets, theses).

    Each hit is enriched from the article detail endpoint so authors and
    abstracts are populated (the search payload alone omits them).

    Args:
        query: Search query string (e.g., 'CRISPR base editing').
        max_results: Maximum number of items to return (default: 10).
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(figshare_searcher, query, max_results)
    return papers if papers else []


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_datacite(query: str, max_results: int = 10) -> List[Dict]:
    """Search DataCite DOIs for datasets, software, theses and other outputs.

    Args:
        query: Search query string (e.g., 'CRISPR dataset').
        max_results: Maximum number of records to return (default: 10).
    Returns:
        List of record metadata in dictionary format.
    """
    papers = await async_search(datacite_searcher, query, max_results)
    return papers if papers else []


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_whoris(query: str, max_results: int = 10) -> List[Dict]:
    """Search WHO IRIS, the World Health Organization institutional repository.

    Args:
        query: Search query string (e.g., 'malaria guidelines').
        max_results: Maximum number of records to return (default: 10).
    Returns:
        List of record metadata in dictionary format.
    """
    papers = await async_search(whoris_searcher, query, max_results)
    return papers if papers else []


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def convert_paper_ids(ids: str, email: str = "") -> Dict:
    """Convert between PMID, PMCID, DOI and MID via the NCBI PMC ID Converter.

    Args:
        ids: One or more comma-separated identifiers (e.g., '38909984,PMC10909955').
        email: Optional contact email (NCBI asks for it; tool name is sent always).
    Returns:
        Dictionary with a 'records' list containing the resolved identifier sets.
    """

    def _run() -> Dict:
        params = {"ids": ids, "format": "json", "tool": "paper-search-mcp"}
        if email:
            params["email"] = email
        response = httpx.get(
            "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/",
            params=params, timeout=30,
        )
        response.raise_for_status()
        return response.json()

    return await asyncio.to_thread(_run)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_citation_metrics(pmids: str) -> Dict:
    """Get citation metrics (counts, RCR) for PMIDs via NIH iCite.

    Args:
        pmids: One or more comma-separated PubMed IDs (e.g., '38909984,38308006').
    Returns:
        Dictionary with a 'data' list of per-PMID citation metrics.
    """

    def _run() -> Dict:
        response = httpx.get(
            "https://icite.od.nih.gov/api/pubs", params={"pmids": pmids}, timeout=30
        )
        response.raise_for_status()
        return response.json()

    return await asyncio.to_thread(_run)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_citing_articles(doi: str, limit: int = 50) -> List[Dict]:
    """List papers that cite a DOI, using the OpenCitations Index (citation graph).

    Args:
        doi: The cited DOI (e.g., '10.1038/s41586-021-03534-y').
        limit: Maximum number of citing records to return (default: 50).
    Returns:
        List of citation records, each with 'citing' and 'cited' identifiers.
    """

    def _run() -> List[Dict]:
        response = httpx.get(
            f"https://api.opencitations.net/index/v2/citations/doi:{doi}",
            timeout=45, follow_redirects=True,
        )
        response.raise_for_status()
        data = response.json() or []
        return data[: max(limit, 1)]

    return await asyncio.to_thread(_run)


