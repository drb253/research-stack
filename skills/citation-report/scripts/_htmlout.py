"""Render the citation report as one self-contained, print-ready HTML file.

HTML is the third renderer of the same span model (see `_highlight.py`), and it exists
for the one thing the other two cannot do: a coloured span and its explanation can
live in the same artifact without shrinking the page. PDF and DOCX must either push
the note into a margin or hide it in a comment layer; here the span links to a full
note in an appendix, and the printed page still carries every note.

Three rules shape the whole module:

* **Nothing informative is hover-only.** Every coloured span is followed by a numbered
  ``<sup>`` anchor, and every anchor has a note with a back-link. The ``title``
  attribute is a convenience on top of that, never the only copy of a note.
* **Self-contained means self-contained.** One inline ``<style>``, no script, no
  font, no image, no ``href`` to any host. The file has to render and print from a
  directory with no network, with its highlight colours intact: hence
  ``print-color-adjust: exact`` under ``@media print`` and no external anything.
* **Document text is data.** Every value that came from the document, the ledger or a
  verdict is passed through `html.escape(..., quote=True)` before it reaches the
  output. That includes note text and titles, where one unescaped quote would end an
  attribute and let a document title change the shape of the report.

Determinism is a requirement, not a nicety: the same inputs must produce the same
bytes, so nothing here reads the clock, the environment, or a hash ordering. All
iteration follows document order, `_highlight.STATE_ORDER`, or the bundle's own
source order.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

import _highlight
import coverage

#: Printed in the footer. The artifact may be copied out of the run directory, so the
#: page itself has to name the program that produced it.
TOOL_NAME = "citation-report"

#: The gate banner, verbatim. A report that says "fail" has to say what that means,
#: and the wording is fixed so two runs cannot describe the same state differently.
GATE_FAILURE = (
    "REPORT NOT GATE CLEAN \u2014 errors present. "
    "This document is a diagnostic, not a clearance."
)

#: A bar segment narrower than this percentage is drawn at this width instead, so the
#: count printed inside it cannot vanish. The bar is renormalised afterwards; the
#: caption states the trade so no reader has to guess why widths are not exact.
MIN_BAR_SHARE = 2.5

#: The single stylesheet. Inline by requirement: a ``<link>`` would make the file
#: depend on a path or a host that may not exist where it is read. The print block
#: keeps the highlight tints on paper and breaks before each appendix.
CSS = """
:root { --ink: #1a1a1a; --muted: #565656; --rule: #c9c9c9; --paper: #ffffff; --wash: #f6f6f4; }
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, "Times New Roman", serif;
  font-size: 11pt; line-height: 1.65; color: var(--ink); background: var(--paper);
  margin: 0 auto; max-width: 46rem; padding: 2.5rem 1.35rem 4rem;
  -webkit-font-smoothing: antialiased;
}
h1 { font-size: 1.9rem; line-height: 1.18; margin: 0 0 .3rem; }
h2.section-h {
  font-size: 1.25rem; margin: 2.2rem 0 .6rem;
  padding-bottom: .2rem; border-bottom: 1px solid var(--rule);
}
h3, h4, h5, h6 { margin: 1.3rem 0 .4rem; }
p { margin: 0 0 .7rem; }
a { color: #1f4e79; text-decoration: none; border-bottom: 1px solid rgba(31,78,121,.35); }
a:hover { border-bottom-color: #1f4e79; }
.report-header { border-bottom: 2px solid var(--rule); padding-bottom: 1rem; margin-bottom: 1.4rem; }
.subtitle { color: var(--muted); font-size: .95rem; margin: 0 0 .9rem; }
dl.meta { display: grid; grid-template-columns: max-content 1fr; gap: .18rem .9rem; margin: 0; font-size: .9rem; }
dl.meta dt { color: var(--muted); }
dl.meta dd { margin: 0; overflow-wrap: anywhere; }
.gate { border: 3px solid #d66959; background: #fdecea; padding: .8rem 1rem; margin: 0 0 1.4rem; }
.gate-stamp { font-weight: 700; letter-spacing: .08em; color: #8a2b1d; margin: 0 0 .3rem; font-size: .82rem; }
.gate-text { font-weight: 700; margin: 0; }
/* Deliberately not the gate colour: an input gap is not a finding about the document. */
.inputbound { border: 3px dashed #4a5a8a; background: #eef1f8; padding: .8rem 1rem; margin: 0 0 1.4rem; }
.inputbound-stamp { font-weight: 700; letter-spacing: .08em; color: #2f3a5c; margin: 0 0 .3rem; font-size: .82rem; }
.inputbound-text { font-weight: 700; margin: 0 0 .35rem; }
.inputbound-reason { margin: 0 0 .25rem; font-size: .9rem; color: #2f3a5c; }
.coverage-bar { display: flex; width: 100%; border: 1px solid var(--rule); }
.bar-seg {
  display: flex; align-items: center; justify-content: center; gap: .35rem;
  height: 2.2rem; min-width: 0; overflow: hidden; white-space: nowrap;
  font-size: .78rem; line-height: 1;
}
.bar-count { font-weight: 700; }
.bar-label { font-size: .68rem; }
.empty { color: var(--muted); font-style: italic; }
.caption { font-size: .84rem; color: var(--muted); margin: .35rem 0 1rem; }
table { border-collapse: collapse; width: 100%; font-size: .84rem; margin: .2rem 0 1.1rem; }
th, td { border: 1px solid var(--rule); padding: .32rem .45rem; vertical-align: top; text-align: left; }
thead th { background: var(--wash); }
thead { display: table-header-group; }
tr { break-inside: avoid; page-break-inside: avoid; }
.swatch { display: inline-block; width: 1.15rem; height: 1.15rem; border: 1px solid var(--rule); vertical-align: -.2rem; }
.swatch-cell { width: 2.2rem; }
.document { margin-top: .6rem; }
.doc-h { margin: 1.5rem 0 .45rem; }
.doc-list-item { padding-left: 1.2rem; text-indent: -1.2rem; }
.doc-list-item::before { content: "\\2022\\00a0\\00a0"; }
.doc-reference { font-size: .9rem; padding-left: 1.4rem; text-indent: -1.4rem; }
.doc-table { white-space: pre-wrap; font-size: .88rem; }
.doc-code, pre {
  font-family: "SF Mono", Menlo, Consolas, "Courier New", monospace;
  font-size: .84em; white-space: pre-wrap; margin: 0 0 .7rem;
}
blockquote { margin: .9rem 0 .9rem 1.2rem; padding-left: .85rem; border-left: 3px solid var(--rule); color: var(--muted); }
.v { border-radius: 2px; padding: 0 .08em; }
sup.note-ref { font-size: .68em; line-height: 0; margin-left: .08em; }
sup.note-ref a { border-bottom: none; text-decoration: none; }
.limits, .sources, .notes { margin-top: 2rem; }
.limits ul, .warnings { padding-left: 1.1rem; }
.limits li, .warnings li { margin-bottom: .4rem; }
.note {
  border-left: 4px solid var(--rule); background: var(--wash);
  padding: .4rem .7rem .5rem .8rem; margin: 0 0 .7rem;
  font-size: .84rem; line-height: 1.45;
}
.note-head { margin: 0 0 .3rem; font-weight: 700; }
.note-state { font-weight: 400; color: var(--muted); }
.note-body { margin: 0 0 .3rem; font-family: inherit; font-size: 1rem; white-space: pre-wrap; }
.note-back { margin: 0; font-size: .8rem; }
.muted { color: var(--muted); font-weight: 400; }
.flag-error { color: #8a2b1d; font-weight: 700; }
.report-footer {
  border-top: 1px solid var(--rule); margin-top: 2.5rem;
  padding-top: .7rem; color: var(--muted); font-size: .82rem;
}
@media print {
  @page { size: A4; margin: 18mm 16mm 20mm; }
  * { print-color-adjust: exact; -webkit-print-color-adjust: exact; }
  body { max-width: none; padding: 0; font-size: 10.5pt; }
  a { color: inherit; border-bottom: none; }
  .page-break { break-before: page; page-break-before: always; }
  .note, .gate, table, pre, blockquote { break-inside: avoid; page-break-inside: avoid; }
  h2.section-h { break-after: avoid; page-break-after: avoid; }
}
"""


@dataclass
class _Note:
    """One rendered note, and the number its marker and its back-link share.

    Carrying the number here rather than recomputing it keeps the span, the anchor
    and the appendix note from ever disagreeing about which note is which.
    """

    number: int
    verdict: object


def esc(value) -> str:
    """Escape any document-derived value for both text and attribute contexts.

    ``quote=True`` is mandatory, not defensive: note text is emitted into
    ``title="..."`` attributes, so an unescaped ``"`` would end the attribute early
    and let a document title inject markup into the report.
    """
    return html.escape("" if value is None else str(value), quote=True)


def _text(value) -> str:
    """A display string for an optional metadata value, empty rather than ``None``."""
    return "" if value is None else str(value)


def render(layout, summary, bundle, meta) -> tuple:
    """Return ``(html_bytes, report_dict)`` for one citation report.

    The byte payload is complete: it opens with a doctype and closes ``</html>``, so
    a caller only has to write it to disk. The report dict records what the renderer
    actually emitted (``highlights`` spans, ``notes`` title attributes, ``segments``
    in the layout) so a caller can check the artifact against its own ledger instead
    of trusting the markup.
    """
    meta = meta or {}
    notes: list = []
    warnings: list = []
    parts: list = []

    title = _text(meta.get("title")).strip() or "Citation report"
    document_path = _text(meta.get("document_path"))
    generated = _text(meta.get("generated"))
    gate_status = _text(meta.get("gate_status")).strip().lower()
    advisory_enabled = bool(meta.get("advisory_enabled"))

    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="en">')
    parts.append("<head>")
    parts.append('<meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    parts.append("<title>%s</title>" % esc(title))
    parts.append("<style>%s</style>" % CSS)
    parts.append("</head>")
    parts.append("<body>")

    _emit_header(parts, title, document_path, generated, summary)
    if gate_status == "fail":
        _emit_gate(parts)
    _emit_input_bound(parts, meta)
    _emit_coverage(parts, summary)
    _emit_legend(parts)
    highlights, segments = _emit_document(parts, layout, notes, warnings)
    _emit_limits(parts, bundle, meta, advisory_enabled)
    _emit_sources(parts, bundle, warnings)
    _emit_notes(parts, notes)
    _emit_footer(parts, generated)

    parts.append("</body>")
    parts.append("</html>")

    if highlights != len(notes):
        warnings.append(
            "rendered %d highlight span(s) but %d note(s): the anchor numbering "
            "and the appendix have drifted apart" % (highlights, len(notes))
        )
    if highlights != segments:
        warnings.append(
            "rendered %d highlight span(s) for %d segment(s): an empty verdict span "
            "was dropped, so some sentences carry no note marker" % (highlights, segments)
        )
    if not notes:
        warnings.append("no graded segments: nothing in the document body is highlighted")

    payload = ("\n".join(parts) + "\n").encode("utf-8")
    report = {
        "format": "html",
        "bytes": len(payload),
        "highlights": highlights,
        "notes": len(notes),
        "segments": segments,
        "warnings": warnings,
    }
    return payload, report


def _emit_header(parts, title, document_path, generated, summary) -> None:
    """Title plus the metadata a reader needs to reproduce every number below it."""
    coverage_info = summary.get("citation_coverage", {}) or {}
    numerator = coverage_info.get("numerator", 0)
    denominator = coverage_info.get("denominator", 0)
    percent = coverage_info.get("percent", 0.0)
    definition = _text(coverage_info.get("definition"))
    rows = [
        ("Source document", document_path or "unknown"),
        ("Generated", generated or "unknown"),
        ("Sentences graded", str(summary.get("sentences_total", 0))),
        ("Requiring a citation", str(summary.get("sentences_requiring_citation", 0))),
        (
            "Citation coverage",
            "%s/%s (%.1f%%) \u2014 %s" % (numerator, denominator, percent, definition),
        ),
    ]
    parts.append('<header class="report-header">')
    parts.append("<h1>%s</h1>" % esc(title))
    parts.append('<p class="subtitle">Citation attribution report</p>')
    parts.append('<dl class="meta">')
    for label, value in rows:
        parts.append("<dt>%s</dt><dd>%s</dd>" % (esc(label), esc(value)))
    parts.append("</dl>")
    parts.append("</header>")


def _emit_gate(parts) -> None:
    """The failure banner. Present whenever the caller reports a failing gate."""
    parts.append('<section class="gate" role="alert">')
    parts.append('<p class="gate-stamp">GATE: FAIL</p>')
    parts.append('<p class="gate-text">%s</p>' % esc(GATE_FAILURE))
    parts.append("</section>")


def _emit_input_bound(parts, meta) -> None:
    """The input banner, deliberately distinct from the gate banner.

    A gate failure is a finding about the document. This is a statement that the
    inputs were not sufficient to make findings, and it must not be mistakable for
    either a pass or a failure -- so it gets its own stamp, colour and wording, and it
    is emitted even when the gate also failed.
    """
    banner = _text(meta.get("input_bound_banner"))
    if not banner:
        return
    parts.append('<section class="inputbound" role="alert">')
    parts.append('<p class="inputbound-stamp">INPUT-BOUND</p>')
    parts.append('<p class="inputbound-text">%s</p>' % esc(banner))
    reason = _text(meta.get("input_bound_reason"))
    if reason:
        parts.append('<p class="inputbound-reason">%s</p>' % esc(reason))
    evidence = meta.get("evidence") or {}
    if evidence:
        parts.append(
            '<p class="inputbound-reason">cited sources: %s; checkable: %s; '
            "sentences that cite an unreadable source: %s; of those asserting a "
            "checkable value: %s</p>"
            % (
                esc(_text(evidence.get("citing_sources"))),
                esc(_text(evidence.get("citing_sources_checkable"))),
                esc(_text(evidence.get("unverifiable_sentences"))),
                esc(_text(evidence.get("undecided_sentences"))),
            )
        )
    parts.append("</section>")


def _bar_segments(summary: dict) -> list:
    """``(state, width_percent)`` pairs for the coverage bar, in legend order.

    `coverage.bar_segments` supplies the proportional spans and drops empty states;
    this adds the legibility floor and renormalises, so the widths still sum to 100%
    and the count printed in each segment stays readable. The footer caption states
    the floor, because a bar that quietly distorts its own proportions would be the
    kind of decoration this report exists to avoid.
    """
    order = {state: index for index, state in enumerate(_highlight.STATE_ORDER)}
    floored = [
        (state, max(span, MIN_BAR_SHARE))
        for state, _x, span, _share in coverage.bar_segments(summary, width=100.0)
    ]
    total = sum(span for _state, span in floored)
    if not total:
        return []
    scale = 100.0 / total
    floored.sort(key=lambda row: order.get(row[0], len(order)))
    return [(state, span * scale) for state, span in floored]


def _emit_coverage(parts, summary) -> None:
    """The stacked bar: one segment per non-empty state, count printed inside it."""
    states = summary.get("states", {}) or {}
    segments = _bar_segments(summary)
    parts.append('<section class="coverage">')
    parts.append('<h2 class="section-h">Coverage</h2>')
    if segments:
        parts.append('<div class="coverage-bar">')
        for state, width in segments:
            parts.append(
                '<span class="bar-seg" style="background:#%s;width:%.4f%%">'
                '<span class="bar-count">%d</span>'
                '<span class="bar-label">%s</span></span>'
                % (
                    esc(_highlight.state_hex(state)),
                    width,
                    int(states.get(state, 0)),
                    esc(_highlight.state_label(state)),
                )
            )
        parts.append("</div>")
    else:
        parts.append('<p class="empty">No sentences were graded, so there is no bar.</p>')
    parts.append(
        '<p class="caption">Each segment is one verdict state and the number printed '
        "in it is its sentence count. Widths are proportional, with a %.1f%% floor so "
        "a small count stays readable; states with no sentences are omitted here and "
        "still listed in the legend.</p>" % MIN_BAR_SHARE
    )
    caveat = _text(summary.get("coverage_caveat"))
    if caveat:
        parts.append('<p class="caveat">%s</p>' % esc(caveat))
    parts.append("</section>")


def _emit_legend(parts) -> None:
    """The legend, straight from the one palette so paint and key cannot disagree."""
    parts.append('<section class="legend">')
    parts.append('<h2 class="section-h">Legend</h2>')
    parts.append(
        "<table><thead><tr>"
        "<th>Colour</th><th>State</th><th>Meaning</th><th>Gate severity</th>"
        "</tr></thead><tbody>"
    )
    for row in _highlight.legend_rows():
        parts.append("<tr>")
        parts.append(
            '<td class="swatch-cell"><span class="swatch" style="background:#%s"></span></td>'
            % esc(row["hex"])
        )
        parts.append(
            '<th scope="row">%s <span class="muted">(%s)</span></th>'
            % (esc(row["label"]), esc(row["state"]))
        )
        parts.append("<td>%s</td>" % esc(row["meaning"]))
        parts.append("<td>%s</td>" % esc(row["severity"]))
        parts.append("</tr>")
    parts.append("</tbody></table>")
    parts.append("</section>")


def _inline(text: str, segments: list, notes: list) -> tuple:
    """Render one paragraph's text, painting each segment and numbering its note.

    Returns ``(markup, span_count)``. Boundaries come from
    `_highlight.split_at_segments`, which drops empty pieces; an empty verdict span
    would therefore lose its note and renumber every later one, so the caller
    cross-checks the span count against the segment count and warns if they differ.
    """
    rendered: list = []
    spans = 0
    for piece_text, segment in _highlight.split_at_segments(text, segments):
        if segment is None:
            rendered.append(esc(piece_text))
            continue
        number = len(notes) + 1
        notes.append(_Note(number=number, verdict=segment.verdict))
        spans += 1
        state = segment.state
        rendered.append(
            '<span class="v v-%s" style="background:#%s" title="%s">%s</span>'
            '<sup class="note-ref"><a href="#note-%d" id="ref-%d">%d</a></sup>'
            % (
                esc(state),
                esc(_highlight.state_hex(state)),
                esc(_highlight.note_text(segment.verdict)),
                esc(piece_text),
                number,
                number,
                number,
            )
        )
    return "".join(rendered), spans


def _emit_document(parts, layout, notes: list, warnings: list) -> tuple:
    """The document body, in order, with headings sized by their own level."""
    parts.append('<main class="document">')
    highlights = 0
    segments = 0
    unknown_kinds: list = []
    for item in layout:
        paragraph = item.paragraph
        kind = _text(paragraph.kind)
        inline, spans = _inline(paragraph.text or "", item.segments or [], notes)
        highlights += spans
        segments += len(item.segments or [])
        if kind == "heading":
            level = max(1, min(int(paragraph.level or 1), 6))
            parts.append('<h%d class="doc-h">%s</h%d>' % (level, inline, level))
        elif kind == "quote":
            parts.append("<blockquote>%s</blockquote>" % inline)
        elif kind == "list_item":
            parts.append('<p class="doc-list-item">%s</p>' % inline)
        elif kind == "caption":
            parts.append('<p class="caption">%s</p>' % inline)
        elif kind == "table":
            parts.append('<p class="doc-table">%s</p>' % inline)
        elif kind == "code":
            parts.append('<pre class="doc-code">%s</pre>' % inline)
        elif kind == "reference":
            parts.append('<p class="doc-reference">%s</p>' % inline)
        elif kind in ("para", ""):
            parts.append("<p>%s</p>" % inline)
        else:
            if kind not in unknown_kinds:
                unknown_kinds.append(kind)
            parts.append("<p>%s</p>" % inline)
    parts.append("</main>")
    if unknown_kinds:
        warnings.append(
            "unknown paragraph kind(s) rendered as plain paragraphs: "
            + ", ".join(sorted(unknown_kinds))
        )
    return highlights, segments


def _emit_limits(parts, bundle, meta, advisory_enabled: bool) -> None:
    """What the colours do and do not claim. Stated once, in full, on the page."""
    bullets = [
        "The colours describe attribution integrity only: whether a sentence's "
        "checkable content is present in the evidence held for the source it cites.",
        "Unverifiable here means no evidence was held for the cited source. It is a "
        "statement about this report's inputs, not a finding about the sentence.",
        "Advisory grades are model-generated and advisory: they never gate inputs. "
        "They cannot create, change or clear a verdict, and the gate reads "
        "deterministic states only.",
        "Coverage counts only sentences that require a citation: coverage = "
        "(attributed + synthesis) / sentences requiring a citation. Unverifiable "
        "sentences sit in neither the numerator nor the denominator and are reported "
        "separately.",
        "This is not a plagiarism report and not an AI-writing detector. It does not "
        "compare text against a corpus, and it does not estimate authorship or "
        "whether a machine wrote the document.",
    ]
    if getattr(bundle, "offline", False):
        bullets.append(
            "This run was offline: no DOI was resolved over the network, so sources "
            "are graded on locally held evidence only."
        )
    if not advisory_enabled:
        bullets.append(
            "Advisory grading was not enabled for this run; any advisory line quoted "
            "in a note came from the input and still does not gate."
        )
    parts.append('<section class="limits">')
    parts.append('<h2 class="section-h">What these colours mean, and what they do not</h2>')
    parts.append("<ul>")
    for bullet in bullets:
        parts.append("<li>%s</li>" % esc(bullet))
    parts.append("</ul>")
    warnings = [_text(item) for item in (meta.get("warnings") or []) if _text(item).strip()]
    if warnings:
        parts.append('<h3>Warnings recorded while reading the inputs</h3>')
        parts.append('<ul class="warnings">')
        for warning in warnings:
            parts.append("<li>%s</li>" % esc(warning))
        parts.append("</ul>")
    parts.append("</section>")


def _emit_sources(parts, bundle, warnings: list) -> None:
    """The sources appendix: what was cited, and how much of it we could check."""
    sources = list(getattr(bundle, "sources", []) or [])
    parts.append('<section class="page-break sources">')
    parts.append('<h2 class="section-h">Sources</h2>')
    if not sources:
        warnings.append("no sources in the bundle: the sources appendix is empty")
        parts.append(
            '<p class="empty">No sources were supplied with this document, so no '
            "citation could resolve to one.</p>"
        )
        parts.append("</section>")
        return
    parts.append(
        "<table><thead><tr>"
        "<th>Source</th><th>Number / citekey</th><th>DOI</th><th>Title</th>"
        "<th>Year</th><th>Verification</th><th>Retraction</th><th>Evidence held</th>"
        "</tr></thead><tbody>"
    )
    for source in sources:
        marker = ""
        if source.citation_number:
            marker = "[%s]" % source.citation_number
        if source.citekey:
            marker = (marker + " " + source.citekey).strip()
        title = source.title or source.title_claimed
        title_cell = esc(title) if title else "\u2014"
        if source.title and source.title_claimed:
            if source.title.strip().casefold() != source.title_claimed.strip().casefold():
                title_cell += ' <span class="muted">(claimed: %s)</span>' % esc(
                    source.title_claimed
                )
        verification = source.verification_status or "\u2014"
        verification_cell = esc(verification)
        if verification == "failed":
            verification_cell = '<span class="flag-error">%s</span>' % verification_cell
        retraction = source.retraction_status or "\u2014"
        retraction_cell = esc(retraction)
        if retraction in ("retracted", "expression_of_concern"):
            retraction_cell = '<span class="flag-error">%s</span>' % retraction_cell
        parts.append("<tr>")
        parts.append("<td>%s</td>" % esc(source.source_id or "\u2014"))
        parts.append("<td>%s</td>" % (esc(marker) if marker else "\u2014"))
        parts.append("<td>%s</td>" % (esc(source.doi) if source.doi else "\u2014"))
        parts.append("<td>%s</td>" % title_cell)
        parts.append("<td>%s</td>" % (esc(source.year) if source.year else "\u2014"))
        parts.append("<td>%s</td>" % verification_cell)
        parts.append("<td>%s</td>" % retraction_cell)
        parts.append(
            "<td>%s</td>"
            % (esc(source.evidence_availability) if source.evidence_availability else "\u2014")
        )
        parts.append("</tr>")
    parts.append("</tbody></table>")
    parts.append("</section>")


def _emit_notes(parts, notes: list) -> None:
    """The notes appendix: every note in full, each linked back to its marker."""
    parts.append('<section class="page-break notes">')
    parts.append('<h2 class="section-h">Notes</h2>')
    parts.append(
        '<p class="caption">Every note, in the order its highlight appears in the '
        "document. Each note links back to its number in the text, so a printed copy "
        "loses nothing that the screen showed on hover.</p>"
    )
    if not notes:
        parts.append('<p class="empty">No sentence was graded, so there are no notes.</p>')
    for note in notes:
        verdict = note.verdict
        state = _text(getattr(verdict, "state", ""))
        parts.append(
            '<div class="note" id="note-%d" style="border-left-color:#%s">'
            % (note.number, esc(_highlight.state_hex(state)))
        )
        parts.append(
            '<p class="note-head">Note %d \u00b7 %s \u00b7 %s '
            '<span class="note-state">%s</span></p>'
            % (
                note.number,
                esc(verdict.sentence_id),
                esc(verdict.rule_id),
                esc(state),
            )
        )
        parts.append('<pre class="note-body">%s</pre>' % esc(_highlight.note_text(verdict)))
        parts.append(
            '<p class="note-back"><a href="#ref-%d">Back to the highlighted sentence</a></p>'
            % note.number
        )
        parts.append("</div>")
    parts.append("</section>")


def _emit_footer(parts, generated: str) -> None:
    """Footer: tool name and generated date, so a printed page is traceable."""
    parts.append('<footer class="report-footer">')
    parts.append(
        "<p>%s \u00b7 HTML citation report \u00b7 generated %s</p>"
        % (esc(TOOL_NAME), esc(generated or "unknown"))
    )
    parts.append("</footer>")
