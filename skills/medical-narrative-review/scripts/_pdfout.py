"""Minimal, dependency-free PDF writer with real typography.

Emits a valid PDF 1.4 file using only the standard 14 fonts, with accurate Times
metrics for line breaking, A4 geometry, page numbering, ruled tables, and vector
figures drawn from recorded data. No third-party packages, no network, no fonts to
install.

Font metrics are the standard Adobe AFM advance widths for Times, stored as strings
of three-digit values for characters 32-126. Accented characters inherit the width of
their base letter, which is how the Times family is built.
"""

from __future__ import annotations

import re
import unicodedata
import zlib

PAGE_W = 595.28
PAGE_H = 841.89
MARGIN = 56.7
TEXT_W = PAGE_W - 2 * MARGIN

FONT_NAMES = {
    "F1": "Times-Roman",
    "F2": "Times-Bold",
    "F3": "Times-Italic",
    "F4": "Times-BoldItalic",
    "F5": "Courier",
}

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
for _font, _packed in WIDTHS.items():
    _values = [int(part) for part in _packed.split()]
    if len(_values) != 95 or any(value <= 0 for value in _values):
        raise ValueError(
            "font width table for %s must hold 95 positive advances, found %d"
            % (_font, len(_values))
        )
    WIDTH_INDEX[_font] = {
        chr(32 + offset): _values[offset] / 1000.0 for offset in range(95)
    }

WINANSI_SPECIALS = {
    "\u20ac": 0x80,
    "\u201a": 0x82,
    "\u0192": 0x83,
    "\u201e": 0x84,
    "\u2026": 0x85,
    "\u2020": 0x86,
    "\u2021": 0x87,
    "\u2030": 0x89,
    "\u2039": 0x8B,
    "\u2018": 0x91,
    "\u2019": 0x92,
    "\u201c": 0x93,
    "\u201d": 0x94,
    "\u2022": 0x95,
    "\u2013": 0x96,
    "\u2014": 0x97,
    "\u2122": 0x99,
    "\u203a": 0x9B,
    "\u2212": 0x2D,
}

TRANSLITERATIONS = {
    "\u2265": ">=",
    "\u2264": "<=",
    "\u2248": "~",
    "\u00d7": "x",
    "\u2192": "->",
    "\u2190": "<-",
    "\u03bc": "\u00b5",
    "\u0301": "",
    "\u0308": "",
    "\u2011": "-",
    "\u2012": "-",
    "\u2019": "'",
}


def sanitize(text: str) -> tuple:
    """Return (windows-1252 bytes, list of characters that had to be replaced)."""
    dropped: list = []
    output = bytearray()
    for char in text:
        code = ord(char)
        if char in WINANSI_SPECIALS:
            output.append(WINANSI_SPECIALS[char])
            continue
        if code < 0x80:
            output.append(code)
            continue
        if 0xA0 <= code <= 0xFF:
            output.append(code)
            continue
        if char in TRANSLITERATIONS:
            replacement = TRANSLITERATIONS[char]
            output.extend(replacement.encode("cp1252", "replace"))
            continue
        decomposed = unicodedata.normalize("NFKD", char)
        if decomposed and all(ord(part) < 0x80 for part in decomposed):
            output.extend(decomposed.encode("ascii"))
            continue
        if decomposed and any(ord(part) < 0x80 for part in decomposed):
            partial = "".join(part for part in decomposed if ord(part) < 0x80)
            output.extend(partial.encode("ascii"))
            dropped.append(char)
            continue
        output.extend(b"?")
        dropped.append(char)
    return bytes(output), dropped


def wrap_text(text: str, font: str, size: float, width: float) -> list:
    lines: list = []
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        current = ""
        for word in words:
            candidate = word if not current else current + " " + word
            if measure(candidate, font, size) <= width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _escape_pdf_string(payload: bytes) -> bytes:
    return (
        payload.replace(b"\\", b"\\\\")
        .replace(b"(", b"\\(")
        .replace(b")", b"\\)")
        .replace(b"\r", b"")
    )


class PdfDocument:
    """A4 document with text, rules, rectangles, and page furniture."""

    def __init__(self, footer_left: str = "", footer_right: str = "Page {page} of {total}"):
        self.pages: list = []
        self.ops: list = []
        self.footer_left = footer_left
        self.footer_right = footer_right
        self.dropped: list = []
        self.cursor = PAGE_H - MARGIN
        self._paint_paper()

    def _paint_paper(self) -> None:
        """Paint opaque white so the PDF never renders on a transparent ground."""
        self.ops.append("1 g 0 0 %.2f %.2f re f" % (PAGE_W, PAGE_H))

    def new_page(self) -> None:
        if self.ops:
            self.pages.append(self.ops)
        self.ops = []
        self._paint_paper()
        self.cursor = PAGE_H - MARGIN

    def ensure(self, needed: float) -> None:
        if self.cursor - needed < MARGIN + 26:
            self.new_page()

    def space(self, amount: float) -> None:
        self.cursor -= amount

    def move_to_top(self) -> None:
        self.cursor = PAGE_H - MARGIN

    def text(self, x: float, y: float, value: str, font: str = "F1", size: float = 10,
             gray: float = 0.0) -> None:
        payload, dropped = sanitize(value)
        if dropped:
            self.dropped.extend(dropped)
        if not payload:
            return
        self.ops.append(
            "BT /%s %.2f Tf %.3f g 1 0 0 1 %.2f %.2f Tm (%s) Tj ET"
            % (font, size, gray, x, y, _escape_pdf_string(payload).decode("latin-1"))
        )

    def para(self, value: str, font: str = "F1", size: float = 10.0, leading: float = 13.0,
             x: float = MARGIN, width: float = TEXT_W, indent: float = 0.0,
             space_after: float = 6.0, gray: float = 0.0) -> None:
        for line in wrap_text(value, font, size, width - indent):
            self.ensure(leading)
            self.cursor -= leading
            self.text(x + indent, self.cursor, line, font, size, gray)
        self.cursor -= space_after

    def rule(self, thickness: float = 0.6, gray: float = 0.5, width: float = TEXT_W,
             x: float = MARGIN) -> None:
        self.ensure(6)
        self.cursor -= 4
        self.ops.append(
            "%.2f G %.2f w %.2f %.2f m %.2f %.2f l S"
            % (gray, thickness, x, self.cursor, x + width, self.cursor)
        )
        self.cursor -= 4

    def rect(self, x: float, y: float, width: float, height: float, fill: float = 0.96,
             stroke: float = 0.2) -> None:
        if fill is not None:
            self.ops.append("%.2f g %.2f %.2f %.2f %.2f re f" % (fill, x, y, width, height))
        self.ops.append(
            "%.2f G 0.7 w %.2f %.2f %.2f %.2f re S" % (stroke, x, y, width, height)
        )



    def _footer_ops(self, page_number: int, total: int) -> list:
        ops: list = []
        y = MARGIN - 18
        right = self.footer_right.replace("{page}", str(page_number)).replace("{total}", str(total))
        for x, value in ((MARGIN, self.footer_left), (PAGE_W - MARGIN - measure(right, "F1", 8), right)):
            payload, dropped = sanitize(value)
            if dropped:
                self.dropped.extend(dropped)
            if not payload:
                continue
            ops.append(
                "BT /F1 8 Tf 0.45 g 1 0 0 1 %.2f %.2f Tm (%s) Tj ET"
                % (x, y, _escape_pdf_string(payload).decode("latin-1"))
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
        for name, base in FONT_NAMES.items():
            font_ids[name] = add(
                (
                    "<< /Type /Font /Subtype /Type1 /BaseFont /%s /Encoding /WinAnsiEncoding >>"
                    % base
                ).encode("latin-1")
            )
        info_id = add(
            b"<< /Producer (medical-narrative-review export_document.py) "
            b"/Creator (medical narrative review) >>"
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
                + " ".join("/%s %d 0 R" % (name, font_ids[name]) for name in FONT_NAMES)
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
                "trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
                % (len(objects) + 1, catalog_id, info_id, xref_offset)
            ).encode("latin-1")
        )
        return bytes(output)


def measure(text: str, font: str, size: float) -> float:
    if font == "F5":
        return len(text) * 0.6 * size
    table = WIDTH_INDEX[font]
    total = 0.0
    for char in text:
        width = table.get(char)
        if width is None:
            decomposed = unicodedata.normalize("NFKD", char)
            base = decomposed[0] if decomposed else "?"
            width = table.get(base, 0.5)
        total += width
    return total * size
