# Platform wiring

`install.sh` writes, for each target, the client's native MCP shape. The
canonical server set is rendered by `bin/mcp_config.py`; merging is
non-destructive (existing file is backed up, only managed keys are replaced).

## Server set

| Server | Command | Needs |
|---|---|---|
| `paper-search` | `~/.local/bin/paper-search-mcp` | uv tool + patches |
| `consensus` | `npx -y mcp-remote https://mcp.consensus.app/mcp` | node/npx |
| `google-scholar` | `npx -y mcp-remote https://mcp.hasdata.com/mcp?apis=google_scholar` | node/npx |
| `ncbi` (optional) | `~/.local/share/ncbi-mcp-server/.venv/bin/python -m ncbi_mcp_server.server` | the ncbi fork + venv |
| `academic-search` (optional) | `~/.local/share/academic-search-mcp/.venv/bin/academic-search` | the academic-search fork + venv |

## Shapes

**Cline / Claude Desktop / Gemini / LM Studio** — `{"mcpServers": {...}}`:
```json
{
  "mcpServers": {
    "paper-search": {
      "command": "/Users/you/.local/bin/paper-search-mcp",
      "args": [], "env": {}, "type": "stdio"
    }
  }
}
```

**OpenCode** — `{"mcp": {...}}` with `type: "local"` and an argv array:
```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "paper-search": {
      "type": "local",
      "command": ["/Users/you/.local/bin/paper-search-mcp"],
      "enabled": true
    }
  }
}
```

## Skill discovery

| Client | Skills directory |
|---|---|
| Cline | `~/.cline/skills` |
| Claude (Code/Desktop) | `~/.claude/skills` |
| OpenCode | `~/.config/opencode/skills` |
| Gemini CLI | `~/.gemini/skills` |
| LM Studio | `~/.lmstudio/skills` |

Skills are symlinked from `~/.research-stack/skills` by default (`--copy-skills`
copies instead). Each skill is a folder with a `SKILL.md` whose frontmatter
opens with `---`.

## Troubleshooting

- **A server does not appear** → the client spawns MCP servers only at startup.
  Fully quit and reopen the client.
- **`npx` servers fail** → install Node.js 18+.
- **Paper-search returns nothing / arXiv empty after an upgrade** → re-run the
  patches: `~/.research-stack-src/install.sh --no-skills`.
- **Config was clobbered** → restore the `.bak.<timestamp>` written next to it.
- **Python version** → 3.9+ (stdlib only for the skills; the MCP tool brings its
  own Python via uv).
