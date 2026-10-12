"""A self-contained PDF 1.4 writer, sized for a diagnostic report.

Why hand-write a PDF: this skill must run from a bare Python 3.9 installation with
no network, no packages and no fonts to install, so the whole writer has to be small
enough to audit in one sitting. Everything is built on the standard 14 base fonts,
which every conforming reader already provides.

Two decisions shape the API:

* **Painted highlights, not annotations.** PDF has no z-order: whoever paints last
  wins. A highlight therefore has to be a filled rectangle written *before* the
  glyphs of the line it sits behind, which is why `PdfCanvas.fill_rect` takes an
  optional `marker`. The marker is emitted as a PDF comment (`%HL <state>`) directly
  above the rectangle; comments are inert to readers, and they make the number of
  painted highlight spans independently countable straight out of the decompressed
  content stream.
* **Printed margin notes, not `/Annots`.** Notes are ordinary text placed in a
  reserved right-hand column, so they survive printing and appear in viewers that
  ignore annotations entirely. The column geometry lives here, next to the page
  geometry, so the renderer and the writer cannot drift apart.

Determinism is a hard requirement: no timestamps, no unsorted iteration, fixed
float formatting, and object order fixed by construction. The same input must
produce byte-identical output.
"""

from __future__ import annotations

import unicodedata
import zlib

# --------------------------------------------------------------------------- #
# Page geometry. The content column is deliberately narrower than the page so
# the note column is free of glyphs: a note painted over body text would be
# unreadable in print, which is the only reason to print notes instead of
# attaching annotations.
# --------------------------------------------------------------------------- #

PAGE_W = 595.28
PAGE_H = 841.89
MARGIN = 48.0
NOTE_WIDTH = 150.0
COLUMN_GAP = 10.0
CONTENT_X = MARGIN
CONTENT_W = PAGE_W - MARGIN - NOTE_WIDTH - COLUMN_GAP - CONTENT_X
NOTE_X = PAGE_W - MARGIN - NOTE_WIDTH
NOTE_TEXT_X = NOTE_X + 3.0
NOTE_TEXT_W = NOTE_WIDTH - 5.0

#: Nothing may be painted below this line; the band under it belongs to the footer.
BOTTOM = MARGIN + 22.0
FOOTER_BASELINE = MARGIN - 14.0

FONT_BASE = {
    "F1": "Times-Roman",
    "F2": "Times-Bold",
    "F3": "Times-Italic",
    "F4": "Times-BoldItalic",
    "F5": "Courier",
}

# Adobe AFM advance widths for characters 32-126, three digits per character.
# Accented letters are built from their base letter in the Times family, so the
# base table plus NFKD decomposition covers Latin text without a second table.
WIDTHS = {
    "F1": (
        "250 333 408 500 500 833 778 180 333 333 500 564 250 333 250 278"
        " 500 500 500 500 500 500 500 500 500 500"
        " 278 278 564 564 564 444 921"
        " 722 667 667 722 611 556 722 722 333 389 722 611 889 722 722 556 722 667 556 611"
        " 722 722 944 722 722 611"
        " 333 278 333 469 500 333"
        " 444 500 444 500 444 333 500 500 278 278 500 278 778 500 500 500 500 333 389 278"
        " 500 500 722 500 500 444"
        " 480 200 480 541"
    ),
    "F2": (
        "250 333 555 500 500 1000 833 278 333 333 500 570 250 333 250 278"
        " 500 500 500 500 500 500 500 500 500 500"
        " 333 333 570 570 570 500 930"
        " 722 667 722 722 667 611 778 778 389 500 778 667 944 722 778 611 778 722 556 667"
        " 722 722 1000 722 722 667"
        " 333 278 333 581 500 333"
        " 500 556 444 556 444 333 500 556 278 333 556 278 833 556 500 556 556 444 389 333"
        " 556 500 722 500 500 444"
        " 394 220 394 520"
    ),
    "F3": (
        "250 333 420 500 500 833 778 214 333 333 500 675 250 333 250 278"
        " 500 500 500 500 500 500 500 500 500 500"
        " 333 333 675 675 675 500 920"
        " 611 611 667 722 611 611 722 722 333 444 667 556 833 667 722 611 722 611 500 556"
        " 722 611 833 611 556 556"
        " 389 278 389 422 500 333"
        " 500 500 444 500 444 278 500 500 278 278 444 278 722 500 500 500 500 389 389 278"
        " 500 444 667 444 444 389"
        " 400 275 400 541"
    ),
    "F4": (
        "250 389 555 500 500 833 778 278 333 333 500 570 250 333 250 278"
        " 500 500 500 500 500 500 500 500 500 500"
        " 333 333 570 570 570 500 832"
        " 667 667 667 722 667 667 722 778 389 500 667 611 889 722 722 611 722 667 556 611"
        " 722 667 889 667 611 611"
        " 333 278 333 570 500 333"
        " 500 500 444 500 444 333 500 556 278 278 500 278 778 556 500 500 500 389 389 278"
        " 556 444 667 500 444 389"
        " 348 220 348 570"
    ),
}

WIDTH_INDEX = {}
for _font_name, _packed in WIDTHS.items():
    _values = [int(part) for part in _packed.split()]
    if len(_values) != 95 or any(value <= 0 for value in _values):
        raise ValueError(
            "width table for %s must hold 95 positive advances, found %d"
            % (_font_name, len(_values))
        )
    WIDTH_INDEX[_font_name] = {
        chr(32 + _offset): _values[_offset] / 1000.0 for _offset in range(95)
    }

#: Times advances for characters the 32-126 table cannot hold and NFKD cannot
#: reduce to an ASCII base. Without these, wrapping would guess 0.5em for every
#: curly quote and en dash, which shows up as visibly loose lines.
EXTRA_WIDTHS = {
    "\u00a0": 0.250,
    "\u00b7": 0.250,
    "\u2013": 0.500,
    "\u2014": 1.000,
    "\u2018": 0.333,
    "\u2019": 0.333,
    "\u201c": 0.444,
    "\u201d": 0.444,
    "\u2022": 0.350,
    "\u2026": 1.000,
}

#: Characters with a lucky ASCII lookalike. Only used when WinAnsiEncoding has no
#: slot for the character and NFKD does not already fold it.
TRANSLITERATIONS = {
    "\u2192": "->",
    "\u2190": "<-",
    "\u2265": ">=",
    "\u2264": "<=",
    "\u2248": "~",
    "\u00d7": "x",
    "\u00b5": "u",
    "\u2011": "-",
    "\u2012": "-",
    "\u2032": "'",
    "\u2033": '"',
    "\u2212": "-",
}

#: Ranges that the CJK scripts occupy. A character here cannot be rendered by a
#: base-14 font at any encoding, so the caller is told rather than left guessing
#: why a clause came out as question marks.
CJK_RANGES = (
    (0x2E80, 0x2EFF),
    (0x3000, 0x303F),
    (0x3040, 0x30FF),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xAC00, 0xD7AF),
    (0xF900, 0xFAFF),
    (0xFF00, 0xFFEF),
)


def is_cjk(char: str) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in CJK_RANGES)


def measure(text: str, font: str, size: float) -> float:
    """Advance width of `text` in points for one of the base fonts."""
    if font == "F5":
        # Courier is monospaced at 600/1000 em; the base-14 Courier is not
        # substituted, so this is exact rather than approximate.
        return len(text) * 0.6 * size
    table = WIDTH_INDEX[font]
    total = 0.0
    for char in text:
        width = table.get(char)
        if width is None:
            width = EXTRA_WIDTHS.get(char)
        if width is None:
            decomposed = unicodedata.normalize("NFKD", char)
            base = decomposed[0] if decomposed else "?"
            width = table.get(base, 0.5)
        total += width
    return total * size


def split_long_word(word: str, font: str, size: float, width: float) -> list:
    """Break a word that is wider than the column, so nothing spills sideways.

    A DOI or a URL has no space to break at, and letting one run past the column
    would push glyphs into the reserved note column of the next page worth of
    layout, so the break is taken at the character level instead.
    """
    if width <= 0 or measure(word, font, size) <= width:
        return [word]
    chunks: list = []
    current: list = []
    used = 0.0
    for char in word:
        advance = measure(char, font, size)
        if current and used + advance > width:
            chunks.append("".join(current))
            current = []
            used = 0.0
        current.append(char)
        used += advance
    if current:
        chunks.append("".join(current))
    return chunks or [word]


def wrap_text(text: str, font: str, size: float, width: float) -> list:
    """Greedy first-fit wrapping. Newlines are honoured as hard breaks."""
    lines: list = []
    for block in text.split("\n"):
        words: list = []
        for word in block.split(" "):
            words.extend(split_long_word(word, font, size, width))
        current = ""
        for word in words:
            candidate = word if not current else current + " " + word
            if current and measure(candidate, font, size) > width:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
    return lines


def encode_text(value: str) -> tuple:
    """Return `(winansi bytes, stats)` for one text run.

    `stats` holds the characters that could not be written as themselves, split by
    what happened to them, because the report must be able to say "302 characters
    were replaced" rather than silently emitting broken bytes. `stats` keys are
    `winansi` (non-Latin-1 but valid WinAnsi, e.g. curly quotes — they render
    correctly), `substituted` (folded to an ASCII lookalike), `replaced` (no
    representation, emitted as `?`) and `cjk`.
    """
    output = bytearray()
    stats = {"winansi": [], "substituted": [], "replaced": [], "cjk": 0}
    for char in value:
        if char in "\r\n":
            output.append(0x20)
            continue
        code = ord(char)
        if char == "\t":
            output.extend(b"    ")
            continue
        if code < 0x20:
            continue
        try:
            encoded = char.encode("cp1252")
        except UnicodeEncodeError:
            encoded = b""
        if len(encoded) == 1:
            if code > 0xFF:
                stats["winansi"].append(char)
            output.extend(encoded)
            continue
        if is_cjk(char):
            stats["cjk"] += 1
        replacement = TRANSLITERATIONS.get(char)
        if replacement is not None:
            output.extend(replacement.encode("ascii", "replace"))
            stats["substituted"].append(char)
            continue
        decomposed = unicodedata.normalize("NFKD", char)
        ascii_part = "".join(part for part in decomposed if ord(part) < 0x80)
        if ascii_part:
            output.extend(ascii_part.encode("ascii"))
            stats["substituted"].append(char)
            continue
        output.extend(b"?")
        stats["replaced"].append(char)
    return bytes(output), stats


def escape_pdf_string(payload: bytes) -> bytes:
    """Escape a literal PDF string. Backslash first, or the escapes re-escape."""
    return (
        payload.replace(b"\\", b"\\\\")
        .replace(b"(", b"\\(")
        .replace(b")", b"\\)")
    )


class PdfCanvas:
    """Append-only page content with just enough structure to serialise a PDF.

    The writer is deliberately dumb: it records operators in call order and never
    reorders them, because the order is the semantics. A highlight rectangle is
    only behind its glyphs if it was appended first.
    """

    def __init__(self, footer_left: str = ""):
        self.pages: list = []
        self.ops: list = []
        self.footer_left = footer_left
        self.stats: dict = {
            "winansi": [],
            "substituted": [],
            "replaced": [],
            "cjk": 0,
        }
        self._start_page()

    # -- page furniture ---------------------------------------------------- #

    def _start_page(self) -> None:
        self.ops = []
        # An opaque ground, so a painted highlight cannot be composited over
        # whatever a viewer drew behind the page.
        self.ops.append("1.000 1.000 1.000 rg 0 0 %.2f %.2f re f" % (PAGE_W, PAGE_H))

    def new_page(self) -> None:
        if self.ops:
            self.pages.append(self.ops)
        self._start_page()

    # -- painting ---------------------------------------------------------- #

    def fill_rect(self, x, y, width, height, rgb, marker: str = "") -> None:
        """Fill a rectangle. `marker` tags a highlight span for audit.

        The marker is a comment, never an operator: it changes nothing a reader
        draws, but it lets a checker count painted highlight spans by decompressing
        the stream instead of trusting this module's own counter.
        """
        if marker:
            self.ops.append("%%HL %s" % marker)
        red, green, blue = rgb
        self.ops.append(
            "%.3f %.3f %.3f rg %.2f %.2f %.2f %.2f re f"
            % (
                min(max(red, 0.0), 1.0),
                min(max(green, 0.0), 1.0),
                min(max(blue, 0.0), 1.0),
                x,
                y,
                width,
                height,
            )
        )

    def stroke_rect(self, x, y, width, height, gray: float = 0.55, weight: float = 0.4) -> None:
        self.ops.append(
            "%.3f G %.2f w %.2f %.2f %.2f %.2f re S" % (gray, weight, x, y, width, height)
        )

    def line(self, x1, y1, x2, y2, rgb=None, gray: float = 0.0, weight: float = 0.5) -> None:
        if rgb is None:
            stroke = "%.3f G" % gray
        else:
            stroke = "%.3f %.3f %.3f RG" % rgb
        self.ops.append(
            "%s %.2f w %.2f %.2f m %.2f %.2f l S" % (stroke, weight, x1, y1, x2, y2)
        )

    def text(
        self,
        x: float,
        y: float,
        value: str,
        font: str = "F1",
        size: float = 10.0,
        gray: float = 0.0,
    ) -> None:
        payload, stats = encode_text(value)
        for key in ("winansi", "substituted", "replaced"):
            self.stats[key].extend(stats[key])
        self.stats["cjk"] += stats["cjk"]
        if not payload:
            return
        self.ops.append(
            "BT /%s %.2f Tf %.3f g 1 0 0 1 %.2f %.2f Tm (%s) Tj ET"
            % (
                font,
                size,
                gray,
                x,
                y,
                escape_pdf_string(payload).decode("latin-1"),
            )
        )

    # -- serialisation ----------------------------------------------------- #

    def _footer_ops(self, page_number: int, total: int) -> list:
        right = "Page %d of %d" % (page_number, total)
        ops: list = []
        entries = (
            (CONTENT_X, self.footer_left),
            (PAGE_W - MARGIN - measure(right, "F1", 7.6), right),
        )
        for x, value in entries:
            if not value:
                continue
            payload, stats = encode_text(value)
            self.stats["replaced"].extend(stats["replaced"])
            self.stats["substituted"].extend(stats["substituted"])
            self.stats["winansi"].extend(stats["winansi"])
            self.stats["cjk"] += stats["cjk"]
            if not payload:
                continue
            ops.append(
                "BT /F1 7.6 Tf 0.450 g 1 0 0 1 %.2f %.2f Tm (%s) Tj ET"
                % (x, FOOTER_BASELINE, escape_pdf_string(payload).decode("latin-1"))
            )
        return ops

    def build(self) -> bytes:
        if self.ops or not self.pages:
            self.pages.append(self.ops)
        total = len(self.pages)
        objects: list = []

        def add(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        catalog_id = add(b"")
        pages_id = add(b"")
        font_ids: dict = {}
        for name, base in FONT_BASE.items():
            font_ids[name] = add(
                (
                    "<< /Type /Font /Subtype /Type1 /BaseFont /%s "
                    "/Encoding /WinAnsiEncoding >>" % base
                ).encode("latin-1")
            )
        # No /CreationDate: a timestamp would break byte-identical reruns.
        info_id = add(
            b"<< /Producer (citation-report _pdfout.py) "
            b"/Creator (citation-report) >>"
        )

        page_ids: list = []
        for number, ops in enumerate(self.pages, start=1):
            content = "\n".join(ops + self._footer_ops(number, total)).encode("latin-1")
            compressed = zlib.compress(content, 9)
            content_id = add(
                b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(compressed)
                + compressed
                + b"\nendstream"
            )
            resources = (
                "<< /Font << "
                + " ".join("/%s %d 0 R" % (name, font_ids[name]) for name in FONT_BASE)
                + " >> >>"
            )
            page_ids.append(
                add(
                    (
                        "<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] "
                        "/Resources %s /Contents %d 0 R >>"
                        % (pages_id, PAGE_W, PAGE_H, resources, content_id)
                    ).encode("latin-1")
                )
            )

        objects[catalog_id - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id
        objects[pages_id - 1] = (
            "<< /Type /Pages /Count %d /Kids [%s] >>"
            % (total, " ".join("%d 0 R" % pid for pid in page_ids))
        ).encode("latin-1")

        output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: list = []
        for index, body in enumerate(objects, start=1):
            offsets.append(len(output))
            output.extend(("%d 0 obj\n" % index).encode("latin-1"))
            output.extend(body)
            output.extend(b"\nendobj\n")
        xref_offset = len(output)
        output.extend(("xref\n0 %d\n" % (len(objects) + 1)).encode("latin-1"))
        output.extend(b"0000000000 65535 f \n")
        for offset in offsets:
            output.extend(("%010d 00000 n \n" % offset).encode("latin-1"))
        output.extend(
            (
                "trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\n"
                "startxref\n%d\n%%%%EOF\n"
                % (len(objects) + 1, catalog_id, info_id, xref_offset)
            ).encode("latin-1")
        )
        return bytes(output)
