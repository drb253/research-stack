"""Citation export for paper-search-mcp.

PATCHED-BY-paper-search-mcp-patches: Tier 8 -- verified citation export.

Nothing in the stock package exported citations, so a write-up had to be
assembled by hand from result metadata.  This module turns DOIs into
**DOI-verified** BibTeX / RIS / plain-text citations, fetched from Crossref --
the DOI registration agency -- rather than from whatever the search source
happened to return.

Accuracy rules, learned from this install's other fixes:

  * Every citation is built from a Crossref lookup of the DOI itself, so the
    author list, journal, year, volume and pages come from the authoritative
    record rather than a scraped summary.
  * Retraction state is checked for each entry (OpenAlex ``is_retracted`` plus
    Crossref notices).  A retracted work is marked in the output -- ``note =
    {RETRACTED}`` in BibTeX -- because citing a retracted paper silently is the
    most damaging citation error there is.
  * A citation whose metadata could not be fetched is *reported*, never emitted
    half-formed: a missing entry must not look like a clean reference list.

Free and keyless: Crossref's polite pool only wants a contact address.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from .config import get_env
from .retraction import check_retraction, normalize_doi
from .source_status import SourceUnavailable, request_json

logger = logging.getLogger(__name__)

CROSSREF_WORK_URL = "https://api.crossref.org/works"

_BIBTEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
}

#: Crossref work type -> BibTeX entry type.
_BIBTEX_TYPES = {
    "journal-article": "article",
    "proceedings-article": "inproceedings",
    "book-chapter": "incollection",
    "book": "book",
    "monograph": "book",
    "reference-entry": "incollection",
    "dissertation": "phdthesis",
    "report": "techreport",
    "posted-content": "misc",
    "dataset": "misc",
}


def _escape_bibtex(value: Any) -> str:
    """Escape a value for a BibTeX field (order matters: backslash first)."""
    text = "" if value is None else str(value)
    for char, replacement in _BIBTEX_ESCAPES.items():
        text = text.replace(char, replacement)
    return " ".join(text.split())


def _first(value: Any) -> str:
    """First element of a Crossref list-valued field, as text."""
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else ""
    return "" if value is None else str(value)


def _year_of(message: Dict[str, Any]) -> str:
    """Publication year from whichever Crossref date field is populated."""
    for key in ("issued", "published-print", "published-online", "created"):
        parts = ((message.get(key) or {}).get("date-parts") or [[]])
        if parts and parts[0] and parts[0][0]:
            return str(parts[0][0])
    return ""


def _authors_of(message: Dict[str, Any]) -> List[Dict[str, str]]:
    """Author list as [{'family','given'}]; organisations keep only 'family'."""
    authors: List[Dict[str, str]] = []
    for entry in message.get("author") or []:
        if not isinstance(entry, dict):
            continue
        family = str(entry.get("family") or entry.get("name") or "").strip()
        given = str(entry.get("given") or "").strip()
        if family or given:
            authors.append({"family": family, "given": given})
    return authors


def _author_text(authors: List[Dict[str, str]]) -> str:
    """'Bird TD, Smith J' style author string."""
    parts = []
    for author in authors:
        name = " ".join(p for p in (author.get("family"), author.get("given")) if p)
        if name:
            parts.append(name)
    return ", ".join(parts)


def cite_key(authors: List[Dict[str, str]], year: str, title: str,
             taken: Optional[set] = None) -> str:
    """A deterministic BibTeX key: 'Bird2024', disambiguated 'Bird2024a'.

    Deterministic so the same paper always produces the same key, and unique
    within one export so two 2024 Bird papers cannot collide.
    """
    first = (authors[0].get("family") if authors else "") or ""
    stem = re.sub(r"[^A-Za-z]", "", first) or "Anon"
    key = f"{stem}{year or 'n.d.'}"
    if taken is None:
        return key
    candidate = key
    suffix = ord("a")
    while candidate in taken:
        candidate = f"{key}{chr(suffix)}"
        suffix += 1
    taken.add(candidate)
    return candidate


def _session() -> requests.Session:
    """A session in Crossref's polite pool (a contact address is all it wants)."""
    session = requests.Session()
    mailto = (
        get_env("CROSSREF_EMAIL", "")
        or get_env("OPENALEX_EMAIL", "")
        or get_env("UNPAYWALL_EMAIL", "")
    )
    contact = f" (mailto:{mailto})" if mailto else ""
    session.headers.update({
        "User-Agent": f"paper-search-mcp/0.1.4{contact}",
        "Accept": "application/json",
    })
    return session


def fetch_metadata(session: requests.Session, doi: str, timeout: float = 25) -> Dict[str, Any]:
    """The authoritative Crossref record for a DOI.

    Crossref is the DOI registration agency, so this is the source of record for
    authors, journal, year, volume and pages -- not a search summary.
    """
    doi = normalize_doi(doi)
    if not doi:
        raise ValueError("Invalid doi: doi is empty")

    payload = request_json(
        session, f"{CROSSREF_WORK_URL}/{doi}", "crossref", timeout=timeout
    )
    message = (payload or {}).get("message")
    if not isinstance(message, dict) or not message:
        raise SourceUnavailable("crossref", f"no Crossref record for {doi}")
    return message


def build_entry(
    doi: str,
    message: Dict[str, Any],
    check_retractions: bool = True,
    session: Optional[requests.Session] = None,
) -> Dict[str, Any]:
    """One citation entry, annotated with retraction state.

    ``retracted`` is True/False only when the check actually ran; when it could
    not run, ``retraction_checked`` is False and ``retraction_error`` explains
    why, so an unverified entry is never presented as a clean one.
    """
    authors = _authors_of(message)
    entry: Dict[str, Any] = {
        "doi": str(message.get("DOI") or normalize_doi(doi)),
        "title": _first(message.get("title")),
        "authors": authors,
        "author_text": _author_text(authors),
        "journal": _first(message.get("container-title")),
        "year": _year_of(message),
        "volume": str(message.get("volume") or ""),
        "issue": str(message.get("issue") or ""),
        "pages": str(message.get("page") or ""),
        "publisher": str(message.get("publisher") or ""),
        "type": str(message.get("type") or ""),
        "url": str(message.get("URL") or f"https://doi.org/{doi}"),
        "cited_by": message.get("is-referenced-by-count"),
        "retracted": None,
        "retraction_checked": False,
    }

    if check_retractions:
        try:
            verdict = check_retraction(entry["doi"], entry["title"])
            entry["retracted"] = bool(verdict.get("is_retracted"))
            entry["retraction_checked"] = True
            entry["retraction_evidence"] = verdict
        except Exception as exc:
            # A failed check must not read as "not retracted".
            entry["retraction_checked"] = False
            entry["retraction_error"] = f"{type(exc).__name__}: {exc}"[:160]
    return entry


def _bibtex_entry(entry: Dict[str, Any], key: str) -> List[str]:
    """One BibTeX record.  The title is brace-protected to keep capitalisation."""
    btype = _BIBTEX_TYPES.get(entry["type"], "misc")
    fields: List[Any] = []

    if entry["authors"]:
        fields.append((
            "author",
            " and ".join(
                " ".join(p for p in (a.get("family"), a.get("given")) if p)
                for a in entry["authors"]
            ),
        ))
    fields.append(("title", entry["title"]))

    container_field = {
        "article": "journal",
        "inproceedings": "booktitle",
        "incollection": "booktitle",
    }.get(btype)
    if container_field and entry["journal"]:
        fields.append((container_field, entry["journal"]))
    elif entry["journal"]:
        fields.append(("howpublished", entry["journal"]))

    if btype in ("book", "incollection", "phdthesis", "techreport") and entry["publisher"]:
        fields.append(("publisher", entry["publisher"]))

    fields.append(("year", entry["year"]))
    if entry["volume"]:
        fields.append(("volume", entry["volume"]))
    if entry["issue"]:
        fields.append(("number", entry["issue"]))
    if entry["pages"]:
        fields.append(("pages", entry["pages"]))
    fields.append(("doi", entry["doi"]))
    fields.append(("url", entry["url"]))
    if entry.get("retracted"):
        # Makes a retracted work impossible to cite by accident.
        fields.append(("note", "RETRACTED"))

    lines = ["@%s{%s," % (btype, key)]
    for name, value in fields:
        if not value:
            continue
        text = _escape_bibtex(value)
        if name == "title":
            text = "{" + text + "}"
        lines.append("  %s = {%s}," % (name, text))
    lines.append("}")
    return lines


def _ris_entry(entry: Dict[str, Any]) -> List[str]:
    """One RIS record."""
    ris_type = {
        "journal-article": "JOUR",
        "proceedings-article": "CPAPER",
        "book-chapter": "CHAP",
        "book": "BOOK",
        "dissertation": "THES",
        "report": "RPRT",
        "posted-content": "UNPB",
    }.get(entry["type"], "GEN")

    lines = ["TY  - %s" % ris_type]
    for author in entry["authors"]:
        name = " ".join(p for p in (author.get("family"), author.get("given")) if p)
        if name:
            lines.append("AU  - %s" % name)
    lines.append("TI  - %s" % entry["title"])
    for tag, value in (
        ("JO", entry["journal"]),
        ("PY", entry["year"]),
        ("VL", entry["volume"]),
        ("IS", entry["issue"]),
        ("SP", entry["pages"]),
        ("PB", entry["publisher"]),
        ("DO", entry["doi"]),
        ("UR", entry["url"]),
    ):
        if value:
            lines.append("%s  - %s" % (tag, value))
    if entry.get("retracted"):
        lines.append("N1  - RETRACTED")
    lines.append("ER  - ")
    return lines


def _text_citation(entry: Dict[str, Any]) -> str:
    """A plain-text citation (authors, year, title, venue, volume/pages, DOI)."""
    parts: List[str] = []
    if entry["author_text"]:
        parts.append(entry["author_text"])
    if entry["year"]:
        parts.append("(%s)." % entry["year"])
    if entry["title"]:
        parts.append(entry["title"].rstrip(".") + ".")
    if entry["journal"]:
        parts.append(entry["journal"].rstrip(".") + ".")
    if entry["volume"]:
        location = entry["volume"]
        if entry["issue"]:
            location += "(%s)" % entry["issue"]
        if entry["pages"]:
            location += ", " + entry["pages"]
        parts.append(location + ".")
    if entry["doi"]:
        parts.append("https://doi.org/%s" % entry["doi"])
    text = " ".join(parts)
    return "[RETRACTED] " + text if entry.get("retracted") else text


def format_citations(
    dois: Any,
    fmt: str = "bibtex",
    check_retractions: bool = True,
    timeout: float = 25.0,
) -> Dict[str, Any]:
    """DOI-verified citations in BibTeX, RIS or plain text.

    Each DOI is resolved at Crossref -- the registration agency -- so the
    rendered citation reflects the authoritative record rather than a search
    summary.  DOIs that cannot be resolved land in ``unavailable`` instead of
    being dropped silently, and every entry carries ``retracted`` /
    ``retraction_checked`` so an unverified entry is never presented as clean.
    """
    if isinstance(dois, str):
        candidates = re.split(r"[,\s;]+", dois)
    else:
        candidates = [str(d) for d in (dois or [])]

    wanted = [normalize_doi(c) for c in candidates if str(c).strip()]
    wanted = [d for d in wanted if d]
    if not wanted:
        raise ValueError("No DOIs supplied")

    session = _session()
    entries: List[Dict[str, Any]] = []
    unavailable: Dict[str, str] = {}
    taken: set = set()

    for doi in dict.fromkeys(wanted):
        try:
            message = fetch_metadata(session, doi, timeout=timeout)
            entry = build_entry(
                doi, message,
                check_retractions=check_retractions, session=session,
            )
            entry["cite_key"] = cite_key(
                entry["authors"], entry["year"], entry["title"], taken
            )
            entries.append(entry)
        except SourceUnavailable as exc:
            unavailable[doi] = str(exc)[:180]
        except Exception as exc:
            unavailable[doi] = f"{type(exc).__name__}: {exc}"[:180]

    fmt = (fmt or "bibtex").strip().lower()
    if fmt in ("bibtex", "bib"):
        body = "\n\n".join(
            "\n".join(_bibtex_entry(e, e["cite_key"])) for e in entries
        )
    elif fmt == "ris":
        body = "\n\n".join("\n".join(_ris_entry(e)) for e in entries)
    else:
        body = "\n".join(
            "%s  %s" % (e["cite_key"], _text_citation(e)) for e in entries
        )

    retracted = [e["doi"] for e in entries if e.get("retracted")]
    unverified = [e["doi"] for e in entries if not e.get("retraction_checked")]
    result: Dict[str, Any] = {
        "format": fmt,
        "count": len(entries),
        "citations": body,
        "entries": entries,
        "retracted": retracted,
        "retraction_unverified": unverified,
        "unavailable": unavailable,
    }
    if retracted:
        result["warning"] = (
            "%d cited work(s) are RETRACTED: %s"
            % (len(retracted), ", ".join(retracted))
        )
    return result


_TAG_RE = re.compile(r"<[^>]+>")

#: Crossref's JATS abstract carries its own "Abstract" heading; drop it so the
#: text does not read as though the paper starts with the word "Abstract".
_ABSTRACT_LABEL_RE = re.compile(r"^\s*abstract[\s:.\u2013-]*", re.IGNORECASE)


def _clean_abstract(value: Any) -> str:
    """Crossref abstracts arrive wrapped in JATS markup; strip it to text."""
    if not value:
        return ""
    text = " ".join(_TAG_RE.sub(" ", str(value)).split())
    return _ABSTRACT_LABEL_RE.sub("", text)


def paper_dict(doi: str, message: Dict[str, Any]) -> Dict[str, Any]:
    """A Crossref record in the shared paper schema (dict form).

    Used by DOI-shaped query routing so a resolved DOI looks like any other
    search hit to the caller.
    """
    authors = _authors_of(message)
    year = _year_of(message)
    published = None
    if year.isdigit():
        try:
            published = datetime(int(year), 1, 1).isoformat()
        except ValueError:
            published = None

    journal = _first(message.get("container-title"))
    record_type = str(message.get("type") or "")
    return {
        "paper_id": str(message.get("DOI") or doi),
        "title": _first(message.get("title")),
        "authors": [
            " ".join(p for p in (a.get("family"), a.get("given")) if p)
            for a in authors
        ],
        "abstract": _clean_abstract(message.get("abstract")),
        "doi": str(message.get("DOI") or doi),
        "published_date": published,
        "updated_date": published,
        "url": str(message.get("URL") or f"https://doi.org/{doi}"),
        "pdf_url": "",
        "source": "crossref",
        "categories": [c for c in (journal, record_type) if c],
        "keywords": [],
        "citations": message.get("is-referenced-by-count") or 0,
        "extra": {
            "resolved_by": "doi-query-routing",
            "journal": journal,
            "publisher": str(message.get("publisher") or ""),
            "type": record_type,
            "volume": str(message.get("volume") or ""),
            "issue": str(message.get("issue") or ""),
            "pages": str(message.get("page") or ""),
        },
    }


def resolve_doi_metadata(doi: str, timeout: float = 25.0) -> Dict[str, Any]:
    """The Crossref record for one DOI, using its own polite session.

    A public wrapper so a caller that needs a single record does not have to
    manage a session -- used by DOI-shaped query routing in ``search_papers``.
    """
    return fetch_metadata(_session(), doi, timeout=timeout)
