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

import re
import unicodedata

import _common
import _signals

#: A bibliography this long with no citation markers bound anywhere almost certainly
#: means the marker grammar does not match the document's style.
REFERENCE_ENTRIES_FOR_STYLE_CHECK = 10
#: Below this share of narrative sentences carrying a trigger, the signal set is
#: probably the wrong language rather than the document being devoid of claims.
MIN_TRIGGER_YIELD = 0.02
SENTENCES_FOR_LANGUAGE_CHECK = 50
#: The trigger rules are English-specific, so "did anything match?" cannot be a language
#: test: a bare digit fires STATISTIC, and digits read the same in every language. A
#: document full of numbers therefore cleared the share test above and was reported as a
#: document with nothing to check. Language is read from the words instead -- the share
#: of tokens that are common English function words.
ENGLISH_FUNCTION_WORDS = frozenset(
    """
    the of and to in is are was were that this with for on by as be or from at an it
    its we our their has have had not but which these those can may also between more
    than when where while such other into over after before within
    """.split()
)
#: On a document long enough to judge (SENTENCES_FOR_LANGUAGE_CHECK), this share of its
#: tokens being English function words is the floor for "this is English". Measured:
#: English controls 0.22-0.43, a mostly-Spanish document 0.03, Spanish prose 0.00.
MIN_ENGLISH_FUNCTION_SHARE = 0.08
#: A short document has too few tokens for the bar above to be sharp, but it still has to
#: clear something before it is called another language -- a three-sentence English method
#: paragraph must not be blocked. Deliberately lower than the long-document bar.
SHORT_ENGLISH_FUNCTION_SHARE = 0.04
#: Below this many tokens there is not enough text to call a short document another
#: language at all: "too short to tell" is not "wrong language", and stays not_applicable.
#: The floor is deliberately not small: two technical English sentences can be twenty
#: tokens with no function word in them ("Statin therapy reduced events [src:S001]."),
#: and that repetition is not evidence of another language.
SHORT_LANGUAGE_CHECK_MIN_TOKENS = 40
#: The words above cannot see a document written in another script, so the script is
#: measured too: this share of the graded text's letters must be Latin script.
MIN_LATIN_LETTER_SHARE = 0.5
#: A handful of letters proves nothing about the script the document is written in.
SHORT_SCRIPT_CHECK_MIN_LETTERS = 30
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


_LANGUAGE_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _graded_text(document) -> str:
    """The narrative prose the language test reads.

    Bibliography apparatus is excluded for the same reason the style and source-list
    checks exclude it: a reference list is not the document's prose.
    """
    narrative = getattr(document, "narrative_sentences", None)
    if callable(narrative):
        sentences = narrative()
    else:
        sentences = list(getattr(document, "sentences", []) or [])
    texts = [getattr(sentence, "text", "") for sentence in sentences]
    if any(text.strip() for text in texts):
        return " ".join(texts)
    return getattr(document, "text", "") or ""


def _letter_is_latin(character: str) -> bool:
    """Whether a letter belongs to the Latin script, accents included."""
    return "LATIN" in unicodedata.name(character, "")


def _language_evidence(document) -> dict:
    """Read the document's language without using the English trigger rules.

    Two independent reads, because each has a blind spot: the function-word share
    cannot see a document written in a non-Latin script, and the script share cannot
    see a Latin-script language that is not English.
    """
    text = _graded_text(document)
    tokens = _LANGUAGE_TOKEN_RE.findall(text)
    function_hits = sum(1 for token in tokens if token.lower() in ENGLISH_FUNCTION_WORDS)
    letters = [character for character in text if character.isalpha()]
    latin_letters = sum(1 for character in letters if _letter_is_latin(character))
    return {
        "tokens": len(tokens),
        "function_hits": function_hits,
        "function_share": (function_hits / len(tokens)) if tokens else 0.0,
        "letters": len(letters),
        "latin_share": (latin_letters / len(letters)) if letters else 1.0,
    }


def _language_observed(evidence: dict) -> str:
    return "English function words %d of %d token(s) = %.1f%%; Latin letters %.1f%%" % (
        evidence["function_hits"],
        evidence["tokens"],
        evidence["function_share"] * 100,
        evidence["latin_share"] * 100,
    )


def _looks_english(evidence: dict) -> bool:
    """The long-document language test: English words in a Latin script."""
    if evidence["function_share"] < MIN_ENGLISH_FUNCTION_SHARE:
        return False
    if evidence["letters"] and evidence["latin_share"] < MIN_LATIN_LETTER_SHARE:
        return False
    return True


def _clearly_another_language(evidence: dict) -> bool:
    """Whether a document too short for the share test is decided anyway.

    Conservative on purpose: a non-Latin script is decided as soon as there are enough
    letters to see it, but the function-word bar is lower for a short document and is
    applied only when there are enough tokens to mean anything. A short English
    paragraph must not be blocked merely for being short.
    """
    if (
        evidence["letters"] >= SHORT_SCRIPT_CHECK_MIN_LETTERS
        and evidence["latin_share"] < MIN_LATIN_LETTER_SHARE
    ):
        return True
    return (
        evidence["tokens"] >= SHORT_LANGUAGE_CHECK_MIN_TOKENS
        and evidence["function_share"] < SHORT_ENGLISH_FUNCTION_SHARE
    )


def _trigger_language(document, verdicts) -> dict:
    """Whether the document is in a language these English signals can read.

    Read the result carefully. Two reads are combined, and neither is a finding about
    the document:

    * The share of narrative sentences a trigger fired on. This catches the extreme case,
      where nothing matched at all. A non-English document that is full of numbers still
      clears it, because digits are language-independent -- so the record also reports
      whether any *language-dependent* signal fired, which is the part that tells a
      reader whether non-numeric claims are being found at all.
    * A language read that does not use the trigger rules at all: the share of tokens
      that are common English function words, and the share of the document's letters
      that are Latin script. The second catches a document in another script that
      happens to contain an English word or two.

    Below SENTENCES_FOR_LANGUAGE_CHECK sentences a trigger share proves nothing, so the
    language read decides between two outcomes the single exemption used to conflate:
    "clearly another language", which fails, and "too short to tell", which stays
    not_applicable.
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
    evidence = _language_evidence(document)
    language_observed = _language_observed(evidence)
    if total < SENTENCES_FOR_LANGUAGE_CHECK:
        if _clearly_another_language(evidence):
            return _record(
                "TRIGGER_LANGUAGE_UNSUPPORTED",
                "failed",
                "%d narrative sentence(s); %s" % (total, language_observed),
                "the document is in another language rather than too short to judge: "
                "%s. The signals are English-specific, so it would be reported as a "
                "document with nothing to check." % language_observed,
                "grade an English version, or treat the report's coverage figures as not "
                "applicable to this document",
            )
        return _record(
            "TRIGGER_LANGUAGE_UNSUPPORTED",
            "not_applicable",
            "%d narrative sentence(s); %s" % (total, language_observed),
            "too short to distinguish a wrong-language document from a document with "
            "few claims",
        )
    triggered = sum(1 for verdict in verdicts if verdict.requires_citation)
    share = triggered / total
    observed = "%d of %d sentence(s) = %.1f%%; language-dependent signals: %s; %s" % (
        triggered,
        total,
        share * 100,
        ", ".join(style_fired) if style_fired else "none",
        language_observed,
    )
    english = _looks_english(evidence)
    if share < MIN_TRIGGER_YIELD or not english:
        if not english:
            detail = (
                "the document does not read as English: %s. A bare digit fires "
                "STATISTIC in any language, so the trigger share alone does not prove "
                "the document was read. The signals are English-specific, so this is "
                "what a non-English document looks like -- and it would be reported as "
                "a document with nothing to check." % language_observed
            )
        else:
            detail = (
                "almost no sentence matched any attribution signal. The signals are "
                "English-specific, so this is what a non-English document looks like -- "
                "and it would be reported as a document with nothing to check."
            )
        return _record(
            "TRIGGER_LANGUAGE_UNSUPPORTED",
            "failed",
            observed,
            detail + extra,
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
