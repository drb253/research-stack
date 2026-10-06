    def _search_graph_api(self, query: str, max_results: int, **kwargs) -> List[Paper]:
        """Search via the OpenAIRE Graph API v1.

        The legacy ``/search/researchProducts`` (v2 XML) endpoint hangs and had to
        be replaced; the Graph API answers the same query in ~1 second.
        """
        params = {
            'search': query,
            'pageSize': min(max(max_results, 1), 100),
            'type': 'publication',
        }
        response = self._get(self.GRAPH_URL, params=params)
        response.raise_for_status()
        results = response.json().get('results', []) or []

        papers: List[Paper] = []
        for item in results:
            paper = self._parse_graph_result(item)
            if paper and self._matches_filters(paper, kwargs):
                papers.append(paper)
            if len(papers) >= max_results:
                break
        return papers

    @staticmethod
    def _graph_description(item: Dict[str, Any]) -> str:
        """Return the first usable description (abstract), stripping markup."""
        descriptions = item.get('descriptions') or []
        if isinstance(descriptions, dict):
            descriptions = [descriptions]
        for entry in descriptions:
            text = entry.get('value') if isinstance(entry, dict) else entry
            if text and str(text).strip():
                return re.sub(r'<[^>]+>', ' ', str(text)).strip()
        return ""

    @staticmethod
    def _graph_urls(item: Dict[str, Any]) -> List[str]:
        """Collect every instance URL for a Graph API record."""
        urls: List[str] = []
        for instance in item.get('instances') or []:
            for url in (instance or {}).get('urls') or []:
                value = url.get('value') if isinstance(url, dict) else url
                if value and value not in urls:
                    urls.append(str(value))
        return urls

    def _parse_graph_result(self, item: Dict[str, Any]) -> Optional[Paper]:
        """Map an OpenAIRE Graph API record onto a Paper."""
        try:
            doi = ""
            for pid in item.get('pids') or []:
                if isinstance(pid, dict) and str(pid.get('scheme') or '').lower() == 'doi':
                    doi = str(pid.get('value') or '').strip()
                    break
            if not doi:
                for original_id in item.get('originalIds') or []:
                    found = extract_doi(str(original_id))
                    if found:
                        doi = found
                        break

            urls = self._graph_urls(item)
            landing = next((u for u in urls if 'doi.org' in u), urls[0] if urls else '')
            if not landing and doi:
                landing = f"https://doi.org/{doi}"
            pdf_url = next((u for u in urls if 'pdf' in u.lower()), '')

            authors: List[str] = []
            for author in item.get('authors') or []:
                if not isinstance(author, dict):
                    continue
                name = author.get('fullName')
                if not name:
                    name = ' '.join(
                        str(part) for part in (author.get('name'), author.get('surname')) if part
                    )
                if name and str(name).strip():
                    authors.append(str(name).strip())

            container = item.get('container') or {}
            categories: List[str] = []
            if isinstance(container, dict) and container.get('name'):
                categories.append(str(container['name']))
            if item.get('type'):
                categories.append(str(item['type']))

            impact = ((item.get('indicators') or {}).get('citationImpact') or {})
            try:
                citations = int(float(impact.get('citationCount') or 0))
            except (TypeError, ValueError):
                citations = 0

            published = self._parse_date(str(item.get('publicationDate') or ''))
            language = item.get('language') or {}

            return Paper(
                paper_id=doi or str(item.get('id') or ''),
                title=str(item.get('mainTitle') or '').strip(),
                authors=authors,
                abstract=self._graph_description(item),
                url=landing,
                pdf_url=pdf_url,
                published_date=published,
                updated_date=published,
                source='openaire',
                categories=categories,
                keywords=[],
                citations=citations,
                doi=doi,
                extra={
                    'publisher': item.get('publisher') or '',
                    'open_access': ((item.get('bestAccessRight') or {}).get('label') or ''),
                    'open_access_color': item.get('openAccessColor') or '',
                    'language': (language.get('code') if isinstance(language, dict) else '') or '',
                    'graph_id': item.get('id') or '',
                },
            )
        except Exception as exc:
            logger.warning("Failed to parse OpenAIRE Graph result: %s", exc)
            return None

