# Cross-model verification (optional, consent-gated)

Adapted from Imbad0202/academic-research-skills-codex (ARS) v3.0
`shared/cross_model_verification.md`. **This layer is entirely optional** — every skill here
works with the single primary model. It is a *higher-confidence* check, not a requirement,
and it never silently runs.

## Why it can help

A published stress test found 31% of 68 AI-generated citations had problems — and all had
passed three rounds of *same-model* integrity checks. The root cause: the verifying and
generating model share a training distribution, so they share blind spots. A different model
family catches different hallucination patterns.

**What it improves:** different models catch different hallucination types.
**What it does not solve:** frame-lock (all LLMs share most training data) and sycophancy
(all RLHF models have it). These are degree, not kind, improvements. The post-verification
residual error rate is *not* measured — do not claim it.

## Consent boundary (hard rule)

Before any unpublished manuscript, private notes, corpus text, reviewer comments, decision
letters, or response letters is sent to an **external provider**, the agent must:

1. identify the provider, model, and content class that would be sent, and
2. obtain **explicit user consent**.

An environment variable is *not* consent to upload user content. If consent is not granted,
continue with single-model verification and report that cross-model verification was
unavailable. Never claim cross-model verification happened when it did not.

## When to use it (not everywhere)

Reserve it for high-stakes, bounded judgments: citation-integrity checks on a final
reference list, a calibrated reviewer/verdict check, or a devil's-advocate pass. It is not a
substitute for the human gates in `screening-governance.md`.

## How a check is shaped

- **Blind:** the external model inspects the bounded input **without** seeing the primary
  model's result, so it cannot simply agree.
- **Bounded:** only the specific artifact (e.g. one reference and its claimed support) is
  sent — not the whole corpus.
- **Typed diversity:** a *different family* is a genuine second substrate; a second run of
  the *same* family is not cross-family validation (report it as a separate run, not as
  independent error processes).

## Configuration (mirrors ARS; keep secrets out of config files)

- A provider key must be present in the environment (e.g. `OPENAI_API_KEY`,
  a Gemini key) plus an explicit selector for the verifier model.
- Cross-model verification is **disabled by default**; it activates only with a configured
  provider **and** explicit per-content-class consent.
- The transport selector is closed: unset or `api` uses the provider API; any other value
  fails visibly rather than falling back.

## Honesty rules

- Report which model family acted as verifier, or state plainly that no cross-model step ran.
- Never label a same-family re-run as cross-model verification.
- A verifier's disagreement is an *input to the decision step*, not a verdict — routed to the
  human in human-in-the-loop mode, or to the logged agent gate in autonomous mode.
- Do not describe any cross-model result as establishing accuracy or eliminating error.

## Local alternative

When no external provider is available or consented, use the local `laya` decision MCP for
bounded typed checks (choice / score / calibrated noul) on short inputs — but note its
documented accuracy bar (kept disabled for screening decisions here at ~77% vs a 90% bar) and
treat it as an aid, never the authoritative screen or gate.
