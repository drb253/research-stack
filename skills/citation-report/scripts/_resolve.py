"""Resolve a source identifier against public metadata authorities.

Keyless, best-effort, and never the only thing standing between a claim and a
verdict: with ``--offline`` this module is not called at all and every source is
graded on local evidence only. That is the reproducible mode, and it is the mode
the gate tests run in.

Authorities, in the order they are consulted:

* **Crossref** — DOI metadata, plus ``update-to`` / ``relation`` retraction signals.
* **OpenAlex** — the ``is_retracted`` flag and a second opinion on the title.
* **Europe PMC** — an abstract, which is often the only evidence available for a
  paywalled source. An abstract is weaker evidence than full text, and the report
  says so wherever it is used.

A failed lookup is recorded as ``unavailable``. It is never silently reported as
"no such paper": a network failure and a nonexistent DOI are different findings
and must not be conflated.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

import _common

USER_AGENT = "citation-report/1.0 (mailto:%s)"
DEFAULT_MAILTO = "research-stack@example.org"
CROSSREF = "https://api.crossref.org/works/"
OPENALEX = "https://api.openalex.org/works/doi:"
EUROPEPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
DATACITE = "https://api.datacite.org/dois/"

RETRACTION_TYPES = {"retraction", "retraction-of", "withdrawal"}
CONCERN_TYPES = {"expression_of_concern", "expression-of-concern"}
CORRECTION_TYPES = {"correction", "corrigendum", "erratum", "addendum"}


@dataclass
class Resolution:
    doi: str = ""
    found: bool = False
    title: str = ""
    authors: list = field(default_factory=list)
    year: str = ""
    container: str = ""
    type: str = ""
    retraction_status: str = "not_checked"
    retraction_notes: list = field(default_factory=list)
    abstract: str = ""
    #: Why an abstract lookup failed, when it did. Kept separate from `abstract == ""`,
    #: because "the API returned 503" and "this work has no abstract" are different
    #: findings and one of them is our problem rather than the document's.
    abstract_error: str = ""
    pmid: str = ""
    sources_consulted: list = field(default_factory=list)
    error: str = ""

    @property
    def verification_status(self) -> str:
        if self.found:
            return "verified"
        return "failed" if self.error else "unverified"

    def to_dict(self) -> dict:
        return {
            "doi": self.doi,
            "found": self.found,
            "title": self.title,
            "authors": list(self.authors),
            "year": self.year,
            "container": self.container,
            "type": self.type,
            "verification_status": self.verification_status,
            "retraction_status": self.retraction_status,
            "retraction_notes": list(self.retraction_notes),
            "abstract_chars": len(self.abstract),
            "abstract_error": self.abstract_error,
            "pmid": self.pmid,
            "sources_consulted": list(self.sources_consulted),
            "error": self.error,
        }


def _get_json(url: str, *, timeout: int = 25, tries: int = 3, mailto: str = DEFAULT_MAILTO):
    last_error = ""
    request_headers = {
        "User-Agent": USER_AGENT % mailto,
        "Accept": "application/json",
    }
    for attempt in range(tries):
        request = urllib.request.Request(url, headers=request_headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8", "replace")), ""
        except urllib.error.HTTPError as exc:
            last_error = "HTTP %s" % exc.code
            if exc.code in (400, 401, 403, 404):
                return None, last_error
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = type(exc).__name__
        except (json.JSONDecodeError, ValueError):
            last_error = "invalid JSON"
        if attempt + 1 < tries:
            time.sleep(0.6 * (attempt + 1))
    return None, last_error


def _year_from_parts(parts) -> str:
    try:
        return str(parts["date-parts"][0][0])
    except (KeyError, IndexError, TypeError):
        return ""


def crossref(doi: str, mailto: str = DEFAULT_MAILTO):
    payload, error = _get_json(CROSSREF + urllib.parse.quote(doi), mailto=mailto)
    if payload is None:
        return None, error
    return payload.get("message", {}), ""


def crossref_signals(message: dict):
    """Retraction / correction signals from a Crossref work record."""
    status = "clear"
    notes: list = []
    for relation_name in ("update-to", "updated-by", "relation"):
        relation = message.get(relation_name)
        if relation_name == "relation" and isinstance(relation, dict):
            entries = []
            for key, values in relation.items():
                for value in values if isinstance(values, list) else [values]:
                    entries.append((key, value))
        elif isinstance(relation, list):
            entries = [(relation_name, value) for value in relation]
        else:
            entries = []
        for label, value in entries:
            if not isinstance(value, dict):
                continue
            kind = (value.get("type") or label or "").lower().replace(" ", "_")
            if kind in RETRACTION_TYPES:
                status = "retracted"
                notes.append("Crossref %s: %s" % (label, value.get("DOI") or value.get("id") or ""))
            elif kind in CONCERN_TYPES and status != "retracted":
                status = "expression_of_concern"
                notes.append("Crossref %s" % kind)
            elif kind in CORRECTION_TYPES and status == "clear":
                status = "corrected"
                notes.append("Crossref %s" % kind)
    if (message.get("type") or "").lower() in RETRACTION_TYPES:
        status = "retracted"
        notes.append("Crossref type=%s" % message.get("type"))
    return status, notes


def openalex(doi: str, mailto: str = DEFAULT_MAILTO):
    payload, error = _get_json(OPENALEX + urllib.parse.quote(doi), mailto=mailto)
    if payload is None:
        return None, error
    return payload, ""


def europepmc_abstract(*, doi: str = "", pmid: str = "", mailto: str = DEFAULT_MAILTO):
    query = "DOI:%s" % doi if doi else "EXT_ID:%s" % pmid
    url = (
        EUROPEPMC
        + "?query="
        + urllib.parse.quote(query)
        + "&resultType=core&format=json&pageSize=1"
    )
    payload, error = _get_json(url, mailto=mailto)
    if payload is None:
        return None, error
    results = (payload.get("resultList") or {}).get("result") or []
    if not results:
        return None, "no Europe PMC record"
    record = results[0]
    abstract = record.get("abstractText") or ""
    abstract = re.sub(r"<[^>]+>", " ", abstract)
    abstract = re.sub(r"\s{2,}", " ", abstract).strip()
    return {
        "abstract": abstract,
        "pmid": str(record.get("pmid") or pmid or ""),
        "title": record.get("title") or "",
        "year": str(record.get("pubYear") or ""),
        "container": record.get("journalTitle") or "",
    }, ""


def resolve(doi: str, *, mailto: str = DEFAULT_MAILTO, want_abstract: bool = True) -> Resolution:
    """Resolve one DOI, recording what each authority said and what failed."""
    normalized = _common.normalize_doi(doi)
    result = Resolution(doi=normalized)
    if not _common.valid_doi(normalized):
        result.error = "not a well-formed DOI"
        result.found = False
        return result

    message, error = crossref(normalized, mailto)
    if message:
        result.found = True
        result.sources_consulted.append("crossref")
        result.title = (message.get("title") or [""])[0]
        result.container = (message.get("container-title") or [""])[0]
        result.type = message.get("type") or ""
        result.year = _year_from_parts(message.get("issued") or {}) or _year_from_parts(
            message.get("published") or {}
        )
        result.authors = [
            " ".join(part for part in (author.get("given"), author.get("family")) if part).strip()
            for author in (message.get("author") or [])[:20]
        ]
        status, notes = crossref_signals(message)
        result.retraction_status = status
        result.retraction_notes.extend(notes)
    elif error:
        result.error = "crossref: " + error

    openalex_record, openalex_error = openalex(normalized, mailto)
    if openalex_record:
        result.sources_consulted.append("openalex")
        result.retraction_status = (
            "retracted" if openalex_record.get("is_retracted") else result.retraction_status
        )
        if openalex_record.get("is_retracted"):
            result.retraction_notes.append("OpenAlex is_retracted")
        if not result.title:
            result.title = openalex_record.get("title") or ""
            result.found = True
        if not result.year:
            result.year = str(openalex_record.get("publication_year") or "")
    elif openalex_error and not result.error:
        result.error = "openalex: " + openalex_error

    if want_abstract and result.found:
        abstract_record, abstract_error = europepmc_abstract(doi=normalized, mailto=mailto)
        if abstract_record:
            result.sources_consulted.append("europepmc")
            result.abstract = abstract_record["abstract"]
            result.pmid = abstract_record["pmid"] or result.pmid
        elif abstract_error:
            result.abstract_error = abstract_error
            result.retraction_notes.append("abstract unavailable (%s)" % abstract_error)

    if result.retraction_status == "not_checked" and result.found:
        result.retraction_status = "clear"
    return result


def title_matches(claimed: str, actual: str, threshold: float = 0.72) -> bool:
    """Loose title agreement, for flagging a DOI that resolves to another paper."""
    left = set(_common.normalize_title(claimed).split())
    right = set(_common.normalize_title(actual).split())
    if not left or not right:
        return False
    overlap = len(left & right)
    return overlap / max(1, min(len(left), len(right))) >= threshold


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("usage: _resolve.py <doi> [--offline]")
        raise SystemExit(2)
    if "--offline" in sys.argv:
        print(json.dumps({"offline": True, "note": "no network call made"}, indent=2))
        raise SystemExit(0)
    print(json.dumps(resolve(sys.argv[1]).to_dict(), indent=2, sort_keys=True))
