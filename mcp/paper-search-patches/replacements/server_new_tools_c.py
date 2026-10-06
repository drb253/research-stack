@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_osf(query: str, max_results: int = 10) -> List[Dict]:
    """Search OSF Preprints (SocArXiv, PsyArXiv, EdArXiv, MetaArXiv...) via SHARE.

    Results are filtered so every query term appears in the title, abstract or
    tags, because SHARE ranks with OR semantics.

    Args:
        query: Search query string (e.g., 'CRISPR base editing').
        max_results: Maximum number of preprints to return (default: 10).
    Returns:
        List of paper metadata in dictionary format.
    """
    papers = await async_search(osf_searcher, query, max_results)
    return papers if papers else []


@mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": True})
async def download_osf(paper_id: str, save_path: str = "./downloads") -> str:
    """Download a preprint file from OSF (https://osf.io/<guid>/download).

    Args:
        paper_id: OSF guid, DOI (10.31219/osf.io/<guid>) or OSF URL.
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        Path to the downloaded PDF.
    """
    return await asyncio.to_thread(osf_searcher.download_pdf, paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def read_osf_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read and extract text from an OSF preprint PDF.

    Args:
        paper_id: OSF guid, DOI (10.31219/osf.io/<guid>) or OSF URL.
        save_path: Directory where the PDF is/will be saved.
    Returns:
        Extracted text content.
    """
    return await asyncio.to_thread(osf_searcher.read_paper, paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_annotations(article_ids: str, annotation_type: str = "") -> List[Dict]:
    """Fetch Europe PMC text-mined annotations for specific articles.

    Args:
        article_ids: Comma-separated NCBI-prefixed IDs, e.g. 'PMC:3890998,MED:38909984'.
            The 'PMC:'/'MED:' prefix is REQUIRED (a bare ID returns HTTP 400).
        annotation_type: Optional filter, e.g. 'Gene_Proteins', 'Diseases',
            'Chemicals', 'Organisms', 'Gene_Ontology'.
    Returns:
        List of annotation records returned by the Europe PMC annotations API.
    """

    def _run() -> List[Dict]:
        params = {"articleIds": article_ids, "format": "JSON"}
        if annotation_type:
            params["type"] = annotation_type
        response = httpx.get(
            "https://www.ebi.ac.uk/europepmc/annotations_api/annotationsByArticleIds",
            params=params, timeout=45, follow_redirects=True,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else [data]

    return await asyncio.to_thread(_run)


