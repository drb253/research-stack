"""The span model shared by every renderer, and the one place colours are defined.

A verdict covers a character range in `Document.text`. A renderer needs that range
expressed *within a paragraph*, because that is the unit each target format
addresses: a PDF line, a Word paragraph run, an HTML `<p>`. Getting this mapping
wrong is the failure mode that matters most — a highlight shifted by one character
silently mis-colours a sentence — so the mapping is computed once here and each
renderer is required to verify it back (see `report_gate.py`).

Colours live here and nowhere else. PDF, DOCX and HTML must agree, and the legend
must agree with the paint, so there is exactly one palette.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import _common

#: state -> (rgb 0-1, hex, human label, what the colour means)
STATE_STYLE = {
    "attributed": (
        (0.349, 0.671, 0.357),
        "59ab5b",
        "Attributed",
        "Every value in the sentence is present in the evidence of a cited source.",
    ),
    "synthesis": (
        (0.749, 1.000, 0.812),
        "bfffcf",
        "Synthesis",
        "Cited and resolvable, with no independently checkable value: comparison, "
        "conclusion or summary supported through synthesis.",
    ),
    "unverifiable": (
        (0.690, 0.769, 0.871),
        "b0c4de",
        "Unverifiable here",
        "Cited and identified, but no evidence was held to check the claim against. "
        "This is not a finding about the sentence; it is a statement about our inputs.",
    ),
    "unattributed": (
        (1.000, 0.741, 0.349),
        "ffbd59",
        "Unattributed",
        "States a checkable fact, figure or borrowed formulation with no resolvable "
        "citation.",
    ),
    "conflict": (
        (0.839, 0.412, 0.349),
        "d66959",
        "Conflict",
        "A citation resolves to nothing, cites a retracted source, or reports a value "
        "that contradicts the same named measure in a source we hold.",
    ),
    "no_citation_needed": (
        None,
        "ffffff",
        "No citation needed",
        "Carries no attribution-requiring signal and no citation marker. Excluded "
        "from the coverage denominator.",
    ),
}

#: Print order for legends and bar segments.
STATE_ORDER = (
    "attributed",
    "synthesis",
    "unverifiable",
    "unattributed",
    "conflict",
    "no_citation_needed",
)


def state_rgb(state: str):
    return STATE_STYLE.get(state, (None, "ffffff", state, ""))[0]


def state_hex(state: str) -> str:
    return STATE_STYLE.get(state, (None, "ffffff", state, ""))[1]


def state_label(state: str) -> str:
    return STATE_STYLE.get(state, (None, "ffffff", state, ""))[2]


def state_meaning(state: str) -> str:
    return STATE_STYLE.get(state, (None, "ffffff", state, ""))[3]


@dataclass
class Segment:
    """A verdict's range expressed within one paragraph's text."""

    start: int
    end: int
    verdict: object

    @property
    def state(self) -> str:
        return self.verdict.state

    @property
    def text(self) -> str:
        return ""


@dataclass
class ParagraphLayout:
    paragraph: object
    segments: list = field(default_factory=list)
    #: Offsets in paragraph text not covered by any segment (kept for renderers that
    #: need to emit the untouched remainder explicitly).
    gaps: list = field(default_factory=list)


def build_layout(document, verdicts) -> list:
    """Map each verdict onto the paragraph that contains it.

    Returns one `ParagraphLayout` per paragraph, in document order, including
    paragraphs that carry no verdict (headings, tables, the reference list) so a
    renderer can emit the document faithfully rather than only the graded parts.

    Raises if a verdict does not fall inside any paragraph, or if two verdicts
    overlap: both mean the sentence spans and the paragraph spans have drifted
    apart, and a renderer must never guess what to paint.
    """
    by_paragraph: dict = {}
    for verdict in verdicts:
        paragraph = document.paragraph_of(verdict.char_start)
        if paragraph is None:
            raise _common.InputError(
                "verdict %s at offset %d falls outside every paragraph"
                % (verdict.sentence_id, verdict.char_start)
            )
        if verdict.char_end > paragraph.char_end:
            raise _common.InputError(
                "verdict %s ends at %d, beyond its paragraph end %d"
                % (verdict.sentence_id, verdict.char_end, paragraph.char_end)
            )
        local_start = verdict.char_start - paragraph.char_start
        local_end = verdict.char_end - paragraph.char_start
        by_paragraph.setdefault(paragraph.index, []).append(
            Segment(start=local_start, end=local_end, verdict=verdict)
        )

    layout: list = []
    for paragraph in document.paragraphs:
        segments = sorted(by_paragraph.get(paragraph.index, []), key=lambda s: s.start)
        for previous, current in zip(segments, segments[1:]):
            if current.start < previous.end:
                raise _common.InputError(
                    "overlapping verdicts in paragraph %d: %s and %s"
                    % (
                        paragraph.index,
                        previous.verdict.sentence_id,
                        current.verdict.sentence_id,
                    )
                )
        gaps: list = []
        cursor = 0
        for segment in segments:
            if segment.start > cursor:
                gaps.append((cursor, segment.start))
            cursor = max(cursor, segment.end)
        if cursor < len(paragraph.text):
            gaps.append((cursor, len(paragraph.text)))
        layout.append(
            ParagraphLayout(paragraph=paragraph, segments=segments, gaps=gaps)
        )
    return layout


def split_at_segments(text: str, segments: list) -> list:
    """Split a paragraph into `(text, segment_or_None)` pieces, in order.

    Renderers that cannot colour a partial run (Word highlights a whole run) still
    get the correct boundaries here, so the only question left is presentation.
    """
    pieces: list = []
    cursor = 0
    for segment in sorted(segments, key=lambda s: s.start):
        if segment.start > cursor:
            pieces.append((text[cursor : segment.start], None))
        pieces.append((text[segment.start : segment.end], segment))
        cursor = segment.end
    if cursor < len(text):
        pieces.append((text[cursor:], None))
    return [piece for piece in pieces if piece[0]]


def legend_rows() -> list:
    """Legend rows for every state, in print order, for any renderer."""
    return [
        {
            "state": state,
            "label": state_label(state),
            "meaning": state_meaning(state),
            "rgb": state_rgb(state),
            "hex": state_hex(state),
            "severity": _common.STATE_SEVERITY[state],
        }
        for state in STATE_ORDER
    ]


def note_text(verdict) -> str:
    """The margin-note body for one verdict. Shared so all formats say the same thing."""
    lines: list = ["%s  [%s]" % (state_label(verdict.state), verdict.rule_id)]
    if verdict.note:
        lines.append(verdict.note)
    for source in verdict.sources:
        piece = source["source_id"]
        if source.get("doi"):
            piece += " · %s" % source["doi"]
        if source.get("locator"):
            piece += " · %s" % source["locator"]
        if source.get("evidence_availability") and source["evidence_availability"] != "full_text":
            piece += " · evidence: %s" % source["evidence_availability"]
        lines.append(piece)
        if source.get("quote"):
            lines.append('"%s"' % source["quote"])
    if verdict.contradiction:
        lines.append(
            "quoted evidence (%s): \"%s\""
            % (verdict.contradiction.get("locator", ""), verdict.contradiction.get("quote", ""))
        )
    if verdict.missing_numbers:
        lines.append("not found in evidence: %s" % ", ".join(verdict.missing_numbers))
    advisory = getattr(verdict, "advisory", None)
    if advisory:
        lines.append(
            "advisory: %s — %s" % (advisory.get("grade", ""), _common.ADVISORY_DISCLOSURE)
        )
        if advisory.get("quote"):
            lines.append('advisory quote: "%s"' % advisory["quote"])
    return "\n".join(lines)
