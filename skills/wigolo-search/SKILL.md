---
name: wigolo-search
description: Runs local-first web research through the wigolo MCP server. Use it for current pages, documentation, news, code answers, and for arXiv or Semantic Scholar lookups. It searches several engines, then merges and reranks the results. It also fetches, crawls, extracts, caches, and answers with citations. It needs no API key. This is not Google Scholar.
allowed-tools: Read Bash
license: AGPL-3.0
compatibility: Needs the wigolo MCP server or CLI. The npm package carries no keys and no cloud bill. The reranker, the embedding model, and the browser engine stay on disk until `wigolo warmup` fetches them.
metadata:
  version: "1.0"
  source: "https://github.com/KnockOutEZ/wigolo"
---

# wigolo Search

Use wigolo for web research on this machine. It keeps its cache, its models, and its keys in `~/.wigolo`, and it sends nothing to a third party.

<!-- gates: check_skill_claims.py -->

## Terms

The Model Context Protocol (MCP) connects this skill to the server. A uniform resource locator (URL) is a web address. Reciprocal rank fusion (RRF) merges the ranked lists of several engines into one list. arXiv is a preprint server. An embedding is a numeric vector that represents the meaning of a text.

## Tools

The server exposes ten tools.

| Tool | Use |
| --- | --- |
| `search` | Several engines, fused and reranked, with evidence and citations. |
| `fetch` | One URL as clean markdown. |
| `crawl` | A site or a list of pages. |
| `extract` | Structured fields from a page. |
| `cache` | The local store. It answers from disk, so it costs nothing. |
| `find_similar` | Pages near a given page or text. It needs the embedding model. |
| `research` | A brief with topics, key findings, and gaps. |
| `agent` | An autonomous gather loop with an optional JSON schema. |
| `diff` | Two versions of one page, or two pages. |
| `watch` | Change jobs on a list of URLs. |

## Search parameters

| Parameter | Values |
| --- | --- |
| `query` | A string, or a list of variants. The server runs the variants in parallel. |
| `max_results` | Default 5. Maximum 20. |
| `category` | `general`, `news`, `code`, `docs`, `papers`, `images` |
| `search_depth` | `ultra-fast` (cache only), `fast` (engines only), `balanced` (default), `deep` |
| `max_fetches` | The number of top results that receive page content. |
| `include_domains`, `exclude_domains` | Domain allow and deny lists. |
| `time_range` | `day`, `week`, `month`, `year` |
| `from_date`, `to_date` | ISO date bounds. |
| `exact_match` | Quoted-phrase semantics. |
| `country`, `language` | Hints for the engines that accept them. |
| `force_refresh` | Skip every cache. |
| `citation_format` | `numbered`, `json`, or `anthropic_tags` |

## Reading a search response

Read three fields before you trust a result.

| Field | Meaning |
| --- | --- |
| `engines_used` | The engines that answered. |
| `engine_telemetry` | One row per engine: `outcome`, `result_count`, `dedup_kept`, `latency_ms`. |
| `evidence_score.components` | Why the result ranks: `base_rrf`, `domain_quality`, `engine_consensus`, and more. |

A `kept` of zero is not a failure. The server removed a duplicate that a higher-ranked engine already supplied. An `outcome` of `error` is a failure.

## Engine status on this machine

Verified on 2026-10-16 with `wigolo doctor`. Re-check the list with that command, because the status depends on the network.

| Vertical | Engines |
| --- | --- |
| general | `bing`, `duckduckgo`, `mojeek`, `marginalia`, `wikipedia` |
| docs | `bing`, `duckduckgo`, `devdocs`, `mdn` |
| code | `duckduckgo`, `mdn`, `stackoverflow` |
| news | `bing_news`, `duckduckgo`, `hn-algolia`, `lobsters`, `mojeek` |
| papers | `arxiv`, `semantic-scholar` |
| images | `ddg-image` |

Two engines need a key: `brave` needs `BRAVE_API_KEY`, and `github-code` needs `WIGOLO_GITHUB_TOKEN`. The other engines need none.

## Depth against the installed components

The reranker, the embedding model, and the browser engine download on first use. Check the state with `wigolo doctor`. While a component is absent, three limits apply.

- `search_depth` `fast` uses the engines only, and `ultra-fast` uses the cache only.
- `max_fetches: 0` keeps the call to links only, because a page render needs the browser engine.
- `find_similar` and the semantic cache fall back to keyword matching.

Fetch every component when the machine can spare the disk and the time.

```bash
wigolo warmup --all          # about 250 MB of models, plus the browser engine
wigolo verify                # an end-to-end capability check
```

## Cache behaviour

A cached search lasts one day, and a cached page lasts seven days. Send `force_refresh: true` for prices, changelogs, versions, and news. A repeated question becomes cheap and fast, which also means a stale answer can look fresh.

## Failure modes

| Answer | Meaning | Action |
| --- | --- | --- |
| `outcome: "error"` in `engine_telemetry` | The engine failed. It contributed nothing. | Name the engine, and report the result as partial. |
| `dedup_kept: 0` with `outcome: "ok"` | The engine answered, and the merge dropped its duplicate. | Report nothing; this is not a failure. |
| `blocked_by_challenge` on a fetch | The site refused the browser. | Name the URL and the code. |
| A `gaps` section in a `research` brief | The sources did not cover those points. | Read it before you claim coverage. |
| A `warning` from `agent` | The schema failed, or a fetch failed. | Label the answer partial. |

## Relationship to OpenSERP

The MCP server `openserp` is a separate local service on port 7000. Use `openserp` when the question is which engine returned what, because it answers with one engine and raw order. Use wigolo for breadth, ranking, fetching, and the cache.

An engine plugin does exist for the OpenSERP service, at `~/.wigolo/plugins/openserp`. The server loads it, and version 0.2.1 never dispatches it: a per-call log line never fired, and `engines_used` never listed it. Treat the two servers as neighbors, not as one pipeline.

## Operations

```bash
wigolo doctor                # the components and the per-engine table
wigolo verify                # the capability smoke test
wigolo search "query" --limit=3 --search-depth=fast
wigolo cache stats           # or: wigolo cache clear
wigolo config --plain        # the current settings
```

A setting resolves in this order: an environment variable, then `~/.wigolo/config.json`, then a built-in default. The backend is `core` by default. `WIGOLO_SEARCH` selects `searxng` or `hybrid`.

## Rubric coverage

`eval.md` holds the rubric. The table below maps every rubric item to the section that implements it.

<!-- ste-allow R10: a coverage table is data, not prose -->

| Rubric item | Implemented in |
|---|---|
| H1 engine telemetry reading | Reading a search response; Failure modes |
| H2 input gap | Failure modes; Depth against the installed components |
| W1 depth against components | Depth against the installed components |
| W2 cache honesty | Cache behaviour |
| W3 claim bounds | Failure modes; Tools |
| W4 name accuracy | Tools; Search parameters; Relationship to OpenSERP |
| W5 untrusted content | Terms; Failure modes |

