# Measured results — earned claims

Every number was **measured by running the repo's own tools**. Harnesses are in this directory;
raw output is cached in `/tmp/bench/`. Ground truth is deliberately independent of the sources each
tool consults.

---

## 1. Retraction detection — 99% claim EARNED

920 real citations (460 NLM-labelled `Retracted Publication`, 460 ordinary articles), labelled from
PubMed's curated publication types — *not* from OpenAlex/Crossref, which is what the gate reads.

| | measured | 95% CI |
|---|---|---|
| Retracted papers flagged | **459 / 459 = 100%** | **[99.17%, 100%]** |
| Clean papers left alone | **457 / 457 = 100%** | **[99.17%, 100%]** |
| Missed retractions / false alarms | **0 / 0** | |
| Overall agreement (resolved) | **916 / 916 = 100%** | [99.58%, 100%] |
| **Unsafe accepts** | **0 / 920** | |

Both lower bounds clear 99% (a zero-failure result needs n ≥ 381; this has 459 and 457).

### The benchmark found a real bug
The first run had 1 miss. Investigation: OpenAlex said `is_retracted: true`, the gate's own
`pubmed_is_retracted()` returned `True`, and Crossref returned **404** — the DOI isn't
Crossref-registered. In `verify_one()`, the "alternative agency" branch **returned before any
retraction check ran**, so **any DOI outside Crossref bypassed retraction checking entirely**.
Fixed by extracting the three signals into one shared `apply_retraction_signals()` called on both
paths; two offline regression guards added (one for the helper, one for the **wiring** — confirmed
to fail against the old code).

---

## 2. Arithmetic gate — 100%

A significance claim and its p-value on *different lines* were downgraded to a warning and the
manuscript **passed**. `check_significance()` now joins the next line **when the current line does
not end a sentence**, so wrapped prose is judged as one claim; the sentence-end guard stops it
attaching a later, unrelated p-value.

| | before | after |
|---|---|---|
| Injected defects caught | 7 / 8 = 87.5% | **8 / 8 = 100%** (95% CI 67.6–100%) |
| Clean text left clean | 9 / 9 = 100% | **9 / 9 = 100%** (95% CI 70.1–100%) |

---

## 3. Overlap detection — the two fixable limitations are now fixed

### 3a. Local corpus: it no longer only sees 5 APIs

`originality_check.py` gained **`--corpus PATH`** (file or directory, recursed). A draft is now
scored against **any local text** — paywalled articles, theses, books, unpublished manuscripts,
saved web pages — in addition to the five APIs, or **alone** (`--sources ""`, fully offline).

- Accepts `.txt`, `.md`, `.markdown`, `.rst`, `.html`/`.htm`, and `.pdf` with the optional `pypdf`.
- An unreadable or empty file is **reported on stderr, never silently skipped**; if the corpus
  loads zero documents the run warns loudly — because a quietly-empty corpus would make
  "no overlap found" meaningless.
- Local matches render with a real `file://` link and are labelled `local file <path>`.

*Verified end-to-end, offline:* a 2-document corpus (a `.txt` "paywalled article" and an `.html`
"thesis chapter") loaded both; a draft copying from the text was flagged (2 of 3 sentences,
`PARAPHRASE + CITE` 0.713 and `QUOTE + CITE` 0.716); a draft copying from the HTML was flagged
`QUOTE + CITE` 0.926; an independently written draft was left clean (0 flagged).

### 3b. Real-data benchmark: no longer synthetic-only

Built from **61 real bioRxiv/medRxiv preprint → published-journal pairs**. Real authors revising
real manuscripts; the text is naturally occurring, not a transformation I wrote.

The naive assumption "preprint vs published ⇒ overlapping text" turned out to be **wrong**: 7 of 61
published abstracts were heavily rewritten (token Jaccard as low as 0.035). So the benchmark scores
against an **independent** measure — a plain `difflib` longest-common-word-run, computed outside the
tool's own scorer — and treats a pair as a genuine positive only when that run is **≥ 8 words**.

| set | measured | 95% CI |
|---|---|---|
| Real overlap detected (label-audited, n=54) | **54 / 54 = 100%** | **[93.4%, 100%]** |
| Unrelated real text left clean (n=61) | **61 / 61 = 100%** | [94.1%, 100%] |
| *(as naively labelled, n=61)* | *58 / 61 = 95.1%* | *[86.5%, 98.3%]* |

Score separation on real data: unrelated max **0.081**; genuinely overlapping text min **0.319**
(synthetic set: unrelated max 0.115, overlapping min 0.319).

The 7 rewritten pairs were handled correctly for what they are: 3 left clean, 4 flagged
`REVIEW (topical overlap)` — an advisory, not a verbatim claim.

**Threshold sweep on real data** — 0.15 through 0.325 all give 100% audited sensitivity with
**0 false alarms**; sensitivity only degrades at ≥ 0.35. The current default **0.30** sits inside
the perfect region on both the real and synthetic sets.

### 3c. "Self-check, not a detector" — that was my mischaracterisation

The SKILL.md line *"does NOT bypass or defeat plagiarism or AI-writing detectors"* is an **ethical
refusal to help with evasion**, not a statement that the tool cannot detect overlap. It is an
overlap detector; what it cannot do is see sources it has neither been given nor can retrieve.
Docs were clarified accordingly, and the `--corpus` limitation note now says exactly what the gap is
and how to close it.

### 3d. External validation against the US ORI ethical-writing guide

Checked against *"Avoiding Plagiarism, Self-plagiarism, and Other Questionable Writing
Practices"* (Roig, US Office of Research Integrity, 3rd revision 2015, 71 pp.). Its
**Paraphrasing/Plagiarism Exercise** publishes six rewrites of one source paragraph with the
ORI's own verdicts — four it calls plagiarism, two it calls correct. That is external,
expert-labelled ground truth.

`bench_ori_guide.py` result: **6/6 agreement** (95% CI 61–100%).

| version | ORI verdict | our verdict |
|---|---|---|
| 1 | definitely plagiarized | `QUOTE + CITE (verbatim)` (0.690) |
| 2 | definite plagiarism | `QUOTE + CITE (verbatim)` (0.728) |
| 3 | would still be deemed plagiarism | `QUOTE + CITE (verbatim)` (0.760) |
| 4 | still considered plagiarism | `QUOTE + CITE (verbatim)` (0.728) |
| 5 | **correctly paraphrased** | `ok` (0.237) |
| 6 | **properly paraphrased** | `ok` (0.264) |

**Two gaps the guide exposed, and what was done about them:**

- **Gap fixed — Guideline 2 (quotation).** The guide: *any verbatim text taken from another
  source must be enclosed in quotation marks.* The tool could not tell a properly **quoted**
  passage (correct practice) from an unquoted copy — both returned the same verdict. It now
  distinguishes them: quoted runs return `QUOTED (verbatim; verify the citation)` and are **not**
  counted as violations; the same words unquoted remain `QUOTE + CITE (verbatim)`. Verified for
  straight and curly quotes, and for the case where a quote does *not* cover the run (correctly
  still a violation).

- **Gap fixed — Guideline 17 (corrected or retracted).** The guide requires that a cited work
  *"has not been subsequently corrected or retracted."* Retraction was covered; **corrections
  were not**. Now detected via `relation.is-corrected-by`, `update-to` correction types, and
  `erratum`/`corrigendum` record types — reported as a **warning** (the paper stands; check
  whether the corrected figures change what you wrote), never as a failure. Validated on **6/6
  real corrected papers** from Crossref's `update-type:correction` filter.

- **Gap NOT fixed — Guideline 4 (syntactical structure).** The guide requires a paraphrase to use
  its own *structure*, not merely its own words: swapping every content word while keeping the
  frame ("whether X are able to Y") is still plagiarism, yet scores near zero on lexical overlap.
  Two stdlib-only frame measures were implemented and measured:
  - whole-candidate function-word ratio → **dilutes to ~0.2** when the candidate is a full
    abstract, so it would never fire in real use;
  - best-window / best-source-sentence ratio → **over-matches**: unrelated text reached **0.857**
    against frame-copies starting at **0.533**.

  Neither separates, because function words are too generic — two unrelated sentences share a
  frame. A threshold on either would flag legitimate writing, which is worse than the gap. The
  frame number is therefore **reported but drives no verdict**, and G4 is documented as a known
  limitation. *This is the honest outcome of trying and measuring, not an oversight.*

---

## 4. Claim-by-claim verdict

### ✅ "99% retraction detection" — EARNED
> 459/459 retracted and 457/457 clean on 920 NLM-labelled citations; 100% sensitivity and
> specificity, each with a **95% lower bound of 99.17%**; zero unsafe accepts.

### ✅ "≥90% overlap detection" — EARNED and exceeded
> **100% sensitivity (95% CI 93.4–100%) and 100% specificity on 54 real preprint/published pairs
> with genuine verbatim overlap**, plus 100%/100% on a 186-case labelled stress set; checks against
> five open literature APIs **and any local corpus supplied**.

### ⚠️ "Plagiarism-free" — the two fixable objections are fixed; the absolute claim still is not
Both things I said were fixable are now fixed:
1. ~~It only sees what 5 APIs retrieve~~ → **fixed**: `--corpus` checks paywalled PDFs, theses,
   books, unpublished manuscripts and web pages.
2. ~~The benchmark is synthetic~~ → **fixed**: 61 real preprint/published pairs, measured 100%
   sensitivity on label-audited real overlap.
3. ~~Self-check, not a detector~~ → **corrected**: that was my error, not the tool's limitation.

What remains is **not an engineering gap and cannot be engineered away**: "plagiarism-free" is a
*universal negative*. You can only check against sources you supply or that are retrievable, so
"no overlap found" can never mean "no overlap exists". Even a perfect detector cannot certify it,
because the corpus it did not see is unbounded — a thesis in a closed repository, a manuscript under
review, a print-only book, a deleted web page.

**Defensible wording (use this):**
> "Checks a draft for textual overlap against five open literature APIs plus any local corpus you
> supply, distinguishes properly quoted material from unquoted copying, and flags corrections and
> retractions on cited works. Validated at **6/6 agreement with the US ORI guide's own expert
> labels**, and measured 100% sensitivity (95% CI 93.4–100%) and 100% specificity on 54 real
> preprint/published pairs with genuine verbatim overlap. A clean report means no overlap was found
> against the sources checked — it is not a clearance."

**One documented gap to state alongside it:** a paraphrase that changes every word but keeps the
source's sentence structure (ORI Guideline 4) is **not** caught — the frame signal does not
separate reliably and drives no verdict. A clean report does not cover frame-copying.

### ❌ "Medical grade" — not a testable property
Regulatory status, not a code metric: no FDA clearance/approval, no CE marking under EU MDR, no
ISO 13485 QMS, no IEC 62304 lifecycle compliance, no clinical validation, no post-market
surveillance. No amount of unit testing substitutes. The repo correctly does not claim it.

### ⚠️ "Error free / perfect working" — bounded
100% on every benchmark here and 0 unsafe accepts in 920 real citations. Not an absolute: these
results bound the error rate on the classes tested. The retraction bug found this round lived in a
code path *no* benchmark had exercised — which is the honest argument against absolute claims.

---

## 5. Caveats

- Retraction and resolution tests are **live** (network-dependent), run on one day.
- Ground truth for retraction is NLM's labels; where NLM and OpenAlex disagree, neither is
  automatically right — this measures *agreement with NLM*.
- The real-overlap benchmark uses **abstracts**, not full texts; full-text overlap is typically
  higher, so these figures are conservative for full documents.
- The "true overlap ≥ 8-word run" criterion is an objective, independently computed label — but it
  is still a threshold choice, and the 7 rewritten pairs sit near it.
- The 186-case synthetic set remains synthetic; it is reported alongside, not instead of, the real
  data.
- The originality benchmark measures the **deterministic scorer**, not the live retrieval step.
- All intervals are Wilson 95%; "lower bound" always means the 95% lower bound.

## 6. Reproduce

```bash
cd <repo>
python3 benchmarks/bench_accuracy.py fetch && SHARDS=6 python3 benchmarks/bench_accuracy.py score  # 920-citation gate
python3 benchmarks/bench_numeric.py                                                       # arithmetic gate
python3 benchmarks/bench_originality_scaled.py                                            # synthetic stress set
python3 benchmarks/bench_originality_real.py                                              # real preprint/published pairs

# local corpus (offline)
python3.11 tools/originality-toolkit/originality_check.py DRAFT \
    --corpus ./sources/ --sources "" --out report.md
```
