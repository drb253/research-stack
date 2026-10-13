"""Read a document into a paragraph model with exact offsets, then into sentences.

Supported inputs and what each can do:

| Suffix | Reader | Notes |
|---|---|---|
| `.md` `.markdown` `.txt` `.rst` | native | headings, lists, quotes, fenced code and tables recognised |
| `.docx` | stdlib `zipfile` + `ElementTree` | paragraphs, tables, text boxes (once), footnotes and endnotes; comments and tracked changes are out of scope and disclosed |
| `.tex` | native | preamble removed, `\\section` hierarchy, `\\parencite`/`\\cite` become citation markers |
| `.pdf` | `_pdftext` cascade | needs poppler or `pypdf`; refuses legibly rather than grading against unreadable evidence |

Every paragraph records its character range inside ``Document.text``, so a sentence
span is always re-locatable. That property is what makes the report checkable: the
gate re-derives every span and fails if a sentence cannot be found again.

Only narrative paragraphs (``para``, ``list_item``, ``quote``, ``caption``) become
sentences. Headings, tables and code are kept for rendering but carry no verdict —
grading a table row for "citation support" would be noise, and the coverage
denominator must not include it.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

import _sentences

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

NARRATIVE_KINDS = ("para", "list_item", "quote", "caption")
EXCLUDED_KINDS = ("heading", "table", "code", "reference")

#: A trailing run of numbered paragraphs this long, reaching the end of the
#: document, is a bibliography rather than a body list.
REFERENCE_RUN_MIN = 5
#: A preceding `References`-style heading is a stronger signal than length, so a
#: short bibliography under such a heading is still recognised. Without this, a
#: three-entry reference list is graded as prose and its `[Internet]` apparatus
#: becomes false findings.
REFERENCE_RUN_MIN_WITH_HEADING = 3
NUMBERED_PARAGRAPH_RE = re.compile(r"^([0-9]{1,3})[.)]\s+(.+)$")
REFERENCE_HEADING_RE = re.compile(
    r"^(?:references|reference list|bibliography|works cited|literature cited|"
    r"sources|references cited)\s*:?\s*$",
    re.IGNORECASE,
)
#: A bibliography entry almost always carries a year, a DOI, an `et al`, or a
#: `volume(issue)` pair. Any one of those is enough to tell an entry from a numbered
#: body list, which is what lets a one- or two-entry bibliography be recognised under
#: a `References` heading. Failing to recognise it is not a neutral outcome: the entry
#: is then graded as prose and its numeric citation becomes a false "fabricated
#: citation" finding, which is the most damaging thing this tool can say.
DOI_SHAPE_RE = re.compile(r"\b10\.[0-9]{4,9}/\S+")
VOLUME_ISSUE_RE = re.compile(r"\b[0-9]{1,4}\s?\(\s?[0-9]{1,4}\s?\)")
ET_AL_RE = re.compile(r"\bet\s+al\b", re.IGNORECASE)
YEAR_SHAPE_RE = re.compile(r"\b(1[89][0-9]{2}|20[0-9]{2})\b")


def _looks_bibliographic(text: str) -> bool:
    return bool(
        YEAR_SHAPE_RE.search(text)
        or DOI_SHAPE_RE.search(text)
        or VOLUME_ISSUE_RE.search(text)
        or ET_AL_RE.search(text)
    )

TEXT_SUFFIXES = (".md", ".markdown", ".txt", ".rst", ".text")
SUPPORTED_SUFFIXES = TEXT_SUFFIXES + (".docx", ".tex", ".pdf")


class IntakeError(ValueError):
    """Raised when a document cannot be read well enough to grade."""


class UnreadableDocument(IntakeError):
    """Raised when a document could not be read *at all*, so nothing can be graded.

    This is deliberately distinct from a generic :class:`IntakeError`: an unreadable input
    is an input condition rather than a finding, and the caller must report it as
    ``insufficient_input`` (exit 4) rather than in the finding channel
    (``INVALID_INPUT``, exit 1). Conditions that raise it are the three ways a PDF can be
    unreadable -- no text layer at all (a scan), an extraction below the density
    threshold (probably a scan), and no extractor installed (or an extractor that could
    not decode the file). In every case the honest answer is "we could not read this",
    never a document that graded to zero sentences.

    The gap kind and its worklist travel with the exception so the caller can emit a
    structured gap rather than leaving the reader to parse prose.
    """

    def __init__(self, message: str, *, kind: str = "unreadable_document",
                 how_to_close: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.how_to_close = how_to_close


@dataclass
class DocParagraph:
    index: int
    kind: str
    text: str
    char_start: int = 0
    char_end: int = 0
    level: int = 0
    page: int = 0
    #: The original leading marker for a list item (`1.`, `2)`, `-`), preserved
    #: because the Markdown reader strips it from `text`. Without it, a numbered
    #: reference list written as a Markdown ordered list loses its numbering, and the
    #: numeric citations pointing at it cannot be resolved at all.
    marker: str = ""

    def to_dict(self) -> dict:
        payload = {
            "index": self.index,
            "kind": self.kind,
            "level": self.level,
            "text": self.text,
            "char_start": self.char_start,
            "char_end": self.char_end,
        }
        if self.marker:
            payload["marker"] = self.marker
        return payload


def reference_number(paragraph) -> str:
    """The entry number of a reference paragraph, or ``""`` when it has none."""
    match = NUMBERED_PARAGRAPH_RE.match(paragraph.text.strip())
    if match:
        return match.group(1)
    marker_match = re.match(r"^([0-9]{1,3})[.)]$", (getattr(paragraph, "marker", "") or "").strip())
    return marker_match.group(1) if marker_match else ""


def reference_body(paragraph) -> str:
    """The reference entry text with its leading number removed."""
    match = NUMBERED_PARAGRAPH_RE.match(paragraph.text.strip())
    if match:
        return match.group(2).strip()
    return paragraph.text.strip()


@dataclass
class Document:
    path: str
    format: str
    text: str
    paragraphs: list = field(default_factory=list)
    sentences: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    title: str = ""
    method: str = "native"

    @property
    def narrative_sentence_count(self) -> int:
        excluded = self._excluded_paragraph_ranges()
        return sum(1 for sentence in self.sentences if not _inside(sentence, excluded))

    def _excluded_paragraph_ranges(self) -> list:
        return [
            (paragraph.char_start, paragraph.char_end)
            for paragraph in self.paragraphs
            if paragraph.kind in EXCLUDED_KINDS
        ]

    def narrative_sentences(self) -> list:
        """The sentences the report grades, in document order."""
        excluded = self._excluded_paragraph_ranges()
        return [sentence for sentence in self.sentences if not _inside(sentence, excluded)]

    def paragraph_of(self, char_start: int) -> DocParagraph | None:
        for paragraph in self.paragraphs:
            if paragraph.char_start <= char_start < paragraph.char_end:
                return paragraph
        return None

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "format": self.format,
            "method": self.method,
            "chars": len(self.text),
            "paragraphs": len(self.paragraphs),
            "sentences": len(self.sentences),
            "narrative_sentences": self.narrative_sentence_count,
            "warnings": list(self.warnings),
        }


def _inside(sentence, ranges: list) -> bool:
    for begin, end in ranges:
        if begin <= sentence.char_start < end:
            return True
    return False


# --------------------------------------------------------------------------- #
# Plain text and Markdown
# --------------------------------------------------------------------------- #

FENCE_RE = re.compile(r"^\s*(```|~~~)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
LIST_RE = re.compile(r"^\s*([-*+]|\d+[.)])\s+(.*)$")
QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
SETEXT_RE = re.compile(r"^(=+|-{3,})\s*$")

#: HTML comments are not rendered, so they are not prose and must not be graded.
#: Without this, a document that documents itself (as the shipped example does)
#: is graded on its own commentary.
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

#: A whitelist of presentational tags, removed from paragraph text. Deliberately not
#: a general `<[^>]+>` strip: prose legitimately contains mathematics such as
#: `p < 0.001 and x > 2`, and a general strip would silently delete it.
HTML_TAG_RE = re.compile(
    r"</?(?:br|b|i|em|strong|sub|sup|span|p|div|small|code|u|mark)\b[^>]*>",
    re.IGNORECASE,
)


def _strip_markup(text: str) -> str:
    """Remove HTML comments and presentational tags, preserving mathematical `<`."""
    return HTML_TAG_RE.sub("", HTML_COMMENT_RE.sub(" ", text))


def _plain_paragraphs(text: str) -> list:
    """Split plain text/Markdown into typed paragraphs."""
    paragraphs: list = []
    lines = _strip_markup(text).split("\n")
    index = 0
    in_fence = False
    fence_marker = ""
    buffer: list = []
    buffer_kind = "para"

    def flush() -> None:
        nonlocal index, buffer, buffer_kind
        joined = " ".join(part.strip() for part in buffer).strip()
        if joined:
            paragraphs.append(DocParagraph(index=index, kind=buffer_kind, text=joined))
            index += 1
        buffer = []
        buffer_kind = "para"

    position = 0
    while position < len(lines):
        line = lines[position]
        if in_fence:
            if FENCE_RE.match(line) and line.strip().startswith(fence_marker):
                in_fence = False
                flush()
            else:
                paragraphs.append(
                    DocParagraph(index=index, kind="code", text=line, level=0)
                )
                index += 1
            position += 1
            continue
        fence = FENCE_RE.match(line)
        if fence:
            flush()
            in_fence = True
            fence_marker = fence.group(1)
            position += 1
            continue
        if not line.strip():
            flush()
            position += 1
            continue
        heading = HEADING_RE.match(line)
        if heading:
            flush()
            paragraphs.append(
                DocParagraph(
                    index=index,
                    kind="heading",
                    text=heading.group(2).strip(),
                    level=len(heading.group(1)),
                )
            )
            index += 1
            position += 1
            continue
        if TABLE_RE.match(line):
            flush()
            paragraphs.append(
                DocParagraph(index=index, kind="table", text=line.strip(), level=0)
            )
            index += 1
            position += 1
            continue
        quote = QUOTE_RE.match(line)
        if quote:
            if buffer_kind != "quote" and buffer:
                flush()
            buffer_kind = "quote"
            buffer.append(quote.group(1))
            position += 1
            continue
        item = LIST_RE.match(line)
        if item:
            flush()
            paragraphs.append(
                DocParagraph(
                    index=index,
                    kind="list_item",
                    text=item.group(2).strip(),
                    marker=item.group(1).strip(),
                )
            )
            index += 1
            position += 1
            continue
        # Setext heading: text on one line, `===` or `---` beneath.
        if (
            position + 1 < len(lines)
            and SETEXT_RE.match(lines[position + 1])
            and line.strip()
        ):
            flush()
            marker = lines[position + 1].strip()
            paragraphs.append(
                DocParagraph(
                    index=index,
                    kind="heading",
                    text=line.strip(),
                    level=1 if marker.startswith("=") else 2,
                )
            )
            index += 1
            position += 2
            continue
        if buffer_kind != "para" and buffer:
            flush()
        buffer_kind = "para"
        buffer.append(line)
        position += 1
    flush()
    return paragraphs


# --------------------------------------------------------------------------- #
# DOCX
# --------------------------------------------------------------------------- #


def _is_superscript(run) -> bool:
    """True when the run's properties mark it as superscript.

    Nature-style numeric citations are superscript numbers with no brackets, so a
    bracket grammar finds nothing in such a document and every checkable sentence would
    be reported as unattributed -- thousands of accusations that the author failed to
    cite. Word records the formatting, so the information is recoverable here in a way
    it is not from a PDF text layer.
    """
    for properties in run.iter(W + "rPr"):
        for node in properties.iter(W + "vertAlign"):
            if (node.get(W + "val") or "").lower() == "superscript":
                return True
    return False


#: A superscript run that is only a citation number. Punctuation and separators are
#: allowed; anything else means the superscript is a footnote marker or mathematics.
SUPERSCRIPT_MARKER_RE = re.compile(r"^[0-9]{1,4}(?:\s*[,\u2013\u2014-]\s*[0-9]{1,4})*$")


def _run_text(run) -> str:
    """Text of one `w:r`, honouring tabs and breaks.

    A superscript run holding only a citation number is bracketed, so the existing
    numeric grammar can bind it. That changes the text the report renders slightly --
    it shows `[12]` where the document showed a superscript `12` -- which is a fair
    trade for being able to read the citation at all, and the report says so.
    """
    pieces: list = []
    for node in run.iter():
        tag = node.tag
        if tag == W + "t":
            pieces.append(node.text or "")
        elif tag == W + "tab":
            pieces.append(" ")
        elif tag in (W + "br", W + "cr"):
            pieces.append(" ")
        elif tag == W + "noBreakHyphen":
            pieces.append("-")
    text = "".join(pieces)
    if text.strip() and _is_superscript(run) and SUPERSCRIPT_MARKER_RE.match(text.strip()):
        return "[%s]" % text.strip()
    return text


def _paragraph_style(paragraph) -> str:
    for node in paragraph.iter(W + "pStyle"):
        value = node.get(W + "val")
        if value:
            return value
    return ""


def _iter_runs(paragraph):
    """Runs of one `w:p` whose text belongs to it, each yielded exactly once.

    ``paragraph.iter(W + "r")`` descends into a `w:txbxContent` (a text box) and yields
    both the run that *holds* the drawing and the runs *inside* the box. The holding
    run's own `_run_text` walks into the same box, so every text-box sentence was
    collected twice and graded twice. Nested runs are skipped here, so the box's text
    survives once, from the run that holds it.
    """
    def walk(node, nested: bool = False):
        for child in node:
            child_nested = nested or child.tag in (W + "r", W + "txbxContent")
            if child.tag == W + "r" and not nested:
                yield child
            yield from walk(child, child_nested)

    return walk(paragraph)


def _paragraph_text(paragraph) -> str:
    """Whitespace-collapsed text of one paragraph, with each run counted once."""
    text = "".join(_run_text(run) for run in _iter_runs(paragraph))
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _note_paragraphs(payload: bytes, tag: str, start_index: int) -> tuple:
    """Paragraphs from a `word/footnotes.xml` or `word/endnotes.xml` part.

    Word writes its own `separator` and `continuationSeparator` entries into those
    parts; they are rule marks rather than prose and are skipped by `w:type`. Every
    remaining `w:footnote`/`w:endnote` contributes its `w:p` text, read with the same
    run walker and whitespace collapse the body uses.

    Footnotes carry graded prose: a sentence that lives only in a footnote is still a
    claim, and not reading it made a document the tool could not read look like a
    document with nothing to check.
    """
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise IntakeError("docx %s part is not well-formed XML" % tag) from exc

    paragraphs: list = []
    index = start_index
    for note in root.findall(W + tag):
        if (note.get(W + "type") or "") in ("separator", "continuationSeparator"):
            continue
        for para in note.iter(W + "p"):
            text = _paragraph_text(para)
            if not text:
                continue
            paragraphs.append(DocParagraph(index=index, kind="para", text=text))
            index += 1
    return paragraphs, index


def _docx_paragraphs(path: Path) -> tuple[list, list]:
    warnings: list = []
    note_parts: list = []
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "word/document.xml" not in names:
                raise IntakeError("docx has no word/document.xml part")
            payload = archive.read("word/document.xml")
            # Footnotes and endnotes hold graded prose, so the parts are read rather than
            # merely disclosed. Comments are still not read, and are still warned about.
            for extra, label in (
                ("word/footnotes.xml", "footnote"),
                ("word/endnotes.xml", "endnote"),
            ):
                if extra in names:
                    note_parts.append((label, archive.read(extra)))
            if "word/comments.xml" in names:
                warnings.append("comments are not read; their text is not graded")
    except zipfile.BadZipFile as exc:
        raise IntakeError("docx is not a readable zip container") from exc

    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise IntakeError("docx document.xml is not well-formed XML") from exc

    paragraphs: list = []
    index = 0
    body = root.find(W + "body")
    if body is None:
        body = root
    for child in body:
        if child.tag == W + "p":
            text = "".join(_run_text(run) for run in _iter_runs(child))
            text = re.sub(r"[ \t]{2,}", " ", text).strip()
            if not text:
                continue
            style = _paragraph_style(child)
            kind = "para"
            level = 0
            lowered = style.lower()
            if lowered.startswith("heading") or lowered in ("title", "subtitle"):
                kind = "heading"
                digits = re.findall(r"[0-9]+", style)
                level = int(digits[0]) if digits else 1
                if lowered in ("title", "subtitle"):
                    level = 1 if lowered == "title" else 2
            elif "list" in lowered:
                kind = "list_item"
            elif "caption" in lowered:
                kind = "caption"
            paragraphs.append(
                DocParagraph(index=index, kind=kind, text=text, level=level)
            )
            index += 1
        elif child.tag == W + "tbl":
            for row in child.iter(W + "tr"):
                cells = []
                for cell in row.findall(W + "tc"):
                    cell_text = " ".join(
                        "".join(_run_text(run) for run in _iter_runs(para)).strip()
                        for para in cell.findall(W + "p")
                    )
                    cells.append(re.sub(r"\s{2,}", " ", cell_text).strip())
                line = " | ".join(cell for cell in cells if cell)
                if line:
                    paragraphs.append(
                        DocParagraph(index=index, kind="table", text=line)
                    )
                    index += 1
    # Body first, then footnotes, then endnotes: a note is read after the text it
    # annotates, so the paragraph order stays stable and the offsets re-locate.
    for label, part_payload in note_parts:
        notes, index = _note_paragraphs(part_payload, label, index)
        paragraphs.extend(notes)
    if not paragraphs:
        raise IntakeError("docx contains no readable paragraphs")
    return paragraphs, warnings


# --------------------------------------------------------------------------- #
# LaTeX
# --------------------------------------------------------------------------- #

TEX_COMMENT_RE = re.compile(r"(?<!\\)%.*$", re.MULTILINE)
TEX_DOCUMENT_RE = re.compile(r"\\begin\{document\}(.*?)\\end\{document\}", re.DOTALL)
TEX_SECTION_RE = re.compile(
    r"\\(?:sub)*section\*?\{([^{}]*)\}|\\(?:sub)*subsection\*?\{([^{}]*)\}", re.DOTALL
)
TEX_HEADING_CMDS = {
    "section": 2,
    "subsection": 3,
    "subsubsection": 4,
    "paragraph": 5,
    "chapter": 1,
    "part": 0,
}
TEX_DROP_ENVIRONMENTS = (
    "table", "table*", "figure", "figure*", "algorithm", "algorithm2e",
    "tabular", "tabularx", "verbatim", "lstlisting", "tikzpicture",
)
TEX_CITE_TWO_RE = re.compile(r"\\parencites?\{([^{}]*)\}\{([^{}]*)\}")
TEX_CITE_ONE_RE = re.compile(r"\\[a-zA-Z]*cite[a-zA-Z]*\*?(?:\[[^\]]*\])*\{([^{}]*)\}")
TEX_REF_RE = re.compile(r"\\(?:label|ref|eqref|autoref|pageref)\{[^{}]*\}")
TEX_URL_RE = re.compile(r"\\url\{([^{}]*)\}")
TEX_NOTE_RE = re.compile(r"\\pdfcomment(?:\[[^\]]*\])?\{")
TEX_KEEP_ARG_RE = re.compile(
    r"\\(?:textbf|textit|emph|texttt|textsc|underline|hl[a-z]+|hllightgreen|"
    r"hldarkgreen|hlorange|hlred|mbox|text|mathrm|mathit|ensuremath|SI|num|qty|"
    r"say|foreignlanguage|textsuperscript|textsubscript)\{"
)


def _strip_tex_environments(text: str) -> str:
    for name in TEX_DROP_ENVIRONMENTS:
        pattern = re.compile(
            r"\\begin\{" + re.escape(name) + r"\}.*?\\end\{" + re.escape(name) + r"\}",
            re.DOTALL,
        )
        text = pattern.sub(" ", text)
    return text


#: Control character used to carry a heading through command stripping. It cannot
#: occur in LaTeX source, so it cannot collide with real content.
HEADING_SENTINEL = "\u0001"


def _protect_tex_headings(text: str) -> str:
    """Replace heading commands with sentinel lines so later stripping keeps them."""
    pattern = re.compile(
        r"\\(part|chapter|section|subsection|subsubsection|paragraph)\*?\s*\{"
    )
    while True:
        match = pattern.search(text)
        if not match:
            return text
        title, end = _strip_balanced(text, match.end() - 1)
        level = TEX_HEADING_CMDS.get(match.group(1), 3)
        replacement = (
            "\n\n"
            + HEADING_SENTINEL
            + str(level)
            + HEADING_SENTINEL
            + re.sub(r"\s+", " ", title).strip()
            + HEADING_SENTINEL
            + "\n\n"
        )
        text = text[: match.start()] + replacement + text[end:]


def _strip_balanced(text: str, opener_index: int) -> tuple:
    """Return (argument, end_index) for a `{...}` group starting at `opener_index`."""
    depth = 0
    position = opener_index
    while position < len(text):
        char = text[position]
        if char == "\\":
            position += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[opener_index + 1 : position], position + 1
        position += 1
    return text[opener_index + 1 :], len(text)


def _drop_command(text: str, command: str) -> str:
    pattern = re.compile(r"\\" + re.escape(command) + r"\s*\{")
    while True:
        match = pattern.search(text)
        if not match:
            return text
        _, end = _strip_balanced(text, match.end() - 1)
        text = text[: match.start()] + " " + text[end:]


def _unwrap_command(text: str, command: str) -> str:
    pattern = re.compile(r"\\" + re.escape(command) + r"\s*\{")
    while True:
        match = pattern.search(text)
        if not match:
            return text
        argument, end = _strip_balanced(text, match.end() - 1)
        text = text[: match.start()] + argument + text[end:]


def _tex_to_paragraphs(raw: str) -> tuple[list, list]:
    warnings: list = []
    text = TEX_COMMENT_RE.sub("", raw)
    document = TEX_DOCUMENT_RE.search(text)
    if document:
        text = document.group(1)
    else:
        warnings.append("no \\begin{document} found; the whole file was treated as body text")

    text = _strip_tex_environments(text)
    # `\pdfcomment[...]{...}` is a margin note from the reference implementation:
    # drop the whole command, it is metadata rather than prose.
    text = _drop_command(text, "pdfcomment")
    # Promote headings to a sentinel BEFORE the generic command stripper runs,
    # otherwise `\section{Introduction}` is deleted as an unknown command and the
    # document loses its structure.
    text = _protect_tex_headings(text)
    text = TEX_REF_RE.sub(" ", text)
    text = TEX_URL_RE.sub(r"\1", text)
    # Two-key `\parencites{a}{b}` then single-key citation forms.
    text = TEX_CITE_TWO_RE.sub(lambda m: "[" + m.group(1).strip() + ";" + m.group(2).strip() + "]", text)
    text = TEX_CITE_ONE_RE.sub(lambda m: "[" + m.group(1).replace(",", ";") + "]", text)
    # Unwrap formatting commands that carry their own visible content.
    for command in (
        "textbf", "textit", "emph", "texttt", "textsc", "underline",
        "hllightgreen", "hldarkgreen", "hlorange", "hlred", "mbox", "text",
        "foreignlanguage", "textsuperscript", "textsubscript", "SI", "num", "qty",
    ):
        text = _unwrap_command(text, command)
    # Leftover commands: drop a single braced argument, then any bare command.
    text = re.sub(r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})?", " ", text)
    text = re.sub(r"[{}]", "", text)
    text = (
        text.replace("\\%", "%")
        .replace("\\&", "&")
        .replace("\\_", "_")
        .replace("\\$", "$")
        .replace("\\#", "#")
        .replace("~", " ")
    )
    text = re.sub(r"[ \t]{2,}", " ", text)

    paragraphs: list = []
    index = 0
    # Headings were replaced by a sentinel line before command stripping, so they
    # survive intact and are recognised here.
    sentinel_re = re.compile(
        r"^" + HEADING_SENTINEL + r"([0-9]+)" + HEADING_SENTINEL + r"(.*)" + HEADING_SENTINEL + r"$"
    )
    chunks = re.split(r"\n\s*\n+", text)
    for chunk in chunks:
        for raw_line in chunk.split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            marker = sentinel_re.match(line)
            if marker:
                paragraphs.append(
                    DocParagraph(
                        index=index,
                        kind="heading",
                        text=re.sub(r"\s+", " ", marker.group(2)).strip(),
                        level=int(marker.group(1)),
                    )
                )
                index += 1
                continue
            for entry in _wrap_lines(line):
                paragraphs.append(DocParagraph(index=index, kind="para", text=entry))
                index += 1
    return paragraphs, warnings


def _wrap_lines(block: str) -> list:
    """Join hard-wrapped lines inside one paragraph into single logical lines."""
    lines = [line.strip() for line in block.split("\n")]
    merged: list = []
    for line in lines:
        if not line:
            continue
        if merged and (merged[-1].endswith("-") and not merged[-1].endswith("--")):
            merged[-1] = merged[-1][:-1] + line
        else:
            merged.append(line)
    return [re.sub(r"\s{2,}", " ", line) for line in merged if line]


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #

PAGE_NUMBER_RE = re.compile(r"^\s*(?:page\s+)?[0-9]{1,4}\s*$", re.IGNORECASE)


def _pdf_paragraphs(path: Path) -> tuple[list, list, str]:
    import _pdftext

    extracted = _pdftext.extract_pdf(path)
    if not extracted.available:
        # A file that was not read at all is an input condition with its own status and
        # exit code, not a finding about the document. `_pdftext` names the kind so the
        # refusal can carry a worklist instead of only a sentence.
        raise UnreadableDocument(
            extracted.error or "PDF text layer is not readable",
            kind=getattr(extracted, "gap_kind", "") or "unreadable_pdf",
            how_to_close=getattr(extracted, "gap_worklist", ""),
        )

    warnings = list(extracted.warnings)
    paragraphs: list = []
    index = 0
    blocks = re.split(r"\n\s*\n+", extracted.text)
    for block in blocks:
        lines = [line.rstrip() for line in block.split("\n")]
        lines = [line for line in lines if line.strip()]
        if not lines:
            continue
        if len(lines) == 1 and PAGE_NUMBER_RE.match(lines[0]):
            continue
        merged: list = []
        for line in lines:
            stripped = line.strip()
            if PAGE_NUMBER_RE.match(stripped) and len(stripped) <= 4:
                continue
            if merged and merged[-1].endswith("-") and not merged[-1].endswith("--"):
                merged[-1] = merged[-1][:-1] + stripped
            else:
                merged.append(stripped)
        for entry in merged:
            text = re.sub(r"\s{2,}", " ", entry).strip()
            if not text:
                continue
            kind = "heading" if _looks_like_heading(text) else "para"
            paragraphs.append(DocParagraph(index=index, kind=kind, text=text))
            index += 1
    return paragraphs, warnings, extracted.method


def _looks_like_heading(text: str) -> bool:
    if len(text) > 90 or text.endswith("."):
        return False
    if re.match(r"^[0-9]+(?:\.[0-9]+)*\s+\S", text):
        return True
    words = text.split()
    if 1 <= len(words) <= 8 and sum(word[:1].isupper() for word in words) >= max(1, len(words) - 1):
        return text.lower() not in {"references", "introduction", "methods", "results", "discussion"}
    return False


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def _longest_consecutive_run(numbered: list) -> list:
    """Longest run of consecutive paragraph positions carrying consecutive numbers."""
    best: list = []
    current: list = []
    for position, number in numbered:
        if current:
            last_position, last_number = current[-1]
            if position == last_position + 1 and int(number) == int(last_number) + 1:
                current.append((position, number))
                continue
        if len(current) > len(best):
            best = current
        current = [(position, number)]
    if len(current) > len(best):
        best = current
    return best


def mark_reference_list(paragraphs: list) -> int:
    """Mark a trailing numbered bibliography as structural, and return its length.

    Reference entries are full of bracketed apparatus — `[Internet]`, `[cited 2026
    Jan 5]` — which the citation grammars would otherwise read as markers and
    report as fabricated citations. They are also not prose: a bibliography entry
    is not a claim, so grading it for "citation support" is noise that would swamp
    the real findings. Both problems are fixed by marking them here.

    Two independent signals are accepted, because either alone has a failure mode: a
    long trailing run (which mislabels a short bibliography as prose) or a
    `References` heading (which could label a numbered body list). Requiring the run
    to reach the end of the document guards both, and a heading merely lowers the
    length threshold rather than removing it.
    """
    numbered = [
        (position, reference_number(paragraph))
        for position, paragraph in enumerate(paragraphs)
    ]
    numbered = [(position, number) for position, number in numbered if number]
    # No global length floor here: each path below applies its own. A short
    # bibliography under a `References` heading must still be recognised, because the
    # alternative is grading its entries as prose and reporting the document's own
    # citations as fabricated.
    if not numbered:
        return 0

    total = len(paragraphs)
    candidates: list = []

    run = _longest_consecutive_run(numbered)
    if (
        len(run) >= REFERENCE_RUN_MIN
        and int(run[0][1]) == 1
        and (not total or run[0][0] >= total * 0.4)
        and (not total or run[-1][0] >= total - 3)
    ):
        candidates.append(run)

    # Heading-led path: the last reference-style heading, then the numbered run under it.
    heading_positions = [
        position
        for position, paragraph in enumerate(paragraphs)
        if paragraph.kind == "heading" and REFERENCE_HEADING_RE.match(paragraph.text.strip())
    ]
    if heading_positions:
        start = heading_positions[-1]
        after = [(position, number) for position, number in numbered if position > start]
        run = _longest_consecutive_run(after)
        if run and (not total or run[-1][0] >= total - 3):
            entry_texts = [paragraphs[position].text for position, _ in run]
            bibliographic = all(_looks_bibliographic(text) for text in entry_texts)
            long_enough = len(run) >= REFERENCE_RUN_MIN_WITH_HEADING
            starts_at_one = int(run[0][1]) == 1
            if starts_at_one and (long_enough or bibliographic):
                candidates.append(run)

    if not candidates:
        return 0
    chosen = max(candidates, key=len)
    for position, _ in chosen:
        paragraphs[position].kind = "reference"
        paragraphs[position].level = 0
    return len(chosen)


def _assemble(
    path: Path,
    fmt: str,
    paragraphs: list,
    warnings: list,
    method: str = "native",
) -> Document:
    references = mark_reference_list(paragraphs)
    if references:
        warnings = warnings + ["%d reference-list entries marked structural" % references]
    cursor = 0
    pieces: list = []
    for paragraph in paragraphs:
        if paragraph.kind == "code":
            continue
        paragraph.char_start = cursor
        paragraph.char_end = cursor + len(paragraph.text)
        pieces.append(paragraph.text)
        cursor = paragraph.char_end + 2  # the "\n\n" join
    text = "\n\n".join(pieces)
    title = ""
    for paragraph in paragraphs:
        if paragraph.kind == "heading" and paragraph.level and paragraph.level <= 2:
            title = paragraph.text
            break
    if not text.strip():
        raise IntakeError("document has no narrative text to grade")
    sentences = _sentences.split_sentences(text)
    return Document(
        path=str(path),
        format=fmt,
        text=text,
        paragraphs=paragraphs,
        sentences=sentences,
        warnings=warnings,
        title=title,
        method=method,
    )


def read_document(path_value) -> Document:
    """Read a supported document into the paragraph + sentence model."""
    path = Path(path_value)
    if not path.exists():
        raise IntakeError("document does not exist: %s" % path)
    if not path.is_file():
        raise IntakeError("document must be a regular file")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise IntakeError(
            "unsupported document extension %s (supported: %s)"
            % (suffix or "<none>", ", ".join(SUPPORTED_SUFFIXES))
        )

    if suffix == ".docx":
        paragraphs, warnings = _docx_paragraphs(path)
        return _assemble(path, "docx", paragraphs, warnings)
    if suffix == ".tex":
        raw = path.read_text(encoding="utf-8", errors="replace")
        paragraphs, warnings = _tex_to_paragraphs(raw)
        return _assemble(path, "tex", paragraphs, warnings)
    if suffix == ".pdf":
        paragraphs, warnings, method = _pdf_paragraphs(path)
        return _assemble(path, "pdf", paragraphs, warnings, method=method)

    raw = path.read_text(encoding="utf-8", errors="replace")
    warnings: list = []
    if suffix in (".md", ".markdown"):
        paragraphs = _plain_paragraphs(raw)
    else:
        paragraphs = _plain_paragraphs(raw)
    return _assemble(path, "text", paragraphs, warnings)


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("usage: _intake.py <document>")
        raise SystemExit(2)
    import json

    document = read_document(sys.argv[1])
    print(json.dumps(document.to_dict(), indent=2))
    for sentence in document.narrative_sentences()[:5]:
        print(" ", sentence.sentence_id, sentence.text[:80])
