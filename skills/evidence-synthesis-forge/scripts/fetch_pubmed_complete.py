#!/usr/bin/env python3
"""Retrieve the COMPLETE PubMed result set for a query -- no silent truncation.

The two ways a review silently loses records are (a) calling esearch with a fixed
retmax and never paginating, and (b) fetching full records for only a hand-picked
subset of the eligible reports. This script does neither:

  1. esearch with retmax=0 to read the true hit count;
  2. esearch again, paginating with retstart, until every id is collected;
  3. efetch in batches (<=200 ids) to pull title/DOI/journal/year/pubtype/abstract
     for EVERY id;
  4. assert identified == fetched and refuse to write an incomplete pool.

Output: <outdir>/pool.csv, one row per identified record.

Usage:
  python3 fetch_pubmed_complete.py --query "probiotics AND ..." --out review/
  python3 fetch_pubmed_complete.py --query "..." --out review/ --email you@example.org

Exit codes: 0 complete; 2 the retrieved set does not match the identified set; 1 usage.
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
UA = "evidence-synthesis-forge/fetch_pubmed_complete"


def _get(url, email=None, tries=3, timeout=60):
    if email:
        url += ("&" if "?" in url else "?") + "email=" + urllib.parse.quote(email)
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as fh:
                return fh.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001 - retried, then surfaced
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise SystemExit("E-utilities request failed after %d tries: %s\n  %s" % (tries, last, url))


def count_hits(query, email):
    url = (EUTILS + "esearch.fcgi?db=pubmed&retmode=json&retmax=0&term="
           + urllib.parse.quote(query))
    return int(json.loads(_get(url, email))["esearchresult"]["count"])


def all_pmids(query, email, page=500):
    """Every PMID for the query -- paginated, never truncated."""
    got, start = [], 0
    while True:
        url = (EUTILS + "esearch.fcgi?db=pubmed&retmode=json&retmax=%d&retstart=%d&term="
               % (page, start) + urllib.parse.quote(query))
        ids = json.loads(_get(url, email))["esearchresult"]["idlist"]
        if not ids:
            break
        got.extend(ids)
        if len(ids) < page:
            break
        start += page
    seen, out = set(), []
    for p in got:                       # de-duplicate, preserve order
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out

def _text(node, path):
    el = node.find(path)
    return "".join(el.itertext()).strip() if el is not None else ""


def _doi_of(art):
    """The article's OWN DOI -- scoped, never a descendant search.

    A bare `.//ArticleId` also matches the DOIs inside ReferenceList/Reference/
    ArticleIdList, i.e. the DOIs of the papers this article CITES. That silently
    attaches a wrong DOI to records and makes every citation resolve to a different
    paper. Scope to the article's own identifier list (and the older ELocationID).
    """
    for aid in art.findall("./PubmedData/ArticleIdList/ArticleId"):
        if (aid.get("IdType") or "").lower() == "doi":
            return (aid.text or "").strip()
    for el in art.findall("./MedlineCitation/Article/ELocationID"):
        if (el.get("EIdType") or "").lower() == "doi":
            return (el.text or "").strip()
    return ""


def fetch_records(pmids, email, batch=200):
    """Title/DOI/journal/year/pubtype/abstract for every PMID, in batches."""
    rows = []
    for i in range(0, len(pmids), batch):
        chunk = pmids[i:i + batch]
        url = (EUTILS + "efetch.fcgi?db=pubmed&retmode=xml&id=" + ",".join(chunk))
        root = ET.fromstring(_get(url, email))
        for art in root.findall(".//PubmedArticle"):
            pmid = _text(art, "./MedlineCitation/PMID")
            year = _text(art, "./MedlineCitation/Article/Journal/JournalIssue/PubDate/Year") or \
                _text(art, "./MedlineCitation/Article/Journal/JournalIssue/PubDate/MedlineDate")[:4]
            abstract = " ".join("".join(a.itertext()).strip()
                                for a in art.findall(".//Abstract/AbstractText")).strip()
            rows.append({
                "pmid": pmid, "doi": _doi_of(art),
                "title": _text(art, "./MedlineCitation/Article/ArticleTitle").rstrip("."),
                "year": year,
                "journal": _text(art, "./MedlineCitation/Article/Journal/Title"),
                "pubtype": ";".join("".join(p.itertext()).strip()
                                    for p in art.findall(
                                        "./MedlineCitation/Article/PublicationTypeList/PublicationType")),
                "abstract": abstract,
            })
    return rows


SELFTEST_XML = """<PubmedArticleSet><PubmedArticle>
  <MedlineCitation><PMID>111</PMID><Article>
    <ArticleTitle>The study we actually retrieved</ArticleTitle>
    <Journal><Title>Journal of Real Papers</Title>
      <JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue></Journal>
  </Article></MedlineCitation>
  <PubmedData><ArticleIdList>
    <ArticleId IdType="pubmed">111</ArticleId>
    <ArticleId IdType="doi">10.1000/own.doi</ArticleId>
  </ArticleIdList></PubmedData>
  <ReferenceList><Reference><ArticleIdList>
    <ArticleId IdType="doi">10.9999/cited.paper.doi</ArticleId>
  </ArticleIdList></Reference></ReferenceList>
</PubmedArticle></PubmedArticleSet>"""


def _self_test():
    """The DOI must be the article's OWN, never a cited reference's.

    A descendant search (.//ArticleId) also matches ReferenceList/Reference/ArticleIdList,
    which silently attaches a CITED paper's DOI to the record -- making every citation
    resolve to a different paper. This asserts the scoped lookup.
    """
    art = ET.fromstring(SELFTEST_XML).find(".//PubmedArticle")
    doi = _doi_of(art)
    assert doi == "10.1000/own.doi", "expected the article's own DOI, got %r" % doi
    assert doi != "10.9999/cited.paper.doi", "picked up a CITED paper's DOI"
    assert _text(art, "./MedlineCitation/Article/ArticleTitle") == \
        "The study we actually retrieved"
    # a record with no DOI of its own must yield "", not a reference's DOI
    bare = ET.fromstring(SELFTEST_XML.replace(
        '<ArticleId IdType="doi">10.1000/own.doi</ArticleId>', ""))
    assert _doi_of(bare.find(".//PubmedArticle")) == "", "must not fall through to a citation"
    print("self-test: OK (DOI is scoped to the article, never to its reference list)")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Retrieve a complete PubMed result set.")
    ap.add_argument("--query")
    ap.add_argument("--out")
    ap.add_argument("--email", default=None, help="NCBI asks for a contact address")
    ap.add_argument("--batch", type=int, default=200, help="efetch batch size (<=200)")
    ap.add_argument("--self-test", action="store_true", help="offline logic check, no network")
    args = ap.parse_args(argv)

    if args.self_test:
        _self_test()
        return 0
    if not args.query or not args.out:
        print("ERROR: --query and --out are required (or use --self-test)", file=sys.stderr)
        return 1

    identified = count_hits(args.query, args.email)
    pmids = all_pmids(args.query, args.email)
    print("identified by the query: %d" % identified)
    print("pmids retrieved:          %d" % len(pmids))
    if len(pmids) != identified:
        print("ERROR: the retrieved id list (%d) does not match the identified count (%d); "
              "refusing to write an incomplete pool." % (len(pmids), identified), file=sys.stderr)
        return 2

    rows = fetch_records(pmids, args.email, args.batch)
    if len(rows) != identified:
        print("ERROR: fetched %d full records for %d identified pmids -- refusing to write an "
              "incomplete pool." % (len(rows), identified), file=sys.stderr)
        return 2

    os.makedirs(args.out, exist_ok=True)
    for i, r in enumerate(rows, 1):
        r["source_id"] = "S%03d" % i
    path = os.path.join(args.out, "pool.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["source_id", "pmid", "doi", "title", "year",
                                           "journal", "pubtype", "abstract"])
        w.writeheader()
        w.writerows(rows)
    print("wrote %s: %d records (%d with a DOI, %d with an abstract)"
          % (path, len(rows), sum(1 for r in rows if r["doi"]),
             sum(1 for r in rows if r["abstract"])))
    print("COMPLETE: identified == retrieved == fetched == %d" % identified)
    return 0


if __name__ == "__main__":
    sys.exit(main())

