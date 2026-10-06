"""Lay the document model out as a PDF.

Handles heading hierarchy, paragraph runs with bold/italic/code, bullet and numbered
lists, ruled tables with wrapped cells, code blocks, captions, page breaks before
References and appendices, and a vector version of the screening-flow figure drawn
from recorded counts only.

No third-party packages. No image rasterisation: figures are drawn as PDF vectors so
they stay sharp at any size.
"""

from __future__ import annotations

from _pdfout import MARGIN, PAGE_H, TEXT_W, PdfDocument, measure, wrap_text

RUN_FONT = {
    (False, False, False): "F1",
    (True, False, False): "F2",
    (False, True, False): "F3",
    (True, True, False): "F4",
    (False, False, True): "F5",
}

BODY_SIZE = 10.0
BODY_LEADING = 13.0
TABLE_SIZE = 8.4
CAPTION_SIZE = 8.6


def run_font(run) -> str:
    return RUN_FONT[(bool(run.bold), bool(run.italic), bool(run.code))]


def wrap_runs(runs: list, width: float, size: float) -> list:
    """Return a list of lines; each line is a list of (text, font) segments."""
    tokens: list = []
    for run in runs:
        font = run_font(run)
        parts = run.text.split(" ")
        for position, part in enumerate(parts):
            text = part if position == 0 else " " + part
            if text:
                tokens.append((text, font))
    lines: list = []
    current: list = []
    used = 0.0
    for text, font in tokens:
        piece = text
        piece_width = measure(piece, font, size)
        if used + piece_width > width and current:
            trimmed = current[-1][0]
            if trimmed.startswith(" "):
                current[-1] = (trimmed[1:], current[-1][1])
            lines.append(current)
            current = []
            used = 0.0
            piece = piece[1:] if piece.startswith(" ") else piece
            piece_width = measure(piece, font, size)
        if piece:
            current.append((piece, font))
            used += piece_width
    if current:
        lines.append(current)
    return lines or [[]]


def emit_runs(document: PdfDocument, lines: list, size: float, leading: float,
              x: float = MARGIN, indent: float = 0.0) -> None:
    for line in lines:
        document.ensure(leading)
        document.cursor -= leading
        offset = 0.0
        for text, font in line:
            document.text(x + indent + offset, document.cursor, text, font, size)
            offset += measure(text, font, size)


def render_heading(document: PdfDocument, block) -> None:
    level = max(1, min(block.level, 4))
    sizes = {1: 15.5, 2: 12.5, 3: 11.0, 4: 10.0}
    size = sizes[level]
    text = block.plain_text()
    if re_page_break_before(text):
        document.new_page()
    document.ensure(size * 3.0)
    document.space(10 if level <= 2 else 7)
    document.para(text, "F2", size, size * 1.25, space_after=4.0)
    if level == 1:
        document.rule(0.8, 0.35)


PAGE_BREAK_PREFIXES = ("references", "appendix")


def re_page_break_before(text: str) -> bool:
    lowered = text.strip().lower()
    return any(lowered.startswith(prefix) for prefix in PAGE_BREAK_PREFIXES)



def render_table(document: PdfDocument, block, warnings: list) -> None:
    columns = len(block.header) or (len(block.rows[0]) if block.rows else 0)
    if not columns:
        return
    if block.label:
        document.space(6)
        document.para(block.label, "F2", CAPTION_SIZE, CAPTION_SIZE * 1.3, space_after=3.0)
    grid: list = [block.header] + [row for row in block.rows]
    widths: list = [0.0] * columns
    for row in grid:
        for index in range(columns):
            value = row[index] if index < len(row) else ""
            widths[index] = max(widths[index], measure(value, "F1", TABLE_SIZE))
    floor_width = TEXT_W * 0.09
    widths = [max(width, floor_width) for width in widths]
    scale = TEXT_W / sum(widths)
    widths = [width * scale for width in widths]

    wrapped_rows: list = []
    for row_index, row in enumerate(grid):
        font = "F2" if row_index == 0 else "F1"
        cells: list = []
        for index in range(columns):
            value = row[index] if index < len(row) else ""
            cells.append(wrap_text(value, font, TABLE_SIZE, widths[index] - 6.0))
        wrapped_rows.append((cells, max(len(cell) for cell in cells)))

    document.ensure(wrapped_rows[0][1] * (TABLE_SIZE + 2.2) + 34.0)
    top = document.cursor
    for row_index, (cells, line_count) in enumerate(wrapped_rows):
        height = line_count * (TABLE_SIZE + 2.2) + 6.0
        if document.cursor - height < MARGIN + 30.0:
            warnings.append("table continued onto a following page")
            document.new_page()
            top = document.cursor
        y = document.cursor - height
        if row_index == 0:
            document.rect(MARGIN, y, TEXT_W, height, fill=0.93, stroke=0.6)
        document.cursor = y
        line_y = y + height - 4.0 - TABLE_SIZE
        for column_index, cell_lines in enumerate(cells):
            x = MARGIN + sum(widths[:column_index]) + 3.0
            font = "F2" if row_index == 0 else "F1"
            for line in cell_lines:
                document.text(x, line_y, line, font, TABLE_SIZE)
                line_y -= TABLE_SIZE + 2.2
        document.ops.append(
            "0.75 G 0.4 w %.2f %.2f m %.2f %.2f l S" % (MARGIN, y, MARGIN + TEXT_W, y)
        )
    document.ops.append(
        "0.4 G 0.7 w %.2f %.2f m %.2f %.2f l S" % (MARGIN, top, MARGIN + TEXT_W, top)
    )
    document.space(8.0)


def draw_screening_figure(document: PdfDocument, counts: dict) -> None:
    from make_prisma_flow import build_boxes

    boxes = build_boxes(counts)
    document.space(8)
    document.para(
        "Figure: screening flow of records identified, screened, and included",
        "F2",
        CAPTION_SIZE,
        CAPTION_SIZE * 1.3,
        space_after=6.0,
    )
    for stage, lines in boxes:
        height = 12.0 * len(lines) + 12.0
        document.ensure(height + 34.0)
        top = document.cursor
        document.rect(MARGIN, top - height, TEXT_W, height, fill=0.97, stroke=0.25)
        document.text(MARGIN + 6.0, top - 10.0, stage.upper(), "F2", 7.2, 0.4)
        line_y = top - 23.0
        for index, line in enumerate(lines):
            font = "F2" if index == 0 else "F1"
            document.text(MARGIN + 10.0, line_y, line.strip(), font, 8.6)
            line_y -= 12.0
        document.cursor = top - height
        centre = MARGIN + TEXT_W / 2
        document.ops.append(
            "0.2 G 0.8 w %.2f %.2f m %.2f %.2f l S"
            % (centre, document.cursor, centre, document.cursor - 14.0)
        )
        document.ops.append(
            "0.2 G 0.8 w %.2f %.2f m %.2f %.2f l S"
            % (centre - 4.0, document.cursor - 10.0, centre, document.cursor - 14.0)
        )
        document.cursor -= 16.0


def render(blocks: list, meta: dict, counts: dict = None, present: list = None) -> tuple:
    """Return (pdf_bytes, report). Never fabricates content: only the blocks given."""
    document = PdfDocument(footer_left=meta.get("footer_left", ""))
    warnings: list = []
    first_heading = True
    figure_drawn = False

    for block in blocks:
        kind = block.kind
        if kind == "heading":
            if first_heading and block.level == 1 and not document.pages:
                document.space(6)
                document.para(block.plain_text(), "F2", 19.0, 24.0, space_after=2.0)
                for line in meta.get("byline", []):
                    document.para(line, "F1", 9.5, 12.5, gray=0.35, space_after=2.0)
                document.rule(0.9, 0.3)
                document.space(6)
                first_heading = False
                continue
            render_heading(document, block)
        elif kind in ("para", "quote", "caption"):
            if kind == "quote":
                document.space(2)
                emit_runs(
                    document,
                    wrap_runs(block.runs, TEXT_W - 22.0, 9.5),
                    9.5,
                    12.5,
                    indent=22.0,
                )
                document.space(6)
            elif kind == "caption":
                document.space(3)
                emit_runs(document, wrap_runs(block.runs, TEXT_W, CAPTION_SIZE), CAPTION_SIZE, 11.4)
                document.space(5)
            else:
                emit_runs(document, wrap_runs(block.runs, TEXT_W, BODY_SIZE), BODY_SIZE, BODY_LEADING)
                document.space(6)
        elif kind == "list":
            document.space(1)
            for label, runs in block.items:
                marker = "\u2022" if label == "bullet" else label + "."
                document.ensure(BODY_LEADING)
                document.cursor -= BODY_LEADING
                document.text(MARGIN + 4.0, document.cursor, marker, "F1", BODY_SIZE)
                lines = wrap_runs(runs, TEXT_W - 20.0, BODY_SIZE)
                emit_runs(document, lines, BODY_SIZE, BODY_LEADING, indent=20.0)
            document.space(6)
        elif kind == "table":
            render_table(document, block, warnings)
        elif kind == "code":
            text = block.plain_text()
            lines = text.split("\n")
            height = len(lines) * 11.0 + 10.0
            document.ensure(height + 10.0)
            top = document.cursor
            document.rect(MARGIN, top - height, TEXT_W, height, fill=0.96, stroke=0.85)
            line_y = top - 14.0
            for line in lines:
                document.text(MARGIN + 6.0, line_y, line[:110], "F5", 8.4)
                line_y -= 11.0
            document.cursor = top - height - 8.0
        elif kind == "rule":
            document.rule(0.5, 0.7)
        elif kind == "image":
            if counts is not None and not figure_drawn:
                draw_screening_figure(document, counts)
                figure_drawn = True
            else:
                document.space(4)
                document.para(
                    "[figure: %s]" % (block.path or block.alt),
                    "F3",
                    9.0,
                    12.0,
                    gray=0.4,
                    space_after=6.0,
                )
    if counts is not None and not figure_drawn:
        document.new_page()
        draw_screening_figure(document, counts)
    if present:
        document.space(8)
        for line in present:
            document.para(line, "F1", 8.6, 11.4, gray=0.4, space_after=1.0)
    payload = document.build()
    report = {
        "format": "pdf",
        "pages": len(document.pages),
        "bytes": len(payload),
        "warnings": warnings,
        "substituted_characters": sorted(set(document.dropped)),
    }
    return payload, report

    document.space(6)
    document.para(
        "Counts are those recorded in prisma_counts.json and are checked arithmetically "
        "before this figure is drawn.",
        "F1",
        CAPTION_SIZE,
        CAPTION_SIZE * 1.3,
        gray=0.4,
    )
