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
