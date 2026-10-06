# Advisory Decision Plan: where a classifier may and may not participate

This plan governs every stage of the review. It exists because "use the classifier wherever a decision
is made" is not automatically an accuracy gain: each added model decision is an unmeasured assumption,
and the measurements so far point the other way.

Companion document: `advisory_laya.md` (contract, prompts, schemas, costs, removal).

## Measurements on a real labelled set

Evaluation set: 108 PubMed records on one topic, **stratified by publication type** so the classes are
balanced (guideline 21, meta-analysis 21, observational 20, randomised trial 20, review 14,
systematic review 11, generic 1). Ground truth is **PubMed's own expert-assigned `PublicationTypeList`**
— independent of the classifier and of the person writing the review. 102 records carry abstracts and
were used.

| Test | Result | Verdict |
|---|---|---|
| `publication_type`, **7-way choice**, title + 600-char abstract, 102 records | **22/102 = 21.6%** against a **20.6%** majority-class baseline; **78.4%** of answers were the generic classes | **FAILS the bar.** Chance-level with heavy generic-class bias. Never deploy this framing |
| `randomised_trial` vs `observational_study`, **binary choice**, 800-char abstract, 40 records | **37/40 = 92.5%** against a 50% baseline; confusion 18/20 and 19/20; answers split 21/19, matching the true 20/20 | **Accuracy passes; sample size does not.** This is the usable framing |
| Causality axis, sentence with a known defect ("cures every patient and has no side effects") | P(asserts causation) = **0.041**, the lowest of six sentences | **Failed the trap**; the deterministic `OVERCLAIM_RE` caught it |
| Hedging axis, 9 claim-bearing sentences vs `claims.csv` certainty | 0 flagged; low-certainty 0.68-1.06 vs high-certainty 0.57-1.02 | Distributions **overlap**; no demonstrated value |
| `theme` on a 3-record fixture | 3/3 | Trivial sample; not evidence |
| Library runtime warning | "this checkpoint ships invalid temperatures ... treat confidence from the affected entries as uncalibrated" | Probability thresholds are **not** trustworthy |

### The decisive insight

The same underlying question (what design is this?) scores **21.6% with 7 options** and **92.5% with
2 options** on the same kind of text. The limitation is **label-set size**, not an inability to read
the text — which matches the library shipping `laya_shortlist` precisely for "a choice question [with]
more options than the guardrails allow", and documenting "a large-criteria question" as a known
failure mode.

**Therefore the classifier must be asked small questions in a hierarchy, never one wide choice.**

## The programme, completed: six experiments on 311 real labelled records

Set: **311 records with abstracts**, harvested by publication type so four classes exceed the
50-record floor (randomised 78, observational 75, meta-analysis 75, guideline 52); systematic-review 16,
review 14 and generic 1 fall below it. Ground truth: PubMed's expert-assigned `PublicationTypeList`.
Full abstracts were also fetched for every record (median 1,730 characters, max 6,264).

| # | Configuration | Composed accuracy | Verdict |
|---|---|---|---|
| 1 | Single 7-way choice, 600-char abstracts | **21.6%** (22/102) | FAIL — chance-level, 78% generic answers |
| 2 | Hierarchy, full taxonomy (7 leaves) | **66.2%** (206/311) | FAIL |
| 3 | **Hierarchy, taxonomy narrowed to what abstracts state (5 leaves)** | **77.2%** (240/311) | **FAIL — best configuration found** |
| 4 | `head_max_len` sweep 128 / 256 / 512 / 1024 | 17.6% at **every** setting, byte-identical answers | **Lever has no effect — hypothesis rejected** |
| 5 | Full abstracts + lexical criteria + three-phrasing majority vote | **51.8%** (161/311) | **Actively worse** |
| 6 | Binary randomised-vs-observational, 800-char abstracts | 92.5% (37/40), and 89.5% (137/153) on the larger set | Best single rung; straddles the bar |

Rung detail for the best configuration (#3):

| Rung | Accuracy | Baseline | Notes |
|---|---|---|---|
| Q1 primary vs synthesis (binary) | 88.4% (275/311) | 50.8% | 128/153 and 147/158 |
| Q2 randomised vs observational (binary) | 89.5% (137/153) | 51.0% | observational 74/75 (99%); randomised 63/78 (81%) |
| Q3n systematic-synthesis vs review vs guideline (3-way) | 86.0% (135/157) | 58.0% | guideline 49/52; systematic-synthesis 81/91; **review 5/14** |

### Why experiment 5 failed, and why that matters

Passing full abstracts at an 8,192-token window made accuracy collapse toward a single label
(Q1 -> 155/158 "synthesis", Q2 -> 75/75 "observational" with randomised recall halving to 50%). This
reproduces Laya's own long-context measurement: 16-18 of 20 correct under about 4,000 tokens,
"more variable beyond", with the README advising you to check long-document accuracy on your own data.
**The classifier's usable regime is short text with few options** — which is precisely where it already
scores 88-92%, and precisely the opposite of what a ledger-field classification task needs.

### Final verdict on Tier B

**No Tier B stage is enabled, and no configuration tested brings it within reach.** The best is
**77.2%** against a **90%** bar. A ledger field at 77% would silently mislabel about one study in four
in the evidence table — an error the reader cannot detect and the gate cannot catch, because that
column is hand-entered ground truth the checks are not designed to question.

Four findings worth keeping:

1. **Architecture matters more than tuning.** Hierarchy plus a taxonomy matched to the text nearly
   quadrupled accuracy (21.6% -> 77.2%). Neither a budget sweep nor a paraphrase ensemble came close
   to that gain.
2. **Two rungs straddle the bar** (88.4%, 89.5%). Randomised-vs-observational detection is the one
   genuinely near-usable capability, with 99% observational recall and 81% on randomised.
3. **`review` is unlearnable** (5/14) because narrative reviews state no method. No architecture
   recovers a label the text does not carry.
4. **More text is not better here.** Feeding the full abstract made it worse, not better, in line with
   the project's own long-context warning.

Tier B is closed pending a different model, a full-text methods section as input (untested, and the
one plausible route to more signal), or a much narrower question than a taxonomy field requires.



## Required architecture before any Tier B stage can be enabled

```
Q1 (binary):  primary study, or synthesis/recommendation document?
  -> primary:       Q2 (binary): randomised or observational?          measured 92.5%
  -> synthesis:     Q3 (4-way):  meta-analysis / systematic review / narrative review / guideline
```

Rules for this architecture:

1. Every rung is a **small** choice (2-4 labels). A rung with more than 4 labels must be decomposed or
   routed through `laya_shortlist` and re-measured.
2. Each rung is measured **separately** against the labelled set. A high score on one rung never
   licenses the next.
3. The composed accuracy is the product of the rungs, so it must be reported as composed accuracy, not
   as the best rung's score.
4. Even when a rung clears the bar, output is a **suggestion for human confirmation**, never a value
   written into `sources.csv` by the tool.


## Tier C: structurally forbidden (not a matter of measurement)

These stages cannot use it, because the decision is a **fact about the world** that a text-labelling
model has no mechanism to establish. The model never sees the source, the DOI, or the registry; it
sees only the text you pass it.

| Stage | Why a classifier cannot decide it |
|---|---|
| Resolving a DOI/PMID, matching title/author/journal/year | Requires identifier retrieval against an external index. No knowledge base, no retrieval, no answer |
| `verification_status`, `retraction_status` | Properties of the published record, not of a snippet of its text |
| `inclusion_status`, `exclusion_reason` | A scientific decision that must be reproducible and auditable; a model verdict is neither |
| Any extracted number, effect estimate, sample size, interval | Numbers are copied verbatim from the source with a locator, never inferred |
| Reference forming, citation numbering, duplicate detection | Deterministic string and identifier operations; a model adds error, not accuracy |
| PRISMA arithmetic | Exact arithmetic; the flow gate must fail closed |
| Any `error`-severity finding or `gate.py` verdict | The verdict must be deterministic and reproducible; a model input destroys that |
| Removing an `UNVERIFIED` placeholder | Removing a placeholder is a claim of verification |

## Tier A: allowed today, advisory only

| Use | Where | Status |
|---|---|---|
| Hedging/certainty observation | prose, after `final/manuscript_cited.md` | Measured weak (no separation). Allowed as a recorded observation, never as a flag implying an error |
| Theme proposal for a new source | extraction, as a *suggestion* for the human | Measured 3/3 on a trivial sample; treat as a prompt, not a value |
| Prompt/guardrail check on user requests | any stage | Does not touch the review; the skill already refuses policy-bypass requests |


## Tier B: may be enabled only after it passes the bar

Candidates, in the order worth testing. All would be **suggestions presented to a human**, never
values written into a ledger by the tool.

| Candidate | Ground truth available | Measured |
|---|---|---|
| `publication_type`, 7-way | PubMed `PublicationTypeList` | **21.6% vs 20.6% baseline — FAILS** |
| `randomised_trial` vs `observational_study`, binary | PubMed `PublicationTypeList` | **92.5% (37/40) — passes accuracy, 40 records is below the 50 floor** |
| `study_design`, remaining rungs (Q1, Q3) | PubMed types | not yet measured |
| `direction` (supports/refutes/mixed/neutral) | **not available in PubMed metadata**; needs human-labelled claim/direction pairs from real reviews | blocked on labels |
| Inclusion pre-ranking of retrieved titles | your own screening decisions | not yet measured; even if enabled it may only order the worklist, never set `inclusion_status` |
| Section-role labelling of paragraphs | your own headings | not yet measured; low value |

### The enabling bar

A candidate stage may be offered to the user (still advisory, still confirmed by a human) only when
all of the following hold on **at least 50 labelled records**, not on a smoke test:

1. **Agreement >= 90%** with the recorded ground truth on that field.
2. **No generic-class bias**: the most common wrong answer must not be the broadest label
   (`journal_article`, `other`). The 1/3 result above failed precisely here.
3. **Disagreements recorded**, not hidden, and reviewed by a human.
4. **Thresholds avoided** where possible, because the checkpoint's probabilities are uncalibrated;
   prefer the argmax label and require human confirmation regardless.
5. **Re-measured after any model or checkpoint change.**

Ground truth for the first three candidates already exists in the ledgers, so the evaluation is cheap
and repeatable: build a labelled set from `sources.csv` and `claims.csv`, run the classifier over it,
and record agreement, the confusion matrix, and the bias check.

## Why "almost all stages" would reduce accuracy here

1. **It cannot act at the stages where accuracy is actually at risk.** Citation verification, number
   fidelity, and reference assembling are the failure modes that matter, and none of them is a text
   classification task.
2. **Every added stage adds false positives and false negatives** on top of the deterministic checks.
   Advisory output cannot remove an error the checks already catch, but it can send a human down a
   wrong path: the 0.041 causality score on the worst sentence in the set is exactly that.
3. **The probabilities are uncalibrated** in the shipped checkpoint by the library's own admission, so
   the natural tuning knob (a confidence threshold) is not available.
4. **It multiplies review burden**: a human must adjudicate model suggestions at every stage, while the
   deterministic checks already produce a defensible verdict.

The defensible version of "use it where decisions are made" is therefore: **use it to generate
candidate judgments about text, measure each against labelled ground truth, enable only those that
clear the bar, and keep every real decision — verification, inclusion, numbers, the gate — with the
deterministic checks and a named human.**

## Stage-by-stage summary

| Phase | Decision being made | Who decides | Classifier role |
|---|---|---|---|
| 1 Scaffold | scope, PICO, venue limits | human | none |
| 2 Search | which queries, which databases | agent + human | none (no retrieval) |
| 3 Verify | does this identifier resolve; does metadata match | deterministic tools + human | **forbidden** |
| 4 Extract | what the source reports, with locators | human reading the source | Tier B suggestions only, after the bar |
| 5 Claims | what is claimed, how certain, which sources | human | Tier B `direction` candidate, after the bar |
| 6 Draft | wording, hedging, structure | human | Tier A hedging observation |
| 7 Displays | what the ledgers say | deterministic scripts | none |
| 8 Finalise | numbering, arithmetic, gate verdict | deterministic scripts | Tier A observation, `info` only, never an error |
| 9 Export | format fidelity | deterministic scripts | none |
