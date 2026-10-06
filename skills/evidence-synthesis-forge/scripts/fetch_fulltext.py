#!/usr/bin/env python3
"""Get PMC ids for PMIDs and fetch open-access full text, to close an abstract-only review.

An abstract-only extraction is a real limitation: most reports do not put the effect
estimate in the abstract. This script links each PMID to PubMed Central, fetches the
full text of the open-access ones, and reports exactly how many records remain
abstract-only -- so the gap is measured rather than asserted.

Usage:
  python3 fetch_fulltext.py --pmids 1,2,3 --out review/ [--email you@example.org]

Writes <outdir>/fulltext/<PMCID>.txt and <outdir>/fulltext_index.csv
(pmid, pmcid, has_fulltext, chars).
"""
import argparse
import csv
import os
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
UA = "evidence-synthesis-forge/fetch_fulltext"


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
            time.sleep(2.0 * (attempt + 1))
    raise SystemExit("E-utilities request failed after %d tries: %s\n  %s" % (tries, last, url))


def pmc_ids(pmids, email):
    """pmid -> pmcid, queried ONE id at a time and filtered to the pubmed_pmc linkname.

    Two traps this avoids:
      * a batched elink returns ONE linkset whose `links` are the UNION across all ids,
        so `ids[0]` maps every pmid to the first record's PMCID;
      * the response also carries `pubmed_pmc_refs` -- articles that CITE the record --
        so taking the first linksetdb blindly attaches a citing paper's PMCID.
    """
    import json
    out = {}
    for pmid in pmids:
        url = (EUTILS + "elink.fcgi?dbfrom=pubmed&db=pmc&retmode=json"
               "&linkname=pubmed_pmc&id=" + pmid)
        try:
            data = json.loads(_get(url, email))
        except SystemExit:
            continue
        for ls in (data.get("linksets") or []):
            for db in (ls.get("linksetdbs") or []):
                if db.get("linkname") == "pubmed_pmc" and db.get("links"):
                    out[pmid] = "PMC" + str(db["links"][0])
        time.sleep(0.4)
    return out


def _body_text(root):
    """Concatenate the article body, excluding the reference list."""
    parts = []
    for node in root.iter():
        tag = node.tag.split("}")[-1]
        if tag in ("ref-list", "back"):
            continue
        if tag in ("p", "title", "td", "th", "caption", "abstract"):
            txt = "".join(node.itertext()).strip()
            if txt:
                parts.append(txt)
    return "\n".join(parts)


def fetch_fulltext(pmcid, email):
    url = (EUTILS + "efetch.fcgi?db=pmc&retmode=xml&id=" + pmcid.replace("PMC", ""))
    xml = _get(url, email)
    if "<body" not in xml and "<sec" not in xml:
        return None
    return _body_text(ET.fromstring(xml))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fetch PMC open-access full text.")
    ap.add_argument("--pmids", required=True, help="comma-separated PMIDs")
    ap.add_argument("--out", required=True)
    ap.add_argument("--email", default=None)
    args = ap.parse_args(argv)

    pmids = [p.strip() for p in args.pmids.split(",") if p.strip()]
    links = pmc_ids(pmids, args.email)
    print("PMIDs: %d | linked to PMC: %d" % (len(pmids), len(links)))

    os.makedirs(os.path.join(args.out, "fulltext"), exist_ok=True)
    index = []
    for pmid in pmids:
        pmcid = links.get(pmid, "")
        text = ""
        if pmcid:
            try:
                text = fetch_fulltext(pmcid, args.email) or ""
            except SystemExit:
                text = ""
            time.sleep(0.4)
        if text:
            with open(os.path.join(args.out, "fulltext", pmcid + ".txt"), "w",
                      encoding="utf-8") as fh:
                fh.write(text)
        index.append({"pmid": pmid, "pmcid": pmcid,
                      "has_fulltext": bool(text), "chars": len(text)})

    with open(os.path.join(args.out, "fulltext_index.csv"), "w", newline="",
              encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["pmid", "pmcid", "has_fulltext", "chars"])
        w.writeheader()
        w.writerows(index)

    got = sum(1 for r in index if r["has_fulltext"])
    print("full text retrieved: %d of %d (%.0f%%)" % (got, len(index), 100.0 * got / max(1, len(index))))
    print("still abstract-only: %d" % (len(index) - got))
    return 0


if __name__ == "__main__":
    sys.exit(main())
