"""Coverage arithmetic. Every number printed is a count of something, with its
denominator attached, and the module refuses to emit a summary that does not add up.

The reference report prints "Citation Coverage: 50%" and "Citation Quality Score:
97.5%" without saying what either is. A number a reader cannot recompute is not a
measurement, it is decoration. Here:

* ``citation_coverage`` = (attributed + synthesis) / (sentences needing citation),
  printed as ``n/N`` as well as a ratio;
* the state distribution is printed over *all* graded sentences, so the reader can
  see what the ratio left out;
* ``unverifiable`` is reported separately and never folded into either side, because
  "we could not check" is not the same as "supported" or "unsupported".

There is deliberately no single scalar "quality score". If one is wanted it has to
be defined, and the honest definition is the ``attributed`` share over all graded
sentences — which is printed here under that name.
"""

from __future__ import annotations

import _common


def compute(verdicts, bundle) -> dict:
    """Summarise a verdict list. Raises if the arithmetic does not balance."""
    total = len(verdicts)
    state_counts = {state: 0 for state in _common.VERDICT_STATES}
    rule_counts: dict = {}
    severity_counts = {"error": 0, "warning": 0, "info": 0}

    for verdict in verdicts:
        if verdict.state not in _common.VERDICT_STATE_SET:
            raise _common.InputError("unknown verdict state: %r" % verdict.state)
        state_counts[verdict.state] += 1
        rule_counts[verdict.rule_id] = rule_counts.get(verdict.rule_id, 0) + 1
        if verdict.severity not in severity_counts:
            raise _common.InputError("unknown severity: %r" % verdict.severity)
        severity_counts[verdict.severity] += 1

    requiring = sum(1 for verdict in verdicts if verdict.requires_citation)
    attributed = state_counts["attributed"]
    synthesis = state_counts["synthesis"]
    covered = attributed + synthesis
    unverifiable = state_counts["unverifiable"]

    # The denominator is every sentence that carries a claim needing support: that is
    # every sentence the report had something to say about, i.e. all but
    # `no_citation_needed`. Using the trigger count instead would be wrong in one
    # direction: a cited sentence with no statistic in it (a synthesis sentence) has a
    # citation but fires no trigger, so it would sit in the numerator while being
    # excluded from the denominator. With this definition the numerator is always a
    # subset of the denominator, and the ratio can never exceed 100%.
    claiming = total - state_counts["no_citation_needed"]

    if claiming:
        ratio = covered / claiming
    else:
        ratio = 0.0

    summary = {
        "sentences_total": total,
        "sentences_requiring_citation": requiring,
        "sentences_with_support_claim": claiming,
        "sentences_not_requiring": total - requiring,
        "states": state_counts,
        "rules": rule_counts,
        "severity": severity_counts,
        # A green backed by the source's own text and a green backed by a ledger's
        # prose look identical in the state counts, so the strength is counted too.
        "attributed_by_strength": _count_by(verdicts, "attributed", "evidence_strength"),
        "uncheckable_by_reason": _count_by(verdicts, "unverifiable", "rule_id"),
        "conflict_link_confidence": _count_by(verdicts, "conflict", "link_confidence"),
        "citation_coverage": {
            "numerator": covered,
            "denominator": claiming,
            "ratio": round(ratio, 4),
            "percent": round(ratio * 100, 1),
            "definition": "(attributed + synthesis) / all sentences carrying a claim",
            "excluded_from_denominator": state_counts["no_citation_needed"],
        },
        "attributed_share_of_all_sentences": {
            "numerator": attributed,
            "denominator": total,
            "ratio": round(attributed / total, 4) if total else 0.0,
            "definition": "attributed / all graded sentences; the honest single scalar",
        },
        "uncheckable": {
            "numerator": unverifiable,
            "denominator": total,
            "detail": "cited and identified, but no evidence was held to check against",
        },
        "sources": {
            "total": len(bundle.sources),
            "by_evidence": bundle.counts_by_evidence(),
            "by_retraction": bundle.counts_by_retraction(),
            "with_evidence": sum(
                1
                for source in bundle.sources
                if source.evidence_availability in ("full_text", "abstract")
            ),
            "retracted": sum(
                1 for source in bundle.sources if source.retraction_status == "retracted"
            ),
            **_source_strength_counts(bundle),
            **_citing_counts(verdicts, bundle),
        },
        "claims": {
            "registered": len(getattr(bundle, "claims", {}) or {}),
        },
    }
    validate(summary)
    return summary


def _count_by(verdicts, state: str, attribute: str) -> dict:
    counts: dict = {}
    for verdict in verdicts:
        if verdict.state != state:
            continue
        key = getattr(verdict, attribute, "") or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _source_strength_counts(bundle) -> dict:
    counts: dict = {}
    for source in getattr(bundle, "sources", []) or []:
        key = getattr(source, "evidence_strength", "none") or "none"
        counts[key] = counts.get(key, 0) + 1
    return {"by_strength": counts}


def _citing_counts(verdicts, bundle) -> dict:
    """How many of the sources the document actually cites can be checked.

    This is the input side of the report, and it is what the sufficiency policy acts
    on. It lives beside the output side so the two can never be reported without each
    other: "0 of 8 checked" must never appear without "8 sources were cited and 0
    could be read".
    """
    by_id = {source.source_id: source for source in getattr(bundle, "sources", []) or []}
    cited: set = set()
    for verdict in verdicts:
        for record in getattr(verdict, "sources", []) or []:
            source_id = record.get("source_id")
            if source_id:
                cited.add(source_id)
    known = [by_id[source_id] for source_id in cited if source_id in by_id]
    unknown = sorted(source_id for source_id in cited if source_id not in by_id)
    return {
        "citing_sources": len(cited),
        "citing_sources_checkable": sum(
            1 for source in known if getattr(source, "checkable", False)
        ),
        "citing_sources_red_capable": sum(
            1 for source in known if getattr(source, "red_capable", False)
        ),
        "citing_sources_link_verified": sum(
            1 for source in known if getattr(source, "link_verified", False)
        ),
        "citing_sources_without_evidence": sorted(
            source.source_id for source in known if not getattr(source, "checkable", False)
        ),
        "citing_sources_unknown_to_registry": unknown,
    }


def validate(summary: dict) -> None:
    """Fail if any printed total disagrees with its parts."""
    states = summary["states"]
    state_total = sum(states.values())
    if state_total != summary["sentences_total"]:
        raise _common.InputError(
            "state counts sum to %d but %d sentences were graded"
            % (state_total, summary["sentences_total"])
        )
    if summary["sentences_requiring_citation"] + summary["sentences_not_requiring"] != summary[
        "sentences_total"
    ]:
        raise _common.InputError("requiring + not-requiring does not equal the total")
    if summary["sentences_with_support_claim"] != (
        summary["sentences_total"] - states["no_citation_needed"]
    ):
        raise _common.InputError(
            "the support-claim denominator disagrees with the no_citation_needed count"
        )

    coverage = summary["citation_coverage"]
    if coverage["numerator"] != states["attributed"] + states["synthesis"]:
        raise _common.InputError("coverage numerator disagrees with the state counts")
    if coverage["denominator"] != summary["sentences_with_support_claim"]:
        raise _common.InputError("coverage denominator disagrees with the support-claim count")
    if coverage["denominator"] and coverage["numerator"] > coverage["denominator"]:
        raise _common.InputError(
            "coverage numerator exceeds its denominator, which is impossible"
        )
    # The numerator must be a subset of the denominator by construction: a sentence
    # is only `no_citation_needed` when D01 fired, and D01 excludes every other state.
    if states["attributed"] + states["synthesis"] > coverage["denominator"]:
        raise _common.InputError("covered sentences fall outside the support-claim denominator")

    rules = summary["rules"]
    if sum(rules.values()) != summary["sentences_total"]:
        raise _common.InputError("rule counts do not sum to the sentence total")
    severities = summary["severity"]
    if sum(severities.values()) != summary["sentences_total"]:
        raise _common.InputError("severity counts do not sum to the sentence total")
    for rule_id in rules:
        if rule_id not in _RULES_FOR_VALIDATION:
            raise _common.InputError("unknown rule id in summary: %r" % rule_id)


def _rules_for_validation() -> set:
    # Imported lazily to avoid a circular import at module load.
    from verdicts import RULES

    return set(RULES)


_RULES_FOR_VALIDATION = _rules_for_validation()


def bar_segments(summary: dict, width: float = 20.0) -> list:
    """Stacked-bar segments as (state, x, width, share) for the renderers."""
    total = summary["sentences_total"] or 1
    segments: list = []
    cursor = 0.0
    for state in _common.VERDICT_STATES:
        count = summary["states"].get(state, 0)
        if not count:
            continue
        span = width * count / total
        segments.append((state, cursor, span, count / total))
        cursor += span
    return segments


def render_text(summary: dict) -> str:
    """A plain-text summary for the console and the text-only mode."""
    lines = [
        "Citation coverage: %d/%d = %.1f%% (%s)"
        % (
            summary["citation_coverage"]["numerator"],
            summary["citation_coverage"]["denominator"],
            summary["citation_coverage"]["percent"],
            summary["citation_coverage"]["definition"],
        ),
        "Sentences graded: %d (requiring a citation: %d)"
        % (summary["sentences_total"], summary["sentences_requiring_citation"]),
        "",
        "%-20s %6s  %s" % ("STATE", "COUNT", "SHARE"),
    ]
    total = summary["sentences_total"] or 1
    for state in _common.VERDICT_STATES:
        count = summary["states"].get(state, 0)
        lines.append("%-20s %6d  %5.1f%%" % (state, count, 100.0 * count / total))
    lines.append("")
    lines.append("Rule      Count  Meaning")
    from verdicts import RULES

    for rule_id in sorted(summary["rules"]):
        state, severity, meaning = RULES[rule_id]
        lines.append(
            "%-8s %5d  [%s/%s] %s"
            % (rule_id, summary["rules"][rule_id], state, severity, meaning)
        )
    lines.append("")
    lines.append(
        "Sources: %d total, %d with evidence, %d retracted"
        % (
            summary["sources"]["total"],
            summary["sources"]["with_evidence"],
            summary["sources"]["retracted"],
        )
    )
    lines.append("Evidence held: %s" % summary["sources"]["by_evidence"])
    return "\n".join(lines)
