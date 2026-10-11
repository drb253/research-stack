#!/usr/bin/env python3
"""Scaled labelled benchmark for the originality toolkit's overlap detector.

Design
------
Sources   : 60 real PubMed abstracts (cached by an earlier fetch).
Positives : verbatim copies (60) + light edits (60) -- "light edit" swaps ~half of
            the eligible content words for synonyms while preserving order and
            structure, which models the common patchwriting pattern.
Negatives : each source sentence scored against a DIFFERENT paper's record (60,
            the false-positive risk the tool's own docstring warns about) plus
            hand-written independent rewrites of the same idea (6).

Also sweeps the decision threshold so the operating point can be chosen from
measured sensitivity/specificity rather than guessed.
"""
from __future__ import annotations

import importlib.util
import json
import math
import random
import re
import sys
from pathlib import Path

TOOLKIT = Path(__file__).resolve().parent.parent / "tools/originality-toolkit"
sys.path.insert(0, str(TOOLKIT))
spec = importlib.util.spec_from_file_location("oc", TOOLKIT / "originality_check.py")
oc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oc)

def _fetch_corpus(path, want):
    """Fetch real PubMed abstracts once and cache them (no third-party deps)."""
    import time, urllib.parse, urllib.request, xml.etree.ElementTree as ET
    path.parent.mkdir(parents=True, exist_ok=True)
    E = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    UA = "research-stack-benchmark/1.0 (mailto:bench@example.org)"

    def get(url):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        return urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")

    ids = json.loads(get(f"{E}/esearch.fcgi?db=pubmed&retmode=json&retmax=400"
                         f"&term={urllib.parse.quote('hasabstract[text] AND english[la] AND 2015:2023[dp]')}")) \
        ["esearchresult"]["idlist"]
    out = []
    for start in range(0, min(len(ids), 300), 100):
        try:
            root = ET.fromstring(get(f"{E}/efetch.fcgi?db=pubmed&retmode=xml&id="
                                     + ",".join(ids[start:start + 100])))
        except Exception:
            continue
        for art in root.findall(".//PubmedArticle"):
            t = art.find(".//ArticleTitle")
            title = "".join(t.itertext()) if t is not None else ""
            abst = " ".join("".join(ab.itertext()) for ab in art.findall(".//Abstract/AbstractText")).strip()
            if len(abst.split()) < 70:
                continue
            out.append({"pmid": art.findtext(".//PMID") or "", "title": title.strip(),
                        "abstract": abst})
        time.sleep(0.4)
    seen, final = set(), []
    for o in out:
        if o["pmid"] in seen:
            continue
        seen.add(o["pmid"])
        final.append(o)
    final = final[:want]
    path.write_text(json.dumps(final, indent=1), encoding="utf-8")
    return final


def load_corpus(path, want):
    if not path.exists():
        print(f"corpus cache missing -> fetching real PubMed abstracts to {path} ...")
        return _fetch_corpus(path, want)
    return json.loads(path.read_text(encoding="utf-8"))


SOURCES = load_corpus(Path("/tmp/bench/orig/sources_large.json"), 60)

SYNONYMS = {
    "important": "significant", "significant": "important", "challenging": "difficult",
    "remains": "stays", "generating": "producing", "multiple": "several",
    "associated": "linked", "adverse": "harmful", "outcomes": "results",
    "patients": "individuals", "various": "several", "increased": "raised",
    "decreased": "lowered", "however": "nevertheless", "therefore": "thus",
    "study": "investigation", "analysis": "assessment", "risk": "hazard",
    "disease": "illness", "treatment": "therapy", "effect": "impact",
    "reduced": "lowered", "improved": "enhanced", "identified": "recognised",
    "found": "observed", "showed": "demonstrated", "compared": "contrasted",
    "evaluated": "assessed", "included": "comprised", "used": "employed",
    "high": "elevated", "low": "reduced", "common": "frequent", "severe": "serious",
    "mortality": "death", "efficacy": "effectiveness", "safety": "tolerability",
    "prevalence": "frequency", "associated with": "linked to",
}

# Hand-written independent rewrites (same idea, genuinely different wording).
HEAVY_REWRITES = {
    0: "Although Cas9 made targeted DNA changes routine, producing several simultaneous "
       "knockouts is still hard.",
    1: "A mother's weight before pregnancy predicts complications during gestation and "
       "health problems in her children years later.",
    2: "Critically ill people who develop both brain dysfunction from sepsis and cardiac "
       "failure form a group that has drawn little research attention, yet identifying "
       "their risk early could shape how they are treated.",
    3: "Breathing airborne particles smaller than 2.5 micrometres ranks among the leading "
       "contributors to lung and heart disease.",
    4: "In mammals, M cells lining the gut take up antigens from the lumen; the protein GP2 "
       "identifies these mature cells and also serves as a receptor for bacteria.",
    5: "Measuring how much carbon dairy farming emits per litre of milk matters both for "
       "quantifying its climate impact and for deciding how to reduce it.",
}


def first_sentence(abstract: str) -> str:
    text = re.sub(r"\s+", " ", abstract).strip()
    for s in re.split(r"(?<=[.!?])\s+", text):
        if len(s.split()) >= 8:
            return s
    return text[:200]


def light_edit(sentence: str, rng: random.Random, rate: float = 0.5) -> str:
    """Swap eligible content words for synonyms, preserving order and structure."""
    words = sentence.split()
    out = []
    for w in words:
        core = re.sub(r"[^A-Za-z-]", "", w).lower()
        repl = SYNONYMS.get(core)
        if repl and rng.random() < rate:
            # keep trailing punctuation and original capitalisation
            lead = w[: len(w) - len(w.lstrip())]
            trail = w[len(w.rstrip()):]
            body = repl.capitalize() if w[:1].isupper() else repl
            out.append(lead + body + trail)
        else:
            out.append(w)
    return " ".join(out)


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def build_cases():
    cases = []  # (candidate_index, variant, text, should_flag)
    for i, s in enumerate(SOURCES):
        sent = first_sentence(s["abstract"])
        cases.append((i, "verbatim", sent, True))
        cases.append((i, "light-edit", light_edit(sent, random.Random(1000 + i)), True))
        # unrelated: this sentence judged against a different paper's record
        cases.append(((i + 17) % len(SOURCES), "unrelated", sent, False))
    for i, text in HEAVY_REWRITES.items():
        if i < len(SOURCES):
            cases.append((i, "heavy-rewrite", text, False))
    return cases


def score_all(cases, threshold):
    rows = []
    for idx, variant, text, should_flag in cases:
        cand = SOURCES[idx]
        res = oc.score(text, {"title": cand["title"], "abstract": cand["abstract"]})
        v = oc.verdict(res, threshold, min_run=3)
        flagged = v != "ok"
        rows.append({"variant": variant, "score": res["score"], "cosine": res["cosine"],
                     "run_words": res["run_words"], "verdict": v, "flagged": flagged,
                     "should_flag": should_flag})
    return rows


def tool_default_threshold() -> float:
    """Read the tool's real --threshold default so the benchmark cannot drift."""
    src = (TOOLKIT / "originality_check.py").read_text(encoding="utf-8")
    m = re.search(r'"--threshold",\s*type=float,\s*default=([0-9.]+)', src)
    return float(m.group(1)) if m else 0.35


def main():
    cases = build_cases()
    default_thr = tool_default_threshold()
    rows = score_all(cases, default_thr)

    tp = sum(1 for r in rows if r["should_flag"] and r["flagged"])
    fn = sum(1 for r in rows if r["should_flag"] and not r["flagged"])
    fp = sum(1 for r in rows if not r["should_flag"] and r["flagged"])
    tn = sum(1 for r in rows if not r["should_flag"] and not r["flagged"])

    print("=== ORIGINALITY OVERLAP DETECTOR — SCALED LABELLED BENCHMARK ===")
    print(f"  cases: {len(rows)}  (positives {tp+fn}, negatives {tn+fp})\n")

    print("  by variant:")
    for v in ("verbatim", "light-edit", "heavy-rewrite", "unrelated"):
        sub = [r for r in rows if r["variant"] == v]
        if not sub:
            continue
        flagged = sum(1 for r in sub if r["flagged"])
        exp = "flag" if sub[0]["should_flag"] else "clean"
        scores = sorted(r["score"] for r in sub)
        print(f"    {v:14s} n={len(sub):3d}  expect={exp:5s}  flagged={flagged:3d}"
              f"  score min={scores[0]:.3f} med={scores[len(scores)//2]:.3f} max={scores[-1]:.3f}")

    sens = tp / (tp + fn)
    spec = tn / (tn + fp)
    ls, hs = wilson(tp, tp + fn)
    lp, hp = wilson(tn, tn + fp)
    print(f"\n  AT THE TOOL'S DEFAULT THRESHOLD ({default_thr}):")
    print(f"    copying detected      (sensitivity): {tp}/{tp+fn} = {sens:.1%}"
          f"  95% CI [{ls:.1%}, {hs:.1%}]")
    print(f"    independent left clean (specificity): {tn}/{tn+fp} = {spec:.1%}"
          f"  95% CI [{lp:.1%}, {hp:.1%}]")

    print("\n  THRESHOLD SWEEP (choose an operating point from data):")
    print(f"    {'thr':>5} {'sens':>7} {'spec':>7} {'misses':>7} {'false alarms':>13}")
    best = None
    for thr in [round(0.20 + 0.02 * i, 2) for i in range(16)]:
        r2 = score_all(cases, thr)
        t2 = sum(1 for r in r2 if r["should_flag"] and r["flagged"])
        f2 = sum(1 for r in r2 if r["should_flag"] and not r["flagged"])
        p2 = sum(1 for r in r2 if not r["should_flag"] and r["flagged"])
        n2 = sum(1 for r in r2 if not r["should_flag"] and not r["flagged"])
        s2 = t2 / (t2 + f2)
        sp2 = n2 / (n2 + p2)
        mark = ""
        # prefer zero false alarms, then highest sensitivity
        if p2 == 0 and (best is None or s2 > best[1]):
            best = (thr, s2, sp2, p2)
            mark = "  <- zero-FP optimum"
        print(f"    {thr:>5.2f} {s2:>7.1%} {sp2:>7.1%} {f2:>7} {p2:>13}{mark}")

    if best:
        thr, s2, sp2, _ = best
        t2 = sum(1 for r in score_all(cases, thr) if r["should_flag"] and r["flagged"])
        n_pos = tp + fn
        lo, hi = wilson(t2, n_pos)
        print(f"\n  RECOMMENDED OPERATING POINT: threshold={thr} "
              f"-> sensitivity {s2:.1%} (95% CI [{lo:.1%}, {hi:.1%}]), specificity {sp2:.1%}")

    Path("/tmp/bench/orig_scaled.json").parent.mkdir(parents=True, exist_ok=True)
    Path("/tmp/bench/orig_scaled.json").write_text(
        json.dumps(rows, indent=1), encoding="utf-8")
    print("\n  detail -> /tmp/bench/orig_scaled.json")


if __name__ == "__main__":
    main()
