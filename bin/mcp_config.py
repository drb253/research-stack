#!/usr/bin/env python3
"""mcp_config.py -- write/merge the research-stack MCP servers into a client config.

One canonical server definition is rendered into each client's on-disk shape:

  * Cline, Claude Desktop, Gemini, LM Studio  ->  {"mcpServers": {...}}   (stdio style)
  * OpenCode                                  ->  {"mcp": {...}}          (type/command/env style)
  * DeepSeek Harness (dsh)                    ->  a YAML top-level array of
    loader patch entries at ~/.dsh/cordis.patch.yml, one `insert:` entry
    holding `@deepseek-ai/dsh-mcp-client` rows.

Merging is non-destructive: an existing config is backed up and only the MCP
keys for the servers we manage are added/replaced. Nothing else is touched.

The dsh writer is the one non-JSON shape, so it is deliberately conservative:
it never imports a YAML library (the repo stays stdlib-only), it understands
only the patch-entry shape DSH expects, it preserves unrelated entries, rows
and comments as they were, and it refuses to touch a file that is not such a
list rather than risk corrupting one that is. It also never leaves the file
empty: DSH fails to boot on an empty or comments-only patch file, so real rows
are always emitted.

Usage:
  mcp_config.py --platform cline  [--out PATH] [--print] [--dry-run]
  mcp_config.py --platform dsh    [--out PATH] [--print] [--dry-run]
  mcp_config.py --list-platforms
Env (optional, else placeholders are used):
  NCBI_EMAIL NCBI_API_KEY S2_API_KEY OPENALEX_EMAIL UNPAYWALL_EMAIL
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

HOME = Path(os.path.expanduser("~"))

# DeepSeek Harness: the MCP client plugin, the home patch layer it composes
# last, and the serverName grammar DSH enforces.
DSH_PLUGIN = "@deepseek-ai/dsh-mcp-client"
DSH_PATCH = HOME / ".dsh" / "cordis.patch.yml"
DSH_SKILLS = HOME / ".dsh" / "skills"
DSH_SERVER_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
DSH_HEADER = (
    "# cordis patch -- written by research-stack (bin/mcp_config.py)\n"
    "# A top-level array of loader patch entries. The research-stack MCP rows\n"
    "# sit inside the `insert` entry below; rows whose id is mcp-<server> are\n"
    "# replaced on re-run. Other entries, rows and comments are preserved.\n"
    "# An empty or comments-only patch file fails DSH boot, so keep the rows.\n"
)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def definitions() -> dict:
    """name -> {'spec': cline-style dict, 'requires': [paths]}"""
    home = str(HOME)
    return {
        "paper-search": {
            "spec": {"command": f"{home}/.local/bin/paper-search-mcp", "args": [],
                     "env": {}, "type": "stdio", "timeout": 300,
                     "autoApprove": [
                         "search_papers", "search_arxiv", "search_pubmed", "search_biorxiv",
                         "search_medrxiv", "search_iacr", "search_semantic", "search_crossref",
                         "search_openalex", "search_pmc", "search_core", "search_europepmc",
                         "search_openaire", "search_doaj", "search_zenodo", "search_hal",
                         "search_ssrn", "search_unpaywall", "search_plos", "search_jstage",
                         "search_figshare", "search_datacite", "search_whoris", "search_osf",
                         "plan_search_query", "check_retraction", "get_crossref_paper_by_doi",
                         "convert_paper_ids", "get_citation_metrics", "get_citing_articles",
                         "get_annotations", "search_clinicaltrials", "get_related_articles",
                         "get_mesh_details", "search_bookshelf", "search_ictrp", "search_ctis",
                     ]},
            "requires": [],
        },
        "ncbi": {
            "spec": {
                "command": f"{home}/.local/share/ncbi-mcp-server/.venv/bin/python",
                "args": ["-m", "ncbi_mcp_server.server"],
                "env": {
                    "PYTHONPATH": f"{home}/.local/share/ncbi-mcp-server/src",
                    "NCBI_EMAIL": _env("NCBI_EMAIL", "you@example.org"),
                    "NCBI_API_KEY": _env("NCBI_API_KEY", ""),
                    "LOG_LEVEL": "INFO",
                },
                "type": "stdio",
                "timeout": 120,
                "autoApprove": [
                    "search_pubmed", "get_article_details", "search_mesh_terms",
                    "get_related_articles", "advanced_search", "cache_stats",
                    "batch_search_multiple_queries", "batch_get_article_details",
                    "get_analytics_summary", "get_detailed_metrics",
                ],
            },
            "requires": [f"{home}/.local/share/ncbi-mcp-server/.venv/bin/python"],
        },
        "academic-search": {
            "spec": {
                "command": f"{home}/.local/share/academic-search-mcp/.venv/bin/academic-search",
                "args": [],
                "env": {"S2_API_KEY": _env("S2_API_KEY", ""),
                        "PATH": f"{home}/.local/bin:/usr/local/bin:/usr/bin:/bin",
                        "HOME": home},
                "type": "stdio", "timeout": 300,
                "autoApprove": ["search_papers", "search_by_author", "explore_citations",
                                "get_paper_stats", "build_extended_query"],
            },
            "requires": [f"{home}/.local/share/academic-search-mcp/.venv/bin/academic-search"],
        },
        "consensus": {
            "spec": {"command": f"{home}/.local/bin/npx",
                     "args": ["-y", "mcp-remote", "https://mcp.consensus.app/mcp"],
                     "env": {"PATH": f"{home}/.local/bin:/usr/local/bin:/usr/bin:/bin",
                             "HOME": home},
                     "type": "stdio", "timeout": 180},
            "requires": [],
        },
        "google-scholar": {
            "spec": {"command": f"{home}/.local/bin/npx",
                     "args": ["-y", "mcp-remote",
                              "https://mcp.hasdata.com/mcp?apis=google_scholar"],
                     "env": {"PATH": f"{home}/.local/bin:/usr/local/bin:/usr/bin:/bin",
                             "HOME": home},
                     "type": "stdio", "timeout": 180},
            "requires": [],
        },
    }


def render_cline_style(names: list) -> dict:
    defs = definitions()
    return {"mcpServers": {n: defs[n]["spec"] for n in names if n in defs}}


def render_opencode(names: list) -> dict:
    defs = definitions()
    out = {}
    for n in names:
        if n not in defs:
            continue
        spec = defs[n]["spec"]
        entry = {"type": "local", "command": [spec["command"], *spec.get("args", [])],
                 "enabled": True}
        env = {k: v for k, v in (spec.get("env") or {}).items() if v}
        if env:
            entry["environment"] = env
        out[n] = entry
    return {"$schema": "https://opencode.ai/config.json", "mcp": out}


# ---- DeepSeek Harness (dsh) ------------------------------------------------- #
#
# DSH composes cordis patch layers in order: bundle layers -> the profile's own
# cordis.patch.yml -> ~/.dsh/cordis.patch.yml. The home layer is composed last,
# so it outranks the profile's own file and reaches every profile (including the
# Electron desktop one). A patch file is a top-level YAML array of *loader patch
# entries*, and the distinction matters: a non-insert entry (`- id: x` + `name`)
# only rewrites a row that already exists and is otherwise dropped with
# `patch: entry "x" not found`. Rows that introduce a new plugin must therefore
# be wrapped in `insert:`, exactly as the shipped profile/bundle patches are.
# No YAML library is imported: the file is small and regular, so it is emitted
# and read back by hand.

def _yaml_scalar(value) -> str:
    """Single-quoted YAML scalar (always quoted, so nothing is ambiguous)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_gap_line(line: str) -> bool:
    s = line.strip()
    return s == "" or s.startswith("#") or s in ("---", "...")


def _dsh_row_lines(entry_id: str, config: dict, indent: int) -> list:
    """One inserted row: - id / name / config, deterministically, at `indent`."""
    pad = " " * indent
    ipad = " " * (indent + 2)
    cpad = " " * (indent + 4)
    apad = " " * (indent + 6)
    lines = [f"{pad}- id: {_yaml_scalar(entry_id)}",
             f"{ipad}name: {_yaml_scalar(DSH_PLUGIN)}",
             f"{ipad}config:",
             f"{cpad}serverName: {_yaml_scalar(config['serverName'])}",
             f"{cpad}transport: {_yaml_scalar('stdio')}",
             f"{cpad}command: {_yaml_scalar(config['command'])}"]
    args = list(config.get("args") or [])
    if args:
        lines.append(f"{cpad}args:")
        lines += [f"{apad}- {_yaml_scalar(a)}" for a in args]
    else:
        lines.append(f"{cpad}args: []")
    env = config.get("env") or {}
    if env:
        lines.append(f"{cpad}env:")
        lines += [f"{apad}{k}: {_yaml_scalar(env[k])}" for k in sorted(env)]
    else:
        lines.append(f"{cpad}env: {{}}")
    lines.append(f"{cpad}toolCallTimeoutMs: {int(config['toolCallTimeoutMs'])}")
    lines.append(f"{cpad}failOnStartupError: {'true' if config['failOnStartupError'] else 'false'}")
    return [ln + "\n" for ln in lines]


def render_dsh_rows(names: list) -> list:
    """[(id, config)] for the requested servers, in request order.

    A server is skipped (with a warning) when we have no definition for it or
    its name violates DSH's serverName grammar. Empty env values are dropped so
    a placeholder key is never injected as an empty string.
    """
    defs = definitions()
    rows = []
    seen = set()
    for n in names:
        if n not in defs:
            print(f"  ! dsh: no definition for server '{n}' (skipped)", file=sys.stderr)
            continue
        if not DSH_SERVER_RE.match(n):
            print(f"  ! dsh: '{n}' is not a valid DSH serverName "
                  f"(^[A-Za-z0-9_-]{{1,32}}$) (skipped)", file=sys.stderr)
            continue
        if n in seen:
            continue
        seen.add(n)
        spec = defs[n]["spec"]
        rows.append((f"mcp-{n}", {
            "serverName": n,
            "command": spec["command"],
            "args": list(spec.get("args") or []),
            "env": {k: v for k, v in (spec.get("env") or {}).items() if v},
            "toolCallTimeoutMs": int(spec.get("timeout", 120)) * 1000,
            # A missing optional server must never take down DSH boot.
            "failOnStartupError": False,
        }))
    return rows


def _yaml_unquote(raw: str) -> str:
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] == "'":
        return s[1:-1].replace("''", "'")
    if len(s) >= 2 and s[0] == s[-1] == '"':
        return s[1:-1]
    return s


def _dsh_split_body(body: list, row_indent: int) -> list:
    """Body lines -> [{'kind': row|gap, 'id': ..., 'lines': [...]}], in order."""
    items = []
    cur = None
    for line in body:
        is_row = _indent_of(line) == row_indent and (
            re.match(r"^\s*-[ \t]", line) or line.strip() == "-")
        if is_row:
            ident = None
            m = re.match(r"^\s*-[ \t]*id:[ \t]*(.*?)[ \t]*$", line)
            if m:
                ident = _yaml_unquote(m.group(1))
            cur = {"kind": "row", "id": ident, "lines": [line]}
            items.append(cur)
        elif cur is not None and _indent_of(line) > row_indent:
            cur["lines"].append(line)
        else:
            items.append({"kind": "gap", "id": None, "lines": [line]})
            cur = None
    return items


def _dsh_parse(text: str):
    """Parse a DSH patch file into (preamble_lines, entries); None if unreadable.

    Each entry is a mapping in a top-level YAML sequence. An entry whose
    `insert:` key we can edit is classified `insert` and split into
    head / items / tail so a managed row can be replaced in place while
    everything else survives byte-for-byte. A flow-style `insert:` value (or a
    file that is not a sequence of mappings) returns None: we refuse to guess.
    """
    lines = text.splitlines(keepends=True)
    preamble = []
    entries = []
    cur = None
    for line in lines:
        if re.match(r"^-(?:[ \t]|$)", line):
            cur = {"lines": [line]}
            entries.append(cur)
        elif cur is not None:
            if line[:1].isspace() or _is_gap_line(line):
                cur["lines"].append(line)
            else:
                return None
        elif _is_gap_line(line):
            preamble.append(line)
        else:
            return None

    for entry in entries:
        entry["kind"] = "other"
        entry["head"] = entry["lines"]
        entry["items"] = []
        entry["tail"] = []
        entry["row_indent"] = None
        for i, line in enumerate(entry["lines"]):
            m = re.match(r"^(\s*)(?:-[ \t]+)?insert:[ \t]*(.*?)[ \t]*$", line)
            if not m:
                continue
            key_indent = len(m.group(1))
            if m.group(2) not in ("", "[]", "~", "null"):
                return None                      # flow-style insert: do not touch
            j = i + 1
            while j < len(entry["lines"]):
                nxt = entry["lines"][j]
                if _is_gap_line(nxt) or _indent_of(nxt) > key_indent:
                    j += 1
                else:
                    break
            body = entry["lines"][i + 1:j]
            row_indent = key_indent + 2
            for ln in body:
                if re.match(r"^\s*-[ \t]", ln) or ln.strip() == "-":
                    row_indent = _indent_of(ln)
                    break
            entry["kind"] = "insert"
            entry["head"] = entry["lines"][:i + 1]
            entry["items"] = _dsh_split_body(body, row_indent)
            entry["tail"] = entry["lines"][j:]
            entry["row_indent"] = row_indent
            break
    return preamble, entries


def _dsh_render_merged(preamble: list, entries: list, rows: list) -> str:
    """Replace managed rows where they already live, keep everything else."""
    managed = dict(rows)
    placed = set()
    out = list(preamble)

    for entry in entries:
        if entry["kind"] != "insert" or not any(
                it["kind"] == "row" and it["id"] in managed for it in entry["items"]):
            out += entry["lines"]
            continue
        out += entry["head"]
        indent = entry["row_indent"] or 4
        for it in entry["items"]:
            if it["kind"] == "row" and it["id"] in managed:
                out += _dsh_row_lines(it["id"], managed[it["id"]], indent)
                placed.add(it["id"])
            else:
                out += it["lines"]
        out += entry["tail"]

    missing = [(rid, cfg) for rid, cfg in rows if rid not in placed]
    if missing:
        block = ["- insert:\n"]
        for rid, cfg in missing:
            block += _dsh_row_lines(rid, cfg, 4)
        idx = len(out)
        while idx > 0 and _is_gap_line(out[idx - 1]):
            idx -= 1
        if idx == 0:
            # The file was comments/blank only (which fails DSH boot): keep any
            # comment header on top and append the rows after it.
            idx = len(out)
        out[idx:idx] = block

    text = "".join(out)
    if text and not text.endswith("\n"):
        text += "\n"
    return text


def write_dsh(names: list, out, dry_run: bool, print_only: bool) -> int:
    target = Path(out) if out else DSH_PATCH
    rows = render_dsh_rows(names)
    if not rows:
        print("  ! dsh: no servers to write (nothing changed).", file=sys.stderr)
        return 1

    existing = ""
    if target.exists():
        try:
            existing = target.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            print(f"  ! cannot read {target} ({exc}); leaving it untouched.",
                  file=sys.stderr)
            return 1
        if existing.strip() in ("", "[]"):
            existing = ""            # an empty array is the boot-failure case
        else:
            parsed = _dsh_parse(existing)
            if parsed is None:
                print(f"  ! {target} is not a top-level YAML array of loader patch "
                      f"entries; refusing to touch it.", file=sys.stderr)
                return 1
            preamble, entries = parsed

    if existing:
        text = _dsh_render_merged(preamble, entries, rows)
    else:
        body = "".join("".join(_dsh_row_lines(rid, cfg, 4)) for rid, cfg in rows)
        text = DSH_HEADER + "\n" + "- insert:\n" + body

    if print_only:
        print(text, end="")
        return 0

    if dry_run:
        print(f"  [dry-run] would write {target}:")
        print("    " + text.replace("\n", "\n    ")[:1400])
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        backup = target.with_suffix(target.suffix + f".bak.{time.strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(target, backup)
        print(f"  backed up -> {backup}")
    target.write_text(text, encoding="utf-8")
    try:
        os.chmod(target, 0o600)
    except Exception:  # noqa: BLE001
        pass
    print(f"  wrote {target}  (insert rows: {', '.join(rid for rid, _c in rows)})")
    return 0


PLATFORMS = {
    "cline": (HOME / ".cline/data/settings/cline_mcp_settings.json", "cline", "mcpServers"),
    "claude": (
        (HOME / "Library/Application Support/Claude/claude_desktop_config.json")
        if sys.platform == "darwin"
        else (HOME / ".config/Claude/claude_desktop_config.json"),
        "cline", "mcpServers"),
    "opencode": (HOME / ".config/opencode/opencode.json", "opencode", "mcp"),
    "gemini": (HOME / ".gemini/settings.json", "cline", "mcpServers"),
    "lmstudio": (HOME / ".lmstudio/mcp.json", "cline", "mcpServers"),
    "dsh": (DSH_PATCH, "dsh", None),
    "trae": (
        (HOME / "Library/Application Support/Trae/User/mcp.json")
        if sys.platform == "darwin"
        else (HOME / ".config/Trae/User/mcp.json"),
        "cline", "mcpServers"),
    "cursor": (HOME / ".cursor/mcp.json", "cline", "mcpServers"),
    "windsurf": (HOME / ".codeium/windsurf/mcp_config.json", "cline", "mcpServers"),
}


def _deep_merge(base: dict, add: dict) -> dict:
    for k, v in add.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def write_platform(platform: str, names: list, out, dry_run: bool, print_only: bool) -> int:
    path, style, key = PLATFORMS[platform]
    if style == "dsh":
        return write_dsh(names, out, dry_run, print_only)
    target = Path(out) if out else path
    rendered = render_opencode(names) if style == "opencode" else render_cline_style(names)

    if print_only:
        print(json.dumps(rendered, indent=2))
        return 0

    merged = {}
    if target.exists():
        try:
            merged = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(merged, dict):
                merged = {}
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {target} is not valid JSON ({exc}); leaving it untouched.",
                  file=sys.stderr)
            return 1
    _deep_merge(merged, rendered)
    text = json.dumps(merged, indent=2) + "\n"

    if dry_run:
        print(f"  [dry-run] would write {target}:")
        print("    " + text.replace("\n", "\n    ")[:1400])
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        backup = target.with_suffix(target.suffix + f".bak.{time.strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(target, backup)
        print(f"  backed up -> {backup}")
    target.write_text(text, encoding="utf-8")
    try:
        os.chmod(target, 0o600)
    except Exception:  # noqa: BLE001
        pass
    print(f"  wrote {target}  (servers: {', '.join(rendered[key].keys())})")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Write/merge research-stack MCP config.")
    ap.add_argument("--platform", choices=sorted(PLATFORMS))
    ap.add_argument("--servers", default="paper-search,consensus,google-scholar")
    ap.add_argument("--out", help="override the config path")
    ap.add_argument("--print", dest="print_only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list-platforms", action="store_true")
    args = ap.parse_args(argv)

    if args.list_platforms:
        for name, (path, _s, _k) in PLATFORMS.items():
            print(f"{name:10s} {path}")
        return 0
    if not args.platform:
        ap.error("--platform is required (or --list-platforms)")
    names = [s.strip() for s in args.servers.split(",") if s.strip()]
    return write_platform(args.platform, names, args.out, args.dry_run, args.print_only)


if __name__ == "__main__":
    sys.exit(main())
