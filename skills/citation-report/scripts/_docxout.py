"""Write the citation report as a Word .docx, standard library only.

A .docx is an Open Packaging Convention zip of XML parts. This module writes the
smallest set that Word, Pages, LibreOffice and Google Docs all open without repair:

  [Content_Types].xml, _rels/.rels, word/document.xml,
  word/_rels/document.xml.rels, word/styles.xml, word/comments.xml,
  word/footer1.xml, docProps/core.xml, docProps/app.xml

Two decisions carry the whole report and are worth stating where they are made:

* **Run background colour, not `<w:highlight>`.** Each graded sentence is painted
  with `<w:shd w:val="clear" w:color="auto" w:fill="RRGGBB"/>` inside the run's
  `<w:rPr>`. `<w:highlight>` accepts only sixteen named colours and cannot express
  this palette at all — it has no light green (synthesis) and no steel blue
  (unverifiable), and a nearest-name approximation would destroy the distinction the
  report exists to make. `<w:shd>` carries an exact RGB fill, renders as a run
  background in Word, and survives printing. Colours are never redefined here: every
  fill comes from ``_highlight.state_hex`` so the DOCX, the PDF and the HTML cannot
  drift apart.

* **Real Word comments, not a notes-only appendix.** Every graded sentence carries
  `<w:commentRangeStart>`/`<w:commentRangeEnd>` anchors plus a `CommentReference`
  run, and `word/comments.xml` holds the matching `<w:comment>` with the note body.
  A reader can therefore see the note on the sentence rather than hunting for its
  number in an appendix. The anchors are audited after the XML is built — see
  `_audit_anchors` — because an id that is referenced but never defined makes Word
  declare the file corrupt, and a partially written package is worse than none.

Output is deterministic: identical input produces a byte-identical zip. The only
date in the package comes from ``meta["generated"]`` and the zip entries are pinned
to 1980-01-01, so the clock never leaks into an artifact that a test may diff.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field

import _common
import _highlight

# --------------------------------------------------------------------------- #
# Namespaces and page geometry
# --------------------------------------------------------------------------- #

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CORE_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC_NS = "http://purl.org/dc/elements/1.1/"
DCTERMS_NS = "http://purl.org/dc/terms/"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
EXTENDED_NS = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"

#: US Letter, portrait, 2 cm margins. Fixed so output never depends on a template.
PAGE_W_TWIPS = 11906
PAGE_H_TWIPS = 16838
MARGIN_TWIPS = 1134
TEXT_WIDTH_TWIPS = PAGE_W_TWIPS - 2 * MARGIN_TWIPS

#: Narrowest coverage-bar cell that still shows a three-digit count at 7 pt.
MIN_CELL_TWIPS = 420

#: Half-points used inside tables (8.5 pt) and in appendix note entries.
TABLE_HALF_POINTS = 17
NOTE_HALF_POINTS = 18

#: Every zip entry gets this timestamp. The alternative — the clock — would make two
#: runs over the same input differ, which breaks diffing and reproducibility tests.
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
ZIP_COMPRESSLEVEL = 6

GATE_BANNER = (
    "REPORT NOT GATE CLEAN \u2014 errors present. "
    "This document is a diagnostic, not a clearance."
)

#: XML 1.0 Char production, negated. Everything outside it (C0/C1 controls other than
#: tab/LF/CR, lone surrogates, U+FFFE/U+FFFF) is unrepresentable in XML at all, so it
#: has to be removed rather than escaped. Python 3 is always a wide build, so the
#: astral range is matched as one character.
_ILLEGAL_XML = re.compile(
    "[^\u0009\u000a\u000d\u0020-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]"
)

_SOURCE_FIELDS = (
    "source_id",
    "citekey",
    "citation_number",
    "doi",
    "title",
    "title_claimed",
    "year",
    "container",
    "verification_status",
    "retraction_status",
    "evidence_availability",
    "resolution",
)


# --------------------------------------------------------------------------- #
# Text hygiene
# --------------------------------------------------------------------------- #


def esc(text: object) -> str:
    """Escape the five XML metacharacters. `&` must go first or it double-escapes."""
    value = "" if text is None else str(text)
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


@dataclass
class _Text:
    """Escaping plus an audit trail for characters that XML cannot carry.

    Dropping a control character is the only correct move — there is no escape for
    U+0001 — but dropping it silently would corrupt a sentence without saying so, so
    the count is accumulated here and reported in ``report["warnings"]``.
    """

    stripped: int = 0

    def clean(self, value: object) -> str:
        text = "" if value is None else str(value)
        cleaned, removed = _ILLEGAL_XML.subn("", text)
        self.stripped += removed
        return cleaned

    def esc(self, value: object) -> str:
        return esc(self.clean(value))


def _run_content(text: object) -> str:
    """Turn plain text into `w:t`/`w:br`/`w:tab` children of one run.

    A newline inside `w:t` is not a line break in Word, and a tab is not a tab, so
    both are promoted to their real OOXML elements instead of being flattened.
    The caller has already removed characters XML cannot carry; only escaping is
    left here, because ``<w:br/>`` and ``<w:tab/>`` are markup this function owns.
    """
    value = "" if text is None else str(text)
    pieces: list = []
    for line_index, line in enumerate(re.split(r"\r\n|\r|\n", value)):
        if line_index:
            pieces.append("<w:br/>")
        for tab_index, part in enumerate(line.split("\t")):
            if tab_index:
                pieces.append("<w:tab/>")
            if part:
                pieces.append('<w:t xml:space="preserve">%s</w:t>' % esc(part))
    return "".join(pieces)


# --------------------------------------------------------------------------- #
# Style sheet
# --------------------------------------------------------------------------- #

#: styleId -> (name, half-points, pPr XML, rPr XML). Heading styles are built
#: separately because they need outline levels for Word's table of contents.
_PARAGRAPH_STYLES = (
    ("Title", "Title", 40, '<w:spacing w:before="0" w:after="160"/><w:jc w:val="center"/>', "<w:b/>"),
    ("Subtitle", "Subtitle", 19, '<w:jc w:val="center"/><w:spacing w:after="240"/>', '<w:i/><w:color w:val="404040"/>'),
    ("Quote", "Quote", 19, '<w:ind w:left="567" w:right="567"/><w:spacing w:before="120" w:after="120"/>', "<w:i/>"),
    ("Caption", "Caption", 18, '<w:spacing w:before="120" w:after="200"/>', "<w:i/>"),
    ("TableText", "Table text", TABLE_HALF_POINTS, '<w:spacing w:after="0" w:line="240" w:lineRule="auto"/>', ""),
    ("CodeBlock", "Code block", TABLE_HALF_POINTS, '<w:spacing w:after="0" w:line="240" w:lineRule="auto"/>', '<w:rFonts w:ascii="Courier New" w:hAnsi="Courier New"/>'),
    ("Reference", "Reference entry", 19, '<w:ind w:left="567" w:hanging="567"/><w:spacing w:after="60"/>', ""),
    ("NoteEntry", "Report note entry", NOTE_HALF_POINTS, '<w:ind w:left="567" w:hanging="567"/><w:spacing w:after="80"/>', ""),
    ("CommentText", "annotation text", 18, '<w:spacing w:after="80"/>', ""),
    ("Footer", "Footer", 16, "", '<w:color w:val="737373"/>'),
)

_HEADING_HALF_POINTS = {1: 32, 2: 26, 3: 23, 4: 21}


def styles_xml() -> str:
    """The style sheet every referenced style must exist in.

    Word tolerates a missing `w:pStyle` by falling back to Normal, but the headings
    would then lose their outline levels and Word could not build a table of
    contents, which is the whole reason the Heading1-4 styles are used.
    """
    parts: list = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<w:styles xmlns:w="%s">' % W,
        "<w:docDefaults><w:rPrDefault><w:rPr>"
        '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/>'
        '<w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr></w:rPrDefault>'
        '<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="264" w:lineRule="auto"/>'
        "</w:pPr></w:pPrDefault></w:docDefaults>",
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal"/><w:qFormat/></w:style>',
        '<w:style w:type="character" w:default="1" w:styleId="DefaultParagraphFont">'
        '<w:name w:val="Default Paragraph Font"/><w:uiPriority w:val="1"/>'
        "<w:semiHidden/><w:unhideWhenUsed/></w:style>",
    ]
    for level in range(1, 5):
        half_points = _HEADING_HALF_POINTS[level]
        parts.append(
            '<w:style w:type="paragraph" w:styleId="Heading%d">'
            '<w:name w:val="heading %d"/><w:basedOn w:val="Normal"/>'
            '<w:next w:val="Normal"/><w:qFormat/>'
            '<w:pPr><w:keepNext/><w:keepLines/>'
            '<w:spacing w:before="280" w:after="120"/>'
            '<w:outlineLvl w:val="%d"/></w:pPr>'
            '<w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/>'
            '<w:b/><w:sz w:val="%d"/><w:szCs w:val="%d"/></w:rPr></w:style>'
            % (level, level, level - 1, half_points, half_points)
        )
    for style_id, name, half_points, paragraph_props, run_props in _PARAGRAPH_STYLES:
        parts.append(
            '<w:style w:type="paragraph" w:styleId="%s"><w:name w:val="%s"/>'
            '<w:basedOn w:val="Normal"/><w:qFormat/><w:pPr>%s</w:pPr>'
            '<w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/>%s'
            '<w:sz w:val="%d"/><w:szCs w:val="%d"/></w:rPr></w:style>'
            % (style_id, name, paragraph_props, run_props, half_points, half_points)
        )
    # The character style Word applies to a comment's reference mark. It must exist
    # or the anchor renders as a stray glyph at body size.
    parts.append(
        '<w:style w:type="character" w:styleId="CommentReference">'
        '<w:name w:val="annotation reference"/><w:basedOn w:val="DefaultParagraphFont"/>'
        '<w:uiPriority w:val="99"/><w:semiHidden/><w:unhideWhenUsed/>'
        '<w:rPr><w:sz w:val="16"/><w:szCs w:val="16"/></w:rPr></w:style>'
    )
    parts.append("</w:styles>")
    return "".join(parts)


# --------------------------------------------------------------------------- #
# Package parts
# --------------------------------------------------------------------------- #

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="%s">'
    '<Default Extension="rels" '
    'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.'
    'openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" ContentType="application/vnd.'
    'openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '<Override PartName="/word/comments.xml" ContentType="application/vnd.'
    'openxmlformats-officedocument.wordprocessingml.comments+xml"/>'
    '<Override PartName="/word/footer1.xml" ContentType="application/vnd.'
    'openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
    '<Override PartName="/docProps/core.xml" ContentType="application/vnd.'
    'openxmlformats-package.core-properties+xml"/>'
    '<Override PartName="/docProps/app.xml" ContentType="application/vnd.'
    'openxmlformats-officedocument.extended-properties+xml"/>'
    "</Types>" % CONTENT_TYPES_NS
)

ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="%s">'
    '<Relationship Id="rId1" Type="%s/officeDocument" Target="word/document.xml"/>'
    '<Relationship Id="rId2" Type="%s/metadata/core-properties" '
    'Target="docProps/core.xml"/>'
    '<Relationship Id="rId3" Type="%s/extended-properties" Target="docProps/app.xml"/>'
    "</Relationships>" % (PACKAGE_REL_NS, R, PACKAGE_REL_NS, R)
)

#: The relationships part for `word/document.xml`. OPC puts it under `word/_rels/`;
#: a part named `word/document.xml.rels` is read by nothing, and the styles, comments
#: and footer would silently fall off the document.
DOCUMENT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="%s">'
    '<Relationship Id="rIdStyles" Type="%s/styles" Target="styles.xml"/>'
    '<Relationship Id="rIdComments" Type="%s/comments" Target="comments.xml"/>'
    '<Relationship Id="rIdFooter" Type="%s/footer" Target="footer1.xml"/>'
    "</Relationships>" % (PACKAGE_REL_NS, R, R, R)
)

#: Real PAGE/NUMPAGES fields. The run between `separate` and `end` is the cached
#: result a viewer shows before it recalculates, so the footer never renders blank.
FOOTER_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:ftr xmlns:w="%s"><w:p><w:pPr><w:pStyle w:val="Footer"/>'
    '<w:jc w:val="right"/></w:pPr>'
    '<w:r><w:t xml:space="preserve">Page </w:t></w:r>'
    '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
    '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
    '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
    '<w:r><w:t>1</w:t></w:r>'
    '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    '<w:r><w:t xml:space="preserve"> of </w:t></w:r>'
    '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
    '<w:r><w:instrText xml:space="preserve"> NUMPAGES </w:instrText></w:r>'
    '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
    '<w:r><w:t>1</w:t></w:r>'
    '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    "</w:p></w:ftr>" % W
)

APP_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Properties xmlns="%s">'
    "<Application>citation-report _docxout.py</Application>"
    "<DocSecurity>0</DocSecurity><ScaleCrop>false</ScaleCrop>"
    "<LinksUpToDate>false</LinksUpToDate><SharedDoc>false</SharedDoc>"
    "<HyperlinksChanged>false</HyperlinksChanged>"
    "</Properties>" % EXTENDED_NS
)


def _isodate(value: object) -> str:
    """Reduce ``meta["generated"]`` to `YYYY-MM-DD`, pinned to midnight UTC.

    Anything unparseable falls back to the zip epoch rather than to today: a report
    that silently changes with the clock is not reproducible. `render` compares the
    input to the result and warns when it had to fall back.
    """
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", str(value or "").strip())
    return match.group(1) if match else "1980-01-01"


def core_xml(meta: dict, iso_date: str, text: _Text) -> str:
    """`docProps/core.xml`. The title goes through the same hygiene as body text.

    A control character in the title would make this part unparseable and Word would
    reject the whole file, so the escaping here is not cosmetic.
    """
    title = text.esc(meta.get("title") or "Citation report")
    stamp = iso_date + "T00:00:00Z"
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="%s" xmlns:dc="%s" xmlns:dcterms="%s" '
        'xmlns:xsi="%s">'
        "<dc:title>%s</dc:title><dc:creator>citation-report</dc:creator>"
        "<cp:lastModifiedBy>citation-report</cp:lastModifiedBy>"
        '<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created>'
        '<dcterms:modified xsi:type="dcterms:W3CDTF">%s</dcterms:modified>'
        "<cp:revision>1</cp:revision></cp:coreProperties>"
        % (CORE_NS, DC_NS, DCTERMS_NS, XSI_NS, title, stamp, stamp)
    )


# --------------------------------------------------------------------------- #
# Counters and the composer
# --------------------------------------------------------------------------- #


@dataclass
class _Counters:
    """Running totals, reported verbatim so a test can reconcile them with the XML.

    ``shading_elements`` counts every `<w:shd>` written into `word/document.xml`,
    which is what an independent parse of that part can see. It is the sum of the
    per-sentence run backgrounds and the coloured table swatches; both are separated
    out below so the headline number can always be decomposed.
    """

    shading_elements: int = 0
    shaded_runs: int = 0
    shaded_cells: int = 0
    comments: int = 0
    segments: int = 0


@dataclass
class _Anchors:
    """The result of auditing comment anchors against the comments part."""

    starts: int = 0
    ends: int = 0
    references: int = 0
    comments: int = 0
    nested: bool = True
    ok: bool = True
    problems: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "starts": self.starts,
            "ends": self.ends,
            "references": self.references,
            "comments": self.comments,
            "nested": self.nested,
            "ok": self.ok,
            "problems": list(self.problems),
        }


class _Composer:
    """Builds the document body, the comments part and the running counts.

    Kept as one object because the three are genuinely coupled: a comment id is
    allocated at the anchor in the body and consumed in the comments part, and the
    counters have to see every run the body emits.
    """

    def __init__(self, layout, summary, bundle, meta) -> None:
        self.layout = list(layout or [])
        self.summary = summary or {}
        self.bundle = bundle
        self.meta = meta or {}
        self.text = _Text()
        self.counters = _Counters()
        self.warnings: list = []
        #: (comment id, segment) in body order — the same order the notes appendix uses.
        self.notes: list = []
        self.body: list = []
        self.truncated_titles = 0

    # -- low level runs and paragraphs ------------------------------------- #

    def _run(
        self,
        text: object,
        *,
        fill: str | None = None,
        bold: bool = False,
        italic: bool = False,
        color: str | None = None,
        style: str | None = None,
        size: int | None = None,
    ) -> str:
        properties: list = []
        if style:
            properties.append('<w:rStyle w:val="%s"/>' % style)
        if bold:
            properties.append("<w:b/><w:bCs/>")
        if italic:
            properties.append("<w:i/><w:iCs/>")
        if color:
            properties.append('<w:color w:val="%s"/>' % color)
        if size:
            properties.append('<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (size, size))
        if fill:
            # Why w:shd and not <w:highlight>: w:highlight accepts only 16 named
            # colours and cannot represent this palette — it has no light-green for
            # synthesis and no steel-blue for unverifiable — whereas w:shd carries an
            # exact RGB fill, renders as a background in Word, and prints. The fill
            # always comes from _highlight.state_hex; no colour is defined here.
            properties.append(
                '<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % fill
            )
            self.counters.shading_elements += 1
            self.counters.shaded_runs += 1
        content = _run_content(self.text.clean(text))
        if not content:
            content = '<w:t xml:space="preserve"></w:t>'
        return "<w:r><w:rPr>%s</w:rPr>%s</w:r>" % ("".join(properties), content)

    def _paragraph(self, style_id: str, runs: str, *, extra: str = "") -> str:
        body = runs or '<w:r><w:t xml:space="preserve"></w:t></w:r>'
        return "<w:p><w:pPr><w:pStyle w:val=\"%s\"/>%s</w:pPr>%s</w:p>" % (
            style_id,
            extra,
            body,
        )

    def _heading(self, level: int, text: object) -> str:
        """Heading1-4, clamped. Real outline levels are what let Word build a TOC."""
        style = "Heading%d" % min(max(int(level or 1), 1), 4)
        return self._paragraph(style, self._run(text))

    def _plain(self, text: object, *, style: str = "Normal", extra: str = "") -> str:
        return self._paragraph(style, self._run(text), extra=extra)

    def _page_break(self) -> str:
        return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'

    # -- tables ------------------------------------------------------------- #

    def _cell(
        self, runs: str, width: int, *, fill: str | None = None, align: str | None = None
    ) -> str:
        properties = ['<w:tcW w:w="%d" w:type="dxa"/>' % width]
        if fill is not None:
            properties.append(
                '<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % fill
            )
            self.counters.shading_elements += 1
            self.counters.shaded_cells += 1
        extra = '<w:jc w:val="%s"/>' % align if align else ""
        return "<w:tc><w:tcPr>%s</w:tcPr>%s</w:tc>" % (
            "".join(properties),
            self._paragraph("TableText", runs, extra=extra),
        )

    def _table(
        self,
        rows: list,
        widths: list,
        *,
        fixed: bool = False,
        tight_margins: bool = False,
    ) -> str:
        borders = (
            "<w:tblBorders>"
            '<w:top w:val="single" w:sz="4" w:color="808080"/>'
            '<w:left w:val="single" w:sz="4" w:color="808080"/>'
            '<w:bottom w:val="single" w:sz="4" w:color="808080"/>'
            '<w:right w:val="single" w:sz="4" w:color="808080"/>'
            '<w:insideH w:val="single" w:sz="4" w:color="808080"/>'
            '<w:insideV w:val="single" w:sz="4" w:color="808080"/>'
            "</w:tblBorders>"
        )
        properties = [
            '<w:tblW w:w="%d" w:type="dxa"/>' % sum(widths),
            borders,
            '<w:tblLayout w:type="%s"/>' % ("fixed" if fixed else "autofit"),
        ]
        if tight_margins:
            # The coverage bar must read as one continuous strip, so its cells get no
            # internal padding; every other table keeps Word's default cell margins.
            properties.append(
                "<w:tblCellMar>"
                '<w:left w:w="0" w:type="dxa"/><w:right w:w="0" w:type="dxa"/>'
                '<w:top w:w="0" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/>'
                "</w:tblCellMar>"
            )
        parts = [
            "<w:tbl><w:tblPr>%s</w:tblPr><w:tblGrid>%s</w:tblGrid>"
            % ("".join(properties), "".join('<w:gridCol w:w="%d"/>' % w for w in widths))
        ]
        for row in rows:
            parts.append("<w:tr>%s</w:tr>" % "".join(row))
        parts.append("</w:tbl>")
        # Two adjacent `w:tbl` elements merge unless a paragraph separates them.
        parts.append('<w:p><w:pPr><w:spacing w:after="0"/></w:pPr></w:p>')
        return "".join(parts)

    # -- 1. title and metadata ---------------------------------------------- #

    def _title_block(self) -> None:
        summary = self.summary
        coverage = summary.get("citation_coverage") or {}
        uncheckable = summary.get("uncheckable") or {}
        sources = summary.get("sources") or {}

        self.body.append(self._paragraph("Title", self._run(self.meta.get("title") or "Citation report")))
        self.body.append(
            self._paragraph(
                "Subtitle",
                self._run("Citation report \u2014 attribution integrity, not a quality score"),
            )
        )
        numerator = coverage.get("numerator", 0)
        denominator = coverage.get("denominator", 0)
        percent = coverage.get("percent", 0.0)
        definition = coverage.get("definition") or "(attributed + synthesis) / sentences requiring a citation"
        lines = [
            ("Source document", self.meta.get("document_path") or "(not recorded)"),
            ("Generated", _isodate(self.meta.get("generated"))),
            ("Sentences graded", summary.get("sentences_total", 0)),
            (
                "Sentences requiring a citation",
                summary.get("sentences_requiring_citation", 0),
            ),
            (
                "Citation coverage",
                "%s/%s (%.1f%%) \u2014 %s" % (numerator, denominator, percent, definition),
            ),
            (
                "Not checkable here",
                "%s/%s \u2014 %s"
                % (
                    uncheckable.get("numerator", 0),
                    uncheckable.get("denominator", summary.get("sentences_total", 0)),
                    uncheckable.get("detail", "no evidence was held for the cited source"),
                ),
            ),
        ]
        # The coverage denominator is whatever `coverage.compute` decided it is, and
        # that module carries the definition. When it also publishes the denominator
        # as a named count, echo it: otherwise a reader sees "requiring a citation: 4"
        # next to a denominator of 7 and has to guess why they differ.
        if "sentences_with_support_claim" in summary:
            lines.append(
                (
                    "Sentences carrying a support claim",
                    summary.get("sentences_with_support_claim", 0),
                )
            )
        lines.extend(
            (
                (
                    "Sources",
                    "%s recorded, %s with evidence held, %s retracted"
                    % (
                        sources.get("total", 0),
                        sources.get("with_evidence", 0),
                        sources.get("retracted", 0),
                    ),
                ),
                (
                    "Advisory channel",
                    "enabled" if self.meta.get("advisory_enabled") else "disabled",
                ),
            )
        )
        for label, value in lines:
            self.body.append(
                self._paragraph(
                    "Normal",
                    self._run(label + ": ", bold=True) + self._run(value),
                    extra='<w:spacing w:after="0"/>',
                )
            )

    # -- 2. gate banner ------------------------------------------------------ #

    def _gate_banner(self) -> None:
        if str(self.meta.get("gate_status") or "").strip().lower() != "fail":
            return
        self.body.append(
            self._paragraph(
                "Normal",
                self._run(GATE_BANNER, bold=True, color="C00000"),
                extra='<w:spacing w:before="240" w:after="240"/><w:jc w:val="center"/>',
            )
        )

    def _input_bound_banner(self) -> None:
        """The input banner: its own colour and wording, never the gate's.

        A gate failure is a finding about the document. This says the inputs did not
        permit findings. Rendering it in the same red would invite a reader to file
        both under "problems with the draft", which is the confusion it exists to
        prevent -- so it is blue, boxed by an indent, and always followed by the counts.
        """
        message = str(self.meta.get("input_bound_banner") or "").strip()
        if not message:
            return
        self.body.append(
            self._paragraph(
                "Normal",
                self._run(message, bold=True, color="2F3A5C"),
                extra='<w:spacing w:before="200" w:after="80"/><w:jc w:val="center"/>',
            )
        )
        reason = str(self.meta.get("input_bound_reason") or "").strip()
        if reason:
            self.body.append(
                self._paragraph(
                    "Normal",
                    self._run(reason, color="2F3A5C"),
                    extra='<w:spacing w:after="80"/>',
                )
            )
        evidence = self.meta.get("evidence") or {}
        if evidence:
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
            self.body.append(
                self._paragraph(
                    "Normal",
                    self._run(counts, color="2F3A5C", italic=True),
                    extra='<w:spacing w:after="240"/>',
                )
            )

    # -- 3. coverage bar ----------------------------------------------------- #

    def _bar_cells(self) -> list:
        """(state, count, share) for every state that actually occurred."""
        counts = self.summary.get("states") or {}
        return [
            (state, int(counts.get(state, 0) or 0))
            for state in _highlight.STATE_ORDER
            if int(counts.get(state, 0) or 0) > 0
        ]

    def _coverage_bar(self) -> None:
        entries = self._bar_cells()
        total = sum(count for _state, count in entries)
        self.body.append(self._paragraph("Heading2", self._run("Coverage bar")))
        if not total:
            self.body.append(self._plain("No sentences were graded, so there is nothing to show."))
            return
        widths: list = []
        for _state, count in entries:
            share = int(round(TEXT_WIDTH_TWIPS * count / total))
            widths.append(max(MIN_CELL_TWIPS, share))
        # Rounding and the minimum width both push the sum off the text column; put
        # the residue in the widest cell so the bar still spans exactly the margins.
        widest = max(range(len(widths)), key=lambda index: (widths[index], -index))
        widths[widest] += TEXT_WIDTH_TWIPS - sum(widths)
        cells: list = []
        for (state, count), width in zip(entries, widths):
            cells.append(
                self._cell(
                    self._run(count, size=14),
                    width,
                    fill=_highlight.state_hex(state),
                    align="center",
                )
            )
        self.body.append(self._table([cells], widths, fixed=True, tight_margins=True))
        self.body.append(
            self._plain(
                "Cell widths are proportional to the %d graded sentence(s); each cell "
                "carries that state's colour and its count. Colours are defined once, in "
                "_highlight.py, and used by every renderer." % total,
                style="Caption",
            )
        )
        # The caveat sits directly under the bar, so the figure and the reason it is what
        # it is cannot be read apart -- the same placement as the PDF and the HTML.
        caveat = str(self.summary.get("coverage_caveat") or "").strip()
        if caveat:
            self.body.append(
                self._paragraph(
                    "Normal",
                    self._run(caveat, bold=True, color="2F3A5C"),
                    extra='<w:spacing w:before="120" w:after="60"/>',
                )
            )

    def _attribution(self) -> None:
        """The defined claim, with its definition and its scope.

        Printed only when the shared definition is installed. The term never appears in
        the artifact without the definition, the scope and the one exception beside it.
        """
        block = self.meta.get("attribution") or {}
        statement = str(block.get("statement") or "").strip()
        if not statement:
            return
        self.body.append(
            self._paragraph("Heading1", self._run(block.get("heading") or ""))
        )
        for line in block.get("definition") or []:
            self.body.append(self._plain(line))
        self.body.append(
            self._paragraph(
                "Normal",
                self._run(statement, bold=True, color="2F3A5C"),
                extra='<w:spacing w:before="120" w:after="60"/>',
            )
        )
        if "Scope:" not in statement:
            # The boundary is printed even when the statement is withheld, so the
            # reader never meets the term on its own.
            self.body.append(self._plain(block.get("scope") or ""))

    # -- 4. legend ----------------------------------------------------------- #

    def _legend(self) -> None:
        rows_meta = _highlight.legend_rows()
        # The swatch column has to hold a six-digit hex label at 6 pt without
        # wrapping, which sets its minimum width at roughly 560 twips once the
        # default cell margins are counted; 820 leaves room to spare.
        widths = [820, 1580, 5838, 1400]
        self.body.append(self._paragraph("Heading2", self._run("Colour legend")))
        rows: list = []
        for row in rows_meta:
            rows.append(
                [
                    self._cell(
                        self._run(row["hex"], size=12),
                        820,
                        fill=row["hex"],
                        align="center",
                    ),
                    self._cell(self._run(row["label"], bold=True), 1580),
                    self._cell(self._run(row["meaning"]), 5838),
                    self._cell(self._run(row["severity"]), 1400),
                ]
            )
        self.body.append(self._table(rows, widths))

    # -- 5. the graded document ---------------------------------------------- #

    def _segment_pieces(self, text: str, segments: list) -> list:
        """`_highlight.split_at_segments`, repaired for zero-width sentences.

        `split_at_segments` filters out empty pieces, so a sentence whose span is
        empty would lose both its shading and its comment anchor, and the body would
        disagree with the notes appendix. The repair path re-derives the split
        keeping every segment; the warning makes the fallback visible.
        """
        pieces = _highlight.split_at_segments(text, segments)
        covered = {id(segment) for _piece, segment in pieces if segment is not None}
        missing = [segment for segment in segments if id(segment) not in covered]
        if not missing:
            return pieces
        self.warnings.append(
            "repaired %d zero-width sentence span(s) so they still carry a shading run "
            "and a comment anchor" % len(missing)
        )
        repaired: list = []
        cursor = 0
        for segment in sorted(segments, key=lambda item: item.start):
            start = max(cursor, min(segment.start, len(text)))
            end = max(start, min(segment.end, len(text)))
            if start > cursor:
                repaired.append((text[cursor:start], None))
            repaired.append((text[start:end], segment))
            cursor = end
        if cursor < len(text):
            repaired.append((text[cursor:], None))
        return repaired

    def _graded_paragraph(self, layout, style_id: str, extra: str = "") -> str:
        chunks: list = []
        for piece, segment in self._segment_pieces(layout.paragraph.text, layout.segments):
            if segment is None:
                chunks.append(self._run(piece))
                continue
            # One comment per graded sentence. The anchors sit directly in `w:p`, so
            # start and end are always in the same paragraph and the ranges cannot
            # cross: the layout guarantees the segments are sorted and disjoint.
            comment_id = len(self.notes) + 1
            self.notes.append((comment_id, segment))
            self.counters.comments += 1
            fill = _highlight.state_hex(segment.state)
            chunks.append('<w:commentRangeStart w:id="%d"/>' % comment_id)
            chunks.append(self._run(piece, fill=fill))
            chunks.append('<w:commentRangeEnd w:id="%d"/>' % comment_id)
            chunks.append(
                '<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>'
                '<w:commentReference w:id="%d"/></w:r>' % comment_id
            )
        return self._paragraph(style_id, "".join(chunks), extra=extra)

    def _document_body(self) -> None:
        self.body.append(self._paragraph("Heading1", self._run("Graded document")))
        styles = {
            "para": ("Normal", ""),
            "quote": ("Quote", ""),
            "caption": ("Caption", ""),
            "code": ("CodeBlock", ""),
            "table": ("TableText", ""),
            "reference": ("Reference", ""),
            "list_item": (
                "Normal",
                '<w:ind w:left="567" w:hanging="284"/><w:spacing w:after="60"/>',
            ),
        }
        for layout in self.layout:
            paragraph = layout.paragraph
            kind = str(getattr(paragraph, "kind", "para") or "para")
            if kind == "heading":
                if layout.segments:
                    self.body.append(
                        self._graded_paragraph(
                            layout,
                            "Heading%d" % min(max(int(paragraph.level or 1), 1), 4),
                        )
                    )
                else:
                    self.body.append(self._heading(paragraph.level, paragraph.text))
                continue
            style_id, extra = styles.get(kind, ("Normal", ""))
            if kind == "list_item":
                prefix = self._run("\u2022  ")
                chunks: list = []
                for piece, segment in self._segment_pieces(
                    paragraph.text, layout.segments
                ):
                    if segment is None:
                        chunks.append(self._run(piece))
                    else:
                        comment_id = len(self.notes) + 1
                        self.notes.append((comment_id, segment))
                        self.counters.comments += 1
                        fill = _highlight.state_hex(segment.state)
                        chunks.append('<w:commentRangeStart w:id="%d"/>' % comment_id)
                        chunks.append(self._run(piece, fill=fill))
                        chunks.append('<w:commentRangeEnd w:id="%d"/>' % comment_id)
                        chunks.append(
                            '<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>'
                            '<w:commentReference w:id="%d"/></w:r>' % comment_id
                        )
                self.body.append(
                    self._paragraph(style_id, prefix + "".join(chunks), extra=extra)
                )
                continue
            self.body.append(self._graded_paragraph(layout, style_id, extra))

    # -- 6. limits ----------------------------------------------------------- #

    def _limits(self) -> None:
        self.body.append(
            self._paragraph(
                "Heading1", self._run("Limits and what these colours mean")
            )
        )
        paragraphs = [
            "The colours describe attribution integrity: whether every checkable value "
            "in a sentence is present in the evidence held for a source the sentence "
            "cites. They say nothing about writing quality, novelty or importance, and "
            "a green sentence is not an endorsement of its claim.",
            "Unverifiable means no evidence was held for the cited source. It is a "
            "statement about this report's inputs, not a finding about the sentence, "
            "and it is counted separately from both covered and uncovered.",
            "A sentence is never painted red because a value was missing from extracted "
            "text. Extraction routinely loses tables, figures and supplementary "
            "material, so absence is recorded as unverifiable. Red requires a retracted "
            "source, or a value that contradicts the same named measure in a source we "
            "actually hold. A citation that resolves to nothing warns instead: an "
            "unmatched marker has no link to verify.",
            "Advisory grades are advisory and never gate inputs. They are "
            "model-generated, cannot set, change or veto a verdict, and are disclosed "
            "as: %s." % _common.ADVISORY_DISCLOSURE,
        ]
        evidence = self.meta.get("evidence") or {}
        if evidence.get("ocr_transcription_sentences"):
            paragraphs.append(
                "OCR: %s of the graded sentence(s) rest on a transcription (%s) rather "
                "than on the document's own text layer. A value that appears to "
                "contradict a source is reported as unverifiable rather than as a finding "
                "(rule D13), because a misread digit would make it an accusation about "
                "the author."
                % (
                    evidence.get("ocr_transcription_sentences"),
                    evidence.get("document_transcription") or "OCR",
                )
            )
        if getattr(self.bundle, "offline", False):
            paragraphs.append(
                "This run was offline: no DOI was resolved over the network, and every "
                "source was graded on locally held evidence only. An unverified source "
                "here means we did not check it, not that it does not exist."
            )
        if not self.meta.get("advisory_enabled"):
            paragraphs.append(
                "The advisory channel was not enabled for this run, so every grade "
                "shown is a deterministic rule outcome."
            )
        for text in paragraphs:
            self.body.append(self._plain(text))

    # -- 7. sources appendix -------------------------------------------------- #

    def _source_view(self, source) -> dict:
        if hasattr(source, "to_dict"):
            return dict(source.to_dict())
        return {name: getattr(source, name, "") for name in _SOURCE_FIELDS}

    def _truncate(self, value: object, limit: int = 90) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= limit:
            return text or "\u2014"
        self.truncated_titles += 1
        return text[: limit - 1].rstrip() + "\u2026"

    def _sources_appendix(self) -> None:
        self.body.append(self._page_break())
        self.body.append(self._paragraph("Heading1", self._run("Sources")))
        sources = list(getattr(self.bundle, "sources", None) or [])
        if not sources:
            self.body.append(self._plain("No sources were recorded for this document."))
            return
        widths = [700, 1300, 1800, 3138, 1000, 900, 800]
        header = [
            self._cell(self._run("Source", bold=True), widths[0]),
            self._cell(self._run("Number / citekey", bold=True), widths[1]),
            self._cell(self._run("DOI", bold=True), widths[2]),
            self._cell(self._run("Title", bold=True), widths[3]),
            self._cell(self._run("Verification", bold=True), widths[4]),
            self._cell(self._run("Retraction", bold=True), widths[5]),
            self._cell(self._run("Evidence", bold=True), widths[6]),
        ]
        rows = [header]
        for source in sources:
            view = self._source_view(source)
            number = str(view.get("citation_number") or "").strip()
            citekey = str(view.get("citekey") or "").strip()
            label = " / ".join(
                part for part in (("#" + number) if number else "", citekey) if part
            )
            title = view.get("title") or view.get("title_claimed") or ""
            rows.append(
                [
                    self._cell(self._run(view.get("source_id") or "\u2014"), widths[0]),
                    self._cell(self._run(label or "\u2014"), widths[1]),
                    self._cell(self._run(view.get("doi") or "\u2014"), widths[2]),
                    self._cell(self._run(self._truncate(title)), widths[3]),
                    self._cell(
                        self._run(view.get("verification_status") or "\u2014"), widths[4]
                    ),
                    self._cell(
                        self._run(view.get("retraction_status") or "\u2014"), widths[5]
                    ),
                    self._cell(
                        self._run(view.get("evidence_availability") or "\u2014"), widths[6]
                    ),
                ]
            )
        self.body.append(self._table(rows, widths))
        if self.truncated_titles:
            self.warnings.append(
                "%d source title(s) truncated to 90 characters in the sources appendix"
                % self.truncated_titles
            )

    # -- 8. notes appendix ---------------------------------------------------- #

    def _notes_appendix(self) -> None:
        self.body.append(self._page_break())
        self.body.append(self._paragraph("Heading1", self._run("Notes")))
        if not self.notes:
            self.body.append(self._plain("No sentences were graded."))
            return
        self.body.append(
            self._plain(
                "One entry per graded sentence, in document order. The same text is "
                "attached to the sentence as a Word comment.",
                style="Caption",
            )
        )
        for index, (_comment_id, segment) in enumerate(self.notes, start=1):
            verdict = segment.verdict
            sentence_id = str(getattr(verdict, "sentence_id", "") or "?")
            rule_id = str(getattr(verdict, "rule_id", "") or "?")
            runs = self._run("%d. %s" % (index, sentence_id), bold=True)
            runs += self._run("  \u00b7 rule %s" % rule_id)
            runs += self._run("\n" + _highlight.note_text(verdict))
            self.body.append(self._paragraph("NoteEntry", runs))

    # -- comments part -------------------------------------------------------- #

    def _comments_xml(self, iso_date: str) -> str:
        stamp = iso_date + "T00:00:00Z"
        parts: list = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<w:comments xmlns:w="%s">' % W,
        ]
        for comment_id, segment in self.notes:
            verdict = segment.verdict
            lines = [
                "%s  %s"
                % (
                    getattr(verdict, "sentence_id", "") or "?",
                    _highlight.state_label(segment.state),
                )
            ]
            lines.extend(_highlight.note_text(verdict).split("\n"))
            paragraphs = "".join(
                self._paragraph("CommentText", self._run(line)) for line in lines if line
            )
            parts.append(
                '<w:comment w:id="%d" w:author="citation-report" w:initials="CR" '
                'w:date="%s">%s</w:comment>' % (comment_id, stamp, paragraphs)
            )
        parts.append("</w:comments>")
        return "".join(parts)

    # -- assembly -------------------------------------------------------------- #

    def document_xml(self) -> str:
        section = (
            "<w:sectPr>"
            '<w:footerReference w:type="default" r:id="rIdFooter"/>'
            '<w:pgSz w:w="%d" w:h="%d"/>'
            '<w:pgMar w:top="%d" w:right="%d" w:bottom="%d" w:left="%d" '
            'w:header="720" w:footer="454" w:gutter="0"/>'
            '<w:cols w:space="708"/><w:docGrid w:linePitch="360"/>'
            "</w:sectPr>"
            % (
                PAGE_W_TWIPS,
                PAGE_H_TWIPS,
                MARGIN_TWIPS,
                MARGIN_TWIPS,
                MARGIN_TWIPS,
                MARGIN_TWIPS,
            )
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="%s" xmlns:r="%s"><w:body>%s%s</w:body></w:document>'
            % (W, R, "".join(self.body), section)
        )

    def build(self, iso_date: str) -> tuple:
        self._title_block()
        self._gate_banner()
        # Called unconditionally: an input gap fires with or without gate errors, and
        # nesting it inside the gate banner would hide it on a clean-but-unverifiable run.
        self._input_bound_banner()
        self._coverage_bar()
        self._attribution()
        self._legend()
        self._document_body()
        self._limits()
        self._sources_appendix()
        self._notes_appendix()
        return self.document_xml(), self._comments_xml(iso_date)


# --------------------------------------------------------------------------- #
# Anchor audit
# --------------------------------------------------------------------------- #


def _audit_anchors(document_xml: str, comments_xml: str) -> _Anchors:
    """Cross-check every comment id between the body and the comments part.

    Word declares a package corrupt when a `w:commentReference` names an id that
    `comments.xml` does not define, and it silently shows nothing when the reverse
    happens. Both are cheap to detect from the XML this module just produced, so the
    check runs on every render rather than only in tests.
    """
    audit = _Anchors()
    try:
        document = ET.fromstring(document_xml)
        comments = ET.fromstring(comments_xml)
    except ET.ParseError as exc:  # pragma: no cover - a bug here is a hard failure
        audit.ok = False
        audit.problems.append("XML did not parse: %s" % exc)
        return audit

    qid = "{%s}id" % W
    starts = [node.get(qid) for node in document.iter("{%s}commentRangeStart" % W)]
    ends = [node.get(qid) for node in document.iter("{%s}commentRangeEnd" % W)]
    references = [node.get(qid) for node in document.iter("{%s}commentReference" % W)]
    defined = [node.get(qid) for node in comments.iter("{%s}comment" % W)]
    audit.starts = len(starts)
    audit.ends = len(ends)
    audit.references = len(references)
    audit.comments = len(defined)

    if len(set(starts)) != len(starts):
        audit.problems.append("a comment id is started more than once")
    if sorted(starts) != sorted(ends):
        audit.problems.append("commentRangeStart and commentRangeEnd ids differ")
    if sorted(starts) != sorted(references):
        audit.problems.append("commentRangeStart and commentReference ids differ")
    if sorted(defined) != sorted(starts):
        audit.problems.append("comment ids do not match the anchors one for one")

    # Nesting: within each paragraph the anchors must open and close in order, and
    # every opened range must be closed before the paragraph ends.
    for paragraph_index, paragraph in enumerate(document.iter("{%s}p" % W)):
        stack: list = []
        for child in paragraph:
            if child.tag == "{%s}commentRangeStart" % W:
                if stack:
                    audit.nested = False
                    audit.problems.append(
                        "comment ranges overlap in paragraph %d" % paragraph_index
                    )
                stack.append(child.get(qid))
            elif child.tag == "{%s}commentRangeEnd" % W:
                if not stack or stack[-1] != child.get(qid):
                    audit.nested = False
                    audit.problems.append(
                        "comment range closes out of order in paragraph %d"
                        % paragraph_index
                    )
                    stack = []
                else:
                    stack.pop()
        if stack:
            audit.nested = False
            audit.problems.append(
                "comment range left open at the end of paragraph %d" % paragraph_index
            )
    audit.ok = not audit.problems
    return audit


# --------------------------------------------------------------------------- #
# Zip assembly
# --------------------------------------------------------------------------- #


def _zip_bytes(parts: list) -> bytes:
    """Write the parts in a fixed order with fixed metadata.

    `date_time` and `create_system` are pinned because both otherwise leak the
    machine and the clock into the bytes, and a reproducible artifact is worth more
    than a realistic timestamp.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=ZIP_COMPRESSLEVEL
    ) as archive:
        for name, content in parts:
            payload = content.encode("utf-8") if isinstance(content, str) else content
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            archive.writestr(info, payload, compresslevel=ZIP_COMPRESSLEVEL)
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# Public interface
# --------------------------------------------------------------------------- #


def render(layout, summary, bundle, meta) -> tuple:
    """Render the report to zip bytes, plus the report dict.

    Separate from `write_docx` so a caller that wants bytes — an HTTP response, a
    test, a comparison of two runs — never has to touch the filesystem.
    """
    meta = dict(meta or {})
    raw_generated = str(meta.get("generated") or "").strip()
    iso_date = _isodate(raw_generated)
    composer = _Composer(layout, summary, bundle, meta)
    if not re.match(r"^\d{4}-\d{2}-\d{2}", raw_generated):
        composer.warnings.append(
            "meta['generated'] is missing or is not an ISO date; comment and document "
            "dates pinned to %s so the output stays reproducible" % iso_date
        )
    composer.counters.segments = sum(len(item.segments or []) for item in composer.layout)
    document_xml, comments_xml = composer.build(iso_date)
    audit = _audit_anchors(document_xml, comments_xml)
    if not audit.ok:
        composer.warnings.append(
            "comment anchor audit failed: " + "; ".join(audit.problems)
        )
    parts = [
        ("[Content_Types].xml", CONTENT_TYPES),
        ("_rels/.rels", ROOT_RELS),
        ("word/document.xml", document_xml),
        ("word/_rels/document.xml.rels", DOCUMENT_RELS),
        ("word/styles.xml", styles_xml()),
        ("word/comments.xml", comments_xml),
        ("word/footer1.xml", FOOTER_XML),
        ("docProps/core.xml", core_xml(meta, iso_date, composer.text)),
        ("docProps/app.xml", APP_XML),
    ]
    payload = _zip_bytes(parts)

    if composer.text.stripped:
        composer.warnings.insert(
            0,
            "stripped %d character(s) illegal in XML 1.0; the text could not be "
            "carried in the document" % composer.text.stripped,
        )
    report = {
        "format": "docx",
        "bytes": len(payload),
        "highlights": composer.counters.shading_elements,
        "shaded_runs": composer.counters.shaded_runs,
        "shaded_cells": composer.counters.shaded_cells,
        "notes": len(composer.notes),
        "comments": composer.counters.comments,
        "segments": composer.counters.segments,
        "tables": sum(1 for part in composer.body if isinstance(part, str) and part.startswith("<w:tbl>")),
        "parts": [name for name, _content in parts],
        "anchors": audit.to_dict(),
        "warnings": list(composer.warnings),
    }
    return payload, report


def write_docx(path, layout, summary, bundle, meta) -> dict:
    """Write the .docx to `path` and return the same report dict `render` returns.

    `report["bytes"]` is the length of the payload written, so it equals the file
    size on disk; the byte sequence itself is what `render` returned, unmodified.
    """
    payload, report = render(layout, summary, bundle, meta)
    _common.write_bytes(path, payload)
    return report


if __name__ == "__main__":
    print("This module is imported by the citation-report command-line tools.")
