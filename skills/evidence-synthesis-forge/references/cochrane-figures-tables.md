# Cochrane figures & tables — the official conventions

Paraphrase of Cochrane Handbook v6.5 **Part I, III.S1 "Considerations and recommendations for
figures in Cochrane reviews: graphs of statistical data"** and the Cochrane Style Manual.
© Cochrane Collaboration — paraphrase and cite; do not reproduce. These are the rules that
separate a publication-grade figure from a default plot.

## Forest plots

- **Effect measure on a log scale** for ratio measures (OR, RR, HR) — never a linear axis.
- **Columns, in order:** study label (author, year); effect estimate with CI; weight;
  the plot; and the numeric estimate + CI as text so the figure is readable without the plot.
- **Pooled estimate** = a **diamond** whose width is the CI; a vertical line at the null
  (1 for ratios, 0 for differences).
- **Weight markers** (squares) sized by weight; for **random-effects**, do not imply that a
  large study dominates the same way as fixed-effect — state the model in the caption.
- **Subgroups** in separate blocks with their own subtotal diamonds; overall diamond below.
- **Do not truncate** an out-of-range CI silently — if a CI is clipped, mark it.
- Caption must state: **effect measure, model (fixed/random), τ² estimator, and heterogeneity**.

## Funnel plots

- Only interpret with **≥10 studies** (Handbook ch. 13); below that they are uninformative.
- Plot effect (x, log scale for ratios) against **precision** (1/SE) or SE.
- **Contour-enhanced** funnels (shading for p < 0.10, 0.05, 0.01) help distinguish
  publication bias from other small-study effects — prefer them for a Cochrane-style figure.
- State that asymmetry is **not** proof of publication bias (other causes exist).

## Summary of findings / evidence profile tables

- One SoF table **per comparison**; GRADEpro-style layout (see `grade-certainty.md`).
- Absolute effects **computed** from the relative effect and a baseline risk — never guessed.
- Include all pre-specified outcomes, even empty ones.

## Risk-of-bias figures

- Both the **traffic-light** (per study × domain) and the **summary bar** (domain judgements)
  are expected; render with `robvis` using the **"cochrane"** palette.

## General figure/table conventions (Style Manual)

- **Vector output** (PDF/SVG) for line art; **≥300 dpi** raster for anything rasterised;
  never screenshot a plot.
- **Units on every axis**; define abbreviations in the caption; captions are self-contained.
- Tables: numbered, cited in text in order, no vertical rules, consistent decimal places,
  and **CI reported with the estimate** everywhere an effect appears.
- Referencing: Cochrane uses its own style; for journal submission use the journal's style
  (default here: **Vancouver/ICMJE**, numbered by first appearance).

## Outputs from this skill

- `scripts/forest_funnel.R` — forest + funnel (+ contour-enhanced) from a coding sheet, with
  the caption text generated alongside.
- `scripts/rob_figure.R` — `robvis` traffic-light + summary.
- `scripts/sof_table.py` — SoF / evidence-profile table generator.
- `scripts/prisma_flow.py` — official PRISMA 2020 flow-diagram layout from counts.
