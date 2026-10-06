#!/usr/bin/env python3
"""Search PROSPERO from the command line.

PROSPERO's website is a JavaScript app, so its pages can't be fetched with
plain curl/WebFetch — you get a near-empty HTML shell. This queries the
same internal endpoint the site itself calls.

    python3 prospero_search.py "breastfeeding AND microbiome"
    python3 prospero_search.py "gut microbiome AND infant" TI
    python3 prospero_search.py CRD42024530071 AN

Field codes: ALL (default), TI title, RQ review question, PA population,
AN registration number. An AN search prints the full record (RIS) instead
of a results table — use it to pull one registration's detail.

Use this for the `novelty-check` and `systematic-review` skills: to search
for competing/duplicate registrations, and to validate a search strategy
against known items.

NOTE: this endpoint is undocumented and may change without notice. Use it
for speed while drafting; repeat key searches manually on the PROSPERO
website before relying on the result for a submission, and cite the date
you ran each search.

If the endpoint breaks: the API base and payload shape are recoverable
from PROSPERO's JS bundle — look for `POST /PROSPERO/api/search`, header
`prospero-auth-token` (base64 of the current epoch-ms timestamp), and a
body with `term`/`actual` both set to `"(query):FIELD"`.
"""

import base64
import json
import re
import sys
import time
import urllib.request

API = "https://www.crd.york.ac.uk/PROSPERO/api/search"
VIEW = "https://www.crd.york.ac.uk/PROSPERO/view/"


def search(term, field="ALL", per_page=50, full=False):
    """Return (total_hits, [record dicts]) for a PROSPERO query."""
    query = f"({term}):{field}"
    payload = json.dumps({
        "term": query,
        "actual": query,
        "line": 1,
        "page": 1,
        "nperpage": per_page,
        "sort": "yr",
        "sortorder": "desc",
        "filters": [],
        "download": full,
    }).encode()

    # The app stamps each request with a base64 millisecond timestamp.
    token = base64.b64encode(str(int(time.time() * 1000)).encode()).decode()
    request = urllib.request.Request(API, data=payload, headers={
        "Content-Type": "application/json",
        "prospero-auth-token": token,
        "Referer": "https://www.crd.york.ac.uk/PROSPERO/",
    })

    result = json.load(urllib.request.urlopen(request, timeout=45))[0]
    if result.get("note", {}).get("status") != "ok":
        raise SystemExit(f"PROSPERO error: {result.get('note')}")

    hits = result["retvals"]["hits"]
    return hits["total"]["value"], [h["_source"] for h in hits["hits"]]


def strip_html(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", text).strip()


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)

    term = sys.argv[1]
    field = sys.argv[2].upper() if len(sys.argv) > 2 else "ALL"
    full = field == "AN"

    total, records = search(term, field, full=full)
    print(f'[{field}] "{term}" -> {total} registration(s)\n')

    for record in records:
        if full:
            print(record.get("ris", "(no detail available)"))
            continue
        print("{:>4}  {}  {:<10}  {}".format(
            record.get("yearfirstpublished", "?"),
            record.get("accessionnumber", "?"),
            record.get("reviewstatus", "?"),
            strip_html(record.get("title"))[:100],
        ))
        print(f"      {VIEW}{record.get('accessionnumber')}")


if __name__ == "__main__":
    main()
