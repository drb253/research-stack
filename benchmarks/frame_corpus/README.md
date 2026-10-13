# frame_corpus — labelled corpus for ORI Guideline 4 (structure)

The toolkit's lexical score cannot see a frame copy: a rewrite that swaps every
content word but keeps the function-word frame. ORI Guideline 4 calls that
rewrite plagiarism. This directory holds the labelled corpus that measures
whether any stdlib-only structural measure can detect it, and the decision that
followed.

## Files

| File | What it is |
|---|---|
| `gen_frame_corpus.py` | the deterministic generator and label audit |
| `source_pairs.json` | 54 frozen bioRxiv/medRxiv preprint-vs-published pairs (real text) |
| `corpus.json` | the generated corpus: 227 labelled items, each a (draft, candidate document) pair |
| `bench_frame_copy.json` | the benchmark result the current toolkit shipping decision rests on |

`../bench_frame_copy.py` reads `corpus.json` offline. `../../skills/originality-check/eval.md`
carries the full measure table.

## Classes and label audit

| Class | n | Label | Machine-generated | Source |
|---|---|---|---|---|
| `frame_copy` | 108 | positive | **yes** | a real sentence the toolkit resolves, with every content word swapped for a different content word |
| `human_frame_copy` | 3 | positive (reported separately) | no | hand-written G4-style copies from `bench_ori_guide.py` |
| `unrelated` | 54 | negative | no | a real sentence against a **different** real document from the 54 pairs |
| `real_revision` | 54 | negative | no | a preprint sentence against its **own** published abstract (same work, revised by the authors) |
| `legit_paraphrase` | 8 | negative | no | ORI guide versions 5 and 6, which the guide labels correctly paraphrased |

Totals: 227 items. 111 positives (108 machine-generated, 3 hand-written), 116
negatives. The decision uses `frame_copy` against all three negative classes;
`human_frame_copy` is reported separately (n=3 cannot decide anything).

## What the generator asserts

`python3 gen_frame_corpus.py` fails unless every one of these holds:

1. For every `frame_copy`, the function-word sequence is **identical** to its
   anchor. The swap cannot have moved the frame.
2. For every `frame_copy`, no content word the swap touched survives, and the
   swapped content words do not overlap the candidate document. The lexical
   score is therefore near zero by construction, which is the point.
3. The toolkit's own local-corpus adapter resolves every `frame_copy`,
   `real_revision` and `human_frame_copy` anchor against its own document
   (165/165 in the frozen corpus).

The substitution is a controlled structural probe, not a fluency benchmark: the
replacement pool is a fixed word list, so the generated sentences are
ungrammatical in places. Only the frame is under test.

## Regenerating

```bash
python3 gen_frame_corpus.py            # deterministic; rewrites corpus.json
python3 gen_frame_corpus.py --audit    # check the labels, write nothing
python3 gen_frame_corpus.py --fetch    # refresh source_pairs.json (network: bioRxiv + OpenAlex)
```

The corpus is a pure function of `source_pairs.json`, the ORI text in
`../bench_ori_guide.py` and the fixed seed in the generator. It uses no clock,
no network and no filesystem entropy, so two runs are byte-identical.
