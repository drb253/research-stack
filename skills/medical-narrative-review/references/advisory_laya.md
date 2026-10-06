# Optional Advisory Classifier (Laya)

**Status: optional, opt-in, advisory only. It can never change a gate verdict.**

Nothing requires it. If it is absent, unavailable, or wrong, the review pipeline behaves exactly as
documented in `SKILL.md`, and the submission gate stays deterministic, offline, and reproducible.

## What it is, and what it is not

[Laya](https://github.com/NandhaKishorM/laya) is a **local, on-device decision engine** (Apache-2.0,
currently beta). It returns three typed decisions from a single forward pass:

| Primitive | Output | Shape |
|---|---|---|
| `choice` | top label, per-option probabilities, confidence | categorical |
| `score` | expected level on an ordinal rubric | ordered label |
| `noul` | calibrated P(true) | 0.0-1.0 |

It is **not** a knowledge base, **not** a citation verifier, and **not** a factual checker. It cannot
know whether a DOI resolves, whether a hazard ratio belongs to a named trial, or whether a percentage
recomputes. It therefore has no role in verifying sources, numbers, or references.

## The hard rule

A model output may **never** set, change, or veto:

- `verification_status`, `retraction_status`, `inclusion_status`, `exclusion_reason`;
- any `error`-severity finding, and therefore any `gate.py` verdict;
- any number, effect estimate, or reference in the deliverable.

Advisory findings are emitted as `info` severity with codes prefixed `ADVISORY_`, and their detail text
ends with "advisory, model-generated, not a gate input". When an advisory and a deterministic check
disagree, **the deterministic check wins and you investigate the model**, not the check.

## The two uses worth having

### 1. Causal-language and hedging flags the regex misses

`lint_manuscript.py` detects causal verbs by pattern matching, which is brittle by construction: it has
already produced false positives on "leading cause of death" and on legitimate stricter-threshold
wording. A calibrated classifier covers phrasing the patterns do not.

```text
laya_predict
  state:     {"sentence": "<the sentence from manuscript_cited.md>"}
  questions: {"asserts_causation": {"type": "noul",
              "instructions": "Does `sentence` assert that one thing causally produces another, for example that a treatment causes an outcome?"}}
```

```text
laya_predict
  state:     {"sentence": "<the sentence>"}
  questions: {"hedging": {"type": "score",
              "instructions": "How hedged is `sentence`?",
              "criteria": {"0": "unhedged: the claim is stated as certain",
                           "1": "partly hedged",
                           "2": "fully hedged: explicitly uncertain or explicitly not causal"}}}
```

### 2. Certainty-versus-hedging mismatch

Compare the hedging level of the sentences carrying a claim marker against that claim's recorded
`certainty` in `claims.csv`:

- claim `certainty` is `low` or `very_low` but the prose reads as unhedged (hedging level 0) -> flag;
- claim `certainty` is `high` but every sentence hedges to level 2 -> flag as understated.

This is the one check a classifier adds that pattern matching genuinely cannot, because it compares two
things the ledger already records.



## How to call it, and how to read the answer

`laya_predict` (MCP) wraps the result as `{"answers": {...}, "routing": ...}`. The per-question
answer dict is keyed by the primitive that answered:

| Question type | Read this key | Meaning |
|---|---|---|
| `noul` | `answers.<question>.noul` | calibrated P(true), 0.0-1.0 |
| `score` | `answers.<question>.score` | expected level on the criteria scale |
| `score` | `answers.<question>.legend` | criteria mapping the model returned |
| `choice` | `answers.<question>.choice` | top label |
| `choice` | `answers.<question>.probability`, `.probabilities` | top-label probability, full distribution |
| any | `answers.<question>.type` | the primitive that actually answered |

**`criteria` differs by primitive**, and getting it wrong raises a library validation error:

- `choice` -> a **dict** of `{label: description}`;
- `score` -> a **list** of level descriptions, index 0 first (`{"0": "..."}` is rejected:
  "a score question takes 'criteria' as a list of level descriptions, index 0 first");
- `noul` -> no criteria needed.

A question key missing from `answers` means the call failed; treat that as the advisory step being
unavailable, never as a negative finding. This shape was confirmed against the project's own test
suite and by calling it, not inferred from the README.

## Measured, not assumed: shadow run on six known sentences

Run against `convaiinnovations/laya` on this machine with the two questions above. Hedging is on a
0-2 scale (0 = unhedged, 2 = fully hedged).

| Sentence (defect known in advance) | P(asserts causation) | Hedging |
|---|---|---|
| "Pembrolizumab plus chemotherapy prolonged overall survival versus chemotherapy alone." | 0.768 | 0.88 |
| "Commensal abundance was associated with response, an association that cannot establish causation." | 0.148 | 0.977 |
| **"This regimen cures every patient and has no side effects."** (the trap) | **0.041** | **0.187** |
| "In mouse models, optimal anti-CTLA-4 responses required specific Bacteroides species." | 0.129 | 0.818 |
| "The evidence may suggest a modest association, although further study is required." | 0.117 | 1.519 |
| "Smoking causes lung cancer." | 0.807 | 0.35 |

**What this shows:**

- **The causality axis failed the trap.** The most egregious overclaim in the set scored the *lowest*
  P(asserts causation) of all six (0.041) — lower than a properly hedged sentence. The deterministic
  `OVERCLAIM_RE`/`ABSOLUTE_RE` catch "cures" + "every patient" + "no side effects" immediately. So the
  classifier is **not** an improvement on the causal check, and must not be used in its place.
- **The hedging axis was informative and correctly ordered.** The trap ranked least hedged of all six
  (0.187), the fully hedged sentence most hedged (1.519), and the flat assertion low (0.35). That is a
  usable signal for the certainty-versus-hedging check.
- **Conclusion adopted:** use the `score`/hedging axis for the certainty-mismatch check; keep the
  causality axis out of any default path. Neither may gate.

Six sentences is a probe, not an evaluation. Reproduce it with more of your own text before relying
on either axis.


## Required server configuration (this is what makes the MCP surface work)

The server preloads checkpoints at startup. Out of the box it preloads **`english` *and*
`multilingual`**, so a first start fetches another ~643 MB and blocks the MCP handshake — which is
exactly what happened here until the environment was constrained. The server's own docstring documents
the controls:

```jsonc
// ~/.cline/data/settings/cline_mcp_settings.json
"laya": {
  "command": "~/.local/share/laya-mcp-server/.venv/bin/laya-mcp-server",
  "env": {
    "LAYA_MODELS": "english",   // preload only the checkpoint that is cached; default is "english,multilingual"
    "LAYA_PRELOAD": "0"        // build checkpoints lazily: never block the handshake on model loading
  }
}
```

Verified after this change: handshake completes, **8 tools** are advertised (`laya_status`,
`laya_route`, `laya_predict`, `laya_predict_batch`, `laya_route_batch`, `laya_shortlist`,
`laya_preset`, `laya_decide`), and a real `laya_predict` call returns a typed answer.

Set `LAYA_MODELS` to include other checkpoints only when you actually need them, and only after
pre-downloading once with a single process.

## The verified response shape

```json
{
  "answers": {
    "hedging": {
      "type": "score",
      "score": 0.6004,
      "legend": {"0": "unhedged", "1": "partly hedged", "2": "fully hedged"},
      "probabilities": {"0": 0.5008, "1": 0.398, "2": 0.1012},
      "confidence": 0.14,
      "answer_confidence": 0.5008,
      "action": {"act_probability": 1.0}
    }
  },
  "routing": {"model": "english", "repo": "convaiinnovations/laya"}
}
```

Beyond `answers.<question>.<primitive>`, read `confidence` and `answer_confidence` when judging how
much to trust a call, and `routing.model` to confirm which checkpoint answered. On this machine
`confidence` came back as **0.14**, consistent with the uncalibrated-temperature warning below: do not
treat these numbers as calibrated probabilities.

## Operational caveats found while wiring this up

These are real behaviours of the server as installed, and they matter for a good first run:

1. **Startup preloads checkpoints and can block the handshake.** Constrain it with
   `LAYA_MODELS` and `LAYA_PRELOAD` as shown above, or pre-download everything first.
2. **Read disk usage correctly.** Hugging Face stores weight blobs in a shared `hub/blobs/` directory
   and symlinks them into the per-repo folder, so `du -sh` on `models--convaiinnovations--laya`
   reports a few megabytes while ~804 MB of blobs sit alongside it. Measure with
   `du -sh ~/.cache/huggingface` (~807 MB for the base checkpoint here). A small number from the
   repo folder does **not** mean the download was lost.
3. **Download with a single process** as general practice. Concurrent resolvers of the same repository
   can contend on the same partial files; run the pre-download once, with nothing else using Laya.
4. **Unauthenticated downloads are rate limited.** Export `HF_TOKEN` for a faster, resumable fetch.
5. **The `typed-decisions` checkpoint is lazy** and is pulled only when a question schema routes to
   it, so a first call may fetch more than the default checkpoint.

Pre-download once, then verify:

```bash
cd ~/.local/share/laya-mcp-server
HF_TOKEN=... .venv/bin/python -c "import laya; laya.load('convaiinnovations/laya'); print('weights ready')"
```

After that, subsequent server starts are fast and the advisory pass is a normal-speed call.


Write findings to `advisory.json` in the review workspace so they appear in the same report as
everything else. Keep it metadata-only: line numbers and claim IDs, not manuscript prose.

```json
{
  "generator": "laya-mcp-server (advisory only)",
  "model": "convaiinnovations/laya",
  "generated_on": "2026-09-28",
  "findings": [
    {"type": "causal_claim", "location": "line:88", "probability": 0.91},
    {"type": "hedging_mismatch", "claim_id": "C004", "certainty": "low", "hedging_score": 0.22},
    {"type": "absolute_language", "location": "line:12", "probability": 0.77}
  ]
}
```

Consumed by:

```bash
python3 scripts/lint_manuscript.py final/manuscript_cited.md --sections --advisory advisory.json
```

`gate.py` passes it automatically when `advisory.json` exists in the workspace. Malformed findings
produce `ADVISORY_FINDING_WITHOUT_TYPE`, `ADVISORY_INVALID_VALUE`, or `ADVISORY_VALUE_OUT_OF_RANGE`
warnings (never errors), so a broken advisory file cannot block a submission.

## Cost, and why it is not bundled

| Item | Size |
|---|---|
| Python environment (torch, transformers, mcp) | ~715 MB |
| Model weights, one checkpoint | ~843 MB |
| Model weights, all three checkpoints (default, typed-decisions, multilingual) | ~2.4 GB |

Weights come from Hugging Face on first use and are **not** vendored here. Unauthenticated downloads
are rate limited; set `HF_TOKEN` for a faster fetch. The environment lives in its own venv
(`~/.local/share/laya-mcp-server/.venv`), so the ten deterministic commands keep working on a
stdlib-only Python, including 3.9.

Because of that cost the skill treats Laya as an optional sidecar: the agent may use it; the pipeline
never depends on it.

## Shadow mode first: measure before trusting

Do not enable anything by default. Laya's own documentation recommends staged adoption, and that is
the right call here:

1. **Shadow.** Run the classifier over a fixture manuscript whose defects are already known, and record
   its verdicts beside the deterministic findings. Do not act on the output.
2. **Compare.** Agreement on the known traps is the only evidence that the model is worth listening to
   on your text. Disagreement is a signal to investigate, never a verdict to apply.
3. **Adopt narrowly.** Only after the comparison, and only where it demonstrably adds information.
   Screening and inclusion decisions stay with humans regardless.

Laya's README reports 16-18 of 20 correct on inputs under about 4,000 tokens and 8-17 of 20 beyond
that, and notes that label sensitivity varies by checkpoint. Treat every output as a hint.

## Availability and failure behaviour

| Situation | Behaviour |
|---|---|
| MCP server not running | `laya_status` fails; the agent reports the advisory step as unavailable and continues. No script is affected |
| Model weights not yet downloaded | The first `laya_predict` triggers the download; until it completes, treat the advisory step as unavailable |
| `advisory.json` absent | `gate.py` does not pass `--advisory`; the report is identical to the dependency-free baseline |
| `advisory.json` malformed | Warning-severity codes only; the gate verdict is unaffected |
| Advisory disagrees with a deterministic finding | The deterministic finding stands; record the disagreement for review |

## Removing it

```bash
rm -f advisory.json                    # stop consuming advisories
# edit ~/.cline/data/settings/cline_mcp_settings.json and delete the "laya" entry,
# or restore cline_mcp_settings.json.bak.before-laya
rm -rf ~/.local/share/laya-mcp-server                            # reclaim the venv
rm -rf ~/.cache/huggingface/hub/models--convaiinnovations--laya  # reclaim the weights
```

Nothing in the skill imports Laya, so removal cannot break any command.
