#!/usr/bin/env python3
"""Labelled benchmark for the originality toolkit's overlap detector.

Measures the DETERMINISTIC scoring core (score() + verdict()), not the live
source-retrieval step: each sentence is scored against a known candidate record,
so retrieval noise cannot contaminate the result.

Labels:
  verbatim      -> copying; the tool MUST flag it
  light-edit    -> still copying (synonym/abbreviation swaps); MUST flag
  heavy-rewrite -> genuinely independent wording of the same idea; MUST NOT flag
  unrelated     -> sentence from a different paper; MUST NOT flag

This measures detection performance on labelled pairs. It does NOT establish
that a manuscript is "plagiarism-free" -- see the caveats printed at the end.
"""
from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

TOOLKIT = Path(__file__).resolve().parent.parent / "tools/originality-toolkit"
sys.path.insert(0, str(TOOLKIT))          # sibling modules (htmltext, sources, ...)
TOOL = TOOLKIT / "originality_check.py"
spec = importlib.util.spec_from_file_location("oc", TOOL)
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


SOURCES = load_corpus(Path("/tmp/bench/orig/sources.json"), 6)

# (source_index, variant, text, should_flag)
# Index into SOURCES identifies the candidate record the sentence is scored against.
CASES = [
    # [0] CRISPR-Cas9
    (0, "verbatim",
     "The CRISPR-Cas9 system has revolutionized genome editing, but generating multiple gene "
     "knockouts (multi-KOs) remains challenging.", True),
    (0, "light-edit",
     "The CRISPR-Cas9 system has transformed genome editing, but creating multiple gene "
     "knockouts (multi-KOs) remains difficult.", True),
    (0, "heavy-rewrite",
     "Although Cas9 made targeted DNA changes routine, producing several simultaneous knockouts "
     "is still hard.", False),
    (0, "unrelated", None, False),

    # [1] maternal obesity
    (1, "verbatim",
     "Maternal obesity is associated with adverse pregnancy and long-term offspring outcomes.",
     True),
    (1, "light-edit",
     "Maternal obesity is linked with adverse pregnancy and long-term offspring outcomes.", True),
    (1, "heavy-rewrite",
     "A mother's weight before pregnancy predicts complications during gestation and health "
     "problems in her children years later.", False),
    (1, "unrelated", None, False),

    # [2] sepsis-associated encephalopathy
    (2, "verbatim",
     "Patients with sepsis-associated encephalopathy (SAE) and heart failure (HF) represent a "
     "clinically relevant but understudied subgroup in the intensive care unit, and early risk "
     "stratification may be important for guiding management.", True),
    (2, "light-edit",
     "Patients with sepsis-associated encephalopathy (SAE) and heart failure (HF) represent a "
     "clinically relevant but understudied subgroup in the ICU, and early risk stratification "
     "may be important for guiding management.", True),
    (2, "heavy-rewrite",
     "Critically ill people who develop both brain dysfunction from sepsis and cardiac failure "
     "form a group that has drawn little research attention, yet identifying their risk early "
     "could shape how they are treated.", False),
    (2, "unrelated", None, False),

    # [3] PM2.5
    (3, "verbatim",
     "Atmospheric fine particulate matter (PM2.5) is one of the most important risk factors for "
     "various respiratory and cardiovascular diseases.", True),
    (3, "light-edit",
     "Atmospheric fine particulate matter (PM2.5) is one of the most significant risk factors "
     "for various respiratory and cardiovascular diseases.", True),
    (3, "heavy-rewrite",
     "Breathing airborne particles smaller than 2.5 micrometres ranks among the leading "
     "contributors to lung and heart disease.", False),
    (3, "unrelated", None, False),

    # [4] microfold cells / GP2
    (4, "verbatim",
     "Mammalian microfold (M) cells are specialized epithelial cells that sample luminal "
     "antigens, and glycoprotein 2 (GP2) is a marker of mature M cells and functions as a "
     "bacterial receptor.", True),
    (4, "light-edit",
     "Mammalian microfold (M) cells are specialized epithelial cells that sample luminal "
     "antigens, and glycoprotein 2 (GP2) is a marker of mature M cells and acts as a bacterial "
     "receptor.", True),
    (4, "heavy-rewrite",
     "In mammals, M cells lining the gut take up antigens from the lumen; the protein GP2 "
     "identifies these mature cells and also serves as a receptor for bacteria.", False),
    (4, "unrelated", None, False),

    # [5] milk carbon footprint
    (5, "verbatim",
     "Assessing the milk carbon footprint (MCF) is essential for understanding greenhouse gas "
     "emissions associated with dairy production and for guiding mitigation strategies on dairy "
     "farms.", True),
    (5, "light-edit",
     "Assessing the milk carbon footprint (MCF) is essential for understanding greenhouse gas "
     "emissions linked to dairy production and for guiding mitigation strategies on dairy "
     "farms.", True),
    (5, "heavy-rewrite",
     "Measuring how much carbon dairy farming emits per litre of milk matters both for "
     "quantifying its climate impact and for deciding how to reduce it.", False),
    (5, "unrelated", None, False),
]


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def main():
    rows = []
    for idx, variant, text, should_flag in CASES:
        cand = SOURCES[idx]
        if text is None:  # unrelated: borrow a sentence from a different paper
            other = SOURCES[(idx + 3) % len(SOURCES)]
            text = other["abstract"].split(".")[0] + "."
            cand = SOURCES[idx]
        res = oc.score(text, {"title": cand["title"], "abstract": cand["abstract"]})
        v = oc.verdict(res, 0.35, min_run=3)
        flagged = v != "ok"
        rows.append({"source": idx, "variant": variant, "verdict": v,
                     "score": res["score"], "cosine": res["cosine"],
                     "run_words": res["run_words"], "flagged": flagged,
                     "should_flag": should_flag, "correct": flagged == should_flag})

    print("=== ORIGINALITY OVERLAP DETECTOR — LABELLED BENCHMARK ===\n")
    print(f"  {'src':>3} {'variant':14s} {'score':>6} {'cos':>6} {'run':>4}  "
          f"{'verdict':24s} {'expect':7s} result")
    print("  " + "-" * 92)
    for r in rows:
        exp = "flag" if r["should_flag"] else "clean"
        print(f"  {r['source']:>3} {r['variant']:14s} {r['score']:>6.3f} {r['cosine']:>6.3f} "
              f"{r['run_words']:>4}  {r['verdict']:24s} {exp:7s} "
              f"{'CORRECT' if r['correct'] else 'WRONG'}")

    tp = sum(1 for r in rows if r["should_flag"] and r["flagged"])
    fn = sum(1 for r in rows if r["should_flag"] and not r["flagged"])
    fp = sum(1 for r in rows if not r["should_flag"] and r["flagged"])
    tn = sum(1 for r in rows if not r["should_flag"] and not r["flagged"])
    ls, hs = wilson(tp, tp + fn)
    lp, hp = wilson(tn, tn + fp)
    la, ha = wilson(tp + tn, len(rows))

    print(f"\n  copying detected      (sensitivity): {tp}/{tp+fn} = {tp/(tp+fn):.1%}"
          f"  95% CI [{ls:.1%}, {hs:.1%}]")
    print(f"  independent left clean (specificity): {tn}/{tn+fp} = {tn/(tn+fp):.1%}"
          f"  95% CI [{lp:.1%}, {hp:.1%}]")
    print(f"  overall agreement                   : {tp+tn}/{len(rows)} = "
          f"{(tp+tn)/len(rows):.1%}  95% CI [{la:.1%}, {ha:.1%}]")

    print("\n  by variant:")
    for v in ("verbatim", "light-edit", "heavy-rewrite", "unrelated"):
        sub = [r for r in rows if r["variant"] == v]
        ok = sum(1 for r in sub if r["correct"])
        print(f"    {v:14s} {ok}/{len(sub)}")

    Path("/tmp/bench/orig_scored.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print("\n  detail -> /tmp/bench/orig_scored.json")


if __name__ == "__main__":
    main()
