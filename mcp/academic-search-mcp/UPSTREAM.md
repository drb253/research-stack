# Vendored `academic-search` (fork)

A complete, self-contained copy of a locally patched `academic-search` MCP
server, vendored so the installer never depends on the network.

| | |
|---|---|
| **Base** | an `academic-search` MCP server (multi-provider: Semantic Scholar, Crossref, OpenAlex, PubMed) |
| **This copy** | local fork `0.8.0+local1` — four upstream fixes + two found during verification |
| **Contents** | `src/academic_search/`, `tests/`, `verification/`, `pyproject.toml`, `STATUS.md` |

## Install

`install.sh` copies this directory to `~/.local/share/academic-search-mcp` and
runs `uv pip install -e .` (deps: `fastmcp`, `numpy`, `pandas`, `requests`).

## Notes

- Semantic Scholar auth reads **`S2_API_KEY`** (or `SEMANTIC_SCHOLAR_API_KEY`);
  `install.sh` writes it into the server's MCP `env` from `--s2-key`.
- To reinstall it in place: use `--reinstall` (a plain run skips an already-built venv).
