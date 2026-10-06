"""Parse the manuscript Markdown into a small document model.

The model is deliberately minimal: it is what the DOCX, PDF, and HTML writers need,
and nothing more. Standard library only, offline, deterministic.

Inline emphasis, code, links, and citation brackets are preserved as runs so that
formatting survives into every output format without re-parsing prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
FENCE_RE = re.compile(r"^```\s*([A-Za-z0-9_+-]*)\s*$")
RULE_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
BULLET_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
ORDERED_RE = re.compile(r"^\s*([0-9]{1,3})[.)]\s+(.*)$")
QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
IMAGE_RE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)\s*$")
TABLE_DIVIDER_RE = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")
INLINE_RE = re.compile(
    r"(\*\*[^*]+\*\*|__[^_]+__|\*[^*\n]+\*|_[^_\n]+_|`[^`]+`)"
)
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
CITE_RE = re.compile(r"\[([0-9]{1,4}(?:\s*[,\u2013-]\s*[0-9]{1,4})*)\]")
FOOTNOTE_RE = re.compile(r"^\[([0-9]{1,3})\]:\s*(.*)$")


@dataclass
class Run:
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    link: str = ""


@dataclass
class Block:
    kind: str
    level: int = 0
    runs: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    header: list = field(default_factory=list)
    items: list = field(default_factory=list)
    path: str = ""
    alt: str = ""
    language: str = ""
    label: str = ""

    def plain_text(self) -> str:
        if self.kind in ("heading", "para", "quote", "caption", "list_item"):
            return "".join(run.text for run in self.runs)
        if self.kind == "code":
            return "".join(run.text for run in self.runs)
        if self.kind == "image":
            return self.alt
        return ""


def parse_inline(text: str) -> list:
    runs: list = []
    for piece in INLINE_RE.split(text):
        if not piece:
            continue
        if piece.startswith("**") and piece.endswith("**") and len(piece) > 4:
            runs.append(Run(piece[2:-2], bold=True))
        elif piece.startswith("__") and piece.endswith("__") and len(piece) > 4:
            runs.append(Run(piece[2:-2], bold=True))
        elif piece.startswith("`") and piece.endswith("`") and len(piece) > 2:
            runs.append(Run(piece[1:-1], code=True))
        elif piece.startswith("*") and piece.endswith("*") and len(piece) > 2:
            runs.append(Run(piece[1:-1], italic=True))
        elif piece.startswith("_") and piece.endswith("_") and len(piece) > 2:
            runs.append(Run(piece[1:-1], italic=True))
        else:
            runs.append(Run(piece))
    return _split_links(runs)


def _split_links(runs: list) -> list:
    output: list = []
    for run in runs:
        if run.code or "[" not in run.text:
            output.append(run)
            continue
        position = 0
        for match in LINK_RE.finditer(run.text):
            if match.start() > position:
                output.append(Run(run.text[position : match.start()], run.bold, run.italic))
            output.append(Run(match.group(1), run.bold, run.italic, link=match.group(2)))
            position = match.end()
        if position < len(run.text):
            output.append(Run(run.text[position:], run.bold, run.italic))
    merged: list = []
    for run in output:
        if merged and not run.bold and not run.italic and not run.code and not run.link:
            previous = merged[-1]
            if not previous.bold and not previous.italic and not previous.code and not previous.link:
                merged[-1] = Run(previous.text + run.text)
                continue
        merged.append(run)
    return merged


def _split_table_row(line: str) -> list:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    cells: list = []
    current = ""
    escaped = False
    for char in stripped:
        if escaped:
            current += char
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            cells.append(current.strip())
            current = ""
        else:
            current += char
    cells.append(current.strip())
    return cells



def parse(text: str) -> list:
    blocks: list = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            index += 1
            continue

        fence = FENCE_RE.match(line)
        if fence:
            language = fence.group(1)
            index += 1
            body: list = []
            while index < len(lines) and not FENCE_RE.match(lines[index]):
                body.append(lines[index])
                index += 1
            index += 1
            blocks.append(
                Block(kind="code", language=language, runs=[Run("\n".join(body), code=True)])
            )
            continue

        heading = HEADING_RE.match(line)
        if heading:
            blocks.append(
                Block(
                    kind="heading",
                    level=len(heading.group(1)),
                    runs=parse_inline(heading.group(2).strip()),
                )
            )
            index += 1
            continue

        if RULE_RE.match(line):
            blocks.append(Block(kind="rule"))
            index += 1
            continue

        image = IMAGE_RE.match(stripped)
        if image:
            blocks.append(Block(kind="image", alt=image.group(1), path=image.group(2)))
            index += 1
            continue

        if stripped.startswith("|") and index + 1 < len(lines) and TABLE_DIVIDER_RE.match(
            lines[index + 1]
        ):
            header = _split_table_row(line)
            index += 2
            rows: list = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(_split_table_row(lines[index]))
                index += 1
            caption = ""
            if blocks and blocks[-1].kind == "heading" and re.match(
                r"^(table|figure)\b", blocks[-1].plain_text(), re.IGNORECASE
            ):
                caption = blocks.pop().plain_text()
            blocks.append(Block(kind="table", header=header, rows=rows, label=caption))
            continue

        if QUOTE_RE.match(line):
            body_quote: list = []
            while index < len(lines) and QUOTE_RE.match(lines[index]):
                body_quote.append(QUOTE_RE.match(lines[index]).group(1))
                index += 1
            blocks.append(Block(kind="quote", runs=parse_inline(" ".join(body_quote).strip())))
            continue

        if BULLET_RE.match(line) or ORDERED_RE.match(line):
            items: list = []
            while index < len(lines):
                bullet = BULLET_RE.match(lines[index])
                ordered = ORDERED_RE.match(lines[index])
                if bullet:
                    items.append(("bullet", parse_inline(bullet.group(1).strip())))
                elif ordered:
                    items.append((ordered.group(1), parse_inline(ordered.group(2).strip())))
                else:
                    break
                index += 1
            blocks.append(Block(kind="list", items=items))
            continue

        footnote = FOOTNOTE_RE.match(stripped)
        if footnote:
            blocks.append(
                Block(
                    kind="para",
                    label="footnote",
                    runs=[Run(footnote.group(1) + ". ", bold=True)]
                    + parse_inline(footnote.group(2).strip()),
                )
            )
            index += 1
            continue

        para: list = [line.strip()]
        index += 1
        while index < len(lines):
            candidate = lines[index]
            if not candidate.strip():
                break
            if (
                HEADING_RE.match(candidate)
                or FENCE_RE.match(candidate)
                or RULE_RE.match(candidate)
                or candidate.strip().startswith("|")
                or BULLET_RE.match(candidate)
                or ORDERED_RE.match(candidate)
                or QUOTE_RE.match(candidate)
                or IMAGE_RE.match(candidate.strip())
            ):
                break
            para.append(candidate.strip())
            index += 1
        text_value = " ".join(part for part in para if part)
        if text_value.startswith("**") and text_value.endswith("**") and ":" not in text_value[:40]:
            blocks.append(Block(kind="caption", runs=parse_inline(text_value[2:-2])))
        else:
            blocks.append(Block(kind="para", runs=parse_inline(text_value)))
    return blocks


def summarise(blocks: list) -> dict:
    counts: dict = {}
    for block in blocks:
        counts[block.kind] = counts.get(block.kind, 0) + 1
    words = sum(len(block.plain_text().split()) for block in blocks if block.kind != "code")
    return {"blocks": len(blocks), "words": words, "by_kind": counts}
