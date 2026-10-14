"""The defined "plagiarism-free" claim, computed from one citation-report run.

The definition itself lives in ``tools/attribution.py``, shared with the originality
toolkit and the review gate, so the three consumers cannot drift apart in what they
claim. This module holds the one mapping from a report's own states to the facts that
definition needs, so ``report.py`` and ``report_gate.py`` cannot disagree about
whether the statement may be issued.

The mapping, in full:

  passage_findings     sentences in `conflict` plus sentences in `unattributed`; a
                       passage that still needs the citation it lacks, or that
                       contradicts a source
  open_reviews         sentences in `unverifiable`; the tool could not decide them, so
                       a human must
  citations_unresolved unresolved citable citation tokens (the D03 sentences are the
                       sentences that carry them)
  retracted_cited      sentences that cite a retracted source (D04)
  sources_checked      the size of the source ledger
  corpus_docs          supplied sources whose text was read
  corpus_unreadable    supplied sources whose text was not read

A fact the run cannot establish is ``None``, never 0. Citation resolution and
retraction are only *checked* when the run held at least one source to check; with an
empty ledger the run verified neither, and a claim that assumes zero is the overclaim
the definition exists to stop.
"""
from __future__ import annotations

import sys
from pathlib import Path

#: The repository tools directory, four levels above this file:
#: ``<repo>/skills/citation-report/scripts/_attribution.py``.
TOOLS_DIR = Path(__file__).resolve().parents[3] / "tools"

#: Marker kinds that name a specific work. Mirrors `verdicts.CITABLE_MARKER_KINDS` plus
#: the author-year form; kept here so the recorded file's tokens can be counted without
#: importing the classifier.
CITABLE_KINDS = frozenset({"numeric", "bracket", "ledger_source", "author_year"})

BLOCK_HEADING = "Plagiarism-free — the defined claim"


def load_module():
    """Return ``tools/attribution.py``, or None when that file is absent.

    The definition is repository furniture, not skill furniture. A skill installed on
    its own does not carry ``tools/``, so the caller reports the missing definition
    instead of inventing one.
    """
    path = TOOLS_DIR / "attribution.py"
    if not path.is_file():
        return None
    if str(TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(TOOLS_DIR))
    import attribution

    return attribution


def _unresolved_tokens(graded) -> int:
    """Citable tokens that resolved to no source, across every verdict."""
    count = 0
    for verdict in graded:
        for token in getattr(verdict, "unresolved_tokens", []) or []:
            if isinstance(token, dict) and token.get("kind") in CITABLE_KINDS:
                count += 1
    return count


def facts(summary, graded) -> dict:
    """The seven facts, from a coverage summary and the graded verdicts."""
    summary = summary or {}
    states = summary.get("states") or {}
    rules = summary.get("rules") or {}
    sources = summary.get("sources") or {}
    total = int(sources.get("total") or 0)
    with_evidence = int(sources.get("with_evidence") or 0)
    checked = total > 0
    unresolved = _unresolved_tokens(graded)
    return {
        "passage_findings": int(states.get("conflict") or 0)
        + int(states.get("unattributed") or 0),
        "open_reviews": int(states.get("unverifiable") or 0),
        # D03 sentences are exactly the sentences that carry an unresolved citable
        # token, so the two counts describe one phenomenon. The larger of the two is
        # the honest count: it never double-counts, and it cannot miss a D03 sentence
        # whose token the record kept in a shape this module does not read.
        "citations_unresolved": max(unresolved, int(rules.get("D03") or 0)) if checked else None,
        "retracted_cited": int(rules.get("D04") or 0) if checked else None,
        "sources_checked": total,
        "corpus_docs": with_evidence,
        "corpus_unreadable": max(total - with_evidence, 0),
    }


def build(summary, graded):
    """Return ``{available, facts, result}`` for one run.

    ``result`` is the dict ``tools/attribution.py`` returns; ``available`` is False
    when that module is not installed, in which case no statement may be issued.
    """
    module = load_module()
    if module is None:
        return {
            "available": False,
            "facts": None,
            "result": None,
            "reason": "tools/attribution.py is not installed beside the skill, so the "
            "defined claim cannot be evaluated",
        }
    values = facts(summary, graded)
    # Name THIS tool's flags in the blocker text: the shared module's neutral
    # default exists because each consumer supplies its evidence differently.
    return {"available": True, "facts": values,
            "result": module.evaluate(**values,
                                      evidence_hint="supply --sources, --bib or --dois")}


def record(built) -> dict:
    """The object ``verdicts.json`` stores, and the gate recomputes.

    Every field the statement rests on is recorded, so a reader of the file can see
    the facts and not only the conclusion.
    """
    if not built.get("available"):
        return {"available": False, "reason": built.get("reason")}
    module = load_module()
    result = built["result"]
    return {
        "available": True,
        "issuable": bool(result["issuable"]),
        "statement": result["statement"],
        "scope": result["scope"],
        "blockers": list(result["blockers"]),
        "facts": dict(built["facts"]),
        "definition": list(module.DEFINITION) if module else [],
    }


def artifact_block(built) -> dict:
    """What each renderer prints: heading, definition, statement, scope.

    The scope travels with the term in both directions. A withheld statement names
    its blockers and the scope is printed beside it, because the term must never
    appear without its boundary -- that is the rule the shared definition encodes.
    """
    if not built.get("available"):
        return {}
    module = load_module()
    result = built["result"]
    return {
        "heading": BLOCK_HEADING,
        "definition": list(module.DEFINITION) if module else [],
        "statement": result["statement"],
        "scope": result["scope"],
        "issuable": bool(result["issuable"]),
        "blockers": list(result["blockers"]),
    }


def markdown(built) -> str:
    """The block as Markdown, for a text artifact and for the honesty scan.

    The rendered block is the shared one, plus the scope line when the shared renderer
    omits it (a withheld statement does not carry the scope itself).
    """
    if not built.get("available"):
        return ""
    module = load_module()
    if module is None:
        return ""
    block = module.render_block(built["result"])
    if "Scope:" not in block:
        block += "\n\n**%s**" % built["result"]["scope"]
    return block


def anchors(module) -> tuple:
    """The three anchors ``tools/claim_guard.py`` requires, from the shared definition."""
    return (module.DEFINITION_ANCHOR, module.SCOPE_ANCHOR, module.EXCEPTION_ANCHOR)


def markdown_from_record(stored) -> str:
    """The block text from the recorded ``attribution`` object, or ''."""
    if not stored or not stored.get("available"):
        return ""
    lines = list(stored.get("definition") or [])
    lines += ["", "**%s**" % stored.get("statement", "")]
    if "Scope:" not in (stored.get("statement") or ""):
        lines += ["", "**%s**" % stored.get("scope", "")]
    return "\n".join(lines)
