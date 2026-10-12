#!/usr/bin/env python3
"""citecheck - resolve, verify, and format references from authoritative sources.

Stdlib only (no third-party packages, no API keys). Metadata comes from
Crossref (api.crossref.org); title search and retraction status come from
OpenAlex (api.openalex.org); arXiv records come from export.arxiv.org.

Usage:
  citecheck.py resolve <doi|pmid|arxiv-id|title> [--format STYLE] [--json]
  citecheck.py verify  <refs.bib|identifiers.txt> [--format text|json]
  citecheck.py format  [--format STYLE] [--file rec.json]   # normalize MCP/JSON metadata
  citecheck.py bib-from-draft <draft> [--format STYLE] [--out refs.bib] [--json] [--ids-only]
  citecheck.py duplicates <draft> [--json]                  # repeat / inconsistent in-text citations

Styles: apa (default), mla, chicago, vancouver, ieee, harvard, bibtex, json.
"""
import argparse
import ast
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

UA = "citecheck/1.0 (mailto:citecheck@example.org)"
CROSSREF = "https://api.crossref.org/works/"
OPENALEX = "https://api.openalex.org/works/"
ARXIV = "http://export.arxiv.org/api/query"

STOP = {"a", "an", "the", "on", "of", "in", "to", "and", "for", "with", "at", "by", "from"}


def _open(req, timeout):
    # TLS verification is never disabled. An earlier version caught SSLError and
    # retried with check_hostname=False / CERT_NONE, which would let a MITM
    # substitute fabricated Crossref/OpenAlex metadata -- defeating the purpose of
    # a citation-verification tool. An SSLError now propagates and is reported as
    # a resolution/retraction-check failure by the caller.
    return urllib.request.urlopen(req, timeout=timeout)


def http_json(url, params=None, timeout=25):
    if params:
        sep = "&" if "?" in url else "?"
        url = url + sep + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with _open(req, timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def http_text(url, params=None, timeout=25):
    if params:
        sep = "&" if "?" in url else "?"
        url = url + sep + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with _open(req, timeout) as r:
        return r.read().decode("utf-8")


def classify(ident):
    s = ident.strip()
    if re.match(r"^10\.\d{4,9}/\S+$", s) or s.lower().startswith("doi:"):
        return "doi"
    if re.match(r"^arxiv:\s*\d{4}\.\d{4,5}", s, re.I) or re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", s):
        return "arxiv"
    if re.fullmatch(r"\d{7,9}", s):
        return "pmid"
    return "title"


def blank():
    return {"source": None, "type": None, "title": None, "authors": [],
            "container": None, "publisher": None, "year": None, "volume": None,
            "issue": None, "pages": None, "doi": None, "pmid": None,
            "url": None, "is_retracted": False, "retraction_source": None}


def clean_doi(s):
    s = s.strip()
    s = re.sub(r"^https?://(dx\.)?doi\.org/", "", s, flags=re.I)
    s = re.sub(r"^doi:\s*", "", s, flags=re.I)
    return s.strip()


def _cr_authors(lst):
    out = []
    for a in lst:
        if a.get("family") or a.get("given"):
            out.append({"family": (a.get("family") or "").strip(),
                        "given": (a.get("given") or "").strip()})
        elif a.get("name"):
            out.append({"name": a["name"].strip()})
    return out


def _cr_year(m):
    for k in ("issued", "published-print", "published-online", "published", "created"):
        dp = (m.get(k) or {}).get("date-parts") or []
        if dp and dp[0] and dp[0][0]:
            return dp[0][0]
    return None


def crossref_record(doi):
    m = http_json(CROSSREF + urllib.parse.quote(clean_doi(doi)))["message"]
    rec = blank()
    rec["source"] = "crossref"
    rec["type"] = m.get("type")
    t = m.get("title") or []
    rec["title"] = t[0] if t else None
    rec["authors"] = _cr_authors(m.get("author") or [])
    ct = m.get("container-title") or []
    rec["container"] = ct[0] if ct else None
    rec["publisher"] = m.get("publisher")
    rec["year"] = _cr_year(m)
    rec["volume"] = m.get("volume")
    rec["issue"] = m.get("issue")
    rec["pages"] = m.get("page")
    rec["doi"] = m.get("DOI") or clean_doi(doi)
    rec["url"] = m.get("URL")
    return rec


def _split_name(name):
    name = (name or "").strip()
    if not name:
        return {"name": ""}
    parts = name.split()
    if len(parts) == 1:
        return {"family": parts[0], "given": ""}
    return {"family": parts[-1], "given": " ".join(parts[:-1])}


def _oa_record(w):
    rec = blank()
    rec["source"] = "openalex"
    rec["type"] = w.get("type")
    rec["title"] = w.get("title")
    rec["authors"] = [_split_name((a.get("author") or {}).get("display_name", ""))
                      for a in (w.get("authorships") or [])]
    src = ((w.get("primary_location") or {}).get("source") or {})
    rec["container"] = src.get("display_name")
    rec["publisher"] = src.get("host_organization_name")
    rec["year"] = w.get("publication_year")
    biblio = w.get("biblio") or {}
    rec["volume"] = biblio.get("volume")
    rec["issue"] = biblio.get("issue")
    fp, lp = biblio.get("first_page"), biblio.get("last_page")
    rec["pages"] = "-".join([p for p in (fp, lp) if p]) or None
    doi = w.get("doi") or ""
    rec["doi"] = re.sub(r"^https?://doi\.org/", "", doi) or None
    ids = w.get("ids") or {}
    pm = ids.get("pmid") or ""
    rec["pmid"] = re.sub(r".*/", "", pm) or None
    rec["url"] = (w.get("primary_location") or {}).get("landing_page_url")
    rec["is_retracted"] = bool(w.get("is_retracted"))
    if rec["is_retracted"]:
        rec["retraction_source"] = "openalex"
    return rec


def openalex_by_doi(doi):
    return _oa_record(http_json(OPENALEX + "doi:" + urllib.parse.quote(clean_doi(doi))))


def openalex_by_pmid(pmid):
    return _oa_record(http_json(OPENALEX + "pmid:" + str(pmid)))


def openalex_by_title(title):
    data = http_json(OPENALEX.rstrip("/"),
                     {"filter": "title.search:" + title, "per-page": 5})
    results = data.get("results") or []
    if not results:
        return None
    want = re.sub(r"\W+", " ", title).strip().lower()

    def score(w):
        t = re.sub(r"\W+", " ", (w.get("title") or "")).strip().lower()
        return (1 if t == want else 0, w.get("cited_by_count") or 0)

    return _oa_record(max(results, key=score))


def arxiv_record(ident):
    aid = re.sub(r"^arxiv:\s*", "", ident.strip(), flags=re.I)
    xml = http_text(ARXIV, {"id_list": aid})
    root = ET.fromstring(xml)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entry = root.find("a:entry", ns)
    if entry is None:
        return None
    rec = blank()
    rec["source"] = "arxiv"
    rec["type"] = "preprint"
    rec["title"] = " ".join((entry.findtext("a:title", "", ns) or "").split())
    rec["authors"] = [_split_name(a.findtext("a:name", "", ns)) for a in entry.findall("a:author", ns)]
    pub = entry.findtext("a:published", "", ns) or ""
    rec["year"] = int(pub[:4]) if pub[:4].isdigit() else None
    rec["doi"] = "10.48550/arXiv." + aid
    rec["url"] = "https://arxiv.org/abs/" + aid
    return rec


def enrich_retraction(rec):
    if rec.get("doi") and rec.get("retraction_source") is None:
        try:
            w = http_json(OPENALEX + "doi:" + urllib.parse.quote(rec["doi"]))
            if w.get("is_retracted"):
                rec["is_retracted"] = True
                rec["retraction_source"] = "openalex"
        except Exception as exc:
            # Do NOT swallow this. A failed retraction lookup must not look like
            # "checked and clean": record it so callers can tell the difference
            # and warn instead of silently clearing a retracted paper.
            rec["retraction_check_failed"] = "%s: %s" % (type(exc).__name__, exc)
    return rec


class Unreachable(RuntimeError):
    """The registry could not be queried.

    eval.md C3 already required this distinction -- "If the check could not run (offline,
    or a source `unavailable`), say so - do not imply 'clean'" -- but `resolve()` caught
    every exception into `None`, so an identifier nobody could ask about was indistinguishable
    from one the registry answered 404 for, and both were dropped from the emitted list.
    """


_MISS = object()  # the registry answered, and does not hold this identifier


def _attempt(fn, ident):
    """One registry lookup.

    Returns the record, `_MISS` when the registry answered and does not hold it, or raises
    `Unreachable` when the registry could not answer. The three outcomes are kept apart so
    no caller can collapse them.
    """
    try:
        return fn(ident)
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 410):
            return _MISS          # a fact about the identifier
        raise Unreachable("HTTP %s from the registry for %s" % (exc.code, ident))
    except urllib.error.URLError as exc:
        raise Unreachable("could not reach the registry for %s: %s" % (ident, exc.reason or exc))
    except (TimeoutError, OSError) as exc:
        raise Unreachable("could not reach the registry for %s: %s" % (ident, exc))
    except json.JSONDecodeError as exc:
        raise Unreachable("the registry returned a response that is not JSON: %s" % exc)
    except Exception as exc:  # noqa: BLE001 - unknown failures mean "could not determine"
        raise Unreachable("lookup failed for %s: %s: %s" % (ident, type(exc).__name__, exc))


def resolve(ident):
    """Resolve one identifier.

    Returns the record, or `None` when every registry that could answer was reached and
    none holds it. Raises `Unreachable` when a registry could not be queried, because then
    we cannot say the identifier does not exist.
    """
    kind = classify(ident)
    if kind == "doi":
        try:
            rec = _attempt(crossref_record, ident)
        except Unreachable:
            # The DOI may be registered outside Crossref; the alternative agency is the
            # deciding lookup, so a Crossref outage alone must not become a verdict.
            rec = _MISS
        if rec is _MISS:
            rec = _attempt(openalex_by_doi, ident)
    elif kind == "pmid":
        rec = _attempt(openalex_by_pmid, ident)
    elif kind == "arxiv":
        rec = _attempt(arxiv_record, ident)
    else:
        rec = _attempt(openalex_by_title, ident)
    if rec is _MISS:
        return None
    return enrich_retraction(rec)


def resolve_many(idents, workers=8):
    """Resolve identifiers concurrently.

    Returns `(cache, unreachable)`. `cache[i]` is the record or `None` when the registries
    were reached and none holds it; `unreachable[i]` holds the reason when the registries
    could not be queried. Callers must not read the second as the first.
    """
    uniq, seen = [], set()
    for i in idents:
        if i not in seen:
            seen.add(i)
            uniq.append(i)
    cache, unreachable = {}, {}

    def one(i):
        try:
            return i, resolve(i), None
        except Unreachable as exc:
            return i, None, str(exc)
        except Exception as exc:  # noqa: BLE001
            return i, None, "%s: %s" % (type(exc).__name__, exc)

    if uniq:
        n = max(1, min(workers, len(uniq)))
        with ThreadPoolExecutor(max_workers=n) as ex:
            for i, rec, err in ex.map(one, uniq):
                cache[i] = rec
                if rec is None and err is not None:
                    unreachable[i] = err
    return cache, unreachable


def _authors_any(a):
    """Accept authors as: list of {family,given} / list of str / 'A; B' / 'A and B' / 'Family, Given'."""
    out = []
    if not a:
        return out
    if isinstance(a, str):
        s = a.strip()
        if ";" in s or re.search(r"\band\b", s):
            for p in re.split(r"\s*;\s*|\s+and\s+", s):
                if p.strip():
                    out.append(_split_name(p.strip()))
        elif "," in s:
            fam, _, giv = s.partition(",")
            out.append({"family": fam.strip(), "given": giv.strip()})
        elif s:
            out.append(_split_name(s))
        return out
    if isinstance(a, list):
        for item in a:
            if isinstance(item, dict):
                if item.get("family") or item.get("given"):
                    out.append({"family": (item.get("family") or "").strip(),
                                "given": (item.get("given") or "").strip()})
                elif item.get("name"):
                    out.append(_split_name(item["name"]))
            elif isinstance(item, str) and item.strip():
                out.append(_split_name(item))
    return out


def _parse_extra(extra):
    if isinstance(extra, dict):
        return extra
    if isinstance(extra, str) and extra.strip().startswith("{"):
        try:
            return ast.literal_eval(extra)
        except Exception:
            return {}
    return {}


def normalize_any(obj):
    """Normalize a record from the MCP tools (paper-search / ncbi) or from this script."""
    rec = blank()
    rec["title"] = obj.get("title")
    rec["authors"] = _authors_any(obj.get("authors") or obj.get("author"))
    ex = _parse_extra(obj.get("extra"))
    rec["container"] = (obj.get("container") or obj.get("journal")
                        or obj.get("container_title") or ex.get("container_title"))
    rec["publisher"] = obj.get("publisher") or ex.get("publisher")
    yr = obj.get("year") or obj.get("publication_year")
    if not yr:
        m = re.search(r"(1[6-9]\d\d|20\d\d)", str(obj.get("published_date")
                                                 or obj.get("publication_date") or ""))
        yr = int(m.group(1)) if m else None
    rec["year"] = yr
    rec["volume"] = obj.get("volume") or ex.get("volume")
    rec["issue"] = obj.get("issue") or obj.get("number") or ex.get("issue")
    rec["pages"] = obj.get("pages") or obj.get("page") or ex.get("page")
    rec["doi"] = clean_doi(obj["doi"]) if obj.get("doi") else None
    rec["type"] = obj.get("type") or "journal-article"
    rec["url"] = obj.get("url") or obj.get("pdf_url") or None
    rec["source"] = obj.get("source")
    rec["is_retracted"] = bool(obj.get("is_retracted") or obj.get("retracted"))
    return rec


def initials(given, dotted=True):
    if not given:
        return ""
    out = []
    for p in re.split(r"[\s\-]+", given.strip()):
        if p:
            out.append(p[0].upper() + ("." if dotted else ""))
    return " ".join(out)


def fam_given(a):
    if "family" in a:
        return a.get("family", ""), a.get("given", "")
    name = a.get("name", "")
    parts = name.split()
    if len(parts) <= 1:
        return name, ""
    return parts[-1], " ".join(parts[:-1])


def _dot(s):
    s = (s or "").rstrip()
    return s if s.endswith(".") else s + "."


def apa_authors(authors):
    items = [(fam_given(a)[0] + ", " + initials(fam_given(a)[1])).strip().rstrip(",") for a in authors]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) <= 20:
        return ", ".join(items[:-1]) + ", & " + items[-1]
    return ", ".join(items[:19]) + ", ... " + items[-1]


def fmt_apa(r):
    parts = []
    au = apa_authors(r["authors"])
    if au:
        parts.append(_dot(au))
    parts.append("(%s)." % (r.get("year") or "n.d."))
    parts.append((r.get("title") or "").rstrip(".") + ".")
    if r.get("container"):
        src = r["container"]
        if r.get("volume"):
            src += ", " + str(r["volume"])
            if r.get("issue"):
                src += "(%s)" % r["issue"]
        if r.get("pages"):
            src += ", " + str(r["pages"])
        parts.append(src + ".")
    elif r.get("publisher"):
        parts.append(r["publisher"] + ".")
    if r.get("doi"):
        parts.append("https://doi.org/" + r["doi"])
    return " ".join(parts)


def mla_authors(authors):
    def first(a):
        f, g = fam_given(a)
        return (f + ", " + g).strip().rstrip(",")

    def rest(a):
        f, g = fam_given(a)
        return (g + " " + f).strip()

    if not authors:
        return ""
    if len(authors) == 1:
        return first(authors[0])
    if len(authors) == 2:
        return first(authors[0]) + ", and " + rest(authors[1])
    return first(authors[0]) + ", et al."


def fmt_mla(r):
    out = ""
    au = mla_authors(r["authors"])
    if au:
        out += _dot(au) + " "
    out += '"' + (r.get("title") or "").rstrip(".") + '." '
    if r.get("container"):
        out += r["container"]
        bits = []
        if r.get("volume"):
            bits.append("vol. " + str(r["volume"]))
        if r.get("issue"):
            bits.append("no. " + str(r["issue"]))
        if r.get("year"):
            bits.append(str(r["year"]))
        if r.get("pages"):
            bits.append("pp. " + str(r["pages"]))
        if bits:
            out += ", " + ", ".join(bits)
        out += "."
    if r.get("doi"):
        out += " https://doi.org/" + r["doi"] + "."
    elif r.get("url"):
        out += " " + r["url"] + "."
    return out.strip()


def chicago_authors(authors):
    def first(a):
        f, g = fam_given(a)
        return (f + ", " + g).strip().rstrip(",")

    def rest(a):
        f, g = fam_given(a)
        return (g + " " + f).strip()

    if not authors:
        return ""
    if len(authors) == 1:
        return first(authors[0])
    if len(authors) == 2:
        return first(authors[0]) + ", and " + rest(authors[1])
    if len(authors) <= 10:
        return first(authors[0]) + ", " + ", ".join(rest(a) for a in authors[1:-1]) + ", and " + rest(authors[-1])
    return first(authors[0]) + " et al."


def fmt_chicago(r):
    out = ""
    au = chicago_authors(r["authors"])
    if au:
        out += _dot(au) + " "
    out += '"' + (r.get("title") or "").rstrip(".") + '." '
    if r.get("container"):
        out += r["container"]
        if r.get("volume"):
            out += " " + str(r["volume"])
            if r.get("issue"):
                out += ", no. " + str(r["issue"])
        if r.get("year"):
            out += " (%s)" % r["year"]
        if r.get("pages"):
            out += ": " + str(r["pages"])
        out += "."
    if r.get("doi"):
        out += " https://doi.org/" + r["doi"] + "."
    return out.strip()


def vanc_authors(authors):
    items = [(fam_given(a)[0] + " " + initials(fam_given(a)[1], dotted=False)).strip() for a in authors]
    if len(items) > 6:
        items = items[:6] + ["et al."]
    return ", ".join(items)


def fmt_vancouver(r, n=None):
    out = (str(n) + ". ") if n is not None else ""
    au = vanc_authors(r["authors"])
    if au:
        out += _dot(au) + " "
    out += (r.get("title") or "").rstrip(".") + ". "
    if r.get("container"):
        out += r["container"] + ". "
    if r.get("year"):
        out += str(r["year"])
        if r.get("volume"):
            out += ";" + str(r["volume"])
            if r.get("issue"):
                out += "(%s)" % r["issue"]
        if r.get("pages"):
            out += ":" + str(r["pages"])
        out += "."
    if r.get("doi"):
        out += " doi:" + r["doi"]
    return out.strip()


def ieee_authors(authors):
    items = [(initials(fam_given(a)[1]) + " " + fam_given(a)[0]).strip() for a in authors]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) <= 6:
        return ", ".join(items[:-1]) + ", and " + items[-1]
    return items[0] + " et al."


def fmt_ieee(r, n=None):
    out = ("[" + str(n) + "] ") if n is not None else ""
    au = ieee_authors(r["authors"])
    if au:
        out += au + ", "
    out += '"' + (r.get("title") or "").rstrip(".") + '," '
    if r.get("container"):
        out += r["container"]
        if r.get("volume"):
            out += ", vol. " + str(r["volume"])
        if r.get("issue"):
            out += ", no. " + str(r["issue"])
        if r.get("pages"):
            out += ", pp. " + str(r["pages"])
        if r.get("year"):
            out += ", " + str(r["year"])
        out += "."
    if r.get("doi"):
        out += " doi: " + r["doi"] + "."
    return out.strip()


def fmt_harvard(r):
    out = apa_authors(r["authors"])
    out += " (%s)" % (r.get("year") or "n.d.")
    out += " '" + (r.get("title") or "").rstrip(".") + "'"
    if r.get("container"):
        out += ", " + r["container"]
        if r.get("volume"):
            out += ", " + str(r["volume"])
            if r.get("issue"):
                out += "(%s)" % r["issue"]
        if r.get("pages"):
            out += ", pp. " + str(r["pages"])
    out += "."
    if r.get("doi"):
        out += " doi: " + r["doi"] + "."
    return out.strip()


def cite_key(r):
    fam = "anon"
    if r["authors"]:
        f, _ = fam_given(r["authors"][0])
        fam = re.sub(r"[^A-Za-z]", "", f).lower() or "anon"
    yr = str(r.get("year") or "nd")
    word = "untitled"
    for w in re.split(r"\W+", r.get("title") or ""):
        if w and w.isalpha() and len(w) > 2 and w.lower() not in STOP:
            word = w.lower()
            break
    return fam + yr + word


def _bib_escape(s):
    return (s or "").replace("{", "(").replace("}", ")")


def fmt_bibtex(r, key=None):
    key = key or cite_key(r)
    btype = "article"
    t = r.get("type") or ""
    if t in ("book", "monograph"):
        btype = "book"
    elif t in ("proceedings-article", "paper-conference"):
        btype = "inproceedings"
    elif t in ("posted-content", "preprint"):
        btype = "misc"
    au = " and ".join(
        (fam_given(a)[0] + ", " + fam_given(a)[1]).strip().rstrip(",")
        if "family" in a else a.get("name", "")
        for a in r["authors"])
    fields = []
    if au:
        fields.append(("author", au))
    if r.get("title"):
        fields.append(("title", _bib_escape(r["title"])))
    if r.get("container"):
        fields.append(("journal" if btype == "article" else "booktitle", _bib_escape(r["container"])))
    if r.get("year"):
        fields.append(("year", str(r["year"])))
    if r.get("volume"):
        fields.append(("volume", str(r["volume"])))
    if r.get("issue"):
        fields.append(("number", str(r["issue"])))
    if r.get("pages"):
        fields.append(("pages", str(r["pages"])))
    if r.get("publisher"):
        fields.append(("publisher", _bib_escape(r["publisher"])))
    if r.get("doi"):
        fields.append(("doi", r["doi"]))
    if r.get("url"):
        fields.append(("url", r["url"]))
    if r.get("is_retracted"):
        fields.append(("note", "RETRACTED"))
    body = ",\n".join("  %s = {%s}" % (k, v) for k, v in fields)
    return "@%s{%s,\n%s\n}" % (btype, key, body)


STYLES = {
    "apa": lambda r, n=None: fmt_apa(r),
    "mla": lambda r, n=None: fmt_mla(r),
    "chicago": lambda r, n=None: fmt_chicago(r),
    "vancouver": fmt_vancouver,
    "ieee": fmt_ieee,
    "harvard": lambda r, n=None: fmt_harvard(r),
    "bibtex": lambda r, n=None: fmt_bibtex(r),
}


def format_rec(r, style, n=None):
    style = (style or "apa").lower()
    if style == "json":
        return json.dumps(r, indent=2, ensure_ascii=False)
    fn = STYLES.get(style)
    if fn is None:
        raise SystemExit("Unknown style %r. Use: %s" % (style, ", ".join(sorted(STYLES))))
    return re.sub(r"[ \t]{2,}", " ", fn(r, n)).strip()


def parse_bib(text):
    entries = []
    i = 0
    n = len(text)
    while True:
        at = text.find("@", i)
        if at == -1:
            break
        brace = text.find("{", at)
        if brace == -1:
            break
        depth = 0
        j = brace
        while j < n:
            c = text[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        entries.append(text[brace + 1:j])
        i = j + 1
    out = []
    for body in entries:
        m = re.match(r"\s*([^,]+),\s*(.*)", body, re.S)
        if not m:
            continue
        fields = {"_key": m.group(1).strip()}
        for fm in re.finditer(r"(\w+)\s*=\s*(\{[^{}]*\}|[^,\n]+)\s*,?", m.group(2)):
            val = fm.group(2).strip().strip(",").strip()
            if val.startswith("{") and val.endswith("}"):
                val = val[1:-1]
            fields[fm.group(1).lower()] = val.strip()
        out.append(fields)
    return out


def verify_file(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    is_bib = path.lower().endswith(".bib") or ("@" in text[:200] and "{" in text[:200])
    items = []
    if is_bib:
        for e in parse_bib(text):
            items.append((e.get("_key"), e.get("doi") or e.get("title"), e))
    else:
        for line in text.splitlines():
            line = line.strip().strip(",").strip()
            if line and not line.startswith("#"):
                items.append((None, line, None))
    cache, unreachable = resolve_many([it[1] for it in items if it[1]])
    results = []
    for key, ident, e in items:
        if not ident:
            results.append({"key": key, "ident": ident, "record": None,
                            "error": "no DOI or title to check", "entry": e,
                            "unreachable": None})
            continue
        rec = cache.get(ident)
        results.append({"key": key, "ident": ident, "record": rec,
                        "error": None if rec is not None else "not resolved (Crossref/OpenAlex)",
                        # Kept apart from `error`: this one is not a finding about the entry.
                        "unreachable": unreachable.get(ident),
                        "entry": e})
    return results


def _norm(s):
    return re.sub(r"\W+", " ", (s or "")).strip().lower()


def report_verify(results, style="text"):
    lines = []
    problems = 0
    unchecked = 0
    for idx, res in enumerate(results, 1):
        rec, e, notes = res["record"], res["entry"], []
        tag = "OK"
        if res.get("unreachable"):
            # The registry could not be asked. NOT a FAIL: a failure would assert the entry
            # is bad, and nothing was checked. Counted separately and returned separately.
            tag = "UNCHECKED"
            notes.append("registry could not be queried: %s" % res["unreachable"])
        elif res["error"]:
            tag, _ = "FAIL", notes.append(res["error"])
        elif rec is None:
            tag, _ = "FAIL", notes.append("not found in Crossref/OpenAlex")
        else:
            if rec.get("is_retracted"):
                tag = "RETRACTED"
                notes.append("source is retracted (%s)" % (rec.get("retraction_source") or "?"))
            if rec.get("retraction_check_failed"):
                notes.append("retraction status NOT verified (%s)"
                             % rec["retraction_check_failed"])
                tag = "WARN" if tag == "OK" else tag
            if e:
                ey = (e.get("year") or "")[:4]
                if ey and rec.get("year") and ey != str(rec["year"]):
                    notes.append("year: bib=%s actual=%s" % (ey, rec["year"]))
                    tag = "WARN" if tag == "OK" else tag
                bt, rt = _norm(e.get("title")), _norm(rec.get("title"))
                if bt and rt and bt[:40] != rt[:40]:
                    notes.append("title differs from record")
                    tag = "WARN" if tag == "OK" else tag
        if tag == "UNCHECKED":
            unchecked += 1
        elif tag != "OK":
            problems += 1
        if style == "json":
            lines.append(json.dumps({"index": idx, "key": res["key"], "status": tag,
                                     "ident": res["ident"], "notes": notes,
                                     "resolved": rec}, indent=2, ensure_ascii=False))
        else:
            label = res["key"] or res["ident"] or "(unknown)"
            line = "[%s] #%d %s" % (tag, idx, label)
            if notes:
                line += "  -- " + "; ".join(notes)
            lines.append(line)
    if style != "json":
        lines.append("")
        lines.append("%d entr(ies) checked, %d need attention (FAIL/RETRACTED/WARN), "
                     "%d could not be checked (the registry was unreachable)."
                     % (len(results), problems, unchecked))
        if unchecked:
            lines.append("The %d uncheckable entr(ies) are an INPUT GAP, not a finding: "
                         "nothing was verified about them either way." % unchecked)
    return "\n".join(lines), problems, unchecked


DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.I)
ARXIV_RE = re.compile(r"arxiv[:\s]+(\d{4}\.\d{4,5})(?:v\d+)?", re.I)
PMID_RE = re.compile(r"pmid[:\s#]*(\d{7,9})\b", re.I)
_TRAIL = ".,;:\"'>}]\\"


def _trim_doi(tok):
    tok = tok.strip()
    while tok and tok[-1] in _TRAIL:
        tok = tok[:-1]
    while tok and tok[-1] == ")" and tok.count(")") > tok.count("("):
        tok = tok[:-1]
    while tok and tok[-1] in _TRAIL:
        tok = tok[:-1]
    return tok


def find_identifiers(text, extra=True):
    """Ordered, de-duplicated (kind, identifier) hits in a draft: DOIs, plus arXiv ids and PMIDs."""
    hits = []
    for m in DOI_RE.finditer(text):
        doi = _trim_doi(m.group(0))
        if doi:
            hits.append((m.start(), "doi", doi))
    if extra:
        for m in ARXIV_RE.finditer(text):
            hits.append((m.start(), "arxiv", m.group(1)))
        for m in PMID_RE.finditer(text):
            hits.append((m.start(), "pmid", m.group(1)))
    hits.sort(key=lambda h: h[0])
    found, seen = [], set()
    for _, kind, ident in hits:
        key = (kind, ident.lower())
        if key not in seen:
            seen.add(key)
            found.append((kind, ident))
    return found


def placeholder_entry(ident, style="apa", number=None, tag="UNRESOLVED", note=None):
    """The line a reference list must carry for an identifier that produced no entry.

    Dropping the entry makes the list look complete: the reader cannot see that a cited work
    is missing from it, and eval.md C2 calls that a hard error. A placeholder exactly where
    the entry would have been means the omission travels with the artifact -- including when
    the reason for the omission is that the registry could not be reached, because an empty
    list is the most misleading artifact of all.
    """
    if note is None:
        note = ("not resolvable via Crossref/OpenAlex/arXiv - verify by hand or remove the "
                "citation")
    if style == "json":
        return json.dumps({tag.lower().replace(" ", "_"): ident, "note": note},
                          ensure_ascii=False)
    if style == "bibtex":
        return "%% [%s] %s - %s" % (tag, ident, note)
    prefix = "[%d] " % number if number else ""
    return "%s[%s] %s - %s" % (prefix, tag, ident, note)


def unresolved_entry(ident, style="apa", number=None):
    return placeholder_entry(ident, style, number)


def not_checked_line(ident, reason, style="apa", number=None):
    return placeholder_entry(
        ident, style, number, tag="NOT CHECKED",
        note=("the registry could not be reached (%s), so this citation was not checked "
              "either way" % reason))


def not_checked_entry(ident, reason):
    """The worklist row for an identifier the registries could not be asked about."""
    return {"identifier": ident, "reason": reason,
            "action": "restore network access and re-run; a registry that could not be "
                      "reached is not a citation that does not exist"}


def bib_from_draft(path, style="apa", out=None, as_json=False, extra=True, ids_only=False,
                   allow_unresolved=False, allow_insufficient=False):
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    found = find_identifiers(text, extra=extra)
    if ids_only:
        for kind, ident in found:
            if kind == "doi":
                print(ident)
        return 0
    cache, unreachable = resolve_many([ident for _, ident in found])
    refs, unresolved, retracted, seen_works = [], [], [], set()
    dupes = 0
    for kind, ident in found:
        rec = cache.get(ident)
        if rec is None:
            # Only an identifier the registries answered about may be called unresolved.
            if ident not in unreachable:
                unresolved.append(ident)
            continue
        wkey = (rec.get("doi") or "").lower() or _norm(rec.get("title"))
        if wkey and wkey in seen_works:
            dupes += 1
            continue
        if wkey:
            seen_works.add(wkey)
        rec["_ident"] = ident
        refs.append(rec)
        if rec.get("is_retracted"):
            retracted.append(rec.get("doi") or ident)
    numbered = style in ("vancouver", "ieee")
    # The list is built in citation order and the placeholders take their slot, so the
    # numbering of the resolved entries does not silently renumber around the gap.
    lines, n = [], 0
    for rec in refs:
        n += 1
        lines.append(format_rec(rec, style, n if numbered else None))
    for ident in unresolved:
        n += 1
        lines.append(unresolved_entry(ident, style, n if numbered else None))
    not_checked = [not_checked_entry(ident, unreachable[ident])
                   for _, ident in found if ident in unreachable]
    for row in not_checked:
        n += 1
        lines.append(not_checked_line(row["identifier"], row["reason"], style,
                                      n if numbered else None))
    has_findings = bool(unresolved or retracted)
    status = ("insufficient_evidence" if not_checked
              else ("fail" if has_findings else "pass"))
    if as_json:
        print(json.dumps({"source": path, "found": len(found), "resolved": len(refs),
                          "duplicates_merged": dupes, "unresolved": unresolved,
                          "retracted": retracted, "not_checked": not_checked,
                          "status": status,
                          "references": refs, "entries": lines},
                         indent=2, ensure_ascii=False))
        return _bib_exit(has_findings, bool(not_checked), allow_unresolved, allow_insufficient)
    print("\n".join(lines))
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    kinds = {}
    for k, _ in found:
        kinds[k] = kinds.get(k, 0) + 1
    print("\n[i] Scanned %s: found %d unique identifier(s) [%s]; resolved %d, duplicates merged %d, "
          "unresolved %d, retracted %d, not checked %d."
          % (path, len(found), ", ".join("%d %s" % (v, k) for k, v in kinds.items()),
             len(refs), dupes, len(unresolved), len(retracted), len(not_checked)),
          file=sys.stderr)
    if out:
        kept = []
        if unresolved:
            kept.append("%d [UNRESOLVED]" % len(unresolved))
        if not_checked:
            kept.append("%d [NOT CHECKED]" % len(not_checked))
        print("[i] Reference list written to %s (%s)"
              % (out, " and ".join(kept) if kept else "no placeholder entries"), file=sys.stderr)
    for u in unresolved:
        print("[!] UNRESOLVED: %s" % u, file=sys.stderr)
    for r in retracted:
        print("[!] RETRACTED: %s" % r, file=sys.stderr)
    if not_checked:
        print("[!] NOT CHECKED - %d identifier(s) the registries could not be asked about."
              % len(not_checked), file=sys.stderr)
        print("    These are absent from unresolved[] and are NOT evidence that the "
              "citations are wrong:", file=sys.stderr)
        for row in not_checked:
            print("      %s  %s" % (row["identifier"], row["reason"][:100]), file=sys.stderr)
        print("    status: insufficient_evidence (an input gap, not a finding about the "
              "reference list)", file=sys.stderr)
        if not allow_insufficient:
            print("    the reference list above is complete for every identifier that could "
                  "be checked; re-run when the registry is reachable", file=sys.stderr)
    return _bib_exit(has_findings, bool(not_checked), allow_unresolved, allow_insufficient)


def _bib_exit(has_findings, has_gaps, allow_unresolved, allow_insufficient):
    """Exit code for the bibliography modes, keeping the two conditions apart.

    An unresolved identifier is a finding and fails (2). A registry we could not reach is an
    input gap and outranks it (3). Each has its own documented opt-out, and the input gap is
    NOT waived by the finding's waiver: there is nothing to waive, because no check was made.
    The finding in the artifact is what matters most -- the placeholder is written either
    way, so waiving changes the exit code and never the list.
    """
    if has_gaps and not allow_insufficient:
        return 3
    if has_findings and not allow_unresolved:
        return 2
    return 0


CITE_PAREN = re.compile(r"\(([^()]{0,90}?)(\d{4})([a-z])?\)")
CITE_NARR = re.compile(
    r"\b([A-Z][A-Za-z'\u2019\-]+)\s*"
    r"(?:et\s+al\.?|&\s*[A-Z][A-Za-z'\u2019\-]+|and\s+[A-Z][A-Za-z'\u2019\-]+)?\s*"
    r"\((\d{4})([a-z])?\)")


def find_citations(text):
    """Return (surface, key, position) for in-text author-date citations."""
    out = []
    for m in CITE_PAREN.finditer(text):
        fm = re.search(r"[A-Z][A-Za-z'\u2019\-]+", m.group(1) or "")
        if not fm:
            continue
        out.append((m.group(0).strip(), (fm.group(0).lower(), m.group(2) + (m.group(3) or "")), m.start()))
    for m in CITE_NARR.finditer(text):
        out.append((m.group(0).strip(), (m.group(1).lower(), m.group(2) + (m.group(3) or "")), m.start()))
    return out


def duplicate_report(path):
    """Group in-text citations by (first-author, year). Flag inconsistent wording and repeats."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    groups = {}
    for surface, key, _ in find_citations(text):
        g = groups.setdefault(key, {"forms": [], "count": 0})
        g["count"] += 1
        if surface not in g["forms"]:
            g["forms"].append(surface)
    findings = []
    for key, g in groups.items():
        if len(g["forms"]) > 1:
            findings.append(("INCONSISTENT", key, sorted(g["forms"]), g["count"]))
        elif g["count"] > 1:
            findings.append(("REPEATED", key, sorted(g["forms"]), g["count"]))
    findings.sort(key=lambda f: (f[0] != "INCONSISTENT", -f[3], f[1]))
    return findings


def print_duplicates(path, as_json=False):
    findings = duplicate_report(path)
    if as_json:
        print(json.dumps({"source": path, "findings": [
            {"type": t, "work": "%s %s" % (k[0], k[1]), "forms": forms, "cited": c}
            for t, k, forms, c in findings]}, indent=2, ensure_ascii=False))
        return 0
    if not findings:
        print("No repeated or inconsistently-worded in-text citations found.", file=sys.stderr)
        return 0
    for t, k, forms, c in findings:
        print("[%s] (%s, %s) - %d form(s), cited %dx: %s"
              % (t, k[0].capitalize(), k[1], len(forms), c, " | ".join(forms)))
    inc = sum(1 for t, _, _, _ in findings if t == "INCONSISTENT")
    print("\n%d work(s) with inconsistent wording; %d finding(s) total."
          % (inc, len(findings)), file=sys.stderr)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Resolve, verify and format references via Crossref/OpenAlex (stdlib only).")
    p.add_argument("--version", action="version", version="citecheck 1.0")
    p.add_argument("--self-test", action="store_true",
                   help="offline check of the resolution/exit routing; no network")
    sub = p.add_subparsers(dest="cmd")

    pr = sub.add_parser("resolve", help="resolve one identifier to a formatted reference")
    pr.add_argument("identifier", help="DOI, PMID, arXiv id, or a title to search")
    pr.add_argument("--format", "--style", dest="style", default="apa",
                    help="apa|mla|chicago|vancouver|ieee|harvard|bibtex|json")
    pr.add_argument("--json", action="store_true", help="print the normalized record as JSON")

    pv = sub.add_parser("verify", help="check a .bib file or a list of identifiers")
    pv.add_argument("file", help="path to refs.bib or a text file of identifiers (one per line)")
    pv.add_argument("--format", dest="style", default="text", choices=["text", "json"])

    pf = sub.add_parser("format", help="format record(s) from JSON (stdin or --file)")
    pf.add_argument("--format", "--style", dest="style", default="apa",
                    help="apa|mla|chicago|vancouver|ieee|harvard|bibtex|json")
    pf.add_argument("--file", help="read JSON from this file instead of stdin")

    pb = sub.add_parser("bib-from-draft", aliases=["scan"],
                        help="scan a draft for DOIs/arXiv/PMIDs and emit a reference list")
    pb.add_argument("file", help="path to the draft (markdown, text, .tex, .bib, ...)")
    pb.add_argument("--format", "--style", dest="style", default="apa",
                    help="apa|mla|chicago|vancouver|ieee|harvard|bibtex|json")
    pb.add_argument("--out", help="also write the reference list to this file")
    pb.add_argument("--json", action="store_true", help="machine-readable JSON output")
    pb.add_argument("--no-extra", action="store_true", help="only DOIs; skip arXiv/PMID detection")
    pb.add_argument("--ids-only", action="store_true",
                    help="print only the DOIs found (for batch resolve via paper-search__export_citations)")
    pb.add_argument("--allow-unresolved", action="store_true",
                    help="exit 0 although identifier(s) did not resolve. The [UNRESOLVED] "
                         "placeholder is written into the list either way, so this changes "
                         "the exit code and never the artifact.")
    pb.add_argument("--allow-insufficient", action="store_true",
                    help="exit 0 although the registries could not be reached. The status "
                         "stays insufficient_evidence and not_checked[] stays populated, so "
                         "the override is logged rather than silent. --allow-unresolved does "
                         "NOT waive this.")

    pd = sub.add_parser("duplicates",
                        help="report in-text citations of the same work written differently")
    pd.add_argument("file", help="path to the draft")
    pd.add_argument("--json", action="store_true", help="machine-readable JSON output")

    args = p.parse_args(argv)
    if getattr(args, "self_test", False):
        return _self_test()
    if args.cmd == "resolve":
        try:
            rec = resolve(args.identifier)
        except Unreachable as exc:
            # An input gap, not a verdict on the identifier. Exit 3, in its own channel.
            print("[!] NOT CHECKED: %s" % args.identifier, file=sys.stderr)
            print("    %s" % exc, file=sys.stderr)
            print("    status: insufficient_evidence -- the registry was not reached, so "
                  "nothing is known either way about this identifier", file=sys.stderr)
            return 3
        if rec is None:
            print("No record found for: %s" % args.identifier, file=sys.stderr)
            return 2
        print(format_rec(rec, "json" if args.json else args.style))
        if classify(args.identifier) == "title":
            print("\n[i] Resolved by title search - confirm the DOI and venue before citing.",
                  file=sys.stderr)
        if rec.get("is_retracted"):
            print("\n[!] RETRACTED source (per %s) - do not cite without the retraction notice."
                  % (rec.get("retraction_source") or "OpenAlex"), file=sys.stderr)
        if rec.get("retraction_check_failed"):
            print("\n[!] retraction status NOT verified (%s) - this is not a clean check."
                  % rec["retraction_check_failed"], file=sys.stderr)
        return 0
    if args.cmd == "verify":
        results = verify_file(args.file)
        text, problems, unchecked = report_verify(results, args.style)
        print(text)
        # An input gap outranks a finding: 3, never 1, so a script cannot read an outage as
        # a verdict on the reference list.
        return 3 if unchecked else (1 if problems else 0)
    if args.cmd == "format":
        try:
            raw = open(args.file, encoding="utf-8").read() if args.file else sys.stdin.read()
            data = json.loads(raw)
        except Exception as e:
            print("Invalid JSON input: %s" % e, file=sys.stderr)
            return 2
        objs = data
        if isinstance(data, dict):
            for k in ("entries", "articles", "papers", "results", "data"):
                if isinstance(data.get(k), list):
                    objs = data[k]
                    break
        if isinstance(objs, dict):
            objs = [objs]
        if not isinstance(objs, list):
            print("Expected a record, a list, or an object with 'entries'.", file=sys.stderr)
            return 2
        numbered = args.style in ("vancouver", "ieee")
        for i, o in enumerate(objs, 1):
            print(format_rec(normalize_any(o), args.style, i if numbered else None))
        return 0
    if args.cmd in ("bib-from-draft", "scan"):
        return bib_from_draft(args.file, args.style, args.out, args.json,
                              extra=not args.no_extra, ids_only=args.ids_only,
                              allow_unresolved=args.allow_unresolved,
                              allow_insufficient=args.allow_insufficient)
    if args.cmd == "duplicates":
        return print_duplicates(args.file, args.json)
    p.print_help()
    return 1


def _self_test():
    """Offline assertions for the routing that keeps an input gap out of the findings.

    No network: every registry call is replaced, so this pins the decision logic and the
    emitted artifact, not the internet. eval.md C2 (an unresolved identifier must appear as
    [UNRESOLVED], never as a normal reference) and C3 (a check that could not run must say
    so) are both hard errors, so both paths are asserted here.
    """
    global crossref_record, openalex_by_doi, _open
    real_cr, real_oa = crossref_record, openalex_by_doi
    try:
        # (a) the registry answers "not held" -> a FINDING
        crossref_record = lambda d: (_ for _ in ()).throw(urllib.error.HTTPError(d, 404, "no", None, None))
        openalex_by_doi = lambda d: (_ for _ in ()).throw(urllib.error.HTTPError(d, 404, "no", None, None))
        assert resolve("10.9999/missing") is None
        # (b) the registry cannot be reached -> NOT a finding
        crossref_record = lambda d: (_ for _ in ()).throw(urllib.error.URLError("connection refused"))
        openalex_by_doi = lambda d: (_ for _ in ()).throw(urllib.error.URLError("connection refused"))
        try:
            resolve("10.9999/unreachable")
            raise AssertionError("an unreachable registry must not resolve to None")
        except Unreachable:
            pass
        # (c) a 404 at Crossref but an outage at the deciding alternative agency is still
        #     "could not ask", not "does not exist"
        crossref_record = lambda d: (_ for _ in ()).throw(urllib.error.HTTPError(d, 404, "no", None, None))
        openalex_by_doi = lambda d: (_ for _ in ()).throw(urllib.error.URLError("refused"))
        try:
            resolve("10.9999/alt-down")
            raise AssertionError("a failed alternative-agency lookup must not mean not-found")
        except Unreachable:
            pass
        # (d) resolve_many reports the two conditions in two containers
        crossref_record = lambda d: (_ for _ in ()).throw(urllib.error.URLError("refused"))
        openalex_by_doi = lambda d: (_ for _ in ()).throw(urllib.error.URLError("refused"))
        cache, unreachable = resolve_many(["10.9999/a", "10.9999/b"])
        assert set(unreachable) == {"10.9999/a", "10.9999/b"}, unreachable
        assert all(v is None for v in cache.values())
        # (e) the artifact carries the placeholder for every unresolved identifier
        line = unresolved_entry("10.9999/missing", "apa")
        assert "[UNRESOLVED]" in line and "10.9999/missing" in line, line
        assert unresolved_entry("10.9999/m", "vancouver", 7).startswith("[7] [UNRESOLVED]")
        assert json.loads(unresolved_entry("10.1/x", "json"))["unresolved"] == "10.1/x"
        assert unresolved_entry("10.1/x", "bibtex").startswith("% [UNRESOLVED]")
        # (f) the exit codes: findings fail, input gaps outrank them, each waiver is separate
        assert _bib_exit(True, False, False, False) == 2      # unresolved -> fail
        assert _bib_exit(False, True, False, False) == 3      # unreachable -> input gap
        assert _bib_exit(True, True, False, False) == 3       # gap outranks the finding
        assert _bib_exit(False, True, True, False) == 3       # --allow-unresolved waives nothing
        assert _bib_exit(True, True, True, False) == 3
        assert _bib_exit(True, True, False, True) == 2         # gap waived, finding still fails
        assert _bib_exit(True, True, True, True) == 0          # both explicitly waived
        assert _bib_exit(True, False, True, False) == 0
        assert _bib_exit(False, False, False, False) == 0     # a clean list passes
        # (g) a row the registry could not answer is UNCHECKED, never FAIL
        rows = [{"key": None, "ident": "10.1/x", "record": None, "error": "not resolved",
                 "unreachable": "could not reach the registry", "entry": None}]
        _, problems, unchecked = report_verify(rows)
        assert problems == 0 and unchecked == 1, (problems, unchecked)
        assert "UNCHECKED" in report_verify(rows)[0]
        print("self-test: OK")
        return 0
    finally:
        crossref_record, openalex_by_doi = real_cr, real_oa


if __name__ == "__main__":
    sys.exit(main())






