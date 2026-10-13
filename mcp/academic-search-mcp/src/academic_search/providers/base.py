"""Base provider interface.

All paper providers inherit from :class:`BaseProvider`.  The
:func:`register_provider` decorator and :func:`get_provider` factory
live in ``__init__.py``.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Type alias for optional progress callbacks
# Signature: progress(current, total, message)
ProgressCallback = Optional[Callable[[int, int, str], None]]


class BaseProvider:
    """Abstract base class for paper repository providers.

    Every provider must implement:

    * :meth:`search` — full-text / keyword search
    * :meth:`search_by_author` — author-specific lookup

    Subclasses should also set :attr:`provider_name`.

    All methods return paper data normalized to the common schema
    (see :mod:`academic_search.models`).
    """

    provider_name: str = "base"

    #: HTTP statuses where the API answered decisively ("no such record" or a
    #: rejected request).  These stay a genuine empty result; every other
    #: recorded failure means the provider was not reached.
    DECISIVE_HTTP_STATUSES: frozenset[int] = frozenset({400, 404})

    def _record_request_error(
        self,
        kind: str,
        status: Optional[int] = None,
        attempt: Optional[int] = None,
    ) -> None:
        """Record the outcome of a failed request attempt.

        ``_last_request_error`` is the pattern :class:`SemanticScholarProvider`
        already used to tell "this identifier does not exist" (HTTP 404) apart
        from "we were rate limited" (HTTP 429).  A request that succeeds clears
        it, so ``None`` means any empty result is a real zero.
        """
        error: dict[str, Any] = {"kind": kind, "attempt": attempt}
        if status is not None:
            error["status"] = status
        self._last_request_error = error

    def _unavailable_meta(self) -> Optional[dict[str, Any]]:
        """Availability record for the last failed request, or ``None``.

        Callers add it to their metadata (and the tool layer turns it into an
        explicit error) when zero records came back: an outage must not be
        indistinguishable from "no matching papers".
        """
        error = getattr(self, "_last_request_error", None)
        if not error:
            return None
        kind = error.get("kind")
        status = error.get("status")
        if kind == "http_error" and status in self.DECISIVE_HTTP_STATUSES:
            # The API answered: 404 is "no such record", 400 is a bad query.
            return None
        if kind == "timeout":
            message = f"{self.provider_name} timed out after retries"
        elif kind == "connection_error":
            message = (
                f"{self.provider_name} could not be reached (network/DNS failure)"
            )
        elif kind == "http_error":
            message = f"{self.provider_name} answered HTTP {status} after retries"
        else:
            message = f"{self.provider_name} request failed ({kind})"
        record = dict(error)
        record["source"] = self.provider_name
        record["message"] = message
        return record

    def search(
        self,
        query: str,
        max_retrieval: int = 10_000,
        limit: int = 50,
        progress_callback: ProgressCallback = None,
        **kwargs: Any,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Search for papers matching *query*.

        Args:
            query: Search string (regex or plain text depending on provider).
            max_retrieval: Maximum number of papers to fetch from the API.
            limit: Maximum number of papers to return.
            progress_callback: Optional callback for progress reporting
                ``(current, total, message)``.
            **kwargs: Provider-specific search parameters.

        Returns:
            Tuple of (papers_list, metadata_dict).
        """
        raise NotImplementedError

    def search_by_author(
        self,
        author_name: str,
        max_retrieval: int = 10_000,
        limit: int = 50,
        progress_callback: ProgressCallback = None,
        **kwargs: Any,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Search for papers by a specific author.

        Args:
            author_name: Author name (e.g. ``"Yoshua Bengio"``).
            max_retrieval: Maximum number of papers to fetch from the API.
            limit: Maximum number of papers to return.
            progress_callback: Optional callback for progress reporting
                ``(current, total, message)``.
            **kwargs: Provider-specific search parameters.

        Returns:
            Tuple of (papers_list, metadata_dict).
        """
        raise NotImplementedError

    def get_stats(
        self,
        query: str,
        max_retrieval: int = 10_000,
    ) -> dict[str, Any]:
        """Fetch papers and return metadata about the result set.

        Args:
            query: Search string.
            max_retrieval: Maximum number of papers to fetch.

        Returns:
            A dict with at least ``total_papers`` and ``provider`` keys.
        """
        raise NotImplementedError
