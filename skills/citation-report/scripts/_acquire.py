"""Acquire readable evidence for a source, and record exactly how it was obtained.

A citation report can only test a sentence when it holds the cited work's own words.
When a source was never supplied as a file, this module makes one bounded, polite
attempt to fetch the text itself -- but only text that is legitimately open access.
Where the material is paywalled, the honest outcome is ``unavailable``, recorded as
a failed attempt rather than papered over; on a real clinical reference list only a
minority of DOIs are open access, and the report must say so rather than guess.

Three tiers, always in this order, always recording an attempt whether it succeeds
or fails:

1. ``api`` -- **open-access full text from Europe PMC.** A keyless ``search`` query
   for the DOI; when the record carries a ``pmcid`` *and* ``isOpenAccess == "Y"``,
   the ``fullTextXML`` for that PMCID is fetched and flattened to text. Section
   titles are kept so a locator can name a section (there are no page numbers in an
   XML record); the offsets live on ``source.evidence_sections`` and
   :func:`section_locator` turns one into a label.
2. ``pdf`` -- **open-access PDF via OpenAlex.** ``best_oa_location.pdf_url`` (falling
   back to ``open_access.oa_url``) is downloaded into ``cache_dir`` and read with
   :func:`_pdftext.extract_pdf`. This is the tier that can yield *page* locators.
3. ``cli`` -- **the vendored ``paper-search`` package.** Strictly optional: located
   with :func:`shutil.which`, run as a subprocess, never imported, never installed.
   It is invoked only to read a PMCID this run has already established is open
   access, and only with its output directed inside ``cache_dir``.

Identity is verified before any acquired text is used. A wrong DOI in a reference
list resolves perfectly well -- to the wrong paper -- and grading a sentence against
the wrong paper is the one failure this module exists to prevent. The DOI must match
(normalised, case-insensitive) and, when a title is available, it must pass
:func:`_resolve.title_matches`. On any doubt the text is discarded entirely and
``identity_check`` is set to ``"mismatch"``.

Nothing here bypasses a paywall, uses a credential, or scrapes a publisher's HTML.
Requests are serialised, paced by a small delay, sent with the repository's
``mailto`` user-agent. With ``offline=True`` no request is made, no file is written,
and no attempt is recorded. Compatible with Python 3.9+ (standard library only).
"""

from __future__ import annotations

import http.client
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

import _bundle
import _common
import _pdftext
import _resolve

#: Same convention as `_resolve`: a contactable user-agent, one module-level string.
USER_AGENT = "citation-report/1.0 (mailto:%s)"
DEFAULT_MAILTO = _resolve.DEFAULT_MAILTO

EUROPEPMC_SEARCH = _resolve.EUROPEPMC
EUROPEPMC_FULLTEXT = "https://www.ebi.ac.uk/europepmc/webservices/rest/%s/fullTextXML"
OPENALEX = _resolve.OPENALEX
PAPER_SEARCH = "paper-search"

#: The tiers, in the order they are tried. Anything else in `allow` is a caller bug.
TIERS = ("api", "pdf", "cli")

REQUEST_TIMEOUT = 30
REQUEST_TRIES = 3
#: One request at a time, and at least this long between them. Polite by fiat.
MIN_REQUEST_INTERVAL = 0.6
MAX_XML_BYTES = 8_000_000
MAX_PDF_BYTES = 40_000_000
MAX_ENDPOINT_CHARS = 300
CLI_TIMEOUT = 180

#: Below this many characters, a CLI answer is a refusal or a stub, not evidence.
MIN_CLI_CHARS = 200

#: Output a `paper-search` invocation may print while still exiting 0. It refuses
#: in prose rather than by status code, so the prose has to be recognised.
_CLI_REFUSALS = (
    "failed to read",
    "cannot be read directly",
    "does not provide direct paper text",
    "no text",
)

#: Inline JATS elements whose text is markup, not prose, and must not leak into the
#: evidence a sentence is graded against.
_DROP_INLINE = frozenset(
    {"xref", "fn", "label", "graphic", "inline-graphic", "supplementary-material"}
)

#: Block-level JATS elements that hold a paragraph's worth of readable text.
_BLOCK_TAGS = frozenset(
    {
        "p",
        "td",
        "th",
        "caption",
        "list-item",
        "disp-quote",
        "statement",
        "note",
        "speech",
        "def",
        "disp-formula",
        "abbrev",
        "kwd",
    }
)

#: A process-local record of the last outbound request, for pacing only.
_LAST_REQUEST = [0.0]


# --------------------------------------------------------------------------- #
# Requests. One at a time, paced, retried, and never allowed to raise.
# --------------------------------------------------------------------------- #


def _pace() -> None:
    """Sleep so that no two outbound requests are closer than the interval."""
    wait = MIN_REQUEST_INTERVAL - (time.monotonic() - _LAST_REQUEST[0])
    if wait > 0:
        time.sleep(wait)
    _LAST_REQUEST[0] = time.monotonic()


def _get_json(url: str, *, mailto: str, timeout: int = REQUEST_TIMEOUT, tries: int = REQUEST_TRIES):
    """`_resolve`'s keyless JSON helper, paced. Returns ``(payload, error)``."""
    _pace()
    try:
        return _resolve._get_json(url, timeout=timeout, tries=tries, mailto=mailto)
    except Exception as exc:  # noqa: BLE001 - a network failure is data, never a crash
        return None, type(exc).__name__ + ": " + str(exc)[:160]


def _get_bytes(
    url: str,
    *,
    mailto: str,
    timeout: int = REQUEST_TIMEOUT,
    tries: int = REQUEST_TRIES,
    accept: str = "*/*",
    max_bytes: int = MAX_PDF_BYTES,
):
    """Fetch raw bytes with retries. Returns ``(payload, error, content_type)``."""
    last_error = ""
    headers = {"User-Agent": USER_AGENT % mailto, "Accept": accept}
    for attempt in range(tries):
        _pace()
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                content_type = (response.headers.get("Content-Type") or "")
                content_type = content_type.split(";")[0].strip().lower()
                # Bounded read: an endless or hostile response must not eat memory.
                payload = response.read(max_bytes + 1)
                if len(payload) > max_bytes:
                    return None, "response exceeds %d bytes" % max_bytes, content_type
                return payload, "", content_type
        except urllib.error.HTTPError as exc:
            last_error = "HTTP %s" % exc.code
            if exc.code in (400, 401, 403, 404, 410, 451):
                return None, last_error, ""
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            last_error = type(exc).__name__
        except ValueError as exc:
            # A malformed location from metadata (a space, a control character) must be
            # data like any other failed request, not an exception out of `acquire`.
            last_error = type(exc).__name__
        if attempt + 1 < tries:
            time.sleep(0.6 * (attempt + 1))
    return None, last_error or "unreachable", ""


def _allowed_url(url: str) -> bool:
    """Only http(s) locations are ever fetched; a metadata `file://` is refused."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _looks_like_pdf(payload: bytes, content_type: str) -> bool:
    if content_type and "pdf" in content_type:
        return True
    return payload[:1024].lstrip()[:4] == b"%PDF"


def _is_doi_resolver(url: str) -> bool:
    """True for a bare `doi.org` URL, which resolves to a landing page, not a file."""
    try:
        host = (urllib.parse.urlsplit(url).netloc or "").lower()
    except ValueError:
        return False
    host = host.split("@")[-1].split(":")[0]
    return host in ("doi.org", "dx.doi.org", "www.doi.org")


# --------------------------------------------------------------------------- #
# Cache. The only directory this module may write to is the one it is given.
# --------------------------------------------------------------------------- #


def _safe_name(value: str, *, limit: int = 120) -> str:
    """A deterministic, filesystem-safe cache name (zlib, not a hash library)."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "").strip("._-")
    if not cleaned:
        cleaned = "item"
    if len(cleaned) > limit:
        cleaned = cleaned[:limit] + "-%08x" % (zlib.crc32(value.encode("utf-8")) & 0xFFFFFFFF)
    return cleaned


def _cache_file(cache_dir, name: str):
    if cache_dir is None:
        return None
    return Path(cache_dir) / name


def _read_cached(path):
    if path is None:
        return None
    try:
        if path.is_symlink() or not path.is_file():
            return None
        return path.read_bytes()
    except OSError:
        return None


def _write_cached(path, payload: bytes) -> str:
    """Write into the given cache directory. Returns ``""`` or the reason it failed."""
    if path is None:
        return "no cache directory"
    try:
        if path.exists() and path.is_symlink():
            return "cache path is a symbolic link"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            handle.write(payload)
    except OSError as exc:
        return type(exc).__name__ + ": " + str(exc)[:160]
    return ""


# --------------------------------------------------------------------------- #
# XML. Europe PMC full text is JATS: strip the markup, keep the section titles.
# --------------------------------------------------------------------------- #


def _local(tag) -> str:
    return tag.rpartition("}")[2].lower() if isinstance(tag, str) else ""


def _text_of(element) -> str:
    """Whitespace-collapsed text of an element, without inline markup or footnotes.

    Every child contributes a hard separator, because JATS packs sibling block
    elements with no whitespace between them: without it `Summary` + `Background`
    becomes the single token ``SummaryBackground`` and a sentence boundary is lost.
    """
    pieces: list = []

    def walk(node, top: bool) -> None:
        if not top and _local(node.tag) in _DROP_INLINE:
            return
        if node.text:
            pieces.append(node.text)
        for child in list(node):
            pieces.append(" ")
            walk(child, False)
            if child.tail:
                pieces.append(" ")
                pieces.append(child.tail)

    walk(element, True)
    return " ".join("".join(pieces).split())


def _find_child(element, name: str):
    if element is None:
        return None
    for child in list(element):
        if _local(child.tag) == name:
            return child
    return None


def _find_descendant(element, name: str, depth: int = 6):
    if element is None or depth < 0:
        return None
    for child in list(element):
        if _local(child.tag) == name:
            return child
    for child in list(element):
        found = _find_descendant(child, name, depth - 1)
        if found is not None:
            return found
    return None


def _extract_fulltext(xml_bytes: bytes):
    """Flatten open-access JATS XML to ``(text, sections, article_title, error)``.

    ``sections`` is a list of ``{"title", "start", "end"}`` character ranges over the
    returned text; ranges nest for nested `<sec>` elements, and the deepest range
    containing an offset is the section a span belongs to.
    """
    # Expat expands internal entities, so a document that declares any is refused
    # rather than parsed: bounded input still deserves bounded expansion.
    if b"<!ENTITY" in xml_bytes:
        return "", [], "", "XML declares internal entities; refusing to parse it"
    try:
        root = ET.fromstring(xml_bytes)
    except (ET.ParseError, ValueError) as exc:
        return "", [], "", "XML could not be parsed: " + type(exc).__name__ + ": " + str(exc)[:160]

    parts: list = []
    sections: list = []
    cursor = [0]

    def emit(text: str) -> None:
        stripped = " ".join((text or "").split())
        if not stripped:
            return
        parts.append(stripped + "\n")
        cursor[0] += len(stripped) + 1

    def walk(element, skip_title=None) -> None:
        for child in list(element):
            tag = _local(child.tag)
            if tag == "sec":
                title_element = _find_child(child, "title")
                section_title = _text_of(title_element) if title_element is not None else ""
                start = cursor[0]
                if section_title:
                    emit(section_title)
                # Remember the index: a nested `sec` appends its own entry during the
                # walk, so `sections[-1]` afterwards is the child, not this section.
                position = len(sections)
                sections.append(
                    {"title": section_title or "unlabelled section", "start": start, "end": start}
                )
                walk(child, skip_title=title_element)
                sections[position]["end"] = cursor[0]
            elif tag == "title":
                if child is skip_title:
                    continue
                emit(_text_of(child))
            elif tag in _BLOCK_TAGS:
                emit(_text_of(child))
            else:
                walk(child)

    front = _find_child(root, "front")
    meta = _find_child(front, "article-meta") if front is not None else None
    article_title = ""
    title_group = _find_child(meta, "title-group") if meta is not None else None
    title_element = _find_child(title_group, "article-title") if title_group is not None else None
    if title_element is None:
        title_element = _find_descendant(meta, "article-title")
    if title_element is not None:
        article_title = _text_of(title_element)

    if meta is not None:
        for abstract in [child for child in list(meta) if _local(child.tag) == "abstract"]:
            if not _text_of(abstract):
                continue
            start = cursor[0]
            emit("Abstract")
            # Walk the abstract instead of flattening it, so its own sub-headings
            # ("Background", "Methods") become sections a locator can name.
            position = len(sections)
            sections.append({"title": "Abstract", "start": start, "end": start})
            walk(abstract)
            sections[position]["end"] = cursor[0]

    body = _find_child(root, "body")
    if body is not None:
        walk(body)

    return "".join(parts), sections, article_title, ""


def _clip(text: str, sections: list, limit: int):
    """Truncate evidence and drop or trim the section ranges that fall outside it."""
    if len(text) <= limit:
        return text, sections
    clipped = []
    for section in sections:
        if section.get("start", 0) >= limit:
            continue
        clipped.append(
            {
                "title": section.get("title", ""),
                "start": section.get("start", 0),
                "end": min(section.get("end", limit), limit),
            }
        )
    return text[:limit], clipped


def section_locator(source, offset: int = -1) -> str:
    """A section name for a character offset in tier-1 (Europe PMC XML) evidence.

    Tier-1 text has no pages, so `Source.locator()` cannot resolve a span; this is
    the locator the caller uses instead, and it is deliberately the bare section
    name -- the `evidence-and-limits.md` convention is `Results`, not `p.13`. The
    deepest section range containing the offset wins, which is what makes a nested
    subsection nameable.
    """
    sections = getattr(source, "evidence_sections", None) or []
    if not sections:
        return getattr(source, "evidence_locator", "") or "no locator"
    if offset < 0:
        return str(sections[0].get("title") or "unlabelled section")
    title = ""
    for section in sections:
        if section.get("start", 0) <= offset < section.get("end", 0):
            title = section.get("title") or title
    if not title:
        title = sections[-1].get("title") or "unlabelled section"
    return str(title)


# --------------------------------------------------------------------------- #
# Identity. The whole point: text may only be used for the work it actually is.
# --------------------------------------------------------------------------- #


def _claimed_title(source) -> str:
    return getattr(source, "title", "") or getattr(source, "title_claimed", "")


def _verify_identity(source, candidate: dict):
    """Confirm the acquired work is the cited work. Returns ``(ok, identity, detail)``.

    Strict by construction: an unmatched DOI, or a title that fails
    `_resolve.title_matches`, discards the text. When there is no DOI to compare and
    no title to match, identity cannot be confirmed and the text is discarded too.
    """
    source_doi = _common.normalize_doi(getattr(source, "doi", "") or "")
    acquired_doi = _common.normalize_doi(candidate.get("acquired_doi") or "")
    if source_doi:
        if not _common.valid_doi(acquired_doi):
            return False, "mismatch", "the acquired record carries no DOI to compare with cited DOI %s" % source_doi
        if acquired_doi != source_doi:
            return False, "mismatch", "acquired DOI %s does not match cited DOI %s" % (acquired_doi, source_doi)
    claimed_title = _claimed_title(source)
    acquired_title = candidate.get("acquired_title") or ""
    if claimed_title and acquired_title and not _resolve.title_matches(claimed_title, acquired_title):
        return False, "mismatch", "acquired title %r does not match the cited title %r" % (
            acquired_title[:120],
            claimed_title[:120],
        )
    if not source_doi and not (claimed_title and acquired_title):
        # Without a DOI, only a title comparison can confirm identity; with neither,
        # there is nothing to confirm it with, and text must not be attached.
        return False, "mismatch", "no DOI and no comparable title: identity cannot be confirmed"
    if source_doi:
        identity = "doi_matched"
        if claimed_title and acquired_title:
            detail = "DOI and title matched"
        elif acquired_title:
            detail = "DOI matched; the source carries no title to cross-check"
        elif claimed_title:
            detail = "DOI matched; the acquired record carried no title to cross-check"
        else:
            detail = "DOI matched"
    else:
        identity, detail = "title_matched", "title matched"
    return True, identity, detail


# --------------------------------------------------------------------------- #
# Tiers.
# --------------------------------------------------------------------------- #


def _try_api(source, *, mailto: str, cache_dir, state: dict):
    """Tier 1: Europe PMC open-access full text. Returns a candidate dict or None."""
    doi = _common.normalize_doi(getattr(source, "doi", "") or "")
    search_url = (
        EUROPEPMC_SEARCH
        + "?query="
        + urllib.parse.quote('DOI:"%s"' % doi)
        + "&resultType=core&format=json&pageSize=1"
    )
    if not _common.valid_doi(doi):
        source.record_attempt(
            "api", "europepmc/rest/search", "unavailable",
            "source has no well-formed DOI; an open-access lookup needs one",
        )
        return None

    payload, error = _get_json(search_url, mailto=mailto)
    if payload is None:
        source.record_attempt("api", search_url, "error", "Europe PMC search failed (%s)" % error)
        return None
    results = (payload.get("resultList") or {}).get("result") or []
    if not results:
        source.record_attempt("api", search_url, "unavailable", "Europe PMC holds no record for this DOI")
        return None

    record = results[0]
    pmcid = str(record.get("pmcid") or "").strip().upper()
    is_open = str(record.get("isOpenAccess") or "").strip().upper() == "Y"
    if not pmcid or not is_open:
        source.record_attempt(
            "api", search_url, "unavailable",
            "not open access in Europe PMC (pmcid=%s, isOpenAccess=%s)"
            % (pmcid or "none", record.get("isOpenAccess") or "unknown"),
        )
        return None

    # This work is now established open access. Remember the record so the optional
    # CLI tier may only ever read a source we have shown is open.
    state["oa_pmcid"] = pmcid
    state["oa_doi"] = _common.normalize_doi(str(record.get("doi") or doi))
    state["oa_title"] = str(record.get("title") or "")

    xml_url = EUROPEPMC_FULLTEXT % pmcid
    cache_path = _cache_file(cache_dir, "epmc-%s.xml" % _safe_name(pmcid, limit=60))
    note = ""
    xml_bytes = _read_cached(cache_path)
    if xml_bytes is None:
        xml_bytes, error, _content_type = _get_bytes(
            xml_url,
            mailto=mailto,
            accept="application/xml,text/xml;q=0.9,*/*;q=0.8",
            max_bytes=MAX_XML_BYTES,
        )
        if xml_bytes is None:
            source.record_attempt(
                "api", xml_url, "error",
                "open-access full text XML could not be fetched (%s)" % error,
            )
            return None
        write_error = _write_cached(cache_path, xml_bytes)
        if write_error:
            # The bytes are already legitimately in hand; failing to cache them is
            # disclosed in the successful attempt rather than discarding the text.
            note = "; cache write failed: " + write_error

    text, sections, article_title, parse_error = _extract_fulltext(xml_bytes)
    if parse_error or not text.strip():
        source.record_attempt(
            "api", xml_url, "error", parse_error or "full text XML contained no readable text"
        )
        return None

    limit = _bundle.MAX_EVIDENCE_CHARS
    text, sections = _clip(text, sections, limit)
    # Bare section name, matching the repository's "section-based (`Results`)" locator
    # convention. A span's own section needs `section_locator(source, offset)`.
    locator = str(sections[0]["title"]) if sections else "full text (no page numbers)"
    return {
        "text": text,
        "pages": [],
        "sections": sections,
        "locator": locator,
        "acquired_doi": _common.normalize_doi(str(record.get("doi") or doi)),
        "acquired_title": article_title or str(record.get("title") or ""),
        "origin": "europepmc:full_text",
        "acquisition_method": "api-fulltext",
        "evidence_method": "europepmc-jats",
        "endpoint": xml_url,
        "detail": "open-access full text XML (%s)%s" % (pmcid, note),
    }


def _try_pdf(source, *, mailto: str, cache_dir, state: dict):
    """Tier 2: open-access PDF via OpenAlex. Returns a candidate dict or None."""
    doi = _common.normalize_doi(getattr(source, "doi", "") or "")
    endpoint = OPENALEX + urllib.parse.quote(doi)
    if not _common.valid_doi(doi):
        source.record_attempt(
            "pdf", "api.openalex.org/works", "unavailable",
            "source has no well-formed DOI; an open-access lookup needs one",
        )
        return None
    if cache_dir is None:
        source.record_attempt(
            "pdf", endpoint, "unavailable",
            "no cache directory was supplied, and this module will not download a PDF "
            "anywhere else",
        )
        return None

    payload, error = _get_json(endpoint, mailto=mailto)
    if payload is None:
        source.record_attempt("pdf", endpoint, "error", "OpenAlex lookup failed (%s)" % error)
        return None

    best = payload.get("best_oa_location") or {}
    from_pdf_field = False
    url = ""
    if isinstance(best, dict) and best.get("pdf_url"):
        url, from_pdf_field = str(best["pdf_url"]), True
    if not url:
        open_access = payload.get("open_access") or {}
        if isinstance(open_access, dict):
            url = str(open_access.get("oa_url") or "")
    if not url:
        source.record_attempt(
            "pdf", endpoint, "unavailable", "OpenAlex reports no open-access PDF for this DOI"
        )
        return None
    if not _allowed_url(url):
        source.record_attempt(
            "pdf", endpoint, "unavailable",
            "OpenAlex returned a location that is not http(s); refusing to fetch it",
        )
        return None
    if not from_pdf_field and _is_doi_resolver(url):
        # `oa_url` is frequently just `https://doi.org/<doi>`: OpenAlex is saying the
        # paper is free to read *somewhere*, not that this URL is a file. Fetching it
        # can only follow a redirect into a publisher's landing page, so it is
        # recorded rather than crawled.
        source.record_attempt(
            "pdf", url, "unavailable",
            "OpenAlex's only open-access location is the DOI resolver, i.e. a landing "
            "page rather than a file; refusing to fetch a publisher's HTML",
        )
        return None
    state["oa_url"] = url

    cache_path = _cache_file(cache_dir, "oa-%s.pdf" % _safe_name(doi, limit=100))
    pdf_bytes = _read_cached(cache_path)
    note = ""
    if pdf_bytes is None:
        pdf_bytes, error, content_type = _get_bytes(
            url, mailto=mailto, accept="application/pdf,*/*;q=0.8", max_bytes=MAX_PDF_BYTES
        )
        if pdf_bytes is None:
            source.record_attempt(
                "pdf", url, "error", "open-access PDF could not be downloaded (%s)" % error
            )
            return None
        if not _looks_like_pdf(pdf_bytes, content_type):
            source.record_attempt(
                "pdf", url, "unavailable",
                "the open-access location did not return a PDF (content-type %s); "
                "refusing to read it as one" % (content_type or "unknown"),
            )
            return None
        write_error = _write_cached(cache_path, pdf_bytes)
        if write_error:
            source.record_attempt(
                "pdf", url, "error", "downloaded the PDF but could not cache it: " + write_error
            )
            return None
    else:
        note = "; read from cache"

    extracted = _pdftext.extract_pdf(cache_path)
    if not extracted.available:
        source.record_attempt(
            "pdf", url, "unavailable", "PDF text extraction refused: %s" % extracted.error
        )
        return None

    text = extracted.text[: _bundle.MAX_EVIDENCE_CHARS]
    return {
        "text": text,
        "pages": list(extracted.pages),
        "sections": [],
        "locator": "p.1",
        "file_path": str(cache_path),
        "acquired_doi": _common.normalize_doi(str(payload.get("doi") or doi)),
        "acquired_title": str(payload.get("display_name") or payload.get("title") or ""),
        "origin": "openalex:oa_pdf",
        "acquisition_method": "oa-pdf",
        "evidence_method": extracted.method,
        "endpoint": url,
        "detail": "open-access PDF via OpenAlex%s" % note,
    }


def _cli_refused(output: str) -> bool:
    lowered = output.strip().lower()
    return any(lowered.startswith(marker) for marker in _CLI_REFUSALS)


def _try_cli(source, *, cache_dir, state: dict):
    """Tier 3: the optional vendored `paper-search`. Returns a candidate dict or None."""
    pmcid = str(state.get("oa_pmcid") or "")
    executable = shutil.which(PAPER_SEARCH)
    if not executable:
        source.record_attempt(
            "cli", PAPER_SEARCH, "unavailable",
            "paper-search is not on PATH; it is an optional extra and is never "
            "installed or imported by this module",
        )
        return None
    if cache_dir is None:
        source.record_attempt(
            "cli", PAPER_SEARCH, "unavailable",
            "no cache directory was supplied, and the CLI writes by default to "
            "./downloads, so it is not run",
        )
        return None
    if not pmcid:
        source.record_attempt(
            "cli", PAPER_SEARCH, "unavailable",
            "no confirmed open-access record for this DOI was established, and this "
            "module will not use an aggregator to reach text it cannot show is open",
        )
        return None

    label = "paper-search read pmc %s" % pmcid
    cache_path = _cache_file(cache_dir, "cli-%s.txt" % _safe_name(pmcid, limit=60))
    cached = _read_cached(cache_path)
    if cached is not None:
        output = cached.decode("utf-8", "replace")
        note = "; read from cache"
    else:
        out_dir = Path(cache_dir) / "paper-search"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            source.record_attempt(
                "cli", label, "error",
                "could not create the CLI output directory: " + type(exc).__name__,
            )
            return None
        command = [executable, "read", "-o", str(out_dir), "pmc", pmcid]
        try:
            completed = subprocess.run(command, capture_output=True, timeout=CLI_TIMEOUT, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            source.record_attempt(
                "cli", label, "error", "paper-search could not be run: " + type(exc).__name__
            )
            return None
        output = (completed.stdout or b"").decode("utf-8", "replace").strip()
        stderr = (completed.stderr or b"").decode("utf-8", "replace").strip()
        if completed.returncode != 0 or _cli_refused(output) or len(output) < MIN_CLI_CHARS:
            detail = (output or stderr or "no output")[:200]
            source.record_attempt(
                "cli", label, "unavailable", "paper-search returned no readable text: " + detail
            )
            return None
        note = ""
        _write_cached(cache_path, output.encode("utf-8"))

    if len(output) < MIN_CLI_CHARS:
        source.record_attempt(
            "cli", label, "unavailable", "paper-search output was too short to be evidence"
        )
        return None

    return {
        "text": output[: _bundle.MAX_EVIDENCE_CHARS],
        "pages": [],
        "sections": [],
        "locator": "full text (no page numbers)",
        "acquired_doi": state.get("oa_doi") or "",
        "acquired_title": state.get("oa_title") or "",
        "origin": "paper-search:pmc",
        "acquisition_method": "cli-paper-search",
        "evidence_method": "paper-search",
        "endpoint": label,
        "detail": "paper-search read of the open-access PMCID %s%s" % (pmcid, note),
    }


# --------------------------------------------------------------------------- #
# Public interface.
# --------------------------------------------------------------------------- #


def _refresh_index(index, source) -> None:
    """Keep the caller's per-source evidence index in step with what was acquired."""
    if index is None:
        return
    try:
        import _evidence

        index[source.source_id] = _evidence.EvidenceIndex.from_source(source)
    except Exception as exc:  # noqa: BLE001 - indexing must never break acquisition
        try:
            source.warnings.append(
                "acquired text could not be indexed (%s); callers must rebuild the "
                "index before grading" % type(exc).__name__
            )
        except Exception:  # noqa: BLE001 - a duck-typed source may have no warnings
            pass


def _attach(source, candidate: dict, *, identity: str) -> None:
    """Commit verified acquired text to the source, with its provenance."""
    source.evidence_text = candidate["text"]
    source.evidence_pages = list(candidate.get("pages") or [])
    source.evidence_method = candidate["evidence_method"]
    source.evidence_availability = "full_text"
    source.evidence_strength = "primary"
    source.evidence_origin = candidate["origin"]
    source.acquisition_method = candidate["acquisition_method"]
    source.acquisition_endpoint = candidate["endpoint"][:MAX_ENDPOINT_CHARS]
    source.identity_check = identity
    source.acquired_at = _bundle._timestamp()
    source.evidence_locator = candidate["locator"]
    if candidate.get("sections"):
        # Not a `Source` field (that file is not ours to change); the caller reads it
        # through `section_locator()` / `acquisition_report()` for tier-1 locators.
        source.evidence_sections = list(candidate["sections"])
    if candidate.get("file_path"):
        source.file_path = candidate["file_path"]
    if identity == "doi_matched":
        source.verification_status = "verified"


def acquire(
    source,
    *,
    offline: bool = False,
    cache_dir=None,
    mailto: str = "",
    allow=("api", "pdf", "cli"),
    index: dict | None = None,
) -> bool:
    """Try to obtain readable evidence for one source.

    Returns True when the source's evidence was set to something checkable. Every
    attempt is recorded on ``source.attempts`` whether it worked or not, and every
    failure path returns False rather than raising. A programming error (an unknown
    tier name, a source that is not a `Source`) still raises.

    With ``offline=True`` this returns False without a request, a write, or a record.
    """
    if not hasattr(source, "record_attempt"):
        raise TypeError("acquire() expects a _bundle.Source-like object")

    allow_list = tuple(allow)
    unknown = sorted({tier for tier in allow_list if tier not in TIERS})
    if unknown:
        raise ValueError("unknown acquisition tier(s): " + ", ".join(unknown))

    # A source that already holds primary evidence has nothing to gain, and a source
    # that already holds a supplied file must not be second-guessed.
    if not _bundle._can_upgrade(source):
        return True

    if offline:
        # No request, no download, no record: the reproducible mode stays untouched.
        return False

    effective_mailto = mailto or DEFAULT_MAILTO
    state: dict = {"oa_pmcid": "", "oa_doi": "", "oa_title": "", "oa_url": ""}

    for tier in allow_list:
        if tier == "api":
            candidate = _try_api(source, mailto=effective_mailto, cache_dir=cache_dir, state=state)
        elif tier == "pdf":
            candidate = _try_pdf(source, mailto=effective_mailto, cache_dir=cache_dir, state=state)
        else:
            candidate = _try_cli(source, cache_dir=cache_dir, state=state)

        if candidate is None:
            continue

        ok, identity, detail = _verify_identity(source, candidate)
        if not ok:
            # The text never touched the source. Discarding it entirely, and saying
            # so, is the whole point of the identity check.
            source.identity_check = "mismatch"
            source.record_attempt(tier, candidate["endpoint"], "error", detail)
            return False

        _attach(source, candidate, identity=identity)
        source.record_attempt(tier, candidate["endpoint"], "returned", candidate["detail"])
        _refresh_index(index, source)
        return True

    return False


def acquisition_report(source) -> dict:
    """A summary of this source's acquisition attempts, for the provenance section."""
    attempts = [
        dict(attempt)
        for attempt in (getattr(source, "attempts", None) or [])
        if isinstance(attempt, dict)
    ]
    acquired = bool(getattr(source, "evidence_text", "")) and (
        getattr(source, "evidence_strength", "none") == "primary"
    )
    if not attempts:
        outcome = "not_attempted"
    elif getattr(source, "identity_check", "") == "mismatch":
        outcome = "identity_mismatch"
    elif acquired:
        outcome = "acquired"
    else:
        outcome = "failed"

    methods: list = []
    for attempt in attempts:
        method = attempt.get("method") or ""
        if method and method not in methods:
            methods.append(method)

    summary = "; ".join(
        "%s: %s%s"
        % (
            attempt.get("method") or "?",
            attempt.get("retrieval_status") or "?",
            (" (" + (attempt.get("detail") or "")[:80] + ")") if attempt.get("detail") else "",
        )
        for attempt in attempts
    ) or "no acquisition attempted"

    sections = [
        str(section.get("title") or "")
        for section in (getattr(source, "evidence_sections", None) or [])
        if isinstance(section, dict)
    ]
    evidence_text = getattr(source, "evidence_text", "") or ""
    return {
        "source_id": getattr(source, "source_id", ""),
        "doi": getattr(source, "doi", ""),
        "outcome": outcome,
        "attempted": bool(attempts),
        "methods": methods,
        "retrieval_status": getattr(source, "retrieval_status", "not_attempted"),
        "summary": summary,
        "identity_check": getattr(source, "identity_check", "not_attempted"),
        "evidence": {
            "availability": getattr(source, "evidence_availability", "unavailable"),
            "strength": getattr(source, "evidence_strength", "none"),
            "origin": getattr(source, "evidence_origin", ""),
            "method": getattr(source, "evidence_method", ""),
            "acquisition_method": getattr(source, "acquisition_method", "none"),
            "acquisition_endpoint": getattr(source, "acquisition_endpoint", ""),
            "locator": getattr(source, "evidence_locator", ""),
            "chars": len(evidence_text),
            "sections": sections,
            "acquired_at": getattr(source, "acquired_at", ""),
        },
        "attempts": attempts,
    }


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("usage: _acquire.py <doi> [--offline] [--cache-dir DIR]")
        raise SystemExit(2)
    doi = sys.argv[1]
    offline = "--offline" in sys.argv
    cache = None
    if "--cache-dir" in sys.argv:
        cache = sys.argv[sys.argv.index("--cache-dir") + 1]
    probe = _bundle.Source(source_id="S001", doi=doi, title_claimed="")
    acquired = acquire(probe, offline=offline, cache_dir=cache)
    print(json.dumps({"acquired": acquired, **acquisition_report(probe)}, indent=2, sort_keys=True))
