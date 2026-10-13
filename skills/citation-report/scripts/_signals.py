"""Deterministic signal detection: what a sentence asserts, and what evidence
would have to contain for the sentence to be traceable.

Two jobs:

1. ``citation_triggers`` — decide whether a sentence states something that needs
   attribution at all. Every trigger records *why* it fired, so the report can
   show its own reasoning and a benchmark can measure whether the reasoning is
   any good. This is the difference between an auditable rule and a black box.

2. ``extract_quantities`` / ``evidence_numbers`` — pull the numbers out of a
   sentence and out of a source's evidence text so they can be compared. The
   comparison is deliberately conservative: a number that is merely *not found*
   in the evidence is never treated as a contradiction, because extracted text is
   lossy. Only a number that is present for the same named measure but carries a
   different value is a contradiction.

No third-party packages. No model. Pure functions over text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Trigger: does this sentence need attribution?
# --------------------------------------------------------------------------- #

#: Fired when the sentence carries a statistic, measurement or date.
TRIGGER_STATISTIC = "STATISTIC"
#: Fired on a superlative or priority claim ("the first", "the largest").
TRIGGER_SUPERLATIVE = "SUPERLATIVE"
#: Fired on attribution to nobody in particular ("studies show").
TRIGGER_VAGUE_ATTRIBUTION = "VAGUE_ATTRIBUTION"
#: Fired on a borrowed definition, which is another author's formulation.
TRIGGER_DEFINITION = "DEFINITION"
#: Fired when a citable marker matches no source in a closed reference apparatus. The
#: author asserted a source, and the assertion does not hold, so the sentence needs the
#: citation it lacks. The classifier records this one, because it is the only code that
#: can see the markers: `citation_triggers` runs on the sentence text without them.
TRIGGER_UNRESOLVED_CITATION = "UNRESOLVED_CITATION"

TRIGGER_CODES = (
    TRIGGER_STATISTIC,
    TRIGGER_SUPERLATIVE,
    TRIGGER_VAGUE_ATTRIBUTION,
    TRIGGER_DEFINITION,
    TRIGGER_UNRESOLVED_CITATION,
)

#: A numbered label: `ICD-11`, `DSM-5`, `PCL-5`, `COVID-19`, `SARS-CoV-2`. The digits
#: name a version or a scale, not a measured quantity, so they must not count as a
#: statistic. Measured on a real review, these tokens were firing STATISTIC constantly.
VERSION_LABEL_RE = re.compile(r"\b[A-Za-z]{2,}(?:[-\u2013][A-Za-z0-9]+)*[-\u2013][0-9]{1,3}\b")


def mask_version_labels(text: str) -> str:
    """Replace the digits of a numbered label with spaces, preserving every offset.

    Offsets must not move: a quantity's span is used to quote the sentence. Replacing
    the digits with an equal number of spaces keeps the string the same length while
    stopping the number patterns from seeing them.
    """
    pieces: list = []
    cursor = 0
    for match in VERSION_LABEL_RE.finditer(text or ""):
        pieces.append(text[cursor:match.start()])
        pieces.append(re.sub(r"[0-9]", " ", match.group(0)))
        cursor = match.end()
    pieces.append(text[cursor:])
    return "".join(pieces)


#: A structural reference, not a measurement: "Figure 2", "Table 3", "phase 2", "type 2".
STRUCTURAL_RE = re.compile(
    r"\b(?:fig(?:ure)?s?|tab(?:le)?s?|appendix|section|chapter|equation|eq|step|phase|"
    r"stage|grade|type|class|version|scale|item|question|wave|round|group|arm|site|"
    r"batch|model|session|visit|part|level)s?[.\s-]*[0-9]{1,3}\b",
    re.IGNORECASE,
)

#: A bare integer below this, with no decimal part, is treated as context rather than a
#: measured value. Small integers are everywhere in extracted text -- page numbers, list
#: numbers, ages, "9 of 12", a protein name like "metalloproteinase 9" -- so finding one
#: proves nothing and finding none proves nothing. Measured on a real document, this was
#: the mechanism behind every false green the report produced: 11 of 12 `attributed`
#: verdicts rested on the digits of `ICD-11` or `DSM-5`, and the twelfth on a protein name.
MIN_DISTINCTIVE_INTEGER = 20


def is_checkable_value(kind: str, values: list) -> bool:
    """Whether a quantity is distinctive enough that finding it means something.

    A value carrying its own context -- a percentage, a `p` value, an `HR`, a fraction,
    an `n =`, a unit, a duration -- is checkable. A bare number is checkable only when it
    is large or fractional enough to be a real measurement rather than a label, an index
    or a name.
    """
    if kind in ("confidence_interval", "year"):
        return False
    if kind != "number":
        return True
    if not values:
        return False
    return any(
        abs(value) >= MIN_DISTINCTIVE_INTEGER or abs(value - int(value)) > 1e-9
        for value in values
    )


SUPERLATIVE_RE = re.compile(
    r"\b(?:"
    r"the\s+(?:first|second|third|largest|smallest|biggest|highest|lowest|best|"
    r"worst|greatest|only|most\s+\w+|least\s+\w+)\b"
    r"|(?:largest|smallest|biggest|highest|lowest|greatest)\s+\w+"
    r"|most\s+(?:common|commonest|frequent|prevalent|widely|important|significant|often)"
    r"|majority\s+of|predominant|unprecedented"
    r"|widely\s+(?:acknowledged|accepted|used|regarded|reported)"
    r"|first[-\s]line|gold\s+standard"
    r"|(?:is|are|was|were)\s+(?:the\s+)?(?:standard|central|primary|principal)\s+\w+"
    r")",
    re.IGNORECASE,
)

VAGUE_ATTRIBUTION_RE = re.compile(
    r"\b(?:studies\s+(?:show|suggest|indicate|demonstrate|have\s+shown|report)|"
    r"research\s+(?:shows|suggests|indicates|has\s+shown|demonstrates)|"
    r"evidence\s+(?:shows|suggests|indicates|supports)|"
    r"experts\s+(?:agree|believe|say|suggest)|"
    r"(?:it|this)\s+(?:is|has\s+been)\s+(?:shown|demonstrated|established|reported|"
    r"suggested|documented|well\s+established|widely\s+accepted|known)|"
    r"has\s+been\s+(?:shown|demonstrated|established|reported|suggested|documented)|"
    r"have\s+been\s+(?:shown|demonstrated|established|reported)|"
    r"is\s+(?:generally|widely|commonly)\s+(?:accepted|recognised|recognized|"
    r"regarded|considered|believed)|"
    r"according\s+to\s+(?:some|many|several|various)|"
    r"several\s+studies|many\s+studies|previous\s+(?:studies|work|research)|"
    r"the\s+literature\s+(?:shows|suggests|indicates)|"
    r"provides?\s+(?:detailed\s+|strong\s+|further\s+|new\s+|the\s+)?evidence\s+"
    r"(?:on|for|that|of)|"
    r"there\s+is\s+(?:growing|increasing|considerable|substantial)\s+evidence"
    # A named body of evidence plus a reporting verb. The old list required an exact
    # phrase ("studies show"), so "research has documented", "investigations describe"
    # and "observations indicate" were all missed -- 21 of 30 misses on a 40-sentence
    # sample of unseen real prose, measured by benchmarks/bench_verdicts.py.
    r"|(?:studies|research|investigations|trials|models|evidence|data|findings|"
    r"observations|analyses|cohorts|samples|authors|instruments|study)"
    # Up to four lowercase words may separate the noun from its verb, so a qualifying
    # phrase does not hide the claim. Capped, so the subject cannot drift to another clause.
    r"(?:\s+[a-z][\w'\u2019()-]*){0,4}\s+"
    # An auxiliary may sit between the noun and the verb: "research has documented".
    r"(?:(?:has|have|had|is|are|was|were)\s+)?(?:\w+ly\s+)?"
    r"(?:show|shows|report|reports|reported|document|documents|documented|describe|"
    r"describes|provide|provides|provided|indicate|indicates|indicated|find|finds|"
    r"found|suggest|suggests|suggested|demonstrate|demonstrates|demonstrated|reveal|"
    r"reveals|revealed|confirm|confirms|confirmed|support|supports|supported|"
    r"position|positions|operationalise|operationalises|operationalised|group|groups|"
    r"grouped|evaluated|interpret|interprets)\b"
    # Passive attribution: someone else's formulation, stated as such.
    r"|(?:is|are|was|were)\s+(?:\w+ly\s+)?(?:described|reported|acknowledged|"
    r"positioned|interpreted|operationalised|operationalized|referred|evaluated)\s+"
    r"(?:as|by|with|using|via|through)\b"
    r"|according\s+to\s+(?:its|their|the\s+authors|one|previous|earlier|original|"
    r"several|various|some|many))\b",
    re.IGNORECASE,
)

#: Association, causation and requirement. These assert a relationship rather than a
#: description, so a source is owed for them. `produce`/`produced` is deliberately
#: absent: "might have produced" is the author's own hedged inference, and including it
#: was measured to cost a true negative on real prose.
ASSOCIATION_RE = re.compile(
    r"\b(?:associated\s+with|correlates?\s+(?:with|negatively|positively)|"
    r"correlated\s+with|related\s+to|predicts?|predicted|prevent|prevents|prevented|"
    r"reduces|reduced|increases|increased|improves|improved|causes?|caused|"
    r"leads?\s+to|led\s+to|results?\s+in|resulted\s+in|requires?|required|"
    r"mediate[sd]?|moderates?|moderated)\b",
    re.IGNORECASE,
)

#: A statistical noun carrying a quantity, even when the digits did not survive
#: extraction. On the real sample several sentences had lost their figures, so the
#: number patterns saw nothing while the sentence still asserted a measured result.
STATISTICAL_NOUN_RE = re.compile(
    r"\b(?:prevalence|incidence|proportion|percentages?|rates?|scores?|odds|risk)\s+"
    r"(?:of|was|were|is|are|as|ranged|range|reached|reaches|higher|lower|greater|"
    r"increased|decreased|rose|fell)\b",
    re.IGNORECASE,
)

#: A hedge that only ever precedes a quantity.
APPROXIMATION_RE = re.compile(r"\b(?:approximately|roughly|nearly|circa)\b", re.IGNORECASE)


DEFINITION_RE = re.compile(
    r"\b(?:is|are|was|were)\s+(?:defined|characterised|characterized|described|"
    r"known|referred\s+to|understood|conceptualised|conceptualized|"
    r"operationalised|operationalized)\s+(?:as|by)\b"
    r"|\brefers?\s+to\b"
    r"|\bis\s+the\s+term\s+(?:for|used)\b"
    r"|\b(?:is|are)\s+called\b",
    re.IGNORECASE,
)

# --------------------------------------------------------------------------- #
# Quantities
# --------------------------------------------------------------------------- #

MEASURE = (
    r"(?:a?HR|a?OR|a?RR|IRR|SMD|MD|WMD|RD|aRD|beta|\u03b2|HR|OR|RR|PR|"
    r"hazard\s+ratio|odds\s+ratio|risk\s+ratio|relative\s+risk|prevalence\s+ratio|"
    r"rate\s+ratio|incidence\s+rate\s+ratio|standardised\s+mean\s+difference|"
    r"mean\s+difference|risk\s+difference)"
)

NUMBER = r"[0-9]+(?:[.,][0-9]+)?"

#: A measure value may carry a sign: "beta = -0.22", "MD \u22120.4" (a Unicode minus), "SMD +0.3".
#: The sign must be glued to the digits, so a dash used as a separator ("risk difference \u2013 0.05")
#: is not read as a negative -- the value is missed rather than inverted, which is the safer error.
SIGNED_NUMBER = r"[-+\u2212\u2013]?[0-9]+(?:[.,][0-9]+)?"

PERCENT_RE = re.compile(r"(?<![\w.])(" + NUMBER + r")\s?(?:%|\u2030|\bpercent\b|\bper\s?cent\b)", re.IGNORECASE)
P_VALUE_RE = re.compile(r"\bp\s*([<>=]|\u2264|\u2265)\s*(" + NUMBER + r")", re.IGNORECASE)

#: The separator between a measure label and its value, as papers actually write it: `OR 1.42`,
#: `OR: 1.42`, `OR=1.42`, `aOR, 3.15`, `(OR) = 2.15`, `( OR ) 2.15`, `risk ratio (RR) 1.42`. The
#: optional `)` covers a label the authors parenthesised; a `(` is deliberately not consumed, so
#: `OR (95% CI 1.2 to 3.4)` is not read as an odds ratio of 95.
MEASURE_RE = re.compile(
    r"\b(" + MEASURE + r")\b\s*\)?\s*[:=,]?\s*(" + SIGNED_NUMBER + r")", re.IGNORECASE
)

#: Short measure labels that are also ordinary English words or word-fragments. `OR` is the
#: conjunction "or"; `MD` is a degree or a state abbreviation; `HR`/`RD`/`PR` are two letters
#: that occur inside other tokens. Papers write all of these in upper case, so a lower-case
#: match on the original text is read as the word rather than the statistic.
#:
#: This is a false-accusation guard, not a precision tweak. Measured before the guard: the
#: sentence "Treatment continued for 6 or 12 weeks at the clinician's discretion [src:S006]."
#: -- cited against a source recording `OR 1.42` -- was reported as a **conflict**, i.e. the
#: tool accused the author of contradicting a source using the word "or" and the number 12.
#: "Variables OR 95% CI" (a table header) and "Fort Detrick MD 21702" (a place and a ZIP)
#: parsed as measures for the same reason. The long forms (hazard ratio, odds ratio, ...) and
#: `beta` are unaffected: `beta 0.67` is the normal spelling of a regression coefficient.
CASE_SENSITIVE_MEASURES = {"OR", "MD", "HR", "RR", "PR", "RD", "IRR", "SMD", "WMD"}

#: Long and short spellings of the SAME effect measure. A sentence may write "relative risk"
#: where the source's ledger recorded "RR"; they are the same statistic, and treating them as
#: different lost two of the ten contradictions in the real-source benchmark set -- a false
#: negative rather than an accusation, but still a contradiction the gate existed to catch.
#:
#: Deliberately NOT included: `aHR`/`aOR` and their unadjusted forms. Those are genuinely
#: different statistics, and conflating them would be a way to manufacture an accusation.
MEASURE_CANON = {
    "RELATIVERISK": "RR",
    "RISKRATIO": "RR",
    "HAZARDRATIO": "HR",
    "ODDSRATIO": "OR",
    "PREVALENCERATIO": "PR",
    "RATERATIO": "IRR",
    "INCIDENCERATERATIO": "IRR",
    "STANDARDISEDMEANDIFFERENCE": "SMD",
    "STANDARDIZEDMEANDIFFERENCE": "SMD",
    "MEANDIFFERENCE": "MD",
    "RISKDIFFERENCE": "RD",
}


def canonical_measure(label: str) -> str:
    """Reduce a measure label to one spelling, so both sides of a comparison agree.

    Run on the sentence side and on the evidence side, so "relative risk" in a sentence and
    "RR" in a ledger row are recognised as the same measure. Input is whatever the regex
    captured: any case, spaces allowed.
    """
    key = (label or "").upper().replace(" ", "")
    return MEASURE_CANON.get(key, key)

#: No effect measure reaches this magnitude, so anything larger is an identifier that happens to
#: follow a short label (`MD 21702` is a ZIP code in an address). Rejecting it costs nothing that
#: was ever a statistic; accepting it costs a false accusation.
MAX_PLAUSIBLE_MEASURE = 1000.0


def _measure_label_case_ok(raw_label: str) -> bool:
    """True when a measure label may be read as a statistic given how it was written.

    A leading `a` is allowed to be lower case, because `aOR`/`aHR` (adjusted) are written that
    way in real papers; the core label must then be upper case.
    """
    core = raw_label[1:] if raw_label[:1] in ("a", "A") and len(raw_label) > 1 else raw_label
    if core.upper() not in CASE_SENSITIVE_MEASURES:
        return True
    return core == core.upper()
CI_RE = re.compile(r"\b(?:95|90|99)\s?%\s*(?:CI|confidence\s+interval)", re.IGNORECASE)
FRACTION_RE = re.compile(r"\b(" + NUMBER + r")\s*/\s*(" + NUMBER + r")\b")
COUNT_RE = re.compile(r"\bn\s*=\s*(" + NUMBER + r")", re.IGNORECASE)
RANGE_RE = re.compile(
    r"(?<![\w.])(" + NUMBER + r")\s*(?:\u2013|\u2014|-|to|and)\s*(" + NUMBER + r")\s?(%|\u2030)",
    re.IGNORECASE,
)
UNIT_RE = re.compile(
    r"(?<![\w.])(" + NUMBER + r")\s?"
    r"(mg|mcg|\u00b5g|ug|kg|g|mL|ml|L|dL|cL|mmol|\u00b5mol|umol|IU|units?|"
    r"mg/kg|mg/dL|mmol/L|mEq/L|bpm|mmHg|cm|mm|km|m)\b",
    re.IGNORECASE,
)
DURATION_RE = re.compile(
    r"(?<![\w.])(" + NUMBER + r")\s?(months?|weeks?|days?|years?|hours?|minutes?|"
    r"hrs?|mins?|sessions?)\b",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"\b(1[6-9][0-9]{2}|20[0-9]{2})\b")
NUMBER_RE = re.compile(r"(?<![\w.])([0-9]+(?:[.,][0-9]+)?)")

QUANTITY_KINDS = (
    "percent",
    "p_value",
    "measure",
    "confidence_interval",
    "fraction",
    "count",
    "range",
    "unit",
    "duration",
    "year",
    "number",
)


@dataclass
class Quantity:
    """One numeric assertion, with enough context to look for it in evidence."""

    kind: str
    raw: str
    values: list = field(default_factory=list)
    measure: str = ""
    unit: str = ""
    start: int = 0
    end: int = 0
    #: Whether this value is distinctive enough to test against evidence; see
    #: `is_checkable_value`. Recorded on every quantity, so a reader can see which values a
    #: verdict actually rested on and which were only context.
    checkable: bool = True

    def to_dict(self) -> dict:
        payload = {
            "kind": self.kind,
            "raw": self.raw,
            "values": list(self.values),
            "checkable": self.checkable,
            "start": self.start,
            "end": self.end,
        }
        if self.measure:
            payload["measure"] = self.measure
        if self.unit:
            payload["unit"] = self.unit
        return payload


def _to_float(token: str) -> float | None:
    """Parse a numeric token. Handles `1,730` (thousands), `0,49` (decimal comma) and signs.

    A Unicode minus (`\u2212`) and an en dash are normalised to an ASCII hyphen first: papers
    set a negative estimate with a typographic minus, and `float()` rejects it, so the value
    would be silently dropped rather than read as negative.
    """
    token = token.strip()
    if not token:
        return None
    token = token.replace("\u2212", "-").replace("\u2013", "-")
    if "," in token and "." in token:
        token = token.replace(",", "")
    elif "," in token:
        left, _, right = token.partition(",")
        # `1,730` is thousands; `0,49` is a decimal comma.
        if len(right) == 3 and left:
            token = left + right
        else:
            token = left + "." + right
    try:
        return float(token)
    except ValueError:
        return None


def _add(quantities: list, occupied: list, quantity: Quantity) -> None:
    """Record a quantity unless an earlier, more specific match owns its span."""
    for begin, end in occupied:
        if quantity.start < end and begin < quantity.end:
            return
    occupied.append((quantity.start, quantity.end))
    quantities.append(quantity)


def extract_quantities(text: str) -> list:
    """Return every numeric assertion in `text`, most specific pattern first.

    Ordering matters: `HR 0.49` must be read as one measure, not as two loose
    numbers, and `9` in `9-90%` must not become a bare number as well.

    Digits belonging to a numbered label (`ICD-11`, `DSM-5`) are masked first: they
    name a version rather than measure anything, and treating them as statistics made
    the report flag sentences for stating a figure they never stated.
    """
    text = mask_version_labels(text)
    # A structural reference is a pointer, not a measurement, so its digits are masked too.
    text = STRUCTURAL_RE.sub(lambda m: re.sub(r"[0-9]", " ", m.group(0)), text)
    quantities: list = []
    occupied: list = []

    for match in P_VALUE_RE.finditer(text):
        _add(
            quantities,
            occupied,
            Quantity(
                kind="p_value",
                raw=match.group(0),
                values=[value for value in [_to_float(match.group(2))] if value is not None],
                measure="p" + match.group(1),
                start=match.start(),
                end=match.end(),
            ),
        )

    for match in MEASURE_RE.finditer(text):
        value = _to_float(match.group(2))
        if value is None:
            continue
        if not _measure_label_case_ok(match.group(1)):
            # The label is the English word, not the statistic. See _measure_label_case_ok:
            # the conjunction "or" in "6 or 12 weeks" was convicting a contradiction.
            continue
        if text[match.end():match.end() + 1] == "%":
            # "Variables OR 95% CI" is a table header, not an odds ratio of 95: a number
            # immediately followed by a percent sign is a percentage. In a real measure the
            # value comes first and its interval follows in brackets ("OR 1.42 (95% CI ...)").
            continue
        if abs(value) >= MAX_PLAUSIBLE_MEASURE:
            # No effect measure is this large, so a five-digit integer after a short label is
            # an identifier rather than a result: "Fort Detrick MD 21702" is a place and a ZIP.
            continue
        _add(
            quantities,
            occupied,
            Quantity(
                kind="measure",
                raw=match.group(0),
                values=[value],
                measure=canonical_measure(match.group(1)),
                start=match.start(),
                end=match.end(),
            ),
        )

    for match in RANGE_RE.finditer(text):
        low, high = _to_float(match.group(1)), _to_float(match.group(2))
        if low is None or high is None:
            continue
        _add(
            quantities,
            occupied,
            Quantity(
                kind="range",
                raw=match.group(0),
                values=[low, high],
                unit=match.group(3),
                start=match.start(),
                end=match.end(),
            ),
        )

    for match in CI_RE.finditer(text):
        _add(
            quantities,
            occupied,
            Quantity(
                kind="confidence_interval",
                raw=match.group(0),
                values=[],
                measure="CI",
                start=match.start(),
                end=match.end(),
            ),
        )

    for match in PERCENT_RE.finditer(text):
        value = _to_float(match.group(1))
        if value is None:
            continue
        _add(
            quantities,
            occupied,
            Quantity(
                kind="percent",
                raw=match.group(0),
                values=[value],
                unit="%",
                start=match.start(),
                end=match.end(),
            ),
        )

    for match in FRACTION_RE.finditer(text):
        numerator, denominator = _to_float(match.group(1)), _to_float(match.group(2))
        if numerator is None or denominator is None:
            continue
        _add(
            quantities,
            occupied,
            Quantity(
                kind="fraction",
                raw=match.group(0),
                values=[numerator, denominator],
                start=match.start(),
                end=match.end(),
            ),
        )

    for match in COUNT_RE.finditer(text):
        value = _to_float(match.group(1))
        if value is None:
            continue
        _add(
            quantities,
            occupied,
            Quantity(
                kind="count",
                raw=match.group(0),
                values=[value],
                measure="N",
                start=match.start(),
                end=match.end(),
            ),
        )

    for match in UNIT_RE.finditer(text):
        value = _to_float(match.group(1))
        if value is None:
            continue
        _add(
            quantities,
            occupied,
            Quantity(
                kind="unit",
                raw=match.group(0),
                values=[value],
                unit=match.group(2),
                start=match.start(),
                end=match.end(),
            ),
        )

    for match in DURATION_RE.finditer(text):
        value = _to_float(match.group(1))
        if value is None:
            continue
        _add(
            quantities,
            occupied,
            Quantity(
                kind="duration",
                raw=match.group(0),
                values=[value],
                unit=match.group(2),
                start=match.start(),
                end=match.end(),
            ),
        )

    for match in YEAR_RE.finditer(text):
        value = _to_float(match.group(1))
        if value is None:
            continue
        _add(
            quantities,
            occupied,
            Quantity(
                kind="year",
                raw=match.group(0),
                values=[value],
                start=match.start(),
                end=match.end(),
            ),
        )

    for match in NUMBER_RE.finditer(text):
        value = _to_float(match.group(1))
        if value is None:
            continue
        _add(
            quantities,
            occupied,
            Quantity(
                kind="number",
                raw=match.group(0),
                values=[value],
                start=match.start(),
                end=match.end(),
            ),
        )

    for quantity in quantities:
        quantity.checkable = is_checkable_value(quantity.kind, quantity.values)
    quantities.sort(key=lambda quantity: quantity.start)
    return quantities


def values_equal(left: float, right: float) -> bool:
    """Numeric equality tolerant of float formatting, strict about magnitude."""
    return abs(left - right) <= 1e-6 * max(1.0, abs(right))


def evidence_numbers(text: str) -> list:
    """Every number appearing in a source's evidence text, as floats."""
    values: list = []
    for match in NUMBER_RE.finditer(text or ""):
        value = _to_float(match.group(1))
        if value is not None:
            values.append(value)
    for match in PERCENT_RE.finditer(text or ""):
        value = _to_float(match.group(1))
        if value is not None:
            values.append(value)
    return values


def value_in_evidence(value: float, numbers: list) -> bool:
    return any(values_equal(value, candidate) for candidate in numbers)


def citation_triggers(text: str) -> list:
    """Return the reasons `text` needs attribution, each with its matched span."""
    triggers: list = []
    if extract_quantities(text):
        triggers.append((TRIGGER_STATISTIC, "", 0, 0))
    for match in SUPERLATIVE_RE.finditer(text):
        triggers.append((TRIGGER_SUPERLATIVE, match.group(0), match.start(), match.end()))
    for match in VAGUE_ATTRIBUTION_RE.finditer(text):
        triggers.append((TRIGGER_VAGUE_ATTRIBUTION, match.group(0), match.start(), match.end()))
    for match in DEFINITION_RE.finditer(text):
        triggers.append((TRIGGER_DEFINITION, match.group(0), match.start(), match.end()))
    for match in ASSOCIATION_RE.finditer(text):
        triggers.append((TRIGGER_STATISTIC, match.group(0), match.start(), match.end()))
    for match in STATISTICAL_NOUN_RE.finditer(text):
        triggers.append((TRIGGER_STATISTIC, match.group(0), match.start(), match.end()))
    if APPROXIMATION_RE.search(text):
        match = APPROXIMATION_RE.search(text)
        triggers.append((TRIGGER_STATISTIC, match.group(0), match.start(), match.end()))

    deduped: list = []
    seen: set = set()
    for code, raw, start, end in triggers:
        key = (code, raw.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"code": code, "match": raw, "start": start, "end": end})
    return deduped


def requires_citation(text: str) -> bool:
    return bool(citation_triggers(text))


def content_words(text: str) -> list:
    """Lowercase content words, used only for overlap scoring between a sentence
    and a source's recorded finding. Never used to assert support on its own."""
    words = re.findall(r"[a-z][a-z0-9\-]{3,}", (text or "").lower())
    return [word for word in words if word not in STOPWORDS]


STOPWORDS = frozenset(
    """
    that this these those with from were have has been being was are will would could
    should their there they them then than when where which while who whom whose what
    into over under between among during about after before because however therefore
    also such more most less least very much many some each both other others only
    both same different between through using used use can may might must not
    """.split()
)
