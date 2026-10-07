#!/usr/bin/env python3
"""
Usage Analytics Module for NCBI MCP Server
Tracks performance metrics, usage patterns, and cache efficiency
"""

import asyncio
import hashlib
import inspect
import json
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union
from functools import wraps
import aiofiles

logger = logging.getLogger(__name__)

@dataclass
class MetricEvent:
    """Individual metric event"""
    timestamp: datetime
    event_type: str  # 'search', 'article_details', 'cache_hit', 'cache_miss', etc.
    operation: str   # 'search_pubmed', 'get_article_details', etc.
    duration_ms: Optional[float] = None
    query_hash: Optional[str] = None
    result_count: Optional[int] = None
    cache_hit: Optional[bool] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

@dataclass
class UsageStats:
    """Aggregated usage statistics"""
    total_requests: int = 0
    total_search_queries: int = 0
    total_article_fetches: int = 0
    total_mesh_searches: int = 0
    total_related_searches: int = 0
    total_advanced_searches: int = 0
    total_batch_operations: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    total_errors: int = 0
    avg_response_time_ms: float = 0.0
    peak_requests_per_minute: int = 0
    unique_queries: int = 0
    start_time: datetime = None
    last_updated: datetime = None

class AnalyticsManager:
    """Manages usage analytics and performance metrics"""
    
    def __init__(self, 
                 analytics_file: str = "analytics.json",
                 max_events_memory: int = 1000,
                 flush_interval: int = 300):  # 5 minutes
        self.analytics_file = Path(analytics_file)
        self.max_events_memory = max_events_memory
        self.flush_interval = flush_interval
        
        # In-memory storage
        self.events: deque = deque(maxlen=max_events_memory)
        self.stats = UsageStats(start_time=datetime.now())
        self.query_hashes: set = set()
        self.request_times: deque = deque(maxlen=100)  # Last 100 requests for rate calculation
        
        # Background task for periodic flushing
        self.flush_task: Optional[asyncio.Task] = None
        self.running = False
    
    async def start(self):
        """Start the analytics manager"""
        self.running = True
        # Load existing analytics data
        await self.load_analytics()
        # Start background flush task
        self.flush_task = asyncio.create_task(self._periodic_flush())
        logger.info("Analytics manager started")
    
    async def stop(self):
        """Stop the analytics manager and flush data"""
        self.running = False
        if self.flush_task:
            self.flush_task.cancel()
            try:
                await self.flush_task
            except asyncio.CancelledError:
                pass
        await self.flush_analytics()
        logger.info("Analytics manager stopped")
    
    def record_event(self, 
                    event_type: str,
                    operation: str,
                    duration_ms: Optional[float] = None,
                    query_hash: Optional[str] = None,
                    result_count: Optional[int] = None,
                    cache_hit: Optional[bool] = None,
                    error: Optional[str] = None,
                    metadata: Optional[Dict[str, Any]] = None):
        """Record a usage event"""
        event = MetricEvent(
            timestamp=datetime.now(),
            event_type=event_type,
            operation=operation,
            duration_ms=duration_ms,
            query_hash=query_hash,
            result_count=result_count,
            cache_hit=cache_hit,
            error=error,
            metadata=metadata
        )
        
        self.events.append(event)
        self._update_stats(event)
        
        # Track request rate
        current_time = time.time()
        self.request_times.append(current_time)
    
    def record_cache_event(self, hit: bool) -> None:
        """Record a cache hit or miss.

        Kept separate from :meth:`record_event` because a cache lookup is not a
        request of its own -- it happens *inside* an already-counted tool call.
        Folding it in through ``record_event`` would inflate ``total_requests``
        and corrupt ``avg_response_time_ms``, so only the cache counters move.
        """
        if hit:
            self.stats.cache_hits += 1
        else:
            self.stats.cache_misses += 1
        self.stats.last_updated = datetime.now()
    
    async def reset(self) -> None:
        """Discard all collected metrics and persist the cleared state.

        Rebuilding the manager instead (as the MCP tool used to) did not actually
        reset anything: ``start()`` immediately called ``load_analytics()``, which
        read the previous counters straight back off disk.
        """
        self.events.clear()
        self.query_hashes.clear()
        self.request_times.clear()
        self.stats = UsageStats(start_time=datetime.now())
        await self.flush_analytics()
    
    def _update_stats(self, event: MetricEvent):
        """Update aggregated statistics"""
        self.stats.total_requests += 1
        self.stats.last_updated = datetime.now()
        
        # Count by event type
        if event.event_type == 'search':
            if event.operation == 'search_pubmed':
                self.stats.total_search_queries += 1
            elif event.operation == 'search_mesh_terms':
                self.stats.total_mesh_searches += 1
            elif event.operation == 'advanced_search':
                self.stats.total_advanced_searches += 1
            elif event.operation == 'get_related_articles':
                self.stats.total_related_searches += 1
        elif event.event_type == 'fetch':
            self.stats.total_article_fetches += 1
        elif event.event_type == 'batch':
            self.stats.total_batch_operations += 1
        
        # Cache statistics
        if event.cache_hit is True:
            self.stats.cache_hits += 1
        elif event.cache_hit is False:
            self.stats.cache_misses += 1
        
        # Error tracking
        if event.error:
            self.stats.total_errors += 1
        
        # Response time tracking
        if event.duration_ms:
            # Update rolling average
            total_time = self.stats.avg_response_time_ms * (self.stats.total_requests - 1)
            self.stats.avg_response_time_ms = (total_time + event.duration_ms) / self.stats.total_requests
        
        # Unique queries
        if event.query_hash:
            if event.query_hash not in self.query_hashes:
                self.query_hashes.add(event.query_hash)
                self.stats.unique_queries = len(self.query_hashes)
        
        # Peak requests per minute
        current_time = time.time()
        minute_ago = current_time - 60
        recent_requests = sum(1 for t in self.request_times if t > minute_ago)
        self.stats.peak_requests_per_minute = max(self.stats.peak_requests_per_minute, recent_requests)
    
    async def get_analytics_summary(self) -> Dict[str, Any]:
        """Get comprehensive analytics summary"""
        uptime = datetime.now() - self.stats.start_time if self.stats.start_time else timedelta(0)
        
        # Cache efficiency
        total_cache_operations = self.stats.cache_hits + self.stats.cache_misses
        cache_hit_rate = (self.stats.cache_hits / total_cache_operations * 100) if total_cache_operations > 0 else 0
        
        # Request rate
        current_time = time.time()
        minute_ago = current_time - 60
        requests_last_minute = sum(1 for t in self.request_times if t > minute_ago)
        
        # Recent activity analysis
        recent_events = [e for e in self.events if (datetime.now() - e.timestamp).total_seconds() < 3600]  # Last hour
        recent_errors = [e for e in recent_events if e.error]
        
        # Top operations
        operation_counts = defaultdict(int)
        for event in self.events:
            operation_counts[event.operation] += 1
        
        summary = {
            "overview": {
                "uptime_hours": round(uptime.total_seconds() / 3600, 2),
                "total_requests": self.stats.total_requests,
                "requests_last_minute": requests_last_minute,
                "peak_requests_per_minute": self.stats.peak_requests_per_minute,
                "avg_response_time_ms": round(self.stats.avg_response_time_ms, 2),
                "error_rate_percent": round((self.stats.total_errors / max(self.stats.total_requests, 1)) * 100, 2)
            },
            "operations": {
                "search_queries": self.stats.total_search_queries,
                "article_fetches": self.stats.total_article_fetches,
                "mesh_searches": self.stats.total_mesh_searches,
                "related_searches": self.stats.total_related_searches,
                "advanced_searches": self.stats.total_advanced_searches,
                "batch_operations": self.stats.total_batch_operations,
                "unique_queries": self.stats.unique_queries
            },
            "cache_performance": {
                "total_cache_operations": total_cache_operations,
                "cache_hits": self.stats.cache_hits,
                "cache_misses": self.stats.cache_misses,
                "cache_hit_rate_percent": round(cache_hit_rate, 2)
            },
            "recent_activity": {
                "events_last_hour": len(recent_events),
                "errors_last_hour": len(recent_errors),
                "most_common_operations": dict(sorted(operation_counts.items(), key=lambda x: x[1], reverse=True)[:5])
            },
            "system_health": {
                "total_errors": self.stats.total_errors,
                "events_in_memory": len(self.events),
                "last_updated": self.stats.last_updated.isoformat() if self.stats.last_updated else None
            }
        }
        
        return summary
    
    async def get_detailed_metrics(self, hours: int = 24) -> Dict[str, Any]:
        """Get detailed metrics for the specified time period"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        recent_events = [e for e in self.events if e.timestamp > cutoff_time]
        
        # Performance metrics by operation
        operation_metrics = defaultdict(lambda: {"count": 0, "total_time": 0, "errors": 0})
        
        for event in recent_events:
            metrics = operation_metrics[event.operation]
            metrics["count"] += 1
            if event.duration_ms:
                metrics["total_time"] += event.duration_ms
            if event.error:
                metrics["errors"] += 1
        
        # Calculate averages
        for operation, metrics in operation_metrics.items():
            if metrics["count"] > 0:
                metrics["avg_time_ms"] = round(metrics["total_time"] / metrics["count"], 2)
                metrics["error_rate_percent"] = round((metrics["errors"] / metrics["count"]) * 100, 2)
        
        # Timeline data (hourly buckets)
        timeline = defaultdict(lambda: {"requests": 0, "errors": 0, "avg_response_time": 0})
        
        for event in recent_events:
            hour_bucket = event.timestamp.replace(minute=0, second=0, microsecond=0)
            bucket = timeline[hour_bucket.isoformat()]
            bucket["requests"] += 1
            if event.error:
                bucket["errors"] += 1
            if event.duration_ms:
                # Simple moving average for response time
                current_avg = bucket["avg_response_time"]
                bucket["avg_response_time"] = (current_avg * (bucket["requests"] - 1) + event.duration_ms) / bucket["requests"]
        
        return {
            "time_period_hours": hours,
            "total_events": len(recent_events),
            "operation_metrics": dict(operation_metrics),
            "timeline": dict(timeline)
        }
    
    async def load_analytics(self):
        """Load analytics data from file"""
        try:
            if self.analytics_file.exists():
                async with aiofiles.open(self.analytics_file, 'r') as f:
                    data = json.loads(await f.read())
                
                # Load stats
                if 'stats' in data:
                    stats_data = data['stats']
                    self.stats = UsageStats(**{
                        k: datetime.fromisoformat(v) if k in ['start_time', 'last_updated'] and v else v
                        for k, v in stats_data.items()
                    })
                
                # Load query hashes
                if 'query_hashes' in data:
                    self.query_hashes = set(data['query_hashes'])
                
                logger.info(f"Loaded analytics data: {self.stats.total_requests} total requests")
        
        except Exception as e:
            logger.warning(f"Failed to load analytics data: {e}")
    
    async def flush_analytics(self):
        """Save analytics data to file"""
        try:
            data = {
                'stats': {
                    **asdict(self.stats),
                    'start_time': self.stats.start_time.isoformat() if self.stats.start_time else None,
                    'last_updated': self.stats.last_updated.isoformat() if self.stats.last_updated else None
                },
                'query_hashes': list(self.query_hashes),
                'last_flush': datetime.now().isoformat()
            }
            
            async with aiofiles.open(self.analytics_file, 'w') as f:
                await f.write(json.dumps(data, indent=2))
            
            logger.debug("Analytics data flushed to file")
        
        except Exception as e:
            logger.error(f"Failed to flush analytics data: {e}")
    
    async def _periodic_flush(self):
        """Background task to periodically flush analytics data"""
        while self.running:
            try:
                await asyncio.sleep(self.flush_interval)
                await self.flush_analytics()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic flush: {e}")

def _extract_query_hash(func: Callable[..., Any], args: tuple, kwargs: Dict[str, Any]) -> Optional[str]:
    """Hash the search term of a tool call, wherever it was passed.

    FastMCP normally passes arguments by keyword, but reading only ``kwargs``
    silently dropped the hash (and therefore ``unique_queries``) for any caller
    that used positional arguments.
    """
    value = kwargs.get("query") or kwargs.get("term")
    if value is None:
        try:
            bound = inspect.signature(func).bind_partial(*args, **kwargs)
        except (TypeError, ValueError):
            bound = None
        if bound is not None:
            value = bound.arguments.get("query") or bound.arguments.get("term")
    if isinstance(value, str) and value:
        return hashlib.md5(value.encode()).hexdigest()[:8]
    return None


def _extract_result_count(result: Any) -> Optional[int]:
    """Pull a result count out of whichever payload shape the tool returned."""
    if not isinstance(result, dict):
        return None
    esearch = result.get("esearchresult")
    if isinstance(esearch, dict) and "idlist" in esearch:
        return len(esearch["idlist"])
    for key in ("articles", "related_pmids", "descriptors", "results"):
        value = result.get(key)
        if isinstance(value, list):
            return len(value)
    return None


def track_usage(operation: str, event_type: str = "search"):
    """Decorator to track usage analytics for MCP tool functions"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            error: Optional[str] = None
            result = None

            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                error = str(e)
                raise
            finally:
                duration_ms = (time.time() - start_time) * 1000

                # The MCP tools swallow their own exceptions and return
                # {"error": ...}, so a raised exception is not the only failure
                # signal -- without this check total_errors stayed at 0 forever.
                if error is None and isinstance(result, dict) and result.get("error"):
                    error = str(result["error"])

                # Record the event against the registered manager.
                #
                # This used to go through sys.modules['ncbi_mcp_server.server'].
                # Under `python -m ncbi_mcp_server.server` the module executes as
                # __main__, so that dotted name is never present in sys.modules,
                # the guard was always false, and *nothing* was ever recorded --
                # which is why every analytics counter read back 0.
                manager = get_analytics_manager()
                if manager is not None:
                    try:
                        manager.record_event(
                            event_type=event_type,
                            operation=operation,
                            duration_ms=duration_ms,
                            query_hash=_extract_query_hash(func, args, kwargs),
                            result_count=_extract_result_count(result),
                            cache_hit=None,
                            error=error,
                        )
                    except Exception:
                        # Warn rather than pass silently: a swallowing except here
                        # is what let the sys.modules bug hide for so long.
                        logger.warning(
                            "Failed to record analytics event for %s", operation,
                            exc_info=True,
                        )

        return wrapper
    return decorator

# ---------------------------------------------------------------------------
# Analytics manager registry
# ---------------------------------------------------------------------------
# The manager is created in server.py, but track_usage lives here.  Reaching
# across modules through sys.modules['ncbi_mcp_server.server'] did not work when
# the server was started with `python -m ncbi_mcp_server.server` (the module runs
# as __main__, so that key never existed) and it also left cache.py holding a
# stale None.  A registry set explicitly at construction time is launch-agnostic.
_analytics_manager: Optional[AnalyticsManager] = None

# Deprecated alias kept so existing `from .analytics import analytics_manager`
# imports keep resolving; prefer get_analytics_manager() for live access.
analytics_manager: Optional[AnalyticsManager] = None


def set_analytics_manager(manager: Optional[AnalyticsManager]) -> None:
    """Register the process-wide analytics manager."""
    global _analytics_manager, analytics_manager
    _analytics_manager = manager
    analytics_manager = manager


def get_analytics_manager() -> Optional[AnalyticsManager]:
    """Return the registered analytics manager, or None if not set up yet."""
    return _analytics_manager
