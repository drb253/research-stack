#!/usr/bin/env python3
"""Item 5 - style and clarity pass that cannot launder sourced text.

A conservative, deterministic editor for YOUR OWN prose. It fixes mechanical
issues (doubled words, spacing, wordy phrases) and flags style concerns (long
sentences, hedging, passive constructions, nominalisations).

The guardrail is structural, not advisory: any sentence the originality report
flagged as sourced is **skipped**, so this tool can never be used to restyle
someone else's wording and present it as yours. Skipped sentences are listed in
the report, so the exclusion is visible rather than silent.

    python3 style_pass.py draft.md --report out.json --out style_report.md \\
        --clean draft_edited.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from difflib import SequenceMatcher

# Mechanical fixes: safe, meaning-preserving, applied to unflagged sentences.
MECHANICAL = [
    (re.compile(r"\b(\w+)\s+\1\b", re.I), r"\1"),                  # the the
    (re.compile(r"[ \t]{2,}"), " "),                                # double spaces
    (re.compile(r"\s+([,.;:!?])"), r"\1"),                         # space before comma
    (re.compile(r"([,.;:!?])(?=[A-Za-z])"), r"\1 "),               # missing space after
    (re.compile(r"\bin order to\b", re.I), "to"),
    (re.compile(r"\bdue to the fact that\b", re.I), "because"),
    (re.compile(r"\ba large number of\b", re.I), "many"),
    (re.compile(r"\butili[sz]e\b", re.I), "use"),
    (re.compile(r"\bin spite of the fact that\b", re.I), "although"),
]

# Advisory flags: reported, never rewritten.
HEDGES = re.compile(r"\b(very|really|quite|basically|actually|arguably|"
                    r"somewhat|fairly|rather|clearly|obviously)\b", re.I)
PASSIVE = re.compile(r"\b(?:is|are|was|were|be|been|being)\s+\w+(?:ed|en)\b(?:\s+by\b)?", re.I)
NOMINAL = re.compile(r"\b\w+(?:tion|ment|ance|ence|ness)\s+of\b", re.I)
CONTRACTION = re.compile(r"\b\w+'\w+\b")
LONG_SENTENCE_WORDS = 35

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-]*")


def normalise_sentence(text):
    """Key used to match a draft sentence against a report entry."""
    return " ".join(WORD_RE.findall(text.lower()))


def load_flagged(report_path):
    """Normalised sentences the originality check flagged as sourced."""
    with open(report_path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return [
        normalise_sentence(item["sentence"])
        for item in payload.get("results", [])
        if item.get("verdict") != "ok" and item.get("sentence")
    ]


def is_flagged(key, flagged, flagged_set, threshold=0.85):
    """Fail-safe membership test.

    An exact match is not enough: a line-level re-split of the draft can produce
    a sentence the report never saw verbatim, and silently restyling that would
    defeat the whole guardrail. So a near-match (>= 0.85 token similarity) also
    counts as flagged.
    """
    if not key:
        return False
    if key in flagged_set:
        return True
    return any(SequenceMatcher(None, key, other).ratio() >= threshold for other in flagged)


def analyse_sentence(sentence):
    """Return (edited_text, fixes_applied, advisory_flags)."""
    text, fixes = sentence, []
    for pattern, replacement in MECHANICAL:
        updated = pattern.sub(replacement, text)
        if updated != text:
            fixes.append(pattern.pattern)
            text = updated

    flags = []
    words = len(WORD_RE.findall(text))
    if words > LONG_SENTENCE_WORDS:
        flags.append("%d words - consider splitting" % words)
    for label, pattern in (("hedging", HEDGES), ("passive", PASSIVE),
                           ("nominalisation", NOMINAL), ("contraction", CONTRACTION)):
        found = pattern.search(text)
        if found:
            flags.append("%s: %r" % (label, found.group(0)))

    # A mechanical fix can strip a sentence-initial capital ("In order to" ->
    # "to"), so restore it when the original began with one.
    if text and sentence[:1].isupper() and text[:1].islower():
        text = text[0].upper() + text[1:]
    return text, fixes, flags


def process_draft(text, flagged):
    flagged_set = set(flagged)
    output_lines, report, skipped = [], [], []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("|"):
            output_lines.append(line)
            continue
        rebuilt = []
        for sentence in SENTENCE_SPLIT.split(stripped):
            if is_flagged(normalise_sentence(sentence), flagged, flagged_set):
                skipped.append(sentence)
                rebuilt.append(sentence)          # never touched
                continue
            edited, fixes, flags = analyse_sentence(sentence)
            if fixes or flags:
                report.append({"original": sentence, "edited": edited,
                               "fixes": fixes, "flags": flags})
            rebuilt.append(edited)
        output_lines.append(" ".join(rebuilt))
    return "\n".join(output_lines), report, skipped


def render_report(draft_name, report, skipped, total_sentences):
    lines = [
        "# Style report — %s" % draft_name,
        "",
        "Mechanical fixes and advisory flags for your own prose only.",
        "",
        "**Sentences scanned:** %d  |  **with findings:** %d  |  "
        "**skipped as sourced:** %d" % (total_sentences, len(report), len(skipped)),
        "",
    ]
    if skipped:
        lines += [
            "## Skipped - flagged as sourced (NOT edited)",
            "",
            "These sentences came from an originality report as quoting or close",
            "paraphrase. This tool refuses to restyle them: editing someone else's",
            "wording to look original is exactly what a similarity report exists to",
            "catch. Quote them with a citation, or rewrite them yourself.",
            "",
        ]
        for sentence in skipped:
            lines.append("- %s" % sentence)
        lines.append("")
    if not report:
        lines.append("No style findings in the unflagged prose.")
        return "\n".join(lines)

    lines += ["## Findings", ""]
    for index, item in enumerate(report, 1):
        lines.append("### %d" % index)
        lines.append("")
        lines.append("- **was:** %s" % item["original"])
        if item["edited"] != item["original"]:
            lines.append("- **now:** %s" % item["edited"])
        if item["fixes"]:
            lines.append("- **fixed:** %d mechanical issue(s)" % len(item["fixes"]))
        for flag in item["flags"]:
            lines.append("- **flag:** %s" % flag)
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("draft", help="your draft (.md/.txt)")
    parser.add_argument("--report", required=True,
                        help="originality_check JSON report (defines sourced passages)")
    parser.add_argument("--out", default="style_report.md")
    parser.add_argument("--clean", default=None, help="write the edited draft here")
    args = parser.parse_args(argv)

    if not os.path.exists(args.report):
        sys.stderr.write("error: report not found: %s\n" % args.report)
        return 2
    flagged = load_flagged(args.report)

    with open(args.draft, encoding="utf-8") as handle:
        text = handle.read()
    total = len([s for line in text.split("\n") for s in SENTENCE_SPLIT.split(line) if s.strip()])

    edited, report, skipped = process_draft(text, flagged)

    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(render_report(os.path.basename(args.draft), report, skipped, total))
    print("Wrote %s (%d findings, %d sourced sentences skipped)"
          % (args.out, len(report), len(skipped)))

    if args.clean:
        with open(args.clean, "w", encoding="utf-8") as handle:
            handle.write(edited)
        print("Wrote edited draft -> %s" % args.clean)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
