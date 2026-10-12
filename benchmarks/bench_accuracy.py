#!/usr/bin/env python3
"""Benchmark the research-stack retraction gate against an INDEPENDENT ground truth.

Ground truth = PubMed's NLM-curated publication types ("Retracted Publication"[pt]),
which is curated independently of the OpenAlex/Crossref sources the gate consults.

Phase 1 `fetch`  : pull a labelled DOI set from PubMed and cache it.
Phase 2 `score`  : run the repo's real gate over the set and compute a confusion matrix.

Nothing here modifies the repo.
"""
from __future__ import annotations

import csv
import json
import math
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
UA = "research-stack-benchmark/1.0 (mailto:bench@example.org)"
CACHE = Path("/tmp/bench")
REPO = Path(__file__).resolve().parent.parent
GATE = REPO / "skills/evidence-synthesis-forge/scripts/cross_verify_citations.py"
PY = sys.executable


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def esearch(query: str, retmax: int) -> list[str]:
    url = (f"{EUTILS}/esearch.fcgi?db=pubmed&retmode=json&retmax={retmax}"
           f"&term={urllib.parse.quote(query)}")
    return json.loads(_get(url))["esearchresult"]["idlist"]


def esummary(pmids: list[str]) -> dict:
    out = {}
    for i in range(0, len(pmids), 200):
        chunk = pmids[i:i + 200]
        url = f"{EUTILS}/esummary.fcgi?db=pubmed&retmode=json&id={','.join(chunk)}"
        out.update(json.loads(_get(url))["result"])
        time.sleep(0.4)
    return out


def doi_of(rec: dict) -> str:
    for aid in rec.get("articleids") or []:
        if (aid.get("idtype") or "").lower() == "doi":
            return (aid.get("value") or "").strip().lower()
    return ""


def is_retracted_label(rec: dict) -> bool:
    return "Retracted Publication" in (rec.get("pubtype") or [])


def fetch() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)

    # ---- positives: NLM-curated retracted publications -----------------------
    pos_pmids = esearch('"Retracted Publication"[pt]', 3000)
    time.sleep(0.4)
    pos = esummary(pos_pmids)

    # ---- negatives: ordinary research articles, filtered to drop any that NLM
    #      itself labels retracted (so the negative label is trustworthy) ------
    neg_pmids = esearch('"Journal Article"[pt] AND 2012:2022[dp] AND hasabstract', 3000)
    time.sleep(0.4)
    neg = esummary(neg_pmids)

    def build(recs: dict, want_retracted: bool) -> list[dict]:
        rows = []
        for pmid, rec in recs.items():
            if pmid in ("uids",) or not isinstance(rec, dict):
                continue
            if not doi_of(rec):
                continue
            label = is_retracted_label(rec)
            if label != want_retracted:
                continue
            rows.append({
                "pmid": pmid,
                "doi": doi_of(rec),
                "title": (rec.get("title") or "").strip(),
                "pubtype": "|".join(rec.get("pubtype") or []),
                "expected_retracted": "true" if want_retracted else "false",
            })
        return rows

    positives = build(pos, True)
    negatives = build(neg, False)

    # de-dup by DOI, cap the sets so the live run stays bounded
    def dedup(rows, cap):
        seen, out = set(), []
        for r in rows:
            if r["doi"] in seen:
                continue
            seen.add(r["doi"])
            out.append(r)
        return out[:cap]

    positives, negatives = dedup(positives, 460), dedup(negatives, 460)

    (CACHE / "positives.json").write_text(json.dumps(positives, indent=1), encoding="utf-8")
    (CACHE / "negatives.json").write_text(json.dumps(negatives, indent=1), encoding="utf-8")

    with (CACHE / "labelled.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["doi", "title", "pmid", "expected_retracted", "pubtype"])
        w.writeheader()
        for r in positives + negatives:
            w.writerow(r)

    print(f"positives (NLM says retracted) : {len(positives)}")
    print(f"negatives (NLM says not)       : {len(negatives)}")
    print(f"wrote {CACHE / 'labelled.csv'}")


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval — honest for small n and extreme proportions."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def score() -> None:
    pos = json.loads((CACHE / "positives.json").read_text(encoding="utf-8"))
    neg = json.loads((CACHE / "negatives.json").read_text(encoding="utf-8"))
    rows = pos + neg

    # The gate is sequential (0.4 s politeness sleep per row), so shard the set and
    # run several REAL gate processes in parallel. Every shard is the unmodified
    # gate; only the input file is split.
    shards = int(os.environ.get("SHARDS", "8"))
    shard_dir = CACHE / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    buckets: list[list[dict]] = [[] for _ in range(shards)]
    for i, r in enumerate(rows):
        buckets[i % shards].append(r)

    fields = ["doi", "title", "pmid", "expected_retracted", "pubtype"]
    jobs = []
    for i, bucket in enumerate(buckets):
        csv_path, out_path = shard_dir / f"shard{i}.csv", shard_dir / f"shard{i}.json"
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(bucket)
        jobs.append((csv_path, out_path))

    def run_shard(job):
        csv_path, out_path = job
        p = subprocess.run(
            [PY, str(GATE), "--sources", str(csv_path),
             "--mailto", "bench@example.org", "--out", str(out_path)],
            capture_output=True, text=True)
        # The gate returns 0 for PASS and 2 for FAIL (see `return 2 if failures
        # else 0`). Both are successful runs; the set deliberately contains
        # retracted papers, so FAIL is the expected outcome.
        return p.returncode, (p.stderr or "").strip()[-200:]

    print(f"running the real gate over {len(rows)} citations in {shards} parallel shards ...")
    with ThreadPoolExecutor(max_workers=shards) as pool:
        outcomes = list(pool.map(run_shard, jobs))

    verdict = {"results": [], "retracted": []}
    failed_shards = 0
    for (csv_path, out_path), (rc, err) in zip(jobs, outcomes):
        if rc not in (0, 2) or not out_path.exists():
            failed_shards += 1
            print(f"  shard {csv_path.name}: rc={rc} {err}")
            continue
        data = json.loads(out_path.read_text(encoding="utf-8"))
        verdict["results"].extend(data.get("results", []))
        verdict["retracted"].extend(data.get("retracted", []))
    if failed_shards:
        print(f"  WARNING: {failed_shards} shard(s) failed; results are partial")
    (CACHE / "gate_out.json").write_text(json.dumps(verdict, indent=1), encoding="utf-8")

    by_doi = {r["doi"].lower(): r for r in verdict.get("results", [])}
    retracted_set = {r["doi"].lower() for r in verdict.get("retracted", [])}

    tp = fp = tn = fn = 0
    unresolved_pos = unresolved_neg = 0
    rows_out = []
    for r in rows:
        doi = r["doi"].lower()
        exp = r["expected_retracted"] == "true"
        res = by_doi.get(doi)
        status = (res or {}).get("status", "MISSING")
        # An unreachable resolver is NOT a resolved citation. Reading the gate's old
        # generic "error" status as resolved meant a lookup failure on a retracted paper
        # counted as a missed retraction -- silently moving the one number this benchmark
        # exists to certify. Both input-side statuses are now counted as unresolved here,
        # and a shard that exits 3 is rejected outright above.
        resolved = status not in ("unresolved", "MISSING", "unreachable", "error")
        got = doi in retracted_set
        if not resolved:
            if exp:
                unresolved_pos += 1
            else:
                unresolved_neg += 1
        elif exp and got:
            tp += 1
        elif exp and not got:
            fn += 1
        elif not exp and got:
            fp += 1
        else:
            tn += 1
        rows_out.append({**r, "gate_status": status, "gate_retracted": got})

    with (CACHE / "scored.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)

    n_pos = sum(1 for r in rows if r["expected_retracted"] == "true")
    n_neg = len(rows) - n_pos

    print("\n=== RETRACTION GATE vs NLM-CURATED LABELS ===")
    print(f"  positive set (NLM: retracted)     : {n_pos}")
    print(f"  negative set (NLM: not retracted) : {n_neg}")
    print("\n  confusion matrix (resolved records only):")
    print(f"    true  positive (flagged retracted)  : {tp}")
    print(f"    false negative (MISSED retraction)  : {fn}   <-- the dangerous one")
    print(f"    false positive (wrongly flagged)    : {fp}")
    print(f"    true  negative (correctly clean)    : {tn}")
    print(f"\n  unresolved by the gate: {unresolved_pos} positive / {unresolved_neg} negative")

    sens = tp / (tp + fn) if (tp + fn) else float("nan")
    spec = tn / (tn + fp) if (tn + fp) else float("nan")
    lo_s, hi_s = wilson(tp, tp + fn)
    lo_p, hi_p = wilson(tn, tn + fp)
    print(f"\n  sensitivity (recall on retractions): {sens:.2%}  95% CI [{lo_s:.2%}, {hi_s:.2%}]"
          f"  n={tp+fn}")
    print(f"  specificity (clean left clean)     : {spec:.2%}  95% CI [{lo_p:.2%}, {hi_p:.2%}]"
          f"  n={tn+fp}")
    acc_n = tp + tn + fp + fn
    acc = (tp + tn) / acc_n if acc_n else float("nan")
    lo_a, hi_a = wilson(tp + tn, acc_n)
    print(f"  overall agreement with NLM labels  : {acc:.2%}  95% CI [{lo_a:.2%}, {hi_a:.2%}]  (n={acc_n})")
    print(f"\n  per-record detail -> {CACHE / 'scored.csv'}")


if __name__ == "__main__":
    {"fetch": fetch, "score": score}[sys.argv[1]]()
