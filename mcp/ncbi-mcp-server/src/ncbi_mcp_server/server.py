#!/usr/bin/env python3
"""
NCBI Literature Search MCP Server
A Model Context Protocol server for searching NCBI databases (PubMed, PMC, etc.)
Designed for researchers in evolutionary biology, computational biology, and all life sciences.
"""

import asyncio
import json
import logging
import os
import urllib.parse
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

import httpx
from mcp.server.fastmcp import FastMCP

# Import our modules
from .analytics import AnalyticsManager, set_analytics_manager, track_usage

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ncbi-mcp-server")

class NCBIClient:
    """Client for interacting with NCBI E-utilities API"""
    
    BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    
    def __init__(self, email: Optional[str] = None, api_key: Optional[str] = None):
        self.email = email
        self.api_key = api_key
        
        # Enhanced HTTP client with connection pooling
        limits = httpx.Limits(
            max_keepalive_connections=20,
            max_connections=100,
            keepalive_expiry=30.0
        )
        
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, read=60.0),
            limits=limits,
            follow_redirects=True
        )
        
        # Rate limiting
        self.last_request_time = 0
        self.min_interval = 0.1 if api_key else 0.34  # 10/sec with key, 3/sec without
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()
    
    async def _rate_limit(self):
        """Implement rate limiting"""
        import time
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.min_interval:
            await asyncio.sleep(self.min_interval - time_since_last)
        
        self.last_request_time = time.time()
        
    async def search_pubmed(self, query: str, max_results: int = 20, 
                           sort: str = "relevance", date_range: Optional[str] = None) -> Dict[str, Any]:
        """Search PubMed database"""
        params = {
            "db": "pubmed",
            "term": query,
            "retmax": str(max_results),
            "sort": sort,
            "retmode": "json"
        }
        
        if date_range:
            params["datetype"] = "pdat"
            params["reldate"] = date_range
            
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
            
        url = f"{self.BASE_URL}/esearch.fcgi"
        
        try:
            await self._rate_limit()
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"PubMed search failed: {e}")
            raise
    
    async def get_article_details(self, pmids: List[str]) -> Dict[str, Any]:
        """Fetch detailed information for specific PMIDs"""
        pmid_list = ",".join(pmids)
        params = {
            "db": "pubmed",
            "id": pmid_list,
            "retmode": "xml",
            "rettype": "abstract"
        }
        
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
            
        url = f"{self.BASE_URL}/efetch.fcgi"
        
        try:
            await self._rate_limit()
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return self._parse_pubmed_xml(response.text)
        except Exception as e:
            logger.error(f"Article details fetch failed: {e}")
            raise
    
    async def search_mesh_terms(self, term: str) -> Dict[str, Any]:
        """Resolve a free-text term to MeSH descriptors.

        Two calls are required because no single NCBI endpoint carries the
        descriptor fields: esearch runs the phrase through NCBI automatic term
        mapping and returns UIDs, then esummary returns the records themselves.
        EFetch is not an option here -- `db=mesh` only serves text/plain, it has
        no XML mode, so its output cannot be parsed reliably.
        """
        params = {
            "db": "mesh",
            "term": term,
            "retmax": "10",
            "retmode": "json"
        }
        
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
            
        url = f"{self.BASE_URL}/esearch.fcgi"
        
        try:
            await self._rate_limit()
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        except Exception as e:
            logger.error(f"MeSH search failed: {e}")
            raise
        
        esearch = payload.get("esearchresult") or {}
        uids = [str(uid) for uid in esearch.get("idlist") or [] if uid]
        
        descriptors: List[Dict[str, Any]] = []
        if uids:
            descriptors = await self._fetch_mesh_descriptors(uids, term)
        
        result: Dict[str, Any] = {
            "query": term,
            "count": len(descriptors),
            "descriptors": descriptors,
            # Automatic term mapping is not an exact lookup, so surface how NCBI
            # interpreted the phrase rather than hiding it.
            "query_translation": esearch.get("querytranslation"),
        }
        if not descriptors:
            result["note"] = (
                "NCBI automatic term mapping returned no descriptors; the term may "
                "not exist in the MeSH controlled vocabulary."
            )
        return result
    
    async def _fetch_mesh_descriptors(self, uids: List[str], term: str) -> List[Dict[str, Any]]:
        """Read MeSH descriptor records for already-resolved UIDs."""
        params = {
            "db": "mesh",
            "id": ",".join(uids),
            "retmode": "json",
        }
        
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        
        url = f"{self.BASE_URL}/esummary.fcgi"
        
        try:
            await self._rate_limit()
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        except Exception as e:
            logger.error(f"MeSH descriptor fetch failed: {e}")
            return []
        
        return self._parse_mesh_summary(payload, uids, term)
    
    @staticmethod
    def _parse_mesh_summary(payload: Dict[str, Any], uids: List[str],
                           term: str) -> List[Dict[str, Any]]:
        """Map an esummary MeSH response onto the documented descriptor shape."""
        result_block = payload.get("result") or {}
        normalized_query = " ".join(term.split()).casefold()
        descriptors: List[Dict[str, Any]] = []
        
        for uid in uids:
            record = result_block.get(uid)
            if not isinstance(record, dict) or record.get("error"):
                continue
            
            # ds_meshterms[0] is the preferred heading; the rest are entry terms,
            # i.e. the descriptor's synonyms.
            terms = [
                item.strip() for item in (record.get("ds_meshterms") or [])
                if isinstance(item, str) and item.strip()
            ]
            matched_term = next(
                (item for item in terms
                 if " ".join(item.split()).casefold() == normalized_query),
                None,
            )
            
            tree_numbers = [
                link.get("treenum")
                for link in (record.get("ds_idxlinks") or [])
                if isinstance(link, dict) and link.get("treenum")
            ]
            
            descriptors.append({
                "uid": uid,
                "label": terms[0] if terms else None,
                "mesh_ui": record.get("ds_meshui") or None,
                "synonyms": terms[1:] if terms else [],
                "scope_note": record.get("ds_scopenote") or None,
                "year_introduced": record.get("ds_yearintroduced") or None,
                "tree_numbers": tree_numbers,
                "record_type": record.get("ds_recordtype") or None,
                # Which term actually matched, so an approximate mapping is
                # visible to the caller instead of being silently accepted.
                "matched_term": matched_term,
            })
        
        return descriptors
    
    async def get_related_articles(self, pmid: str, max_results: int = 10) -> Dict[str, Any]:
        """Find articles related to a given PMID.

        The raw ELink payload is deliberately not returned: it carries every link
        set NCBI holds and runs to tens of thousands of characters, and ELink does
        not honour retmax for the link lists. The sets are parsed and truncated
        here instead.
        """
        params = {
            "dbfrom": "pubmed",
            "db": "pubmed",
            "id": pmid,
            "retmax": str(max_results),
            "retmode": "json"
        }
        
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
            
        url = f"{self.BASE_URL}/elink.fcgi"
        
        try:
            await self._rate_limit()
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        except Exception as e:
            logger.error(f"Related articles fetch failed: {e}")
            raise
        
        return self._parse_elink_related(payload, pmid, max_results)
    
    @staticmethod
    def _parse_elink_related(payload: Dict[str, Any], pmid: str,
                            max_results: int) -> Dict[str, Any]:
        """Reduce an ELink response to the documented related-article shape."""
        seed = str(pmid).strip()
        try:
            limit = max(0, int(max_results))
        except (TypeError, ValueError):
            limit = 10
        
        by_link_set: Dict[str, List[str]] = {}
        
        for linkset in payload.get("linksets") or []:
            if not isinstance(linkset, dict):
                continue
            # Ignore link sets that belong to some other seed id.
            link_ids = [str(item) for item in (linkset.get("ids") or [])]
            if link_ids and seed not in link_ids:
                continue
            
            for linksetdb in linkset.get("linksetdbs") or []:
                if not isinstance(linksetdb, dict):
                    continue
                name = linksetdb.get("linkname") or "unknown"
                bucket = by_link_set.setdefault(name, [])
                for linked in linksetdb.get("links") or []:
                    linked = str(linked)
                    # ELink echoes the query PMID back inside every set.
                    if linked != seed and linked not in bucket:
                        bucket.append(linked)
        
        if not by_link_set:
            return {
                "pmid": seed,
                "related_pmids": [],
                "total_related": 0,
                "link_sets": [],
                "reviews": [],
                "note": "PubMed holds no related-article links for this PMID.",
            }
        
        # pubmed_pubmed is PubMed's own similar-articles set; the others are
        # narrower slices of it (reviews, and reviews from the last five years).
        primary = "pubmed_pubmed" if "pubmed_pubmed" in by_link_set else sorted(by_link_set)[0]
        primary_links = by_link_set[primary]
        reviews = by_link_set.get("pubmed_pubmed_reviews", [])
        
        return {
            "pmid": seed,
            "related_pmids": primary_links[:limit],
            "total_related": len(primary_links),
            "primary_link_set": primary,
            "link_sets": sorted(by_link_set),
            "reviews": reviews[:limit],
        }

    async def advanced_search(self, terms: List[str], operator: str = "AND",
                            authors: Optional[List[str]] = None, journals: Optional[List[str]] = None,
                            publication_types: Optional[List[str]] = None, date_from: Optional[str] = None,
                            date_to: Optional[str] = None, max_results: int = 20) -> Dict[str, Any]:
        """Perform advanced search with multiple criteria"""
        query_parts = []
        
        # Add main terms
        if terms:
            term_query = f" {operator} ".join(terms)
            query_parts.append(f"({term_query})")
        
        # Add authors
        if authors:
            author_queries = [f"{author}[au]" for author in authors]
            query_parts.append(f"({' OR '.join(author_queries)})")
        
        # Add journals
        if journals:
            journal_queries = [f"{journal}[journal]" for journal in journals]
            query_parts.append(f"({' OR '.join(journal_queries)})")
        
        # Add publication types
        if publication_types:
            pub_type_queries = [f"{pub_type}[pt]" for pub_type in publication_types]
            query_parts.append(f"({' OR '.join(pub_type_queries)})")
        
        # Add date range
        if date_from and date_to:
            query_parts.append(f"({date_from}[pdat]:{date_to}[pdat])")
        
        # Combine all parts
        final_query = " AND ".join(query_parts)
        
        # Use regular search with the complex query
        return await self.search_pubmed(final_query, max_results)
    
    def _parse_pubmed_xml(self, xml_text: str) -> Dict[str, Any]:
        """Parse PubMed XML response into structured data"""
        try:
            root = ET.fromstring(xml_text)
            articles = []
            
            for article in root.findall(".//PubmedArticle"):
                article_data = {}
                
                # PMID
                pmid_elem = article.find(".//PMID")
                if pmid_elem is not None:
                    article_data["pmid"] = pmid_elem.text
                
                # Title -- itertext() keeps nested markup (<i>, <sup>, ...) instead
                # of truncating the title at the first child tag. Set unconditionally
                # so a record with no ArticleTitle element at all still carries a
                # title key rather than silently omitting the field.
                title_elem = article.find(".//ArticleTitle")
                title_text = (
                    "".join(title_elem.itertext()).strip() if title_elem is not None else ""
                )
                article_data["title"] = title_text or "No title available"
                
                # Authors -- collective names and last-name-only entries included;
                # requiring a ForeName silently dropped consortium authors.
                authors = []
                for author in article.findall(".//Author"):
                    collective = author.find("CollectiveName")
                    if collective is not None and collective.text:
                        authors.append(collective.text.strip())
                        continue
                    last_name = author.find("LastName")
                    if last_name is None or not last_name.text:
                        continue
                    first_name = author.find("ForeName")
                    if first_name is None:
                        first_name = author.find("Initials")
                    if first_name is not None and first_name.text:
                        authors.append(f"{first_name.text} {last_name.text}")
                    else:
                        authors.append(last_name.text)
                article_data["authors"] = authors
                
                # Journal
                journal_elem = article.find(".//Journal/Title")
                if journal_elem is not None:
                    article_data["journal"] = journal_elem.text
                
                # Publication date -- MedlineDate carries ranges and seasons that
                # have no numeric month, so prefer it when it is present.
                pub_date = article.find(".//PubDate")
                if pub_date is not None:
                    medline_date = pub_date.find("MedlineDate")
                    if medline_date is not None and medline_date.text:
                        article_data["publication_date"] = medline_date.text.strip()
                    else:
                        year = pub_date.find("Year")
                        if year is not None and year.text:
                            date_str = year.text
                            month = pub_date.find("Month")
                            if month is not None and month.text:
                                date_str += f"-{month.text}"
                                day = pub_date.find("Day")
                                if day is not None and day.text:
                                    date_str += f"-{day.text}"
                            article_data["publication_date"] = date_str
                
                # Abstract -- a structured abstract is a sequence of labelled
                # AbstractText sections; reading only the first silently dropped
                # every later section. Scoping to Abstract/AbstractText also skips
                # the separate OtherAbstract used for translated text.
                abstract_parts = []
                for abstract_elem in article.findall(".//Abstract/AbstractText"):
                    text = "".join(abstract_elem.itertext()).strip()
                    if not text:
                        continue
                    label = abstract_elem.get("Label")
                    abstract_parts.append(f"{label}: {text}" if label else text)
                if abstract_parts:
                    article_data["abstract"] = " ".join(abstract_parts)
                
                # DOI
                doi_elem = article.find(".//ELocationID[@EIdType='doi']")
                if doi_elem is not None:
                    article_data["doi"] = doi_elem.text
                
                # Keywords/MeSH terms
                mesh_terms = []
                for mesh in article.findall(".//MeshHeading/DescriptorName"):
                    if mesh.text:
                        mesh_terms.append(mesh.text)
                article_data["mesh_terms"] = mesh_terms
                
                articles.append(article_data)
            
            return {"articles": articles}
            
        except ET.ParseError as e:
            logger.error(f"XML parsing failed: {e}")
            return {"articles": [], "error": "Failed to parse XML response"}

# Import caching and batch processing
from .cache import CacheManager, CachedNCBIClient
from .batch import BatchProcessor

# Configure caching
# PATCHED: this was os.path.join(os.getcwd(), ".cache").  CacheManager is built at
# import time, so a launcher whose cwd is not writable killed the server before it
# could answer the MCP handshake -- on macOS an app launched from Finder or Dock
# typically starts in "/", which is read-only under SIP, giving exit 1, zero bytes
# on stdout and no error visible to the client.  An absolute, cwd-independent path
# removes the failure mode; the cache no longer fragments across directories either.
cache_manager = CacheManager(
    redis_url=os.getenv("REDIS_URL"),  # You can provide: redis://localhost:6379/0
    file_cache_dir=os.getenv("NCBI_MCP_CACHE_DIR")
    or os.path.join(os.path.expanduser("~"), ".cache", "ncbi-mcp-server"),
)

# Initialize NCBI client with caching
ncbi_client = CachedNCBIClient(
    NCBIClient(
        email=os.getenv("NCBI_EMAIL"),
        api_key=os.getenv("NCBI_API_KEY")
    ),
    cache_manager
)

# Initialize batch processor
batch_processor = BatchProcessor(ncbi_client, max_concurrent=5)

# Initialize analytics manager
# PATCHED: this was os.path.join(os.getcwd(), "analytics.json").  Analytics is written
# lazily (start/flush), so a read-only working directory did not kill the server the way
# the cache path did -- but every flush failed, and the file scattered into whatever
# directory the client happened to launch from.  Keep it absolute, beside the cache.
_DATA_DIR = os.getenv("NCBI_MCP_DATA_DIR") or os.path.join(
    os.path.expanduser("~"), ".cache", "ncbi-mcp-server"
)
_ANALYTICS_FILE = os.path.join(_DATA_DIR, "analytics.json")

analytics_manager = AnalyticsManager(
    analytics_file=_ANALYTICS_FILE,
    max_events_memory=1000,
    flush_interval=300  # 5 minutes
)

# Register the manager so that @track_usage can reach it.
# Doing this at import time, on a name importable from any launch path, is what
# makes recording work: it used to be looked up via
# sys.modules['ncbi_mcp_server.server'], which simply does not exist when the
# process is started with `python -m` (the module runs as __main__).
set_analytics_manager(analytics_manager)

async def startup():
    """Start background services before the server accepts requests."""
    await analytics_manager.start()
    logger.info("All services initialized")

async def shutdown():
    """Flush analytics and release the HTTP client on exit."""
    await analytics_manager.stop()
    await ncbi_client.close()
    logger.info("All services shut down")

@asynccontextmanager
async def lifespan(server: FastMCP):
    """FastMCP lifespan hook.

    Analytics has to be started from inside the server's own event loop: the
    periodic flush is an asyncio task, and one created on a different loop would
    be torn down before it ever wrote anything. This replaces a startup()/
    shutdown() pair that was defined but never invoked -- main() called only
    mcp.run() -- so analytics.json was never updated and the flush task never
    existed.
    """
    await startup()
    try:
        yield {}
    finally:
        await shutdown()

# Create FastMCP server
mcp = FastMCP("NCBI Literature Search", lifespan=lifespan)

@mcp.tool()
@track_usage("search_pubmed", "search")
async def search_pubmed(
    query: str,
    max_results: int = 20,
    sort: str = "relevance",
    date_range: Optional[str] = None
) -> Dict[str, Any]:
    """Search PubMed database for scientific literature."""
    try:
        result = await ncbi_client.search_pubmed(query, max_results, sort, date_range)
        return result
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
@track_usage("get_article_details", "fetch")
async def get_article_details(pmids: List[str]) -> Dict[str, Any]:
    """Fetch detailed information for specific PubMed articles."""
    try:
        result = await ncbi_client.get_article_details(pmids)
        return result
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
@track_usage("search_mesh_terms", "search")
async def search_mesh_terms(term: str) -> Dict[str, Any]:
    """Search Medical Subject Headings (MeSH) terms."""
    try:
        result = await ncbi_client.search_mesh_terms(term)
        return result
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
@track_usage("get_related_articles", "search")
async def get_related_articles(pmid: str, max_results: int = 10) -> Dict[str, Any]:
    """Find articles related to a specific PubMed article."""
    try:
        result = await ncbi_client.get_related_articles(pmid, max_results)
        return result
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
@track_usage("advanced_search", "search")
async def advanced_search(
    terms: List[str],
    operator: str = "AND",
    authors: Optional[List[str]] = None,
    journals: Optional[List[str]] = None,
    publication_types: Optional[List[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    max_results: int = 20
) -> Dict[str, Any]:
    """Perform advanced PubMed searches with multiple criteria."""
    try:
        result = await ncbi_client.advanced_search(
            terms, operator, authors, journals, publication_types,
            date_from, date_to, max_results
        )
        return result
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
async def cache_stats() -> Dict[str, Any]:
    """Get cache performance statistics."""
    try:
        stats = await cache_manager.stats()
        return stats
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
async def clear_cache() -> Dict[str, Any]:
    """Clear expired cache entries."""
    try:
        cleared = await cache_manager.clear_expired()
        return {
            "status": "success",
            "cleared_entries": cleared,
            "message": f"Cleared {cleared} expired cache entries"
        }
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
@track_usage("batch_search_multiple_queries", "batch")
async def batch_search_multiple_queries(queries: List[str], max_results_per_query: int = 20) -> Dict[str, Any]:
    """Perform multiple PubMed searches in parallel for efficiency."""
    try:
        result = await batch_processor.batch_search(queries, max_results_per_query)
        return {
            "success_count": result.success_count,
            "failure_count": result.failure_count,
            "total_time": result.total_time,
            "results": result.results,
            "errors": result.errors
        }
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
@track_usage("batch_get_article_details", "batch")
async def batch_get_article_details(pmids: List[str], chunk_size: int = 50) -> Dict[str, Any]:
    """Fetch article details for many PMIDs efficiently in batches.

    Counts are reported per article, not per chunk: success_count is the number
    of article records returned and failure_count is the number of requested
    PMIDs that produced no record, so success_count + failure_count always adds
    up to pmids_requested. Chunk-level totals describe the batching itself;
    previously success_count counted *chunks* while total_articles counted
    *articles*, which is why they disagreed on any multi-PMID request.
    """
    try:
        # De-duplicate while preserving order: a repeated PMID would otherwise be
        # fetched twice and inflate the article counts.
        requested = []
        for pmid in pmids:
            value = str(pmid).strip()
            if value and value not in requested:
                requested.append(value)
        
        if not requested:
            return {
                "success_count": 0,
                "failure_count": 0,
                "total_articles": 0,
                "pmids_requested": 0,
                "articles": [],
                "errors": []
            }
        
        # Split PMIDs into chunks
        pmid_chunks = batch_processor.chunk_pmids(requested, chunk_size)
        result = await batch_processor.batch_get_articles(pmid_chunks)
        
        # Flatten results, dropping duplicates that survived across chunks
        all_articles = []
        returned_pmids = set()
        for batch_result in result.results:
            articles = (batch_result.get("result") or {}).get("articles") or []
            for article in articles:
                article_pmid = str(article.get("pmid") or "").strip()
                if article_pmid and article_pmid in returned_pmids:
                    continue
                if article_pmid:
                    returned_pmids.add(article_pmid)
                all_articles.append(article)
        
        errors = list(result.errors)
        missing = [pmid for pmid in requested if pmid not in returned_pmids]
        if missing:
            errors.append(
                "No article record returned for PMID(s): " + ", ".join(missing)
            )
        
        return {
            "success_count": len(all_articles),
            "failure_count": len(missing),
            "total_articles": len(all_articles),
            "pmids_requested": len(requested),
            "pmids_returned": len(returned_pmids),
            "articles": all_articles,
            "errors": errors,
            "chunks": {
                "total": len(pmid_chunks),
                "succeeded": result.success_count,
                "failed": result.failure_count
            },
            "total_time": result.total_time
        }
    except Exception as e:
        return {"error": str(e)}

# Analytics MCP Tools
@mcp.tool()
async def get_analytics_summary() -> Dict[str, Any]:
    """Get comprehensive analytics summary including usage stats, performance metrics, and system health."""
    try:
        summary = await analytics_manager.get_analytics_summary()
        return summary
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
async def get_detailed_metrics(hours: int = 24) -> Dict[str, Any]:
    """Get detailed performance metrics for the specified time period (default: last 24 hours)."""
    try:
        metrics = await analytics_manager.get_detailed_metrics(hours)
        return metrics
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
async def reset_analytics() -> Dict[str, Any]:
    """Reset analytics data (use with caution - this will clear all collected metrics)."""
    try:
        # Reset in place. Rebuilding the manager and calling start() did not clear
        # anything: start() reloads the previous counters from disk immediately.
        await analytics_manager.reset()
        return {
            "status": "success",
            "message": "Analytics data has been reset",
            "reset_time": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e)}

def main():
    """Main function to run the MCP server.

    Startup and shutdown are handled by the lifespan hook passed to FastMCP.
    mcp.run() owns the event loop, so that hook is the only place where the
    analytics flush task can be created and cancelled safely. The previous
    version defined a run_with_lifecycle() that called mcp.run_async() -- a
    method FastMCP does not have -- and then never called it anyway.
    """
    mcp.run()

if __name__ == "__main__":
    main()
