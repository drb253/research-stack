"""Lay the graded span model out as a PDF diagnostic.

Two commitments shape this module, and both come from the same failure: a report
that marks up a document in a way the reader cannot see is worse than no report.

* **The highlights are painted, and the notes are printed.** The colour is a filled
  rectangle written immediately before the glyphs of the line it sits behind, and
  every note is ordinary text in a reserved right-hand column. Nothing here depends
  on `/Annots`: an annotation can be filtered away by a viewer, dropped by a print
  pipeline, or simply not shown, and the marking is the entire product.
* **No note may be silently shortened.** A note that does not fit the column is
  continued at the top of the next page's note column, marked `(cont.)`. If the
  continuation still does not fit, the remainder is listed in the Notes appendix and
  counted in `notes_moved_to_appendix`. The appendix repeats every note in full, so
  nothing is ever only available in the margin.

The span offsets handed in are local to `paragraph.text`; the mapping from those
offsets to painted x-extents is recomputed here, line by line, because a wrapped
line can start and end in the middle of a sentence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import _common
import _highlight
from _pdfout import (
    BOTTOM,
    CONTENT_W,
    CONTENT_X,
    MARGIN,
    NOTE_TEXT_W,
    NOTE_TEXT_X,
    NOTE_X,
    PAGE_H,
    PdfCanvas,
    measure,
    split_long_word,
    wrap_text,
)

BODY_SIZE = 9.4
BODY_LEADING = 12.2
CODE_SIZE = 7.6
CODE_LEADING = 9.4
#: Notes sit at the small end of the readable range: 6.8pt is still legible in
#: print, and a wider column would eat the document column the report exists for.
NOTE_SIZE = 6.8
NOTE_LEADING = 8.2
TABLE_SIZE = 6.6
HEADING_SIZES = {1: 15.0, 2: 11.8, 3: 10.4, 4: 9.8}

#: Heading text that starts a back-matter section gets a clean page, mirroring how
#: the source document itself is usually paginated.
PAGE_BREAK_PREFIXES = ("references", "reference list", "bibliography", "appendix")

_MISSING = object()


@dataclass(frozen=True)
class _Style:
    """Typography for one paragraph kind.

    A frozen dataclass rather than a dict of dicts so a typo in a key is an import
    error instead of a silently unstyled paragraph.
    """

    font: str = "F1"
    size: float = BODY_SIZE
    leading: float = BODY_LEADING
    indent: float = 0.0
    space_before: float = 0.0
    space_after: float = 5.0
    marker: str = ""
    rule: bool = False
    gray: float = 0.0


_PARA = _Style()
_LIST_ITEM = _Style(indent=13.0, marker="\u2022")
_QUOTE = _Style(font="F3", indent=14.0, rule=True, space_after=6.0)
_CAPTION = _Style(font="F3", size=8.4, leading=10.8, space_after=5.0)
_TABLE = _Style(font="F5", size=7.0, leading=9.0, space_after=5.0)
_REFERENCE = _Style(size=8.0, leading=10.4, space_after=3.0)

KIND_STYLES = {
    "para": _PARA,
    "list_item": _LIST_ITEM,
    "quote": _QUOTE,
    "caption": _CAPTION,
    "table": _TABLE,
    "reference": _REFERENCE,
}


@dataclass
class _PendingNote:
    """A note that ran out of column mid-way and must resume on the next page."""

    verdict: object
    lines: list = field(default_factory=list)
    printed: bool = False


def _state_colour(state: str):
    """The paint colour for a state, with `state_hex` as the fallback.

    `no_citation_needed` deliberately has no paint colour. Its hex is the paper
    white, so a coverage-bar block for it is a white block rather than a colour
    invented here; the palette stays in `_highlight` and nowhere else.
    """
    rgb = _highlight.state_rgb(state)
    if rgb is not None:
        return rgb
    hex_value = _highlight.state_hex(state)
    return tuple(int(hex_value[index : index + 2], 16) / 255.0 for index in (0, 2, 4))


def _footer_left(meta: dict) -> str:
    path = str(meta.get("document_path") or "").replace("\\", "/")
    name = path.rsplit("/", 1)[-1]
    return "citation report - %s" % name if name else "citation report"


def _tokenize(text: str, segments: list, font: str, size: float, width: float) -> list:
    """Split a paragraph into `(word, segment_or_None)` tokens.

    Words longer than the column are broken at the character level here, before
    wrapping, so an unbreakable DOI or URL cannot push glyphs sideways into the
    note column.
    """
    tokens: list = []
    for piece, segment in _highlight.split_at_segments(text, segments):
        for word in piece.split(" "):
            if not word:
                continue
            for chunk in split_long_word(word, font, size, width):
                tokens.append((chunk, segment))
    return tokens


def _wrap_tokens(tokens: list, font: str, size: float, width: float) -> list:
    """Greedy wrap of tokens into lines, preserving each token's segment."""
    space = measure(" ", font, size)
    lines: list = []
    current: list = []
    used = 0.0
    for text, segment in tokens:
        advance = measure(text, font, size)
        gap = space if current else 0.0
        if current and used + gap + advance > width:
            lines.append(current)
            current = []
            used = 0.0
            gap = 0.0
        current.append((text, segment))
        used += gap + advance
    if current:
        lines.append(current)
    return lines or [[]]


def _truncate(text: str, font: str, size: float, width: float) -> str:
    """Cut a cell value to one line. Used only where the full value is elsewhere."""
    if measure(text, font, size) <= width:
        return text
    budget = width - measure("...", font, size)
    kept: list = []
    used = 0.0
    for char in text:
        advance = measure(char, font, size)
        if used + advance > budget:
            break
        kept.append(char)
        used += advance
    return "".join(kept).rstrip() + "..."


class _Renderer:
    """Owns the page cursors, the note column and every drawing decision."""

    def __init__(self, meta: dict):
        self.meta = meta
        self.canvas = PdfCanvas(footer_left=_footer_left(meta))
        self.y = PAGE_H - MARGIN
        self.note_y = PAGE_H - MARGIN
        self.pending: list = []
        self.moved: set = set()
        self.printed: set = set()
        self.started: set = set()
        self.highlights = 0
        self.segments = 0

    # -- page and column mechanics ----------------------------------------- #

    def ensure(self, needed: float) -> None:
        if self.y - needed < BOTTOM:
            self.new_page()

    def space(self, amount: float) -> None:
        self.y -= amount

    def new_page(self) -> None:
        self.canvas.new_page()
        self.y = PAGE_H - MARGIN
        self.note_y = PAGE_H - MARGIN
        self._drain_pending()

    def _drain_pending(self) -> None:
        """Resume deferred notes at the top of a fresh column.

        A note resumes only once: if it still does not fit, its remainder is
        announced in the appendix instead, so a pathological note can never spin
        the renderer into an unbounded number of pages.
        """
        pending, self.pending = self.pending, []
        for item in pending:
            lines = list(item.lines)
            if item.printed and lines:
                lines = ["(cont.) " + lines[0]] + lines[1:]
            self._write_note(item.verdict, lines, top=self.note_y, allow_queue=False)

    # -- notes ------------------------------------------------------------- #

    def _note_lines(self, verdict) -> list:
        body = _highlight.note_text(verdict)
        return wrap_text(body, "F1", NOTE_SIZE, NOTE_TEXT_W - 6.0)

    def _write_note(self, verdict, lines, top: float, allow_queue: bool) -> None:
        start = min(self.note_y, top)
        room = start - BOTTOM
        fits = int(room // NOTE_LEADING) if room > 0 else 0
        emit = lines if fits >= len(lines) else lines[: max(fits, 0)]
        if emit:
            self._draw_note(verdict.state, emit, start)
            self.note_y = start - len(emit) * NOTE_LEADING - 2.0
            self.printed.add(verdict.sentence_id)
        if len(emit) >= len(lines):
            return
        remainder = lines[len(emit) :]
        if allow_queue:
            self.pending.append(
                _PendingNote(verdict=verdict, lines=remainder, printed=bool(emit))
            )
        else:
            self.moved.add(verdict.sentence_id)

    def _draw_note(self, state: str, lines: list, start: float) -> None:
        height = NOTE_LEADING * len(lines)
        self.canvas.line(
            NOTE_X - 4.0,
            start,
            NOTE_X - 4.0,
            start - height,
            rgb=_state_colour(state),
            weight=0.9,
        )
        for index, text in enumerate(lines):
            baseline = start - NOTE_LEADING * (index + 1) + NOTE_LEADING * 0.24
            self.canvas.text(NOTE_TEXT_X, baseline, text, "F1", NOTE_SIZE, 0.15)

    def _note_for_line(self, pieces: list, top: float) -> None:
        """Start the note of every segment whose first line this is."""
        for _text, segment in pieces:
            if segment is None or id(segment) in self.started:
                continue
            self.started.add(id(segment))
            self._write_note(
                segment.verdict,
                self._note_lines(segment.verdict),
                top=top,
                allow_queue=True,
            )

    # -- text lines -------------------------------------------------------- #

    def _emit_line(self, pieces: list, x0: float, baseline: float, font: str,
                   size: float, gray: float = 0.0) -> None:
        """Paint the line's segment rectangles, then draw the glyphs over them.

        Stream order is the z-order, so the rectangles must be appended first. The
        whole line is drawn as one string so a text extractor sees the sentence
        rather than a heap of words.
        """
        space = measure(" ", font, size)
        runs: list = []
        cursor = x0
        for index, (text, segment) in enumerate(pieces):
            advance = measure(text, font, size)
            if segment is not None:
                if runs and runs[-1][0] is segment:
                    runs[-1][2] = cursor + advance
                else:
                    runs.append([segment, cursor, cursor + advance])
            cursor += advance + (space if index < len(pieces) - 1 else 0.0)
        for segment, start, end in runs:
            rgb = _highlight.state_rgb(segment.state)
            if rgb is None or end <= start:
                continue
            self.canvas.fill_rect(
                start,
                baseline - size * 0.27,
                end - start,
                size * 1.18,
                rgb,
                marker=segment.state,
            )
            self.highlights += 1
        line = " ".join(text for text, _ in pieces)
        if line:
            self.canvas.text(x0, baseline, line, font, size, gray)

    def prose(self, text: str, font: str = "F1", size: float = BODY_SIZE,
              leading: float = None, indent: float = 0.0, gray: float = 0.0,
              space_after: float = 5.0, width: float = CONTENT_W) -> None:
        if not text:
            return
        leading = leading if leading is not None else size * 1.3
        for line in wrap_text(text, font, size, width - indent):
            self.ensure(leading)
            self.y -= leading
            if line:
                self.canvas.text(CONTENT_X + indent, self.y, line, font, size, gray)
        self.space(space_after)

    # -- sections ---------------------------------------------------------- #

    def report_heading(self, text: str, break_before: bool = False) -> None:
        if break_before and self.y < PAGE_H - MARGIN - 40.0:
            self.new_page()
        self.space(9.0)
        self.ensure(30.0)
        self.y -= 15.0
        self.canvas.text(CONTENT_X, self.y, text, "F2", 12.5)
        self.y -= 4.0
        self.canvas.line(
            CONTENT_X, self.y, CONTENT_X + CONTENT_W, self.y, gray=0.4, weight=0.7
        )
        self.space(7.0)

    def _metadata_line(self, label: str, value: str) -> None:
        label_width = 150.0
        lines = wrap_text(value, "F1", 8.8, CONTENT_W - label_width)
        self.ensure(11.0 + (len(lines) - 1) * 10.6)
        self.y -= 11.5
        for index, line in enumerate(lines):
            if index == 0:
                self.canvas.text(CONTENT_X, self.y, label, "F1", 8.4, 0.35)
            self.canvas.text(CONTENT_X + label_width, self.y - index * 10.6, line, "F1", 8.8)
        self.y -= (len(lines) - 1) * 10.6

    def title_block(self, summary: dict, bundle, meta: dict) -> None:
        title = str(meta.get("title") or "Citation report")
        self.space(4.0)
        for line in wrap_text(title, "F2", 17.0, CONTENT_W):
            self.y -= 21.0
            self.canvas.text(CONTENT_X, self.y, line, "F2", 17.0)
        self.canvas.line(
            CONTENT_X, self.y - 5.0, CONTENT_X + CONTENT_W, self.y - 5.0, gray=0.35, weight=0.8
        )
        self.space(12.0)

        coverage = summary["citation_coverage"]
        uncheckable = summary.get("uncheckable") or {}
        self._metadata_line("Source document", str(meta.get("document_path") or "(unknown)"))
        self._metadata_line("Generated", str(meta.get("generated") or "(undated)"))
        self._metadata_line("Gate status", str(meta.get("gate_status") or "unknown"))
        self._metadata_line("Sentences graded", str(summary.get("sentences_total", 0)))
        self._metadata_line(
            "Sentences requiring a citation",
            str(summary.get("sentences_requiring_citation", 0)),
        )
        self._metadata_line(
            "Citation coverage",
            "%d/%d = %.1f%%  (%s)"
            % (
                coverage.get("numerator", 0),
                coverage.get("denominator", 0),
                coverage.get("percent", 0.0),
                coverage.get("definition", ""),
            ),
        )
        if uncheckable:
            self._metadata_line(
                "Uncheckable here",
                "%s/%s (%s)"
                % (
                    uncheckable.get("numerator", 0),
                    uncheckable.get("denominator", 0),
                    uncheckable.get("detail", ""),
                ),
            )
        sources = getattr(bundle, "sources", []) or []
        self._metadata_line(
            "Sources held",
            "%d (%d with evidence; %d retracted)"
            % (
                len(sources),
                sum(
                    1
                    for source in sources
                    if source.evidence_availability in ("full_text", "abstract")
                ),
                sum(1 for source in sources if source.retraction_status == "retracted"),
            ),
        )
        self.space(8.0)

    def gate_banner(self, meta: dict) -> None:
        if str(meta.get("gate_status") or "").lower() != "fail":
            return
        message = (
            "REPORT NOT GATE CLEAN \u2014 errors present. "
            "This document is a diagnostic, not a clearance."
        )
        size = 9.0
        lines = wrap_text(message, "F2", size, CONTENT_W - 12.0)
        height = len(lines) * 11.6 + 8.0
        self.space(9.0)
        self.ensure(height + 6.0)
        top = self.y
        # The banner borrows the conflict state colour: it is the same "stop" the
        # document body uses, and the palette stays in `_highlight`.
        self.canvas.fill_rect(CONTENT_X, top - height, CONTENT_W, height, _state_colour("conflict"))
        baseline = top - 6.5 - size
        for line in lines:
            self.canvas.text(CONTENT_X + 6.0, baseline, line, "F2", size, 1.0)
            baseline -= 11.6
        self.y = top - height
        self.space(11.0)

    def input_bound_banner(self, meta: dict) -> None:
        """The input banner. Deliberately not the gate colour.

        A gate failure is a finding about the document; this says the inputs did not
        allow findings at all. Rendering them in the same colour would invite a reader
        to file both under "problems with the draft", which is the exact confusion this
        banner exists to prevent. It is drawn with a border instead of a solid fill for
        the same reason -- it reads as a caveat, not as a verdict.
        """
        message = str(meta.get("input_bound_banner") or "").strip()
        if not message:
            return
        reason = str(meta.get("input_bound_reason") or "").strip()
        evidence = meta.get("evidence") or {}
        counts = (
            "cited sources: %s; checkable: %s; sentences citing an unreadable source: "
            "%s; of those asserting a checkable value: %s"
            % (
                evidence.get("citing_sources"),
                evidence.get("citing_sources_checkable"),
                evidence.get("unverifiable_sentences"),
                evidence.get("undecided_sentences"),
            )
        )
        size = 9.0
        lines = wrap_text(message, "F2", size, CONTENT_W - 12.0)
        detail_lines = wrap_text(reason, "F1", 8.0, CONTENT_W - 12.0) if reason else []
        count_lines = wrap_text(counts, "F1", 8.0, CONTENT_W - 12.0)
        height = len(lines) * 11.6 + len(detail_lines) * 9.6 + len(count_lines) * 9.6 + 12.0
        self.space(9.0)
        self.ensure(height + 6.0)
        top = self.y
        self.canvas.stroke_rect(CONTENT_X, top - height, CONTENT_W, height, 0.35, 1.2)
        baseline = top - 6.5 - size
        for line in lines:
            self.canvas.text(CONTENT_X + 6.0, baseline, line, "F2", size, 0.0)
            baseline -= 11.6
        for line in detail_lines:
            self.canvas.text(CONTENT_X + 6.0, baseline, line, "F1", 8.0, 0.25)
            baseline -= 9.6
        for line in count_lines:
            self.canvas.text(CONTENT_X + 6.0, baseline, line, "F1", 8.0, 0.25)
            baseline -= 9.6
        self.y = top - height
        self.space(11.0)

    def coverage_section(self, summary: dict) -> None:
        self.report_heading("Coverage")
        self._coverage_bar(summary)
        # The caveat sits directly under the bar, so the figure and the reason it is
        # what it is can never be read apart from each other.
        caveat = str(summary.get("coverage_caveat") or "").strip()
        if caveat:
            for line in wrap_text(caveat, "F2", 8.0, CONTENT_W):
                self.ensure(10.0)
                self.y -= 10.0
                self.canvas.text(CONTENT_X, self.y, line, "F2", 8.0, 0.0)
            self.space(4.0)
        self._legend_table()

    def attribution_section(self, meta: dict) -> None:
        """The defined claim, with its definition and its scope.

        Printed only when the shared definition is installed. The term never appears in
        the artifact without the definition, the scope and the one exception beside it.
        """
        block = (meta or {}).get("attribution") or {}
        statement = str(block.get("statement") or "").strip()
        if not statement:
            return
        self.report_heading(str(block.get("heading") or "The defined claim"))
        for line in block.get("definition") or []:
            self.prose(str(line), font="F1", size=8.6, gray=0.15)
        self.prose(statement, font="F2", size=9.0)
        if "Scope:" not in statement:
            # The boundary is printed even when the statement is withheld, so the
            # reader never meets the term on its own.
            self.prose(str(block.get("scope") or ""), font="F1", size=8.6, gray=0.15)

    def _coverage_bar(self, summary: dict) -> None:
        states = summary.get("states") or {}
        total = summary.get("sentences_total") or sum(states.values()) or 0
        height = 13.0
        self.space(12.0)
        self.ensure(height + 34.0)
        top = self.y
        bar_top = top - 12.0
        bar_bottom = bar_top - height
        self.canvas.fill_rect(CONTENT_X, bar_bottom, CONTENT_W, height, (0.95, 0.95, 0.95))
        cursor = CONTENT_X
        outside: list = []
        for state in _highlight.STATE_ORDER:
            count = states.get(state, 0)
            if not count or not total:
                continue
            width = CONTENT_W * count / total
            rgb = _highlight.state_rgb(state)
            if rgb is not None:
                self.canvas.fill_rect(cursor, bar_bottom, width, height, rgb)
            self.canvas.stroke_rect(cursor, bar_bottom, width, height, 0.55, 0.3)
            label = str(count)
            label_width = measure(label, "F1", 7.0)
            if label_width + 5.0 <= width:
                self.canvas.text(
                    cursor + width / 2.0 - label_width / 2.0,
                    bar_bottom + height / 2.0 - 2.6,
                    label,
                    "F1",
                    7.0,
                )
            else:
                outside.append((cursor + width / 2.0, label))
            cursor += width
        # A count too wide for its own block is printed just above the bar, chained
        # left to right so two narrow blocks can never overprint each other.
        limit = CONTENT_X
        for centre, label in outside:
            width = measure(label, "F1", 6.5)
            x = max(limit, centre - width / 2.0)
            if x + width > CONTENT_X + CONTENT_W:
                x = CONTENT_X + CONTENT_W - width
            self.canvas.text(x, top - 2.0, label, "F1", 6.5, 0.3)
            limit = x + width + 3.0
        self.y = bar_bottom - 3.0
        counts = ", ".join(
            "%s %d" % (state, states.get(state, 0)) for state in _highlight.STATE_ORDER
        )
        self.prose(
            "Segments show all %d graded sentences, in state order: %s." % (total, counts),
            size=8.0,
            leading=10.4,
            gray=0.3,
            space_after=4.0,
        )

    def _legend_table(self) -> None:
        widths = [13.0, 62.0, 208.28, 56.0]
        header = ["", "label (hex)", "what the colour means", "severity"]
        rows: list = []
        fills: dict = {}
        for index, row in enumerate(_highlight.legend_rows()):
            rows.append(
                [
                    "",
                    "%s (%s)" % (row["label"], row["hex"]),
                    row["meaning"],
                    row["severity"],
                ]
            )
            rgb = row["rgb"]
            fills[(index, 0)] = rgb if rgb is not None else (1.0, 1.0, 1.0)
        self.table(widths, header, rows, size=TABLE_SIZE, fills=fills)

    def document_body(self, layout: list) -> None:
        self.report_heading("Document")
        if not layout:
            self.prose("The document contained no paragraphs to render.", gray=0.4)
            return
        for entry in layout:
            paragraph = entry.paragraph
            text = paragraph.text
            if not text or not text.strip():
                continue
            kind = paragraph.kind
            if kind == "heading":
                self._document_heading(paragraph)
            elif kind == "code":
                self._code_block(text)
            else:
                self._flow(entry, KIND_STYLES.get(kind, _PARA))

    def _document_heading(self, paragraph) -> None:
        level = paragraph.level or 1
        level = 1 if level < 1 else min(level, 4)
        size = HEADING_SIZES[level]
        text = paragraph.text.strip()
        lowered = text.lower()
        if (
            level <= 2
            and any(lowered.startswith(prefix) for prefix in PAGE_BREAK_PREFIXES)
            and self.y < PAGE_H - MARGIN - 60.0
        ):
            self.new_page()
        self.space(9.0 if level <= 2 else 5.0)
        self.ensure(size * 2.4)
        for line in wrap_text(text, "F2", size, CONTENT_W):
            self.y -= size * 1.3
            self.canvas.text(CONTENT_X, self.y, line, "F2", size)
        if level == 1:
            self.canvas.line(
                CONTENT_X,
                self.y - size * 0.35,
                CONTENT_X + CONTENT_W,
                self.y - size * 0.35,
                gray=0.4,
                weight=0.7,
            )
        self.space(4.0)

    def _code_block(self, text: str) -> None:
        self.space(2.0)
        for line in wrap_text(text, "F5", CODE_SIZE, CONTENT_W - 16.0):
            self.ensure(CODE_LEADING)
            self.y -= CODE_LEADING
            if line:
                self.canvas.text(CONTENT_X + 8.0, self.y, line, "F5", CODE_SIZE, 0.1)
        self.space(4.0)

    def _flow(self, entry, style: _Style) -> None:
        text = entry.paragraph.text
        width = CONTENT_W - style.indent
        tokens = _tokenize(text, entry.segments, style.font, style.size, width)
        lines = _wrap_tokens(tokens, style.font, style.size, width)
        if style.space_before:
            self.space(style.space_before)
        rule_top = None
        rule_bottom = None
        for index, line in enumerate(lines):
            self.ensure(style.leading)
            self.y -= style.leading
            if style.marker and index == 0:
                self.canvas.text(
                    CONTENT_X + style.indent - 9.0, self.y, style.marker, style.font, style.size
                )
            if style.rule:
                if rule_top is None:
                    rule_top = self.y + style.size * 0.8
                rule_bottom = self.y - style.size * 0.3
            self._emit_line(
                line, CONTENT_X + style.indent, self.y, style.font, style.size, style.gray
            )
            self._note_for_line(line, self.y + style.size * 0.78)
        if style.rule and rule_top is not None:
            self.canvas.line(
                CONTENT_X + 3.0, rule_top, CONTENT_X + 3.0, rule_bottom, gray=0.65, weight=0.6
            )
        self.space(style.space_after)

    def disclosure(self, bundle, meta: dict) -> None:
        self.report_heading("What these colours mean")
        self.prose(
            "The colours describe attribution integrity, not the quality or correctness "
            "of the writing. A coloured span records what this report could establish "
            "about the evidence behind that sentence, and nothing else."
        )
        self.prose(
            "unverifiable means that no evidence was held for the source the sentence "
            "cites, so the claim was never checked. It is not a finding about the "
            "sentence: it is a statement about this report's inputs, and it is counted "
            "separately from both the supported and the unsupported totals."
        )
        self.prose(
            "Advisory grades are model-generated, are advisory, and are never gate "
            "inputs: they cannot set, change or veto a state. Where one is shown it is "
            "labelled with the disclosure \"%s\"." % _common.ADVISORY_DISCLOSURE
        )
        self.prose(
            "Every note printed in the right-hand column is repeated in full in the "
            "Notes appendix, keyed by sentence id, so no reading depends on the margin."
        )

        self.report_heading("Limits")
        self.prose(
            "This report grades the document it was given against the sources and "
            "evidence it was given. It does not search for literature, it does not read "
            "a paper that was not supplied, and it treats an identifier that did not "
            "resolve as identified-only rather than as support."
        )
        evidence = (meta or {}).get("evidence") or {}
        if evidence.get("ocr_transcription_sentences"):
            # Printed in the artifact, not only in the JSON: a reader weighing a finding
            # has to know when the text behind it was a machine's reading.
            self.prose(
                "OCR: %s of the graded sentence(s) rest on a transcription (%s) rather "
                "than on the document's own text layer. A value that appears to "
                "contradict a source is reported as unverifiable rather than as a "
                "finding (rule D13), because a misread digit would make it an "
                "accusation about the author."
                % (
                    evidence.get("ocr_transcription_sentences"),
                    evidence.get("document_transcription") or "OCR",
                )
            )
        if getattr(bundle, "offline", False):
            self.prose(
                "No DOI was resolved over the network for this run: it ran offline, and "
                "every source was graded on the local evidence recorded in the ledger. "
                "An unresolved identifier here says what this run held, not what exists."
            )
        else:
            self.prose(
                "Sources are graded on the evidence recorded in this run; a source with "
                "metadata only was identified but never read, and is reported as such."
            )
        self.prose(
            "A state is set only by the named rules over recorded facts. Where the "
            "report cannot tell, it says so; where it can tell, the rule id is printed "
            "beside every note and every colour is listed in the legend above."
        )
        self.prose(
            "What this report cannot do: it cannot show that an uncited sentence is "
            "wrong, and it cannot show that an attributed sentence is right in a source "
            "it never read. Absence of a highlight is not a statement of quality."
        )

    def sources_appendix(self, bundle) -> None:
        self.report_heading("Sources", break_before=True)
        sources = list(getattr(bundle, "sources", []) or [])
        if not sources:
            self.prose("No sources were supplied to this run.", gray=0.4)
            return
        self.prose(
            "Every source this run held, whether or not a sentence cited it. Titles are "
            "truncated to fit; the full record is in the machine-readable report.",
            size=8.0,
            leading=10.4,
            gray=0.3,
            space_after=3.0,
        )
        size = TABLE_SIZE
        widths = [28.0, 50.0, 62.0, 82.0, 34.0, 39.0, 44.28]
        header = [
            "source",
            "number / citekey",
            "DOI",
            "title (truncated)",
            "verification",
            "retraction",
            "evidence",
        ]
        rows: list = []
        for source in sources:
            data = source.to_dict()
            rows.append(
                [
                    str(data.get("source_id") or ""),
                    str(data.get("citation_number") or data.get("citekey") or "-"),
                    str(data.get("doi") or "-"),
                    _truncate(
                        str(data.get("title") or data.get("title_claimed") or "(untitled)"),
                        "F1",
                        size,
                        widths[3] - 4.0,
                    ),
                    str(data.get("verification_status") or ""),
                    str(data.get("retraction_status") or ""),
                    str(data.get("evidence_availability") or ""),
                ]
            )
        self.table(widths, header, rows, size=size)

    def notes_appendix(self, layout: list) -> None:
        self.report_heading("Notes", break_before=True)
        if self.moved:
            self.prose(
                "%d note(s) could not be completed in the margin column and are given "
                "here in full, marked accordingly." % len(self.moved),
                size=8.0,
                leading=10.4,
                gray=0.3,
                space_after=3.0,
            )
        self.prose(
            "Every note, in full, keyed by sentence id. A note printed beside the "
            "document appears here as well.",
            size=8.0,
            leading=10.4,
            gray=0.3,
            space_after=5.0,
        )
        entries = [segment for entry in layout for segment in entry.segments]
        if not entries:
            self.prose("No sentences were graded, so there are no notes.", gray=0.4)
            return
        for segment in entries:
            self._note_entry(segment.verdict)

    def _note_entry(self, verdict) -> None:
        header = "%s  [%s]  %s" % (
            verdict.sentence_id,
            verdict.rule_id,
            _highlight.state_label(verdict.state),
        )
        self.prose(header, font="F2", size=8.2, leading=10.2, space_after=1.5)
        for line in self._note_lines(verdict):
            if not line:
                continue
            self.ensure(9.6)
            self.y -= 9.6
            self.canvas.text(CONTENT_X + 12.0, self.y, line, "F1", 7.6, 0.15)
        if verdict.sentence_id in self.moved:
            self.ensure(9.6)
            self.y -= 9.6
            self.canvas.text(
                CONTENT_X + 12.0,
                self.y,
                "[this note could not be completed in the margin column]",
                "F3",
                7.6,
                0.45,
            )
        self.space(4.0)

    # -- tables ------------------------------------------------------------ #

    def table(self, widths: list, header: list, rows: list, size: float = TABLE_SIZE,
              fills: dict = None) -> None:
        fills = fills or {}
        leading = size + 1.9
        header_lines = [wrap_text(cell, "F2", size, width - 4.0) or [""]
                        for cell, width in zip(header, widths)]
        self.space(2.0)
        self._table_row(widths, header_lines, size, leading, header=True, top_rule=True)
        for index, row in enumerate(rows):
            cell_lines = [wrap_text(cell, "F1", size, width - 4.0) or [""]
                          for cell, width in zip(row, widths)]
            height = max(len(lines) for lines in cell_lines) * leading + 4.0
            if self.y - height < BOTTOM:
                self.new_page()
                self._table_row(widths, header_lines, size, leading, header=True, top_rule=True)
            self._table_row(
                widths, cell_lines, size, leading, header=False, row_index=index, fills=fills
            )
        self.space(6.0)

    def _table_row(self, widths: list, cell_lines: list, size: float, leading: float,
                   header: bool, row_index: int = -1, fills: dict = None,
                   top_rule: bool = False) -> None:
        fills = fills or {}
        height = max(len(lines) for lines in cell_lines) * leading + 4.0
        top = self.y
        bottom = top - height
        if header:
            self.canvas.fill_rect(CONTENT_X, bottom, CONTENT_W, height, (0.90, 0.90, 0.90))
        else:
            x = CONTENT_X
            for column, width in enumerate(widths):
                rgb = fills.get((row_index, column), _MISSING)
                if rgb is _MISSING:
                    x += width
                    continue
                # A legend swatch is the only other place the palette is painted;
                # it carries no marker, so it can never be mistaken for a highlight.
                self.canvas.fill_rect(x, bottom, width, height, rgb or (1.0, 1.0, 1.0))
                self.canvas.stroke_rect(x, bottom, width, height, 0.45, 0.4)
                x += width
        x = CONTENT_X
        for column, lines in enumerate(cell_lines):
            baseline = top - 3.0 - size
            for line in lines:
                if line:
                    self.canvas.text(
                        x + 2.0,
                        baseline,
                        line,
                        "F2" if header else "F1",
                        size,
                        0.0 if header else 0.15,
                    )
                baseline -= leading
            x += widths[column]
        if top_rule or header:
            self.canvas.line(
                CONTENT_X, top, CONTENT_X + CONTENT_W, top, gray=0.4, weight=0.7
            )
        self.canvas.line(
            CONTENT_X, bottom, CONTENT_X + CONTENT_W, bottom, gray=0.68, weight=0.4
        )
        self.y = bottom

    # -- reporting --------------------------------------------------------- #

    def render_warnings(self) -> list:
        stats = self.canvas.stats
        warnings: list = []
        winansi = stats["winansi"]
        if winansi:
            warnings.append(
                "%d character(s) outside Latin-1 were written in their WinAnsiEncoding "
                "form (for example %s); they render correctly but an extractor may not "
                "return the original codepoint"
                % (len(winansi), _sample(winansi))
            )
        substituted = stats["substituted"]
        if substituted:
            warnings.append(
                "%d character(s) had no base-14 glyph and were transliterated to ASCII "
                "(for example %s)" % (len(substituted), _sample(substituted))
            )
        replaced = stats["replaced"]
        if replaced:
            warnings.append(
                "%d character(s) could not be represented by the standard 14 fonts and "
                "were emitted as '?' (for example %s)"
                % (len(replaced), _sample(replaced))
            )
        if stats["cjk"]:
            warnings.append(
                "%d CJK character(s) were replaced: the standard 14 PDF fonts have no "
                "CJK glyphs, so this text is not readable in the PDF and must be read "
                "in the source document" % stats["cjk"]
            )
        return warnings


def _sample(chars: list) -> str:
    return ", ".join(sorted(set(chars))[:6])


def render(layout, summary, bundle, meta) -> tuple:
    """Return `(pdf_bytes, report_dict)`.

    The document model is drawn in the order the report requires: identity and
    metadata, the gate banner, the coverage bar and legend, the graded document,
    the disclosure, then the Sources and Notes appendices. Nothing is produced that
    was not handed in: every number comes from `summary`, every colour from
    `_highlight`, and every note body from `_highlight.note_text`.
    """
    layout = list(layout or [])
    summary = dict(summary or {})
    meta = dict(meta or {})
    coverage = summary.get("citation_coverage")
    if not isinstance(coverage, dict) or "numerator" not in coverage:
        raise _common.InputError(
            "summary is missing citation_coverage; refusing to print a coverage line "
            "whose denominator is unknown"
        )

    painter = _Renderer(meta)
    painter.segments = sum(len(entry.segments) for entry in layout)
    painter.title_block(summary, bundle, meta)
    painter.gate_banner(meta)
    painter.input_bound_banner(meta)
    painter.coverage_section(summary)
    painter.attribution_section(meta)
    painter.document_body(layout)
    painter.disclosure(bundle, meta)
    painter.sources_appendix(bundle)
    painter.notes_appendix(layout)
    payload = painter.canvas.build()

    warnings = list(meta.get("warnings") or [])
    warnings.extend(painter.render_warnings())
    report = {
        "format": "pdf",
        "bytes": len(payload),
        "pages": len(painter.canvas.pages),
        "highlights": painter.highlights,
        "notes": len(painter.printed),
        "segments": painter.segments,
        "warnings": warnings,
        "notes_moved_to_appendix": len(painter.moved),
    }
    return payload, report
