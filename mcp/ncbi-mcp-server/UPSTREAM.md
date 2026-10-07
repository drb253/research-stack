# Vendored `ncbi-mcp-server` (fork)

A complete, self-contained copy of the `ncbi-mcp-server` fork, vendored so the
installer never depends on the network or on a moving upstream.

| | |
|---|---|
| **Upstream** | https://github.com/vitorpavinato/ncbi-mcp-server |
| **This copy** | the local reliability fork (cwd-independent cache + MeSH/analytics fixes; 3 `PATCHED` markers in `src/`) |
| **License** | MIT (upstream) |
| **Contents** | `src/ncbi_mcp_server/` (patched), `tests/`, `pyproject.toml`, `requirements.txt`, `doc/` |

## Install

`install.sh` copies this directory to `~/.local/share/ncbi-mcp-server`, creates a
venv (`mcp<2`, `httpx`, `typing-extensions`, `python-dotenv`), and the client
launches it as `python -m ncbi_mcp_server.server` with `PYTHONPATH=src`.

## Notes

- **`.env` and `.env.production` are deliberately NOT vendored** (they can hold
  keys). Copy `.env.example` → `.env` only if you run the server standalone.
- The old `ncbi-mcp-server.patch` + `ncbi-tests/` artifacts are gone — the
  patched source and tests ship here instead.
