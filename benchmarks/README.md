# Benchmarks

Reproducible measurements behind the claims in the main README. Every number quoted there comes
from one of these scripts; none is asserted without a run.

Each script prints a confusion matrix, sensitivity, specificity and **Wilson 95% confidence
intervals**, so the honest range is visible rather than a bare point estimate.

| Script | What it measures | Network? |
|---|---|---|
| `bench_accuracy.py` | Retraction gate vs **NLM-curated** `Retracted Publication` labels (460 positives + 460 negatives) | yes |
| `bench_numeric.py` | Arithmetic gate on 17 labelled manuscripts (8 with injected defects) | no |
| `bench_ori_guide.py` | Overlap detector vs the **US ORI guide's own expert verdicts** on its paraphrasing exercise | no |
| `bench_originality_scaled.py` | Overlap detector on 186 labelled cases (verbatim, light edit, rewrite, unrelated) | no |
| `bench_originality_real.py` | Overlap detector on **real** bioRxiv/medRxiv preprint → published pairs | yes |
| `bench_originality.py` | The original 24-case hand-built overlap set (kept for continuity) | no |
| `bench_verdicts.py` | `citation-report` deterministic channel vs 23 hand-labelled sentences; asserts **conflict precision = 1.000** | no |

## Running

```bash
cd benchmarks
python3 bench_numeric.py            # instant, offline
python3 bench_ori_guide.py          # instant, offline
python3 bench_verdicts.py           # instant, offline
python3 bench_originality_scaled.py # instant, offline (uses cached abstracts)
python3 bench_originality_real.py   # fetches once, then cached
python3 bench_accuracy.py fetch     # builds the labelled citation set from PubMed
SHARDS=6 python3 bench_accuracy.py score
```

Requirements: Python 3.9+ and the standard library. `bench_originality*.py` import the toolkit in
`tools/originality-toolkit/` directly. `bench_accuracy.py` shells out to the real gate in
`skills/evidence-synthesis-forge/scripts/cross_verify_citations.py` — it does not reimplement it.

Fetched data is cached under `/tmp/bench/`, so re-runs are cheap. Delete that directory to refetch.

## Notes on method

- **Ground truth is independent of the tool.** Retraction labels come from NLM's publication types,
  not from OpenAlex/Crossref — which is what the gate reads. The overlap benchmark labels come from
  the ORI guide, not from our own scorer.
- **`bench_accuracy.py` shards.** The gate is sequential (it sleeps 0.4 s between rows to be polite
  to the APIs), so the set is split and several unmodified gate processes run in parallel. The gate
  itself is not modified.
- **`bench_originality_real.py` audits its own labels.** "Preprint vs published" does *not* imply
  overlapping text — 7 of 61 published abstracts were heavily rewritten. It therefore also computes
  an independent `difflib` verbatim run and reports sensitivity on the pairs that genuinely overlap.
- **The gate exits 0 for PASS and 2 for FAIL.** Both are successful runs; the labelled set
  deliberately contains retracted papers, so FAIL is expected.
- **`bench_ori_guide.py` embeds text** from the ORI guide (a U.S. federal government publication)
  solely to test against its published labels.

## Known limitation these benchmarks expose

`bench_ori_guide.py` shows that a paraphrase which changes every content word but keeps the source's
sentence structure (ORI Guideline 4) is **not** caught. Two stdlib-only frame measures were tried
and neither separates frame-copying from unrelated text, so no verdict depends on the frame number.
See `BENCHMARK-RESULTS.md` in `docs/` for the measurements.
