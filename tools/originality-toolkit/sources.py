"""Scholarly source adapters for the self-originality checker.

Standard library only (urllib), so this runs on a bare Python 3.9+ with no
pip installs.  Every adapter returns a list of Candidate dicts with a
uniform shape:

    {"source", "id", "title", "abstract", "year", "authors", "doi", "url"}

These adapters only *discover* candidate documents that may overlap a
passage.  Scoring the overlap happens in originality_check.py, so a
false candidate here is harmless: it simply scores low.

A transport failure is reported, never swallowed: each adapter returns
(status, candidates) where status is "ok", "empty" or "unavailable".
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

__all__ = ["search", "SOURCES"]

_EMAIL = (
    os.environ.get("OPENALEX_EMAIL")
    or os.environ.get("NCBI_EMAIL")
    or "researcher@example.org"
)
_TIMEOUT = 25


def _headers():
    return {
        "User-Agent": "OriginalityChecker/1.0 (self-originality pre-check; mailto:%s)" % _EMAIL,
        "Accept": "application/json, application/atom+xml, text/xml, */*",
    }


def _fetch(url, retries=2, backoff=1.5):
    """GET a URL and return decoded text. Raises on final failure."""
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=_headers())
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001 - report, never crash the run
            last = exc
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
    raise last


def _strip_tags(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(text))
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", text).strip()


def _cand(source, ident, title, abstract, year, authors, doi, url):
    return {
        "source": source,
        "id": ident or "",
        "title": _strip_tags(title),
        "abstract": _strip_tags(abstract),
        "year": year or "",
        "authors": authors or "",
        "doi": (doi or "").replace("https://doi.org/", ""),
        "url": url or "",
    }


def _openalex_abstract(inverted):
    """Rebuild an abstract from OpenAlex's inverted index (position -> terms)."""
    if not isinstance(inverted, dict) or not inverted:
        return ""
    positioned = []
    for word, positions in inverted.items():
        for pos in positions:
            positioned.append((pos, word))
    positioned.sort()
    return " ".join(word for _, word in positioned)


def _openalex(query, limit):
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(
        {"search": query, "per-page": limit, "mailto": _EMAIL}
    )
    payload = json.loads(_fetch(url))
    out = []
    for work in payload.get("results", []):
        authors = ", ".join(
            a.get("author", {}).get("display_name", "")
            for a in (work.get("authorships") or [])[:6]
            if a.get("author")
        )
        out.append(
            _cand(
                "openalex",
                work.get("id", "").rsplit("/", 1)[-1],
                work.get("title") or work.get("display_name"),
                _openalex_abstract(work.get("abstract_inverted_index")),
                work.get("publication_year"),
                authors,
                work.get("doi"),
                work.get("doi") or work.get("id") or "",
            )
        )
    return out


def _arxiv(query, limit):
    atom = "{http://www.w3.org/2005/Atom}"
    # arXiv's `all:"a b c"` is a *phrase* search (too strict -> empty). Build an
    # explicit AND of the most distinctive terms instead.
    terms = [t for t in query.split() if len(t) > 3][:6]
    search_query = " AND ".join("all:%s" % t for t in terms) or query
    url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {"search_query": search_query, "max_results": limit,
         "sortBy": "relevance"}
    )
    root = ET.fromstring(_fetch(url))
    out = []
    for entry in root.findall(atom + "entry"):
        authors = ", ".join(
            a.findtext(atom + "name", "") for a in entry.findall(atom + "author")[:6]
        )
        link = entry.findtext(atom + "id", "")
        doi_el = entry.find("{http://arxiv.org/schemas/atom}doi")
        out.append(
            _cand(
                "arxiv",
                link.rsplit("/", 1)[-1],
                entry.findtext(atom + "title"),
                entry.findtext(atom + "summary"),
                (entry.findtext(atom + "published") or "")[:4],
                authors,
                doi_el.text if doi_el is not None else "",
                link,
            )
        )
    return out


def _europepmc(query, limit):
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(
        {"query": query, "format": "json", "pageSize": limit, "resultType": "core"}
    )
    payload = json.loads(_fetch(url))
    out = []
    for item in payload.get("resultList", {}).get("result", []):
        out.append(
            _cand(
                "europepmc",
                item.get("id", ""),
                item.get("title"),
                item.get("abstractText"),
                item.get("pubYear"),
                item.get("authorString"),
                item.get("doi"),
                "https://europepmc.org/article/%s/%s"
                % (item.get("source", "MED"), item.get("id", "")),
            )
        )
    return out


def _semantic(query, limit):
    url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(
        {"query": query, "limit": limit,
         "fields": "title,abstract,year,authors,externalIds,url"}
    )
    payload = json.loads(_fetch(url))
    out = []
    for item in payload.get("data", []):
        ext = item.get("externalIds") or {}
        out.append(
            _cand(
                "semantic",
                item.get("paperId", ""),
                item.get("title"),
                item.get("abstract"),
                item.get("year"),
                ", ".join(a.get("name", "") for a in (item.get("authors") or [])[:6]),
                ext.get("DOI"),
                item.get("url") or "",
            )
        )
    return out


def _crossref(query, limit):
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(
        {"query.bibliographic": query, "rows": limit, "select":
         "DOI,title,abstract,issued,author,URL"}
    )
    payload = json.loads(_fetch(url))
    out = []
    for item in payload.get("message", {}).get("items", []):
        year = ""
        issued = item.get("issued", {}).get("date-parts") or [[]]
        if issued and issued[0]:
            year = issued[0][0]
        authors = ", ".join(
            ("%s %s" % (a.get("given", ""), a.get("family", ""))).strip()
            for a in (item.get("author") or [])[:6]
        )
        title = (item.get("title") or [""])[0]
        out.append(
            _cand(
                "crossref",
                item.get("DOI", ""),
                title,
                item.get("abstract"),
                year,
                authors,
                item.get("DOI"),
                item.get("URL") or ("https://doi.org/" + (item.get("DOI") or "")),
            )
        )
    return out



# name -> adapter. Order matters: it is the default query order.
SOURCES = {
    "openalex": _openalex,
    "crossref": _crossref,
    "arxiv": _arxiv,
    "europepmc": _europepmc,
    "semantic": _semantic,
}


def search(query, source, limit=5):
    """Run one adapter.

    Returns (status, candidates):
        "ok"          -> candidates found
        "empty"       -> the service answered, but had no match
        "unavailable" -> transport/lookup failure (never confused with empty)
    """
    adapter = SOURCES.get(source)
    if adapter is None:
        raise KeyError("unknown source: %s" % source)
    try:
        found = adapter(query, limit)
    except urllib.error.HTTPError as exc:
        return "unavailable", ["HTTP %s %s" % (exc.code, exc.reason)]
    except Exception as exc:  # noqa: BLE001 - surface the reason to the caller
        return "unavailable", ["%s: %s" % (type(exc).__name__, exc)]
    if not found:
        return "empty", []
    return "ok", found
