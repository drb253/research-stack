#!/usr/bin/env python3
"""Benchmark the overlap detector against the US ORI guide's OWN expert labels.

Source: "Avoiding Plagiarism, Self-plagiarism, and Other Questionable Writing
Practices: A Guide to Ethical Writing" (Miguel Roig, Ph.D.), Office of Research
Integrity, U.S. Department of Health and Human Services -- third revision, 2015.
https://ori.hhs.gov/avoiding-plagiarism-self-plagiarism-and-other-questionable-writing-practices-guide-ethical-writing

The guide's "Paraphrasing/Plagiarism Exercise" publishes six rewrites of one
source paragraph, each with the ORI's own verdict. Four are called plagiarism
explicitly ("definitely plagiarized", "definite plagiarism", "would still be
deemed as [plagiarism]", "still considered as a case of plagiarism"); two are
called correct ("sufficiently modified ... correctly paraphrased", "properly
paraphrased").

That makes an external, expert-labelled test set for this tool -- better than any
transformation I could author. This script measures agreement with it, plus two
checks the guide calls out that lexical overlap alone cannot see:

  Guideline 2 -- verbatim text must be QUOTED (quoting is correct practice)
  Guideline 4 -- a paraphrase must use its own STRUCTURE, not just its own words

Texts are reproduced from the ORI guide (a U.S. federal government publication)
for the sole purpose of testing a plagiarism checker against its labels.
"""
from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

TOOLKIT = Path(__file__).resolve().parent.parent / "tools/originality-toolkit"
sys.path.insert(0, str(TOOLKIT))
spec = importlib.util.spec_from_file_location("oc", TOOLKIT / "originality_check.py")
oc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oc)

THRESHOLD = 0.30

ORIGINAL = "This study examines whether workers of S. invicta are able to assist their mothers in colony usurpations. First we tested whether [queens] of S. invicta are better able to usurp colonies to which their daughters have moved. Second, we tested whether the effect of daughters on usurpation success is due to familiarity with the queen or to genetic relatedness. Aggressive behavior during these usurpation attempts was observed to determine if the presence of familiar or related workers influenced the aggressive response toward either the resident queen or the queen attempting usurpation."

VERSIONS = {
    1: ('PLAGIARIZED', "A study was conducted to examine whether workers of S. invicta can assist their mothers in colony usurpations. T he first hypothesis tested was whether queens of S. invicta are better able to usurp colonies to which their daughters have moved. For the second 51 hypothesis, the researchers tested whether the effect of daughters on usurpation success is due to familiarity with the queen or to genetic relatedness. The researchers observed aggressive behavior during these usurpation attempts to determine if the presence of familiar or related workers influenced the aggressive response toward either the resident queen or the queen attempting usurpation."),
    2: ('PLAGIARIZED', "An investigation was carried out to examine whether workers of S. invicta can assist their mothers in colony usurpations. The first hypothesis tested was whether queens of S. invicta are better able to usurp colonies to which their daughters have moved. The second hypothesis tested whether the effect of daughters on usurpation success is due to familiarity with the queen or to genetic relatedness. Aggressiveness during these usurpation attempts was measured to determine if the presence of familiar or related workers influenced the aggressive response toward either the resident queen or the queen attempting usurpation."),
    3: ('PLAGIARIZED', "To determine whether workers of S. invicta can assist their mothers in colony usurpations, two researchers have conducted a study in w hich the following hypotheses were tested: First, they wanted to see whether queens of S. invicta are better able to usurp colonies to which their daughters have moved. Second, they tested whether the effect of daughters on usurpation success is due to familiarity with the queen or to genetic relatedness. The ants’ aggressive behavior during these usurpation attempts was observed to determine if the presence of related or familiar workers influenced the aggressive response toward either the resident queen or the queen attempting a colony take- over. Pleas e indicate whether the above paragraph is: 1. P roperly paraphrased. 2. Definitely plagiarized. 3. Cannot determine."),
    4: ('PLAGIARIZED', "To determine whether workers of S. invicta can assist their mothers in colony usurpations, a study was conducted in which the following variables were investigated: First, S. invicta queens’ hypothesized ability to usurp colonies to which their daughters have moved was examined. The second hypothesis tested whether the effect of daughters on usurpation success is due to familiarity with the queen or to genetic relatedness. During these usurpation attempts aggressive behavior was observed to determine if the presence of familiar or related workers influenced aggression toward either the resident queen or the queen attempting colony usurpation. Please indicate whet her the above paragraph is: 1. P roperly paraphrased. 2. Definitely plagiarized. 3. Cannot determine."),
    5: ('PROPER', "An investigation was carried out to determine whether S. invicta mothers are helped by their worker offspring during colony usurpations. The study’s focus of investigation was the question of whether colony take-over by S. invicta queens is more effective when their daughters first invade the colonies. One hypothesis concerned the extent to which daughters’ familiarity with the queen, or their genetic similarity to her, affects successful colony take-over. During attempts at taking over another colony, behavioral observations were made of usurping workers that were either familiar or genetically related to the queens to see if these variables were related to aggressive behavior toward the resident or the invading queen."),
    6: ('PROPER', "Balas and Adams carried out an investigation to determine whether S. invicta mothers are helped by their worker offspring during colony take-overs. These authors asked whether colony take-over by S. invicta queens is more effective when their daughters first invade the colonies. A second hypothesis concerned the extent to which daughters’ familiarity with the queen, or their genetic similarity to her, affects successful colony take-over. During these occupation attempts, aggressive behavior of usurping workers that were either familiar or genetically related was observed to see if these variables mediated aggressive behavior toward the invading or the resident queen."),
}


# Structure-preserved rewrites: every content word swapped, the syntactic frame
# kept. ORI Guideline 4 says this is still plagiarism; lexical overlap is ~zero.
STRUCTURE_COPIES = [
    "The present investigation assesses whether labourers of the fire ant are capable of "
    "aiding their parents during nest takeovers.",
    "Our research asks whether members of this species can help their queens in nest seizures.",
    "The current work determines whether insects of this genus are able to aid their relatives "
    "in colony captures.",
]


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def best_for(text, candidate):
    best, verdict_text = None, "ok"
    for sentence in oc.split_sentences(text, min_words=8):
        result = oc.score(sentence, candidate)
        text_verdict = oc.verdict(result, THRESHOLD, 3)
        if best is None or result["score"] > best["score"]:
            best, verdict_text = result, text_verdict
    return best, verdict_text


def main():
    candidate = {"title": "", "abstract": ORIGINAL}
    print("=== ORI GUIDE EXPERT-LABELLED PARAPHRASE EXERCISE ===\n")
    print(f"  {'ver':>4} {'ORI verdict':14s} {'lex':>6} {'struct':>7}  {'our verdict':34s} result")
    print("  " + "-" * 92)
    agree = 0
    for n, (label, text) in sorted(VERSIONS.items()):
        best, verdict_text = best_for(text, candidate)
        flagged = oc.is_violation(verdict_text)
        want = label == "PLAGIARIZED"
        ok = flagged == want
        agree += ok
        print(f"  {n:>4} {label:14s} {best['score']:>6.3f} {best['structure']:>7.3f}  "
              f"{verdict_text:34s} {'OK' if ok else '<<< DISAGREES'}")
    lo, hi = wilson(agree, len(VERSIONS))
    print(f"\n  agreement with ORI expert labels: {agree}/{len(VERSIONS)} = "
          f"{agree/len(VERSIONS):.0%}  95% CI [{lo:.0%}, {hi:.0%}]")

    print("\n=== GUIDELINE 2: verbatim must be QUOTED ===")
    quote = ORIGINAL.split(".")[0] + "."
    unquoted = f"The authors report that {quote}"
    quoted = f'The authors report that "{quote}" (Balas & Adams, 1996).'
    for label, text in (("unquoted verbatim", unquoted), ("properly quoted", quoted)):
        best, verdict_text = best_for(text, candidate)
        print(f"  {label:20s} -> {verdict_text:36s} violation={oc.is_violation(verdict_text)}")

    print("\n=== GUIDELINE 4: structure copied, words changed ===")
    print("  KNOWN LIMITATION -- reported, not decisive. Two stdlib-only frame")
    print("  measures were tried and neither separates frame-copying from unrelated")
    print("  text (unrelated reached 0.857 against frame-copies from 0.533), so no")
    print("  verdict depends on this number. These are therefore NOT flagged:")
    for text in STRUCTURE_COPIES:
        best, verdict_text = best_for(text, candidate)
        print(f"  lex={best['score']:.3f} struct={best['structure']:.3f} -> {verdict_text}")


if __name__ == "__main__":
    main()
