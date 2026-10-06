#!/usr/bin/env python3
"""Item 4 - research & synthesis scaffolding over a corpus you already have.

Extracts the heading structure and word counts from a folder of drafts, and
emits (a) an outline and (b) a notes skeleton pairing each section with the
prompts you need: key claims, sources needed, and your own observations. This is
the "make original writing easier" half - it maps what exists so writing starts
from structure, not a blank page.

    python3 outline.py ../agentic-ai-phc-india-systematic-review --out outline.md \\
        --notes notes.md

Reads .md, .txt and .html (tags stripped). Stdlib only.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

import htmltext

TEXT_EXT = {".md", ".markdown", ".txt", ".html", ".htm"}
SKIP_DIRS = {".git", "__pycache__", ".cache", "node_modules", "figures"}


def _clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"&[a-z]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_sections(path, keep_tables=False):
    """Return [(level, heading, body_text)] for one file."""
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        raw = handle.read()

    if htmltext.is_html(path):
        # Strip scripts/styles/chrome and (by default) tables before looking for
        # headings, so a research-question table cannot leak in as prose.
        cleaned = htmltext.clean_html(raw, drop_tables=not keep_tables)
        sections = []
        for match in re.finditer(
            r"<h([1-6])[^>]*>(.*?)</h\1>(.*?)(?=<h[1-6][^>]*>|\Z)", cleaned, re.S | re.I
        ):
            sections.append((
                int(match.group(1)),
                _clean(re.sub(r"<[^>]+>", " ", match.group(2))),
                htmltext.to_text(match.group(3), drop_tables=not keep_tables),
            ))
        if sections:
            return sections
        return [(1, os.path.basename(path),
                 htmltext.to_text(cleaned, drop_tables=not keep_tables))]

    sections, current = [], (1, os.path.basename(path), [])
    for line in raw.splitlines():
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            if current[2]:
                sections.append((current[0], current[1], _clean(" ".join(current[2]))))
            current = (len(heading.group(1)), _clean(heading.group(2)), [])
        else:
            current[2].append(line)
    if current[2]:
        sections.append((current[0], current[1], _clean(" ".join(current[2]))))
    return sections


def collect(root):
    if os.path.isfile(root):
        return [root]
    found = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in sorted(files):
            if os.path.splitext(name)[1].lower() in TEXT_EXT:
                found.append(os.path.join(base, name))
    return found


def render_outline(root, files_sections):
    is_dir = os.path.isdir(root)
    total = sum(len(section[2].split()) for _, sections in files_sections for section in sections)
    lines = [
        "# Corpus outline — %s" % root,
        "",
        "**%d files, %d words total.**" % (len(files_sections), total),
        "",
    ]
    for path, sections in files_sections:
        label = os.path.relpath(path, root) if is_dir else path
        words = sum(len(section[2].split()) for section in sections)
        lines.append("## %s  (%d words)" % (label, words))
        lines.append("")
        for level, heading, body in sections:
            indent = "  " * max(0, level - 1)
            lines.append("%s- %s  _(%d words)_" % (indent, heading, len(body.split())))
        lines.append("")
    return "\n".join(lines)


def render_notes(root, files_sections, max_level=2):
    lines = [
        "# Notes skeleton — %s" % root,
        "",
        "Fill each section as you read. The *Sources needed* box is what keeps the",
        "final draft defensible: every claim that is not yours gets a citation",
        "here, before it reaches the prose.",
        "",
        "Workflow: **literature-review** skill to find sources ->",
        "**citation-management** (`extract_metadata.py`, `doi_to_bibtex.py`) to",
        "produce verified BibTeX -> `cite_fix.py` to attach the in-text citation.",
        "See RUNBOOK_research.md.",
        "",
    ]
    seen = set()
    for _path, sections in files_sections:
        for level, heading, _body in sections:
            if level > max_level or heading in seen:
                continue
            seen.add(heading)
            lines.extend([
                "## %s" % heading,
                "",
                "- **Key claims:**",
                "- **Sources needed:** _(author, year -> bib key)_",
                "- **Evidence / numbers:**",
                "- **My own observation (no citation needed):**",
                "- **Open questions:**",
                "",
            ])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("roots", nargs="+", help="folders or files to map")
    parser.add_argument("--out", default="outline.md")
    parser.add_argument("--notes", default=None, help="also write a notes skeleton here")
    parser.add_argument("--max-level", type=int, default=2, help="notes: heading depth")
    parser.add_argument("--keep-tables", action="store_true",
                        help="keep <table> content (dropped by default)")
    args = parser.parse_args(argv)

    files_sections = []
    for root in args.roots:
        for path in collect(root):
            sections = extract_sections(path, keep_tables=args.keep_tables)
            if sections:
                files_sections.append((path, sections))
    if not files_sections:
        sys.stderr.write("no readable text files found in: %s\n" % ", ".join(args.roots))
        return 1

    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(render_outline(args.roots[0], files_sections))
    print("Wrote outline -> %s (%d files)" % (args.out, len(files_sections)))

    if args.notes:
        with open(args.notes, "w", encoding="utf-8") as handle:
            handle.write(render_notes(args.roots[0], files_sections, args.max_level))
        print("Wrote notes skeleton -> %s" % args.notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
