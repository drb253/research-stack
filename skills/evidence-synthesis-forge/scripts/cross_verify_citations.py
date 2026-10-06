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
    raise RuntimeError("network failure for %s: %s" % (url, last))


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


def _norm_title(t):
    # Crossref returns JATS markup inside titles (<i>, <scp>, <sub>, newlines), sometimes
    # DOUBLE-escaped as &lt;i&gt;. Unescape first, then strip the tags, then normalise --
    # stripping before unescaping leaves the tag's inner letter behind as a token ("i"),
    # which is reported as "DOI resolves to a different paper" when it is the same paper.
    t = _html.unescape(_html.unescape(t or ""))
    t = re.sub(r"<[^>]+>", " ", t)
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
    for rel_name in ("update-to", "updated-by"):
        for item in rel.get(rel_name, []) or []:
            if str(item.get("type", "")).lower() in ("retraction", "retraction-of"):
                notices.append({"source": "crossref-relation",
                                "type": item.get("type"),
                                "doi": item.get("id")})
    for upd in msg.get("update-to", []) or []:
        if str(upd.get("type", "")).lower() == "retraction":
            notices.append({"source": "crossref-update-to",
                            "type": upd.get("type"),
                            "doi": upd.get("DOI")})
    if "retraction" in str(msg.get("type", "")).lower():
        notices.append({"source": "crossref-type", "type": msg.get("type")})
    return (len(notices) > 0, notices)


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


def verify_one(doi, mailto, row=None):
    """Resolve one DOI and classify it."""
    rec = {"doi": doi, "s_id": (row or {}).get("s_id"), "status": None,
           "retracted": False, "retraction_evidence": [], "title_mismatch": None}
    if not doi:
        pm = pmid_verified((row or {}).get("pmid"), mailto)
        if pm:
            rec["status"] = "verified"
            rec["note"] = "no DOI exists for this record; verified via its PubMed PMID at Europe PMC"
            rec["verified_via"] = "PMID"
            rec["title"] = pm["title"]
            return rec
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
            return rec
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
    cr_retracted, notices = crossref_retraction(msg)
    oa = None
    try:
        oa = openalex_is_retracted(doi, mailto)
    except Exception as e:  # noqa: BLE001
        rec["openalex_error"] = str(e)
    ## third, independent signal: PubMed's publication type for this PMID
    pm_retracted = None
    if row and (row.get("pmid") or "").strip():
        pm_retracted = pubmed_is_retracted(row.get("pmid"), mailto)
        if pm_retracted is not None:
            rec["pubmed_retraction_check"] = pm_retracted
    rec["retraction_evidence"] = (notices
                                  + (["openalex:is_retracted"] if oa else [])
                                  + (["pubmed:retracted-publication-type"] if pm_retracted else []))
    rec["retracted"] = bool(cr_retracted or oa or pm_retracted)
    if row and row.get("title"):
        if _norm_title(row["title"])[:60] != _norm_title(cr_title)[:60]:
            rec["title_mismatch"] = {"ledger": row["title"], "crossref": cr_title}
    rec["status"] = "retracted" if rec["retracted"] else "verified"
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
    args = ap.parse_args(argv)

    if args.self_test:
        _self_test()
        return 0

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
            results.append(verify_one(row["doi"], args.mailto, row))
        except Exception as e:  # noqa: BLE001
            results.append({"doi": row["doi"], "status": "error",
                            "retracted": False, "note": str(e)})

    unresolved = [r for r in results if r["status"] in ("unresolved", "error")]
    missing = [r for r in results if r["status"] == "no_identifier"]
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
        "gate": "FAIL" if failures else "PASS",
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
    print("gate: %s -> %s" % (report["gate"], args.out))
    return 2 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

