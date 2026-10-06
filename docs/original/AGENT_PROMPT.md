# AGENT_PROMPT.md — hand this to Cline on the new PC

**How to use:** copy everything between the `===` markers into a fresh Cline
session, in **Act mode**, with the `cline-setup` folder open. Attach or point at
the folder path. Cline will work through it phase by phase and stop where it
needs a secret from you.

The prompt is written to be **self-contained** — it does not assume Cline can
see this repo's other files, only the `cline-setup/` folder you give it.

---

```
=== BEGIN PROMPT ===

You are setting up a research workstation on THIS machine. A complete, verified
setup package is in the folder `cline-setup/` (ask me for the absolute path if
you cannot find it). Read `cline-setup/SETUP.md` FIRST — it is the authoritative
runbook and it contains the exact commands, the reasons for each step, and the
troubleshooting entries. Do not improvise where it gives a command.

GOAL
Reproduce: 6 MCP servers (paper-search, ncbi, academic-search, consensus,
google-scholar, optional laya), ~30 literature sources, 176 skills
(166 scientific + 10 custom), and a working HTML-to-PDF render toolchain.

HARD RULES
1. Work phase by phase, in the order SETUP.md gives. Verify each phase before
   starting the next.
2. NEVER invent or guess an API key, and never write a placeholder into a live
   config file. When a phase needs a secret, STOP and ask me for it.
3. Every path you write into `cline_mcp_settings.json` must be literal and
   absolute. Cline does not expand `~` or environment variables in that file.
4. After any phase that installs or edits code, run that phase's verification
   command and show me the raw output. Do not summarise it as "passed".
5. If a command fails, read SETUP.md Appendix B before trying a workaround.
   Report what you tried.
6. Do not skip Phase 4.1's patch step. The unpatched server silently returns
   zero results for sources that are merely rate-limited, which makes the whole
   setup untrustworthy.

PHASES (details, commands and verifications are in SETUP.md)
  Phase 1  Cline itself          — confirm the app is installed and initialised
  Phase 2  Toolchain             — uv, Python 3.11, git, node, Edge.
                                   RECORD the absolute paths of `npx` and
                                   `uv python find 3.11` — Phase 5 needs them.
  Phase 3  Scientific skills     — 166 skills via cline-scientific-skills
  Phase 4  MCP fleet             — 4.1 paper-search (+ patches), 4.2 ncbi
                                   (+ patch), 4.3 academic-search (fork),
                                   4.4 consensus, 4.5 google-scholar,
                                   4.6 laya (optional, default disabled)
  Phase 5  MCP config            — fill mcp-settings.template.json, chmod 600
  Phase 6  Custom skills         — copy portable/skills/* into ~/.cline/skills
  Phase 7  Render toolchain      — browser-probe venv + Playwright chromium
  Phase 8  API keys              — ASK ME for each; do not fabricate

FIRST ACTIONS
1. Read `cline-setup/SETUP.md` in full.
2. Inventory this machine: OS and version, `uname -a`, `$HOME`, whether
   `uv`, `git`, `node`, `npx`, `brew` exist and their versions, whether Cline's
   data dir exists at `~/.cline/data/settings/`, and free disk space.
3. Show me that inventory plus a phase-by-phase plan with the exact commands you
   intend to run.
4. Then start Phase 2 and proceed.

WHAT TO REPORT AT THE END
- The output of every verification command, raw.
- A table: thing installed / version / verified yes-no.
- Anything you could not complete, and precisely why.
- Any place where reality differed from SETUP.md.

STOP AND ASK ME WHEN
- A phase needs an API key or email address.
- A verification command fails.
- A path in SETUP.md does not exist on this machine.
- You are about to delete or overwrite anything outside `~/.local/share/`,
  `~/.cline/`, `~/.config/paper-search-mcp/`, or the `cline-setup/` folder.

FINAL STEP
After everything passes, tell me to fully QUIT and REOPEN Cline (not a window
reload). Then in the new session, confirm: typing `/` shows 176 skills, and a
`paper-search__search_papers` call with query "CRISPR base editing" and
sources="auto" returns hits AND a `source_status` block. The critical check is
that a source which is DOWN reports `unavailable` — never `0 results`.

=== END PROMPT ===
```

---

## Why the prompt is shaped this way

| Instruction | Reason |
|---|---|
| "Read SETUP.md first" | Prevents Cline re-deriving (and mis-deriving) what is already documented. |
| "Never invent a key" | A placeholder written into a live config produces an auth error that looks like a broken server. |
| "Literal absolute paths" | Cline's MCP config does **not** expand `~` or env vars — a silent, common failure. |
| "Show raw verification output" | On the source machine, a verifier bug made `0/0 checks passed` **exit 0**. Summaries hide exactly this class of failure. |
| "Do not skip Phase 4.1's patches" | Unpatched, a rate-limited source is indistinguishable from an empty literature. That is the defect the whole setup exists to prevent. |
| "Record npx and python paths in Phase 2" | Phase 5 cannot be completed without them. |
| "Stop and ask on failure" | Stops the agent improvising a divergent setup. |
| "Quit and reopen, not reload" | MCP servers are spawned only at startup; on the source machine the live processes ran ~30 hours behind the patched code. |
