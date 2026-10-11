#!/usr/bin/env python3
"""REAL-DATA benchmark for the originality overlap detector.

Unlike bench_originality_scaled.py (which I authored synthetic light edits for),
this uses naturally-occurring text pairs:

  positives : a bioRxiv/medRxiv PREPRINT abstract scored against the record of its
              own PUBLISHED journal version. Real overlap, produced by real
              authors revising real manuscripts -- not a transformation I wrote.
  negatives : a preprint abstract scored against a DIFFERENT paper's record
              (real, unrelated text).

Also reports how much the preprint and published abstracts actually differ, so the
difficulty of the positive set is visible rather than assumed.
"""
from __future__ import annotations

import importlib.util
import difflib
import json
import math
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

TOOLKIT = Path(__file__).resolve().parent.parent / "tools/originality-toolkit"
sys.path.insert(0, str(TOOLKIT))
spec = importlib.util.spec_from_file_location("oc", TOOLKIT / "originality_check.py")
oc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oc)

CACHE = Path("/tmp/bench/real")
UA = "research-stack-benchmark/1.0 (mailto:bench@example.org)"
TARGET = int(os.environ.get("PAIRS", "60"))


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return json.load(urllib.request.urlopen(req, timeout=60))


def openalex_by_doi(doi):
    try:
        w = _get("https://api.openalex.org/works/doi:" + urllib.parse.quote(doi))
    except Exception:
        return None
    inv = w.get("abstract_inverted_index") or {}
    if not inv:
        return None
    positioned = sorted((p, t) for t, ps in inv.items() for p in ps)
    abstract = " ".join(t for _, t in positioned)
    return {"title": w.get("display_name") or "", "abstract": abstract,
            "year": w.get("publication_year") or "", "doi": doi}


def collect():
    CACHE.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE / "pairs.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    # bioRxiv posts ~30 preprints/day; sweep several weeks to find enough that
    # have since been published (the API exposes the journal DOI).
    windows = [("2024-01-08", "2024-01-14"), ("2024-02-05", "2024-02-11"),
               ("2024-03-04", "2024-03-10"), ("2024-04-01", "2024-04-07"),
               ("2024-05-06", "2024-05-12"), ("2024-06-03", "2024-06-09"),
               ("2024-07-01", "2024-07-07"), ("2024-09-02", "2024-09-08")]
    pairs = []
    for start, end in windows:
        if len(pairs) >= TARGET:
            break
        for server in ("biorxiv", "medrxiv"):
            try:
                d = _get(f"https://api.biorxiv.org/details/{server}/{start}/{end}/0")
            except Exception:
                continue
            for c in d.get("collection", []):
                pub = (c.get("published") or "").strip()
                if pub in ("", "NA"):
                    continue
                abstract = (c.get("abstract") or "").strip()
                if len(abstract.split()) < 60:
                    continue
                rec = openalex_by_doi(pub)
                if not rec or len(rec["abstract"].split()) < 60:
                    continue
                pairs.append({"preprint_doi": c.get("doi"), "published_doi": pub,
                              "preprint_abstract": abstract,
                              "published_title": rec["title"],
                              "published_abstract": rec["abstract"],
                              "published_year": rec["year"]})
                if len(pairs) >= TARGET:
                    break
            time.sleep(0.3)
    cache_file.write_text(json.dumps(pairs, indent=1), encoding="utf-8")
    return pairs


def independent_run(sentence, published_abstract):
    """Longest shared word run, computed independently of the tool's own scorer.

    A preprint and its published version are the same WORK but not necessarily
    the same WORDS -- some journals rewrite abstracts heavily. So "preprint vs
    published" is not by itself evidence that text overlaps. This measures the
    text itself, which is what the detector is supposed to find.
    """
    a = re.findall(r"[a-z0-9]+", sentence.lower())
    b = re.findall(r"[a-z0-9]+", published_abstract.lower())
    if not a or not b:
        return 0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).find_longest_match(
        0, len(a), 0, len(b)).size


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def first_sentence(text):
    text = re.sub(r"\s+", " ", text).strip()
    for s in re.split(r"(?<=[.!?])\s+", text):
        if len(s.split()) >= 8:
            return s
    return text[:250]


def main():
    pairs = collect()
    if len(pairs) < 10:
        sys.exit(f"only {len(pairs)} real pairs collected; need more")
    print(f"=== REAL-DATA OVERLAP BENCHMARK ===\n  real preprint/published pairs: {len(pairs)}")

    # How different are the two abstracts really? (characterises difficulty)
    ratios = []
    for p in pairs:
        a = re.sub(r"\W+", " ", p["preprint_abstract"].lower())
        b = re.sub(r"\W+", " ", p["published_abstract"].lower())
        aw, bw = set(a.split()), set(b.split())
        if aw | bw:
            ratios.append(len(aw & bw) / len(aw | bw))
    ratios.sort()
    print(f"  preprint vs published token Jaccard: min={ratios[0]:.2f} "
          f"median={ratios[len(ratios)//2]:.2f} max={ratios[-1]:.2f}")

    thr = float(re.search(r'"--threshold",\s*type=float,\s*default=([0-9.]+)',
                          (TOOLKIT / "originality_check.py").read_text(encoding="utf-8")).group(1))

    rows = []
    for i, p in enumerate(pairs):
        sent = first_sentence(p["preprint_abstract"])
        run_indep = independent_run(sent, p["published_abstract"])
        # positive: this sentence against its OWN published record
        res = oc.score(sent, {"title": p["published_title"], "abstract": p["published_abstract"]})
        rows.append({"kind": "real-positive", "score": res["score"], "run": res["run_words"],
                     "run_independent": run_indep, "true_overlap": run_indep >= 8,
                     "result": res,
                     "verdict": oc.verdict(res, thr, 3), "should_flag": True})
        # negative: the same sentence against a DIFFERENT paper's record
        other = pairs[(i + 7) % len(pairs)]
        res2 = oc.score(sent, {"title": other["published_title"],
                               "abstract": other["published_abstract"]})
        rows.append({"kind": "real-negative", "score": res2["score"], "run": res2["run_words"],
                     "result": res2,
                     "verdict": oc.verdict(res2, thr, 3), "should_flag": False})

    for kind in ("real-positive", "real-negative"):
        sub = [r for r in rows if r["kind"] == kind]
        flagged = sum(1 for r in sub if r["verdict"] != "ok")
        scores = sorted(r["score"] for r in sub)
        print(f"\n  {kind:14s} n={len(sub):3d}  flagged={flagged:3d}"
              f"  score min={scores[0]:.3f} med={scores[len(scores)//2]:.3f} max={scores[-1]:.3f}")

    pos = [r for r in rows if r["kind"] == "real-positive"]
    neg = [r for r in rows if r["kind"] == "real-negative"]

    def report(k, n, label):
        lo, hi = wilson(k, n)
        print(f"    {label:34s}: {k}/{n} = {k/n:.1%}  95% CI [{lo:.1%}, {hi:.1%}]")

    print(f"\n  AT THE TOOL'S DEFAULT THRESHOLD ({thr}):")
    print("    (a) as labelled -- preprint text vs its own published record:")
    report(sum(1 for r in pos if r["verdict"] != "ok"), len(pos), "detected")
    print("    (b) label-audited -- only pairs whose text really overlaps")
    print("        (independent verbatim run >= 8 words):")
    true_pos = [r for r in pos if r["true_overlap"]]
    report(sum(1 for r in true_pos if r["verdict"] != "ok"), len(true_pos), "detected")
    report(sum(1 for r in neg if r["verdict"] == "ok"), len(neg),
           "unrelated left clean (specificity)")
    print(f"        pairs excluded as genuinely rewritten: {len(pos) - len(true_pos)}"
          f" (independent run < 8 words)")

    print("\n  THRESHOLD SWEEP on REAL data (zero false alarms required):")
    print(f"    {'thr':>5} {'audited sens':>13} {'spec':>7} {'false alarms':>13}")
    for t in [round(0.15 + 0.025 * i, 3) for i in range(13)]:
        hit = sum(1 for r in true_pos if oc.verdict(r["result"], t, 3) != "ok")
        fa = sum(1 for r in neg if oc.verdict(r["result"], t, 3) != "ok")
        n = len(true_pos)
        lo, _ = wilson(hit, n)
        print(f"    {t:>5.3f} {hit}/{n} = {hit/n:>5.1%} {1 - fa/len(neg):>7.1%} {fa:>13}"
              f"   lower bound {lo:.1%}")

    misses = [r for r in true_pos if r["verdict"] == "ok"]
    if misses:
        print(f"\n    {len(misses)} audited positive(s) missed at {thr}:")
        for r in sorted(misses, key=lambda x: x["score"]):
            print(f"      score={r['score']:.3f} independent_run={r['run_independent']}")

    (CACHE / "scored.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"\n  detail -> {CACHE / 'scored.json'}")


if __name__ == "__main__":
    main()
