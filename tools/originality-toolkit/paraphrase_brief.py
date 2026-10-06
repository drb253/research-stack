#!/usr/bin/env python3
"""Item 3 - paraphrase-with-attribution worksheet.

Takes the originality report and, for every flagged passage, emits a rewrite
brief: the sentence, the source, the exact overlapping wording to *avoid*, the
citation to attach, and a ready-to-run LLM prompt. The actual rewriting is an
interactive step (run these prompts in Cline) - this script prepares the ground
so the rewrite is attribution-correct rather than merely undetectable.

    python3 paraphrase_brief.py out.json --out paraphrase_worksheet.md

The guardrail is deliberate: the goal is YOUR phrasing plus an accurate
citation, never text engineered to evade a classifier.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

import cite_fix


PROMPT_TEMPLATE = """Rewrite the sentence below in my own voice.

Hard rules:
- Keep the meaning exact. Do not add or drop claims.
- Do NOT reuse this overlapping wording: "{span}"
- The rewrite must carry this citation: {intext}
- If part of the sentence is a standard definition or common knowledge, say so
  explicitly instead of citing it.
- Return: (a) the rewritten sentence, (b) the citation placement, and
  (c) a one-line note on what a reader would need to check in the source.

Sentence: {sentence}
Source: {title} ({year})"""


def build_worksheet(draft_name, passages, entries):
    by_key = {e["key"]: e for e in entries}
    lines = [
        "# Paraphrase & attribution worksheet — %s" % draft_name,
        "",
        "For each flagged passage: decide whether it needs a quotation, a",
        "paraphrase with citation, or nothing. The aim is *your words plus the",
        "right attribution* — not text tuned to slip past a detector.",
        "",
        "---",
        "",
    ]
    prompts = []
    for index, passage in enumerate(passages, 1):
        key = passage.get("key", "")
        entry = by_key.get(key)
        if entry:
            intext = cite_fix.intext(entry["fields"])
            citation = "%s  [bib key: `%s`]" % (intext, key)
        else:
            intext = "(SOURCE NEEDED)"
            citation = "**no citation resolved — locate the primary source first**"

        lines.append("## %d. %s" % (index, passage["verdict"]))
        lines.append("")
        lines.append("**Original sentence**")
        lines.append("")
        lines.append("> %s" % passage["sentence"])
        lines.append("")
        lines.append("**Source:** %s (%s)" % (passage["title"] or "(untitled)",
                                              passage["year"] or "n.d."))
        lines.append("")
        lines.append("**Attribution decision**")
        lines.append("")
        lines.append("- [ ] quote verbatim (add quotes + locator) + citation")
        lines.append("- [ ] paraphrase in my own words + citation")
        lines.append("- [ ] common knowledge / my own observation -> no citation")
        lines.append("")
        lines.append("**Citation to attach:** %s" % citation)
        lines.append("")
        if passage["span"]:
            lines.append("**Wording to avoid**")
            lines.append("")
            lines.append("`%s`" % passage["span"])
            lines.append("")
        lines.append("**My rewrite**")
        lines.append("")
        lines.append("> _(write it here)_")
        lines.append("")
        lines.append("---")
        lines.append("")
        prompts.append({
            "index": index,
            "prompt": PROMPT_TEMPLATE.format(
                span=passage["span"] or "(none - topical overlap only)",
                intext=intext,
                sentence=passage["sentence"],
                title=passage["title"] or "(untitled)",
                year=passage["year"] or "n.d.",
            ),
        })
    return "\n".join(lines), prompts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", help="originality_check JSON report")
    parser.add_argument("--out", default="paraphrase_worksheet.md")
    parser.add_argument("--prompts", default=None,
                        help="also write the LLM prompt payloads as JSON here")
    args = parser.parse_args(argv)

    if not args.report.endswith(".json"):
        sys.stderr.write("error: needs the JSON report "
                         "(originality_check.py --json)\n")
        return 2

    draft_name, passages, entries = load_and_link(args.report)
    worksheet, prompts = build_worksheet(draft_name, passages, entries)

    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(worksheet)
    print("Wrote %s (%d passages)" % (args.out, len(passages)))

    if args.prompts:
        with open(args.prompts, "w", encoding="utf-8") as handle:
            json.dump(prompts, handle, indent=2)
        print("Wrote %s" % args.prompts)
    return 0


def _norm_title(text):
    """Title key for linking a report passage to a BibTeX entry."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def load_and_link(report_path):
    """Load passages and attach the citation key from the sibling refs.bib."""
    draft_name, passages, _payload = cite_fix.load_report(report_path)

    entries = []
    for candidate in ("refs.bib", os.path.join(os.path.dirname(report_path), "refs.bib")):
        if os.path.exists(candidate):
            with open(candidate, encoding="utf-8") as handle:
                parsed = cite_fix.parse_bibtex(handle.read())
            entries = [{"key": e["key"], "fields": e["fields"]} for e in parsed]
            break

    # Link passage -> entry. DOI is checked first, then normalised title: an
    # arXiv hit carries no DOI in the report (the checker's adapters leave it
    # empty), so the DOI alone would leave these passages unresolved.
    by_doi, by_title = {}, {}
    for entry in entries:
        by_doi[(entry["fields"].get("doi", "") or "").lower()] = entry["key"]
        by_title[_norm_title(entry["fields"].get("title", ""))] = entry["key"]
    for passage in passages:
        key = by_doi.get((passage.get("doi") or "").lower(), "")
        if not key:
            key = by_title.get(_norm_title(passage.get("title", "")), "")
        passage["key"] = key

    return draft_name, passages, entries


if __name__ == "__main__":
    raise SystemExit(main())
