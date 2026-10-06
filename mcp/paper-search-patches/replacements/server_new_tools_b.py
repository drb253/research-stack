@mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": True})
async def download_plos(paper_id: str, save_path: str = "./downloads") -> str:
    """Download a PDF from PLOS.

    Args:
        paper_id: plos identifier as returned by search_plos.
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        Path to the downloaded PDF. Raises with an explicit reason when the
        record carries no PDF (figshare/DataCite/WHO IRIS are not PDF-only).
    """
    return await asyncio.to_thread(plos_searcher.download_pdf, paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def read_plos_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read and extract text from a PLOS PDF.

    Args:
        paper_id: plos identifier as returned by search_plos.
        save_path: Directory where the PDF is/will be saved.
    Returns:
        Extracted text content.
    """
    return await asyncio.to_thread(plos_searcher.read_paper, paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": True})
async def download_jstage(paper_id: str, save_path: str = "./downloads") -> str:
    """Download a PDF from J-STAGE.

    Args:
        paper_id: jstage identifier as returned by search_jstage.
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        Path to the downloaded PDF. Raises with an explicit reason when the
        record carries no PDF (figshare/DataCite/WHO IRIS are not PDF-only).
    """
    return await asyncio.to_thread(jstage_searcher.download_pdf, paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def read_jstage_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read and extract text from a J-STAGE PDF.

    Args:
        paper_id: jstage identifier as returned by search_jstage.
        save_path: Directory where the PDF is/will be saved.
    Returns:
        Extracted text content.
    """
    return await asyncio.to_thread(jstage_searcher.read_paper, paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": True})
async def download_figshare(paper_id: str, save_path: str = "./downloads") -> str:
    """Download a PDF from figshare.

    Args:
        paper_id: figshare identifier as returned by search_figshare.
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        Path to the downloaded PDF. Raises with an explicit reason when the
        record carries no PDF (figshare/DataCite/WHO IRIS are not PDF-only).
    """
    return await asyncio.to_thread(figshare_searcher.download_pdf, paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def read_figshare_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read and extract text from a figshare PDF.

    Args:
        paper_id: figshare identifier as returned by search_figshare.
        save_path: Directory where the PDF is/will be saved.
    Returns:
        Extracted text content.
    """
    return await asyncio.to_thread(figshare_searcher.read_paper, paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": True})
async def download_datacite(paper_id: str, save_path: str = "./downloads") -> str:
    """Download a PDF from DataCite.

    Args:
        paper_id: datacite identifier as returned by search_datacite.
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        Path to the downloaded PDF. Raises with an explicit reason when the
        record carries no PDF (figshare/DataCite/WHO IRIS are not PDF-only).
    """
    return await asyncio.to_thread(datacite_searcher.download_pdf, paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def read_datacite_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read and extract text from a DataCite PDF.

    Args:
        paper_id: datacite identifier as returned by search_datacite.
        save_path: Directory where the PDF is/will be saved.
    Returns:
        Extracted text content.
    """
    return await asyncio.to_thread(datacite_searcher.read_paper, paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": True})
async def download_whoris(paper_id: str, save_path: str = "./downloads") -> str:
    """Download a PDF from WHO IRIS.

    Args:
        paper_id: whoris identifier as returned by search_whoris.
        save_path: Directory to save the PDF (default: './downloads').
    Returns:
        Path to the downloaded PDF. Raises with an explicit reason when the
        record carries no PDF (figshare/DataCite/WHO IRIS are not PDF-only).
    """
    return await asyncio.to_thread(whoris_searcher.download_pdf, paper_id, save_path)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def read_whoris_paper(paper_id: str, save_path: str = "./downloads") -> str:
    """Read and extract text from a WHO IRIS PDF.

    Args:
        paper_id: whoris identifier as returned by search_whoris.
        save_path: Directory where the PDF is/will be saved.
    Returns:
        Extracted text content.
    """
    return await asyncio.to_thread(whoris_searcher.read_paper, paper_id, save_path)


