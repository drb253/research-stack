@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_ictrp(query: str, max_results: int = 10) -> List[Dict]:
    """Search the WHO ICTRP aggregator across ~20 trial registries (free).

    ICTRP is the WHO's international trial-registry platform and covers
    ClinicalTrials.gov, ISRCTN, ChiCTR, CTRI, JPRN, DRKS, ANZCTR and more behind
    one search -- the cross-registry sweep a systematic review needs.

    Args:
        query: Query; explicit operators work best (e.g. 'malaria AND treatment').
            A multi-term query is ANDed and progressively relaxed internally.
        max_results: Maximum trials to return (default: 10).
    Returns:
        Trial records in the shared paper schema; ``extra`` carries the trial_id,
        registry name, recruitment status and registration date.
    """
    papers = await async_search(ictrp_searcher, query, max_results)
    return papers if papers else []


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_ctis(
    query: str,
    max_results: int = 10,
    status: str = "",
    medical_condition: str = "",
    sponsor: str = "",
    product_name: str = "",
    trial_phase: str = "",
) -> List[Dict]:
    """Search EU CTIS, the mandatory EU/EEA trial registry since 2022 (free).

    Complements ClinicalTrials.gov and WHO ICTRP with EU-specific trials; the
    record carries the CT number, status, conditions and trial region.

    Args:
        query: Free text (title, product, condition or sponsor).
        max_results: Maximum trials to return (default: 10).
        status: Optional status filter, e.g. 'AUTHORISED', 'ONGOING'.
        medical_condition: Optional condition filter.
        sponsor: Optional sponsor filter.
        product_name: Optional investigational-product filter.
        trial_phase: Optional phase filter, e.g. 'PHASE3'.
    Returns:
        Trial records in the shared paper schema.
    """
    papers = await async_search(
        ctis_searcher, query, max_results,
        status=status, medical_condition=medical_condition, sponsor=sponsor,
        product_name=product_name, trial_phase=trial_phase,
    )
    return papers if papers else []


