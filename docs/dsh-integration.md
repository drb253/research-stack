# DeepSeek Harness (dsh)

`./install.sh --targets dsh` makes DeepSeek Harness a first-class target: the
repo's **13 review skills** go into `~/.dsh/skills`, and the MCP servers go into
`~/.dsh/cordis.patch.yml` through the `dsh` platform in `bin/mcp_config.py`.

```bash
./install.sh --targets dsh                          # skills + MCP + optional servers
./install.sh --targets dsh --no-mcp                 # skills only
./install.sh --targets dsh --no-skills              # MCP config only
./install.sh --targets dsh --no-upstream-skills     # just the 13 repo skills
```

## What is written

| Piece | Path | Shape |
|---|---|---|
| Review skills | `~/.dsh/skills/<name>` (symlinks by default; `--copy-skills` copies) | one directory per skill with a `SKILL.md` |
| MCP servers | `~/.dsh/cordis.patch.yml` | top-level YAML array of loader patch entries; one `insert:` entry holding `@deepseek-ai/dsh-mcp-client` rows |

A skill is discovered at depth 1 — `<root>/<name>/SKILL.md` — with `name`
(kebab-case) and `description` in its frontmatter.

## Skill roots

DSH's filesystem skill provider scans these roots in rank order (lower wins), so
a project skill shadows a user skill of the same name:

| Rank | Source | Path |
|---|---|---|
| 100 | `project-dsh` | `<projectRoot>/.dsh/skills` |
| 200 | `project-agents` | `<projectRoot>/.agents/skills` |
| 300 | `custom` | `Config.customSkillDirs` |
| 400 | `user-dsh` | `<dshHome>/skills` — `~/.dsh/skills` (`$DSH_HOME` overrides) |
| 500 | `user-agents` | `<agentsHome>/skills` — `~/.agents/skills` |

`<projectRoot>` is the nearest ancestor containing `.git`; without one, the
current working directory. The installer writes to rank 400
(`~/.dsh/skills`), which is available to every project and every profile.

## Patch layer precedence

DSH composes cordis patch layers in application order, and later layers win:

1. **bundle layers** — what the profile's `dsh.profile.bundles` pull in
   (e.g. `@deepseek-ai/dsh-base`, then the app's own layers);
2. **the profile's patch file** — `~/.dsh/profiles/<name>/cordis.patch.yml`
   (the Electron desktop app uses the `desktop` profile);
3. **the home patch file** — `~/.dsh/cordis.patch.yml`.

Because the home layer is composed last it outranks the profile's own file and
reaches **every** profile, including the desktop app. That is why the installer
writes there rather than editing a profile file.

## The shape, and why it is `insert:`

A patch file is a top-level YAML array of *loader patch entries*, and each entry
is a mapping of one of two kinds:

```yaml
# override: rewrites a row that already exists (unknown id -> warned + skipped)
- id: ui-chat
  config:
    transcriptView: standard

# insertion: appends new rows to the entry list
- insert:
    - id: mcp-paper-search
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

A non-`insert` entry only targets an **existing** row id; anything else is
dropped with `patch: entry "<id>" not found`. Our servers are new plugins with
no existing row, so they must be inserted — the shipped MCP template
(`@deepseek-ai/dsh-agent-preset/skills/cordis-plugin-development/templates/mcp/cordis.patch.yml`)
uses exactly this `- insert:` shape, and so do the shipped bundle patches.

`config` fields used here:

| Field | Value | Notes |
|---|---|---|
| `serverName` | `paper-search`, `consensus`, `google-scholar`, `ncbi`, `academic-search` | `^[A-Za-z0-9_-]{1,32}$`, unique inside one registration scope |
| `transport` | `stdio` | all repo servers are local processes |
| `command` / `args` / `env` | from the repo's canonical server definitions | empty env values are dropped, so no blank API key is injected |
| `toolCallTimeoutMs` | repo per-server timeout × 1000 | e.g. 300 s → `300000` |
| `failOnStartupError` | `false` | an optional server that is not installed must not block DSH boot |

The server's tools surface as **`mcp__<serverName>__<rawTool>`** — e.g.
`mcp__paper-search__search_pubmed`, `mcp__ncbi__get_article_details`.

## Non-destructive merge

`bin/mcp_config.py --platform dsh` (stdlib only — no PyYAML, the YAML is emitted
and read back by hand):

- **backs up** an existing file to `cordis.patch.yml.bak.<timestamp>` (and sets
  mode `600`);
- **preserves** every other top-level entry, every other inserted row, and every
  comment, byte-for-byte;
- replaces in place only the rows **inside the `insert:` entry it manages** whose
  id is `mcp-<server>`; rows for servers that are not there yet are appended
  there. A top-level `- id: mcp-<server>` row that an older revision wrote is
  *preserved, not deleted* — it is dead weight DSH warns about, and removing a
  row the writer does not own is the one thing this refusal boundary forbids;
- is **idempotent** — a second run is byte-identical;
- **refuses** (exit 1) to touch a file that is not a top-level array of mapping
  patch entries, or one using flow-style `insert: [...]`, rather than risk
  corrupting a config it cannot read;
- **never leaves the file empty**: an empty or comments-only patch file fails
  DSH boot, so real rows are always emitted.

`--print` writes nothing, `--dry-run` prints what would be written, and `--out
PATH` redirects the target — useful for inspecting the result safely.

## Restart

DSH normally needs **no** restart. The `dsh-base` bundle enables
`@deepseek-ai/dsh-hmr` whenever the launcher supplies a profile context (the
desktop app does), and HMR watches the profile manifest and **both** user patch
files — the profile's `cordis.patch.yml` and the home `~/.dsh/cordis.patch.yml`.
Creating or editing the home patch therefore triggers a live recomposition: the
MCP servers connect and their tools appear in the running session, and the
filesystem skill provider re-indexes `~/.dsh/skills` so the skills reach the
catalog too. Expect roughly a 2-second write-stability window before a change is
picked up.

A restart is only the fallback: headless, SDK and ACP bundles disable the `hmr`
row, and a profile may disable it explicitly. If the tools still do not appear,
fully quit and reopen the app — closing the window is not enough.

## Verify

```bash
python3 bin/mcp_config.py --list-platforms
python3 bin/mcp_config.py --platform dsh --servers paper-search,academic-search,ncbi --print
./install.sh --targets dsh --dry-run
ls -l ~/.dsh/skills
```

Then, in DSH, `mcp__paper-search__search_pubmed` (or any other
`mcp__<server>__<tool>`) should be available.

## Rollback

```bash
ls ~/.dsh/cordis.patch.yml.bak.*                    # newest backup
cp ~/.dsh/cordis.patch.yml.bak.<timestamp> ~/.dsh/cordis.patch.yml
rm -rf ~/.dsh/skills/<name>                         # drop a symlinked skill
```

If there was no patch file before the install, remove the file entirely
(`rm ~/.dsh/cordis.patch.yml`) rather than truncating it — an empty or
comments-only patch file fails DSH boot. To keep other rows and drop only ours,
delete the `mcp-*` rows inside the `insert:` entry the installer added.
