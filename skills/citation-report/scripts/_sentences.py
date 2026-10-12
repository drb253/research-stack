"""Deterministic sentence segmentation and citation binding.

The whole report rests on one operation being right: cutting a document into
sentences and knowing which citation markers belong to which sentence. A splitter
that cuts mid-sentence produces a report that accuses a half-sentence of being
unsupported; a splitter that merges two sentences attributes one sentence's
sources to another. Both failures are silent, so this module is written to be
explicit about every decision it makes and carries a fixture test with adversarial
cases (abbreviations, initials, decimals, en-dash ranges, statistics, CJK).

No third-party packages. No language model. Same input, same spans, always.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Terminators and trailing characters
# --------------------------------------------------------------------------- #

#: Latin and CJK sentence terminators. Semicolons and colons are deliberately
#: absent: they separate clauses, not sentences.
TERMINATORS = ".!?\u2026\u3002\uff01\uff1f"

#: Characters that may legally follow a terminator and still belong to the same
#: sentence, e.g. `(see above.)` or `"quoted."`.
CLOSERS = "\"')]\u201d\u2019\u00bb\u203a}"

#: CJK terminators need no following whitespace to end a sentence.
CJK_TERMINATORS = "\u3002\uff01\uff1f"

#: Abbreviations whose full stop is not a sentence boundary. Matched
#: case-insensitively against the token immediately preceding the full stop.
ABBREVIATIONS = frozenset(
    {
        # Latin and reference apparatus
        "e.g", "i.e", "cf", "ca", "vs", "v", "al", "etc", "resp", "seq", "ibid",
        "op", "cit", "viz", "approx", "esp", "etal",
        # Titles and names
        "dr", "mr", "mrs", "ms", "prof", "st", "jr", "sr", "rev", "hon", "sir",
        "dame", "fr", "sr", "gen", "col", "lt", "sgt", "capt",
        # Publication apparatus
        "fig", "figs", "eq", "eqs", "tab", "tabs", "ref", "refs", "vol", "vols",
        "no", "nos", "ed", "eds", "p", "pp", "sec", "secs", "ch", "chs", "app",
        "suppl", "supp", "abs", "para", "paras",
        # Units and statistics that habitually sit before a full stop
        "min", "max", "sd", "se", "ci", "or", "hr", "rr", "irr", "iqr", "med",
        "mean", "nr", "ns", "df", "sig",
        # Corporate suffixes
        "inc", "ltd", "co", "corp", "plc", "gmbh",
        # Months, shortened
        "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct",
        "nov", "dec",
    }
)

#: A lone initial, as in `J. Smith` or `R. J. Davies`.
INITIAL_RE = re.compile(r"(?:^|[\s(\[])([A-Za-z])\.$")
TOKEN_BEFORE_RE = re.compile(r"([A-Za-z][A-Za-z.]*)\.$")
WHITESPACE_RE = re.compile(r"\s")


@dataclass
class Marker:
    """One citation marker found in a sentence."""

    kind: str  # numeric | ledger_claim | ledger_source | author_year
    raw: str
    values: list = field(default_factory=list)
    start: int = 0
    end: int = 0

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "raw": self.raw,
            "values": list(self.values),
            "start": self.start,
            "end": self.end,
        }


@dataclass
class Sentence:
    """One sentence with exact character offsets into the normalized text."""

    index: int
    text: str
    char_start: int
    char_end: int
    paragraph: int = 0
    markers: list = field(default_factory=list)

    @property
    def sentence_id(self) -> str:
        return "N%04d" % self.index

    def marker_values(self, kind: str) -> list:
        values: list = []
        for marker in self.markers:
            if marker.kind == kind:
                values.extend(marker.values)
        return values

    def to_dict(self) -> dict:
        return {
            "sentence_id": self.sentence_id,
            "text": self.text,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "paragraph": self.paragraph,
            "markers": [marker.to_dict() for marker in self.markers],
        }


# --------------------------------------------------------------------------- #
# Citation marker grammars
# --------------------------------------------------------------------------- #

NUMERIC_MARKER_RE = re.compile(
    r"\[([0-9]{1,4}(?:\s*[,\u2013\u2014-]\s*[0-9]{1,4})*)\]"
)
#: Parenthetical numeric citations: `(1)`, `(1-4)`, `(1,3,5)`. Deliberately narrow —
#: the parentheses must contain nothing but numbers, separators and spaces, so
#: `(PTSD)`, `(DSO)` and `(ITQ)` are not citations. A four-digit value in the year
#: range is an author-year pointer, not a reference number, and is excluded.
PAREN_NUMERIC_RE = re.compile(
    r"\(([0-9]{1,4}(?:\s*[,\u2013\u2014-]\s*[0-9]{1,4})*)\)"
)
LEDGER_CLAIM_RE = re.compile(r"\[claim:(C[0-9]{3,8})\]")
LEDGER_SOURCE_RE = re.compile(
    r"\[src:(S[0-9]{3,8}(?:\s*[,\u2013\u2014-]\s*S[0-9]{3,8})*)\]"
)
#: Any bracketed token that the specific grammars above did not claim. This is how
#: a citekey-shaped marker (`[7483504]`) or a bracketed DOI reaches the source
#: registry, which is the only component that can decide whether it resolves.
BRACKET_RE = re.compile(r"\[([^\[\]]{1,80})\]")
AUTHOR_YEAR_PAREN_RE = re.compile(
    r"\(([^()]{0,160}?\b(?:1[6-9]|20)[0-9]{2}[a-z]?(?:\s*[,\u2013-]\s*(?:1[6-9]|20)[0-9]{2}[a-z]?)*)\)"
)
AUTHOR_YEAR_INLINE_RE = re.compile(
    r"\b([A-Z][A-Za-z\u2019'\-]+(?:\s+(?:et\s+al\.|and|&)\s+[A-Za-z\u2019'\-]+)?\s*,\s*"
    r"(?:1[6-9]|20)[0-9]{2}[a-z]?)\b"
)
_YEAR_RE = re.compile(r"(?:1[6-9]|20)[0-9]{2}[a-z]?")


def expand_numeric_values(raw: str) -> list:
    """Expand `12,14` and `12-14` / `12\u201314` into individual citation numbers."""
    values: list = []
    for part in re.split(r"[,\u2013\u2014]", raw):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            bounds = [piece.strip() for piece in part.split("-") if piece.strip()]
            if len(bounds) == 2 and all(bound.isdigit() for bound in bounds):
                low, high = int(bounds[0]), int(bounds[1])
                if 0 <= high - low <= 200:
                    values.extend(str(number) for number in range(low, high + 1))
                    continue
        if part.isdigit():
            values.append(part)
    return values


def expand_source_values(raw: str) -> list:
    values: list = []
    for part in re.split(r"[,\u2013\u2014]", raw):
        part = part.strip()
        if re.fullmatch(r"S[0-9]{3,8}", part):
            if "-" in part:
                continue
            values.append(part)
            continue
        match = re.fullmatch(r"(S)([0-9]{3,8})-(S?)([0-9]{3,8})", part)
        if match:
            low, high = int(match.group(2)), int(match.group(4))
            if 0 <= high - low <= 200:
                width = len(match.group(2))
                values.extend("S%0*d" % (width, number) for number in range(low, high + 1))
    return values


def bind_markers(text: str, styles=("numeric", "author-year", "ledger")) -> list:
    """Return every citation marker in `text`, in order of appearance."""
    markers: list = []
    wanted = set(styles)
    if "numeric" in wanted:
        for match in NUMERIC_MARKER_RE.finditer(text):
            # A bracketed run of digits that is part of a ledger marker's payload
            # cannot occur, but guard against `[claim:C001]`-style overlap anyway.
            if LEDGER_SOURCE_RE.match(text, max(0, match.start() - 7)):
                continue
            markers.append(
                Marker(
                    kind="numeric",
                    raw=match.group(0),
                    values=expand_numeric_values(match.group(1)),
                    start=match.start(),
                    end=match.end(),
                )
            )
        for match in PAREN_NUMERIC_RE.finditer(text):
            values = expand_numeric_values(match.group(1))
            # `(2019)` is a year, not reference 2019.
            if not values or all(1600 <= int(value) <= 2099 for value in values):
                continue
            if any(
                existing.start <= match.start() < existing.end for existing in markers
            ):
                continue
            markers.append(
                Marker(
                    kind="numeric",
                    raw=match.group(0),
                    values=values,
                    start=match.start(),
                    end=match.end(),
                )
            )
    if "ledger" in wanted:
        for match in LEDGER_CLAIM_RE.finditer(text):
            markers.append(
                Marker(
                    kind="ledger_claim",
                    raw=match.group(0),
                    values=[match.group(1)],
                    start=match.start(),
                    end=match.end(),
                )
            )
        for match in LEDGER_SOURCE_RE.finditer(text):
            markers.append(
                Marker(
                    kind="ledger_source",
                    raw=match.group(0),
                    values=expand_source_values(match.group(1)),
                    start=match.start(),
                    end=match.end(),
                )
            )
    if "author-year" in wanted:
        for match in AUTHOR_YEAR_PAREN_RE.finditer(text):
            years = _YEAR_RE.findall(match.group(1))
            if years:
                markers.append(
                    Marker(
                        kind="author_year",
                        raw=match.group(0),
                        values=years,
                        start=match.start(),
                        end=match.end(),
                    )
                )
        for match in AUTHOR_YEAR_INLINE_RE.finditer(text):
            if any(
                existing.start <= match.start() < existing.end for existing in markers
            ):
                continue
            years = _YEAR_RE.findall(match.group(1))
            if years:
                markers.append(
                    Marker(
                        kind="author_year",
                        raw=match.group(1),
                        values=years,
                        start=match.start(1),
                        end=match.end(1),
                    )
                )
    # Anything still bracketed becomes an unresolved candidate. Collected last so
    # the typed grammars above keep ownership of the spans they already claim.
    for match in BRACKET_RE.finditer(text):
        if any(
            existing.start <= match.start() < existing.end for existing in markers
        ):
            continue
        payload = match.group(1).strip()
        if not payload:
            continue
        markers.append(
            Marker(
                kind="bracket",
                raw=match.group(0),
                values=[payload],
                start=match.start(),
                end=match.end(),
            )
        )
    markers.sort(key=lambda marker: (marker.start, marker.end))
    return markers


# --------------------------------------------------------------------------- #
# Segmentation
# --------------------------------------------------------------------------- #


def normalize_text(raw: str) -> str:
    """Normalize line endings and collapse runs of spaces without moving offsets
    more than necessary. Tabs become single spaces; CRLF becomes LF."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\t", " ")
    return text


def _is_boundary(text: str, position: int, end_of_run: int) -> bool:
    """Decide whether the terminator run ending at `end_of_run` ends a sentence."""
    terminator = text[position]
    length = len(text)

    if terminator in CJK_TERMINATORS:
        return True

    # A decimal point: a digit on both sides.
    if terminator == "." and position > 0 and position + 1 < length:
        if text[position - 1].isdigit() and text[position + 1].isdigit():
            return False

    following = end_of_run + 1
    # Skip legal trailing closers.
    while following < length and text[following] in CLOSERS:
        following += 1

    if following < length and not WHITESPACE_RE.match(text[following]):
        # A terminator not followed by space is interior (e.g. `3.5`, `U.S.`,
        # a URL, or a file path) unless it is the very end of the text.
        return False

    if terminator == ".":
        before = text[: position + 1]
        token_match = TOKEN_BEFORE_RE.search(before)
        if token_match:
            token = token_match.group(1)
            if token.lower() in ABBREVIATIONS:
                return False
            if "." in token:
                # Any token already carrying a dot is an abbreviation, e.g. `e.g.`
                return False
        if INITIAL_RE.search(before):
            return False
        # A lowercase continuation after a space is almost always an
        # abbreviation or a mid-sentence acronym list, not a new sentence.
        if following < length and text[following].islower():
            return False

    return True


def split_sentences(text: str, *, styles=("numeric", "author-year", "ledger")) -> list:
    """Split normalized text into sentences with exact offsets, then bind markers.

    Paragraph breaks (blank lines) are hard boundaries and are counted so that a
    marker can never be attributed across paragraphs.
    """
    sentences: list = []
    length = len(text)
    start = 0
    paragraph = 0
    index = 0
    position = 0

    def flush(end: int) -> None:
        nonlocal start, index
        raw = text[start:end]
        stripped = raw.strip()
        if stripped:
            offset = start + (len(raw) - len(raw.lstrip()))
            index += 1
            sentences.append(
                Sentence(
                    index=index,
                    text=stripped,
                    char_start=offset,
                    char_end=offset + len(stripped),
                    paragraph=paragraph,
                    markers=bind_markers(stripped, styles),
                )
            )
        start = end

    while position < length:
        char = text[position]
        if char == "\n":
            # Blank line (paragraph break) is a hard boundary.
            probe = position
            while probe < length and text[probe] in " \n":
                probe += 1
            if text[position:probe].count("\n") >= 2:
                flush(position)
                paragraph += 1
                start = probe
                position = probe
                continue
            position += 1
            continue
        if char in TERMINATORS:
            run_end = position
            while run_end + 1 < length and text[run_end + 1] in TERMINATORS:
                run_end += 1
            if _is_boundary(text, position, run_end):
                end = run_end + 1
                while end < length and text[end] in CLOSERS:
                    end += 1
                flush(end)
                position = end
                continue
            position = run_end + 1
            continue
        position += 1

    flush(length)
    return sentences


def segment(text: str, *, styles=("numeric", "author-year", "ledger")) -> list:
    """Normalize then split. The single entry point used by the intake layer."""
    return split_sentences(normalize_text(text), styles=styles)


def strip_markers(text: str, styles=("numeric", "author-year", "ledger")) -> str:
    """Remove citation markers from a sentence, for display and for matching.

    The report shows the sentence as written but matches numbers against evidence
    with markers removed, so a citation number can never be mistaken for a study
    statistic.
    """
    spans = [(marker.start, marker.end) for marker in bind_markers(text, styles)]
    if not spans:
        return text
    pieces: list = []
    cursor = 0
    for begin, end in sorted(spans):
        if begin < cursor:
            continue
        pieces.append(text[cursor:begin])
        cursor = end
    pieces.append(text[cursor:])
    joined = re.sub(r"\s{2,}", " ", "".join(pieces))
    joined = re.sub(r"\s+([,.;:!?\u2026\u3002\uff01\uff1f])", r"\1", joined)
    return joined.strip()
