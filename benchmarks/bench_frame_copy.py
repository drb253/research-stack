#!/usr/bin/env python3
"""bench_frame_copy.py -- measure structural (frame-copy) detectors honestly.

ORI Guideline 4 says a paraphrase must use its own *syntactical structure*, not
merely its own words. The toolkit's lexical score cannot see a frame copy, and
``originality_check.structure_similarity`` records that two stdlib function-word
formulations failed to separate frame copies from unrelated text. This script
measures a family of candidate measures on a labelled corpus and reports every
one of them, including the failures.

Corpus (frozen, offline): frame_corpus/corpus.json, built by gen_frame_corpus.py.
  positives  frame_copy          n=108  every content word swapped, frame kept
  negatives  unrelated           n=54   real sentence vs a DIFFERENT real paper
             legit_paraphrase    n=8    ORI guide v5/v6 (guide says correct)
             real_revision       n=54   preprint sentence vs its OWN published abstract
  secondary  human_frame_copy    n=3    hand-written G4-style frame copies
             real_revision is also reported on its own (the hardest negatives).

Measures tried (all stdlib, deterministic):
  1  toolkit_structure        the existing reported structure_similarity (baseline)
  2  best_window              best-window function-word SequenceMatcher ratio
  3  inf_lcs_bigram           LCS over INFORMATIVE function-word bigrams
  4  inf_lcs_unigram          LCS over INFORMATIVE function words
  5  inf_lcs_bigram_sentence  as 3, best candidate SENTENCE instead of whole stream
  6  skeleton_length          punctuation/clause skeleton + sentence-length ratio
  7  slot_agreement           positional agreement of content-word slots
  8  combined                 pre-declared mean of 3, 6 and 7 (no tuning)
  ref lexical                the toolkit's own lexical score, for context

Reported per measure: ROC/AUC with a 95% bootstrap CI, and the best operating
point (max sensitivity at FPR <= 5%) with a Wilson 95% CI on sensitivity.

DECISION RULE (fixed before the numbers were seen, and implemented below):
a measure is wireable only if, at its best operating point,
    sensitivity >= 0.90  AND  FPR <= 0.05  AND  Wilson lower bound >= 0.80,
and (robustness guard, added because the threshold is selected on the same set)
a deterministic 2-fold cross-validated sensitivity >= 0.80. Otherwise NO
threshold is wired and the toolkit ships the measured-coverage disclosure.

Usage:
  python3 bench_frame_copy.py                 # table on stdout
  python3 bench_frame_copy.py --json out.json
  python3 bench_frame_copy.py --self-test     # offline math checks
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "frame_corpus/corpus.json"
TOOLKIT = HERE.parent / "tools/originality-toolkit"
sys.path.insert(0, str(TOOLKIT))

spec = importlib.util.spec_from_file_location("oc", TOOLKIT / "originality_check.py")
oc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oc)

# Function words that carry almost no frame information: determiners, preps,
# auxiliary verbs, coordination. Removing them is the point of measure 3/4.
GENERIC = frozenset("""
a an the this that these those it its and or but nor so yet for of in on at by
with from to into as is are was were be been being am do does did done have has
had having will would shall should can could may might must not no there here
then than if such other more most much many few all both each every any some
only own same very also
""".split())
INFORMATIVE = frozenset(oc._FUNCTION_WORDS) - GENERIC
CLAUSE_SPLIT = re.compile(r"[;:,]")
PUNCT = re.compile(r"[,;:()\-]")


def body(candidate):
    return "%s. %s" % (candidate.get("title", ""), candidate.get("abstract", ""))


def fw(text):
    return [w for w in oc.normalise(text) if w in oc._FUNCTION_WORDS]


def informative(text):
    return [w for w in fw(text) if w in INFORMATIVE]


def bigrams(seq):
    return list(zip(seq, seq[1:]))


def lcs(a, b):
    """Longest common subsequence length (two-row DP)."""
    if not a or not b:
        return 0
    if len(a) > len(b):
        a, b = b, a
    previous = [0] * (len(a) + 1)
    for token in b:
        current = [0]
        for index, other in enumerate(a):
            if token == other:
                current.append(previous[index] + 1)
            else:
                current.append(max(previous[index + 1], current[index]))
        previous = current
    return previous[-1]


def candidate_sentences(candidate, min_words=5):
    return oc.split_sentences(body(candidate), min_words=min_words)


# ---------------------------------------------------------------------------
# The candidate measures. Each takes (draft, candidate) and returns 0..1.
# ---------------------------------------------------------------------------
def m_toolkit_structure(draft, candidate):
    return oc.structure_similarity(draft, candidate=body(candidate))


def m_best_window(draft, candidate):
    a, b = fw(draft), fw(body(candidate))
    if len(a) < 3 or len(b) < 3:
        return 0.0
    width = len(a)
    if len(b) <= width:
        return round(oc.SequenceMatcher(None, a, b, autojunk=False).ratio(), 4)
    best = 0.0
    for start in range(0, len(b) - width + 1):
        ratio = oc.SequenceMatcher(None, a, b[start:start + width],
                                   autojunk=False).ratio()
        if ratio > best:
            best = ratio
    return round(best, 4)


def m_inf_lcs_bigram(draft, candidate):
    a, b = bigrams(informative(draft)), bigrams(informative(body(candidate)))
    if not a:
        return 0.0
    return round(lcs(a, b) / float(len(a)), 4)


def m_inf_lcs_unigram(draft, candidate):
    a, b = informative(draft), informative(body(candidate))
    if not a:
        return 0.0
    return round(lcs(a, b) / float(len(a)), 4)


def _informative_ngrams(text, n=3):
    """Function-word n-grams, dropping the all-generic ones.

    Forming n-grams over the INFORMATIVE words alone (measure inf_lcs_bigram)
    makes adjacency almost impossible -- two rare frame words rarely sit next to
    each other -- so the useful reading is: keep the full frame in order, and
    count only the windows that carry a frame word.
    """
    words = fw(text)
    grams = [tuple(words[i:i + n]) for i in range(len(words) - n + 1)]
    return [g for g in grams if any(w in INFORMATIVE for w in g)]


def m_inf_ngram_lcs(draft, candidate):
    a, b = _informative_ngrams(draft), _informative_ngrams(body(candidate))
    if not a:
        return 0.0
    return round(lcs(a, b) / float(len(a)), 4)


def m_fw_lcs_all(draft, candidate):
    """LCS over the whole function-word frame -- the naive sibling of 3/4.

    Kept in the table precisely because it should NOT separate: unrelated
    scientific prose shares generic function words in order by chance.
    """
    a, b = fw(draft), fw(body(candidate))
    if not a:
        return 0.0
    return round(lcs(a, b) / float(len(a)), 4)


def m_inf_lcs_bigram_sentence(draft, candidate):
    a = bigrams(informative(draft))
    if not a:
        return 0.0
    best = 0.0
    for sentence in candidate_sentences(candidate):
        b = bigrams(informative(sentence))
        if not b:
            continue
        best = max(best, lcs(a, b) / float(len(a)))
    return round(best, 4)


def _clause_lengths(text):
    return [len(oc.normalise(part)) for part in CLAUSE_SPLIT.split(text) if part.strip()]


def m_skeleton_length(draft, candidate):
    d_punct = PUNCT.findall(draft)
    c_punct = PUNCT.findall(body(candidate))
    punct_cover = (lcs(d_punct, c_punct) / float(len(d_punct))) if d_punct else 0.0
    d_words = max(1, len(oc.normalise(draft)))
    d_clauses = _clause_lengths(draft)
    best = 0.0
    for sentence in candidate_sentences(candidate):
        c_clauses = _clause_lengths(sentence)
        count_sim = 1.0 - abs(len(d_clauses) - len(c_clauses)) / float(
            max(len(d_clauses), len(c_clauses), 1))
        c_words = max(1, len(oc.normalise(sentence)))
        len_ratio = min(d_words, c_words) / float(max(d_words, c_words))
        best = max(best, (punct_cover + count_sim + len_ratio) / 3.0)
    return round(best, 4)


def _mask(text):
    return "".join("1" if w not in oc._FUNCTION_WORDS else "0"
                   for w in oc.normalise(text))


def m_slot_agreement(draft, candidate):
    d_mask = _mask(draft)
    if not d_mask:
        return 0.0
    best = 0.0
    for sentence in candidate_sentences(candidate):
        c_mask = _mask(sentence)
        if not c_mask:
            continue
        best = max(best, lcs(d_mask, c_mask) / float(max(len(d_mask), len(c_mask))))
    return round(best, 4)


def m_combined(draft, candidate):
    return round((m_inf_ngram_lcs(draft, candidate)
                  + m_skeleton_length(draft, candidate)
                  + m_slot_agreement(draft, candidate)) / 3.0, 4)


def m_lexical(draft, candidate):
    return oc.score(draft, candidate)["score"]


MEASURES = [
    ("toolkit_structure", "existing structure_similarity (baseline)", m_toolkit_structure),
    ("best_window", "best-window function-word ratio", m_best_window),
    ("fw_lcs_all", "LCS over ALL function words (naive sibling)", m_fw_lcs_all),
    ("inf_lcs_unigram", "LCS over informative function words", m_inf_lcs_unigram),
    ("inf_ngram_lcs", "LCS over informative function-word trigrams", m_inf_ngram_lcs),
    ("inf_lcs_bigram", "LCS over informative bigrams only (degenerate)",
     m_inf_lcs_bigram),
    ("inf_lcs_bigram_sentence", "informative bigram LCS vs best sentence (degenerate)",
     m_inf_lcs_bigram_sentence),
    ("skeleton_length", "punctuation/clause skeleton + length ratio", m_skeleton_length),
    ("slot_agreement", "content-word slot agreement", m_slot_agreement),
    ("combined", "pre-declared mean of inf_ngram/skeleton/slot", m_combined),
]

REFERENCE = [
    ("lexical", "toolkit lexical score (context, not structural)", m_lexical),
]

POSITIVE = "frame_copy"
NEGATIVE = ("unrelated", "legit_paraphrase", "real_revision")
SECONDARY = ("human_frame_copy",)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def auc(pos, neg):
    """Rank-based AUC (ties count 0.5)."""
    if not pos or not neg:
        return float("nan")
    joined = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg])
    rank_sum = 0.0
    index = 0
    while index < len(joined):
        end = index
        while end + 1 < len(joined) and joined[end + 1][0] == joined[index][0]:
            end += 1
        average_rank = (index + end) / 2.0 + 1.0
        for position in range(index, end + 1):
            if joined[position][1] == 1:
                rank_sum += average_rank
        index = end + 1
    n_pos, n_neg = len(pos), len(neg)
    return (rank_sum - n_pos * (n_pos + 1) / 2.0) / float(n_pos * n_neg)


def bootstrap_auc_ci(pos, neg, reps=2000, seed=0):
    rng = random.Random(seed)
    values = []
    for _ in range(reps):
        p = [pos[rng.randrange(len(pos))] for _ in range(len(pos))]
        n = [neg[rng.randrange(len(neg))] for _ in range(len(neg))]
        values.append(auc(p, n))
    values.sort()
    return values[int(0.025 * reps)], values[int(0.975 * reps) - 1]


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def operating_point(pos, neg, max_fpr=0.05):
    """Highest sensitivity with FPR <= max_fpr; ties -> highest threshold.

    Returns a dict that is always present. When NO threshold reaches the FPR cap
    the dict carries ``feasible: False`` plus the FPR floor and what sensitivity
    is available there -- "n/a" alone hides why a high-AUC measure is unusable.
    """
    thresholds = sorted({0.0} | set(pos) | set(neg), reverse=True)
    best = None
    floor = None
    for threshold in thresholds:
        tp = sum(1 for v in pos if v >= threshold)
        fp = sum(1 for v in neg if v >= threshold)
        fpr = fp / float(len(neg))
        sens = tp / float(len(pos))
        if floor is None or fpr < floor["fpr"] - 1e-12 or (
                abs(fpr - floor["fpr"]) <= 1e-12 and sens > floor["sensitivity"]):
            floor = {"threshold": threshold, "fpr": fpr, "sensitivity": sens,
                     "tp": tp, "fp": fp}
        if fpr > max_fpr + 1e-12:
            continue
        if best is None or sens > best["sensitivity"] + 1e-12:
            best = {"threshold": threshold, "sensitivity": sens, "fpr": fpr,
                    "tp": tp, "fp": fp}
        elif abs(sens - best["sensitivity"]) <= 1e-12 and threshold > best["threshold"]:
            best = {"threshold": threshold, "sensitivity": sens, "fpr": fpr,
                    "tp": tp, "fp": fp}
    if best is None:
        low, high = wilson(floor["tp"], len(pos))
        return {"feasible": False, "fpr_floor": floor["fpr"],
                "fpr_floor_threshold": floor["threshold"],
                "sensitivity_at_floor": floor["sensitivity"],
                "sensitivity_at_floor_ci": [low, high]}
    low, high = wilson(best["tp"], len(pos))
    best["feasible"] = True
    best["sensitivity_ci"] = [low, high]
    return best


def _fold(item):
    digest = hashlib.sha1(item["id"].encode()).hexdigest()
    return int(digest[:8], 16) % 2


def cross_validated(pos, neg):
    """2-fold CV: pick the threshold on one fold, score the other. Deterministic."""
    tp = total_pos = fp = total_neg = 0
    for held in (0, 1):
        train_pos = [v for v, f in pos if f != held]
        train_neg = [v for v, f in neg if f != held]
        test_pos = [v for v, f in pos if f == held]
        test_neg = [v for v, f in neg if f == held]
        point = operating_point(train_pos, train_neg)
        threshold = point["threshold"] if point.get("feasible") else float("inf")
        tp += sum(1 for v in test_pos if v >= threshold)
        total_pos += len(test_pos)
        fp += sum(1 for v in test_neg if v >= threshold)
        total_neg += len(test_neg)
    return {"sensitivity": tp / total_pos if total_pos else float("nan"),
            "fpr": fp / total_neg if total_neg else float("nan"),
            "positives": total_pos, "negatives": total_neg}


def evaluate(measure, items, classes=POSITIVE, negatives=NEGATIVE):
    pos = [(measure(it["draft"], {"title": it["source_title"],
                                  "abstract": it["source_text"]}), _fold(it))
           for it in items if it["class"] in _as_tuple(classes)]
    neg = [(measure(it["draft"], {"title": it["source_title"],
                                  "abstract": it["source_text"]}), _fold(it))
           for it in items if it["class"] in _as_tuple(negatives)]
    pos_values = [v for v, _ in pos]
    neg_values = [v for v, _ in neg]
    low, high = bootstrap_auc_ci(pos_values, neg_values)
    point = operating_point(pos_values, neg_values)
    cv = cross_validated(pos, neg)
    return {
        "auc": round(auc(pos_values, neg_values), 4),
        "auc_ci": [round(low, 4), round(high, 4)],
        "positives": len(pos_values), "negatives": len(neg_values),
        "operating_point": point,
        "cv": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in cv.items()},
        "clears_bar": bool(point.get("feasible")
                           and point["sensitivity"] >= 0.90
                           and point["fpr"] <= 0.05
                           and point["sensitivity_ci"][0] >= 0.80
                           and cv["sensitivity"] >= 0.80),
        "median_positive": _median(pos_values),
        "median_negative": _median(neg_values),
    }


def _as_tuple(value):
    return value if isinstance(value, tuple) else (value,)


def _median(values):
    if not values:
        return float("nan")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 4)
    return round((ordered[middle - 1] + ordered[middle]) / 2.0, 4)


# ---------------------------------------------------------------------------
def load_corpus(path=CORPUS):
    if not Path(path).is_file():
        sys.exit("bench_frame_copy: %s missing; run gen_frame_corpus.py" % path)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run(corpus_path=CORPUS):
    corpus = load_corpus(corpus_path)
    items = corpus["items"]
    rows = []
    for name, description, function in MEASURES + REFERENCE:
        result = evaluate(function, items)
        result.update({"measure": name, "description": description})
        rows.append(result)
    # Sensitivity analysis, NOT the decision: the same measures with the
    # same-work revision class removed from the negative pool.
    no_revision = []
    for name, description, function in MEASURES:
        result = evaluate(function, items, negatives=("unrelated", "legit_paraphrase"))
        result.update({"measure": name, "description": description})
        no_revision.append(result)
    combined = next(f for n, _d, f in MEASURES if n == "combined")
    context = {
        "corpus": str(corpus_path),
        "counts": corpus.get("counts", {}),
        "resolution": corpus.get("resolution", {}),
        "decision_rule": ("sensitivity >= 0.90 and FPR <= 0.05 and Wilson lower "
                          "bound >= 0.80 and 2-fold CV sensitivity >= 0.80"),
        "decision_negatives": list(NEGATIVE),
        "secondary": {
            cls: evaluate(combined, items, classes=cls, negatives=NEGATIVE)
            for cls in SECONDARY
        },
    }
    return context, rows, no_revision


def _fmt_point(point):
    if not point:
        return "n/a", "n/a", "n/a"
    if not point.get("feasible"):
        return ("  n/a", "no t<=5%% (floor %.3f)" % point["fpr_floor"],
                "%6.3f" % point["fpr_floor"])
    return ("%6.3f" % point["sensitivity"],
            "[%.3f, %.3f]" % tuple(point["sensitivity_ci"]),
            "%6.3f" % point["fpr"])


def _table(rows, show_cv=True):
    header = ("%-26s %6s %16s %10s %16s %8s %8s %8s"
              % ("measure", "AUC", "AUC 95% CI", "sens", "sens 95% CI", "FPR",
                 "CVsens", "bar"))
    print(header)
    print("-" * len(header))
    for row in rows:
        sens, ci, fpr = _fmt_point(row["operating_point"])
        print("%-26s %6.3f %16s %10s %16s %8s %8.3f %8s"
              % (row["measure"], row["auc"],
                 "[%.3f, %.3f]" % tuple(row["auc_ci"]),
                 sens, ci, fpr, row["cv"]["sensitivity"],
                 "CLEARS" if row["clears_bar"] else "no"))


def print_table(context, rows, no_revision):
    print("=== FRAME-COPY BENCHMARK ===")
    print("corpus: %s" % context["corpus"])
    print("items: %s" % json.dumps(context["counts"], sort_keys=True))
    print("toolkit resolves %s/%s anchors against their own document"
          % (context["resolution"].get("anchors_resolved"),
             context["resolution"].get("anchors_checked")))
    print("positives: %s | decision negatives: %s (%s)"
          % (POSITIVE, sum(context["counts"].get(c, 0) for c in NEGATIVE),
             ", ".join(NEGATIVE)))
    print()
    _table(rows)
    print()
    for row in rows:
        print("  %-26s %s" % (row["measure"], row["description"]))
        print("      median positive %.3f vs median negative %.3f"
              % (row["median_positive"], row["median_negative"]))
    print()
    print("sensitivity analysis (NOT the decision): negatives without the "
          "same-work revision class")
    print()
    _table(no_revision)
    print()
    print("decision rule: %s" % context["decision_rule"])
    winners = [r["measure"] for r in rows if r["clears_bar"]]
    if winners:
        print("DECISION: wire %s" % ", ".join(winners))
    else:
        print("DECISION: no measure clears the bar -> disclosure fallback")
    print()
    print("secondary class (combined measure):")
    for cls, result in context["secondary"].items():
        point = result["operating_point"]
        sens = ("%.3f" % point["sensitivity"]) if point.get("feasible") else "n/a"
        print("  %-18s n=%-3d sensitivity at the frame-copy operating point: %s"
              % (cls, result["positives"], sens))


# ---------------------------------------------------------------------------
SELF_TEST = []


def self_test():
    failures = []

    def check(condition, message):
        if not condition:
            failures.append(message)

    # LCS against brute force recursion on small strings.
    def brute(a, b):
        if not a or not b:
            return 0
        if a[0] == b[0]:
            return 1 + brute(a[1:], b[1:])
        return max(brute(a[1:], b), brute(a, b[1:]))

    cases = [("", ""), ("a", "a"), ("abc", "ac"), ("abcd", "bd"),
             ("whetherxare", "whetheryare"), ("zzz", "abc")]
    for a, b in cases:
        check(lcs(a, b) == brute(a, b), "lcs mismatch on %r/%r" % (a, b))
    # AUC endpoints.
    check(abs(auc([1, 1], [0, 0]) - 1.0) < 1e-9, "perfect AUC != 1")
    check(abs(auc([0, 0], [1, 1]) - 0.0) < 1e-9, "inverted AUC != 0")
    check(abs(auc([1, 0], [1, 0]) - 0.5) < 1e-9, "tied AUC != 0.5")
    # Wilson bounds bracket the point estimate.
    low, high = wilson(9, 10)
    check(low < 0.9 < high, "wilson bounds do not bracket the estimate")
    # Operating point respects the FPR cap.
    point = operating_point([1, 1, 1], [0, 0, 0.9])
    check(point.get("feasible") and point["fpr"] <= 0.05,
          "operating point broke the FPR cap")
    check(point.get("feasible") and point["sensitivity"] == 1.0,
          "operating point missed sensitivity 1.0")
    # An infeasible cap is reported, not hidden as None.
    infeasible = operating_point([1, 1], [1, 1, 0])
    check(infeasible["feasible"] is False and infeasible["fpr_floor"] > 0.05,
          "an infeasible operating point was not reported as a floor")
    # A measure that cannot separate must not clear the bar.
    flat = evaluate(lambda _d, _c: 0.5, load_corpus()["items"])
    check(not flat["clears_bar"], "a constant measure cleared the bar")
    # Determinism: two runs give identical rows.
    context_a, rows_a, norev_a = run()
    context_b, rows_b, norev_b = run()
    check(json.dumps(rows_a, sort_keys=True) == json.dumps(rows_b, sort_keys=True),
          "the benchmark is not deterministic")
    check(json.dumps(norev_a, sort_keys=True) == json.dumps(norev_b, sort_keys=True),
          "the sensitivity analysis is not deterministic")
    check(context_a["counts"] == context_b["counts"], "corpus counts are not stable")

    for failure in failures:
        print("FAIL  %s" % failure)
    print("bench_frame_copy self-test: %d checks, %d failed"
          % (10 + len(cases), len(failures)))
    return 1 if failures else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--corpus", default=str(CORPUS))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    context, rows, no_revision = run(args.corpus)
    print_table(context, rows, no_revision)
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({"context": context, "measures": rows,
                        "sensitivity_analysis_no_revision": no_revision}, indent=1),
            encoding="utf-8")
        print("results written to %s" % args.json_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
