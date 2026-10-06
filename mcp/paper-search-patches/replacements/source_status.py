"""Shared source-availability and query-building helpers.

PATCHED-BY-paper-search-mcp-patches: Tier-1 availability layer + Tier-2 query builders.

Why this module exists
----------------------
Every upstream connector swallowed its transport errors and returned an empty
list::

    except Exception as exc:
        logger.error("Zenodo search failed: %s", exc)
        return []

That makes a rate-limited, overloaded or down source *indistinguishable* from a
source that genuinely has no matching literature.  A sweep then records
"0 results" and the caller concludes the literature does not exist -- the most
misleading failure mode a discovery tool can have.  Measured: anonymous OpenAlex
search answers HTTP 429 "Rate limit exceeded" while ``filter=title.search:``
still answers 200, so one query can legitimately return 0 with no signal at all.

This module makes availability explicit:

  * :class:`SourceUnavailable` -- raised instead of returning ``[]``.
  * :func:`request_json` -- retries, honours ``Retry-After`` / JSON ``retryAfter``.
  * :func:`search_ladder` -- runs progressively looser queries, which also fixes
    the second measured defect: one loose ``search=<query>`` matched
    196 342 OpenAlex works (1 relevant in 36) whereas ``title.search:`` matched
    1 439 with an on-target top-3.
  * :func:`unavailable_marker` / :func:`split_markers` -- carry the condition
    through list-returning MCP tools without pretending it is a paper.

Stdlib only, no package-internal imports (connectors import this module).
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Availability
# --------------------------------------------------------------------------- #

SOURCE_OK = "ok"
SOURCE_EMPTY = "empty"
SOURCE_UNAVAILABLE = "unavailable"

#: Statuses that mean "ask again later", never "there is no such literature".
UNAVAILABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})

#: Hard cap on how long we will honour a Retry-After hint (seconds).
MAX_RETRY_AFTER = 40.0

_BACKOFF_BASE = 2.0

_MARKER_KEY = "error"


class SourceUnavailable(Exception):
    """A source could not be queried (rate limit, outage, timeout, bad request).

    Raised *instead of* returning an empty list so callers can tell
    "source unavailable" apart from "source has no matches".
    """

    def __init__(
        self,
        source: str,
        message: str = "",
        http_status: Optional[int] = None,
        retry_after: Optional[float] = None,
    ) -> None:
        self.source = source
        self.message = message
        self.http_status = http_status
        self.retry_after = retry_after
        super().__init__(self.describe())

    def describe(self) -> str:
        parts = []
        if self.http_status:
            parts.append(f"HTTP {self.http_status}")
        if self.retry_after:
            parts.append(f"retry-after {int(self.retry_after)}s")
        if self.message:
            parts.append(self.message)
        detail = "; ".join(parts)
        return f"{self.source} unavailable ({detail})" if detail else f"{self.source} unavailable"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": SOURCE_UNAVAILABLE,
            "source": self.source,
            "http_status": self.http_status,
            "retry_after": self.retry_after,
            "message": self.message or "",
            "detail": self.describe(),
        }


def is_unavailable_status(status_code: Optional[int]) -> bool:
    """True when an HTTP status means "try later", not "no results"."""
    return status_code in UNAVAILABLE_STATUS_CODES


def retry_after_seconds(response: Any = None, payload: Any = None) -> Optional[float]:
    """Best-effort Retry-After in seconds from a header or a JSON body.

    OpenAlex replies ``{"error": "Rate limit exceeded", ..., "retryAfter": 37}``
    and CORE/Crossref use the standard ``Retry-After`` header.
    """
    raw: Optional[str] = None

    headers = getattr(response, "headers", None)
    if headers is not None:
        try:
            raw = headers.get("Retry-After") or headers.get("retry-after")
        except Exception:
            raw = None

    if raw:
        try:
            return min(float(str(raw).strip()), MAX_RETRY_AFTER)
        except (TypeError, ValueError):
            pass

    if isinstance(payload, dict):
        for key in ("retryAfter", "retry_after", "Retry-After"):
            value = payload.get(key)
            if isinstance(value, (int, float)):
                return min(float(value), MAX_RETRY_AFTER)
            if isinstance(value, str):
                try:
                    return min(float(value.strip()), MAX_RETRY_AFTER)
                except ValueError:
                    pass
        # OpenAlex embeds "Please retry in 37s" inside the message.
        message = str(payload.get("message") or payload.get("error") or "")
        match = re.search(r"retry in (\d+(?:\.\d+)?)\s*s", message, re.IGNORECASE)
        if match:
            return min(float(match.group(1)), MAX_RETRY_AFTER)

    return None


def _describe_http(status_code: int, payload: Any) -> str:
    """Short human message for a failing response (used in status records)."""
    if isinstance(payload, dict):
        for key in ("message", "error", "detail", "title"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return " ".join(value.split())[:300]
    return f"HTTP {status_code}"


def request_json(
    session: Any,
    url: str,
    source: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 30,
    max_retries: int = 2,
    accept_json: bool = True,
) -> Any:
    """GET ``url`` and return parsed JSON, or raise :class:`SourceUnavailable`.

    Retries only for genuinely transient conditions (``UNAVAILABLE_STATUS_CODES``
    and transport errors), waiting ``Retry-After`` when the server supplies one
    (capped at :data:`MAX_RETRY_AFTER`).  Any other non-200 -- including 400 and
    403 -- raises immediately: a rejected request is not an empty result set.
    """
    last_error: Optional[SourceUnavailable] = None

    for attempt in range(max(1, max_retries)):
        response = None
        try:
            response = session.get(
                url,
                params=params,
                headers=headers,
                timeout=timeout,
            )
        except Exception as exc:  # requests.RequestException and friends
            last_error = SourceUnavailable(
                source, f"{type(exc).__name__}: {exc}"[:300]
            )
            if attempt < max_retries - 1:
                time.sleep(min(_BACKOFF_BASE * (2 ** attempt), MAX_RETRY_AFTER))
                continue
            raise last_error

        status_code = getattr(response, "status_code", None)

        if status_code == 200:
            if not accept_json:
                return response
            try:
                return response.json()
            except Exception as exc:
                raise SourceUnavailable(
                    source,
                    f"unparsable JSON response ({type(exc).__name__})",
                    http_status=status_code,
                )

        payload = None
        if accept_json:
            try:
                payload = response.json()
            except Exception:
                payload = None

        wait = retry_after_seconds(response, payload)

        if is_unavailable_status(status_code):
            last_error = SourceUnavailable(
                source,
                _describe_http(status_code, payload),
                http_status=status_code,
                retry_after=wait,
            )
            if attempt < max_retries - 1:
                delay = wait if wait else min(
                    _BACKOFF_BASE * (2 ** attempt), MAX_RETRY_AFTER
                )
                logger.warning(
                    "%s: HTTP %s, retrying in %.0fs (attempt %s/%s)",
                    source, status_code, delay, attempt + 1, max_retries,
                )
                time.sleep(min(delay, MAX_RETRY_AFTER))
                continue
            raise last_error

        # Non-retryable failure (400 bad query, 401/403 auth, 404 unknown, ...).
        raise SourceUnavailable(
            source,
            _describe_http(status_code, payload),
            http_status=status_code,
        )

    if last_error is not None:
        raise last_error
    raise SourceUnavailable(source, "no attempt was made")


def best_error(errors: Sequence[SourceUnavailable]) -> Optional[SourceUnavailable]:
    """Prefer a retryable ("try later") error over a rejected-request error."""
    retryable = [e for e in errors if is_unavailable_status(e.http_status)]
    if retryable:
        return retryable[0]
    return errors[0] if errors else None


def search_ladder(
    source: str,
    session: Any,
    url: str,
    attempts: Sequence[Tuple[str, Dict[str, Any]]],
    parse: Callable[[Any], Optional[Iterable[Any]]],
    timeout: float = 30,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[List[Any], str]:
    """Run progressively looser queries and return the first non-empty result.

    ``attempts`` is a sequence of ``(label, params)`` ordered most-precise first.
    A failing attempt does **not** stop the ladder: measured on OpenAlex, the
    ``search=`` cluster was rate-limited (429) while ``filter=title.search:``
    answered 200 from the same host at the same moment, so a later rung can
    legitimately succeed after an earlier one is refused.

    Returns ``(records, label)``.  When every rung fails, the most informative
    error is raised; when every rung simply finds nothing, an empty list is
    returned -- that is a real "no matches", not a silent failure.
    """
    errors: List[SourceUnavailable] = []

    for label, params in attempts:
        try:
            payload = request_json(
                session, url, source, params=params, headers=headers,
                timeout=timeout, max_retries=1,
            )
        except SourceUnavailable as exc:
            errors.append(exc)
            continue

        try:
            records = list(parse(payload) or [])
        except Exception as exc:  # parser bugs must not look like "no results"
            raise SourceUnavailable(source, f"response parsing failed: {exc}"[:300])

        if records:
            return records, label

    if errors:
        raise best_error(errors) or errors[0]

    return [], attempts[0][0] if attempts else ""


# --------------------------------------------------------------------------- #
# Availability markers for list-returning MCP tools
# --------------------------------------------------------------------------- #

def unavailable_marker(error: Exception) -> List[Dict[str, Any]]:
    """A one-item list marking that a source could not be queried.

    Single-source MCP tools return ``List[Dict]``; an empty list cannot say
    *why* it is empty.  This marker carries the reason and is detected by
    :func:`is_unavailable_marker`, so ``search_papers`` can move it into its
    per-source ``source_status`` instead of counting it as a paper.
    """
    if isinstance(error, SourceUnavailable):
        source = error.source
        http_status = error.http_status
        retry_after = error.retry_after
        message = error.message
        detail = error.describe()
    else:
        source = ""
        http_status = None
        retry_after = None
        message = f"{type(error).__name__}: {error}"[:300]
        detail = message
    return [{
        _MARKER_KEY: SOURCE_UNAVAILABLE,
        "source": source,
        "http_status": http_status,
        "retry_after": retry_after,
        "message": message,
        "detail": detail,
    }]


def is_unavailable_marker(item: Any) -> bool:
    """True when ``item`` is an availability marker rather than a paper."""
    return (
        isinstance(item, dict)
        and item.get(_MARKER_KEY) == SOURCE_UNAVAILABLE
        and not item.get("title")
        and "paper_id" not in item
    )


def split_markers(
    items: Optional[Iterable[Dict[str, Any]]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split a tool's output into ``(papers, markers)``."""
    papers: List[Dict[str, Any]] = []
    markers: List[Dict[str, Any]] = []
    for item in items or []:
        (markers if is_unavailable_marker(item) else papers).append(item)
    return papers, markers


# --------------------------------------------------------------------------- #
# Tier 2 -- query construction
# --------------------------------------------------------------------------- #

#: Dropped from AND-joined rungs only (the raw-query rung is never modified).
_STOPWORDS = frozenset("""
a an the of for and or to in on with without using use used based via from by at
as is are was were be been being its their this that these those into over under
between across during within about after before than then
""".split())

_UNSAFE = re.compile(r'[\\"()\[\]{}:^~*?]')


def clean_terms(query: str) -> List[str]:
    """Tokenize a query for field-scoped search, preserving word order."""
    tokens = [t for t in re.split(r"[^\w.+#-]+", str(query or "")) if t]
    keep = [t for t in tokens if t.lower() not in _STOPWORDS]
    if not keep:
        keep = tokens
    seen = set()
    out = []
    for token in keep:
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def search_terms(query: str) -> List[str]:
    """The terms a field-scoped query is built from (:func:`clean_terms`)."""
    return clean_terms(query)


def escape_term(term: str) -> str:
    """Escape a term so it is a safe bare literal inside a field query."""
    return _UNSAFE.sub(" ", str(term)).strip()


def phrase(query_or_terms: Any) -> str:
    """``crispr base editing`` -- the terms as a quoteable phrase body."""
    if isinstance(query_or_terms, str):
        terms = clean_terms(query_or_terms)
    else:
        terms = list(query_or_terms or [])
    return " ".join(t for t in (escape_term(t) for t in terms) if t)


def and_query(query_or_terms: Any) -> str:
    """``crispr AND base AND editing`` -- every term required."""
    if isinstance(query_or_terms, str):
        terms = clean_terms(query_or_terms)
    else:
        terms = list(query_or_terms or [])
    cleaned = [t for t in (escape_term(t) for t in terms) if t]
    return " AND ".join(cleaned)


def field_phrase(field: str, query_or_terms: Any) -> str:
    """``title:"crispr base editing"`` -- a phrase confined to one field."""
    value = phrase(query_or_terms)
    return f'{field}:"{value}"' if value else f"{field}:"


def field_and(field: str, query_or_terms: Any) -> str:
    """``title:(crispr AND base AND editing)`` -- all terms inside one field."""
    value = and_query(query_or_terms)
    return f"{field}:({value})" if value else f"{field}:"


# --------------------------------------------------------------------------- #
# Tier 7 -- "HTTP 200, but not an answer"
# --------------------------------------------------------------------------- #
# Measured failure class (2026-09-29): a source answers 200 with something that
# is not a result set.  Any status-code check sees success, the caller records
# "0 results", and the literature is then reported as non-existent.  Reproduced:
#
#   * https://www.ncbi.nlm.nih.gov/books/NBK1116/ -> HTTP 200 carrying
#     "<title>Checking your browser - reCAPTCHA</title>"
#   * connect.biorxiv.org/biorxiv_xml.php?subject=<bad slug> -> HTTP 200 with
#     1 059 bytes of empty feed (a valid slug returns ~79 000 bytes)
#   * NCBI esearch answers HTTP 200 with {"error": "error forwarding request"}
#   * efetch db=books answers HTTP 200 with an IdList and no content

#: Substrings that identify an automated-access / bot-wall page.
_BOTWALL_MARKERS = (
    "captcha",
    "checking your browser",
    "cf-browser-verification",
    "cf_chl",
    "just a moment",
    "verify you are human",
    "enable javascript and cookies",
    "access denied",
    "request blocked",
)

#: JSON keys that carry an error where a result set was expected.
_ERROR_KEYS = ("error", "errors", "errorMessage", "error_message", "fault")


def looks_like_botwall(text: Any) -> bool:
    """True when a response body is a human-verification / bot-wall page."""
    if not text:
        return False
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    lowered = str(text)[:4000].lower()
    return any(marker in lowered for marker in _BOTWALL_MARKERS)


def assert_not_botwall(
    source: str, text: Any, http_status: Optional[int] = None
) -> None:
    """Raise when a 200 response is actually a bot-wall page."""
    if looks_like_botwall(text):
        raise SourceUnavailable(
            source,
            "human verification required (bot-wall page returned with HTTP 200)",
            http_status=http_status,
        )


def shape_reason(payload: Any, keys: Sequence[str] = ()) -> Optional[str]:
    """Return why a 200 payload is not a result set, or None when it looks fine.

    ``keys`` are the top-level keys a *successful* response carries, so an error
    body or a radically different schema is caught instead of being read as an
    empty result set.
    """
    if payload is None:
        return "empty response body"
    if isinstance(payload, dict):
        error = next((payload[k] for k in _ERROR_KEYS if payload.get(k)), None)
        if error and not any(k in payload for k in keys):
            return f"error body: {str(error)[:160]}"
        if keys and not any(k in payload for k in keys):
            return f"unexpected response shape (none of: {', '.join(keys)})"
    return None


def assert_shape(
    source: str,
    payload: Any,
    keys: Sequence[str] = (),
    http_status: Optional[int] = None,
) -> None:
    """Raise when a 200 payload lacks every key a successful response carries."""
    reason = shape_reason(payload, keys)
    if reason:
        raise SourceUnavailable(source, reason, http_status=http_status)


def assert_usable_bytes(
    source: str, body: Any, min_bytes: int, label: str = "response"
) -> None:
    """Raise when a 200 body is too small to be a real result set.

    ``min_bytes`` must be a floor the endpoint cannot legitimately fall below, so
    this is only useful where an empty success and an empty payload differ in
    size (measured: a valid bioRxiv subject feed is ~79 000 bytes, an
    unrecognised slug 1 059).
    """
    size = len(body or b"")
    if size < min_bytes:
        raise SourceUnavailable(
            source,
            f"{label} too small to be a result set ({size} < {min_bytes} bytes)",
        )

