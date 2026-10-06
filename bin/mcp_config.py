#!/usr/bin/env python3
"""mcp_config.py -- write/merge the research-stack MCP servers into a client config.

One canonical server definition is rendered into each client's on-disk shape:

  * Cline, Claude Desktop, Gemini, LM Studio  ->  {"mcpServers": {...}}   (stdio style)
  * OpenCode                                  ->  {"mcp": {...}}          (type/command/env style)

Merging is non-destructive: an existing config is backed up and only the MCP
keys for the servers we manage are added/replaced. Nothing else is touched.

Usage:
  mcp_config.py --platform cline  [--out PATH] [--print] [--dry-run]
  mcp_config.py --list-platforms
Env (optional, else placeholders are used):
  NCBI_EMAIL NCBI_API_KEY S2_API_KEY OPENALEX_EMAIL UNPAYWALL_EMAIL
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

HOME = Path(os.path.expanduser("~"))


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def definitions() -> dict:
    """name -> {'spec': cline-style dict, 'requires': [paths]}"""
    home = str(HOME)
    return {
        "paper-search": {
            "spec": {"command": f"{home}/.local/bin/paper-search-mcp", "args": [],
                     "env": {}, "type": "stdio"},
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
                "type": "stdio",
            },
            "requires": [f"{home}/.local/share/academic-search-mcp/.venv/bin/academic-search"],
        },
        "consensus": {
            "spec": {"command": f"{home}/.local/bin/npx",
                     "args": ["-y", "mcp-remote", "https://mcp.consensus.app/mcp"],
                     "env": {"PATH": f"{home}/.local/bin:/usr/local/bin:/usr/bin:/bin",
                             "HOME": home},
                     "type": "stdio"},
            "requires": [],
        },
        "google-scholar": {
            "spec": {"command": f"{home}/.local/bin/npx",
                     "args": ["-y", "mcp-remote",
                              "https://mcp.hasdata.com/mcp?apis=google_scholar"],
                     "env": {"PATH": f"{home}/.local/bin:/usr/local/bin:/usr/bin:/bin",
                             "HOME": home},
                     "type": "stdio"},
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
