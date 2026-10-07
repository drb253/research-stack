"""Provider registry and factory.

All paper providers inherit from :class:`BaseProvider` (in ``base.py``)
and register themselves via the :func:`register_provider` decorator.
The :func:`get_provider` factory returns the appropriate provider for a
given name.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .base import BaseProvider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

_providers: dict[str, type[BaseProvider]] = {}


def register_provider(name: str):
    """Decorator that registers a provider class under *name*.

    Usage::

        @register_provider("openalex")
        class OpenAlexProvider(BaseProvider):
            ...
    """
    def decorator(cls):
        _providers[name.lower()] = cls
        cls.provider_name = name.lower()
        return cls
    return decorator


def get_provider(
    name: str,
    **kwargs: Any,
) -> BaseProvider:
    """Return an instance of the named provider.

    Args:
        name: Provider name (e.g. ``"semantic_scholar"``, ``"openalex"``,
            ``"crossref"``, ``"pubmed"``).
        **kwargs: Provider-specific constructor arguments.

    Returns:
        An initialized provider instance.

    Raises:
        ValueError: If *name* is not a registered provider.
    """
    name = name.lower().replace("-", "_")
    cls = _providers.get(name)
    if cls is None:
        available = ", ".join(sorted(_providers))
        raise ValueError(
            f"Unknown provider '{name}'. Available providers: {available}"
        )
    logger.info("Using provider: %s", name)
    return cls(**kwargs)


def list_providers() -> list[str]:
    """Return a sorted list of registered provider names."""
    return sorted(_providers)


# ---------------------------------------------------------------------------
# Auto-import all provider modules so their decorators execute.
# ---------------------------------------------------------------------------

from . import semantic_scholar  # noqa: F401, E402
from . import crossref          # noqa: F401, E402
from . import openalex          # noqa: F401, E402
from . import pubmed            # noqa: F401, E402
