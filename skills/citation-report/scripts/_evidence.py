"""A per-source index over extracted evidence, built once and queried per sentence.

Scanning a 600,000-character paper with regular expressions once per sentence would
be unusably slow (a thousand sentences against sixty sources is sixty million
scans). Every source is therefore indexed exactly once:

* ``has_number`` — O(1) membership test for "does this source contain this value",
  keyed on a 6-significant-digit form so float formatting cannot cause a miss.
* ``measures`` — every `HR 0.49` / `OR 1.2` / `RR 0.8` occurrence with its offset,
  which is what makes a contradiction claim quotable and checkable.
* ``snippet`` — the surrounding text of any offset, for the margin note.

The index is deliberately read-only. Nothing here decides a verdict; it only
answers "is this number present, and where".
"""

from __future__ import annotations

from dataclasses import dataclass, field

import _signals


def number_key(value: float) -> str:
    """A stable key for a numeric value, tolerant of formatting and safe against
    float noise."""
    if value == int(value) and abs(value) < 1e15:
        return "i%d" % int(value)
    return "f%.6g" % value


def _keys(value: float) -> list:
    keys = [number_key(value)]
    # A percentage written as `30 %` or `30.0%` must both be found.
    try:
        keys.append("f%.6g" % float(value))
    except (TypeError, ValueError):
        pass
    return keys


@dataclass
class EvidenceIndex:
    source_id: str = ""
    availability: str = "unavailable"
    text: str = ""
    number_keys: set = field(default_factory=set)
    measures: dict = field(default_factory=dict)
    pages: list = field(default_factory=list)
    _page_starts: list = field(default_factory=list)

    @property
    def graded(self) -> bool:
        return self.availability in ("full_text", "abstract") and bool(self.text)

    def has_number(self, value: float) -> bool:
        return any(key in self.number_keys for key in _keys(value))

    def measure_values(self, label: str) -> list:
        """Every `value, offset` recorded for a measure such as HR or OR."""
        normalized = (label or "").upper().replace(" ", "")
        entries = self.measures.get(normalized)
        if entries:
            return entries
        # `aHR` and `HR` are different statistics; do not conflate them silently.
        return []

    def snippet(self, offset: int, width: int = 110) -> str:
        """A quotable window of evidence around an offset, whitespace-collapsed."""
        if not self.text:
            return ""
        begin = max(0, offset - width // 2)
        end = min(len(self.text), offset + width)
        window = self.text[begin:end]
        return " ".join(window.split())

    def build(self) -> "EvidenceIndex":
        if not self.text:
            return self
        self.number_keys = set()
        for value in _signals.evidence_numbers(self.text):
            self.number_keys.update(_keys(value))
        self.measures = {}
        for match in _signals.MEASURE_RE.finditer(self.text):
            value = _signals._to_float(match.group(2))
            if value is None:
                continue
            label = match.group(1).upper().replace(" ", "")
            self.measures.setdefault(label, []).append((value, match.start()))
        return self

    @classmethod
    def from_source(cls, source) -> "EvidenceIndex":
        index = cls(
            source_id=source.source_id,
            availability=source.evidence_availability,
            text=source.evidence_text or "",
            pages=list(source.evidence_pages or []),
        )
        return index.build()


def build_indexes(bundle) -> dict:
    """Index every source in the bundle once. Keyed by `source_id`."""
    return {source.source_id: EvidenceIndex.from_source(source) for source in bundle.sources}
