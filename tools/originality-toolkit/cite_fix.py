#!/usr/bin/env python3
"""Turn a self-originality report into a verified bibliography + citation plan.

Reads the JSON emitted by ``originality_check.py --json`` (or its markdown
report), resolves each flagged passage to a citable record, fetches BibTeX via
DOI Content Negotiation, and writes:

    refs.bib                  de-duplicated, verified BibTeX
    citation_suggestions.md   per-passage: which citation to attach, where

    python3 originality_check.py draft.md --json out.json
    python3 cite_fix.py out.json --bib refs.bib --out citation_suggestions.md

BibTeX is rendered with the citation-management skill's own ``_common`` module
(its citation-key scheme), so these entries de-duplicate against entries the
skill produces elsewhere.  Stdlib only -- no ``requests`` needed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

def _find_citation_scripts() -> str:
    """Locate the upstream `citation-management` skill's scripts dir.

    Searched in order so the toolkit works on any client (Cline/Claude/OpenCode),
    from the upstream clone, or via an explicit override. Falls back to the legacy
    path (cite_fix degrades gracefully to --no-skill-render when absent).
    """
    candidates = [
        os.environ.get("CITATION_MGMT_SCRIPTS", ""),
        os.path.expanduser("~/.research-stack/skills/citation-management/scripts"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills",
                     "citation-management", "scripts"),
        os.path.expanduser("~/.cline/skills/citation-management/scripts"),
        os.path.expanduser("~/.claude/skills/citation-management/scripts"),
        os.path.expanduser("~/.config/opencode/skills/citation-management/scripts"),
        os.path.expanduser("~/.local/share/scientific-agent-skills/skills/"
                           "citation-management/scripts"),
    ]
    for cand in candidates:
        if cand and os.path.isdir(cand):
            return os.path.abspath(cand)
    return os.path.expanduser("~/.cline/skills/citation-management/scripts")


SKILL_SCRIPTS = _find_citation_scripts()
if os.path.isdir(SKILL_SCRIPTS):
    sys.path.insert(0, SKILL_SCRIPTS)
try:
    from _common import citation_key, parse_bibtex, protect_title, render_entry
except ImportError:  # pragma: no cover - only when the skill is absent
    sys.stderr.write(
        "error: citation-management skill not found at %s\n"
        "       install it, or pass --no-skill-render to build entries locally\n"
        % SKILL_SCRIPTS
    )
    citation_key = parse_bibtex = protect_title = render_entry = None

_UA = "OriginalityToolkit-cite_fix/1.0 (citation pipeline; mailto:%s)" % (
    os.environ.get("CROSSREF_EMAIL", os.environ.get("OPENALEX_EMAIL", "researcher@example.org"))
)
_TIMEOUT = 25


def _get(url, accept="application/x-bibtex", retries=2):
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": accept})
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < retries:
                time.sleep(1.2 * (attempt + 1))
    raise last


MD_PASSAGE = re.compile(
    r"^###\s+\d+\.\s+(?P<verdict>.+?)\s+—\s+score\s+(?P<score>[\d.]+)\s*$"
    r".*?\n>\s+(?P<sentence>.+?)\s*$"
    r".*?- \*\*Source:\*\*\s+(?P<title>.+?)\s+—\s+(?P<authors>.+?)\s+\((?P<ref>[^)]*)\)\s*$"
    r"(?:.*?- \*\*Link:\*\*\s+(?P<link>\S+)\s*$)?"
    r".*?- \*\*Matching wording:\*\*\s+\"(?P<span>.*?)\"\s*$",
    re.M | re.S,
)


def load_report(path):
    """Load flagged passages from the JSON report, or parse the markdown one."""
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    if path.endswith(".json"):
        payload = json.loads(text)
        passages = []
        for item in payload.get("results", []):
            if item.get("verdict") == "ok" or not item.get("source"):
                continue
            src = item["source"]
            passages.append({
                "sentence": item["sentence"],
                "verdict": item["verdict"],
                "score": item.get("score"),
                "run_words": item.get("run_words", 0),
                "span": item.get("run_span", ""),
                "title": src.get("title", ""),
                "authors": src.get("authors", ""),
                "year": str(src.get("year") or ""),
                "doi": src.get("doi", ""),
                "url": src.get("url", ""),
                "origin": src.get("source", ""),
                "id": src.get("id", ""),
            })
        return payload.get("draft", os.path.basename(path)), passages, payload

    passages = []
    for match in MD_PASSAGE.finditer(text):
        ref = match.group("ref") or ""
        year = ""
        year_match = re.search(r"\b(19|20)\d{2}\b", ref)
        if year_match:
            year = year_match.group(0)
        link = match.group("link") or ""
        passages.append({
            "sentence": match.group("sentence").strip(),
            "verdict": match.group("verdict").strip(),
            "score": float(match.group("score")),
            "run_words": len(match.group("span").split()),
            "span": match.group("span").strip(),
            "title": match.group("title").strip(),
            "authors": match.group("authors").strip(),
            "year": year,
            "doi": link if "doi.org" in link else "",
            "url": link,
            "origin": ref.split()[0] if ref else "",
            "id": "",
        })
    return os.path.basename(path), passages, {}


def resolve_doi(passage):
    """Best DOI for a passage: the one already found, else a Crossref title lookup."""
    doi = (passage.get("doi") or "").strip()
    if doi:
        return doi, "reported"
    if passage.get("origin") == "arxiv":
        match = re.match(r"(\d{4}\.\d{4,5})", passage.get("id") or "")
        if match:
            return "10.48550/arXiv." + match.group(1), "arxiv-derived"
    if passage.get("title"):
        try:
            url = "https://api.crossref.org/works?" + urllib.parse.urlencode(
                {"query.bibliographic": passage["title"], "rows": 1, "select": "DOI,title"}
            )
            payload = json.loads(_get(url, accept="application/json"))
            items = payload.get("message", {}).get("items", [])
            if items:
                return items[0]["DOI"], "crossref-title-match"
        except Exception:  # noqa: BLE001 - resolution failure is reported, not fatal
            pass
    return "", "unresolved"


def fetch_bibtex(doi):
    """DOI Content Negotiation -> BibTeX (same mechanism as doi_to_bibtex.py)."""
    text = _get("https://doi.org/" + urllib.parse.quote(doi, safe="/:"))
    text = re.sub(r"^%+.*$", "", text, flags=re.M).strip()
    if not text.startswith("@"):
        raise ValueError("DOI did not yield BibTeX: %r" % text[:60])
    return text


def local_entry(passage):
    """Fallback when content negotiation fails: build with the skill's scheme."""
    if not render_entry:
        return ""
    authors = passage.get("authors") or ""
    bib_authors = " and ".join(a.strip() for a in authors.split(",") if a.strip())
    title = passage.get("title") or ""
    fields = {
        "title": protect_title(title) if protect_title else title,
        "author": bib_authors,
        "year": passage.get("year") or "",
        "journal": "arXiv preprint" if passage.get("origin") == "arxiv" else "",
        "doi": passage.get("doi") or "",
        "url": passage.get("url") or "",
        "note": "auto-built by cite_fix.py - verify before submission",
    }
    key = citation_key(bib_authors, passage.get("year") or "", title) if citation_key else "ref"
    return render_entry("misc", key, fields)


def intext(fields):
    """Author-year in-text citation (APA-ish) from a BibTeX entry's fields."""
    raw = (fields or {}).get("author", "") or ""
    names = [part.strip() for part in raw.split(" and ") if part.strip()]

    def surname(name):
        if "," in name:
            return name.split(",")[0].strip()
        parts = name.split()
        return parts[-1] if parts else name

    year = re.sub(r"[^0-9]", "", str((fields or {}).get("year", "")))[:4] or "n.d."
    if not names:
        return "(%s)" % year
    if len(names) == 1:
        return "(%s, %s)" % (surname(names[0]), year)
    if len(names) == 2:
        return "(%s & %s, %s)" % (surname(names[0]), surname(names[1]), year)
    return "(%s et al., %s)" % (surname(names[0]), year)


def _rekey(fields, fallback=""):
    """Normalise a fetched entry's key to the skill's citation-key scheme.

    arXiv's DOI content negotiation returns a URL-shaped key
    (``https://doi.org/10.48550/arxiv.1706.03762``), which neither reads well in
    LaTeX nor de-duplicates against entries this skill produces elsewhere.
    Re-keying with ``citation_key()`` gives the same key every producer uses.
    """
    if not citation_key:
        return fallback
    authors = fields.get("author", "")
    title = fields.get("title", "")
    if not (authors or title):
        return fallback
    return citation_key(authors, fields.get("year", ""), title)


def build_entries(passages, no_fetch=False, pause=0.6):
    """Resolve each passage to a BibTeX entry; de-duplicate by DOI then key.

    Returns (entries, passage_links) where entries is a list of
    {bib, key, fields, doi, doi_source} and passage_links maps a passage index
    to its entry key.
    """
    entries, by_doi, by_key, links = [], {}, {}, {}
    for index, passage in enumerate(passages):
        doi, doi_source = resolve_doi(passage)
        bib, key, fields = "", "", {}
        if doi and not no_fetch:
            try:
                bib = fetch_bibtex(doi)
            except Exception:  # noqa: BLE001 - fall through to a local entry
                bib = ""
        if not bib:
            bib = local_entry(passage)
            doi_source += "->local-entry" if bib else "->failed"
        parsed = parse_bibtex(bib) if (bib and parse_bibtex) else []
        if parsed:
            entry_type = parsed[0]["type"]
            fields = parsed[0]["fields"]
            key = _rekey(fields, fallback=parsed[0]["key"])
            if render_entry:
                bib = render_entry(entry_type, key, fields)
        elif bib:
            match = re.search(r"@\w+\{\s*([^,]+),", bib)
            key = match.group(1).strip() if match else "ref%d" % index
        else:
            key = ""

        if key and key in by_key:
            links[index] = by_key[key]
            continue
        if doi and doi in by_doi:
            links[index] = by_doi[doi]
            continue
        if bib:
            entries.append({"bib": bib, "key": key, "fields": fields,
                            "doi": doi, "doi_source": doi_source})
            if doi:
                by_doi[doi] = key
            if key:
                by_key[key] = key
            links[index] = key
        else:
            links[index] = ""
        time.sleep(pause)
    return entries, links


def render_suggestions(draft_name, passages, entries, links):
    lines = ["# Citation plan — %s" % draft_name, ""]
    if entries:
        lines.append("%d unique source(s) resolved -> `refs.bib`." % len(entries))
    else:
        lines.append("No source could be resolved to a citation. "
                     "Every passage still needs an in-text citation.")
    lines.append("")
    for index, passage in enumerate(passages):
        key = links.get(index, "")
        lines.append("## %d. %s" % (index + 1, passage["verdict"]))
        lines.append("")
        lines.append("> %s" % passage["sentence"])
        lines.append("")
        lines.append("- **Source:** %s (%s)" % (passage["title"] or "(untitled)",
                                               passage["year"] or "n.d."))
        entry = next((e for e in entries if e["key"] == key), None)
        if entry:
            lines.append("- **BibTeX key:** `%s`  |  **in-text:** %s"
                         % (key, intext(entry["fields"])))
            lines.append("- **DOI:** %s (%s)" % (entry["doi"] or "n/a",
                                                 entry["doi_source"]))
        else:
            lines.append("- **No citation resolved** — find the primary source "
                         "manually before submitting this passage.")
        if passage["verdict"].startswith("QUOTE"):
            lines.append("- **Do:** put the words in quotation marks and add the "
                         "citation with a page/locator.")
        elif passage["verdict"].startswith("PARAPHRASE"):
            lines.append("- **Do:** rewrite in your own words, then attach the citation.")
        else:
            lines.append("- **Do:** confirm whether a citation is warranted.")
        if passage["span"]:
            lines.append("- **Overlapping wording:** \"%s\"" % passage["span"])
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", help="originality_check JSON (.json) or markdown report")
    parser.add_argument("--bib", default="refs.bib")
    parser.add_argument("--out", default="citation_suggestions.md")
    parser.add_argument("--no-fetch", action="store_true",
                        help="skip DOI network lookups; build entries locally")
    parser.add_argument("--pause", type=float, default=0.6)
    args = parser.parse_args(argv)

    draft_name, passages, _ = load_report(args.report)
    if not passages:
        print("No flagged passages in %s - nothing to cite." % args.report)
        return 0

    entries, links = build_entries(passages, no_fetch=args.no_fetch, pause=args.pause)

    with open(args.bib, "w", encoding="utf-8") as handle:
        handle.write("\n\n".join(e["bib"] for e in entries) + ("\n" if entries else ""))
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(render_suggestions(draft_name, passages, entries, links))

    unresolved = sum(1 for i in range(len(passages)) if not links.get(i))
    print("Wrote %d entries -> %s" % (len(entries), args.bib))
    print("Wrote citation plan -> %s" % args.out)
    if unresolved:
        print("WARNING: %d passage(s) unresolved and NOT cited." % unresolved,
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


