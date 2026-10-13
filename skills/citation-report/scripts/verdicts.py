"""Assign every sentence to a state, by a named rule, from recorded facts only.

The rule table below is the whole feature. Each rule has an identifier, the state
(or paint colour) it produces, the gate severity it carries, and the exact
predicate in `_classify`. The report prints the rule id on every note, the reference
documentation mirrors the table, and the test suite asserts both the passing and
the failing side of every rule. Nothing here is a model judgement: a language model
cannot change one of these verdicts, and the advisory channel is stored separately
and can never set, change or veto a state.

Two design commitments worth stating plainly:

* **Red requires positive evidence.** A sentence is never painted red because a
  number was *not found*. Extracted text is lossy — tables, figures and
  supplementary material routinely do not survive extraction — so "absent" is
  recorded as unverifiable, never as an accusation. Red is reserved for a citation
  that resolves to nothing, a retracted source, or a number that contradicts the
  same named measure in a source we actually hold.
* **The four-colour scheme is not enough.** The reference report has no state for
  "cited, identified, but I hold no evidence", so its sentences default to looking
  supported. That state exists here and is counted separately.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import _common
import _evidence
import _sentences
import _signals

# --------------------------------------------------------------------------- #
# The rule table
# --------------------------------------------------------------------------- #

#: rule id -> (state, severity, one-line meaning)
RULES = {
    "D01": (
        "no_citation_needed",
        "info",
        "no attribution-requiring signal and no citation marker",
    ),
    "D02": (
        "unattributed",
        "warning",
        "states a checkable fact, figure or borrowed formulation with no resolvable citation",
    ),
    "D03": (
        "unattributed",
        "warning",
        "citation marker matches no source in the document's reference apparatus",
    ),
    "D04": (
        "conflict",
        "error",
        "cited source is retracted",
    ),
    "D05": (
        "unverifiable",
        "info",
        "cited source identified but no evidence is held, so the claim cannot be checked",
    ),
    "D06": (
        "unverifiable",
        "info",
        "citation could not be resolved because no reference apparatus or source list was supplied",
    ),
    "D07": (
        "unverifiable",
        "warning",
        "citations resolve, but a number in the sentence is absent from the evidence held",
    ),
    "D08": (
        "conflict",
        "error",
        "a number contradicts the same named measure in a source we hold",
    ),
    "D09": (
        "attributed",
        "info",
        "every number in the sentence is present in the evidence of a cited source",
    ),
    "D10": (
        "synthesis",
        "info",
        "cited, resolves, and carries no independently checkable number",
    ),
    "D11": (
        "unverifiable",
        "warning",
        "would be a conflict, but the citation's link to the source is inferred rather than verified",
    ),
    "D12": (
        "unverifiable",
        "warning",
        "would be a conflict, but the evidence is a prose summary rather than the source's own text or a recorded value",
    ),
    "D13": (
        "unverifiable",
        "warning",
        "would be a conflict, but the value on one side came from OCR: a transcription may not support an accusation",
    ),
}

#: Quantities that must never be looked up in evidence. A confidence level is
#: apparatus, not a study result; a publication year is citation metadata, which is
#: checked by resolving the DOI against an authority rather than by searching the
#: source text (years frequently appear only in the reference list, which is not
#: part of the extracted evidence).
NON_CHECKABLE_KINDS = frozenset({"confidence_interval", "year"})

#: Marker kinds that identify a specific work, as opposed to an author-year note.
CITABLE_MARKER_KINDS = frozenset({"numeric", "bracket", "ledger_source"})

#: Marker kinds that point at the document's own claim ledger. A claim marker is a
#: reference to a registered claim, not to a source, so on its own it is not a
#: citation and must never be read as a fabricated one.
CLAIM_MARKER_KINDS = frozenset({"ledger_claim"})


@dataclass
class Verdict:
    sentence_id: str
    text: str
    char_start: int
    char_end: int
    paragraph: int
    section: str
    state: str
    rule_id: str
    severity: str
    requires_citation: bool
    triggers: list = field(default_factory=list)
    markers: list = field(default_factory=list)
    quantities: list = field(default_factory=list)
    unresolved_tokens: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    missing_numbers: list = field(default_factory=list)
    contradiction: dict = field(default_factory=dict)
    note: str = ""
    advisory: dict = field(default_factory=dict)
    #: What the verdict rested on, so a reader can see the quality of the evidence
    #: behind a colour rather than only its existence.
    evidence_strength: str = "none"
    evidence_origin: str = ""
    link_confidence: str = "none"

    def to_dict(self) -> dict:
        payload = {
            "sentence_id": self.sentence_id,
            "text": self.text,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "paragraph": self.paragraph,
            "section": self.section,
            "state": self.state,
            "rule_id": self.rule_id,
            "severity": self.severity,
            "requires_citation": self.requires_citation,
            "triggers": list(self.triggers),
            "markers": list(self.markers),
            "quantities": list(self.quantities),
            "unresolved_tokens": list(self.unresolved_tokens),
            "sources": list(self.sources),
            "missing_numbers": list(self.missing_numbers),
            "evidence_strength": self.evidence_strength,
            "evidence_origin": self.evidence_origin,
            "link_confidence": self.link_confidence,
            "note": self.note,
        }
        if self.contradiction:
            payload["contradiction"] = dict(self.contradiction)
        if self.advisory:
            payload["advisory"] = dict(self.advisory)
        return payload


def _rule(rule_id: str) -> tuple:
    return RULES[rule_id]


def _section_of(document, char_start: int) -> str:
    """The nearest preceding heading, so a report can group by section."""
    heading = ""
    for paragraph in document.paragraphs:
        if paragraph.char_start > char_start:
            break
        if paragraph.kind == "heading":
            heading = paragraph.text
    return heading


def _collect_tokens(sentence, bundle) -> tuple:
    """Split the sentence's markers into resolvable sources and raw tokens.

    A `[claim:C001]` marker is resolved through the claim ledger when one was
    supplied: the claim's own recorded `source_ids` are the citations, which is what
    makes a manuscript produced by this repository's review skills a first-class
    input rather than a special case.
    """
    resolved: list = []
    unresolved: list = []
    seen: set = set()
    for marker in sentence.markers:
        for token in marker.values:
            key = (marker.kind, token)
            if key in seen:
                continue
            seen.add(key)

            if marker.kind in CLAIM_MARKER_KINDS:
                claim = (bundle.claims or {}).get(token)
                if claim:
                    for source_id in claim.get("source_ids", []):
                        source = bundle.lookup(source_id)
                        if source is not None:
                            resolved.append(("claim", token, source))
                        else:
                            unresolved.append(
                                {
                                    "kind": "claim",
                                    "token": token,
                                    "detail": "claim %s names unknown source %s"
                                    % (token, source_id),
                                }
                            )
                    continue
                unresolved.append(
                    {
                        "kind": "claim",
                        "token": token,
                        "detail": "no claim ledger was supplied",
                    }
                )
                continue

            source = bundle.lookup(token)
            if source is None and marker.kind == "author_year":
                # An author-year marker is a pointer, not an identifier: match it
                # against a source's year only when exactly one source claims it.
                candidates = [s for s in bundle.sources if s.year == token]
                source = candidates[0] if len(candidates) == 1 else None
            if source is not None:
                resolved.append((marker.kind, token, source))
            else:
                unresolved.append({"kind": marker.kind, "token": token})
    return resolved, unresolved


def _has_citation_marker(sentence) -> bool:
    """True when the sentence carries something that identifies a work.

    A claim marker alone is not a citation: `[claim:C006]` says "this is claim 6",
    it does not say who established it. A sentence carrying only claim markers is
    therefore unattributed, not verifiable.
    """
    for marker in sentence.markers:
        if marker.kind in CITABLE_MARKER_KINDS or marker.kind == "author_year":
            return True
    return False


def _apparatus_is_closed(bundle) -> bool:
    """True when we know what the citable set is, so an unmatched marker is a
    finding rather than a gap in our own inputs."""
    if bundle.reference_entries:
        return True
    if any(source.citation_number for source in bundle.sources):
        return True
    if any(source.resolution in ("bib", "ledger") for source in bundle.sources):
        return True
    return False


def classify(document, bundle, indexes: dict, *, advisory=None) -> list:
    """Return one Verdict per narrative sentence, in document order."""
    verdicts: list = []
    closed = _apparatus_is_closed(bundle)

    for sentence in document.narrative_sentences():
        stripped = _sentences.strip_markers(sentence.text)
        triggers = _signals.citation_triggers(stripped)
        # `checkable` is a per-value judgement, not a per-kind one: a bare integer small
        # enough to be a page number, an index or a protein name proves nothing by being
        # found, so it may not be the basis of a green. It is still recorded, so a reader
        # sees every value the sentence contains.
        quantities = [
            quantity
            for quantity in _signals.extract_quantities(stripped)
            if quantity.kind not in NON_CHECKABLE_KINDS
        ]
        checkable_quantities = [q for q in quantities if q.checkable]
        resolved, unresolved = _collect_tokens(sentence, bundle)

        # A citable marker that the document's own apparatus cannot account for is itself
        # an attribution-requiring signal: the author asserted a source, and the assertion
        # does not hold. Recording it as a trigger keeps the `unattributed` state honest --
        # an orange sentence must genuinely need the citation it lacks. It applies only
        # when the apparatus is closed, because with no source list an unresolved marker
        # describes our inputs (D06), not the document.
        broken_citation = closed and any(
            token["kind"] in CITABLE_MARKER_KINDS or token["kind"] == "author_year"
            for token in unresolved
        )

        state, rule_id, note, extra = _classify(
            sentence, stripped, triggers, quantities, resolved, unresolved, indexes, closed,
            checkable=checkable_quantities,
            transcribed={
                "transcribed": bool(getattr(document, "transcribed", False)),
                "transcription": getattr(document, "transcription", ""),
            },
        )
        severity = _rule(rule_id)[1]
        source_records = _source_records(resolved, indexes, quantities)
        strength, origin, link_confidence = _evidence_summary(resolved)
        if broken_citation:
            triggers = triggers + [
                {
                    "code": _signals.TRIGGER_UNRESOLVED_CITATION,
                    "match": "",
                    "start": 0,
                    "end": 0,
                }
            ]

        verdict = Verdict(
            sentence_id=sentence.sentence_id,
            text=sentence.text,
            char_start=sentence.char_start,
            char_end=sentence.char_end,
            paragraph=sentence.paragraph,
            section=_section_of(document, sentence.char_start),
            state=state,
            rule_id=rule_id,
            severity=severity,
            requires_citation=bool(triggers),
            triggers=triggers,
            markers=[marker.to_dict() for marker in sentence.markers],
            quantities=[quantity.to_dict() for quantity in quantities],
            unresolved_tokens=unresolved,
            sources=source_records,
            note=note,
            evidence_strength=strength,
            evidence_origin=origin,
            link_confidence=link_confidence,
        )
        verdict.missing_numbers = extra.get("missing_numbers", [])
        verdict.contradiction = extra.get("contradiction", {}) or extra.get(
            "candidate_contradiction", {}
        )
        if advisory:
            grade = advisory.get(sentence.sentence_id)
            if grade:
                verdict.advisory = grade
        verdicts.append(verdict)
    return verdicts


def _evidence_summary(resolved) -> tuple:
    """The best evidence behind a sentence, and how the links were made.

    Reported per verdict so a colour never hides the quality of what it rested on:
    a green backed by the source's own text and a green backed by a ledger summary
    look identical otherwise.
    """
    if not resolved:
        return "none", "", "none"
    strengths = [source.evidence_strength for _, _, source in resolved]
    best = max(strengths, key=lambda name: _common.EVIDENCE_STRENGTH_RANK.get(name, 0))
    origins = []
    for _, _, source in resolved:
        if source.evidence_origin and source.evidence_origin not in origins:
            origins.append(source.evidence_origin)
    confidence = "exact" if all(source.link_verified for _, _, source in resolved) else "inferred"
    return best, "; ".join(origins)[:400], confidence


def _classify(
    sentence, stripped, triggers, quantities, resolved, unresolved, indexes, closed,
    checkable=None, transcribed=None,
) -> tuple:
    """The ladder. First matching rule wins, in rule-id order.

    `transcribed` is the *document's* transcription record (`{"transcribed": bool,
    "transcription": str}`), not the sources': a contradiction needs both sides to have
    been read rather than transcribed, and the sources carry their own flag.
    """
    if checkable is None:
        checkable = quantities
    transcribed = transcribed or {}
    document_transcribed = bool(transcribed.get("transcribed"))
    document_transcription = str(transcribed.get("transcription") or "")
    # A source can be reached through more than one marker (`[claim:C001]` and
    # `[src:S001]` name the same work), so collapse before reasoning about it.
    deduped: list = []
    seen_source_ids: set = set()
    for kind, token, source in resolved:
        if source.source_id in seen_source_ids:
            continue
        seen_source_ids.add(source.source_id)
        deduped.append((kind, token, source))
    resolved = deduped
    sources = [source for _, _, source in resolved]
    cites = _has_citation_marker(sentence)

    # D01 — nothing to attribute and nothing attached.
    if not sentence.markers and not triggers:
        return (
            "no_citation_needed",
            "D01",
            "No attribution-requiring signal and no citation marker.",
            {},
        )

    # D02 — a checkable assertion with no citation to a work. A claim marker alone
    # does not count: it names a registered claim, not a source.
    if not cites:
        detail = "States something checkable (%s) with no citation." % _trigger_summary(triggers)
        if sentence.markers:
            detail = (
                "Carries a claim marker but no citation to a source: %s."
                % _trigger_summary(triggers)
                if triggers
                else "Carries a claim marker but no citation to a source."
            )
        return ("unattributed", "D02", detail, {})

    # D05/D06 — markers exist but none resolves.
    if not resolved:
        citation_like = [
            token
            for token in unresolved
            if token["kind"] in CITABLE_MARKER_KINDS or token["kind"] == "author_year"
        ]
        if closed and citation_like:
            return (
                "unattributed",
                "D03",
                "Citation %s matches no source in the document's reference apparatus."
                % ", ".join("`%s`" % token["token"] for token in citation_like[:4]),
                {},
            )
        return (
            "unverifiable",
            "D06",
            "Citation present but unresolvable: no reference apparatus or source list "
            "was supplied, so this report cannot tell whether it exists.",
            {},
        )

    # D03 — some markers resolve and others do not, in a closed apparatus. The unmatched
    # marker is still a defect: the sentence cites a work that the document's own
    # reference apparatus cannot account for, so the sentence needs a citation. It does
    # not contradict a source, though, and it has no link to accuse: an unmatched marker
    # is by construction unlinked. The red bar requires an identity-verified link, so
    # this stays a warning. A red is an accusation, and this is not one.
    stray = [
        token
        for token in unresolved
        if token["kind"] in CITABLE_MARKER_KINDS and closed
    ]
    if stray:
        return (
            "unattributed",
            "D03",
            "Citation %s resolves to no source while other citations in the same "
            "sentence do; the reference apparatus is known, so this is not a gap in "
            "our inputs." % ", ".join("`%s`" % token["token"] for token in stray[:4]),
            {},
        )

    # D04 — a retracted source is cited. This rests on the *link* being right: if we
    # only guessed which work the citation points at, we do not know that the
    # retracted paper is the one cited, and saying so would be a false accusation.
    retracted = [source for source in sources if source.retraction_status == "retracted"]
    if retracted:
        if any(not source.link_verified for source in retracted):
            offenders = ", ".join(
                source.source_id for source in retracted if not source.link_verified
            )
            return (
                "unverifiable",
                "D11",
                "A cited source appears to be retracted, but the citation's link to %s "
                "was inferred from a title or year match rather than confirmed. "
                "Confirm the identifier before treating this as a finding." % offenders,
                {"downgraded_from": "D04"},
            )
        return (
            "conflict",
            "D04",
            "Cites a retracted source: "
            + "; ".join(
                "%s (%s)" % (source.source_id, ", ".join(source.retraction_notes) or "retracted")
                for source in retracted
            ),
            {},
        )

    # D08 — a number contradicts the same named measure in evidence we hold. A
    # contradiction is an accusation, so it has to clear three bars: the link must be
    # verified, the evidence must be machine-comparable rather than a human's summary, and
    # neither side may have been transcribed by OCR. Failing any bar downgrades to
    # `unverifiable` with the reason, so the disagreement is disclosed without being
    # asserted.
    candidates = _find_contradictions(checkable, sources, indexes)
    if candidates:
        defencible = [
            candidate
            for candidate in candidates
            if candidate["link_verified"]
            and candidate["red_capable"]
            and not candidate["transcribed"]
            and not document_transcribed
        ]
        if defencible:
            contradiction = defencible[0]
            return (
                "conflict",
                "D08",
                "Contradicts %s in %s: the sentence reports %s, the source reports %s."
                % (
                    contradiction["measure"],
                    contradiction["source_id"],
                    contradiction["sentence_value"],
                    contradiction["evidence_value"],
                ),
                {"contradiction": contradiction},
            )
        weakest = candidates[0]
        if not weakest["link_verified"]:
            return (
                "unverifiable",
                "D11",
                "The value %s differs from %s in %s, but the citation's link to that "
                "source was inferred from a title or year match rather than confirmed. "
                "Confirm the identifier to turn this into a finding."
                % (
                    weakest["sentence_value"],
                    weakest["measure"],
                    weakest["source_id"],
                ),
                {"downgraded_from": "D08", "candidate_contradiction": weakest},
            )
        if weakest["transcribed"] or document_transcribed:
            # Which side was transcribed decides what would close the gap, so say it.
            if weakest["transcribed"]:
                side = ("the evidence held for %s was read by OCR (%s)"
                        % (weakest["source_id"], weakest["transcription"] or "ocr"))
                remedy = ("Supply that source's text layer, or a corrected text export, to "
                          "turn this into a finding.")
            else:
                side = ("the sentence itself was read by OCR (%s)"
                        % (document_transcription or "ocr"))
                remedy = ("Supply a text-layer copy of the document, or its text export, to "
                          "turn this into a finding.")
            return (
                "unverifiable",
                "D13",
                "The value %s differs from the %s of %s, but %s. OCR is a transcription, "
                "and a single misread digit would make this an accusation about the author "
                "rather than a finding. %s"
                % (
                    weakest["sentence_value"],
                    weakest["measure"],
                    weakest["source_id"],
                    side,
                    remedy,
                ),
                {"downgraded_from": "D08", "candidate_contradiction": weakest},
            )
        return (
            "unverifiable",
            "D12",
            "The value %s differs from the %s of %s recorded in the ledger, but that "
            "record is the extractor's own prose rather than a value copied from the "
            "source. Supply the source file, or add the verbatim effect estimate to the "
            "ledger, to turn this into a finding."
            % (
                weakest["sentence_value"],
                weakest["measure"],
                weakest["source_id"],
            ),
            {"downgraded_from": "D08", "candidate_contradiction": weakest},
        )

    # D05 — we hold no evidence for any cited source.
    gradeable = [
        index
        for index in (indexes.get(source.source_id) for source in sources)
        if index is not None and index.graded
    ]
    if not gradeable:
        availability = ", ".join(
            sorted({source.evidence_availability for source in sources})
        )
        return (
            "unverifiable",
            "D05",
            "Cites %s, which is identified but not held (%s), so the claim cannot be "
            "checked. Supply the source file or allow resolution to confirm it."
            % (", ".join(source.source_id for source in sources[:3]), availability),
            {},
        )

    # D09 — every number is present in a cited source's evidence.
    missing = _missing_numbers(checkable, gradeable)
    if not missing:
        if checkable:
            return (
                "attributed",
                "D09",
                "Every value in the sentence (%s) is present in the evidence of %s."
                % (
                    _quantity_summary(checkable),
                    ", ".join(index.source_id for index in gradeable[:3]),
                ),
                {},
            )
        # No numbers: cited and resolvable, but nothing to check.
        return (
            "synthesis",
            "D10",
            "Cited and resolvable; carries no independently checkable value (%s), so it "
            "reads as synthesis rather than a directly evidenced result."
            % _quantity_summary(quantities)
            if quantities
            else "Cited and resolvable; carries no independently checkable value, so it "
            "reads as synthesis rather than a directly evidenced result.",
            {},
        )

    # D07 — a number is absent from the evidence we hold. Never red: extraction is
    # lossy and a table or figure may not have survived it.
    return (
        "unverifiable",
        "D07",
        "%s could not be found in the evidence held for %s. This is not treated as a "
        "contradiction: extracted text routinely omits tables and figures."
        % (
            ", ".join(missing),
            ", ".join(index.source_id for index in gradeable[:3]),
        ),
        {"missing_numbers": missing},
    )


def _missing_numbers(quantities, gradeable) -> list:
    missing: list = []
    for quantity in quantities:
        if not quantity.values:
            continue
        found = any(
            all(index.has_number(value) for value in quantity.values)
            for index in gradeable
        )
        if not found:
            missing.append(quantity.raw)
    return missing


def _find_contradictions(quantities, sources, indexes) -> list:
    """Every value that contradicts the same named measure in a source we hold.

    Returns candidates rather than a verdict, because whether a candidate may become a
    finding depends on two facts the caller owns: whether the link is verified, and
    whether the evidence is machine-comparable. Keeping the search separate from the
    judgment means the *search* can stay sensitive (find every disagreement) while the
    *accusation* stays conservative.

    Deliberately narrow otherwise: only an explicitly labelled measure (HR, OR, RR, ...)
    can contradict. An unlabelled number never can, because the same value legitimately
    appears in many roles -- sample size, year, dosage, page.
    """
    found: list = []
    for quantity in quantities:
        if quantity.kind != "measure" or not quantity.measure or not quantity.values:
            continue
        value = quantity.values[0]
        for source in sources:
            index = indexes.get(source.source_id)
            if index is None or not index.graded:
                continue
            for evidence_value, offset in index.measure_values(quantity.measure):
                if _signals.values_equal(value, evidence_value):
                    continue
                found.append(
                    {
                        "measure": quantity.measure,
                        "sentence_value": ("%g" % value),
                        "sentence_raw": quantity.raw,
                        "evidence_value": ("%g" % evidence_value),
                        "evidence_raw": "%s %g" % (quantity.measure, evidence_value),
                        "source_id": source.source_id,
                        "locator": source.locator(offset),
                        "quote": index.snippet(offset),
                        "link_method": source.link_method or source.resolution,
                        "link_verified": source.link_verified,
                        "evidence_strength": source.evidence_strength,
                        "evidence_origin": source.evidence_origin,
                        "red_capable": source.red_capable,
                        "transcribed": bool(getattr(source, "transcribed", False)),
                        "transcription": getattr(source, "transcription", ""),
                    }
                )
                break
    # Most defensible first: a verified link on machine-comparable evidence outranks
    # anything that would have to be downgraded.
    found.sort(
        key=lambda candidate: (
            not (candidate["link_verified"] and candidate["red_capable"]),
            candidate["source_id"],
        )
    )
    return found


def _source_records(resolved, indexes, quantities) -> list:
    records: list = []
    seen: set = set()
    for kind, token, source in resolved:
        if source.source_id in seen:
            continue
        seen.add(source.source_id)
        index = indexes.get(source.source_id)
        locator = source.locator()
        quote = ""
        if index is not None and index.graded:
            # Prefer a locator that points at one of the sentence's own values.
            for quantity in quantities:
                for value in quantity.values:
                    if index.has_number(value):
                        for offset in _offsets_of(index, quantity):
                            locator = source.locator(offset)
                            quote = index.snippet(offset)
                            break
                        break
                if quote:
                    break
            if not quote:
                locator = source.locator(0)
                quote = index.snippet(0, width=90)
        records.append(
            {
                "source_id": source.source_id,
                "citekey": source.citekey,
                "citation_number": source.citation_number,
                "marker": token,
                "marker_kind": kind,
                "doi": source.doi,
                "title": (source.title or source.title_claimed)[:200],
                "verification_status": source.verification_status,
                "retraction_status": source.retraction_status,
                "evidence_availability": source.evidence_availability,
                "evidence_method": source.evidence_method,
                "evidence_strength": source.evidence_strength,
                "evidence_origin": source.evidence_origin,
                "link_method": source.link_method or source.resolution,
                "link_verified": source.link_verified,
                "transcribed": bool(getattr(source, "transcribed", False)),
                "transcription": getattr(source, "transcription", ""),
                "locator": locator,
                "quote": quote,
            }
        )
    return records


def _offsets_of(index, quantity) -> list:
    """Offsets at which any value of `quantity` appears in the index's measures,
    else a single representative offset. Kept cheap: no full text re-scan."""
    offsets: list = []
    for label, entries in index.measures.items():
        for value, offset in entries:
            if any(_signals.values_equal(value, candidate) for candidate in quantity.values):
                offsets.append(offset)
    return offsets[:1]


def _trigger_summary(triggers) -> str:
    codes = []
    for trigger in triggers:
        if trigger["code"] not in codes:
            codes.append(trigger["code"])
    return ", ".join(code.lower().replace("_", " ") for code in codes) or "no signal"


def _quantity_summary(quantities) -> str:
    raws = [quantity.raw for quantity in quantities][:4]
    return ", ".join(raws)


# --------------------------------------------------------------------------- #
# Advisory channel
# --------------------------------------------------------------------------- #

ADVISORY_PROMPT = (
    "You are grading attribution only, not style. For each sentence below, decide "
    "whether the cited source text directly supports it, is synthesised with other "
    "material, is unsupported, or is contradicted. Quote the exact source span you "
    "relied on. Your answer is advisory: it is recorded beside the deterministic "
    "verdict and can never change it."
)


def from_dict(payload) -> list:
    """Rebuild Verdict objects from a `verdicts.json` file.

    Rendering must be possible from the recorded file alone: that is what makes the
    report reproducible and reviewable, and what lets a human correct a verdict and
    re-render without re-running the classification. Every field is validated, so a
    hand-edited file that contradicts itself is rejected rather than rendered.
    """
    record = _common.require_object(payload, "verdicts file")
    rows = _common.require_list(record.get("verdicts"), "verdicts")
    rebuilt: list = []
    seen_ids: set = set()
    for row in rows:
        row = _common.require_object(row, "verdict entry")
        sentence_id = str(row.get("sentence_id", ""))
        if not _common.SENTENCE_ID_RE.match(sentence_id):
            raise _common.InputError("verdicts file has an invalid sentence_id: %r" % sentence_id)
        if sentence_id in seen_ids:
            raise _common.InputError("verdicts file repeats sentence_id %s" % sentence_id)
        seen_ids.add(sentence_id)
        state = str(row.get("state", ""))
        rule_id = str(row.get("rule_id", ""))
        if state not in _common.VERDICT_STATE_SET:
            raise _common.InputError("verdict %s has an unknown state %r" % (sentence_id, state))
        if rule_id not in RULES:
            raise _common.InputError("verdict %s has an unknown rule %r" % (sentence_id, rule_id))
        expected_state, expected_severity, _ = RULES[rule_id]
        if state != expected_state:
            raise _common.InputError(
                "verdict %s pairs rule %s with state %s; the rule requires %s"
                % (sentence_id, rule_id, state, expected_state)
            )
        for field_name in ("char_start", "char_end"):
            if not isinstance(row.get(field_name), int):
                raise _common.InputError(
                    "verdict %s is missing integer %s" % (sentence_id, field_name)
                )
        verdict = Verdict(
            sentence_id=sentence_id,
            text=str(row.get("text", "")),
            char_start=row["char_start"],
            char_end=row["char_end"],
            paragraph=int(row.get("paragraph", 0)),
            section=str(row.get("section", "")),
            state=state,
            rule_id=rule_id,
            severity=expected_severity,
            requires_citation=bool(row.get("requires_citation")),
            triggers=list(row.get("triggers", [])),
            markers=list(row.get("markers", [])),
            quantities=list(row.get("quantities", [])),
            unresolved_tokens=list(row.get("unresolved_tokens", [])),
            sources=list(row.get("sources", [])),
            missing_numbers=list(row.get("missing_numbers", [])),
            contradiction=dict(row.get("contradiction", {})),
            note=str(row.get("note", "")),
            advisory=dict(row.get("advisory", {})),
            evidence_strength=str(row.get("evidence_strength", "none")),
            evidence_origin=str(row.get("evidence_origin", "")),
            link_confidence=str(row.get("link_confidence", "none")),
        )
        if verdict.evidence_strength not in _common.EVIDENCE_STRENGTH_SET:
            raise _common.InputError(
                "verdict %s has an unknown evidence strength %r"
                % (sentence_id, verdict.evidence_strength)
            )
        if verdict.link_confidence not in _common.LINK_CONFIDENCE_SET:
            raise _common.InputError(
                "verdict %s has an unknown link confidence %r"
                % (sentence_id, verdict.link_confidence)
            )
        if verdict.advisory and verdict.advisory.get("grade") not in _common.ADVISORY_GRADE_SET:
            raise _common.InputError(
                "verdict %s carries an advisory grade outside the controlled vocabulary"
                % sentence_id
            )
        rebuilt.append(verdict)
    return rebuilt


def load_advisory(path) -> dict:
    """Read an advisory file: {sentence_id: {grade, quote, model, ...}}.

    Grades are validated against the controlled vocabulary, the disclosure string is
    forced, and an unknown grade is rejected rather than quietly accepted.
    """
    payload = _common.require_object(_common.read_json(path), "advisory file")
    grades = payload.get("grades", payload)
    if not isinstance(grades, dict):
        raise _common.InputError("advisory file must map sentence ids to grades")
    result: dict = {}
    for sentence_id, entry in grades.items():
        if not _common.SENTENCE_ID_RE.match(str(sentence_id)):
            raise _common.InputError("advisory file has an invalid sentence id: %s" % sentence_id)
        if not isinstance(entry, dict):
            raise _common.InputError("advisory entry must be an object: %s" % sentence_id)
        grade = str(entry.get("grade", ""))
        if grade not in _common.ADVISORY_GRADE_SET:
            raise _common.InputError(
                "advisory grade must be one of %s (got %r)"
                % (", ".join(_common.ADVISORY_GRADES), grade)
            )
        result[str(sentence_id)] = {
            "grade": grade,
            "quote": str(entry.get("quote", ""))[:600],
            "source_id": str(entry.get("source_id", ""))[:40],
            "model": str(entry.get("model", ""))[:80],
            "disclosure": _common.ADVISORY_DISCLOSURE,
        }
    return result
