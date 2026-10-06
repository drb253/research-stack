"""Write a Word .docx from the document model, with no third-party packages.

A .docx is an Open Packaging Convention zip of XML parts. This module writes the
minimum set that Word (and Pages, LibreOffice, and Google Docs) open correctly:

  [Content_Types].xml, _rels/.rels, word/document.xml, word/document.xml.rels,
  word/styles.xml, word/footer1.xml, word/media/*, docProps/core.xml, docProps/app.xml

Output includes heading styles (so Word can build a table of contents), real Word
tables with repeating header rows, hanging-indent references, page numbers in the
footer, and aspect-scaled inline images when a PNG is available for a figure.
"""

from __future__ import annotations

import struct
import zipfile

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"

TEXT_WIDTH_TWIPS = 9638
PAGE_W_TWIPS = 11906
PAGE_H_TWIPS = 16838
MARGIN_TWIPS = 1134

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Default Extension="png" ContentType="image/png"/>'
    '<Default Extension="jpg" ContentType="image/jpeg"/>'
    '<Default Extension="jpeg" ContentType="image/jpeg"/>'
    '<Default Extension="svg" ContentType="image/svg+xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
    '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
    '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
    "</Types>"
)

ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="%s/officeDocument" Target="word/document.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
    '<Relationship Id="rId3" Type="%s/extended-properties" Target="docProps/app.xml"/>'
    "</Relationships>" % (R, R)
)


def esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )



STYLE_DEFS = (
    ("Normal", "Normal body text", 20, "Times New Roman"),
    ("Title", "Title", 40, "Times New Roman"),
    ("Subtitle", "Subtitle", 19, "Times New Roman"),
    ("Heading1", "Heading 1", 32, "Times New Roman"),
    ("Heading2", "Heading 2", 26, "Times New Roman"),
    ("Heading3", "Heading 3", 23, "Times New Roman"),
    ("Heading4", "Heading 4", 21, "Times New Roman"),
    ("Quote", "Block quote", 19, "Times New Roman"),
    ("Caption", "Caption", 18, "Times New Roman"),
    ("TableText", "Table text", 17, "Times New Roman"),
    ("CodeBlock", "Code block", 17, "Courier New"),
    ("Reference", "Reference entry", 19, "Times New Roman"),
    ("Footer", "Footer", 16, "Times New Roman"),
)

STYLE_EXTRAS = {
    "Title": ('<w:spacing w:before="0" w:after="120"/><w:jc w:val="center"/>', "<w:b/>"),
    "Subtitle": (
        '<w:jc w:val="center"/><w:spacing w:after="240"/>',
        '<w:i/><w:color w:val="404040"/>',
    ),
    "Quote": (
        '<w:ind w:left="567" w:right="567"/><w:spacing w:before="120" w:after="120"/>',
        "<w:i/>",
    ),
    "Caption": ('<w:spacing w:before="120" w:after="200"/>', "<w:i/>"),
    "TableText": ('<w:spacing w:after="0" w:line="240" w:lineRule="auto"/>', ""),
    "CodeBlock": (
        '<w:spacing w:after="0" w:line="240" w:lineRule="auto"/>'
        '<w:shd w:val="clear" w:fill="F2F2F2"/>',
        "",
    ),
    "Reference": ('<w:ind w:left="567" w:hanging="567"/><w:spacing w:after="60"/>', ""),
    "Footer": ("", '<w:color w:val="737373"/>'),
}


def styles_xml() -> str:
    parts: list = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<w:styles xmlns:w="%s">' % W,
        "<w:docDefaults><w:rPrDefault><w:rPr>"
        '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/>'
        '<w:sz w:val="20"/></w:rPr></w:rPrDefault>'
        '<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="264" w:lineRule="auto"/>'
        "</w:pPr></w:pPrDefault></w:docDefaults>",
    ]
    for style_id, name, half_points, font in STYLE_DEFS:
        if style_id.startswith("Heading"):
            level = int(style_id[-1]) - 1
            parts.append(
                '<w:style w:type="paragraph" w:styleId="%s"><w:name w:val="%s"/>'
                '<w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:pPr><w:keepNext/>'
                '<w:spacing w:before="280" w:after="120"/><w:outlineLvl w:val="%d"/></w:pPr>'
                '<w:rPr><w:rFonts w:ascii="%s" w:hAnsi="%s"/><w:b/><w:sz w:val="%d"/></w:rPr>'
                "</w:style>" % (style_id, name, level, font, font, half_points)
            )
            continue
        extras, run_extras = STYLE_EXTRAS.get(style_id, ("", ""))
        parts.append(
            '<w:style w:type="paragraph" w:styleId="%s"><w:name w:val="%s"/>'
            '<w:basedOn w:val="Normal"/><w:pPr>%s</w:pPr>'
            '<w:rPr><w:rFonts w:ascii="%s" w:hAnsi="%s"/>%s<w:sz w:val="%d"/></w:rPr>'
            "</w:style>" % (style_id, name, extras, font, font, run_extras, half_points)
        )
    parts.append("</w:styles>")
    return "".join(parts)


FOOTER_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:ftr xmlns:w="%s"><w:p><w:pPr><w:pStyle w:val="Footer"/>'
    '<w:jc w:val="right"/></w:pPr>'
    '<w:r><w:t xml:space="preserve">Page </w:t></w:r>'
    '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
    '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
    '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    '<w:r><w:t xml:space="preserve"> of </w:t></w:r>'
    '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
    '<w:r><w:instrText xml:space="preserve"> NUMPAGES </w:instrText></w:r>'
    '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    "</w:p></w:ftr>" % W
)



class SimpleRun:
    """A minimal stand-in for _markdown.Run when a cell needs plain text."""

    def __init__(self, text: str, bold: bool = False):
        self.text = text
        self.bold = bold
        self.italic = False
        self.code = False
        self.link = ""


def run_xml(run, size_half_points: int = None) -> str:
    properties: list = []
    if getattr(run, "bold", False):
        properties.append("<w:b/>")
    if getattr(run, "italic", False):
        properties.append("<w:i/>")
    if getattr(run, "code", False):
        properties.append('<w:rFonts w:ascii="Courier New" w:hAnsi="Courier New"/>')
    if size_half_points:
        properties.append('<w:sz w:val="%d"/>' % size_half_points)
    if getattr(run, "link", ""):
        properties.append('<w:color w:val="1F4E79"/><w:u w:val="single"/>')
    return (
        '<w:r><w:rPr>%s</w:rPr><w:t xml:space="preserve">%s</w:t></w:r>'
        % ("".join(properties), esc(run.text))
    )


def paragraph_xml(style_id: str, runs: list, size_half_points: int = None,
                  extra_properties: str = "") -> str:
    body = "".join(run_xml(run, size_half_points) for run in runs if run.text)
    if not body:
        body = '<w:r><w:t xml:space="preserve"></w:t></w:r>'
    return (
        '<w:p><w:pPr><w:pStyle w:val="%s"/>%s</w:pPr>%s</w:p>'
        % (style_id, extra_properties, body)
    )


def table_xml(block) -> str:
    columns = len(block.header) or (len(block.rows[0]) if block.rows else 0)
    if not columns:
        return ""
    grid: list = [block.header] + [row for row in block.rows]
    weights: list = [1.0] * columns
    for row in grid:
        for index in range(columns):
            value = row[index] if index < len(row) else ""
            weights[index] = max(weights[index], min(len(value), 60))
    total = sum(weights)
    widths = [int(TEXT_WIDTH_TWIPS * weight / total) for weight in weights]
    widths[-1] += TEXT_WIDTH_TWIPS - sum(widths)

    borders = (
        "<w:tblBorders>"
        '<w:top w:val="single" w:sz="6" w:color="808080"/>'
        '<w:left w:val="single" w:sz="4" w:color="BFBFBF"/>'
        '<w:bottom w:val="single" w:sz="6" w:color="808080"/>'
        '<w:right w:val="single" w:sz="4" w:color="BFBFBF"/>'
        '<w:insideH w:val="single" w:sz="4" w:color="BFBFBF"/>'
        '<w:insideV w:val="single" w:sz="4" w:color="BFBFBF"/>'
        "</w:tblBorders>"
    )
    parts: list = [
        '<w:tbl><w:tblPr><w:tblW w:w="%d" w:type="dxa"/>%s'
        '<w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>%s</w:tblGrid>'
        % (
            TEXT_WIDTH_TWIPS,
            borders,
            "".join('<w:gridCol w:w="%d"/>' % width for width in widths),
        )
    ]
    for row_index, row in enumerate(grid):
        is_header = row_index == 0
        cells: list = []
        for index in range(columns):
            value = row[index] if index < len(row) else ""
            shading = (
                '<w:shd w:val="clear" w:color="auto" w:fill="EFEFEF"/>' if is_header else ""
            )
            cells.append(
                '<w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/>%s</w:tcPr>%s</w:tc>'
                % (
                    widths[index],
                    shading,
                    paragraph_xml(
                        "TableText",
                        [SimpleRun(value, is_header)],
                        extra_properties='<w:spacing w:after="0"/>',
                    ),
                )
            )
        properties = "<w:trPr><w:tblHeader/></w:trPr>" if is_header else ""
        parts.append("<w:tr>%s%s</w:tr>" % (properties, "".join(cells)))
    parts.append('</w:tbl><w:p><w:pPr><w:spacing w:after="0"/></w:pPr></w:p>')
    return "".join(parts)



def png_dimensions(payload: bytes) -> tuple:
    if payload[:8] != b"\x89PNG\r\n\x1a\n":
        return (0, 0)
    width, height = struct.unpack(">II", payload[16:24])
    return (int(width), int(height))


def image_xml(relationship_id: str, pixel_width: int, pixel_height: int,
              max_emu: int = 5486400, drawing_id: int = 1) -> str:
    if pixel_width <= 0 or pixel_height <= 0:
        return ""
    width_emu = int(pixel_width * 9525)
    height_emu = int(pixel_height * 9525)
    if width_emu > max_emu:
        factor = max_emu / width_emu
        width_emu = max_emu
        height_emu = int(height_emu * factor)
    return (
        '<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:before="120" w:after="200"/></w:pPr>'
        '<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
        '<wp:extent cx="%d" cy="%d"/><wp:docPr id="%d" name="Figure %d"/>'
        '<a:graphic xmlns:a="%s"><a:graphicData uri="%s">'
        '<pic:pic xmlns:pic="%s"><pic:nvPicPr><pic:cNvPr id="%d" name="Figure %d"/>'
        "<pic:cNvPicPr/></pic:nvPicPr>"
        '<pic:blipFill><a:blip xmlns:r="%s" r:embed="%s"/>'
        "<a:stretch><a:fillRect/></a:stretch></pic:blipFill>"
        '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        "</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"
        % (
            width_emu, height_emu, drawing_id, drawing_id, A, PIC, PIC,
            drawing_id, drawing_id, R, relationship_id, width_emu, height_emu,
        )
    )


def page_break_xml() -> str:
    return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


def build_document_body(blocks: list, images: dict, warnings: list) -> str:
    """images maps a normalised path to (relationship id, png bytes)."""
    parts: list = []
    first_heading = True
    drawing_id = 1
    for block in blocks:
        kind = block.kind
        if kind == "heading":
            if first_heading and block.level == 1:
                parts.append(paragraph_xml("Title", block.runs))
                first_heading = False
                continue
            style = "Heading%d" % min(max(block.level, 1), 4)
            lowered = block.plain_text().strip().lower()
            if lowered.startswith(("references", "appendix")):
                parts.append(page_break_xml())
            parts.append(paragraph_xml(style, block.runs))
        elif kind == "para":
            style = "Caption" if block.label == "footnote" else "Normal"
            parts.append(paragraph_xml(style, block.runs))
        elif kind == "quote":
            parts.append(paragraph_xml("Quote", block.runs))
        elif kind == "caption":
            parts.append(paragraph_xml("Caption", block.runs))
        elif kind == "list":
            for label, runs in block.items:
                prefix = "\u2022  " if label == "bullet" else label + ".  "
                parts.append(
                    paragraph_xml(
                        "Normal",
                        [SimpleRun(prefix)] + list(runs),
                        extra_properties=(
                            '<w:ind w:left="567" w:hanging="284"/><w:spacing w:after="60"/>'
                        ),
                    )
                )
        elif kind == "table":
            if block.label:
                parts.append(paragraph_xml("Caption", [SimpleRun(block.label)]))
            parts.append(table_xml(block))
        elif kind == "code":
            for line in block.plain_text().split("\n"):
                parts.append(paragraph_xml("CodeBlock", [SimpleRun(line)]))
        elif kind == "rule":
            parts.append(
                '<w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="6" w:color="BFBFBF"/>'
                "</w:pBdr></w:pPr></w:p>"
            )
        elif kind == "image":
            key = block.path.replace("\\", "/").lstrip("./")
            entry = images.get(key)
            if entry is None:
                basename = key.split("/")[-1]
                entry = next(
                    (value for path, value in images.items() if path.endswith(basename)), None
                )
            if entry is None:
                warnings.append("figure not embedded, no PNG available: " + key)
                parts.append(
                    paragraph_xml(
                        "Caption",
                        [SimpleRun("[figure not embedded: %s - see the SVG or PDF output]" % key)],
                    )
                )
                continue
            relationship_id, payload, _media_name = entry
            width, height = png_dimensions(payload)
            xml = image_xml(relationship_id, width, height, drawing_id=drawing_id)
            if xml:
                parts.append(xml)
                drawing_id += 1
            else:
                warnings.append("figure not embedded, unreadable PNG: " + key)
            if block.alt:
                parts.append(paragraph_xml("Caption", [SimpleRun(block.alt)]))
    return "".join(parts)


def document_xml(body: str) -> str:
    section = (
        "<w:sectPr>"
        '<w:footerReference w:type="default" r:id="rIdFooter"/>'
        '<w:pgSz w:w="%d" w:h="%d"/>'
        '<w:pgMar w:top="%d" w:right="%d" w:bottom="%d" w:left="%d" w:header="720" w:footer="454" '
        'w:gutter="0"/>'
        "</w:sectPr>" % (PAGE_W_TWIPS, PAGE_H_TWIPS, MARGIN_TWIPS, MARGIN_TWIPS, MARGIN_TWIPS,
                         MARGIN_TWIPS)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="%s" xmlns:r="%s" xmlns:wp="%s" xmlns:a="%s" xmlns:pic="%s">'
        "<w:body>%s%s</w:body></w:document>" % (W, R, WP, A, PIC, body, section)
    )


def document_rels_xml(images: dict) -> str:
    relationships: list = [
        '<Relationship Id="rIdFooter" Type="%s/footer" Target="footer1.xml"/>' % R,
        '<Relationship Id="rIdStyles" Type="%s/styles" Target="styles.xml"/>' % R,
    ]
    for _path, entry in sorted(images.items()):
        relationship_id, _payload, media_name = entry
        relationships.append(
            '<Relationship Id="%s" Type="%s/image" Target="media/%s"/>'
            % (relationship_id, R, media_name)
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s'
        "</Relationships>" % "".join(relationships)
    )


def core_xml(meta: dict) -> str:
    title = esc(meta.get("title", "Medical narrative review"))
    author = esc(meta.get("author", ""))
    timestamp = meta.get("generated_on", "")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<dc:title>%s</dc:title><dc:creator>%s</dc:creator><cp:lastModifiedBy>%s</cp:lastModifiedBy>"
        '<dcterms:created xsi:type="dcterms:W3CDTF">%sT00:00:00Z</dcterms:created>'
        '<dcterms:modified xsi:type="dcterms:W3CDTF">%sT00:00:00Z</dcterms:modified>'
        "<cp:revision>1</cp:revision></cp:coreProperties>" % (title, author, author, timestamp, timestamp)
    )


APP_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
    'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
    "<Application>medical-narrative-review export_document.py</Application>"
    "<DocSecurity>0</DocSecurity></Properties>"
)


def write_docx(path: str, blocks: list, meta: dict, images: dict) -> dict:
    warnings: list = []
    body = build_document_body(blocks, images, warnings)
    parts = {
        "[Content_Types].xml": CONTENT_TYPES,
        "_rels/.rels": ROOT_RELS,
        "word/document.xml": document_xml(body),
        "word/_rels/document.xml.rels": document_rels_xml(images),
        "word/styles.xml": styles_xml(),
        "word/footer1.xml": FOOTER_XML,
        "docProps/core.xml": core_xml(meta),
        "docProps/app.xml": APP_XML,
    }
    for image_path, entry in images.items():
        _relationship_id, payload, media_name = entry
        parts["word/media/" + media_name] = payload

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            payload = content.encode("utf-8") if isinstance(content, str) else content
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    import os

    return {
        "format": "docx",
        "bytes": os.path.getsize(path),
        "paragraphs": body.count("<w:p>"),
        "tables": body.count("<w:tbl>"),
        "images_embedded": len(images),
        "warnings": warnings,
    }

