#!/usr/bin/env python3
"""Generate the README charts as SVG (diff-friendly, no raster).

Reproducible:  python3 scripts/make_readme_charts.py
Numbers are the repo's own measured facts (see selftest/verify output).
"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import re
from pathlib import Path
import subprocess

OUT = Path(__file__).resolve().parent.parent / "assets"
OUT.mkdir(exist_ok=True)

INK = "#0d1117"
BLUE = "#2f6feb"
GREEN = "#2ea043"
AMBER = "#d29922"
GREY = "#8b949e"


def _clean(ax):
    ax.spines[["top", "right"]].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GREY)
    ax.tick_params(colors=INK)
    ax.grid(axis="y", alpha=0.20)


def save(fig, name):
    fig.tight_layout()
    path = OUT / name
    fig.savefig(path, format="svg", transparent=False)
    plt.close(fig)
    # matplotlib writes a trailing space on every path-continuation line, so the committed
    # SVGs carried roughly a thousand whitespace-only diff hits each. Strip them here, so a
    # regeneration produces a clean diff instead of a wall of "trailing whitespace".
    text = path.read_text(encoding="utf-8")
    stripped = "\n".join(line.rstrip() for line in text.splitlines()) + "\n"
    if stripped != text:
        path.write_text(stripped, encoding="utf-8")
    print("wrote", path)


# 1. Automated checks by suite -------------------------------------------------- #
# Each number is the total its own suite prints at the end of a run. Two of them (the R
# golden tests and the live acceptance run) need R and the network, so they cannot be
# derived here; the rest could be, and the whole list is cross-checked against the README
# below instead. That check is the point: this chart previously showed four suites summing
# to 103 while the README said 198, and it omitted citation-report's 95 entirely.
SUITES = [
    ("evidence-synthesis\nforge selftest", 78, BLUE),
    ("medical-narrative\nreview selftest", 30, GREEN),
    # citation-report is environment-dependent: 137 where no PDF extractor and no OCR exist
    # (CI), 139 with an extractor but no OCR, 144 on the machine that built this chart. The
    # README's headline number uses the same configuration as this row, and its table lists
    # the other two; the check below is what keeps the two in step.
    ("citation-report\nselftest", 144, "#cf222e"),
    ("meta-analysis-forge\ngolden tests", 22, AMBER),
    ("live acceptance\n(adversarial)", 17, "#8250df"),
]
labels = [name for name, _, _ in SUITES]
vals = [value for _, value, _ in SUITES]
colors = [colour for _, _, colour in SUITES]

_README = (OUT.parent / "README.md") if OUT.parent.name != "assets" else None
if _README is None:
    _README = Path(__file__).resolve().parent.parent / "README.md"
_match = re.search(r"\*\*(\d+) automated checks, all passing\.\*\*", _README.read_text(encoding="utf-8"))
if not _match:
    raise SystemExit("README does not state '**N automated checks, all passing.**'; "
                     "cannot cross-check the chart against it")
if int(_match.group(1)) != sum(vals):
    raise SystemExit(
        "the suites sum to %d but the README claims %s -- update both together"
        % (sum(vals), _match.group(1)))

fig, ax = plt.subplots(figsize=(10.5, 4.6), dpi=120)
bars = ax.bar(labels, vals, color=colors)
ax.set_title("Automated checks by suite (all passing)", fontsize=15, fontweight="bold", color=INK)
ax.set_ylabel("assertions / checks", color=INK)
_clean(ax)
for b, v in zip(bars, vals):
    ax.text(b.get_x() + b.get_width() / 2, v + 1.5, str(v), ha="center", color=INK, fontsize=12)
save(fig, "coverage.svg")

# 2. Repository composition by area (git ls-files counts). -------------------- #
# Derived from git rather than hand-typed: a hard-coded list silently goes stale
# as files are added (it had drifted to 400 against 402 tracked files).
def _tracked_files():
    try:
        out = subprocess.check_output(["git", "ls-files"], cwd=OUT.parent, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"ERROR: `git ls-files` failed ({exc}); run from the repo.")
    return [line for line in out.splitlines() if line.strip()]


_TOP_LEVEL = ["skills/", "mcp/", "tools/", "docs/", "benchmarks/", "assets/", "config/",
              "bin/", "scripts/", ".github/"]
_tracked = _tracked_files()
_counts = {p: sum(1 for f in _tracked if f.startswith(p)) for p in _TOP_LEVEL}
_root = [f for f in _tracked if "/" not in f]
_counts["root scripts"] = sum(1 for f in _root if f.endswith(".sh"))
_counts["meta"] = len(_root) - _counts["root scripts"]

areas = _TOP_LEVEL + ["root scripts", "meta"]
files = [_counts[a] for a in areas]
order = sorted(range(len(areas)), key=lambda i: -files[i])   # largest first
areas = [areas[i] for i in order]
files = [files[i] for i in order]

total_files = sum(files)
if total_files != len(_tracked):
    raise SystemExit(
        f"ERROR: categories account for {total_files} files but git tracks "
        f"{len(_tracked)}; add the missing top-level area to _TOP_LEVEL."
    )

fig, ax = plt.subplots(figsize=(9, 4.6), dpi=120)
y = range(len(areas))
bars = ax.barh(list(y), files, color=BLUE)
ax.set_yticks(list(y))
ax.set_yticklabels(areas, color=INK)
ax.invert_yaxis()
ax.set_title(f"Repository composition  ({total_files} tracked files)",
             fontsize=15, fontweight="bold", color=INK)
ax.set_xlabel("tracked files", color=INK)
_clean(ax)
ax.grid(axis="y", alpha=0)
ax.grid(axis="x", alpha=0.20)
for b, v in zip(bars, files):
    ax.text(v + 1, b.get_y() + b.get_height() / 2, str(v), va="center", color=INK, fontsize=11)
save(fig, "composition.svg")

# 3. The 13 skills: review/synthesis vs guardrails. --------------------------- #
fig, ax = plt.subplots(figsize=(6.4, 5.2), dpi=120)
sizes = [8, 5]
colors = [BLUE, GREEN]
wedges, _ = ax.pie(sizes, colors=colors, startangle=90,
                   wedgeprops=dict(width=0.42, edgecolor="white"))
ax.text(0, 0.12, "12", ha="center", va="center", fontsize=30, fontweight="bold", color=INK)
ax.text(0, -0.22, "skills", ha="center", va="center", fontsize=13, color=GREY)
ax.legend(wedges, ["8  review / synthesis", "4  guardrails"],
          loc="lower center", bbox_to_anchor=(0.5, -0.14), frameon=False, fontsize=11)
ax.set_title("Bundled skills", fontsize=15, fontweight="bold", color=INK)
save(fig, "skills.svg")
