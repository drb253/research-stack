"""Intake adequacy: did the tool understand the document well enough to grade it?

Every failure this module guards against produces *confident nonsense* rather than an
error, which is why each one is a precondition rather than a warning:

* A Nature-style document citing with superscript numbers produces **zero** citation
  markers under a bracket grammar, so every checkable sentence becomes `unattributed`
  -- thousands of false accusations that the author failed to cite.
* A German or French document matches none of the English trigger phrases, so it
  reports almost nothing to check and reads as a clean result.
* A splitter that fails on unpunctuated or tabular text yields one enormous "sentence",
  which is then graded as though it were a claim.
* A document with markers but no source list at all cannot be checked, yet used to
  exit 0.

Each precondition reports `passed`, `failed` or `not_applicable` with the observed
value, so the artefact shows not only the findings but the evidence that the tool was
in a position to make them. A failure makes the run `insufficient_input` (exit 4) and
no finding is presented as a finding.
"""

from __future__ import annotations

import _common
import _signals

#: A bibliography this long with no citation markers bound anywhere almost certainly
#: means the marker grammar does not match the document's style.
REFERENCE_ENTRIES_FOR_STYLE_CHECK = 10
#: Below this share of narrative sentences carrying a trigger, the signal set is
#: probably the wrong language rather than the document being devoid of claims.
MIN_TRIGGER_YIELD = 0.02
SENTENCES_FOR_LANGUAGE_CHECK = 50
#: A sentence this long is not a sentence; it is a failed split.
SUSPECT_MEDIAN_SENTENCE_CHARS = 400
#: One sentence swallowing this share of the document is a failed split -- but only in a
#: document big enough for the share to mean anything. In a two-sentence document the
#: longest is inevitably about half the text, so applying the share test there blocks a
#: perfectly good short document. Both conditions must hold.
SUSPECT_SINGLE_SENTENCE_SHARE = 0.20
SUSPECT_SHARE_MIN_SENTENCES = 10
SUSPECT_SHARE_MIN_CHARS = 800


def evaluate(document, bundle, verdicts) -> list:
    """Return one record per precondition, in a fixed order."""
    records = [
        _citation_style(document, bundle),
        _trigger_language(document, verdicts),
        _sentence_split(document),
        _source_list(document, bundle),
    ]
    return records


def _record(code: str, status: str, observed: str, detail: str, action: str = "") -> dict:
    payload = {
        "code": code,
        "status": status,
        "observed": observed,
        "detail": detail,
    }
    if action:
        payload["action"] = action
    return payload


def _citation_style(document, bundle) -> dict:
    """Markers bound in the graded prose, against the size of the reference list.

    Counted over narrative sentences only. A bibliography is full of bracketed and
    parenthesised apparatus -- `[Internet]`, `(2020)`, `12(3)` -- so counting markers
    document-wide made this check pass on a document whose prose contained no citation
    marker at all, which is precisely the case it exists to catch.
    """
    entries = len(bundle.reference_entries)
    narrative = document.narrative_sentences()
    markers = sum(len(sentence.markers) for sentence in narrative)
    marker_sentences = sum(1 for sentence in narrative if sentence.markers)
    observed = "%d marker(s) in %d of %d graded sentence(s); %d reference entr(ies)" % (
        markers,
        marker_sentences,
        len(narrative),
        entries,
    )
    if entries < REFERENCE_ENTRIES_FOR_STYLE_CHECK:
        return _record(
            "CITATION_STYLE_UNRECOGNISED",
            "not_applicable",
            observed,
            "fewer than %d reference entries, so there is not enough evidence to tell a "
            "style mismatch from a document that simply cites little"
            % REFERENCE_ENTRIES_FOR_STYLE_CHECK,
        )
    if marker_sentences:
        return _record("CITATION_STYLE_UNRECOGNISED", "passed", observed, "citation markers were bound")
    return _record(
        "CITATION_STYLE_UNRECOGNISED",
        "failed",
        observed,
        "the document has a substantial reference list but no citation marker could be "
        "bound in its prose, so every checkable sentence would be reported as "
        "unattributed. Superscript numeric citations are recognised in DOCX; a PDF text "
        "layer does not carry superscript, so a PDF of such a document cannot be graded "
        "by markers.",
        "supply the document as DOCX or TeX, or state the citation style explicitly",
    )


def _trigger_language(document, verdicts) -> dict:
    """Share of narrative sentences that any trigger fired on.

    Read the result carefully: this catches the extreme case, where nothing matched at
    all. A non-English document that is full of numbers still clears it, because digits
    are language-independent -- so the record also reports whether any
    *language-dependent* signal fired, which is the part that tells a reader whether
    non-numeric claims are being found at all.
    """
    total = len(verdicts)
    language_dependent = {
        _signals.TRIGGER_SUPERLATIVE,
        _signals.TRIGGER_VAGUE_ATTRIBUTION,
        _signals.TRIGGER_DEFINITION,
    }
    fired = {
        trigger.get("code")
        for verdict in verdicts
        for trigger in verdict.triggers
        if trigger.get("code")
    }
    style_fired = sorted(fired & language_dependent)
    extra = ""
    if total >= SENTENCES_FOR_LANGUAGE_CHECK and not style_fired:
        extra = (
            " No language-dependent signal (superlative, vague attribution, borrowed "
            "definition) fired anywhere, so only numeric claims were looked for. That is "
            "normal in a results-heavy section, and it is also what a non-English "
            "document looks like."
        )
    if total < SENTENCES_FOR_LANGUAGE_CHECK:
        return _record(
            "TRIGGER_LANGUAGE_UNSUPPORTED",
            "not_applicable",
            "%d narrative sentence(s)" % total,
            "too short to distinguish a wrong-language document from a document with "
            "few claims",
        )
    triggered = sum(1 for verdict in verdicts if verdict.requires_citation)
    share = triggered / total
    observed = "%d of %d sentence(s) = %.1f%%; language-dependent signals: %s" % (
        triggered,
        total,
        share * 100,
        ", ".join(style_fired) if style_fired else "none",
    )
    if share < MIN_TRIGGER_YIELD:
        return _record(
            "TRIGGER_LANGUAGE_UNSUPPORTED",
            "failed",
            observed,
            "almost no sentence matched any attribution signal. The signals are "
            "English-specific, so this is what a non-English document looks like -- and "
            "it would be reported as a document with nothing to check." + extra,
            "grade an English version, or treat the report's coverage figures as not "
            "applicable to this document",
        )
    return _record(
        "TRIGGER_LANGUAGE_UNSUPPORTED",
        "passed",
        observed,
        "signals matched the prose." + extra,
    )


def _sentence_split(document) -> dict:
    """Median sentence length, and whether one sentence swallowed the document."""
    sentences = list(document.sentences)
    if not sentences:
        return _record(
            "SENTENCE_SPLIT_SUSPECT", "not_applicable", "no sentences", "nothing to measure"
        )
    lengths = sorted(len(sentence.text) for sentence in sentences)
    median = lengths[len(lengths) // 2]
    longest = lengths[-1]
    total_chars = sum(lengths) or 1
    share = longest / total_chars
    observed = "median %d chars, longest %d (%.0f%% of the graded text)" % (
        median,
        longest,
        share * 100,
    )
    # The share test only means something in a document with enough sentences for one
    # sentence to stand out. See the constants above.
    share_is_meaningful = (
        len(sentences) >= SUSPECT_SHARE_MIN_SENTENCES and longest >= SUSPECT_SHARE_MIN_CHARS
    )
    if median > SUSPECT_MEDIAN_SENTENCE_CHARS or (
        share_is_meaningful and share > SUSPECT_SINGLE_SENTENCE_SHARE
    ):
        return _record(
            "SENTENCE_SPLIT_SUSPECT",
            "failed",
            observed,
            "sentences this long mean the splitter did not find the boundaries, so each "
            "'sentence' is several claims and any verdict on it is meaningless",
            "add punctuation, or convert the document to text with sentence breaks",
        )
    return _record("SENTENCE_SPLIT_SUSPECT", "passed", observed, "sentence lengths are plausible")


def _source_list(document, bundle) -> dict:
    """Is there anything at all to check a citation against?"""
    # Narrative markers only, for the same reason as the style check: apparatus inside a
    # bibliography is not the prose citing something.
    markers = sum(len(sentence.markers) for sentence in document.narrative_sentences())
    has_registry = bool(bundle.sources) or bool(bundle.reference_entries) or bool(bundle.claims)
    observed = "%d citation marker(s) in the prose; %d source(s); %d reference entr(ies)" % (
        markers,
        len(bundle.sources),
        len(bundle.reference_entries),
    )
    if not markers:
        return _record(
            "NO_SOURCE_LIST",
            "not_applicable",
            observed,
            "the document cites nothing, so there is no citation to check",
        )
    if has_registry:
        return _record("NO_SOURCE_LIST", "passed", observed, "a source list is available")
    return _record(
        "NO_SOURCE_LIST",
        "failed",
        observed,
        "the document cites sources but no reference list was recognised and none was "
        "supplied, so nothing can be checked and no verdict would mean anything",
        "pass --bib, --sources or --dois, or make the reference list machine-readable",
    )


def summarise(records: list) -> dict:
    """The status and reasons a run should adopt, given the preconditions."""
    failed = [record for record in records if record["status"] == "failed"]
    if not failed:
        return {
            "status": "pass",
            "blocking": False,
            "failed": [],
            "reason": [],
        }
    return {
        "status": "insufficient_input",
        "blocking": True,
        "failed": [record["code"] for record in failed],
        "reason": [
            "%s: %s" % (record["code"], record["detail"]) for record in failed
        ]
        + [
            record["action"]
            for record in failed
            if record.get("action")
        ],
    }


def banner(records: list) -> str:
    """The input banner for a precondition failure, distinct from the evidence banner."""
    failed = [record for record in records if record["status"] == "failed"]
    if not failed:
        return ""
    return (
        "INPUT-BOUND \u2014 THE DOCUMENT COULD NOT BE READ WELL ENOUGH. "
        "Findings below are provisional and must not be quoted."
    )
