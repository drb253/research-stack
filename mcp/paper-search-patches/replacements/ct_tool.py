@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_clinicaltrials(
    query: str,
    max_results: int = 10,
    status: str = "",
    study_type: str = "",
    phase: str = "",
) -> List[Dict]:
    """Search ClinicalTrials.gov registered studies (free, no API key).

    Trial registries are a required part of systematic-review searching (PRISMA),
    because registry records carry protocol detail, phase and status that journal
    indexes do not, and they surface studies whose results were never published.

    Args:
        query: Free-text query (intervention, condition, sponsor or NCT id).
        max_results: Maximum studies to return (default: 10).
        status: Optional overall status filter, e.g. 'RECRUITING', 'COMPLETED'.
        study_type: Optional 'INTERVENTIONAL' or 'OBSERVATIONAL'.
        phase: Optional phase filter, e.g. 'PHASE3'.
    Returns:
        Study records in the shared paper schema; ``extra`` carries the NCT id,
        status, phases, enrollment, conditions and whether results exist.
    """
    papers = await async_search(
        clinicaltrials_searcher, query, max_results,
        status=status, study_type=study_type, phase=phase,
    )
    return papers if papers else []


