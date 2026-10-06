# Vendored `paper-search-mcp`

This directory is a **complete, self-contained copy** of the `paper-search-mcp`
package, vendored so the installer never depends on PyPI or a moving upstream.

| | |
|---|---|
| **Upstream** | https://github.com/openags/paper-search-mcp |
| **Version** | `0.1.4`  (git tag `v0.1.4`, commit `c8b6421`) |
| **License** | MIT — see [`LICENSE`](LICENSE) |
| **Contents** | the full `paper_search_mcp/` package **plus** the research-stack reliability patches (43 patched/added modules) already applied |

## How it was produced

1. `git clone --branch v0.1.4 https://github.com/openags/paper-search-mcp`
2. Overlaid the patched modules from
   `../paper-search-patches/replacements/` **and** the marker-based edits — i.e.
   exactly the file set that `apply_patches.py` produces against 0.1.4.
3. Verified **byte-for-byte identical** to the installed, working package
   (`diff -rq` clean).

## Install

`install.sh` runs `uv tool install <this-dir>` by default (no PyPI, no runtime
patching). To install the PyPI release and apply patches at runtime instead, use:

```bash
./install.sh --from-pypi
```

## Notes

- **Do not hand-edit** these files — they are generated. To refresh the vendored
  copy (new upstream version or changed patches), regenerate it and re-run
  `diff -rq` against a known-good install before committing.
- `uv tool upgrade` no longer applies (the tool is installed from this path). To
  refresh, `git pull` and run `./install.sh --reinstall`.
