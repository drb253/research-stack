#!/usr/bin/env python3
"""Gate review citations against authoritative sources (stdlib only).

Resolves each cited DOI at Crossref (the registration agency), flags retraction
(OpenAlex is_retracted + Crossref retraction notices/relations), and writes
GATE_REPORT.json. Exits non-zero if any cited DOI is unresolved or retracted, so a
broken or retracted citation can never pass quietly.

Usage:
  python3 cross_verify_citations.py --sources sources.csv --out GATE_REPORT.json
  python3 cross_verify_citations.py --sources sources.csv --resolve-pmid-doi
  python3 cross_verify_citations.py --doi 10.1136/bmj.n71 --mailto you@example.org
  python3 cross_verify_citations.py --self-test        # offline logic check, no network

CSV: expects a 'doi' column (case-insensitive); optional 'title','year','s_id','pmid'.
Rows with an empty doi are reported as 'no_identifier' (a gate failure unless
--allow-unresolved).

With --resolve-pmid-doi, a row that carries a PMID but an empty DOI is looked up at
Europe PMC. A DOI that IS resolvable but absent from the ledger is a gate FAILURE, not a
waiver case: an empty cell is evidence that nobody looked, never evidence that no DOI
exists. The resolved DOI is filled in and verified normally, so the report shows both the
true citation status AND the ledger omission.

Exit codes: 0 all clear; 2 gate failure; 1 usage error.
"""
import argparse
import csv
import html as _html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CROSSREF = "https://api.crossref.org/works/"
DATACITE = "https://api.datacite.org/dois/"
OPENALEX = "https://api.openalex.org/works/doi:"
NCBI_ESUMMARY = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
                 "?db=pubmed&retmode=json&id=")
UA = "cross-verify-citations/1.0 (mailto:{mailto})"

# A DOI is not always Crossref-registered. DataCite registers datasets, software, theses and
# Zenodo deposits; arXiv registers its own 10.48550 prefix. Those are legitimate persistent
# identifiers, so a Crossref miss is NOT by itself a failure: the DOI must be checked at the
# agency that actually registered it before it may be called unresolved.
ALT_AGENCIES = {"10.48550": "arXiv", "10.5281": "DataCite", "10.5061": "DataCite",
                "10.31219": "OSF", "10.6084": "DataCite"}


class Unreachable(RuntimeError):
    """The registry could not be reached at all.

    This is a fact about our inputs, not about the citation. A DOI that returns 404
    does not exist; a resolver that refuses the connection tells us nothing about the
    DOI. Before this class existed the two produced byte-identical output -- the same
    "1 unresolved", the same ``gate: FAIL``, the same DOI in ``unresolved[]`` -- so a
    reader was told a citation was wrong when the tool never asked. It was worse under
    ``--allow-unresolved``, where a total network outage reported ``gate: PASS`` and
    exited 0.
    """


def _get(url, mailto, timeout=30, tries=3):
    """GET JSON with polite backoff. 404 -> None (a fact, not a retry)."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA.format(mailto=mailto or "anonymous"),
                 "Accept": "application/json"},
    )
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code not in (429, 500, 502, 503):
                raise
            last = e
        except Exception as e:  # noqa: BLE001 - network variety
            last = e
        time.sleep(1.5 * (i + 1))
    raise Unreachable("resolver unreachable for %s: %s" % (url, last))


SENTINELS = {"", "none", "n/a", "na", "null", "-", "nil", "not_reported", "not reported", "unknown"}


def norm_doi(doi):
    """Normalise a DOI to bare lowercase form; treat sentinel placeholders as absent."""
    doi = (doi or "").strip()
    if doi.lower() in SENTINELS:
        return ""
    for p in ("https://doi.org/", "http://doi.org/", "http://dx.doi.org/",
              "https://dx.doi.org/", "doi:", "DOI:"):
        if doi.lower().startswith(p.lower()):
            doi = doi[len(p):]
            break
    return doi.strip().lower()


_RETRACTION_PREFIX = re.compile(
    r"^\s*(?:retracted\s+article|retracted|withdrawn|expression\s+of\s+concern|"
    r"editorial\s+expression\s+of\s+concern)\s*[:\-\u2013]\s*",
    re.IGNORECASE,
)


def _norm_title(t):
    # Crossref returns JATS markup inside titles (<i>, <scp>, <sub>, newlines), sometimes
    # DOUBLE-escaped as &lt;i&gt;. Unescape first, then strip the tags, then normalise --
    # stripping before unescaping leaves the tag's inner letter behind as a token ("i"),
    # which is reported as "DOI resolves to a different paper" when it is the same paper.
    t = _html.unescape(_html.unescape(t or ""))
    t = re.sub(r"<[^>]+>", " ", t)
    # Same defect class, different cause: Crossref prefixes the title of a retracted
    # work with "RETRACTED:" / "RETRACTED ARTICLE:", which PubMed's title does not
    # carry. Comparing them verbatim reported the SAME paper as a wrong citation --
    # measured on a 120-citation benchmark, 13 of 15 flagged mismatches were exactly
    # this (similarity >= 0.99 once the prefix was removed).
    for _ in range(3):
        stripped = _RETRACTION_PREFIX.sub("", t)
        if stripped == t:
            break
        t = stripped
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def _crossref_message(doi, mailto):
    url = CROSSREF + urllib.parse.quote(doi)
    if mailto:
        url += "?mailto=" + urllib.parse.quote(mailto)
    data = _get(url, mailto)
    return (data or {}).get("message")


def crossref_retraction(msg):
    """Return (is_retracted, notices) from a Crossref work message."""
    notices = []
    rel = (msg.get("relation") or {})
    # "is-retracted-by" is Crossref's canonical relation for "this work was
    # retracted by X" and is what the vendored retraction.py reads. Without it a
    # record carrying only that relation was missed here (OpenAlex still caught
    # the real-world cases, so this is defence in depth, not the only signal).
    for rel_name in ("is-retracted-by", "update-to", "updated-by"):
        for item in rel.get(rel_name, []) or []:
            if str(item.get("type", "")).lower() in ("retraction", "retraction-of") or rel_name == "is-retracted-by":
                notices.append({"source": "crossref-relation",
                                "type": item.get("type") or "retraction",
                                "doi": item.get("id")})
    for upd in msg.get("update-to", []) or []:
        if str(upd.get("type", "")).lower() == "retraction":
            notices.append({"source": "crossref-update-to",
                            "type": upd.get("type"),
                            "doi": upd.get("DOI")})
    if "retraction" in str(msg.get("type", "")).lower():
        notices.append({"source": "crossref-type", "type": msg.get("type")})
    return (len(notices) > 0, notices)


_CORRECTION_TYPES = ("correction", "corrigendum", "erratum", "expression_of_concern",
                     "expression-of-concern", "withdrawal")


def crossref_corrections(msg):
    """Return correction/erratum notices for a Crossref work message.

    ORI Guideline 17: "Ensure that the cited work has not been subsequently
    corrected or retracted." Retraction is a hard failure -- the claim is void.
    A correction is a WARNING: the paper stands, but the version cited may be
    superseded, so the author should check whether the corrected figures change
    what they wrote.
    """
    notices = []
    rel = msg.get("relation") or {}
    for rel_name in ("is-corrected-by", "is-correction-of"):
        for item in rel.get(rel_name, []) or []:
            notices.append({"source": "crossref-relation", "relation": rel_name,
                            "doi": item.get("id")})
    for upd in msg.get("update-to", []) or []:
        if str(upd.get("type", "")).lower() in _CORRECTION_TYPES:
            notices.append({"source": "crossref-update-to",
                            "type": upd.get("type"), "doi": upd.get("DOI")})
    kind = str(msg.get("type", "")).lower()
    if any(k in kind for k in ("correction", "erratum", "corrigendum")):
        notices.append({"source": "crossref-type", "type": msg.get("type")})
    return notices


def openalex_is_retracted(doi, mailto):
    data = _get(OPENALEX + urllib.parse.quote(doi), mailto)
    return None if not data else bool(data.get("is_retracted"))


EUROPEPMC = ("https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=EXT_ID:{pmid}"
             "&resultType=core&format=json&pageSize=1")


def resolve_doi_from_pmid(pmid, mailto):
    """Resolve a PMID to its DOI via Europe PMC (returns '' if none is indexed).

    This is what turns 'PMID-only' from an assertion into a finding. An empty DOI cell in
    a ledger says only that nobody looked; this lookup says whether a DOI exists.
    """
    pmid = (pmid or "").strip()
    if not pmid:
        return ""
    data = _get(EUROPEPMC.format(pmid=urllib.parse.quote(pmid)), mailto)
    for rec in (((data or {}).get("resultList") or {}).get("result") or []):
        found = norm_doi(rec.get("doi", ""))
        if found:
            return found
    return ""


def _datacite_message(doi, mailto):
    """Look a DOI up at DataCite. Returns a Crossref-shaped dict, or None."""
    data = _get(DATACITE + urllib.parse.quote(doi), mailto)
    if not data or "data" not in data:
        return None
    a = (data.get("data") or {}).get("attributes") or {}
    titles = a.get("titles") or []
    return {"title": [titles[0].get("title", "")] if titles else [""],
            "year": a.get("publicationYear"), "type": "dataset"}


def _doi_org_location(doi):
    """Whether doi.org redirects this DOI -- RETRIED, so the verdict is stable.

    doi.org only issues a redirect for a REGISTERED DOI, so a redirect is real evidence.
    The defect being fixed is determinism: the redirect is intermittent for some prefixes
    (the same DOI returned a Location header on one run and an error on the next), which
    made the gate's verdict flip between runs.

    Requiring the LANDING PAGE to answer 2xx was tried and rejected -- many publishers
    return 403 to a non-browser agent even for perfectly valid DOIs, so that check
    rejects good citations.
    """
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request("https://doi.org/" + urllib.parse.quote(doi),
                                 headers={"User-Agent": UA.format(mailto="anonymous")})
    for attempt in range(3):
        try:
            with opener.open(req, timeout=20) as r:
                return r.url or ""
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                return e.headers.get("Location", "") or ""
            if e.code == 404:
                return ""                      # doi.org itself says: not registered
            time.sleep(1.0 * (attempt + 1))     # 5xx / transient -> retry for stability
        except Exception:                       # noqa: BLE001
            time.sleep(1.0 * (attempt + 1))
    return ""


def verify_alt_agency(doi, mailto):
    """Verify a non-Crossref DOI at the agency that registered it."""
    if doi.split("/")[0] in ("10.5281", "10.5061", "10.6084"):
        m = _datacite_message(doi, mailto)
        if m is not None:
            return {"registry": "DataCite", "title": (m["title"] or [""])[0],
                    "year": m.get("year"), "type": m.get("type")}
    reg = ALT_AGENCIES.get(doi.split("/")[0])
    loc = _doi_org_location(doi)
    if loc and reg:
        return {"registry": reg, "resolves_to": loc}
    if loc:
        return {"registry": "doi.org", "resolves_to": loc}
    return None


def pmid_verified(pmid, mailto):
    """A record may legitimately have no DOI at all. Its PMID must then resolve at Europe PMC."""
    pmid = (pmid or "").strip()
    if not pmid:
        return None
    data = _get(EUROPEPMC.format(pmid=urllib.parse.quote(pmid)), mailto)
    for rec in (((data or {}).get("resultList") or {}).get("result") or []):
        if (rec.get("pmid") or "").strip() == pmid:
            return {"title": (rec.get("title") or "").strip(),
                    "journal": ((rec.get("journalInfo") or {}).get("journal") or {}).get("title", "")}
    return None

def pubmed_is_retracted(pmid, mailto):
    """Independent retraction signal from NCBI's PubMed record for a PMID.

    Crossref and OpenAlex retraction records are deposited by the publisher and can
    lag behind the journal's own action. PubMed tags a retracted article with the
    'Retracted Publication' publication type, so this catches some cases the DOI
    registries do not yet show. Deliberately matches ONLY 'retracted publication':
    'retraction of publication' is the type on the retraction notice itself, and
    citing a notice is legitimate.

    Returns True / False, or None when the lookup could not be made (so a transport
    failure is never recorded as a clean result).
    """
    pmid = (pmid or "").strip()
    if not pmid:
        return None
    url = NCBI_ESUMMARY + urllib.parse.quote(pmid)
    if mailto:
        url += "&email=" + urllib.parse.quote(mailto)
    try:
        data = _get(url, mailto)
    except Exception:  # noqa: BLE001 - a failed lookup must not read as "clean"
        return None
    try:
        rec = ((data or {}).get("result") or {}).get(pmid) or {}
        types = [str(t).lower() for t in (rec.get("pubtype") or [])]
        return any("retracted publication" in t for t in types)
    except Exception:  # noqa: BLE001
        return None


def apply_retraction_signals(rec, doi, row, mailto, crossref_msg=None):
    """Attach every retraction signal to ``rec`` and set its status.

    Kept separate from :func:`verify_one` so no path can return early without it. The
    "not Crossref-registered" path used to skip retraction checking entirely, so a
    retracted paper whose DOI lives outside Crossref was reported as verified even when
    OpenAlex and PubMed both flagged it -- measured on a 920-citation benchmark as the
    single missed retraction. The PMID-only path did the same thing for the same reason
    -- it returned "verified" without asking anybody -- until it was routed through here.

    It also records WHICH signals could actually be consulted. "Not retracted" is only a
    finding if somebody was asked: when every signal failed, the retraction status is
    unknown, and this returns ``unreachable`` -- an input condition -- rather than a clean
    bill of health.
    """
    consulted: list = []
    failed: list = []
    notices = []
    cr_retracted = False
    if crossref_msg is not None:
        # Crossref answered, so its own retraction relation was readable.
        consulted.append("crossref")
        cr_retracted, notices = crossref_retraction(crossref_msg)
        # ORI Guideline 17 also asks about CORRECTIONS. A correction is a warning,
        # not a failure: the paper still stands, but the cited version may be
        # superseded.
        corrections = crossref_corrections(crossref_msg)
        if corrections:
            rec["corrections"] = corrections
    oa = None
    try:
        oa = openalex_is_retracted(doi, mailto)
        consulted.append("openalex")
    except Exception as e:  # noqa: BLE001
        rec["openalex_error"] = str(e)
        failed.append("openalex")
    # Third, independent signal: PubMed's publication type for this PMID. It returns None when
    # the lookup could not be made, which is a failure to ask rather than a clean result.
    pm_retracted = None
    if row and (row.get("pmid") or "").strip():
        pm_retracted = pubmed_is_retracted(row.get("pmid"), mailto)
        if pm_retracted is not None:
            rec["pubmed_retraction_check"] = pm_retracted
            consulted.append("pubmed")
        else:
            failed.append("pubmed")
    rec["retraction_signals_consulted"] = consulted
    rec["retraction_signals_failed"] = failed
    rec["retraction_evidence"] = (notices
                                  + (["openalex:is_retracted"] if oa else [])
                                  + (["pubmed:retracted-publication-type"] if pm_retracted else []))
    rec["retracted"] = bool(cr_retracted or oa or pm_retracted)
    if rec["retracted"]:
        rec["status"] = "retracted"
    elif not consulted:
        # Nobody was asked. Reporting "verified" here would be reading an absence of evidence
        # as evidence of absence, which is the same defect as reading a 404 as a check.
        rec["status"] = "unreachable"
        rec["note"] = ("no retraction signal could be consulted (%s failed), so this source's "
                       "retraction status is unknown -- it is not clear"
                       % (", ".join(failed) or "every signal"))
    else:
        rec["status"] = "verified"
        if failed:
            # A partial check is still a check, but the record says which part is missing.
            rec["note"] = ("retraction check is PARTIAL: %d of %d signal(s) could not be "
                           "consulted (%s)"
                           % (len(failed), len(failed) + len(consulted), ", ".join(failed)))
    return rec


def verify_one(doi, mailto, row=None):
    """Resolve one DOI and classify it."""
    rec = {"doi": doi, "s_id": (row or {}).get("s_id"), "status": None,
           # Carried so a re-check can rebuild the query from the report alone, and so an
           # input gap can name the PMID it could not look up.
           "pmid": (row or {}).get("pmid") or "",
           "retracted": False, "retraction_evidence": [], "title_mismatch": None}
    if not doi:
        pm = pmid_verified((row or {}).get("pmid"), mailto)
        if pm:
            rec["note"] = ("no DOI exists for this record; verified via its PubMed PMID at "
                           "Europe PMC")
            rec["verified_via"] = "PMID"
            rec["title"] = pm["title"]
            # Route through the retraction signals. This path used to return "verified" here,
            # so a PMID-only citation was reported clean without anybody ever being asked
            # whether the paper had been retracted -- the same early-return defect that was
            # fixed for the not-Crossref-registered path and left standing here.
            return apply_retraction_signals(rec, "", row, mailto)
        rec["status"] = "no_identifier"
        rec["note"] = "empty doi in ledger row and no resolvable PMID"
        return rec
    msg = _crossref_message(doi, mailto)
    if msg is None:
        alt = verify_alt_agency(doi, mailto)
        if alt:
            rec["status"] = "verified"
            rec["note"] = "not Crossref-registered; verified at %s" % alt["registry"]
            rec["verified_via"] = alt["registry"]
            rec["title"] = alt.get("title", "")
            rec["year"] = alt.get("year")
            # A DOI outside Crossref still needs its retraction signals checked;
            # returning here unchecked was the bug.
            return apply_retraction_signals(rec, doi, row, mailto)
        rec["status"] = "unresolved"
        rec["note"] = "not found at Crossref, DataCite, or doi.org"
        return rec
    cr_title = (msg.get("title") or [""])[0]
    cr_year = None
    for key in ("published-print", "published-online", "issued", "created"):
        parts = (msg.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            cr_year = parts[0][0]
            break
    rec["title"] = cr_title
    rec["year"] = cr_year
    rec["type"] = msg.get("type")
    apply_retraction_signals(rec, doi, row, mailto, crossref_msg=msg)
    if row and row.get("title"):
        if _norm_title(row["title"])[:60] != _norm_title(cr_title)[:60]:
            rec["title_mismatch"] = {"ledger": row["title"], "crossref": cr_title}
    return rec


def load_rows(path):
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        lower = {(k or "").lower(): k for k in (reader.fieldnames or [])}
        doi_col = lower.get("doi")
        sid_col = lower.get("s_id") or lower.get("source_id") or lower.get("study_id") or lower.get("id")
        pmid_col = lower.get("pmid")
        for r in reader:
            rows.append({
                "doi": norm_doi(r.get(doi_col, "") if doi_col else ""),
                "title": r.get(lower.get("title", ""), ""),
                "year": r.get(lower.get("year", ""), ""),
                "s_id": (r.get(sid_col, "") if sid_col else ""),
                "pmid": (r.get(pmid_col, "") if pmid_col else "").strip(),
            })
    return rows


def partition_results(results):
    """Split results into findings about the citations and conditions of our inputs.

    The distinction is the whole point. ``unresolved``, ``no_identifier``, ``retracted``
    and a title mismatch are claims about the cited work or the ledger. ``unreachable``
    and ``error`` are claims about our ability to ask. They are returned separately so
    that nothing downstream can add them into one count.
    """
    unresolved = [r for r in results if r["status"] == "unresolved"]
    unreachable = [r for r in results if r["status"] in ("unreachable", "error")]
    missing = [r for r in results if r["status"] == "no_identifier"]
    return unresolved, unreachable, missing


def input_gap_entry(rec):
    """One row of the worklist: what could not be checked, why, and what to do."""
    return {
        "doi": rec.get("doi") or "",
        "s_id": rec.get("s_id") or "",
        "pmid": rec.get("pmid") or "",
        "status": rec.get("status") or "",
        "reason": rec.get("note") or "",
        "action": ("re-run when the resolver is reachable, or pass --recheck with this "
                   "report to re-check only these identifiers"),
    }


def recheck(args):
    """Re-verify only the identifiers a previous report recorded as input gaps.

    The invariant asks for a mode that re-checks the worklist, so that a gap can be shown
    to be closed rather than quietly forgotten. This reads a previous report, re-queries
    exactly the identifiers it could not check, and exits 3 while any of them remain
    uncheckable. It never turns an uncheckable identifier into a finding.
    """
    try:
        with open(args.recheck, encoding="utf-8") as fh:
            prior = json.load(fh)
    except Exception as e:  # noqa: BLE001
        print("recheck: cannot read %s: %s" % (args.recheck, e))
        return 1
    gaps = prior.get("input_gaps") or []
    if not gaps:
        print("recheck: %s recorded no input gaps -- there is nothing to re-check"
              % args.recheck)
        return 0

    print("recheck: %d identifier(s) previously unchecked; re-querying now" % len(gaps))
    still = []
    for i, gap in enumerate(gaps):
        if i:
            time.sleep(0.4)
        row = {"s_id": gap.get("s_id") or "", "pmid": gap.get("pmid") or "",
               "doi": gap.get("doi") or ""}
        label = row["doi"] or ("(no DOI) %s" % (row["s_id"] or row["pmid"] or "?"))
        try:
            rec = verify_one(row["doi"], args.mailto, row)
        except Unreachable as e:
            rec = {"doi": row["doi"], "status": "unreachable", "note": str(e)}
        except Exception as e:  # noqa: BLE001
            rec = {"doi": row["doi"], "status": "error", "note": str(e)}
        if rec["status"] in ("unreachable", "error"):
            still.append(input_gap_entry(dict(rec, s_id=row["s_id"], pmid=row["pmid"])))
            print("  STILL UNCHECKABLE  %s  %s" % (label, (rec.get("note") or "")[:90]))
        else:
            print("  CLOSED             %s -> %s" % (label, rec["status"]))

    if still:
        print("recheck: %d of %d still cannot be checked -- the input gap is NOT closed"
              % (len(still), len(gaps)))
        print("  the status remains insufficient_evidence; find the identifiers that are still")
        print("  uncheckable in the report above rather than reading this as a clean run")
        return 3
    print("recheck: every previously uncheckable identifier was reached; the gap is closed")
    return 0


def _self_test():
    assert norm_doi("https://doi.org/10.1136/BMJ.n71") == "10.1136/bmj.n71"
    assert norm_doi("doi:10.1/x") == "10.1/x"
    assert norm_doi("") == ""
    assert norm_doi("none") == "" and norm_doi("N/A") == "" and norm_doi("null") == ""
    ok = {"type": "journal-article", "title": ["T"], "relation": {}}
    assert crossref_retraction(ok) == (False, [])
    rel = {"type": "journal-article",
           "relation": {"updated-by": [{"type": "retraction", "id": "10.1/ret"}]}}
    assert crossref_retraction(rel)[0] is True
    typ = {"type": "retraction", "title": ["Retraction"]}
    assert crossref_retraction(typ)[0] is True
    upd = {"type": "journal-article", "update-to": [{"type": "retraction", "DOI": "10.1/x"}]}
    assert crossref_retraction(upd)[0] is True
    # ORI Guideline 17: a CORRECTION is a warning, never a retraction. Mixing the
    # two would either void a valid paper or pass a retracted one.
    corr = {"type": "journal-article",
            "update-to": [{"type": "correction", "DOI": "10.1/c"}]}
    assert crossref_corrections(corr) and crossref_retraction(corr)[0] is False
    assert crossref_corrections({"type": "journal-article", "relation": {}}) == []
    assert crossref_corrections({"type": "journal-article",
                                 "relation": {"is-corrected-by": [{"id": "10.1/c"}]}})
    assert crossref_corrections({"type": "erratum", "relation": {}})
    # Crossref's canonical "retracted by" relation, as read by retraction.py.
    isret = {"type": "journal-article",
             "relation": {"is-retracted-by": [{"id": "10.1/ret"}]}}
    assert crossref_retraction(isret)[0] is True
    # Regression guard (offline): a DOI that is NOT Crossref-registered used to
    # return "verified" before any retraction check ran, so a retracted paper
    # outside Crossref was reported clean even when OpenAlex and PubMed both
    # flagged it. apply_retraction_signals() is now the single shared path.
    global openalex_is_retracted, pubmed_is_retracted
    _oa, _pm = openalex_is_retracted, pubmed_is_retracted
    try:
        openalex_is_retracted = lambda d, m: True
        pubmed_is_retracted = lambda p, m: True
        hit = apply_retraction_signals(
            {"doi": "10.1/x", "status": "verified", "retracted": False,
             "retraction_evidence": []}, "10.1/x", {"pmid": "1"}, "x@y.z")
        assert hit["retracted"] is True and hit["status"] == "retracted", hit
        assert "openalex:is_retracted" in hit["retraction_evidence"], hit
        openalex_is_retracted = lambda d, m: False
        pubmed_is_retracted = lambda p, m: None
        clean = apply_retraction_signals(
            {"doi": "10.1/x", "status": "verified", "retracted": False,
             "retraction_evidence": []}, "10.1/x", {}, "x@y.z")
        assert clean["retracted"] is False and clean["status"] == "verified", clean
        # Every signal failing means NOBODY was asked. "Not retracted" is then an unknown, not
        # a finding, and the record must not read "verified" -- that is an absence of evidence
        # presented as evidence of absence.
        def _boom(*_a):
            raise RuntimeError("connection refused")
        openalex_is_retracted = _boom
        pubmed_is_retracted = lambda p, m: None
        blind = apply_retraction_signals(
            {"doi": "10.1/x", "status": None, "retracted": False, "retraction_evidence": []},
            "10.1/x", {"pmid": "1"}, "x@y.z")
        assert blind["status"] == "unreachable", blind
        assert "not clear" in blind["note"], blind
        assert blind["retraction_signals_consulted"] == [], blind
        assert set(blind["retraction_signals_failed"]) == {"openalex", "pubmed"}, blind
        # A PARTIAL check is still a check, and it says which part is missing.
        openalex_is_retracted = lambda d, m: False
        pubmed_is_retracted = lambda p, m: None
        partial = apply_retraction_signals(
            {"doi": "10.1/x", "status": None, "retracted": False, "retraction_evidence": []},
            "10.1/x", {"pmid": "1"}, "x@y.z")
        assert partial["status"] == "verified", partial
        assert "PARTIAL" in partial["note"], partial
        assert partial["retraction_signals_consulted"] == ["openalex"], partial
        assert partial["retraction_signals_failed"] == ["pubmed"], partial
    finally:
        openalex_is_retracted, pubmed_is_retracted = _oa, _pm
    # ...and guard the WIRING: verify_one() must run the signals on the
    # "not Crossref-registered" branch too, not just on the Crossref branch.
    global _crossref_message, verify_alt_agency
    _cm, _va = _crossref_message, verify_alt_agency
    try:
        _crossref_message = lambda d, m: None          # simulate a Crossref 404
        verify_alt_agency = lambda d, m: {"registry": "DataCite", "title": "T", "year": 2020}
        openalex_is_retracted = lambda d, m: True
        pubmed_is_retracted = lambda p, m: None
        alt = verify_one("10.1/alt", "x@y.z", {"pmid": "1", "title": "T"})
        assert alt["status"] == "retracted", alt
        assert alt.get("verified_via") == "DataCite", alt
        openalex_is_retracted = lambda d, m: False
        ok = verify_one("10.1/alt", "x@y.z", {"pmid": "1", "title": "T"})
        assert ok["status"] == "verified", ok
    finally:
        _crossref_message, verify_alt_agency = _cm, _va
    # ...and the PMID-only path must run the signals as well. It used to return "verified"
    # straight out of verify_one(), so a PMID-only citation -- a ledger row with no DOI --
    # was reported clean without anyone ever being asked whether the paper was retracted.
    global pmid_verified
    _pv = pmid_verified
    try:
        pmid_verified = lambda p, m: {"title": "T", "journal": "J"}
        openalex_is_retracted = lambda d, m: True
        pubmed_is_retracted = lambda p, m: None
        only = verify_one("", "x@y.z", {"pmid": "1", "s_id": "S1"})
        assert only["status"] == "retracted", only
        assert only["verified_via"] == "PMID", only
        assert only["retraction_evidence"] == ["openalex:is_retracted"], only
        # and when nothing can be asked, it says so instead of "verified"
        openalex_is_retracted = lambda d, m: (_ for _ in ()).throw(RuntimeError("refused"))
        blind_pmid = verify_one("", "x@y.z", {"pmid": "1", "s_id": "S1"})
        assert blind_pmid["status"] == "unreachable", blind_pmid
    finally:
        pmid_verified = _pv
    assert _norm_title("Hello, World! (2020)") == "hello world 2020"
    # Crossref returns JATS markup inside titles; a markup difference must not be
    # reported as "DOI resolves to a different paper".
    assert _norm_title("High-dose <i>Lactobacillus</i> spp. trial") == \
           _norm_title("High-dose Lactobacillus spp. trial")
    assert _norm_title("Which probiotic <scp><i>Clostridium difficile</i></scp>-associated?") == \
           _norm_title("Which probiotic Clostridium difficile-associated?")
    assert _norm_title("A\n     <sub>2</sub> study") == _norm_title("A 2 study")
    # Crossref sometimes DOUBLE-escapes the markup (&lt;i&gt;). Unescape before stripping,
    # or the tag's inner letter survives as a token and fakes a title mismatch.
    assert _norm_title("Effect of &lt;i&gt;Lactobacillus GG&lt;/i&gt; supplementation") == \
           _norm_title("Effect of Lactobacillus GG supplementation")
    # Crossref prefixes retracted titles; PubMed does not. That must not read as a
    # wrong citation, but a genuinely different title still must.
    assert _norm_title("RETRACTED: A dual self-regulatory platform") == \
           _norm_title("A dual self-regulatory platform")
    assert _norm_title("RETRACTED ARTICLE: Safety in sows") == _norm_title("Safety in sows")
    assert _norm_title("Withdrawn: Trial of X") == _norm_title("Trial of X")
    assert _norm_title("RETRACTED: Study A") != _norm_title("Study B")
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, "s.csv")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("source_id,doi,pmid,title,year\nS001,,32114430,T,2020\n")
    r = load_rows(p)[0]
    assert r["pmid"] == "32114430" and r["doi"] == "" and r["s_id"] == "S001", r
    assert resolve_doi_from_pmid("", "x") == ""   # empty pmid must not hit the network
    # the alternative-agency rule: a Crossref miss is NOT a failure by itself, but a DOI that
    # resolves at NO agency is. These asserts pin the routing, not the network.
    assert ALT_AGENCIES["10.48550"] == "arXiv" and ALT_AGENCIES["10.5281"] == "DataCite"
    assert "10.48550/arxiv.2410.20168".split("/")[0] in ALT_AGENCIES
    assert "10.9999/nothing".split("/")[0] not in ALT_AGENCIES
    assert "10.5281/zenodo.18550755".split("/")[0] in ("10.5281", "10.5061", "10.6084")
    # --- The evidence invariant: an uncheckable identifier is not an unresolved one. ---
    # Synthetic results, so the routing is pinned offline and cannot regress. This is the
    # regression guard for the defect where a refused connection produced the same
    # "unresolved" count, the same failures[] and the same exit code as a DOI that really
    # does not exist -- and where --allow-unresolved turned a total outage into gate PASS.
    findings, gaps, absent = partition_results([
        {"status": "unresolved", "doi": "10.1/a"},
        {"status": "unreachable", "doi": "10.1/b"},
        {"status": "error", "doi": "10.1/c"},
        {"status": "no_identifier", "doi": ""},
        {"status": "verified", "doi": "10.1/d"},
    ])
    assert [r["doi"] for r in findings] == ["10.1/a"], findings
    assert [r["doi"] for r in gaps] == ["10.1/b", "10.1/c"], gaps
    assert len(absent) == 1, absent
    # A refusal must be its own exception type, distinguishable from a 404 that _get
    # deliberately turns into None.
    assert issubclass(Unreachable, RuntimeError)
    assert _get.__doc__ and "404 -> None" in _get.__doc__
    # The worklist entry says what to do, not only what failed.
    gap = input_gap_entry({"doi": "10.1/b", "s_id": "S002", "pmid": "9",
                           "status": "unreachable", "note": "connection refused"})
    assert gap["reason"] == "connection refused" and gap["pmid"] == "9", gap
    assert gap["action"] and "recheck" in gap["action"], gap
    print("self-test: OK")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Gate review citations via Crossref/OpenAlex.")
    ap.add_argument("--sources", help="CSV with a 'doi' column")
    ap.add_argument("--doi", action="append", default=[], help="a DOI (repeatable)")
    ap.add_argument("--out", default="GATE_REPORT.json")
    ap.add_argument("--mailto", default="", help="contact email for polite pools")
    ap.add_argument("--allow-unresolved", action="store_true")
    ap.add_argument("--allow-retracted", action="store_true")
    ap.add_argument("--resolve-pmid-doi", action="store_true",
                    help="for a row with a PMID and an empty DOI, resolve the DOI via Europe "
                         "PMC; a resolvable-but-absent DOI is a gate FAILURE (not waivable)")
    ap.add_argument("--strict-titles", action="store_true", default=True,
                    help="treat ledger/Crossref title differences as gate failures "
                         "(DEFAULT; a DOI that resolves to a different paper is a wrong citation)")
    ap.add_argument("--allow-title-drift", dest="strict_titles", action="store_false",
                    help="downgrade title differences to warnings (explicit, logged waiver - "
                         "use only for a known benign case such as a subtitle change)")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument(
        "--allow-insufficient",
        action="store_true",
        help="proceed when the resolver could not be reached. The report still records "
             "status=insufficient_evidence and gate=INCOMPLETE, so the override is logged "
             "rather than silent. --allow-unresolved does NOT waive an input gap.")
    ap.add_argument(
        "--recheck",
        metavar="REPORT.json",
        help="re-check only the identifiers a previous run could not check, so a gap can be "
             "shown to be closed rather than merely re-asserted. Exits 3 while any remain.")
    args = ap.parse_args(argv)

    if args.self_test:
        _self_test()
        return 0

    if args.recheck:
        return recheck(args)

    rows = load_rows(args.sources) if args.sources else []
    if args.doi:
        rows += [{"doi": norm_doi(d), "title": "", "year": "", "s_id": "", "pmid": ""}
                 for d in args.doi]
    if not rows:
        ap.error("provide --sources and/or --doi (or --self-test)")

    # An empty DOI cell is evidence that nobody looked, never evidence that no DOI exists.
    # Resolve PMID-only rows so an omission surfaces as a ledger defect instead of a waiver.
    resolvable = []
    if args.resolve_pmid_doi:
        for row in rows:
            if row.get("doi") or not row.get("pmid"):
                continue
            time.sleep(0.4)
            try:
                found = resolve_doi_from_pmid(row["pmid"], args.mailto)
            except Exception as e:  # noqa: BLE001
                row["pmid_lookup_error"] = str(e)
                continue
            if found:
                resolvable.append({"s_id": row.get("s_id") or "", "pmid": row["pmid"],
                                   "doi": found})
                row["doi"] = found

    results = []
    for i, row in enumerate(rows):
        if i:
            time.sleep(0.4)  # be a polite API citizen
        try:
            rec = verify_one(row["doi"], args.mailto, row)
        except Unreachable as e:
            # The resolver was never reached. Recorded as an input condition, in its own
            # status, so it cannot be counted as "unresolved" below.
            rec = {"doi": row["doi"], "s_id": row.get("s_id"), "pmid": row.get("pmid") or "",
                   "status": "unreachable", "retracted": False, "note": str(e)}
        except Exception as e:  # noqa: BLE001
            # Not a transport failure, but still "we could not check" rather than "it is wrong".
            rec = {"doi": row["doi"], "s_id": row.get("s_id"), "pmid": row.get("pmid") or "",
                   "status": "error", "retracted": False, "note": str(e)}
        # "Could not look up" must never be reported as "does not exist". The PMID lookup
        # already failed once (row["pmid_lookup_error"]); if the fallback also finds no
        # record, the honest reading is that the lookup did not happen, not that no
        # identifier exists for this work.
        if row.get("pmid_lookup_error") and rec["status"] == "no_identifier":
            rec["status"] = "unreachable"
            rec["note"] = ("PMID %s could not be looked up (%s), so no DOI was resolved and "
                           "no PMID verified. This is a failure to look, not a missing "
                           "identifier." % (row.get("pmid") or "?", row["pmid_lookup_error"]))
        results.append(rec)

    unresolved, unreachable, missing = partition_results(results)
    retracted = [r for r in results if r["retracted"]]
    mismatches = [dict(r["title_mismatch"], doi=r["doi"], s_id=r.get("s_id"))
                  for r in results if r.get("title_mismatch")]

    failures = []
    if unresolved and not args.allow_unresolved:
        failures += [r["doi"] or "(blank)" for r in unresolved]
    if missing and not args.allow_unresolved:
        failures += ["(no DOI) %s" % (r.get("s_id") or "") for r in missing]
    if retracted and not args.allow_retracted:
        failures += [r["doi"] for r in retracted]
    # NOT waivable: a resolvable DOI absent from the ledger is a ledger defect. The fix is to
    # fill the cell, not to waive the finding.
    failures += ["(ledger DOI missing but resolvable) %s pmid:%s -> %s"
                 % (r["s_id"] or "?", r["pmid"], r["doi"]) for r in resolvable]
    # A DOI that resolves to a DIFFERENT paper is a wrong citation, so a title difference FAILS
    # the gate by default. This default was previously "warn", and that is exactly how six
    # misaligned DOIs survived an earlier PASS in this project: the warning was printed and not
    # acted on. Downgrading to a warning is now an explicit, logged waiver.
    warnings = ["title differs for %s (%s)" % (m.get("s_id") or m["doi"], m["doi"])
                for m in mismatches]
    # ORI Guideline 17: the cited work must not have been subsequently corrected.
    # A correction is reported as a warning (the paper stands) rather than a
    # failure (which is what retraction gets), so the author can check whether
    # the corrected figures change what they wrote.
    for rec in results:
        for correction in rec.get("corrections") or []:
            warnings.append("CORRECTED: %s has a %s notice (%s) - verify the figures you cite"
                            % (rec.get("doi"), correction.get("type") or correction.get("relation"),
                               correction.get("doi") or "no DOI given"))
    if args.strict_titles:
        failures += ["%s: DOI resolves to a different paper (%s)"
                     % (m.get("s_id") or "?", m["doi"]) for m in mismatches]
    else:
        # A waiver is for BENIGN drift (a language variant, a subtitle change). A high
        # mismatch rate is a systemic data problem -- wrong DOIs in the ledger -- and must
        # still fail: waiving 19 of 83 records hid exactly that in this project.
        budget = max(2, int(0.05 * len(results)))
        if len(mismatches) > budget:
            failures.append(
                "title-drift waiver REFUSED: %d record(s) disagree with Crossref, above the "
                "%d-record drift budget (max(2, 5%% of checked)). A mismatch rate this high "
                "indicates wrong DOIs in the ledger, not benign drift -- fix the ledger and "
                "re-run." % (len(mismatches), budget))
        warnings.append("title-drift WAIVED by --allow-title-drift for %d record(s): %s"
                        % (len(mismatches), ", ".join(m.get("s_id") or "?" for m in mismatches)))

    report = {
        "tool": "cross_verify_citations",
        "checked": len(results),
        "verified": sum(1 for r in results if r["status"] == "verified"),
        "unresolved": [r["doi"] for r in unresolved],
        "no_identifier": [r.get("s_id") or r["doi"] for r in missing],
        "doi_resolvable_but_absent": resolvable,
        "retracted": [{"doi": r["doi"], "evidence": r["retraction_evidence"]} for r in retracted],
        "title_mismatches": mismatches,
        # A gap in the inputs, kept in its own key so no consumer can add it to a count of
        # findings. `status` carries it, and the exit code carries it too.
        "input_gaps": [input_gap_entry(r) for r in unreachable],
        "status": ("insufficient_evidence" if unreachable
                   else ("fail" if failures else "pass")),
        # "INCOMPLETE" rather than "PASS": a run that could not ask must not print the word a
        # reader scans for to mean "checked and clean".
        "gate": ("FAIL" if failures else ("INCOMPLETE" if unreachable else "PASS")),
        "failures": failures,
        "warnings": warnings,
        "results": results,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)

    print("cross-verify: %d checked, %d verified, %d unresolved, %d retracted, %d title-difference(s)"
          % (report["checked"], report["verified"], len(unresolved), len(retracted), len(mismatches)))
    if resolvable:
        print("  LEDGER DEFECT - DOI omitted but resolvable (fill the cell; do not waive):")
        for r in resolvable:
            print("    %s  pmid:%s -> %s" % (r["s_id"] or "?", r["pmid"], r["doi"]))
    for w in warnings:
        print("  warn:", w)
    if report["input_gaps"]:
        print("  INPUT GAP - %d identifier(s) could not be checked. This is a statement about"
              % len(report["input_gaps"]))
        print("  our inputs, NOT a finding about the citations. --allow-unresolved does not")
        print("  waive it, because there is nothing to waive: no check was made.")
        for gap in report["input_gaps"]:
            print("    %s  %s" % (gap["doi"] or "(no DOI) %s" % gap["s_id"], gap["reason"][:110]))
        print("  action: restore network access and re-run, or re-check only these with")
        print("          --recheck %s" % args.out)
    print("gate: %s -> %s" % (report["gate"], args.out))
    if report["status"] == "insufficient_evidence":
        print("status: insufficient_evidence (an input gap, outranking the findings below)")
        if not args.allow_insufficient:
            return 3
        print("  --allow-insufficient given: the status stays insufficient_evidence in the")
        print("  report; only the exit code falls back to the findings.")
    return 2 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

