#!/usr/bin/env python3
"""Typeset a review in the narrative house style: metric-card cover, boxed abstract,
contents with live page numbers, numbered sections, navy-header tables, drawn screening
figure, two-column references, overlaid running footer.

Optional design upgrade. The guaranteed baseline remains ``export_document.py``, which
needs nothing beyond the standard library. This command needs a Chromium-family browser
for printing, and uses ``pypdf`` + ``reportlab`` only for the page footer; when either is
missing it degrades (no footer, or no PDF) and says so in ``issues``.

Inputs read from the workspace (all optional except the manuscript):
  final/manuscript_cited.md   numbered manuscript (build_reference_list.py)
  final/references.md         numbered reference list
  sources.csv                 evidence table + cover metrics
  claims.csv                  claim count + certainty table
  tables/table2.md            certainty table (regenerated if absent)
  prisma_counts.json          screening figure + cover metric
  house_style_narrative.json  optional presentation config

Usage:
  python3 scripts/house_style_narrative.py --workspace <review-dir>
  python3 scripts/house_style_narrative.py --workspace . --html-only
  python3 scripts/house_style_narrative.py --workspace . --out final/My_Review.pdf
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

TOOL = "house_style_narrative"

DEFAULT_CONFIG = {
    "title": "",
    "subtitle": "",
    "kicker": "Narrative Review &middot; Preventive Oncology",
    "running_title": "",
    "metrics": [],
    "toc_note": "",
    "footer_left": "Prepared with the paper-search evidence engine \u00b7 Cline",
    "status_box": {
        "heading": "Evidence status at a glance",
        "items": [],
    },
}

CANDIDATE_BROWSERS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
)


CSS = r"""
:root{
  --navy:#0B3D6B; --navy2:#12507F; --navyd:#062743;
  --teal:#0E7C7B; --teald:#0A5F5E;
  --amber:#B45309; --amberl:#FEF3C7;
  --red:#B91C1C; --redl:#FEF2F2;
  --green:#15803D; --greenl:#ECFDF5;
  --violet:#5B21B6; --violetl:#F5F3FF;
  --ink:#1E293B; --muted:#5B6B7C; --rule:#CBD5E1;
  --bg1:#F1F5F9; --bg2:#EFF6FF; --bg3:#F0FDFA;
}
*{box-sizing:border-box;}
html{-webkit-print-color-adjust:exact; print-color-adjust:exact;}
body{margin:0; color:var(--ink); background:#fff;
  font-family:"Charter","Georgia","Times New Roman",serif; font-size:10.1pt; line-height:1.5;}
@page{ size:A4; margin:15mm 14mm 19mm 14mm; }
h1,h2,h3,h4,.sans{font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;}
p{margin:0 0 7pt 0; text-align:justify; hyphens:auto; overflow-wrap:break-word;}
sup{font-size:0.70em; line-height:0; color:var(--teal); font-weight:600;}
h2.sec{font-size:13.2pt; color:var(--navy); margin:0 0 8pt 0; padding:5pt 0 5pt 9pt;
  border-left:4.5pt solid var(--navy); background:var(--bg1); letter-spacing:.1pt; break-after:avoid;}
h2.sec .n{color:var(--teal); font-weight:700; margin-right:6pt;}
h3{font-size:11.1pt; color:var(--navyd); margin:11pt 0 5pt 0; break-after:avoid;}
.cover{border-top:9pt solid var(--navy); padding-top:12pt;}
.kicker{font-family:"Helvetica Neue",Helvetica,Arial,sans-serif; font-size:8.4pt;
  letter-spacing:2.4pt; text-transform:uppercase; color:var(--teal); font-weight:700;}
h1.title{font-size:25pt; line-height:1.16; color:var(--navyd); margin:9pt 0 6pt 0; font-weight:700;}
.subtitle{font-size:12.2pt; color:var(--navy2); font-style:italic; margin:0 0 12pt 0; line-height:1.35;}
.metagrid{display:grid; grid-template-columns:repeat(4,1fr); gap:7pt; margin:13pt 0 0 0; width:100%;}
.metacard{background:var(--bg1); border-top:3pt solid var(--teal); padding:7pt 8pt;}
.metacard{min-width:0; overflow:hidden;} .metacard .lab{overflow-wrap:anywhere; font-family:"Helvetica Neue",Helvetica,Arial,sans-serif; font-size:7.1pt;
  letter-spacing:1pt; text-transform:uppercase; color:var(--muted); font-weight:700;}
.metacard .val{font-family:"Helvetica Neue",Helvetica,Arial,sans-serif; font-size:12.6pt;
  font-weight:700; color:var(--navy); line-height:1.15; margin-top:2pt;}
.metacard .val small{font-size:8.2pt; color:var(--muted); font-weight:400;}
.box{max-width:100%; border:0.9pt solid var(--rule); border-left:4.5pt solid var(--navy);
  background:var(--bg2); padding:9pt 11pt; margin:10pt 0; break-inside:avoid;}
.box .bt{font-family:"Helvetica Neue",Helvetica,Arial,sans-serif; font-size:8.6pt; font-weight:700;
  letter-spacing:1.1pt; text-transform:uppercase; color:var(--navy); margin-bottom:5pt; display:block;}
.box.amber{border-left-color:var(--amber); background:var(--amberl);}
.box.amber .bt{color:var(--amber);}
.box.good{border-left-color:var(--green); background:var(--greenl);}
.box.good .bt{color:var(--green);}
.box p:last-child{margin-bottom:0;}
table{width:100%; border-collapse:collapse; margin:8pt 0 4pt 0; font-size:8.6pt;
  font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;}
thead{display:table-header-group;}
tr{break-inside:avoid;}
th{background:var(--navy); color:#fff; text-align:left; padding:5pt 6pt; font-size:7.9pt;
  letter-spacing:.35pt; text-transform:uppercase; font-weight:700;
  border-right:0.7pt solid rgba(255,255,255,.22);}
th:last-child{border-right:none;}
td{padding:4.4pt 6pt; border-bottom:0.6pt solid var(--rule); vertical-align:top;}
tbody tr:nth-child(even){background:#F8FAFC;}
table.t2 th{background:var(--teal);}
table.ev{font-size:8.0pt; table-layout:fixed;}
table.ev th{font-size:7.2pt; padding:4.4pt 4pt; letter-spacing:.15pt;}
table.ev td{padding:3.4pt 4pt;}
table.ev td{padding:3.6pt 5pt;}
caption{caption-side:top; text-align:left; font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;
  font-size:8.7pt; font-weight:700; color:var(--navy); padding:8pt 0 3pt 0;}
caption .cap{color:var(--teal);}
.tnote{hyphens:none; font-family:"Helvetica Neue",Helvetica,Arial,sans-serif; font-size:7.5pt; color:var(--muted);
  margin:2pt 0 10pt 0; line-height:1.35;}
figure{margin:11pt 0; break-inside:avoid; text-align:center;}
figure svg,figure img{max-width:100%; height:auto;}
figcaption{font-family:"Helvetica Neue",Helvetica,Arial,sans-serif; font-size:8.2pt; color:var(--muted);
  text-align:left; margin-top:5pt; line-height:1.4;}
figcaption b{color:var(--navy);}
ol.refs{font-size:8.4pt; padding-left:0; margin:6pt 0 0 0; list-style:none;
  font-family:"Helvetica Neue",Helvetica,Arial,sans-serif; line-height:1.42; columns:2; column-gap:14pt;}
ol.refs li{break-inside:avoid; margin-bottom:5.5pt; padding-left:16pt; text-align:left;}
ol.refs li .rn{float:left; width:16pt; margin-left:-16pt; color:var(--teal); font-weight:700;}
.toc{font-family:"Helvetica Neue",Helvetica,Arial,sans-serif; font-size:9pt;}
.toc div{display:flex; padding:2.6pt 0; border-bottom:0.5pt dotted var(--rule);}
.toc .tnum{width:26pt; color:var(--teal); font-weight:700;}
.toc .ttxt{flex:1; color:var(--ink);}
.toc .tpg{color:var(--muted); font-weight:700;}
.pb{break-before:page;}
ul.tight{margin:4pt 0 8pt 0; padding-left:15pt;}
ul.tight li{margin-bottom:3.2pt; text-align:justify;}
.decl{font-family:"Helvetica Neue",Helvetica,Arial,sans-serif; font-size:8.9pt; line-height:1.45;}
.decl li{margin-bottom:4pt;}
"""

WS: Path = Path(".")

ESC = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}


def esc(text: str) -> str:
    return "".join(ESC.get(ch, ch) for ch in str(text))


def inline(text: str) -> str:
    out = esc(text)
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"\[([0-9][0-9,\-\u2013 ]*)\]", r"<sup>\1</sup>", out)
    return out


def parse_sections(md: str):
    sections, current, buf = [], None, []
    for line in md.splitlines():
        if line.startswith("## "):
            if current is not None:
                sections.append((current, buf))
            current, buf = line[3:].strip(), []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections.append((current, buf))
    return sections


def md_table(lines, cls=""):
    rows = []
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(set(c) <= set("-: ") and c for c in cells):
            continue
        rows.append(cells)
    if not rows:
        return ""
    head, body = rows[0], rows[1:]
    parts = ['<table class="%s">' % cls, "<thead><tr>"]
    parts += ["<th>%s</th>" % inline(c) for c in head]
    parts.append("</tr></thead><tbody>")
    for row in body:
        row = (row + [""] * len(head))[: len(head)]
        parts.append("<tr>" + "".join("<td>%s</td>" % inline(c) for c in row) + "</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def paras(lines):
    out, buf, table = [], [], []

    def flush_para():
        nonlocal buf
        text = " ".join(x.strip() for x in buf).strip()
        if text:
            out.append("<p>%s</p>" % inline(text))
        buf = []

    def flush_table():
        nonlocal table
        if table:
            out.append(md_table(table))
        table = []

    for raw in lines:
        line = raw.rstrip()
        if line.strip().startswith("|"):
            flush_para(); table.append(line.strip()); continue
        if table:
            flush_table()
        if not line.strip():
            flush_para(); continue
        if line.startswith("### "):
            flush_para(); out.append("<h3>%s</h3>" % inline(line[4:].strip())); continue
        if line.startswith("- "):
            flush_para(); out.append('<ul class="tight"><li>%s</li></ul>' % inline(line[2:].strip())); continue
        if line.startswith("!["):
            flush_para()
            m = re.match(r"!\[(.*?)\]\((.*?)\)", line.strip())
            if m:
                out.append('<figure><img src="%s" alt="%s"><figcaption><b>Figure.</b> %s</figcaption></figure>'
                           % (esc(m.group(2)), esc(m.group(1)), inline(m.group(1))))
            continue
        buf.append(line)
    flush_para(); flush_table()
    return "\n".join(out)


def abstract_parts(md: str):
    body = dict(parse_sections(md)).get("Abstract", [])
    parts, key, buf = {}, None, []
    for line in body:
        if line.startswith("### "):
            if key:
                parts[key] = " ".join(buf).strip()
            key, buf = line[4:].strip(), []
        elif line.strip().startswith("Keywords:"):
            parts["Keywords"] = line.strip()
        elif key:
            buf.append(line.strip())
    if key:
        parts[key] = " ".join(buf).strip()
    return parts


def declarations_html(lines):
    items = [l[2:].strip() for l in lines if l.startswith("- ")]
    if not items:
        return paras(lines)
    return '<ul class="tight decl">' + "".join("<li>%s</li>" % inline(i) for i in items) + "</ul>"


def references_html():
    path = WS / "final" / "references.md"
    if not path.is_file():
        return "", 0
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(\d+)\.\s+(.*)$", line.strip())
        if m:
            items.append('<li><span class="rn">%s.</span>%s</li>' % (m.group(1), inline(m.group(2))))
    return '<ol class="refs">%s</ol>' % "".join(items), len(items)


def plan_sections(sections):
    """Number the body, letter the appendices, and mark the special sections."""
    plan, n = [], 0
    for title, lines in sections:
        low = title.lower()
        if low == "abstract":
            continue
        if low.startswith("references"):
            plan.append({"key": "refs", "num": "&#8212;", "title": "References",
                         "kind": "references", "lines": lines})
            continue
        if low.startswith("declaration"):
            plan.append({"key": "decl", "num": "&nbsp;", "title": "Declarations",
                         "kind": "declarations", "lines": lines})
            continue
        m = re.match(r"appendix\s+([A-Z])\s*[:\-]\s*(.*)", title, re.IGNORECASE)
        if m:
            plan.append({"key": "app" + m.group(1).upper(), "num": m.group(1).upper(),
                         "title": title, "kind": "appendix", "lines": lines})
            continue
        n += 1
        plan.append({"key": "s%d" % n, "num": str(n), "title": title,
                     "kind": "body", "lines": lines})
    return plan


def evidence_table(limit=None):
    path = WS / "sources.csv"
    if not path.is_file():
        return ""
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    rows = [r for r in rows if r.get("inclusion_status") in ("included", "cited_for_context")]
    if limit:
        rows = rows[:limit]
    head = ["Source", "Study", "Design and population", "n", "Main finding", "Effect estimate"]
    widths = ["9%", "13%", "23%", "7%", "29%", "19%"]
    out = ['<table class="ev"><caption>Table 1. <span class="cap">Included sources, by first author and year</span></caption>',
           "<colgroup>" + "".join('<col style="width:%s">' % w for w in widths) + "</colgroup>",
           "<thead><tr>" + "".join("<th>%s</th>" % h for h in head) + "</tr></thead><tbody>"]
    for r in rows:
        first = (r.get("authors") or "").split(",")[0].strip() or "unknown"
        study = "%s et al., %s" % (first, r.get("year")) if "et al" in (r.get("authors") or "") \
            else "%s, %s" % (first, r.get("year"))
        design = r.get("study_design", "not_reported")
        pop = r.get("population", "not_reported")
        if pop not in ("not_applicable", "not_reported"):
            design = design + "; " + pop
        nval = r.get("n_participants", "not_reported")
        if nval in ("not_applicable", "not_reported"):
            nval = "\u2014"
        cells = [r.get("source_id", ""), study, design, nval,
                 r.get("main_finding", "not_reported"), r.get("effect_estimate", "not_reported")]
        out.append("<tr>" + "".join("<td>%s</td>" % inline(c) for c in cells) + "</tr>")
    out.append("</tbody></table>")
    out.append('<div class="tnote">Values are reproduced from the source ledger. Where a source did '
               'not report a field, the ledger records <i>not_reported</i>; no value was imputed and no '
               'estimate was recalculated. Estimates are not pooled.</div>')
    return "\n".join(out)


def certainty_table():
    path = WS / "tables" / "table2.md"
    if not path.is_file():
        return ""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(set(c) <= set("-: ") and c for c in cells):
            continue
        rows.append(cells)
    if len(rows) < 2:
        return ""
    keep = [0, 1, 2, 3, 4, 6]
    head = [rows[0][i] for i in keep if i < len(rows[0])]
    out = ['<table class="t2"><caption>Table 2. <span class="cap">Certainty of evidence by theme</span></caption>',
           "<thead><tr>" + "".join("<th>%s</th>" % h for h in head) + "</tr></thead><tbody>"]
    for row in rows[1:]:
        cells = [row[i] if i < len(row) else "" for i in keep]
        if len(cells) > 2 and cells[2] == "0":
            cells[2] = "\u2014"
        out.append("<tr>" + "".join("<td>%s</td>" % inline(c) for c in cells) + "</tr>")
    out.append("</tbody></table>")
    out.append('<div class="tnote">Certainty is a three-level judgement on design and consistency, '
               'not a GRADE assessment. Counts are claims, not pooled participants.</div>')
    return "\n".join(out)


def prisma_svg():
    path = WS / "prisma_counts.json"
    if not path.is_file():
        return ""
    c = json.loads(path.read_text(encoding="utf-8"))
    ident = c.get("identification", {})
    total_in = (ident.get("records_from_databases", 0) + ident.get("records_from_registers", 0)
                + ident.get("records_from_other_methods", 0))
    screened = c.get("screening", {}).get("records_screened", 0)
    excluded = c.get("screening", {}).get("records_excluded", 0)
    sought = c.get("retrieval", {}).get("reports_sought", 0)
    not_ret = c.get("retrieval", {}).get("reports_not_retrieved", 0)
    assessed = c.get("eligibility", {}).get("reports_assessed", 0)
    el_excl = c.get("eligibility", {}).get("reports_excluded", 0)
    included = c.get("included", {}).get("studies_included", 0)

    context = 0
    spath = WS / "sources.csv"
    if spath.is_file():
        for row in csv.DictReader(spath.open(newline="", encoding="utf-8")):
            if row.get("inclusion_status") == "cited_for_context":
                context += 1
    context = min(context, included)

    boxes = [
        ("Identification", "Records identified (n = %d)" % total_in,
         "Databases %d \u00b7 Registers %d \u00b7 Other %d" % (ident.get("records_from_databases", 0),
                                                          ident.get("records_from_registers", 0),
                                                          ident.get("records_from_other_methods", 0)),
         "Duplicates removed before screening (n = %d)" % ident.get("duplicates_removed", 0)),
        ("Screening", "Records screened (n = %d)" % screened,
         "Records excluded at title and abstract (n = %d)" % excluded, ""),
        ("Retrieval", "Reports sought for retrieval (n = %d)" % sought,
         "Reports not retrieved (n = %d)" % not_ret, ""),
        ("Eligibility", "Reports assessed for eligibility (n = %d)" % assessed,
         "Reports excluded (n = %d)" % el_excl, ""),
        ("Included", "Sources included in review (n = %d)" % included,
         "Evidence base %d \u00b7 cited for context %d" % (included - context, context), ""),
    ]

    W, H = 515, 476
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
             'font-family="Helvetica, Arial, sans-serif">' % (W, H, W, H),
             '<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
             'markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#0B3D6B"/></marker></defs>',
             '<rect width="%d" height="%d" fill="#ffffff"/>' % (W, H)]
    y = 8
    for idx, (label, title, line2, line3) in enumerate(boxes):
        parts.append('<text x="2" y="%d" font-size="7.6" font-weight="700" fill="#0E7C7B" '
                     'letter-spacing="0.4">%s</text>' % (y + 30, esc(label.upper())))
        parts.append('<rect x="88" y="%d" width="418" height="%d" rx="3" fill="#F1F5F9" '
                     'stroke="#0B3D6B" stroke-width="1"/>' % (y, 64 if line3 else 56))
        parts.append('<text x="100" y="%d" font-size="9.2" font-weight="700" fill="#062743">%s</text>'
                     % (y + 19, esc(title)))
        parts.append('<text x="100" y="%d" font-size="7.9" fill="#1E293B">%s</text>' % (y + 34, esc(line2)))
        if line3:
            parts.append('<text x="100" y="%d" font-size="7.9" fill="#5B6B7C">%s</text>' % (y + 47, esc(line3)))
        if idx < len(boxes) - 1:
            top = y + (64 if line3 else 56)
            parts.append('<line x1="297" y1="%d" x2="297" y2="%d" stroke="#0B3D6B" '
                         'stroke-width="1.1" marker-end="url(#ar)"/>' % (top, top + 22))
        y += 92
    parts.append("</svg>")
    return "".join(parts)


def cover_metrics(cfg):
    if cfg.get("metrics"):
        return [(m.get("label", ""), m.get("value", "")) for m in cfg["metrics"]]
    screened = refs = claims = verified = 0
    p = WS / "prisma_counts.json"
    if p.is_file():
        screened = json.loads(p.read_text(encoding="utf-8")).get("screening", {}).get("records_screened", 0)
    p = WS / "claims.csv"
    if p.is_file():
        claims = max(0, len(list(csv.DictReader(p.open(newline="", encoding="utf-8")))))
    p = WS / "sources.csv"
    if p.is_file():
        for row in csv.DictReader(p.open(newline="", encoding="utf-8")):
            if row.get("verification_status") == "verified" and row.get("inclusion_status") in ("included", "cited_for_context"):
                verified += 1
    p = WS / "final" / "references.md"
    if p.is_file():
        refs = len(re.findall(r"(?m)^\d+\.\s", p.read_text(encoding="utf-8")))
    return [("Records screened", str(screened)), ("Sources verified", str(verified)),
            ("Atomic claims", str(claims)), ("References", str(refs))]



def status_box_html(cfg):
    box = cfg.get("status_box") or {}
    items = [i for i in box.get("items", []) if (i.get("text") or "").strip()]
    if not items:
        return ""
    rows = "".join("<p><b>%s.</b> %s</p>" % (esc(i.get("label", "")), inline(i.get("text", "")))
                   for i in items)
    return '<div class="box amber"><span class="bt">%s</span>%s</div>' % (esc(box.get("heading", "")), rows)

def build_html(cfg, plan, ab, refs, n_refs, page_map):
    def pg(key):
        value = page_map.get(key)
        return str(value) if value else "&middot;"

    toc = "".join('<div><span class="tnum">%s</span><span class="ttxt">%s</span>'
                  '<span class="tpg">%s</span></div>' % (e["num"], esc(e["title"]), pg(e["key"]))
                  for e in plan)

    abstract_html = "".join("<p><b>%s.</b> %s</p>" % (k, inline(ab.get(k, "")))
                            for k in ("Background", "Objective", "Methods", "Results", "Conclusions")
                            if ab.get(k))

    parts = ['<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">',
             "<title>%s</title>" % esc(cfg["title"]),
             "<style>%s</style></head><body>" % CSS]

    parts.append('<div class="cover"><div class="kicker">%s</div>' % cfg["kicker"])
    parts.append('<h1 class="title">%s</h1>' % esc(cfg["title"]))
    if cfg.get("subtitle"):
        parts.append('<div class="subtitle">%s</div>' % esc(cfg["subtitle"]))
    parts.append('<div class="metagrid">')
    for label, value in cover_metrics(cfg):
        parts.append('<div class="metacard"><div class="lab">%s</div><div class="val">%s</div></div>'
                     % (esc(label), esc(value)))
    parts.append('</div>')
    parts.append('<div class="box" style="margin-top:13pt;"><span class="bt">Abstract</span>%s'
                 '<p class="tnote" style="margin:6pt 0 0 0;">%s</p></div></div>'
                 % (abstract_html, inline(ab.get("Keywords", ""))))

    parts.append('<h2 class="sec pb"><span class="n">&nbsp;</span>Contents</h2><div class="toc">%s</div>' % toc)
    if cfg.get("toc_note"):
        parts.append('<div class="tnote" style="margin-top:9pt;">%s</div>' % cfg["toc_note"])

    for entry in plan:
        kind, title, lines = entry["kind"], entry["title"], entry["lines"]
        cls = "sec pb" if kind == "references" else "sec"
        parts.append('<h2 class="%s"><span class="n">%s</span>%s</h2>' % (cls, entry["num"], esc(title)))
        if kind == "references":
            parts.append(refs)
            continue
        if kind == "declarations":
            parts.append(declarations_html(lines))
            continue
        low = title.lower()
        if kind == "appendix" and "screening" in low and prisma_svg():
            svg_path = WS / "figures" / "prisma_house.svg"
            svg_path.parent.mkdir(parents=True, exist_ok=True)
            svg_path.write_text(prisma_svg(), encoding="utf-8")
            cut = next((i for i, l in enumerate(lines) if l.strip().startswith("![")), len(lines))
            rest = [l for l in lines[cut + 1:] if not l.strip().lower().startswith("figure ")]
            parts.append('<figure><img src="%s" style="width:100%%;height:auto">'
                         '<figcaption><b>Figure 1.</b> Screening flow of records from identification to '
                         'inclusion, generated from the counts file that the arithmetic check validates.'
                         '</figcaption></figure>' % svg_path)
            parts.append(paras(rest))
            continue
        if kind == "appendix" and "evidence" in low:
            prose = [l for l in lines if not l.strip().startswith("Table ")]
            parts.append("<p>The tables below are generated from the source and claim ledgers.</p>")
            parts.append(evidence_table())
            parts.append(certainty_table())
            continue
        parts.append(paras(lines))
        if kind == "body" and title.lower().startswith("discussion"):
            parts.append(status_box_html(cfg))

    parts.append("</body></html>")
    return "\n".join(parts)


def find_browser():
    for env in ("CHROME", "CHROMIUM", "CHROME_PATH"):
        value = os.environ.get(env)
        if value and Path(value).exists():
            return Path(value)
    for name in ("chrome", "chromium", "chromium-browser", "google-chrome", "microsoft-edge"):
        found = shutil.which(name)
        if found:
            return Path(found)
    for candidate in CANDIDATE_BROWSERS:
        if Path(candidate).exists():
            return Path(candidate)
    home = Path.home()
    for pattern in ("Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell",
                    "Library/Caches/ms-playwright/chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
                    ".cache/ms-playwright/chromium-*/chrome-linux/chrome",
                    ".cache/ms-playwright/chromium_headless_shell-*/chrome-linux/headless_shell"):
        for hit in sorted(home.glob(pattern), reverse=True):
            if hit.is_file() and os.access(hit, os.X_OK):
                return hit
    return None


def render(browser, html_path, pdf_path):
    cmd = [str(browser), "--headless", "--disable-gpu", "--no-sandbox",
           "--no-pdf-header-footer", "--virtual-time-budget=15000",
           "--print-to-pdf=%s" % pdf_path, Path(html_path).resolve().as_uri()]
    done = subprocess.run(cmd, capture_output=True, text=True)
    if not Path(pdf_path).is_file():
        raise RuntimeError((done.stderr or done.stdout or "no output")[-600:])
    return Path(pdf_path)



def normalise(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def page_texts(pdf_path):
    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        total = pdf_total(pdf_path)
        out = []
        for n in range(1, total + 1):
            text = subprocess.run([pdftotext, "-layout", "-f", str(n), "-l", str(n), str(pdf_path), "-"],
                                  capture_output=True, text=True).stdout
            out.append(normalise(text))
        return out
    try:
        from pypdf import PdfReader
    except ImportError:
        return []
    return [normalise(page.extract_text() or "")
            for page in PdfReader(str(pdf_path)).pages]


def pdf_total(pdf_path):
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(pdf_path)).pages)
    except ImportError:
        info = subprocess.run(["pdfinfo", str(pdf_path)], capture_output=True, text=True).stdout
        m = re.search(r"Pages:\s+(\d+)", info)
        return int(m.group(1)) if m else 0


def locate_pages(pdf_path, plan):
    texts = page_texts(pdf_path)
    if not texts:
        return {}
    contents_page = None
    for idx, text in enumerate(texts, start=1):
        if "contents" in text and sum(1 for e in plan if e["title"].lower()[:20] in text) >= 3:
            contents_page = idx
            break
    found, cursor = {}, contents_page or 3
    for entry in plan:
        needle = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", entry["title"].lower())).strip()
        prefix = needle[:35]
        if entry["kind"] == "body" and entry["num"].isdigit():
            prefix = entry["num"] + " " + prefix
        hit = None
        for idx in range(max(cursor - 1, 2), len(texts)):
            if contents_page and (idx + 1) == contents_page:
                continue
            if prefix and prefix in texts[idx]:
                hit = idx + 1
                break
        if hit is None and entry["key"] == "s1" and contents_page:
            hit = contents_page
        if hit:
            found[entry["key"]] = hit
            cursor = hit
    return found


def stamp_footer(src, dst, running, footer_left):
    try:
        import io
        from pypdf import PdfReader, PdfWriter
        from reportlab.pdfgen import canvas
        from reportlab.lib.colors import HexColor
    except ImportError:
        return False, "pypdf/reportlab not installed"
    grey, rule, navy = HexColor("#5B6B7C"), HexColor("#CBD5E1"), HexColor("#0B3D6B")
    reader = PdfReader(str(src))
    total = len(reader.pages)
    writer = PdfWriter()
    for idx, page in enumerate(reader.pages):
        n = idx + 1
        if n > 1:
            w, h = float(page.mediabox.width), float(page.mediabox.height)
            buf = io.BytesIO()
            c = canvas.Canvas(buf, pagesize=(w, h))
            left, right, y = 39.7, w - 39.7, 36.0
            c.setStrokeColor(rule); c.setLineWidth(0.5); c.line(left, y + 11, right, y + 11)
            c.setFont("Helvetica", 6.6); c.setFillColor(grey); c.drawString(left, y, footer_left or running)
            c.setFont("Helvetica-Bold", 6.6); c.setFillColor(navy)
            c.drawRightString(right, y, "%d / %d" % (n, total))
            c.save(); buf.seek(0)
            page.merge_page(PdfReader(buf).pages[0])
        writer.add_page(page)
    writer.add_metadata({"/Title": running, "/Creator": "Cline"})
    with open(dst, "wb") as fh:
        writer.write(fh)
    return True, "%d pages" % total


def slugify(text):
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return re.sub(r"_+", "_", text)[:90] or "review"


def load_config(path):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    issues = []
    if path and Path(path).is_file():
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            issues.append({"severity": "error", "code": "CONFIG_INVALID", "detail": str(exc)})
            return cfg, issues
        for key, value in data.items():
            if key == "status_box" and isinstance(value, dict):
                cfg["status_box"].update(value)
            else:
                cfg[key] = value
    return cfg, issues


def emit(report, code):
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return code


def main():
    global WS
    parser = argparse.ArgumentParser(description="Typeset a review in the narrative house style.")
    parser.add_argument("--workspace", default=".", help="review workspace directory")
    parser.add_argument("--out", default="", help="output PDF path (default <Title>_Narrative_Review.pdf)")
    parser.add_argument("--config", default="house_style_narrative.json", help="presentation config (optional)")
    parser.add_argument("--html-only", action="store_true", help="write the HTML edition and stop")
    parser.add_argument("--no-footer", action="store_true", help="skip the overlaid page footer")
    args = parser.parse_args()

    WS = Path(args.workspace).resolve()
    issues = []
    manuscript = WS / "final" / "manuscript_cited.md"
    if not manuscript.is_file():
        return emit({"tool": TOOL, "status": "fail", "summary": {},
                     "issues": [{"severity": "error", "code": "MANUSCRIPT_MISSING",
                                 "detail": str(manuscript)}]}, 1)

    cfg_path = Path(args.config) if Path(args.config).is_absolute() else WS / args.config
    cfg, cfg_issues = load_config(cfg_path)
    issues.extend(cfg_issues)
    if any(i["severity"] == "error" for i in issues):
        return emit({"tool": TOOL, "status": "fail", "summary": {}, "issues": issues}, 1)

    md = manuscript.read_text(encoding="utf-8")
    sections = parse_sections(md)
    plan = plan_sections(sections)
    ab = abstract_parts(md)
    refs, n_refs = references_html()

    if not cfg.get("title"):
        first = next((l[2:].strip() for l in md.splitlines() if l.startswith("# ")), "Review")
        cfg["title"] = first
    if not cfg.get("running_title"):
        cfg["running_title"] = cfg["title"]

    html_path = WS / "final" / "house_style_narrative.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(build_html(cfg, plan, ab, refs, n_refs, {}), encoding="utf-8")

    if args.html_only:
        return emit({"tool": TOOL, "status": "pass",
                     "summary": {"html": str(html_path), "sections": len(plan), "references": n_refs},
                     "issues": issues}, 0)

    browser = find_browser()
    if browser is None:
        issues.append({"severity": "error", "code": "RENDERER_UNAVAILABLE",
                       "detail": "no Chromium-family browser found; set CHROME or use export_document.py"})
        return emit({"tool": TOOL, "status": "fail",
                     "summary": {"html": str(html_path)}, "issues": issues}, 1)

    tmp1 = WS / "final" / "_house_narrative_pass1.pdf"
    tmp2 = WS / "final" / "_house_narrative_render.pdf"
    try:
        render(browser, html_path, tmp1)
        mapping = locate_pages(tmp1, plan)
        html_path.write_text(build_html(cfg, plan, ab, refs, n_refs, mapping), encoding="utf-8")
        render(browser, html_path, tmp2)
    except RuntimeError as exc:
        issues.append({"severity": "error", "code": "RENDER_FAILED", "detail": str(exc)})
        return emit({"tool": TOOL, "status": "fail", "summary": {"html": str(html_path)}, "issues": issues}, 1)

    tmp1.unlink(missing_ok=True)
    target = Path(args.out) if args.out else WS / (slugify(cfg["title"]) + "_Narrative_Review.pdf")
    if not target.is_absolute():
        target = WS / target
    footer_ok = False
    if args.no_footer:
        tmp2.replace(target)
    else:
        footer_ok, detail = stamp_footer(tmp2, target, cfg["running_title"], cfg.get("footer_left", ""))
        if footer_ok:
            tmp2.unlink(missing_ok=True)
        else:
            tmp2.replace(target)
            issues.append({"severity": "warning", "code": "FOOTER_SKIPPED", "detail": detail})

    missing = [e["key"] for e in plan if e["key"] not in mapping]
    if missing:
        issues.append({"severity": "warning", "code": "TOC_UNMAPPED", "detail": ",".join(missing)})

    pages = pdf_total(target)
    final_copy = WS / "final" / target.name
    if final_copy != target:
        final_copy.write_bytes(target.read_bytes())

    return emit({"tool": TOOL, "status": "pass",
                 "summary": {"pdf": str(target), "pages": pages, "sections": len(plan),
                             "references": n_refs, "tables": 2 if (WS / "sources.csv").is_file() else 0,
                             "figures": 1 if (WS / "prisma_counts.json").is_file() else 0,
                             "renderer": str(browser), "footer": footer_ok,
                             "toc_pages": len(mapping), "html": str(html_path)},
                 "issues": issues}, 0)


if __name__ == "__main__":
    raise SystemExit(main())
