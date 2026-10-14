#!/usr/bin/env python3
"""attribution.py -- the defined meaning of "plagiarism-free".

"Plagiarism-free" is not a property a program can prove. It is, however, a
property a human can define, check and sign. This module holds that definition in
one place so the three consumers (the originality toolkit, citation-report and the
sysreview manuscript gate) cannot drift apart in what they claim.

THE DEFINITION (ASD-STE100 wording, one instruction or condition per sentence)

  A passage is plagiarism-free when it meets one of these conditions:
    - It quotes another work. The quotation is marked. The source is cited.
    - It paraphrases another work. The words are new. The source is cited.
    - It states a fact that needs no citation.

  A document is plagiarism-free against the sources checked when every assessed
  passage meets one condition. Also required: no citation is unresolved, no cited
  source is retracted, and the supplied corpus was read.

  The check has limits. It reads only the sources supplied or reachable. It does
  not verify structure above the measured separation, so a paraphrase that keeps
  the source's sentence structure is not covered.

WHY THE SCOPE TRAVELS WITH THE CLAIM

A statement without its scope is the universal negative this project refuses. The
same words with the scope are a defined, auditable claim: the reader can see how
many sources were checked, how many supplied documents were read, what could not
be read, and which single case the check does not cover.

Exit codes (the repository's convention):
  0  the statement is issued
  1  the statement is withheld (at least one condition failed)
  4  input gap -- the evidence needed to decide was not supplied (never a pass)

Usage:
  python3 tools/attribution.py --facts facts.json [--json out.json]
  python3 tools/attribution.py --definition
  python3 tools/attribution.py --self-test
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TERM = "plagiarism-free (against the sources checked)"

DEFINITION = [
    "A passage is plagiarism-free when it meets one of these conditions:",
    "- It quotes another work. The quotation is marked. The source is cited.",
    "- It paraphrases another work. The words are new. The source is cited.",
    "- It states a fact that needs no citation.",
    "A document is plagiarism-free against the sources checked when every assessed passage "
    "meets one condition, no citation is unresolved, no cited source is retracted, and the "
    "supplied corpus was read.",
    "The check has limits. It reads only the sources supplied or reachable. It does not verify "
    "structure above the measured separation, so a paraphrase that keeps the source's sentence "
    "structure is not covered.",
]

# The three anchors a report must carry before it may use the term. claim_guard
# reads them: the same words without the definition, the scope and the exception
# are the universal negative this project forbids.
DEFINITION_ANCHOR = "A passage is plagiarism-free when it meets one of these conditions"
SCOPE_ANCHOR = "Scope:"
# The shared substring, so the definition sentence and the scope line cannot drift
# apart -- a consumer flagged exactly that risk. The wording of each sentence stays
# free to read naturally; this string is what the gate checks.
EXCEPTION_ANCHOR = "above the measured separation"

G4_EXCEPTION = "structure is not verified above the measured separation"


def scope_line(sources_checked, corpus_docs, corpus_unreadable):
    """The four facts, in one sentence: the boundary of the claim."""
    return ("Scope: %d source(s) checked; %d supplied document(s) read; %d document(s) could "
            "not be read; %s." % (sources_checked, corpus_docs, corpus_unreadable, G4_EXCEPTION))


def evaluate(*, passage_findings=0, open_reviews=0, citations_unresolved=None,
             retracted_cited=None, sources_checked=0, corpus_docs=0, corpus_unreadable=0,
             evidence_hint="supply the source evidence this check needs"):
    """Decide whether the statement may be issued. Return the result and the blockers.

    `citations_unresolved` and `retracted_cited` are None when the caller has no
    evidence for them. None is an input gap and blocks the statement: this tool
    cannot verify citation resolution or retraction itself, and a claim that
    silently assumes them would be the overclaim the definition exists to stop.

    `evidence_hint` names what the CALLER's user must supply. The default is
    neutral because the flag differs per consumer (the toolkit takes
    `--attribution-evidence`, citation-report takes `--sources`/`--bib`/`--dois`,
    sysreview reads its citation gate); naming one consumer's flag in a shared
    message sent users to a flag their tool does not have.
    """
    blockers = []
    if passage_findings:
        blockers.append("%d passage(s) copy or paraphrase without a marked quotation and a "
                        "citation" % passage_findings)
    if open_reviews:
        blockers.append("%d passage(s) still need a decision: cite them, or record them as "
                        "common knowledge" % open_reviews)
    if citations_unresolved is None:
        blockers.append("citation resolution was not verified (%s)" % evidence_hint)
    elif citations_unresolved:
        blockers.append("%d citation(s) do not resolve" % citations_unresolved)
    if retracted_cited is None:
        blockers.append("retracted sources were not checked (%s)" % evidence_hint)
    elif retracted_cited:
        blockers.append("%d cited source(s) are retracted" % retracted_cited)
    if corpus_unreadable:
        blockers.append("%d supplied document(s) could not be read, so the corpus was not fully "
                        "read" % corpus_unreadable)

    scope = scope_line(sources_checked, corpus_docs, corpus_unreadable)
    if blockers:
        statement = ("%s -- NOT ISSUED. %s." % (TERM, "; ".join(blockers)))
    else:
        statement = ("%s: every assessed passage quotes and cites, paraphrases in new words and "
                     "cites, or needs no citation. No citation is unresolved. No cited source is "
                     "retracted. %s" % (TERM, scope))
    return {
        "issuable": not blockers,
        "statement": statement,
        "blockers": blockers,
        "scope": scope,
    }


def render_block(result):
    """The markdown block a report carries: definition, statement, scope.

    The scope is appended when the statement does not already carry it. A WITHHELD
    statement lists blockers instead of the scope, and without this the block had
    no SCOPE_ANCHOR -- so claim_guard refused the term in a report that was doing
    the right thing by withholding it. The block must be self-contained in both
    states.
    """
    lines = ["## Plagiarism-free — the defined claim", ""]
    lines += DEFINITION
    lines.append("")
    lines.append("**%s**" % result["statement"])
    if SCOPE_ANCHOR not in result["statement"]:
        lines.append("")
        lines.append(result["scope"])
    return "\n".join(lines)


def _facts_from_file(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {k: data.get(k) for k in (
        "passage_findings", "open_reviews", "citations_unresolved", "retracted_cited",
        "sources_checked", "corpus_docs", "corpus_unreadable")}


SELF_TEST = [
    # (facts, issuable?)
    ({"passage_findings": 0, "open_reviews": 0, "citations_unresolved": 0,
      "retracted_cited": 0, "sources_checked": 5, "corpus_docs": 3,
      "corpus_unreadable": 0}, True),
    ({"passage_findings": 2, "open_reviews": 0, "citations_unresolved": 0,
      "retracted_cited": 0, "sources_checked": 5, "corpus_docs": 3,
      "corpus_unreadable": 0}, False),
    ({"passage_findings": 0, "open_reviews": 1, "citations_unresolved": 0,
      "retracted_cited": 0, "sources_checked": 5, "corpus_docs": 3,
      "corpus_unreadable": 0}, False),
    ({"passage_findings": 0, "open_reviews": 0, "citations_unresolved": None,
      "retracted_cited": 0, "sources_checked": 5, "corpus_docs": 3,
      "corpus_unreadable": 0}, False),
    ({"passage_findings": 0, "open_reviews": 0, "citations_unresolved": 0,
      "retracted_cited": None, "sources_checked": 5, "corpus_docs": 3,
      "corpus_unreadable": 0}, False),
    ({"passage_findings": 0, "open_reviews": 0, "citations_unresolved": 0,
      "retracted_cited": 1, "sources_checked": 5, "corpus_docs": 3,
      "corpus_unreadable": 0}, False),
    ({"passage_findings": 0, "open_reviews": 0, "citations_unresolved": 0,
      "retracted_cited": 0, "sources_checked": 5, "corpus_docs": 3,
      "corpus_unreadable": 1}, False),
]


def self_test():
    failures = []
    for i, (facts, expected) in enumerate(SELF_TEST):
        result = evaluate(**facts)
        if result["issuable"] != expected:
            failures.append("case %d: expected issuable=%s, got %s (%s)"
                            % (i, expected, result["issuable"], result["blockers"]))
    # The issued statement must carry the scope, and the scope must carry all four facts.
    ok = evaluate(passage_findings=0, open_reviews=0, citations_unresolved=0,
                  retracted_cited=0, sources_checked=5, corpus_docs=3, corpus_unreadable=0)
    for anchor in (SCOPE_ANCHOR, G4_EXCEPTION):
        if anchor not in ok["statement"]:
            failures.append("the issued statement is missing the anchor %r" % anchor)
    for number in ("5 source", "3 supplied", "0 document"):
        if number not in ok["statement"]:
            failures.append("the scope line is missing %r" % number)
    # The definition must carry its own anchors, or claim_guard cannot recognise it.
    text = "\n".join(DEFINITION)
    for anchor in (DEFINITION_ANCHOR, EXCEPTION_ANCHOR):
        if anchor not in text:
            failures.append("the definition is missing the anchor %r" % anchor)
    # Both states must render a block claim_guard accepts: all three anchors.
    for label, result in (("issued", ok),
                          ("withheld", evaluate(passage_findings=0, open_reviews=0,
                                                citations_unresolved=None, retracted_cited=0,
                                                sources_checked=5, corpus_docs=3,
                                                corpus_unreadable=0))):
        block = render_block(result)
        for anchor in (DEFINITION_ANCHOR, SCOPE_ANCHOR, EXCEPTION_ANCHOR):
            if anchor not in block:
                failures.append("the %s block is missing the anchor %r" % (label, anchor))
    for msg in failures:
        print("FAIL  %s" % msg)
    print("attribution self-test: %d checks, %d failed" % (len(SELF_TEST) + 11, len(failures)))
    return 1 if failures else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--facts", metavar="JSON", help="the seven facts evaluate() needs")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--definition", action="store_true", help="print the definition")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.definition:
        print("\n".join(DEFINITION))
        return 0
    if not args.facts:
        print("attribution: supply --facts (input gap, not a pass)", file=sys.stderr)
        return 4
    result = evaluate(**_facts_from_file(args.facts))
    print(render_block(result))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, indent=1), encoding="utf-8")
    return 0 if result["issuable"] else 1


if __name__ == "__main__":
    sys.exit(main())
