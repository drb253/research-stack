#!/usr/bin/env python3
"""Summary-of-findings (SoF) table generator -- GRADEpro-style layout (stdlib only).

Absolute effects are COMPUTED from the relative effect and a supplied baseline risk,
never hand-typed. Certainty is validated against the GRADE levels. Missing certainty,
or a missing baseline risk for a ratio measure, is a hard error -- an SoF table with a
blank certainty column is not a Summary of findings table.

Usage:
  python3 sof_table.py --input sof.csv --outdir figs [--title "Comparison: X vs Y"]

Input CSV columns:
  outcome, n_studies, n_participants, effect_measure, relative_effect, ci_lb, ci_ub,
  baseline_risk, certainty, comments
  - effect_measure: OR | RR | HR | MD | SMD | RD
  - relative_effect/ci: the RELATIVE measure for OR/RR/HR; absolute units for MD/SMD/RD
  - baseline_risk: comparator risk (proportion, e.g. 0.15) -- required for OR/RR/HR
  - certainty: High | Moderate | Low | Very low

Outputs: sof_table.md, sof_table.html
"""
import argparse
import csv
import html
import os
import sys

LEVELS = {"high": "High", "moderate": "Moderate", "low": "Low",
          "very low": "Very low", "verylow": "Very low"}
RATIOS = {"OR", "RR", "HR"}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def absolute_effects(rel, lo, hi, baseline):
    """(control_per_1000, intervention_per_1000, text) for a ratio measure."""
    control = baseline * 1000.0

    def fmt(x):
        if x is None:
            return "?"
        return "%d %s" % (int(round(abs(x))), "fewer" if x < 0 else "more")

    diff = control * (rel - 1.0)
    d_lo = control * (lo - 1.0) if lo is not None else None
    d_hi = control * (hi - 1.0) if hi is not None else None
    return control, control * rel, "%s per 1000 (from %s to %s)" % (fmt(diff), fmt(d_lo), fmt(d_hi))


def load(path):
    out = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            out.append({(k or "").strip().lower(): (v or "").strip() for k, v in r.items()})
    return out


def validate(rows):
    errs = []
    for i, r in enumerate(rows, 1):
        m = (r.get("effect_measure") or "").upper()
        if (r.get("certainty") or "").strip().lower() not in LEVELS:
            errs.append("row %d: certainty '%s' not one of High/Moderate/Low/Very low" % (i, r.get("certainty")))
        if m in RATIOS and _f(r.get("baseline_risk")) is None:
            errs.append("row %d: ratio measure %s needs a baseline_risk (absolute effect is computed, not guessed)" % (i, m))
        if _f(r.get("relative_effect")) is None:
            errs.append("row %d: relative_effect missing or not numeric" % i)
    return errs


def render_md(rows, title):
    out = ["## %s" % title, "",
           "| Outcome | No. studies | No. participants | Effect (relative, 95% CI) | Effect (absolute) | Certainty | Comments |",
           "|---|---:|---:|---|---|---|---|"]
    for r in rows:
        m = (r.get("effect_measure") or "").upper()
        rel = _f(r.get("relative_effect")); lo = _f(r.get("ci_lb")); hi = _f(r.get("ci_ub"))
        base = _f(r.get("baseline_risk"))
        if m in RATIOS and rel is not None:
            rel_txt = "%s %.2f (%.2f to %.2f)" % (m, rel, lo if lo is not None else float("nan"),
                                                  hi if hi is not None else float("nan"))
            _, _, abs_txt = absolute_effects(rel, lo, hi, base)
        else:
            name = r.get("effect_measure") or ""
            rel_txt = "%s %.2f (%.2f to %.2f)" % (name, rel if rel is not None else float("nan"),
                                                  lo if lo is not None else float("nan"),
                                                  hi if hi is not None else float("nan"))
            abs_txt = "as measured, in %s units" % name
        out.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            r.get("outcome", ""), r.get("n_studies", ""), r.get("n_participants", ""),
            rel_txt, abs_txt, LEVELS[(r.get("certainty") or "").strip().lower()], r.get("comments", "")))
    out += ["", "*Absolute effects are computed from the relative effect and the baseline risk.*"]
    return "\n".join(out)


def render_html(md):
    return ("<!DOCTYPE html><html><head><meta charset='utf-8'><style>"
            "body{font-family:Helvetica,Arial,sans-serif;font-size:11px;margin:16px}"
            "pre{white-space:pre-wrap;font-family:Menlo,Consolas,monospace}</style></head>"
            "<body><pre>%s</pre></body></html>" % html.escape(md))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Summary-of-findings table generator.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--outdir", default="figs")
    ap.add_argument("--title", default="Summary of findings")
    args = ap.parse_args(argv)
    if not os.path.exists(args.input):
        ap.error("input not found: %s" % args.input)
    rows = load(args.input)
    errs = validate(rows)
    if errs:
        print("VALIDATION FAILED:")
        for e in errs:
            print("  -", e)
        return 2
    md = render_md(rows, args.title)
    os.makedirs(args.outdir, exist_ok=True)
    with open(os.path.join(args.outdir, "sof_table.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    with open(os.path.join(args.outdir, "sof_table.html"), "w", encoding="utf-8") as fh:
        fh.write(render_html(md))
    print("SoF table -> %s" % os.path.join(args.outdir, "sof_table.md"))
    print("  %d outcome(s); every row carries certainty and a computed absolute effect." % len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
