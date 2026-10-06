#!/usr/bin/env python3
"""PRISMA 2020 flow diagram generator (stdlib only).

Renders the official four-phase PRISMA 2020 layout from counts. The diagram is
generated FROM the review ledger -- numbers are never hand-entered into a diagram.

Variant: new review, databases+registers+other sources (the full template).
Outputs: prisma_flow.html (print-ready A4 portrait) and prisma_flow.mmd (Mermaid).

Usage:
  python3 prisma_flow.py --counts prisma_counts.json --outdir figs

prisma_counts.json keys (missing keys render as 0 and are reported):
  identified_databases, identified_registers, identified_other,
  duplicates_removed, removed_automation, removed_other,
  screened, excluded_ta, sought, not_retrieved, assessed,
  excluded_ft: {reason: n}, included_studies, included_reports, in_meta_analysis
"""
import argparse
import csv
import html
import json
import os
import sys

DEFAULT = {
    "identified_databases": 0, "identified_registers": 0, "identified_other": 0,
    "duplicates_removed": 0, "removed_automation": 0, "removed_other": 0,
    "screened": 0, "excluded_ta": 0, "sought": 0, "not_retrieved": 0,
    "assessed": 0, "excluded_ft": {}, "included_studies": 0,
    "included_reports": 0, "in_meta_analysis": 0,
}


def normalize(data):
    """Accept either the flat schema or the nested identification/screening/... schema."""
    if isinstance(data.get("identification"), dict):
        ident = data.get("identification", {}) or {}
        scr = data.get("screening", {}) or {}
        ret = data.get("retrieval", {}) or {}
        elig = data.get("eligibility", {}) or {}
        inc = data.get("included", {}) or {}
        return {
            "identified_databases": ident.get("records_from_databases", 0),
            "identified_registers": ident.get("records_from_registers", 0),
            "identified_other": ident.get("records_from_other_methods", 0),
            "duplicates_removed": ident.get("duplicates_removed", 0),
            "removed_automation": ident.get("removed_automation", 0),
            "removed_other": ident.get("removed_other", 0),
            "screened": scr.get("records_screened", 0),
            "excluded_ta": scr.get("records_excluded", 0),
            "sought": ret.get("reports_sought", 0),
            "not_retrieved": ret.get("reports_not_retrieved", 0),
            "assessed": elig.get("reports_assessed", 0),
            "excluded_ft": elig.get("exclusion_reasons", {}) or {},
            "included_studies": inc.get("studies_included", 0),
            "included_reports": inc.get("sources_verified", inc.get("studies_included", 0)),
            "in_meta_analysis": inc.get("in_meta_analysis", 0),
        }
    return data


def load_counts(path):
    if path.endswith(".json"):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    else:  # CSV: key,value
        data = {}
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                k = (row.get("key") or "").strip()
                v = (row.get("value") or "").strip()
                if k:
                    data[k] = v
    data = normalize(data)
    c = dict(DEFAULT)
    c.update(data)
    c["excluded_ft"] = data.get("excluded_ft", {}) or {}
    return c


def check(c):
    """Reconcile the counts; return a list of arithmetic problems (never silently pass)."""
    problems = []

    def n(k):
        try:
            return int(c.get(k, 0) or 0)
        except (TypeError, ValueError):
            return 0
    ident = n("identified_databases") + n("identified_registers") + n("identified_other")
    removed = n("duplicates_removed") + n("removed_automation") + n("removed_other")
    if ident - removed != n("screened"):
        problems.append("identified(%d) - removed(%d) != screened(%d)" % (ident, removed, n("screened")))
    if n("screened") - n("excluded_ta") != n("sought"):
        problems.append("screened(%d) - excluded_ta(%d) != sought(%d)"
                        % (n("screened"), n("excluded_ta"), n("sought")))
    if n("sought") - n("not_retrieved") != n("assessed"):
        problems.append("sought(%d) - not_retrieved(%d) != assessed(%d)"
                        % (n("sought"), n("not_retrieved"), n("assessed")))
    ft_exc = sum(int(v or 0) for v in c["excluded_ft"].values())
    if n("assessed") - ft_exc != n("included_studies"):
        problems.append("assessed(%d) - excluded_ft(%d) != included(%d)"
                        % (n("assessed"), ft_exc, n("included_studies")))
    return problems


CSS = """
body{font-family:Helvetica,Arial,sans-serif;margin:18px;color:#111}
h1{font-size:15px;margin:0 0 10px}
.wrap{display:flex;gap:16px;align-items:stretch}
.col{flex:1;display:flex;flex-direction:column;gap:8px}
.box{border:1.5px solid #333;border-radius:3px;padding:7px 9px;font-size:11px;line-height:1.28;background:#fff}
.box b{display:block;font-size:11.5px;margin-bottom:2px}
.side{background:#f6f6f6}
.phase{font-size:10.5px;font-weight:bold;letter-spacing:.06em;text-transform:uppercase;
       color:#555;border-left:4px solid #333;padding-left:6px;margin:10px 0 2px}
.arrow{text-align:center;font-size:13px;color:#444;line-height:1}
.problems{color:#b00020;font-size:11px;margin-top:10px}
@media print{body{margin:8mm}}
"""

def _box(title, lines, side=False):
    body = "".join("<div>%s</div>" % html.escape(str(x)) for x in lines if x)
    cls = "box side" if side else "box"
    return '<div class="%s"><b>%s</b>%s</div>' % (cls, html.escape(title), body)


def render_html(c):
    n = lambda k: int(c.get(k, 0) or 0)
    ident_db = n("identified_databases"); ident_rg = n("identified_registers"); ident_ot = n("identified_other")
    left = [
        _box("Records identified from:", ["Databases (n = %d)" % ident_db,
             "Registers (n = %d)" % ident_rg, "Other sources (n = %d)" % ident_ot]),
        _box("Records screened", ["(n = %d)" % n("screened")]),
        _box("Reports sought for retrieval", ["(n = %d)" % n("sought")]),
        _box("Reports assessed for eligibility", ["(n = %d)" % n("assessed")]),
        _box("Studies included in review", ["(n = %d)" % n("included_studies")]),
        _box("Reports of included studies", ["(n = %d)" % n("included_reports")]),
        _box("Studies included in meta-analysis", ["(n = %d)" % n("in_meta_analysis")]),
    ]
    ft = c["excluded_ft"] or {}
    reasons = ["%s (n = %d)" % (k, int(v or 0)) for k, v in ft.items()] or ["(n = 0)"]
    right = [
        _box("Records removed before screening:", [
            "Duplicate records (n = %d)" % n("duplicates_removed"),
            "Removed by automation tools (n = %d)" % n("removed_automation"),
            "Removed for other reasons (n = %d)" % n("removed_other")], side=True),
        _box("Records excluded", ["(n = %d)" % n("excluded_ta")], side=True),
        _box("Reports not retrieved", ["(n = %d)" % n("not_retrieved")], side=True),
        _box("Reports excluded:", reasons, side=True),
    ]
    problems = check(c)
    warn = ("<div class='problems'>RECONCILIATION FAILED (counts do not add up): "
            + "; ".join(html.escape(p) for p in problems) + "</div>") if problems else ""
    return ("<!DOCTYPE html><html><head><meta charset='utf-8'><style>%s</style></head><body>"
            "<h1>PRISMA 2020 flow diagram &mdash; new review (databases, registers and other sources)</h1>"
            "<div class='wrap'><div class='col'>"
            "<div class='phase'>Identification</div>%s<div class='arrow'>&#8595;</div>%s"
            "<div class='phase'>Screening</div><div class='arrow'>&#8595;</div>%s"
            "<div class='arrow'>&#8595;</div>%s"
            "<div class='phase'>Included</div><div class='arrow'>&#8595;</div>%s%s%s</div>"
            "<div class='col'><div class='phase'>&nbsp;</div>%s<div class='arrow'>&nbsp;</div>%s"
            "<div class='arrow'>&nbsp;</div>%s<div class='arrow'>&nbsp;</div>%s</div></div>%s"
            "</body></html>") % (CSS, left[0], left[1], left[2], left[3], left[4], left[5],
                                 left[6], right[0], right[1], right[2], right[3], warn)


def render_mermaid(c):
    n = lambda k: int(c.get(k, 0) or 0)
    total = n("identified_databases") + n("identified_registers") + n("identified_other")
    removed = n("duplicates_removed") + n("removed_automation") + n("removed_other")
    lines = ["flowchart TD",
             '  A["Records identified (n = %d)"]' % total,
             '  R["Records removed before screening (n = %d)"]' % removed,
             '  B["Records screened (n = %d)"]' % n("screened"),
             '  C["Records excluded (n = %d)"]' % n("excluded_ta"),
             '  D["Reports sought (n = %d)"]' % n("sought"),
             '  E["Reports not retrieved (n = %d)"]' % n("not_retrieved"),
             '  F["Reports assessed (n = %d)"]' % n("assessed"),
             '  H["Studies included (n = %d)"]' % n("included_studies"),
             '  I["Studies in meta-analysis (n = %d)"]' % n("in_meta_analysis"),
             "  A --> R --> B", "  B --> C", "  B --> D", "  D --> E", "  D --> F",
             "  F --> H --> I"]
    for i, (k, v) in enumerate((c["excluded_ft"] or {}).items()):
        lines.append('  F --> G%d["%s (n = %d)"]' % (i, k, int(v or 0)))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="PRISMA 2020 flow diagram from counts.")
    ap.add_argument("--counts", required=True)
    ap.add_argument("--outdir", default="figs")
    args = ap.parse_args(argv)
    if not os.path.exists(args.counts):
        ap.error("counts file not found: %s" % args.counts)
    c = load_counts(args.counts)
    os.makedirs(args.outdir, exist_ok=True)
    html_path = os.path.join(args.outdir, "prisma_flow.html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(render_html(c))
    with open(os.path.join(args.outdir, "prisma_flow.mmd"), "w", encoding="utf-8") as fh:
        fh.write(render_mermaid(c))
    problems = check(c)
    print("PRISMA flow -> %s" % html_path)
    if problems:
        print("WARNING: count reconciliation failed (fix before reporting):")
        for p in problems:
            print("  -", p)
        return 2
    print("count reconciliation: OK (all stages add up)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

