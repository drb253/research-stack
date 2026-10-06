@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_bookshelf(query: str, max_results: int = 10) -> List[Dict]:
    """Search NCBI Bookshelf: books, reports, guidelines and textbook chapters.

    Bookshelf carries full-text reference literature that no journal index holds
    (GeneReviews, StatPearls, NCI PDQ summaries, WHO/NCBI reports, methods
    monographs). Uses your NCBI API key. In-book tables/figures are filtered out.

    Args:
        query: Free-text query; PubMed-style field tags work, e.g.
            'base editing[Title]'.
        max_results: Maximum documents to return (default: 10).
    Returns:
        Documents in the shared paper schema; ``extra`` carries record_type,
        book_title, publisher and the Bookshelf accessions.
    """
    papers = await async_search(bookshelf_searcher, query, max_results)
    return papers if papers else []


