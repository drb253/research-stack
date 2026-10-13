# Platform wiring

`install.sh` writes, for each target, the client's native MCP shape. The
canonical server set is rendered by `bin/mcp_config.py`; merging is
non-destructive (existing file is backed up, only managed keys are replaced).

## Server set

| Server | Command | Needs |
|---|---|---|
| `paper-search` | `~/.local/bin/paper-search-mcp` | uv tool (vendored, pre-patched) |
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

**DeepSeek Harness (`dsh`)** — not JSON. A YAML **patch layer** at
`~/.dsh/cordis.patch.yml`: a top-level array of loader patch entries, where our
servers are new plugins and so must be *inserted*:
```yaml
- insert:
    - id: 'mcp-paper-search'
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: 'paper-search'
        transport: 'stdio'
        command: '/Users/you/.local/bin/paper-search-mcp'
        args: []
        env: {}
        toolCallTimeoutMs: 300000
        failOnStartupError: false
```

An entry without `insert:` only rewrites a row that already exists (an unknown
id is warned and skipped), which is why the rows are wrapped. DSH composes
layers **bundles → the profile's patch file
(`~/.dsh/profiles/<name>/cordis.patch.yml`) → `~/.dsh/cordis.patch.yml`**;
the home layer is composed last, so it outranks the profile file and applies to
every profile (including the Electron desktop app). Its tools surface as
`mcp__<serverName>__<rawTool>`, e.g. `mcp__paper-search__search_pubmed`. An
empty or comments-only patch file fails DSH boot, so the writer always emits
real rows. See [dsh-integration.md](dsh-integration.md) for the full detail.

## Skill discovery

| Client | Skills directory |
|---|---|
| Cline | `~/.cline/skills` |
| Claude (Code/Desktop) | `~/.claude/skills` |
| OpenCode | `~/.config/opencode/skills` |
| Gemini CLI | `~/.gemini/skills` |
| LM Studio | `~/.lmstudio/skills` |
| DeepSeek Harness | `~/.dsh/skills` |

DSH also scans higher-priority project roots — `<projectRoot>/.dsh/skills` and
`<projectRoot>/.agents/skills`, plus `customSkillDirs` — before the user root,
so a project skill of the same name shadows the installed one. Rank order and
the `agentsHome` root are in [dsh-integration.md](dsh-integration.md#skill-roots).

Skills are symlinked from `~/.research-stack/skills` by default (`--copy-skills`
copies instead). Each skill is a folder with a `SKILL.md` whose frontmatter
opens with `---`.

## Troubleshooting

- **A server does not appear** → most clients spawn MCP servers only at startup,
  so fully quit and reopen them. DeepSeek Harness is the exception: its HMR
  watches both user patch files, so a new `~/.dsh/cordis.patch.yml` is composed
  live (about a 2-second stability delay). Restart DSH only if HMR is disabled
  (headless/SDK/ACP) or the tools still do not appear.
- **DSH will not boot after editing its patch file** → an empty or
  comments-only `~/.dsh/cordis.patch.yml` is a boot failure. Restore the
  `.bak.<timestamp>` beside it, or delete the file entirely — never leave it
  empty.
- **`npx` servers fail** → install Node.js 18+.
- **Paper-search returns nothing / arXiv empty** → reinstall from the vendored
  source: `~/.research-stack-src/install.sh --reinstall`.
- **Config was clobbered** → restore the `.bak.<timestamp>` written next to it.
- **Python version** → 3.9+ (stdlib only for the skills; the MCP tool brings its
  own Python via uv).
