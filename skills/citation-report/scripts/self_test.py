"""Offline logic self-test: no files, no network, no renderer.

Run with ``--self-test``. It asserts the invariants that would otherwise fail
silently — sentence splitting, marker binding, DOI mining, quantity comparison, the
rule ladder, and the coverage arithmetic. Every assertion states the failure it is
preventing, because a self-test that only says "assert" teaches nothing when it
breaks.

This is deliberately separate from ``selftest.sh``: that harness exercises the
command-line programs end to end against fixtures, including the paths that must
fail. This module checks the pure functions those programs are built from.
"""

from __future__ import annotations

import sys

import _bundle
import _common
import _evidence
import _highlight
import _intake
import preconditions
import sufficiency
import _sentences
import _signals
import coverage
import verdicts


def _check(condition, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_sentence_splitting() -> int:
    """A splitter that cuts mid-sentence would accuse half a sentence."""
    checks = 0
    cases = [
        ("Prevalence ranged from 9-90% for anxiety. This was a review [12].", 2),
        ("Screening tools favour sensitivity (e.g. brief checklists). Interviews are gold standard.", 2),
        ("The trial by J. Smith et al. reported HR 0.49 (95% CI 0.38-0.64). It was published in 2018.", 2),
        ("See Fig. 2 for the flow. Table 3 lists counts. pp. 5-7 cover methods.", 3),
        ("A dose of 3.5 mg was given. The total was 12.4%. p < 0.001 was reported.", 3),
        ("\u8fd9\u662f\u7b2c\u4e00\u53e5\u3002\u8fd9\u662f\u7b2c\u4e8c\u53e5\uff01\u7b2c\u4e09\u53e5\uff1f", 3),
        ("Statin therapy reduced events [claim:C001] [src:S001]. It was tolerated.", 2),
    ]
    for text, expected in cases:
        got = len(_sentences.split_sentences(_sentences.normalize_text(text)))
        _check(
            got == expected,
            "sentence splitting: expected %d sentence(s), got %d in %r" % (expected, got, text),
        )
        checks += 1
    return checks


def test_marker_binding() -> int:
    """A marker attributed to the wrong sentence would mis-cite it."""
    checks = 0
    sentence = _sentences.split_sentences("See [12,14] and [15-17] (Smith et al., 2019).")[0]
    numeric = [value for marker in sentence.markers if marker.kind == "numeric" for value in marker.values]
    _check("12" in numeric and "17" in numeric, "numeric markers must expand ranges: %r" % numeric)
    # `12,14` is two references; `15-17` is three. Five in total.
    _check(len(numeric) == 5, "12,14 + 15-17 must expand to 5 values, got %d" % len(numeric))
    checks += 1

    acronyms = _sentences.split_sentences("Not a citation (PTSD) or (ITQ) or (DSO).")[0]
    values = [value for marker in acronyms.markers for value in marker.values]
    _check(values == [], "acronyms in parentheses must not become citations: %r" % values)
    checks += 1

    year_only = _sentences.split_sentences("Published in the year (2019) elsewhere.")[0]
    numeric_years = [
        value for marker in year_only.markers if marker.kind == "numeric" for value in marker.values
    ]
    _check(
        numeric_years == [],
        "a parenthesised year must not be read as a reference number: %r" % numeric_years,
    )
    checks += 1

    parenthetical = _sentences.split_sentences("Vary widely (1-4) across groups.")[0]
    values = [value for marker in parenthetical.markers for value in marker.values]
    _check(values == ["1", "2", "3", "4"], "parenthetical numeric citations must expand: %r" % values)
    checks += 1

    stripped = _sentences.strip_markers("Events fell in adults [12].")
    _check(
        "12" not in stripped and " ." not in stripped,
        "stripping a marker must not leave a stray space before the full stop: %r" % stripped,
    )
    checks += 1
    return checks


def test_doi_mining() -> int:
    """Truncating a DOI with parentheses silently resolves the wrong paper."""
    checks = 0
    cases = [
        ("See 10.1016/s2215-0366(22)00375-3 for details", "10.1016/s2215-0366(22)00375-3"),
        ("doi:10.1056/NEJMoa1801005.", "10.1056/nejmoa1801005"),
        ("(10.1136/bmj.n1234)", "10.1136/bmj.n1234"),
        ("no identifier here", ""),
    ]
    import _bundle

    for text, expected in cases:
        got = _bundle.mine_doi(text)
        _check(got == expected, "DOI mining: expected %r, got %r from %r" % (expected, got, text))
        checks += 1
    return checks


def test_signals() -> int:
    """Over-triggering inflates the orange count; under-triggering hides gaps."""
    checks = 0
    must_trigger = [
        "Prevalence was 91.5% among students.",
        "Studies suggest that social media use is addictive.",
        "CPTSD is defined as PTSD plus disturbances in self-organisation.",
        "The largest trial to date reported 12.4%.",
    ]
    must_not_trigger = [
        "Screening instruments favour sensitivity over specificity.",
        "The study was cross-sectional.",
        # "studies reported" IS a vague attribution and does deserve a citation, so this
        # case asserts only what it was written to assert: that the hedge "at most" is
        # not itself read as a superlative claim.
        "At most three studies reported this.",
        "Among adolescents, 91.5% experienced at least one stressor.",
    ]
    for text in must_trigger:
        _check(_signals.requires_citation(text), "must require a citation: %r" % text)
        checks += 1
    for text in must_not_trigger:
        if text.startswith("Among") or text.startswith("At most"):
            # These DO require a citation, for reasons other than the hedge. The
            # assertion is that the hedge itself is not mistaken for a superlative.
            codes = [trigger["code"] for trigger in _signals.citation_triggers(text)]
            _check(
                "SUPERLATIVE" not in codes,
                "the hedge must not be read as a superlative claim: %r" % codes,
            )
        else:
            _check(not _signals.requires_citation(text), "must not require a citation: %r" % text)
        checks += 1

    quantities = _signals.extract_quantities("Survival improved (HR 0.49, 95% CI 0.38-0.64; p < 0.001).")
    kinds = {quantity.kind for quantity in quantities}
    _check("measure" in kinds and "confidence_interval" in kinds, "measure and CI must separate: %r" % kinds)
    measure = [quantity for quantity in quantities if quantity.kind == "measure"][0]
    _check(measure.values == [0.49], "HR value must parse: %r" % measure.values)
    checks += 1
    return checks


def test_evidence_index() -> int:
    """A number lookup miss would downgrade a properly attributed sentence."""
    checks = 0
    index = _evidence.EvidenceIndex(text="Prevalence 91.5% and 12.4% CPTSD, n = 616, HR 0.49 (95% CI 0.38-0.64).").build()
    for value, expected in ((91.5, True), (12.4, True), (616, True), (0.49, True), (0.80, False)):
        _check(
            index.has_number(value) is expected,
            "evidence index: %s presence should be %s" % (value, expected),
        )
        checks += 1
    _check(index.measure_values("HR") and index.measure_values("HR")[0][0] == 0.49, "HR must be indexed")
    checks += 1
    return checks


def test_rule_table_integrity() -> int:
    """A rule paired with the wrong state would paint the wrong colour."""
    checks = 0
    for rule_id, (state, severity, meaning) in verdicts.RULES.items():
        _check(state in _common.VERDICT_STATE_SET, "rule %s names unknown state %r" % (rule_id, state))
        _check(severity in ("error", "warning", "info"), "rule %s has bad severity" % rule_id)
        _check(bool(meaning), "rule %s has no meaning text" % rule_id)
        checks += 1
    for state in _common.VERDICT_STATES:
        _check(state in _highlight.STATE_STYLE, "state %s has no colour" % state)
        _check(state in _highlight.STATE_ORDER, "state %s is missing from the legend order" % state)
        checks += 1
    _check(
        len(_highlight.STATE_ORDER) == len(_common.VERDICT_STATES),
        "legend and state vocabulary disagree",
    )
    checks += 1
    return checks


def test_verdicht_round_trip() -> int:
    """A recorded verdict that cannot be rebuilt cannot be audited."""
    checks = 0
    payload = {
        "verdicts": [
            {
                "sentence_id": "N0001",
                "text": "A sentence.",
                "char_start": 10,
                "char_end": 21,
                "state": "attributed",
                "rule_id": "D09",
                "requires_citation": True,
            }
        ]
    }
    rebuilt = verdicts.from_dict(payload)
    _check(len(rebuilt) == 1 and rebuilt[0].state == "attributed", "round trip failed")
    _check(rebuilt[0].severity == "info", "severity must come from the rule table")
    checks += 2

    for broken, why in (
        ({"verdicts": [dict(payload["verdicts"][0], rule_id="D99")]}, "unknown rule must be rejected"),
        ({"verdicts": [dict(payload["verdicts"][0], state="conflict")]}, "state/rule mismatch must be rejected"),
        ({"verdicts": [dict(payload["verdicts"][0], sentence_id="X1")]}, "bad sentence id must be rejected"),
    ):
        try:
            verdicts.from_dict(broken)
            raise AssertionError(why)
        except _common.InputError:
            checks += 1
    return checks


def test_coverage_arithmetic() -> int:
    """A summary whose parts do not sum to its total is worse than no summary."""
    checks = 0

    class _Source:
        def __init__(self, source_id, availability, retraction, strength="primary"):
            self.source_id = source_id
            self.evidence_availability = availability
            self.retraction_status = retraction
            self.evidence_strength = strength

        @property
        def checkable(self):
            return self.evidence_strength in _common.CHECKABLE_STRENGTH

        @property
        def red_capable(self):
            return self.evidence_strength in _common.RED_CAPABLE_STRENGTH

        @property
        def link_verified(self):
            return True

    class _Bundle:
        sources = [_Source("S001", "full_text", "clear"), _Source("S002", "metadata_only", "retracted")]
        claims: dict = {}

        @staticmethod
        def counts_by_evidence():
            return {"full_text": 1, "metadata_only": 1}

        @staticmethod
        def counts_by_retraction():
            return {"clear": 1, "retracted": 1}

    class _Verdict:
        def __init__(self, state, rule_id, requires):
            self.state = state
            self.rule_id = rule_id
            self.requires_citation = requires
            self.severity = verdicts.RULES[rule_id][1]

    graded = [
        _Verdict("attributed", "D09", True),
        _Verdict("synthesis", "D10", True),
        _Verdict("unattributed", "D02", True),
        _Verdict("no_citation_needed", "D01", False),
    ]
    summary = coverage.compute(graded, _Bundle())
    _check(summary["sentences_total"] == 4, "total must be 4")
    _check(summary["sentences_requiring_citation"] == 3, "requiring must be 3")
    _check(
        summary["sentences_with_support_claim"] == 3,
        "the support-claim denominator must exclude no_citation_needed (4 - 1 = 3)",
    )
    _check(summary["citation_coverage"]["numerator"] == 2, "covered must be 2")
    _check(
        summary["citation_coverage"]["denominator"] == 3,
        "the denominator must be the support-claim count, not the trigger count",
    )
    _check(
        summary["citation_coverage"]["numerator"] <= summary["citation_coverage"]["denominator"],
        "the coverage numerator must be a subset of its denominator",
    )
    checks += 5

    tampered = dict(summary)
    tampered["states"] = dict(summary["states"])
    tampered["states"]["attributed"] += 1
    try:
        coverage.validate(tampered)
        raise AssertionError("a tampered state count must be rejected")
    except _common.InputError:
        checks += 1
    return checks


def test_reference_entry_shapes() -> int:
    """A numbered reference entry arrives in one of two shapes depending on the reader.

    Markdown and plain text strip the list marker into `DocParagraph.marker`, so the
    number is NOT in the text. DOCX, PDF and LaTeX keep it in the text. Reading group
    two of a one-group pattern crashes on the second shape, and that crash was live in
    a shipped revision: it only triggered on a DOCX with a numbered bibliography,
    which the end-to-end harness did not cover at the time. Both shapes are asserted
    here so the gap cannot reopen silently.
    """
    checks = 0
    in_text = _intake.DocParagraph(index=0, kind="reference", text="1. Smith J. A title. 2020.")
    _check(_intake.reference_number(in_text) == "1", "number must be read from the text")
    _check(
        _intake.reference_body(in_text) == "Smith J. A title. 2020.",
        "the body must have its number removed: %r" % _intake.reference_body(in_text),
    )
    checks += 2

    via_marker = _intake.DocParagraph(
        index=1, kind="reference", text="Smith J. A title. 2020.", marker="2."
    )
    _check(_intake.reference_number(via_marker) == "2", "number must be read from the marker")
    _check(
        _intake.reference_body(via_marker) == "Smith J. A title. 2020.",
        "a marker-numbered entry needs no stripping: %r" % _intake.reference_body(via_marker),
    )
    checks += 2

    unnumbered = _intake.DocParagraph(index=2, kind="para", text="A body sentence.")
    _check(_intake.reference_number(unnumbered) == "", "an unnumbered paragraph has no number")
    _check(
        _intake.reference_body(unnumbered) == "A body sentence.",
        "an unnumbered paragraph is returned whole",
    )
    checks += 2
    return checks


def test_evidence_vocabulary() -> int:
    """The vocabulary is what stops a colour from claiming more than its evidence."""
    checks = 0
    # Anything that may convict must also be enough to check: a red built on evidence that
    # cannot even test a value would be an accusation from nothing.
    _check(
        _common.RED_CAPABLE_STRENGTH <= _common.CHECKABLE_STRENGTH,
        "every red-capable strength must also be checkable",
    )
    checks += 1
    _check(
        _common.EVIDENCE_STRENGTH_SET == frozenset(_common.EVIDENCE_STRENGTH),
        "the strength set and tuple disagree",
    )
    _check(
        set(_common.EVIDENCE_STRENGTH_RANK) == _common.EVIDENCE_STRENGTH_SET,
        "every strength needs a rank, or the best evidence cannot be chosen",
    )
    checks += 2
    _check(
        set(_common.STATUS_PRECEDENCE) == set(_common.RUN_STATUSES),
        "every run status needs a precedence",
    )
    _check(
        set(_common.STATUS_EXIT_CODE) == set(_common.RUN_STATUSES),
        "every run status needs an exit code",
    )
    _check(
        _common.STATUS_EXIT_CODE["insufficient_evidence"] not in (0, 1)
        and _common.STATUS_EXIT_CODE["insufficient_input"] not in (0, 1),
        "an input condition must not share an exit code with pass or fail",
    )
    checks += 3
    # D11, D12 and D13 are the downgrade rules and must land on a non-accusing state.
    for rule_id in ("D11", "D12", "D13"):
        _check(rule_id in verdicts.RULES, "rule %s is missing" % rule_id)
        _check(
            verdicts.RULES[rule_id][0] == "unverifiable",
            "rule %s must land on unverifiable, not %s" % (rule_id, verdicts.RULES[rule_id][0]),
        )
        _check(
            verdicts.RULES[rule_id][1] != "error",
            "rule %s must never be an error severity" % rule_id,
        )
        checks += 3
    return checks


def test_ocr_never_accuses() -> int:
    """Transcribed evidence may never support an accusation, at any strength.

    This is the safety-critical half of the OCR tier and it needs no engine: a `Source`
    with `transcribed=True` must not be `red_capable`, so the D08 bar cannot be cleared.
    The engine-dependent half -- that a real scan is transcribed and lands on D13 -- is a
    fixture in selftest.sh, because it needs tesseract and poppler.
    """
    checks = 0
    source = _bundle.Source(source_id="S001")
    for strength in sorted(_common.RED_CAPABLE_STRENGTH):
        source.evidence_strength = strength
        source.transcribed = False
        _check(source.red_capable, "%s evidence should be red-capable when it was read" % strength)
        source.transcribed = True
        source.transcription = "tesseract:eng"
        _check(
            not source.red_capable,
            "%s evidence must not be red-capable once it was transcribed" % strength,
        )
        checks += 2
    # And the flag must survive serialisation, or a consumer of the JSON cannot tell.
    source.transcribed = True
    source.transcription = "tesseract:eng"
    payload = source.to_dict()
    _check(payload.get("transcribed") is True, "transcribed must be serialised")
    _check(payload.get("transcription") == "tesseract:eng", "transcription must be serialised")
    _check(
        verdicts.RULES["D13"][0] == "unverifiable" and verdicts.RULES["D13"][1] != "error",
        "D13 must disclose a transcribed contradiction without asserting it",
    )
    checks += 3
    return checks


def test_ocr_engine_resolution() -> int:
    """Engine selection is a rule, not an accident, and it needs no engine installed.

    `resolve_engine` is what decides whether a run uses tesseract, RapidOCR, or refuses
    because the requested engine is absent. Pinned here because the CLI fixture for the
    absent-engine gap can only run on a machine that has one engine but not the other.
    """
    import _pdftext

    checks = 0
    original = _pdftext.ocr_engines_available
    try:
        # No engine at all: auto resolves to nothing, and any request is unmet.
        _pdftext.ocr_engines_available = lambda: []
        _check(_pdftext.resolve_engine("auto") == "", "auto with no engine must resolve to nothing")
        _check(_pdftext.resolve_engine("tesseract") == "",
               "a request for an absent engine must not resolve")
        _check(not _pdftext.ocr_available("auto"), "no engine means no OCR")
        checks += 3

        # One engine: auto picks it, the other stays unmet rather than falling back.
        _pdftext.ocr_engines_available = lambda: [_pdftext.ENGINE_TESSERACT]
        _check(_pdftext.resolve_engine("auto") == _pdftext.ENGINE_TESSERACT,
               "auto must resolve to the engine that is present")
        _check(_pdftext.resolve_engine(_pdftext.ENGINE_TESSERACT) == _pdftext.ENGINE_TESSERACT,
               "a request for a present engine must resolve")
        _check(_pdftext.resolve_engine(_pdftext.ENGINE_RAPIDOCR) == "",
               "a request for an absent engine must not silently use another")
        checks += 3

        # Both present: auto prefers tesseract (the engine this tier was measured on).
        _pdftext.ocr_engines_available = lambda: [_pdftext.ENGINE_TESSERACT,
                                                  _pdftext.ENGINE_RAPIDOCR]
        _check(_pdftext.resolve_engine("auto") == _pdftext.ENGINE_TESSERACT,
               "auto must prefer the engine this tier was built on")
        _check(_pdftext.resolve_engine(_pdftext.ENGINE_RAPIDOCR) == _pdftext.ENGINE_RAPIDOCR,
               "an explicit choice must be honoured when available")
        checks += 2

        # And the gap it produces must be an input gap with a worklist, not a finding.
        _pdftext.ocr_engines_available = lambda: [_pdftext.ENGINE_TESSERACT]
        gap = _pdftext._via_ocr(__import__("pathlib").Path("nope.pdf"),
                                engine=_pdftext.ENGINE_RAPIDOCR)
        _check(gap is not None and gap.gap_kind == _pdftext.GAP_OCR_ENGINE,
               "an absent requested engine must produce the engine gap")
        _check(bool(gap.gap_worklist), "the engine gap must carry a worklist")
        _check(not gap.transcribed, "an engine gap must not claim to have transcribed anything")
        checks += 3
    finally:
        _pdftext.ocr_engines_available = original
    return checks


def test_sufficiency_policies() -> int:
    """A policy that cannot block is not a policy."""
    checks = 0

    class _Source:
        def __init__(self, source_id, strength):
            self.source_id = source_id
            self.evidence_strength = strength
            self.checkable = strength in _common.CHECKABLE_STRENGTH
            self.red_capable = strength in _common.RED_CAPABLE_STRENGTH
            self.link_verified = True
            self.evidence_availability = "full_text"
            self.evidence_text = "x" * 50
            self.retraction_status = "clear"
            self.retrieval_status = "user_supplied"
            self.attempts = []
            self.citation_number = ""
            self.citekey = source_id
            self.doi = "10.1/" + source_id
            self.pmid = ""
            self.title = "Title " + source_id
            self.title_claimed = ""

    class _Bundle:
        sources = [_Source("S001", "primary"), _Source("S002", "none")]

    class _Verdict:
        def __init__(self, source_id):
            self.sources = [{"source_id": source_id}]
            self.requires_citation = True
            self.quantities = [{"kind": "percent"}]
            self.sentence_id = "N0001"

    verdict_list = [_Verdict("S001"), _Verdict("S002")]
    strict = sufficiency.evaluate(verdict_list, {}, _Bundle())
    _check(strict["status"] == "insufficient_evidence", "strict must block on one unreadable source")
    _check(strict["blocking"] is True, "strict must be blocking")
    _check(len(strict["worklist"]) == 1, "the unreadable source must be on the worklist")
    _check(strict["undecided_sentences"] == 1, "one sentence asserted a value it could not check")
    checks += 4

    relaxed = sufficiency.evaluate(verdict_list, {}, _Bundle(), policy="share", share=0.5)
    _check(relaxed["status"] == "pass", "a 0.5 share with one of two checkable must pass")
    _check(relaxed["blocking"] is False, "and must not block")
    checks += 2

    nothing_cited = sufficiency.evaluate([], {}, _Bundle())
    _check(nothing_cited["status"] == "pass", "a document citing nothing has no evidence to require")
    _check(nothing_cited["citing_sources"] == 0, "and no citing sources")
    checks += 2

    caveat = sufficiency.coverage_caveat(strict)
    _check("limit of the inputs" in caveat, "the caveat must say the limit is the inputs")
    _check("1 of 2" in caveat, "the caveat must name the ratio: %r" % caveat)
    checks += 2
    return checks


def test_preconditions() -> int:
    """A precondition that cannot fail, or that fails on good input, is worse than none."""
    checks = 0

    class _Sentence:
        def __init__(self, text, markers=0):
            self.text = text
            self.markers = [{"kind": "numeric", "values": ["1"]}] * markers

    class _Document:
        def __init__(self, sentences):
            self.sentences = [
                sentence if isinstance(sentence, _Sentence) else _Sentence(sentence)
                for sentence in sentences
            ]

        def narrative_sentences(self):
            return list(self.sentences)

    class _Bundle:
        def __init__(self, entries=0, sources=0, claims=0):
            self.reference_entries = list(range(entries))
            self.sources = list(range(sources))
            self.claims = {} if not claims else {"C001": {}}

    class _Verdict:
        def __init__(self, requires, triggers=()):
            self.requires_citation = requires
            self.triggers = [{"code": code} for code in triggers]

    # A two-sentence document must not be accused of a failed split: the longest
    # sentence is inevitably about half of it.
    short = _Document(["A short sentence about statins.", "Another short one."])
    records = preconditions.evaluate(short, _Bundle(), [_Verdict(True)] * 2)
    split = [r for r in records if r["code"] == "SENTENCE_SPLIT_SUSPECT"][0]
    _check(split["status"] == "passed", "a two-sentence document must not fail the split check")
    checks += 1

    # One enormous unpunctuated block must fail it.
    blob = _Document(["x" * 3000, "short."])
    records = preconditions.evaluate(blob, _Bundle(), [_Verdict(True)] * 2)
    split = [r for r in records if r["code"] == "SENTENCE_SPLIT_SUSPECT"][0]
    _check(split["status"] == "failed", "a 3000-character sentence must fail the split check")
    checks += 1

    # A substantial bibliography with no marker in the prose must fail the style check.
    many = _Document(["Sentence %d about statins." % index for index in range(12)])
    records = preconditions.evaluate(many, _Bundle(entries=12), [_Verdict(False)] * 12)
    style = [r for r in records if r["code"] == "CITATION_STYLE_UNRECOGNISED"][0]
    _check(style["status"] == "failed", "12 entries and no prose marker must fail the style check")
    checks += 1

    # Citations with no source list at all must fail.
    records = preconditions.evaluate(
        _Document([_Sentence("Statins reduced events [12].", markers=1)]),
        _Bundle(),
        [_Verdict(False)],
    )
    source_list = [r for r in records if r["code"] == "NO_SOURCE_LIST"][0]
    _check(source_list["status"] == "failed", "a citation with no source list must fail")
    checks += 1

    summary = preconditions.summarise(records)
    _check(summary["status"] == "insufficient_input", "a failed precondition must set the status")
    _check(summary["blocking"] is True, "and must block")
    checks += 2

    # No trigger anywhere over a long document is the non-English case.
    language = _Document(["Sentence %d about statins." % index for index in range(60)])
    records = preconditions.evaluate(language, _Bundle(sources=1), [_Verdict(False)] * 60)
    trigger = [r for r in records if r["code"] == "TRIGGER_LANGUAGE_UNSUPPORTED"][0]
    _check(trigger["status"] == "failed", "60 sentences with no signal must fail the language check")
    checks += 1
    return checks


def test_worklist_wording() -> int:
    """A transient failure must not be worded as an absence of evidence.

    Telling a user to go and find sixty PDFs because an API returned HTTP 503 is a false
    instruction, and it is the same class of error as reporting an input gap as a
    finding. The two cases must produce different advice.
    """
    checks = 0
    entry = {"sentences": 3, "needing_evidence": 2}

    transient = _bundle.Source(
        source_id="S001", doi="10.1/x", title="T", evidence_strength="none",
        retrieval_status="error",
    )
    transient.record_attempt("api-abstract", "europepmc/rest/search", "error", "HTTP 503")
    transient_row = sufficiency._worklist_row("S001", entry, transient)
    _check(
        "retry" in transient_row["suggested_action"],
        "a transient failure must advise a retry: %r" % transient_row["suggested_action"],
    )
    _check(
        "lookup failed" in transient_row["reason"],
        "and must say the lookup failed: %r" % transient_row["reason"],
    )
    checks += 2

    absent = _bundle.Source(
        source_id="S002", doi="10.1/y", title="T2", evidence_strength="none",
        retrieval_status="unavailable",
    )
    absent.record_attempt("api", "europepmc/rest/search", "unavailable", "not open access")
    absent_row = sufficiency._worklist_row("S002", entry, absent)
    _check(
        "pdf-dir" in absent_row["suggested_action"],
        "an absent source must ask for the file: %r" % absent_row["suggested_action"],
    )
    _check(
        "retry" not in absent_row["suggested_action"],
        "and must not advise a pointless retry",
    )
    checks += 2

    # A source that errored *and* then succeeded is not a transient failure.
    recovered = _bundle.Source(
        source_id="S003", doi="10.1/z", title="T3", evidence_strength="none",
        retrieval_status="returned",
    )
    recovered.record_attempt("api", "europepmc/rest/search", "error", "HTTP 503")
    recovered.record_attempt("api", "europepmc/rest/search", "returned", "abstract")
    recovered_row = sufficiency._worklist_row("S003", entry, recovered)
    _check(
        "retry" not in recovered_row["suggested_action"],
        "a source that recovered must not be told to retry",
    )
    checks += 1
    return checks


def main() -> int:
    tests = [
        ("sentence splitting", test_sentence_splitting),
        ("marker binding", test_marker_binding),
        ("doi mining", test_doi_mining),
        ("citation signals", test_signals),
        ("evidence index", test_evidence_index),
        ("rule table integrity", test_rule_table_integrity),
        ("verdict round trip", test_verdicht_round_trip),
        ("coverage arithmetic", test_coverage_arithmetic),
        ("reference entry shapes", test_reference_entry_shapes),
        ("evidence vocabulary", test_evidence_vocabulary),
        ("ocr never accuses", test_ocr_never_accuses),
        ("ocr engine resolution", test_ocr_engine_resolution),
        ("sufficiency policies", test_sufficiency_policies),
        ("intake preconditions", test_preconditions),
        ("worklist wording", test_worklist_wording),
    ]
    total = 0
    failed = 0
    for name, function in tests:
        try:
            total += function()
            print("  \033[32mPASS\033[0m %s" % name)
        except AssertionError as exc:
            failed += 1
            print("  \033[31mFAIL\033[0m %s: %s" % (name, exc))
    print("  %d assertion(s), %d failing test(s)" % (total, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv or len(sys.argv) == 1:
        raise SystemExit(main())
    print("usage: self_test.py --self-test")
    raise SystemExit(2)
