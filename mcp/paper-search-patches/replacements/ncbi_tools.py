@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_related_articles(pmid: str, max_results: int = 10) -> Dict[str, Any]:
    """Find PubMed articles related to a PMID (NCBI elink, free).

    Combines PubMed's "similar articles" and citation relationships -- the fastest
    way to expand from one known paper to its whole neighbourhood. Uses your NCBI
    API key (10 req/s instead of 3).

    Args:
        pmid: PubMed ID, e.g. '38909984'.
        max_results: Maximum related PMIDs to return (default: 10).
    Returns:
        Dictionary with 'related_pmids', 'total_related' and the 'link_sets' that
        produced them.
    """

    def _run() -> Dict[str, Any]:
        params = {
            "dbfrom": "pubmed",
            "db": "pubmed",
            "id": str(pmid).strip(),
            "retmode": "json",
            "cmd": "neighbor_score",
            **ncbi_eutils_params(),
        }
        response = httpx.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi",
            params=params, timeout=30, follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()

        related: List[str] = []
        link_sets: List[str] = []
        for linkset in payload.get("linksets") or []:
            for linksetdb in (linkset or {}).get("linksetdbs") or []:
                raw_links = (linksetdb or {}).get("links") or []
                # elink returns [{"id": "38909984", "score": 123}] per link set.
                ids = [
                    str(link.get("id") if isinstance(link, dict) else link)
                    for link in raw_links
                    if (link.get("id") if isinstance(link, dict) else link)
                ]
                if ids:
                    link_sets.append(
                        f"{(linksetdb or {}).get('linkname', '?')} ({len(ids)})"
                    )
                    related.extend(ids)
        deduped = list(dict.fromkeys(related))
        return {
            "pmid": str(pmid).strip(),
            "related_pmids": deduped[:max_results],
            "total_related": len(deduped),
            "link_sets": link_sets,
        }

    return await asyncio.to_thread(_run)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def get_mesh_details(term: str) -> Dict[str, Any]:
    """Resolve a term to MeSH descriptors and synonyms (free, NCBI key aware).

    Entry-term aware, so lay phrasing resolves correctly
    (e.g. 'heart attack' -> Myocardial Infarction).

    Args:
        term: Term to resolve, e.g. 'heart attack', 'gene therapy'.
    Returns:
        Dictionary with 'descriptors', each carrying label, mesh_ui, synonyms and
        scope note.
    """

    def _run() -> Dict[str, Any]:
        search = httpx.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={"db": "mesh", "term": term, "retmax": 5, "retmode": "json",
                    **ncbi_eutils_params()},
            timeout=30, follow_redirects=True,
        )
        search.raise_for_status()
        ids = ((search.json().get("esearchresult") or {}).get("idlist")) or []
        if not ids:
            return {"query": term, "descriptors": []}

        summary = httpx.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
            params={"db": "mesh", "id": ",".join(ids), "retmode": "json",
                    **ncbi_eutils_params()},
            timeout=30, follow_redirects=True,
        )
        summary.raise_for_status()
        result = summary.json().get("result") or {}

        descriptors: List[Dict[str, Any]] = []
        for uid in ids:
            record = result.get(str(uid)) or {}
            if not isinstance(record, dict):
                continue
            # Skip qualifiers/subheadings (recordtype "qualifier" / MeSH UI "Q..."):
            # their ds_meshterms are entry terms of a subheading, not descriptors.
            # Measured, "screening" otherwise returned the subheading "diagnosis"
            # (Q000175) presented as a descriptor -- copying it into a search
            # strategy is wrong, because a subheading is not a MeSH descriptor.
            if str(record.get("ds_recordtype", "")).lower() == "qualifier":
                continue
            if str(record.get("ds_meshui", "")).upper().startswith("Q"):
                continue
            mesh_terms = record.get("ds_meshterms") or []
            if not mesh_terms:
                continue
            descriptors.append({
                "label": mesh_terms[0],
                "synonyms": mesh_terms[1:],
                "mesh_ui": record.get("ds_meshui", ""),
                "scope_note": record.get("ds_scopenote", ""),
                "year_introduced": record.get("ds_yearintroduced", ""),
            })
        return {"query": term, "descriptors": descriptors}

    return await asyncio.to_thread(_run)


