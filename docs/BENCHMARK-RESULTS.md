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

## 5. citation-report deterministic channel — 100% on a hand-labelled set, and what that is worth

`benchmarks/bench_verdicts.py` runs the real CLI against 48 hand-labelled sentences covering every
rule in `skills/citation-report/references/verdict-rules.md`, plus six adversarial cases that must
**not** be flagged. Ground truth is the rule id each sentence is supposed to earn.

Every rate below is a confusion matrix with a Wilson 95% interval, because accuracy alone hides the
asymmetry that matters: for an accusation, a false positive accuses someone, while a false negative
merely leaves a sentence ungraded. Sensitivity and specificity are therefore always reported together,
and never collapsed into one number.

**A. On the 48 constructed cases** (written to exercise every rule)

| Decision | Accuracy | Sensitivity | Specificity | Precision | F1 |
|---|---|---|---|---|---|
| Any state, one against the rest | 1.000 [0.926, 1.000] | 1.000 per class (see below) | 1.000 per class | 1.000 | 1.000 |
| **The accusation decision** (conflict vs not) | **1.000** [0.926, 1.000] | **1.000** [0.871, 1.000] | **1.000** [0.851, 1.000] | 1.000 [0.871, 1.000] | 1.000 |
| The trigger decision (needs attribution?) | 1.000 [0.926, 1.000] | 1.000 [0.916, 1.000] | 1.000 [0.610, 1.000] | 1.000 [0.916, 1.000] | 1.000 |

Per-state one-vs-rest, all at sensitivity 1.000 and specificity 1.000: `attributed` (3 positives of 48),
`synthesis` (3), `unverifiable` (5), `unattributed` (5), **`conflict` (26)**, `no_citation_needed` (6).
The interval on each is wide — sensitivity 3/3 gives a lower bound of 0.438 — which is the honest
reading of a 48-case set.

### The conflict class was four positives wide, which made its interval the weakest number here

`conflict` is the one class that accuses someone, so its interval is the number a reader should
judge the tool by — and in the first revision that interval was **0.510**, because the labelled set
held four conflict cases. That is not a rounding problem; it is a set too small to distinguish
"the rules work" from "the rules happened to work four times".

The set now holds **twenty-six** conflict positives, reaching the same decision through mechanisms
that fail differently rather than repeating one shape:

| Mechanism | Cases | Example |
|---|---:|---|
| Effect measure contradicted, both directions | 18 | `HR 0.60` against a recorded `HR 0.80`; `RR 0.90` against `RR 0.75` |
| Distinct measures covered | 8 | HR, RR, OR, MD, SMD, IRR, PR, beta |
| Direction reversed rather than merely off | 1 | `HR 0.85` for a trial whose recorded `HR 1.25` was *harm* |
| Retraction, with the figure quoted correctly | 2 | a retracted source cited at exactly its recorded `RR 0.60` |
| Citation number the apparatus cannot account for | 2 | `[98]` where the reference list holds three sources |

All 26 classify correctly, so conflict precision stays at 1.000 and its Wilson lower bound moves
**0.510 → 0.871**. The set is still written by the author of the rule table, so it still shows the
rules do what they were designed to do rather than that they generalise; what it no longer does is
let four cases stand in for a claim about accusations generally.

**B. On 40 unseen real sentences** (drawn at a fixed interval from a real 34-page PTSD review, so it is
not a set written to fit the rules; hand-labelled by reading each sentence)

| Decision | Accuracy | Sensitivity | Specificity | Precision | F1 |
|---|---|---|---|---|---|
| Trigger: does the sentence need attribution? | **0.900** [0.769, 0.960] | **0.867** [0.703, 0.947] | **1.000** [0.722, 1.000] | 1.000 [0.871, 1.000] | 0.929 |
| The accusation path (every sentence is a true negative) | 1.000 [0.912, 1.000] | n/a — no contradiction occurs | **1.000** [0.912, 1.000] | n/a | n/a |

The real sample cannot measure conflict *sensitivity*: the document contains no contradiction, so there
is no positive to find. It measures the specificity of the accusation path on prose the rules were not
written against, and that is 40/40.

### The metrics found a real defect, and the fix is measured

The first run of these metrics scored the trigger at **accuracy 0.475, sensitivity 0.300, specificity
1.000** on the real sample: the rules never accused wrongly, but they missed 70% of the sentences that
did need attribution. Reading the 21 misses showed why — the signal list required exact phrases
("studies show"), so "research has documented", "investigations describe", "observations indicate",
"models ... show" and "instruments ... operationalise" were all invisible, as were associational claims
("is associated with", "correlate with", "prevent") and statistical nouns whose digits had not survived
extraction ("prevalence of", "scores were higher").

Three measured defects were fixed:

1. **Exact-phrase attribution.** A named body of evidence plus a reporting verb is now recognised, with
   up to four intervening words and an optional auxiliary or adverb, so a qualifying phrase cannot hide
   the claim. Capped at four, so the subject cannot drift into another clause.
2. **No association signal.** A claim that X is associated with, predicts, prevents, reduces or requires
   Y is now a trigger. `produce`/`produced` is deliberately excluded: "might have produced" is the
   author's own hedged inference, and including it was measured to cost a true negative.
3. **Two false triggers.** `ICD-11`, `DSM-5` and `PCL-5` digits were being read as statistics (a
   numbered label is a name, not a figure), and the hedge list contained the bare word `about`, which
   matched the *preposition* in "thinking about how chronic violence ... might have produced".

| Trigger on 40 unseen real sentences | Accuracy | Sensitivity | Specificity |
|---|---|---|---|
| before | 0.475 | 0.300 | 1.000 |
| **after** | **0.900** | **0.867** | **1.000** |

Sensitivity nearly tripled with no loss of specificity, and the constructed set stayed at 1.000. On the
real 1,027-sentence document the same change moved `unattributed` from **174 to 306** sentences
(`no_citation_needed` fell 656 → 524) — the old rules had been silently ignoring 132
attribution-requiring sentences, which is exactly the kind of under-reporting the metrics exist to
expose.

**The four remaining misses are named, not averaged away.** All four put more than four words between
the evidence noun and its reporting verb, which is the window the rule deliberately refuses to cross:

* "Developmental trauma research in children and adolescents with childhood maltreatment (CM)
  histories provides…"
* "A large study of postpartum women addressed this gap by examining…"
* "One approach interprets scores at or above as indicative…"
* "High-dose psilocybin produced marked improvements…"

`produce`/`produced` is excluded on purpose (defect 2 above), so the fourth is a costing decision rather
than an oversight. The other three are the price of the four-word cap: widening it is the obvious next
experiment, and it has to be measured, because the cap is what keeps a subject from drifting into a
neighbouring clause and triggering falsely.

### That experiment was run, and every variant was rejected

The four misses do not have one cause, and the obvious hypothesis — the cap is too small — turned out
to be wrong. Three candidate fixes were each measured against both labelled sets; none is kept. The
numbers below are the real-prose trigger (`tp fp fn tn` on the 40 unseen sentences, 30 of them
needing attribution) and the constructed set (48 cases, 6 of them true negatives):

| Variant | Real prose | Real sens | Real spec | Constructed spec | Whole-set agreement | Kept |
|---|---|---|---|---|---|---|
| **Committed** (cap 4) | 26 0 4 10 | 0.867 | 1.000 | 1.000 | 48/48 | — |
| Cap widened to 6, 8, 10, 12, 16, 24 | 26 0 4 10 | 0.867 | 1.000 | 1.000 | 48/48 | **No** |
| Parenthetical token allowed inside the window (`(CM)` no longer breaks the run) | 26 0 4 10 | 0.867 | 1.000 | 1.000 | 48/48 | **No** |
| Reporting verbs extended (`address`, `examine`, `explore`, `investigate`, `assess`, `compare`) | **27 0 3 10** | **0.900** | 1.000 | **0.833** | **47/48** | **No** |
| Cap widened **and** verbs extended | 27 0 3 10 | 0.900 | 1.000 | 0.833 | 47/48 | **No** |

What this establishes:

1. **The cap was never the problem.** Every value from 6 to 24 produced *byte-identical* results. The
   misses are not caused by the window, and the rule that matters here is the requirement of a
   contiguous lowercase run followed immediately by the verb — a parenthetical or an unrecognised
   verb stops it regardless of how large the cap is.
2. **Allowing a parenthetical inside the window changed nothing either**, so the first miss is not
   blocked by `(CM)` in the way it appears to be.
3. **The one change that did raise sensitivity cost a true negative, and that is disqualifying.** The
   extra verbs fixed exactly one real miss and broke exactly one protected case:
   `"At least one study examined this."` became a false orange. That sentence is a statement about the
   review's own scope, not another author's finding — the author is not failing to cite anything, and
   an orange finding would accuse them of it. The trade is one caught gap for one false accusation, and
   a false accusation is the more expensive error.

So the four misses stand, each with its own identified cause rather than as a tuning knob: one is
blocked by an unrecognised reporting verb, one has no evidence noun at all before its verb, one is
excluded deliberately, and the first is still unexplained — the parenthetical that seemed to explain
it does not. That last one is recorded as unresolved rather than papered over: it is the one case
where a plausible mechanism was tested and rejected, so the honest statement is that the cause is not
yet known.

### The metrics also found false *greens* — 12 of them

Chasing the trigger exposed the opposite error, which matters more. `attributed` requires every
checkable value in a sentence to be present in a cited source's evidence. Two classes of token were
being read as values:

* **numbered labels** — `ICD-11`, `DSM-5`, `PCL-5`. Their digits were treated as statistics.
* **bare small integers and structural pointers** — `metalloproteinase 9` (a protein name), `Figure 2`,
  `phase 2`, `Table 3`. A small integer is everywhere in extracted text, so finding one proves nothing
  and finding none proves nothing.

On the real document, **11 of 12 `attributed` verdicts rested on the digits of `ICD-11` or `DSM-5`, and
the twelfth on a protein name.** Every one was a sentence reported as supported on the strength of a
value that was never checked — the precise failure the tool exists to prevent, produced by the tool.
After masking labels and structural references, and requiring a bare number to be large or fractional
before it may serve as a value, the count of greens on that document is **zero**, which is the correct
answer: with those sources, no sentence's distinctive value could be confirmed.

**C. The safety properties**, both asserted rather than merely printed:

```
SAFETY PROPERTIES HOLD:
  conflict precision is 1.000 over 26 conflict case(s) -- no false accusation
  trigger specificity is 1.000 over 40 unseen real sentences -- no sentence was
    told it needs a citation when it did not
```

Per state, all at precision 1.000 and recall 1.000: `attributed` (3), `synthesis` (3),
`unverifiable` (5), `unattributed` (5), `conflict` (4), `no_citation_needed` (6).

### The red bar, measured separately

Three cases decide whether an accusation is allowed, each in its own source configuration:

| Case | Evidence | Link | Expected | Result |
|---|---|---|---|---|
| contradiction against a value copied verbatim into the ledger | `recorded_estimate` | exact | `conflict` (D08) | ✅ |
| contradiction against the extractor's own prose | `prose_summary` | exact | `unverifiable` (D12) | ✅ |
| contradiction against a source linked only by a title match | `primary` | inferred | `unverifiable` (D11) | ✅ |

The benchmark also asserts the bar **structurally**: no conflict in any group may carry
`link_confidence != exact` or evidence weaker than primary text or a recorded value. Precision alone
would not catch a red that reached the right answer through the wrong door.

The cost is real and is reported rather than absorbed: **conflict recall falls**, because a contradiction
visible only through a prose summary is no longer asserted. That is the trade — an accusation must be
defensible — and the case is named in the table above so the loss is visible.

**Why conflict precision is the number that matters.** A red finding asserts a citation to a work
that does not exist, a citation to a retracted source, or a value that contradicts the source. Each is
an accusation, and a tool that produces false accusations is worse than one that produces none. The
benchmark therefore fails loudly if conflict precision drops below 1.000, and the design keeps red
narrow on purpose: a number merely *absent* from extracted evidence is a warning, never a conflict,
because PDF extraction routinely loses tables and figures.

### What this does not show — read this before quoting the 100%

The labelled set was written by the same author as the rule table, from the same reading of the
requirements. A perfect score therefore shows the rules **do what they were designed to do**; it does
not show they generalise to prose the author did not choose. There is also only one case per
distinction in several classes. The conflict class was widened for exactly this reason: it held four
positives in the first revision, which put the Wilson lower bound on conflict precision at 51.0%,
and now holds twenty-six, which puts it at 87.1%.

The honest complement is the **unlabelled** distribution over a real 1,027-sentence document (a
34-page PTSD review). It was measured twice, and the difference between the two runs is the point
rather than a footnote.

**Run 1 — 62 sources identified, no source text supplied at all (`--offline`).** Every cited sentence
is `unverifiable`: a citation that cannot be checked is not a citation that passed.

| State | Sentences | Share |
|---|---|---|
| `no_citation_needed` | 524 | 51.0% |
| `unattributed` | 306 | 29.8% |
| `unverifiable` | 197 | 19.2% |
| `synthesis` | **0** | 0% |
| `attributed` | **0** | 0% |
| `conflict` | 0 | 0% |

Coverage: **0/503 = 0.0%**. The run exits **3 (`insufficient_evidence`)**.

**Run 2 — the same 62 sources, with open-access acquisition enabled** (Europe PMC full text; no rule
changed). 47 sources end up with evidence and 36 of the 48 citing sources become checkable:

| State | Run 1 (no sources) | Run 2 (open access fetched) |
|---|---|---|
| `synthesis` | 0 | **143** (13.9%) |
| `unverifiable` | 197 | **54** (5.3%) |
| `no_citation_needed` | 524 | 524 (51.0%) |
| `unattributed` | 306 | 306 (29.8%) |
| `attributed` | 0 | 0 |
| `conflict` | 0 | 0 |
| **coverage** (attributed + synthesis) / sentences carrying a claim | **0/503 = 0.0%** | **143/503 = 28.4%** |

(391 of the 1,027 sentences require a citation, and 503 carry a claim. These are the figures after
both accuracy fixes above. For comparison, the same document under the first revision reported
`attributed` 12, `unattributed` 174 and `no_citation_needed` 656 — twelve false greens and 132 missed
attribution-requiring sentences.)

Run 2 still exits **3**: 12 of the 48 citing sources could not be obtained (11 of them transiently),
so the evidence gap is recorded rather than absorbed, and the worklist names each one. Zero conflicts
in both runs is the correct result for that document, not a good one: `conflict` requires evidence
strong enough to convict, and no sentence's value could be confirmed against a source the tool holds
in full. Supply the remaining PDFs and the `unverifiable` block converts into `attributed`,
`synthesis`, or a genuine finding.

Three defects were found by running the tools rather than by inspection, and all three are now fixed:

1. **47 false conflicts from a bibliography.** The reference list of the source document was being
   graded as prose, so `[Internet]` and `[cited 2026]` became fabricated citations. Reference entries
   are now marked structural, recognised by a long trailing numbered run or a `References` heading.
2. **DOIs truncated at a parenthesis.** `10.1016/s2215-0366(22)00375-3` is a real Lancet DOI; a
   trailing-`)` strip silently resolved citation `[1]` to the wrong paper.
3. **`n_participants` and `follow_up` were not treatable as evidence**, so "1000 adults were
   randomised" could never be `attributed` against a ledger that recorded exactly that.
4. **A one-entry bibliography was not recognised.** A `References` heading with a single numbered entry
   fell below the run-length floor, so the entry was graded as prose and the document's own citation
   became a **fabricated-citation** finding — the most damaging thing this tool can say. Short
   bibliographies are now recognised when the entries look bibliographic, and the end-to-end harness
   builds a DOCX with a numbered bibliography so the path is covered.
5. **Short titles never matched a bibliography entry.** A title under five words was skipped, creating a
   *second*, evidence-less source for the same work, so the citation resolved to a source with no
   evidence and the sentence became `unverifiable` instead of being checked. Titles of three or more
   content words now match, with a token-overlap fallback.
6. **A ledger's context-only row could never be upgraded.** A row holding only
   `population`/`intervention` has text but no finding, and the attachment check tested for *absent
   text* rather than insufficient strength — so the worklist could never close for exactly the sources
   it named.

### Evidence acquisition, measured on a real reference list

`_acquire.py` was measured against all 60 DOIs of a real clinical bibliography, using the module's own
harness with the network enabled and a warm cache.

| Tier | Mechanism | Yield |
|---|---|---|
| B | Europe PMC open-access full text (keyless) | **20 / 60 = 33.3%** |
| C | open-access PDF via OpenAlex | **0 / 60** |
| D | optional `paper-search` CLI subprocess | **0 / 60** |
| | identity mismatches | **0** |

Tier C fails because publisher `/pdf` endpoints answer a non-browser client with `403` or an HTML error
page, and where OpenAlex holds no `pdf_url` the fallback is a bare `doi.org` resolver — a landing page
rather than a file, which the module refuses to fetch. Tier D only works by re-reading a PMCID that
tier B has already established is open access. Both are kept because they cost nothing when they fail
and carry other corpora, and both are reported at zero rather than quietly dropped.

The failures: 26 records Europe PMC reports as not open access, 13 with no Europe PMC record, 28 with
no OpenAlex `pdf_url`, and 12 whose `pdf_url` is on a publisher host that refuses. An earlier probe of
14 of the same DOIs suggested ~14%; the measured 20/60 replaced it, because a figure extrapolated from
a tenth of the list was wrong in both directions.

Two consequences that matter more than the number: acquisition took the run from **0 to 36 checkable
citing sources** (re-measured end to end on the same document; the module harness alone reports 20/60
DOIs yielding usable full text, and 47 of the 62 sources end up with abstract-or-better evidence), and
a source upgraded from an abstract to full text changes what it may support — an abstract can never
convict a contradiction, full text can. The wiring bug that made acquisition skip those upgrades (it
gated on "has any checkable evidence" rather than "has primary evidence") was found by the harness that
measured the yield, not by inspection.

### The advisory channel is not measured for accuracy

No calibrated grader ships with `citation-report`, so there is nothing whose accuracy could be
measured. That is deliberate: the repository's own measurement of a comparable classifier found
**21.6%** on a seven-way choice against a **20.6%** majority baseline, and it **failed a causality
trap** that a regular expression caught
(`skills/medical-narrative-review/references/advisory_decision_plan.md`). The advisory channel is
therefore measured for **inertness** instead, by `skills/citation-report/scripts/selftest.sh`:
rendering with `--advisory off` and with grades supplied must leave the deterministic verdicts, the
coverage arithmetic, the gate verdict, the process exit code, and the sequence of painted states
identical. It does.

---

## 6. Caveats

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

## 7. Reproduce

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

---

## 8. OCR: what the engine actually did, and why the bar is provenance

Measured on this machine with tesseract 5.5.3 (`eng`, 300 dpi rasterisation via poppler), against a
one-page image PDF built with Pillow — no text layer, so every character came from OCR.

| Fixture | What OCR returned | Verdict |
|---|---|---|
| two sentences, 1,700 × 2,200 px | 178 characters, `method=tesseract`, `transcribed=true` | read, and labelled |
| the same page, upper-case `CI` | `95% Cl` — an upper-case I read as a lower-case l | one character from a false accusation |
| scanned manuscript `(HR 0.50)` vs a source recording `HR 0.80` | transcribed correctly | `unverifiable` / **D13**, exit 0 |
| the identical sentence as `.md` (control) | read from the text layer | `conflict` / **D08**, exit 1 |
| a scanned *source* PDF, cited by a text manuscript | transcribed, `evidence_origin = ocr:S001.pdf:tesseract:eng` | `unverifiable` / **D13**, exit 0 |
| a blank page | no text | `ocr_empty`, exit 4 (input gap) |
| the same page image, **RapidOCR** | `(HR 0.80, 95% CI 0.72 to 0.89)` — correct, 0.99 confidence | read, and named `rapidocr` in the provenance |
| a German scan, `--ocr-lang deu` | read with the German data | `transcription: tesseract:deu` |

The control row is the point of the whole tier: the same words, the same values, the same source — and
a different verdict, because one side was a machine's reading. Without the rule, the scanned-manuscript
row would have been a red finding against an author, resting on OCR.

The cross-engine row is the reason the engine is part of the provenance: on one page image the two
engines disagreed about a single character, and only one of them was right. It is also why engine
agreement does not lift the D13 bar — two engines agreeing is still a machine reading, and the rule
is about provenance rather than confidence.

**Not measured here:** any error *rate*. One misread character in one page is evidence that the failure
mode is real, not an estimate of how often it occurs. No scan corpus was assembled, so no
per-character or per-value accuracy figure is claimed for OCR, and the tier's honesty rests on the
provenance rule rather than on the engine's quality.
