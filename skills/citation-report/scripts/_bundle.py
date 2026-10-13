"""Build the source registry: what the document cites, and what evidence we hold.

The report can only be as strong as this step. Three questions are answered per
source, and each answer is recorded rather than assumed:

1. **What is it?** A DOI, and metadata resolved from Crossref/OpenAlex, or the
   document's own reference-list text when no DOI is available.
2. **Can it be trusted?** ``verification_status`` and ``retraction_status``.
3. **What evidence do we actually hold?** ``evidence_availability`` — ``full_text``
   from a supplied PDF, ``abstract`` from Europe PMC, ``metadata_only``, or
   ``unavailable``. Anything weaker than full text is disclosed in every note that
   relies on it, and a source with no evidence can never make a sentence green.

Sources are linked from whatever the user has, in this order of preference:

* a BibTeX file, whose ``file = {...}`` field is the author's own upload manifest
  and therefore the strongest link to a supplied PDF;
* a directory of PDFs, with DOIs mined from page 1 when filenames are opaque;
* the document's own numbered reference list (each entry's DOI is read out of it);
* a ``sources.csv`` produced by this repository's review skills;
* a plain list of DOIs or PMIDs.

No network call is made when ``offline=True``. In that mode every source is graded
on local evidence alone, which is the reproducible mode used by the test suite.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import _common
import _pdftext

DOI_IN_TEXT_RE = re.compile(r"\b(10\.[0-9]{4,9}/\S+)", re.IGNORECASE)
PMID_IN_TEXT_RE = re.compile(r"\bPMID:?\s*([0-9]{6,9})\b", re.IGNORECASE)
YEAR_IN_TEXT_RE = re.compile(r"\b(1[89][0-9]{2}|20[0-9]{2})\b")
FILENAME_DOI_RE = re.compile(r"(10\.[0-9]{4,9}[._-][^\s/]+)", re.IGNORECASE)

MAX_EVIDENCE_CHARS = 600_000

#: Seconds between DOI resolutions. Sixty lookups in a burst earns an HTTP 503 from
#: Europe PMC, and a 503 that is recorded as "no evidence" sends a user looking for
#: files they may not need to find.
RESOLUTION_PACING_SECONDS = 0.35


def _timestamp() -> str:
    """UTC timestamp for an acquisition record. Never used for anything else, so it
    cannot make two otherwise-identical runs differ in their verdicts."""
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def clean_doi_candidate(raw: str) -> str:
    """Trim punctuation around a DOI without breaking balanced parentheses.

    Publisher DOIs legitimately contain parentheses — `10.1016/s2215-0366(22)00375-3`
    is a real Lancet Psychiatry DOI — so a naive trailing-`)` strip truncates them
    and silently resolves citation [1] against the wrong paper.
    """
    candidate = (raw or "").strip()
    while candidate:
        last = candidate[-1]
        if last in ".,;:'\"<>":
            candidate = candidate[:-1]
            continue
        if last == ")" and candidate.count("(") < candidate.count(")"):
            candidate = candidate[:-1]
            continue
        if last == "]" and candidate.count("[") < candidate.count("]"):
            candidate = candidate[:-1]
            continue
        break
    return candidate


def mine_doi(text: str) -> str:
    """First plausible DOI in a block of text, trailing punctuation removed."""
    for match in DOI_IN_TEXT_RE.finditer(text or ""):
        candidate = clean_doi_candidate(match.group(1))
        if _common.valid_doi(candidate):
            return _common.normalize_doi(candidate)
    return ""


# --------------------------------------------------------------------------- #
# Reference list parsing
# --------------------------------------------------------------------------- #


@dataclass
class ReferenceEntry:
    number: str
    text: str
    doi: str = ""
    year: str = ""
    pmid: str = ""

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "text": self.text[:400],
            "doi": self.doi,
            "year": self.year,
        }


def parse_reference_list(paragraphs) -> list:
    """Read the document's own reference list, which intake has already marked.

    Intake decides *whether* a trailing numbered run is a bibliography (it needs the
    whole-document view to tell a bibliography from a body list); this function only
    reads the entries and mines an identifier from each. Keeping the decision in one
    place means the report and the exclusion that keeps reference entries out of the
    graded prose can never disagree.

    The entry number comes from `_intake.reference_number`, which also understands a
    Markdown ordered list whose marker the reader stripped from the text. Without
    that, a numeric citation cannot be mapped to its entry in a Markdown document.
    """
    import _intake

    entries: list = []
    for paragraph in paragraphs:
        if getattr(paragraph, "kind", "") != "reference":
            continue
        number = _intake.reference_number(paragraph)
        if not number:
            continue
        body = _intake.reference_body(paragraph)
        entries.append(
            ReferenceEntry(
                number=number,
                text=body,
                doi=mine_doi(paragraph.text),
                year=(YEAR_IN_TEXT_RE.search(paragraph.text).group(1)
                      if YEAR_IN_TEXT_RE.search(paragraph.text) else ""),
                pmid=(PMID_IN_TEXT_RE.search(paragraph.text).group(1)
                      if PMID_IN_TEXT_RE.search(paragraph.text) else ""),
            )
        )
    return entries


# --------------------------------------------------------------------------- #
# BibTeX parsing
# --------------------------------------------------------------------------- #


@dataclass
class BibEntry:
    key: str
    type: str
    fields: dict = field(default_factory=dict)

    @property
    def doi(self) -> str:
        return _common.normalize_doi(re.sub(r"^https?://(dx\.)?doi\.org/", "", self.fields.get("doi", "")))

    @property
    def title(self) -> str:
        return _clean_tex_value(self.fields.get("title", ""))

    @property
    def files(self) -> list:
        raw = self.fields.get("file", "")
        if not raw:
            return []
        names: list = []
        for chunk in raw.split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            # Zotero writes `description:path:format`; keep the path component.
            parts = chunk.split(":")
            candidate = parts[-2] if len(parts) >= 3 else parts[-1]
            candidate = candidate.strip().strip("{}")
            if candidate:
                names.append(candidate)
        return names


def _clean_tex_value(value: str) -> str:
    text = re.sub(r"[{}]", "", value or "")
    text = re.sub(r"\\[a-zA-Z]+\s*", "", text)
    return re.sub(r"\s{2,}", " ", text.replace("~", " ")).strip()


def _split_bib_fields(body: str) -> list:
    """Split an entry body on top-level commas, respecting braces and quotes."""
    fields: list = []
    depth = 0
    in_quote = False
    current: list = []
    position = 0
    while position < len(body):
        char = body[position]
        if char == "\\":
            current.append(body[position : position + 2])
            position += 2
            continue
        if char == '"' and depth == 0:
            in_quote = not in_quote
        elif not in_quote:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            elif char == "," and depth == 0:
                fields.append("".join(current))
                current = []
                position += 1
                continue
        current.append(char)
        position += 1
    if current:
        fields.append("".join(current))
    return fields


def parse_bibtex(text: str) -> list:
    """Minimal but brace-correct BibTeX reader. Returns entries in file order."""
    entries: list = []
    position = 0
    length = len(text)
    while position < length:
        at = text.find("@", position)
        if at < 0:
            break
        header = re.match(r"@([A-Za-z]+)\s*[{(]\s*([^,\s}]+)\s*,", text[at:])
        if not header:
            position = at + 1
            continue
        entry_type = header.group(1).lower()
        key = header.group(2)
        body_start = at + header.end()
        depth = 1
        cursor = body_start
        while cursor < length and depth > 0:
            char = text[cursor]
            if char == "\\":
                cursor += 2
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    break
            cursor += 1
        body = text[body_start:cursor]
        fields: dict = {}
        for chunk in _split_bib_fields(body):
            if "=" not in chunk:
                continue
            name, _, value = chunk.partition("=")
            name = name.strip().lower()
            value = value.strip().rstrip(",").strip()
            if value.startswith("{") and value.endswith("}"):
                value = value[1:-1]
            elif value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            fields[name] = value
        if entry_type in ("comment", "preamble", "string"):
            position = cursor + 1
            continue
        entries.append(BibEntry(key=key, type=entry_type, fields=fields))
        position = cursor + 1
    return entries


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #


@dataclass
class Source:
    source_id: str
    citekey: str = ""
    citation_number: str = ""
    doi: str = ""
    pmid: str = ""
    title: str = ""
    authors: list = field(default_factory=list)
    year: str = ""
    container: str = ""
    resolution: str = ""
    verification_status: str = "unverified"
    retraction_status: str = "not_checked"
    retraction_notes: list = field(default_factory=list)
    evidence_availability: str = "unavailable"
    evidence_text: str = ""
    evidence_pages: list = field(default_factory=list)
    evidence_method: str = ""
    evidence_locator: str = ""
    file_path: str = ""
    title_claimed: str = ""
    title_match: str = "not_checked"
    link_method: str = ""
    warnings: list = field(default_factory=list)
    # -- provenance. Every field here exists so that a verdict can be traced back to a
    #    specific acquisition attempt. A source with evidence text and an empty
    #    `evidence_origin` is a gate error: evidence may never appear without a record
    #    of where it came from.
    evidence_strength: str = "none"
    evidence_origin: str = ""
    acquisition_method: str = "none"
    acquisition_endpoint: str = ""
    identity_check: str = "not_attempted"
    #: Section ranges for evidence that has no pages (open-access XML). Set by
    #: `_acquire` as a dynamic attribute; declared here so it is part of the model,
    #: serialised, and available to the renderers like any other field.
    evidence_sections: list = field(default_factory=list)
    acquired_at: str = ""
    #: Uses the vocabulary the repository already uses for "we tried, and this is what
    #: happened", so a failed attempt is recorded rather than looking like an absent
    #: source.
    retrieval_status: str = "not_attempted"
    attempts: list = field(default_factory=list)
    #: True when `evidence_text` was transcribed by OCR rather than read from a text
    #: layer. A transcription is a machine's reading: it can support what a sentence
    #: *says*, but it can never support an accusation, because a misread digit would make
    #: the tool accuse an author of contradicting a source using the tool's own error.
    transcribed: bool = False
    #: What produced the transcription, e.g. `tesseract:eng`. Empty when not transcribed.
    transcription: str = ""

    @property
    def citable(self) -> bool:
        """True only when the source is real, not retracted, and has evidence."""
        return (
            self.verification_status == "verified"
            and self.retraction_status != "retracted"
            and self.evidence_availability in ("full_text", "abstract")
        )

    @property
    def checkable(self) -> bool:
        """True when the evidence is strong enough to test a sentence's numbers."""
        return self.evidence_strength in _common.CHECKABLE_STRENGTH

    @property
    def red_capable(self) -> bool:
        """True when the evidence may support an accusation. See `_common`.

        Transcribed evidence never is, whatever its strength: the second bar for a red
        finding is that a human wrote the number down and we read it, and OCR breaks the
        second half of that.
        """
        return (
            self.evidence_strength in _common.RED_CAPABLE_STRENGTH
            and not self.transcribed
        )

    @property
    def link_verified(self) -> bool:
        """True when this source's identity was confirmed rather than guessed.

        A user-supplied file is its own declaration; a ledger or DOI link was checked
        against an authority. A title or year match is a guess about which work this
        is, and a guess may not support a red finding.
        """
        if self.link_method in _common.VERIFIED_LINK_METHODS:
            return True
        return bool(
            self.verification_status == "verified"
            and (self.doi or self.pmid)
            and self.link_method != "unlinked"
        )

    def record_attempt(self, method: str, endpoint: str, status: str, detail: str = "") -> None:
        """Append one acquisition attempt, successful or not."""
        self.attempts.append(
            {
                "method": method,
                "endpoint": endpoint[:300],
                "retrieval_status": status,
                "detail": detail[:300],
                "acquired_at": _timestamp(),
            }
        )
        self.retrieval_status = status

    def page_of(self, offset: int) -> int:
        if not self.evidence_pages:
            return 1
        cursor = 0
        for number, page in enumerate(self.evidence_pages, start=1):
            cursor += len(page) + 1
            if offset < cursor:
                return number
        return len(self.evidence_pages)

    def locator(self, offset: int = -1) -> str:
        """A locator a reader can act on: a page, a section, or the word `abstract`.

        Open-access full text arrives as sectioned XML with no pages, so a page locator
        is impossible and a section name is used instead. That is what makes a note from
        acquired full text checkable rather than merely plausible.
        """
        if self.evidence_availability == "abstract":
            return "abstract"
        if self.evidence_pages:
            if offset < 0:
                return "p.1"
            return "p.%d" % self.page_of(offset)
        if self.evidence_sections:
            # Imported lazily: `_acquire` imports this module, so a module-level import
            # here would be circular.
            import _acquire

            return _acquire.section_locator(self, offset)
        return self.evidence_locator or "no locator"

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "citekey": self.citekey,
            "citation_number": self.citation_number,
            "doi": self.doi,
            "pmid": self.pmid,
            "title": self.title or self.title_claimed,
            "year": self.year,
            "container": self.container,
            "resolution": self.resolution,
            "verification_status": self.verification_status,
            "retraction_status": self.retraction_status,
            "retraction_notes": list(self.retraction_notes),
            "evidence_availability": self.evidence_availability,
            "evidence_method": self.evidence_method,
            "evidence_chars": len(self.evidence_text),
            "evidence_locator": self.evidence_locator,
            "file_path": self.file_path,
            "title_claimed": self.title_claimed,
            "title_match": self.title_match,
            "link_method": self.link_method,
            "evidence_strength": self.evidence_strength,
            "evidence_origin": self.evidence_origin,
            "acquisition_method": self.acquisition_method,
            "acquisition_endpoint": self.acquisition_endpoint,
            "identity_check": self.identity_check,
            "acquired_at": self.acquired_at,
            "evidence_sections": [
                {"title": section.get("title", ""), "start": section.get("start", 0),
                 "end": section.get("end", 0)}
                for section in self.evidence_sections
            ],
            "retrieval_status": self.retrieval_status,
            "attempts": list(self.attempts),
            "transcribed": self.transcribed,
            "transcription": self.transcription,
            "warnings": list(self.warnings),
        }


class SourceBundle:
    """The registry, with lookups that a citation marker can be resolved against."""

    def __init__(self) -> None:
        self.sources: list = []
        self.reference_entries: list = []
        self.claims: dict = {}
        self.warnings: list = []
        self.offline = False
        self._by_number: dict = {}
        self._by_citekey: dict = {}
        self._by_doi: dict = {}
        self._by_id: dict = {}

    # -- indexing ---------------------------------------------------------- #

    def _index(self) -> None:
        self._by_number = {}
        self._by_citekey = {}
        self._by_doi = {}
        self._by_id = {}
        for source in self.sources:
            if source.citation_number:
                self._by_number.setdefault(source.citation_number, source)
            if source.citekey:
                self._by_citekey.setdefault(source.citekey, source)
            if source.doi:
                self._by_doi.setdefault(source.doi, source)
            self._by_id[source.source_id] = source

    def lookup(self, token: str) -> Source | None:
        """Resolve one citation token: a number, citekey, DOI, PMID or `S` id."""
        token = (token or "").strip()
        if not token:
            return None
        for table, key in (
            (self._by_number, token),
            (self._by_citekey, token),
            (self._by_id, token.upper()),
            (self._by_doi, _common.normalize_doi(token)),
        ):
            if key in table:
                return table[key]
        if _common.valid_doi(token):
            return self._by_doi.get(_common.normalize_doi(token))
        if _common.valid_pmid(token):
            for source in self.sources:
                if source.pmid == token:
                    return source
        # A numeric marker may be zero-padded or carry a letter suffix.
        digits = re.fullmatch(r"\[?([0-9]{1,4})[a-z]?\]?", token)
        if digits and digits.group(1) in self._by_number:
            return self._by_number[digits.group(1)]
        return None

    @property
    def citation_numbers(self) -> set:
        return set(self._by_number)

    def counts_by_evidence(self) -> dict:
        counts: dict = {}
        for source in self.sources:
            counts[source.evidence_availability] = counts.get(source.evidence_availability, 0) + 1
        return counts

    def counts_by_retraction(self) -> dict:
        counts: dict = {}
        for source in self.sources:
            counts[source.retraction_status] = counts.get(source.retraction_status, 0) + 1
        return counts

    def to_dict(self) -> dict:
        return {
            "sources": [source.to_dict() for source in self.sources],
            "reference_entries": len(self.reference_entries),
            "claims": len(self.claims),
            "offline": self.offline,
            "evidence": self.counts_by_evidence(),
            "retraction": self.counts_by_retraction(),
            "warnings": list(self.warnings),
        }

    def write_csv(self, path) -> Path:
        columns = [
            "source_id", "citekey", "citation_number", "doi", "pmid", "title", "year",
            "container", "resolution", "verification_status", "retraction_status",
            "evidence_availability", "evidence_method", "evidence_chars",
            "evidence_locator", "file_path", "title_claimed", "title_match", "warnings",
        ]
        import csv
        import io

        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for source in self.sources:
            row = source.to_dict()
            row["warnings"] = "; ".join(source.warnings)
            row["title"] = (row.get("title") or "")[:300]
            row["title_claimed"] = (row.get("title_claimed") or "")[:300]
            writer.writerow(row)
        return _common.write_text_lf(path, buffer.getvalue())


# --------------------------------------------------------------------------- #
# Loading each input kind
# --------------------------------------------------------------------------- #


def _next_source_id(bundle: SourceBundle) -> str:
    return "S%03d" % (len(bundle.sources) + 1)


def load_ledger(bundle: SourceBundle, path) -> None:
    """Load a `sources.csv` produced by this repository's review skills."""
    fields, rows = _common.read_csv(path)
    required = {"source_id", "title", "verification_status", "retraction_status"}
    missing = required - set(fields)
    if missing:
        raise _common.InputError(
            "sources.csv is missing required columns: " + ", ".join(sorted(missing))
        )
    for row in rows:
        source = Source(
            source_id=row["source_id"].strip() or _next_source_id(bundle),
            citekey=row.get("source_id", "").strip(),
            doi=_common.normalize_doi(row.get("doi", "")),
            pmid=(row.get("pmid", "") or "").strip(),
            title=row.get("title", "").strip(),
            authors=[part.strip() for part in row.get("authors", "").split(",") if part.strip()],
            year=(row.get("year", "") or "").strip(),
            container=(row.get("container", "") or "").strip(),
            resolution="ledger",
            verification_status=(row.get("verification_status") or "unverified").strip(),
            retraction_status=(row.get("retraction_status") or "not_checked").strip(),
            evidence_locator=(row.get("locator") or "").strip(),
        )
        # The ledger's recorded extraction is evidence of what the source says, but
        # not all of it is equally strong, and the difference decides what a verdict
        # is allowed to claim.
        #
        # `effect_estimate`, `n_participants` and `follow_up` are values the ledger
        # copies verbatim from the source, so they are machine-comparable and may
        # support a red finding. `main_finding` is the extractor's own sentence and
        # `key_outcomes` is a list of outcome names: useful, but a human's words, so
        # they may support a green claim and never an accusation.
        # `population`/`intervention`/`comparator` describe who was studied, not what
        # was found, so a row with only those is metadata rather than evidence.
        #
        # `not_reported` and `not_applicable` are placeholders, not findings, so they
        # must not become evidence either: doing so would convert "we did not extract
        # this" into "we checked this".
        def _usable(value: str) -> bool:
            text = (value or "").strip()
            if not text or _common.is_absent(text):
                return False
            return not text.lower().startswith("not_reported")

        recorded_fields = [
            ("effect_estimate", row.get("effect_estimate", "")),
            ("n_participants", row.get("n_participants", "")),
            ("follow_up", row.get("follow_up", "")),
        ]
        summary_fields = [
            ("main_finding", row.get("main_finding", "")),
            ("key_outcomes", row.get("key_outcomes", "")),
        ]
        context_fields = [
            ("population", row.get("population", "")),
            ("intervention", row.get("intervention", "")),
            ("comparator", row.get("comparator", "")),
        ]
        recorded_used = [(name, value) for name, value in recorded_fields if _usable(value)]
        summary_used = [(name, value) for name, value in summary_fields if _usable(value)]
        context_used = [(name, value) for name, value in context_fields if _usable(value)]

        result_evidence = " ".join(
            value for _, value in recorded_used + summary_used
        ).strip()
        context_evidence = " ".join(value for _, value in context_used).strip()
        combined = " ".join(part for part in (result_evidence, context_evidence) if part).strip()

        if recorded_used or summary_used:
            source.evidence_availability = "full_text"
            source.evidence_text = combined
            source.evidence_method = "ledger"
            source.evidence_locator = source.evidence_locator or "ledger record"
            # The strongest field present decides the strength; the origin names every
            # field that contributed, so a reader can see exactly what was compared.
            if recorded_used:
                source.evidence_strength = "recorded_estimate"
            else:
                source.evidence_strength = "prose_summary"
            source.evidence_origin = "ledger:" + "+".join(
                name for name, _ in recorded_used + summary_used
            )
            source.acquisition_method = "ledger"
            source.acquisition_endpoint = "sources.csv"
            source.identity_check = "declared"
            source.retrieval_status = "user_supplied"
            if not recorded_used:
                source.warnings.append(
                    "ledger records no verbatim value (effect_estimate/n_participants/"
                    "follow_up), only the extractor's own words, so this source can "
                    "support a green claim but never a red finding"
                )
        elif context_used:
            # Kept for the record and shown in the sources table, but NOT gradeable: a
            # study description cannot support a result claim.
            source.evidence_text = combined
            source.evidence_method = "ledger-context-only"
            source.evidence_availability = "metadata_only"
            source.evidence_strength = "none"
            source.evidence_origin = "ledger:context-only"
            source.acquisition_method = "ledger"
            source.acquisition_endpoint = "sources.csv"
            source.retrieval_status = "user_supplied"
            source.warnings.append(
                "ledger row has no extracted finding (main_finding/effect_estimate/"
                "key_outcomes are placeholders), so it is treated as metadata; "
                "sentences citing it are unverifiable rather than green"
            )
        bundle.sources.append(source)
    bundle.warnings.append("loaded %d source(s) from the ledger" % len(rows))


def load_claims(bundle: SourceBundle, path) -> None:
    """Load a `claims.csv` claim ledger, so `[claim:C001]` resolves to its sources.

    This is what makes a manuscript drafted by this repository's review skills a
    first-class input: the claim's own recorded `source_ids` are the citations, and
    a claim naming a source the ledger does not contain is recorded as a finding
    rather than dropped.
    """
    fields, rows = _common.read_csv(path)
    required = {"claim_id", "source_ids"}
    missing = required - set(fields)
    if missing:
        raise _common.InputError(
            "claims.csv is missing required columns: " + ", ".join(sorted(missing))
        )
    for row in rows:
        claim_id = row["claim_id"].strip()
        if not _common.CLAIM_ID_RE.match(claim_id):
            raise _common.InputError("claims.csv has an invalid claim_id: %r" % claim_id)
        bundle.claims[claim_id] = {
            "claim_id": claim_id,
            "source_ids": _common.split_ids(row.get("source_ids", "")),
            "claim_summary": row.get("claim_summary", ""),
            "direction": row.get("direction", ""),
            "certainty": row.get("certainty", ""),
            "verification_status": row.get("verification_status", ""),
            "section": row.get("section", ""),
        }
    bundle.warnings.append("loaded %d claim(s) from the claim ledger" % len(rows))


def load_bib(bundle: SourceBundle, path) -> list:
    text = _common.read_text(path, {".bib", ".bibtex", ".txt"})
    entries = parse_bibtex(text)
    if not entries:
        raise _common.InputError("no BibTeX entries found in " + str(path))
    bundle.warnings.append("parsed %d BibTeX entr(ies)" % len(entries))
    return entries


def load_dois(bundle: SourceBundle, path) -> list:
    text = _common.read_text(path, {".txt", ".csv", ".list", ".dois"})
    dois: list = []
    for token in re.split(r"[\s,;]+", text):
        token = token.strip()
        if not token or token.startswith("#"):
            continue
        if _common.valid_doi(token):
            dois.append(_common.normalize_doi(token))
        elif _common.valid_pmid(token):
            dois.append("PMID:" + token)
    if not dois:
        raise _common.InputError("no DOI or PMID found in " + str(path))
    return dois


def scan_pdf_dir(path) -> list:
    """Find source candidates in a directory: PDFs, and `.txt` sidecars."""
    root = Path(path)
    if not root.is_dir():
        raise _common.InputError("pdf directory does not exist: %s" % root)
    found: list = []
    for candidate in sorted(root.rglob("*")):
        if not candidate.is_file() or candidate.is_symlink():
            continue
        if candidate.suffix.lower() == ".pdf":
            found.append(candidate)
        elif candidate.suffix.lower() in (".txt", ".md"):
            found.append(candidate)
    if not found:
        raise _common.InputError("no PDF or text files found under %s" % root)
    return found


# --------------------------------------------------------------------------- #
# Evidence attachment
# --------------------------------------------------------------------------- #


def _read_sidecar(path: Path) -> tuple:
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[:MAX_EVIDENCE_CHARS], [], "text"


def _can_upgrade(source: Source) -> bool:
    """True when a supplied file would improve this source's evidence.

    Keyed on strength, not on whether text happens to exist. A ledger row with only
    `population`/`intervention` holds context text at strength `none`, and an earlier
    revision refused to attach a supplied PDF to it because `evidence_text` was already
    non-empty -- so the worklist could never close for exactly the sources it named.
    """
    return source.evidence_strength != "primary"


def attach_local_evidence(source: Source, path: Path) -> bool:
    """Attach a local file as full-text evidence. Returns True on success.

    A supplied file is its own identity declaration: the user is asserting that this
    file is this source. That is why it counts as a verified link, and why the
    provenance records the exact path rather than only the extraction method.
    """
    source.file_path = str(path)
    # A source whose ledger row carried no finding was flagged as metadata; once its
    # own text is here, that warning describes a state we are no longer in.
    source.warnings = [
        warning
        for warning in source.warnings
        if "no extracted finding" not in warning
    ]
    if path.suffix.lower() != ".pdf":
        text, pages, method = _read_sidecar(path)
        if not text.strip():
            source.warnings.append("local file is empty: %s" % path.name)
            source.record_attempt("file", str(path), "empty", "file contained no text")
            return False
        source.evidence_text = text
        source.evidence_pages = pages
        source.evidence_method = method
        source.evidence_availability = "full_text"
        source.evidence_strength = "primary"
        source.evidence_origin = "file:" + path.name
        source.acquisition_method = "supplied-file"
        source.acquisition_endpoint = str(path)
        source.identity_check = "user_supplied"
        source.acquired_at = _timestamp()
        source.record_attempt("file", str(path), "user_supplied", "text sidecar")
        source.evidence_locator = "p.1"
        return True
    extracted = _pdftext.extract_pdf(path)
    if not extracted.available:
        source.warnings.append(
            "supplied PDF could not be read (%s): %s" % (path.name, extracted.error)
        )
        source.record_attempt("pdf", str(path), "unavailable", extracted.error)
        return False
    source.evidence_text = extracted.text[:MAX_EVIDENCE_CHARS]
    source.evidence_pages = extracted.pages
    source.evidence_method = extracted.method
    source.evidence_availability = "full_text"
    source.evidence_strength = "primary"
    # A transcribed source says so in its origin, and `red_capable` refuses it. Both are
    # needed: the origin is what a reader sees, the flag is what the engine obeys.
    if getattr(extracted, "transcribed", False):
        source.transcribed = True
        source.transcription = getattr(extracted, "transcription", "") or "ocr"
        source.evidence_origin = "ocr:%s:%s" % (path.name, source.transcription)
        source.warnings.append(
            "evidence for %s came from OCR (%s): a transcription, so a value that appears "
            "to contradict the sentence is reported as unverifiable rather than as a "
            "finding" % (source.source_id, source.transcription)
        )
    else:
        source.evidence_origin = "file:" + path.name
    source.acquisition_method = "supplied-pdf"
    source.acquisition_endpoint = str(path)
    source.identity_check = "user_supplied"
    source.acquired_at = _timestamp()
    source.record_attempt("pdf", str(path), "user_supplied", extracted.method)
    source.evidence_locator = "p.1"
    return True


def match_file_to_source(path: Path, bundle, claimed: set):
    """Match an unclaimed supplied file to a source, by the conventions a user uses.

    The worklist tells a user to "drop the source file into --pdf-dir, named as the DOI
    or the title". This function honours that instruction. Without it the loop cannot
    close: a file named `10.9999_demo.review.2021.pdf`, or `S003.txt`, or
    `First-line lipid-lowering strategies.pdf`, would sit in the folder unread while the
    worklist kept reporting the gap.

    Order matters: an explicit identifier in the name is a declaration, while a title
    fragment is a guess. Returns `(source, method)` or `(None, "")`.
    """
    name = path.name
    normalized = _common.normalize_doi(name)
    stem = path.stem

    # A DOI-shaped name, with the separators a filesystem forces on us put back.
    for candidate in (normalized, _common.normalize_doi(stem), _common.normalize_doi(re.sub(r"[_\s]", "/", stem))):
        if _common.valid_doi(candidate):
            source = bundle.lookup(candidate)
            if source is not None and source.source_id not in claimed:
                return source, "filename-doi"

    # A source id or citekey in the name, e.g. `S003.txt` or `7483504.pdf`.
    for token in re.split(r"[^A-Za-z0-9]+", stem):
        if not token:
            continue
        source = bundle.lookup(token)
        if source is not None and source.source_id not in claimed:
            return source, "filename-id"

    # A title fragment, longest match wins.
    normalized_stem = _common.normalize_title(stem)
    if len(normalized_stem) >= 20:
        best = None
        best_score = 0.0
        for source in bundle.sources:
            if source.source_id in claimed:
                continue
            candidate = _common.normalize_title(source.title or source.title_claimed)
            if len(candidate) < 20:
                continue
            words = candidate.split()
            probe = " ".join(words[:8])
            if probe and probe in normalized_stem:
                score = len(probe) / max(1, len(normalized_stem))
                if score > best_score:
                    best, best_score = source, score
            else:
                overlap = len(set(words) & set(normalized_stem.split())) / len(set(words))
                if overlap >= 0.8 and overlap > best_score:
                    best, best_score = source, overlap
        if best is not None:
            return best, "filename-title"
    return None, ""


def _mine_text_doi(path: Path) -> str:
    """DOI from a text sidecar. Cheap enough to read whole, unlike a PDF."""
    try:
        return mine_doi(path.read_text(encoding="utf-8", errors="replace")[:200_000])
    except OSError:
        return ""


def _candidate_pdfs(files: list) -> list:
    return [path for path in files if path.suffix.lower() == ".pdf"]


def match_file(name: str, files: list):
    """Find a supplied file by exact basename, then by stem, then by containment."""
    if not name:
        return None
    target = Path(name).name.lower()
    target_stem = Path(name).stem.lower()
    for path in files:
        if path.name.lower() == target:
            return path
    for path in files:
        if path.stem.lower() == target_stem:
            return path
    for path in files:
        if target_stem and (target_stem in path.stem.lower() or path.stem.lower() in target_stem):
            return path
    return None


def build_bundle(
    *,
    document=None,
    bib_path=None,
    pdf_dir=None,
    ledger_path=None,
    claims_path=None,
    doi_path=None,
    offline: bool = False,
    mailto: str = "",
    resolve_metadata: bool = True,
    acquire=("api", "pdf", "cli"),
    cache_dir=None,
) -> SourceBundle:
    """Assemble the registry from every input the user supplied."""
    bundle = SourceBundle()
    bundle.offline = offline
    files = scan_pdf_dir(pdf_dir) if pdf_dir else []
    bib_entries = load_bib(bundle, bib_path) if bib_path else []
    doi_tokens = load_dois(bundle, doi_path) if doi_path else []

    if document is not None:
        bundle.reference_entries = parse_reference_list(document.paragraphs)
        if bundle.reference_entries:
            bundle.warnings.append(
                "found a %d-entry numbered reference list in the document"
                % len(bundle.reference_entries)
            )

    number_to_source: dict = {}

    # 1. Ledger sources keep their own identifiers and are already verified. The
    #    claim ledger is loaded after the sources so a claim naming an unknown
    #    source can be reported against a known set.
    if ledger_path:
        load_ledger(bundle, ledger_path)
    if claims_path:
        load_claims(bundle, claims_path)

    # 2. BibTeX entries become sources, carrying their `file` manifest.
    declared_files: dict = {}
    for entry in bib_entries:
        source = Source(
            source_id=_next_source_id(bundle),
            citekey=entry.key,
            doi=entry.doi,
            title=entry.title,
            authors=[part.strip() for part in re.split(r"\s+and\s+", entry.fields.get("author", "")) if part.strip()],
            year=_clean_tex_value(entry.fields.get("year", "") or entry.fields.get("date", ""))[:4],
            container=_clean_tex_value(
                entry.fields.get("journal", "")
                or entry.fields.get("journaltitle", "")
                or entry.fields.get("booktitle", "")
            ),
            resolution="bib",
        )
        for name in entry.files:
            declared_files.setdefault(source.source_id, []).append(name)
        bundle.sources.append(source)

    # 3. Reference-list entries carry the citation numbers the prose actually uses.
    #    Match each entry to a bib source by CONTENT, never by position: a BibTeX
    #    file is commonly ordered by citekey while the reference list is ordered
    #    alphabetically, so positional matching silently attributes citation [1] to
    #    the wrong paper. DOI first, then title, then first author + year.
    claimed_ids: set = set()
    for reference in bundle.reference_entries:
        target = None
        link_method = ""

        if reference.doi:
            for source in bundle.sources:
                if source.source_id in claimed_ids or not source.doi:
                    continue
                if source.doi == reference.doi:
                    target, link_method = source, "doi"
                    break

        if target is None:
            normalized_reference = _common.normalize_title(reference.text)
            reference_words = set(normalized_reference.split())
            best_score = 0.0
            for source in bundle.sources:
                if source.source_id in claimed_ids:
                    continue
                candidate = source.title or source.title_claimed
                if not candidate or source.resolution == "reference-list":
                    continue
                words = _common.normalize_title(candidate).split()
                # A title is discriminating if it has at least three content words.
                # Requiring five, as an earlier revision did, silently refused to match
                # short titles like "Statin therapy trial", creating a second,
                # evidence-less source for the same work -- so the citation resolved to
                # a source with no evidence and the sentence became unverifiable instead
                # of being checked.
                if len(words) < 3:
                    continue
                probe = " ".join(words[:8])
                if probe and probe in normalized_reference:
                    score = 0.9 + len(probe) / max(1, len(normalized_reference))
                    if score > best_score:
                        best_score, target, link_method = score, source, "title"
                    continue
                # Token overlap catches the same work when punctuation, markup or a
                # journal-suffix difference stops the substring test from firing.
                overlap = len(set(words) & reference_words) / len(set(words))
                if overlap >= 0.8:
                    score = overlap
                    if score > best_score:
                        best_score, target, link_method = score, source, "title"
            if target is None:
                best_score = 0.0
                for source in bundle.sources:
                    if source.source_id in claimed_ids or not source.year:
                        continue
                    surname = ""
                    if source.authors:
                        surname = _common.normalize_title(source.authors[0]).split()[-1:] or [""]
                        surname = surname[0] if surname else ""
                    if not surname or len(surname) < 4:
                        continue
                    if surname in normalized_reference and source.year in reference.text:
                        score = len(surname) / 20.0
                        if score > best_score:
                            best_score, target, link_method = score, source, "author-year"

        if target is None:
            target = Source(
                source_id=_next_source_id(bundle),
                doi=reference.doi,
                pmid=reference.pmid,
                year=reference.year,
                title_claimed=reference.text[:300],
                resolution="reference-list",
                evidence_locator="reference list",
            )
            bundle.sources.append(target)
            link_method = "unlinked"
        else:
            claimed_ids.add(target.source_id)
            target.link_method = link_method
            if link_method != "doi" and target.doi and reference.doi and target.doi != reference.doi:
                bundle.warnings.append(
                    "reference %s matched source %s by %s but the DOIs differ (%s vs %s)"
                    % (reference.number, target.source_id, link_method, reference.doi, target.doi)
                )

        target.citation_number = target.citation_number or reference.number
        if reference.doi and not target.doi:
            target.doi = reference.doi
        target.title_claimed = target.title_claimed or reference.text[:300]
        number_to_source[reference.number] = target

    # 4. Bare DOI/PMID lists.
    for token in doi_tokens:
        if token.startswith("PMID:"):
            source = Source(
                source_id=_next_source_id(bundle),
                pmid=token.split(":", 1)[1],
                resolution="doi-list",
            )
        else:
            source = Source(
                source_id=_next_source_id(bundle), doi=token, resolution="doi-list"
            )
        bundle.sources.append(source)

    # 5. Sources that exist only as bare `S` ids would already be in the ledger.
    for number, source in number_to_source.items():
        source.citation_number = source.citation_number or number

    # Assign stable ids to anything that still lacks one, then index.
    for source in bundle.sources:
        if not source.source_id:
            source.source_id = _next_source_id(bundle)
    # Re-key to be safe against duplicates introduced above.
    seen: set = set()
    for position, source in enumerate(bundle.sources, start=1):
        if not source.source_id or source.source_id in seen:
            source.source_id = "S%03d" % position
        seen.add(source.source_id)
    bundle._index()

    # 6. Attach local evidence: declared manifest file first, then DOI in filename,
    #    then mined DOI from page 1, then a same-stem sidecar.
    pdfs = _candidate_pdfs(files)
    claimed: set = set()
    for source in bundle.sources:
        for name in declared_files.get(source.source_id, []):
            match = match_file(name, files)
            if match is not None and str(match) not in claimed:
                if attach_local_evidence(source, match):
                    claimed.add(str(match))
                    source.warnings.append("attached from the BibTeX file field")
                break

    if files:
        # Anything the manifest did not claim: try to place it by name first, which is
        # what closes a worklist gap, then by mined DOI.
        for path in files:
            if str(path) in claimed:
                continue
            target, method = match_file_to_source(path, bundle, claimed)
            if target is None:
                continue
            if _can_upgrade(target) and attach_local_evidence(target, path):
                claimed.add(str(path))
                target.link_method = target.link_method or "user_supplied"
                target.identity_check = "user_supplied"
                target.warnings.append("matched by %s and attached as evidence" % method)
        bundle._index()

    if pdfs and not bib_entries:
        # No manifest: mine page 1 for a DOI so the folder can still be joined.
        mined: list = []
        for path in pdfs:
            if str(path) in claimed:
                continue
            extracted = _pdftext.extract_pdf(path, first_page_only=True)
            doi = mine_doi(extracted.text) if extracted.text else ""
            if not doi:
                doi = _common.normalize_doi(
                    (FILENAME_DOI_RE.search(path.stem).group(1) if FILENAME_DOI_RE.search(path.stem) else "")
                )
            mined.append((path, doi, extracted.text or ""))
        for path, doi, page_one in mined:
            target = bundle.lookup(doi) if doi else None
            if target is None:
                target = Source(
                    source_id=_next_source_id(bundle),
                    doi=doi,
                    resolution="pdf-folder",
                )
                bundle.sources.append(target)
            if _can_upgrade(target):
                if attach_local_evidence(target, path):
                    claimed.add(str(path))
                    if doi and not target.doi:
                        target.doi = doi
            elif not target.file_path:
                target.file_path = str(path)
        bundle._index()

    # Text sidecars with no PDF: mine a DOI from the text so a `.txt` export of a
    # paywalled paper can still be joined, which is the documented route for a source
    # the user had to obtain by hand.
    for path in files:
        if str(path) in claimed or path.suffix.lower() not in (".txt", ".md"):
            continue
        doi = _mine_text_doi(path)
        target = bundle.lookup(doi) if doi else None
        if target is None:
            continue
        if _can_upgrade(target) and attach_local_evidence(target, path):
            claimed.add(str(path))
            target.warnings.append("matched by DOI mined from the text file")
    bundle._index()

    # 7. Metadata resolution (network) for sources that still need it.
    if resolve_metadata and not offline:
        import _resolve

        effective_mailto = mailto or _resolve.DEFAULT_MAILTO
        transient_failures = 0
        queried = 0
        for source in bundle.sources:
            if source.doi and (not source.title or source.verification_status != "verified"):
                resolution = _resolve.resolve(source.doi, mailto=effective_mailto)
                _apply_resolution(source, resolution)
                if resolution.abstract_error:
                    transient_failures += 1
                queried += 1
                # Paced, because sixty back-to-back lookups is enough to earn an HTTP
                # 503, and a 503 recorded as "no evidence" is a false instruction.
                if queried < len(bundle.sources):
                    time.sleep(RESOLUTION_PACING_SECONDS)
        if transient_failures:
            bundle.warnings.append(
                "%d of %d abstract lookups failed (%s); this is a transient lookup "
                "failure, not evidence that the sources lack abstracts, so retry before "
                "concluding anything from it"
                % (
                    transient_failures,
                    queried,
                    "see each source's attempts",
                )
            )
    elif not offline:
        bundle.warnings.append("metadata resolution skipped")
    else:
        bundle.warnings.append(
            "offline: no DOI was resolved over the network; sources are graded on local evidence only"
        )

    # 7b. Evidence acquisition (network). Runs after resolution so the identity check can
    #     use a settled title and DOI, and after the supplied-file step so a file the user
    #     provided always wins. A source that already holds primary evidence is skipped
    #     inside `acquire`, so this cannot overwrite better evidence with worse.
    if acquire and not offline:
        import _acquire

        acquired = 0
        upgraded = 0
        before: dict = {}
        for source in bundle.sources:
            # Skip only what is already `primary`. Gating on `checkable` was a bug: an
            # abstract is checkable but cannot support a red finding, so acquisition
            # skipped exactly the sources it most improves.
            if not _can_upgrade(source):
                continue
            before[source.source_id] = source.evidence_strength
            state = _acquire.acquire(
                source,
                offline=False,
                cache_dir=cache_dir,
                mailto=mailto,
                allow=acquire,
            )
            if state:
                acquired += 1
                if before.get(source.source_id) != source.evidence_strength:
                    upgraded += 1
        if acquired:
            bundle.warnings.append(
                "acquired readable evidence for %d source(s); %d of them improved in "
                "strength (an abstract upgraded to full text can support a red finding, "
                "an abstract cannot)" % (acquired, upgraded)
            )
        else:
            bundle.warnings.append(
                "no open-access evidence could be acquired for the %d source(s) that needed it; "
                "the worklist names what to supply" % len(bundle.sources)
            )
    elif acquire and offline:
        bundle.warnings.append(
            "offline: no evidence was acquired over the network even though --acquire was given"
        )

    # 8. In offline mode, a DOI we hold locally still counts as identified, but not
    #    as verified: verification requires an authority to have confirmed it.
    for source in bundle.sources:
        if source.verification_status != "verified":
            if source.resolution == "ledger" and source.doi:
                continue  # the ledger's own verification_status stands
            if source.evidence_availability in ("full_text", "abstract") and source.doi:
                source.verification_status = "unverified"
        if source.retraction_status == "not_checked" and offline:
            source.warnings.append("retraction status not checked (offline)")

    # 9. Anything still holding no evidence is metadata only, whether or not it has a
    #    title: a source we know exists but cannot read is exactly the condition the
    #    worklist exists to surface, and it must never look like a source we checked.
    for source in bundle.sources:
        if not source.evidence_text:
            if source.evidence_availability == "unavailable":
                source.evidence_availability = "metadata_only" if (
                    source.title or source.title_claimed or source.doi
                ) else "unavailable"
            source.evidence_strength = "none"
            if not source.evidence_origin:
                source.evidence_origin = ""
            if source.retrieval_status == "not_attempted":
                source.retrieval_status = (
                    "unavailable" if offline else "empty"
                )
    bundle._index()
    return bundle


def _apply_resolution(source: Source, resolution) -> None:
    """Copy a network resolution onto a source, recording what was learned."""
    if resolution.found:
        source.verification_status = "verified"
        source.title = source.title or resolution.title
        if resolution.title and source.title_claimed:
            import _resolve

            source.title_match = (
                "match"
                if _resolve.title_matches(source.title_claimed, resolution.title)
                else "mismatch"
            )
        if not source.authors:
            source.authors = resolution.authors
        source.year = source.year or resolution.year
        source.container = source.container or resolution.container
        source.pmid = source.pmid or resolution.pmid
        if resolution.retraction_status != "not_checked":
            source.retraction_status = resolution.retraction_status
        source.retraction_notes.extend(resolution.retraction_notes)
        if resolution.abstract and not source.evidence_text:
            source.evidence_text = resolution.abstract[:MAX_EVIDENCE_CHARS]
            source.evidence_availability = "abstract"
            source.evidence_method = "europepmc"
            source.evidence_strength = "abstract"
            source.evidence_origin = "europepmc:abstract"
            source.acquisition_method = "api-abstract"
            source.acquisition_endpoint = "europepmc/rest/search"
            source.identity_check = "doi_matched"
            source.acquired_at = _timestamp()
            source.record_attempt("api", "europepmc/rest/search", "returned", "abstract")
            source.evidence_locator = "abstract"
            if resolution.title and source.title_claimed:
                # The abstract belongs to the DOI we asked about; confirm that DOI's
                # title is the work the document cites before using its text.
                if source.title_match == "mismatch":
                    source.evidence_text = ""
                    source.evidence_availability = "metadata_only"
                    source.evidence_strength = "none"
                    source.evidence_origin = ""
                    source.identity_check = "title_mismatch"
                    source.warnings.append(
                        "the resolved DOI's title does not match the reference entry, so "
                        "its abstract was discarded rather than used as evidence"
                    )
    else:
        source.verification_status = "failed" if resolution.error else "unverified"
        if resolution.error:
            source.warnings.append("resolution failed: %s" % resolution.error)
            source.record_attempt("api", "crossref/openalex", "error", resolution.error)
    if resolution.abstract_error:
        # A transient failure must not be filed where "no evidence exists" lives: the
        # worklist tells a user what to do, and "go and find this PDF" is the wrong
        # instruction when the API was briefly unavailable.
        source.record_attempt(
            "api-abstract", "europepmc/rest/search", "error", resolution.abstract_error
        )


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="build a citation-report source bundle")
    parser.add_argument("--document")
    parser.add_argument("--bib")
    parser.add_argument("--pdf-dir")
    parser.add_argument("--sources")
    parser.add_argument("--claims")
    parser.add_argument("--dois")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--out")
    arguments = parser.parse_args()

    document = None
    if arguments.document:
        import _intake

        document = _intake.read_document(arguments.document)
    built = build_bundle(
        document=document,
        bib_path=arguments.bib,
        pdf_dir=arguments.pdf_dir,
        ledger_path=arguments.sources,
        claims_path=arguments.claims,
        doi_path=arguments.dois,
        offline=arguments.offline,
    )
    if arguments.out:
        built.write_csv(arguments.out)
    print(json.dumps(built.to_dict(), indent=2)[:4000])
