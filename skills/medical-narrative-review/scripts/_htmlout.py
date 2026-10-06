"""Render the document model as print-ready HTML.

The HTML output is the second PDF path: open it in any browser and print to PDF with
page breaks already set. It also displays SVG figures directly, so a figure never has
to be rasterised for this format.

Citations become internal links to the reference entries when the reference list is
part of the document, which is the one interaction DOCX and PDF do not get.
"""

from __future__ import annotations

import re

CITE_RE = re.compile(r"\[([0-9]{1,4}(?:\s*[,\u2013-]\s*[0-9]{1,4})*)\]")
REFERENCE_ENTRY_RE = re.compile(r"^\s*([0-9]{1,3})\.\s+\S")
PAGE_BREAK_SECTIONS = ("references", "appendix")

CSS = """
:root { --ink: #1a1a1a; --muted: #5a5a5a; --rule: #c9c9c9; }
* { box-sizing: border-box; }
body {
  font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, "Times New Roman", serif;
  font-size: 11pt; line-height: 1.5; color: var(--ink);
  margin: 0 auto; max-width: 42rem; padding: 2.5rem 1.25rem 4rem;
  -webkit-font-smoothing: antialiased;
}
h1 { font-size: 1.85rem; line-height: 1.2; margin: 0 0 .35rem; }
h2 { font-size: 1.3rem; margin: 2rem 0 .5rem; padding-bottom: .2rem; border-bottom: 1px solid var(--rule); }
h3 { font-size: 1.08rem; margin: 1.4rem 0 .4rem; }
h4 { font-size: 1rem; margin: 1.1rem 0 .35rem; }
p { margin: 0 0 .7rem; text-align: left; hyphens: auto; }
ul, ol { margin: .2rem 0 .9rem; padding-left: 1.6rem; }
li { margin-bottom: .28rem; }
blockquote { margin: 1rem 1.5rem; padding-left: .9rem; border-left: 3px solid var(--rule); color: var(--muted); }
hr { border: 0; border-top: 1px solid var(--rule); margin: 1.6rem 0; }
code, pre { font-family: "SF Mono", Menlo, Consolas, "Courier New", monospace; font-size: .86em; }
pre { background: #f5f5f5; border: 1px solid var(--rule); padding: .7rem .8rem; overflow-x: auto; white-space: pre-wrap; }
.caption { font-size: .86rem; color: var(--muted); font-style: italic; margin: .2rem 0 .9rem; }
table { border-collapse: collapse; width: 100%; font-size: .82rem; margin: .3rem 0 1.1rem; }
th, td { border: 1px solid var(--rule); padding: .32rem .45rem; vertical-align: top; text-align: left; }
th { background: #efefef; font-weight: 700; }
thead { display: table-header-group; }
tr { page-break-inside: avoid; }
img { max-width: 100%; height: auto; display: block; margin: 1rem auto; }
figure { margin: 1.2rem 0; }
a { color: #1f4e79; text-decoration: none; border-bottom: 1px solid rgba(31,78,121,.3); }
a:hover { border-bottom-color: #1f4e79; }
.references li, .references p { font-size: .92rem; }
.references li:target, .references p:target { background: #fff6cc; }
.meta { color: var(--muted); font-size: .84rem; text-align: center; margin-bottom: 1.2rem; }
.title-block { text-align: center; border-bottom: 1px solid var(--rule); padding-bottom: 1.2rem; margin-bottom: 1.6rem; }
.title-block h1 { margin-bottom: .4rem; }
@media print {
  @page { size: A4; margin: 20mm 20mm 22mm; }
  body { max-width: none; padding: 0; font-size: 10.5pt; }
  a { color: inherit; border-bottom: none; }
  h2.page-break { break-before: page; page-break-before: always; }
  table, pre, img { page-break-inside: avoid; }
}
"""


def esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def runs_html(runs: list, reference_ids: set) -> str:
    output: list = []
    for run in runs:
        text = esc(run.text)
        if not run.code and reference_ids:
            text = CITE_RE.sub(lambda match: link_citations(match, reference_ids), text)
        if run.code:
            text = "<code>%s</code>" % text
        if run.italic:
            text = "<em>%s</em>" % text
        if run.bold:
            text = "<strong>%s</strong>" % text
        if run.link:
            text = '<a href="%s">%s</a>' % (esc(run.link), text)
        output.append(text)
    return "".join(output)


def link_citations(match: re.Match, reference_ids: set) -> str:
    group = match.group(1)
    numbers: list = []
    for part in re.split(r"\s*,\s*", group):
        part = part.strip()
        span = re.fullmatch(r"([0-9]{1,4})\s*[\u2013-]\s*([0-9]{1,4})", part)
        if span:
            low, high = int(span.group(1)), int(span.group(2))
            if high >= low and high - low <= 100:
                numbers.extend(range(low, high + 1))
        elif part.isdigit():
            numbers.append(int(part))
    if not numbers or any(number not in reference_ids for number in numbers):
        return "[%s]" % group
    links = ", ".join(
        '<a href="#ref%d">%d</a>' % (number, number) for number in numbers
    )
    return "[%s]" % links



def collect_reference_ids(blocks: list) -> set:
    identifiers: set = set()
    for block in blocks:
        if block.kind == "list":
            for label, _runs in block.items:
                if label.isdigit():
                    identifiers.add(int(label))
        elif block.kind == "para":
            match = REFERENCE_ENTRY_RE.match(block.plain_text())
            if match:
                identifiers.add(int(match.group(1)))
    return identifiers


def render(blocks: list, meta: dict, figure_svg: str = "") -> tuple:
    reference_ids = collect_reference_ids(blocks)
    parts: list = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>%s</title>" % esc(meta.get("title", "Medical narrative review")),
        "<style>%s</style>" % CSS,
        "</head><body>",
    ]
    warnings: list = []
    section = ""
    first_heading = True
    figure_inserted = False

    for block in blocks:
        kind = block.kind
        if kind == "heading":
            text = block.plain_text()
            section = text.strip().lower()
            if first_heading and block.level == 1:
                parts.append('<header class="title-block">')
                parts.append("<h1>%s</h1>" % runs_html(block.runs, reference_ids))
                for line in meta.get("byline", []):
                    parts.append('<p class="meta">%s</p>' % esc(line))
                parts.append("</header>")
                first_heading = False
                continue
            level = min(max(block.level, 1), 4)
            classes: list = []
            if any(section.startswith(prefix) for prefix in PAGE_BREAK_SECTIONS):
                classes.append("page-break")
            if section.startswith("reference"):
                classes.append("references")
            attribute = ' class="%s"' % " ".join(classes) if classes else ""
            parts.append(
                "<h%d%s>%s</h%d>"
                % (level, attribute, runs_html(block.runs, reference_ids), level)
            )
        elif kind in ("para", "caption", "quote"):
            if kind == "caption":
                parts.append('<p class="caption">%s</p>' % runs_html(block.runs, reference_ids))
            elif kind == "quote":
                parts.append("<blockquote>%s</blockquote>" % runs_html(block.runs, reference_ids))
            elif section.startswith("reference") and REFERENCE_ENTRY_RE.match(block.plain_text()):
                number = int(REFERENCE_ENTRY_RE.match(block.plain_text()).group(1))
                parts.append(
                    '<p class="references" id="ref%d">%s</p>'
                    % (number, runs_html(block.runs, reference_ids))
                )
            else:
                parts.append("<p>%s</p>" % runs_html(block.runs, reference_ids))
        elif kind == "list":
            ordered = bool(block.items) and all(label.isdigit() for label, _ in block.items)
            tag = "ol" if ordered else "ul"
            classes = ' class="references"' if section.startswith("reference") else ""
            parts.append("<%s%s>" % (tag, classes))
            for label, runs in block.items:
                attribute = ""
                if section.startswith("reference") and label.isdigit():
                    attribute = ' id="ref%s"' % label
                parts.append("<li%s>%s</li>" % (attribute, runs_html(runs, reference_ids)))
            parts.append("</%s>" % tag)
        elif kind == "table":
            if block.label:
                parts.append('<p class="caption">%s</p>' % esc(block.label))
            parts.append("<table><thead><tr>")
            for cell in block.header:
                parts.append("<th>%s</th>" % esc(cell))
            parts.append("</tr></thead><tbody>")
            for row in block.rows:
                parts.append("<tr>")
                for cell in row:
                    parts.append("<td>%s</td>" % esc(cell))
                parts.append("</tr>")
            parts.append("</tbody></table>")
        elif kind == "code":
            parts.append("<pre>%s</pre>" % esc(block.plain_text()))
        elif kind == "rule":
            parts.append("<hr>")
        elif kind == "image":
            if figure_svg and not figure_inserted:
                parts.append(
                    '<figure><img src="%s" alt="%s">'
                    % (esc(figure_svg), esc(block.alt or "figure"))
                )
                if block.alt:
                    parts.append('<figcaption class="caption">%s</figcaption>' % esc(block.alt))
                parts.append("</figure>")
                figure_inserted = True
            else:
                parts.append('<p class="caption">[figure: %s]</p>' % esc(block.path or block.alt))
    if figure_svg and not figure_inserted:
        parts.append(
            '<figure class="page-break"><img src="%s" alt="Screening flow diagram">' % esc(figure_svg)
        )
        parts.append(
            '<figcaption class="caption">Screening flow of records identified, screened, and '
            "included. Counts come from prisma_counts.json and are checked arithmetically before "
            "the figure is drawn.</figcaption></figure>"
        )
    if not reference_ids:
        warnings.append("no reference list found: citations are not linked")
    parts.append("</body></html>")
    return "\n".join(parts) + "\n", {
        "format": "html",
        "reference_entries": len(reference_ids),
        "warnings": warnings,
    }
