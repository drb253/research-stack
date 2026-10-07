#!/usr/bin/env python3
"""Generate the README charts as SVG (diff-friendly, no raster).

Reproducible:  python3 scripts/make_readme_charts.py
Numbers are the repo's own measured facts (see selftest/verify output).
"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

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
    fig.savefig(OUT / name, format="svg", transparent=False)
    plt.close(fig)
    print("wrote", OUT / name)


# 1. Automated checks by suite (numbers from the suites' own output). ---------- #
labels = ["evidence-synthesis\nforge selftest", "medical-narrative\nreview selftest",
          "meta-analysis-forge\ngolden tests", "live acceptance\n(adversarial)"]
vals = [50, 19, 17, 17]
fig, ax = plt.subplots(figsize=(9, 4.6), dpi=120)
bars = ax.bar(labels, vals, color=[BLUE, GREEN, AMBER, "#8250df"])
ax.set_title("Automated checks by suite (all passing)", fontsize=15, fontweight="bold", color=INK)
ax.set_ylabel("assertions / checks", color=INK)
_clean(ax)
for b, v in zip(bars, vals):
    ax.text(b.get_x() + b.get_width() / 2, v + 0.6, str(v), ha="center", color=INK, fontsize=12)
save(fig, "coverage.svg")

# 2. Repository composition by area (git ls-files counts). -------------------- #
areas = ["skills/", "mcp/", "tools/", "docs/", "root scripts", "config/", "bin/", "scripts/", "assets/", "meta"]
files = [198, 160, 24, 5, 4, 1, 1, 1, 3, 3]
fig, ax = plt.subplots(figsize=(9, 4.6), dpi=120)
y = range(len(areas))
bars = ax.barh(list(y), files, color=BLUE)
ax.set_yticks(list(y))
ax.set_yticklabels(areas, color=INK)
ax.invert_yaxis()
ax.set_title("Repository composition  (400 tracked files)", fontsize=15, fontweight="bold", color=INK)
ax.set_xlabel("tracked files", color=INK)
_clean(ax)
ax.grid(axis="y", alpha=0)
ax.grid(axis="x", alpha=0.20)
for b, v in zip(bars, files):
    ax.text(v + 1, b.get_y() + b.get_height() / 2, str(v), va="center", color=INK, fontsize=11)
save(fig, "composition.svg")

# 3. The 12 skills: review/synthesis vs guardrails. --------------------------- #
fig, ax = plt.subplots(figsize=(6.4, 5.2), dpi=120)
sizes = [8, 4]
colors = [BLUE, GREEN]
wedges, _ = ax.pie(sizes, colors=colors, startangle=90,
                   wedgeprops=dict(width=0.42, edgecolor="white"))
ax.text(0, 0.12, "12", ha="center", va="center", fontsize=30, fontweight="bold", color=INK)
ax.text(0, -0.22, "skills", ha="center", va="center", fontsize=13, color=GREY)
ax.legend(wedges, ["8  review / synthesis", "4  guardrails"],
          loc="lower center", bbox_to_anchor=(0.5, -0.14), frameon=False, fontsize=11)
ax.set_title("Bundled skills", fontsize=15, fontweight="bold", color=INK)
save(fig, "skills.svg")
