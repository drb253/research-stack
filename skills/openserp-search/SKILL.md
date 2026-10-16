---
name: openserp-search
description: Runs web searches and page extraction through the local OpenSERP service. Use it for current pages, documentation, news, and for turning a URL into clean markdown. It names the engine that answered each query. Google needs a link unwrap and blocks bursts, while Bing and DuckDuckGo answer directly. This is web search, not a literature database and not Google Scholar.
allowed-tools: Read Bash
license: MIT
compatibility: Needs the OpenSERP service on 127.0.0.1:7000, plus the `openserp` command or the `openserp` MCP server. The service needs no API key. A proxy raises the success rate for the blocked engines.
metadata:
  version: "1.0"
  source: "https://github.com/karust/openserp"
---

# OpenSERP Search

Run web searches and page extraction on this machine. The service listens on loopback only, and it stores the responses in a small cache.

<!-- gates: openserp_unwrap.py -->

## Terms

A search engine results page (SERP) is the page that an engine returns for one query. The Model Context Protocol (MCP) connects this skill to the service. A uniform resource locator (URL) is a web address. A proxy is an intermediate server that carries the requests of another host.

## Preflight

Run the health check before the first search.

```bash
curl -s http://127.0.0.1:7000/health | jq -c '{status, ready: [.engines[] | select(.status=="ready") | .name] | length}'
```

Expect `"status":"healthy"` and six ready engines. Restart the service when the check fails.

```bash
launchctl kickstart -k gui/$(id -u)/ai.openserp.server
```

## Tools

The MCP server `openserp` wraps the same endpoints that the CLI uses.

| Tool | Use |
| --- | --- |
| `search` | One engine. It needs `engine` and `text`. |
| `mega_search` | Several engines, merged and deduplicated. |
| `fast_search`, `any_search` | The first engine that answers. |
| `extract`, `batch_extract` | One URL, or up to twenty URLs, as markdown. |
| `list_engines`, `get_usage` | Engine status. The second tool reports nothing in local mode. |

The argument for the query text is `text`. The server ignores `query`, and it answers `EMPTY_QUERY`.

| Endpoint | Parameters |
| --- | --- |
| `/google/search`, `/bing/search`, `/duckduckgo/search` | `text`, `limit`, `lang`, `region`, `site`, `file`, `start` |
| `/mega/search` | The same parameters, plus `engines` and `mode` |
| `/extract`, `/extract/batch` | `url`, or a list of URLs |

## Engine status on this machine

Check the list with `openserp doctor` or with a live query, because the status changes with the network.

| Engine | Status on 2026-10-16 |
| --- | --- |
| `bing` | Reliable. About four seconds. The results include ads. |
| `duckduckgo` | Reliable. About four seconds. |
| `google` | Works with care. Read the next section. |
| `ecosia` | Blocked. The server answers `blocked`. |
| `yandex` | Blocked. The server answers `captcha_detected` and HTTP 429. |
| `baidu` | Fails. The server answers `proxy_timeout` or nothing. |

Keep only the results of type `organic` before a citation. A proxy is the only local fix for the blocked engines.

## Google

Google answers this host. It needs two precautions.

**Avoid bursts.** A parallel fan-out of six engines returned `0 results`, `blocked`, and one `captcha_detected`. The same queries in series, four seconds apart, all answered. The configuration pins `google.rate_requests: 10` and `rate_burst: 1`. The `region` and `lang` parameters make a block more likely, so omit both for Google.

**Resolve the wrapped links.** Google returns one encrypted redirect for each organic result.

```json
{ "url": "https://www.google.com/goto?url=CAES...", "domain": "google.com" }
```

The link works. A plain request returns HTTP 302 with the real address in the `Location` header. The `domain` field stays wrong until you resolve the link.

```bash
curl -s 'http://127.0.0.1:7000/google/search?text=example&limit=5' | openserp-unwrap > results.json
openserp-unwrap --url 'https://www.google.com/goto?url=CAES...'
```

The tool rewrites `url`, `domain`, `display_url`, and `domain_info`. It keeps the original address in `wrapped_url`. It prints `n/m wrapped links resolved` on stderr, and it exits 1 when a link fails. A failure keeps the original URL and sets `"unwrapped": false`. It touches only wrapped links, so it is safe on the results of the other engines.

Upstream fixed this attribution in commit `98e48e6`. No release contains that commit yet.

## Failure modes

| Answer | Meaning | Action |
| --- | --- | --- |
| `blocked`, `captcha_detected` | The engine refused this host. No search happened. | Name the engine. Wait 10 to 15 seconds, then retry once, or use `bing`. |
| `empty_result` | The engine answered, and it found no match. | Report an empty answer for that engine. |
| `EMPTY_QUERY` | The call sent `query` instead of `text`. | Send `text`. |
| `extract_failed` | The extraction failed. | Report the URL and the error code. |
| HTTP 403 with a `blocked` page | The server classifies the page, and it skips the retries on purpose. | Use the `blocked` rule. |

Never report a refusal as an absent source. A blocked engine contributed nothing, so the result is partial.

## Rubric coverage

`eval.md` holds the rubric. The table below maps every rubric item to the section that implements it.

<!-- ste-allow R10: a coverage table is data, not prose -->

| Rubric item | Implemented in |
|---|---|
| H1 engine attribution | Tools; Engine status; Failure modes |
| H2 input gap | Failure modes; Engine status |
| S1 link provenance | Google |
| S2 serial Google requests | Google |
| S3 extraction honesty | Tools; Failure modes |
| S4 cache awareness | Terms; Failure modes |
| S5 claim bounds | Failure modes |
| S6 name accuracy | Tools; Engine status |

