#!/usr/bin/env python3
"""Build a print-ready HTML edition of a review in the house critical-review style.

Stdlib only, no network. Reads the verified workspace artifacts and writes one HTML
document plus a manifest that the optional renderer uses for contents pagination.

Inputs (all optional except the manuscript):
  final/manuscript_cited.md   numbered manuscript produced by build_reference_list.py
  sources.csv                 evidence table by theme
  claims.csv                  certainty table
  search_log.csv              appendix search table
  final/references.md         reference list
  figures/prisma_flow.svg     screening-flow figure (embedded inline)
  house_style.json            per-review presentation config (title, badges, callouts)

Usage:
  python3 scripts/house_style_build.py --workspace <review-dir> \
      [--out final/house_style.html] [--config house_style.json] [--toc toc_pages.json]
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
from pathlib import Path

DEFAULT_CONFIG = {
    "title": "",
    "short_title": "",
    "eyebrow": "Critical Review",
    "subtitle": "An evidence-mapped, governance-focused critical review of what is proven, "
                "what is plausible, and what is missing.",
    "meta": [],
    "badges": [],
    "footer_left": "Prepared with the paper-search evidence engine \u00b7 Cline",
    "footer_right": "",
    "verdict_heading": "The one-line verdict",
    "verdict": "",
    "callouts": [],
    "abbreviations": {},
    "table_captions": {},
    "figure_caption": "",
    "evidence_table_caption": "Evidence base by interface. Counts are the verified records in "
                              "<i>sources.csv</i>; designs are abbreviated from the ledger. No estimate is pooled.",
    "certainty_table_caption": "Certainty of evidence by claim. Certainty is a three-level judgement on "
                               "design and consistency, not a GRADE assessment or a per-study risk-of-bias score.",
}

CITE_RE = re.compile(r"\[(\d{1,3}(?:\s*[,\u2013-]\s*\d{1,3})*)\]")
IMG_RE = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$")
SKIP_SECTIONS = {"abstract", "references"}
SKIP_TITLE_HINTS = ("evidence tables",)

CSS = r"""
:root{--navy:#0B3D6B;--navy2:#123f63;--teal:#0E7C7B;--teal2:#0a5c5b;--amber:#C4820F;--amber2:#8a5a08;
--red:#B3261E;--green:#1E7A46;--ink:#16212b;--muted:#5B6B7C;--line:#CBD5E1;--bg:#F1F6FA;--bg2:#E7F0F7;}
*{box-sizing:border-box;}
@page{size:A4;margin:16mm 13mm 16mm 13mm;}
@page :first{margin:0;}
html,body{margin:0;padding:0;}
body{font-family:"Palatino Linotype","Book Antiqua",Palatino,"Times New Roman",serif;color:var(--ink);
font-size:10.3pt;line-height:1.5;background:#fff;}
h1,h2,h3,h4,.tbl th,.cover,.badge{font-family:"Segoe UI","Helvetica Neue",Helvetica,Arial,sans-serif;}
.cover{position:relative;height:297mm;width:210mm;color:#fff;overflow:hidden;
background:linear-gradient(150deg,#0B3D6B 0%,#0e5a8a 42%,#0E7C7B 100%);page-break-after:always;}
.cover .grid{position:absolute;inset:0;opacity:.14;
background-image:linear-gradient(#fff 1px,transparent 1px),linear-gradient(90deg,#fff 1px,transparent 1px);
background-size:26px 26px;}
.cover .glow{position:absolute;border-radius:50%;}
.cover .g1{width:420px;height:420px;background:#7fd7d3;right:-140px;top:-120px;opacity:.18;}
.cover .g2{width:340px;height:340px;background:#ffd98a;left:-120px;bottom:-90px;opacity:.14;}
.cover .inner{position:relative;padding:26mm 20mm 0 20mm;}
.eyebrow{font-size:9.5pt;letter-spacing:.26em;text-transform:uppercase;color:#bfe3f2;font-weight:600;
font-family:"Segoe UI",Helvetica,Arial,sans-serif;}
.cover h1{font-size:29pt;line-height:1.1;margin:10mm 0 4mm 0;font-weight:800;letter-spacing:-.4px;}
.cover h1 .accent{color:#FFD98A;}
.cover .sub{font-size:13pt;color:#dceefb;font-weight:400;line-height:1.4;max-width:162mm;
font-family:"Segoe UI",Helvetica,Arial,sans-serif;}
.cover .rule{height:5px;width:96px;background:#FFD98A;border-radius:3px;margin:7mm 0;}
.cover .meta{margin-top:8mm;font-size:9.8pt;color:#cfe6f5;line-height:1.75;
font-family:"Segoe UI",Helvetica,Arial,sans-serif;}
.cover .badges{margin-top:9mm;display:flex;gap:8px;flex-wrap:wrap;}
.badge{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.35);border-radius:20px;
padding:5px 12px;font-size:9pt;color:#eaf6ff;}
.cover .foot{position:absolute;bottom:16mm;left:20mm;right:20mm;color:#bfe3f2;font-size:9pt;
border-top:1px solid rgba(255,255,255,.28);padding-top:6mm;display:flex;justify-content:space-between;
font-family:"Segoe UI",Helvetica,Arial,sans-serif;}
section{page-break-before:always;}
h2{font-size:17pt;color:var(--navy);margin:0 0 8px 0;line-height:1.15;font-weight:800;letter-spacing:-.2px;}
h2 .num{display:inline-block;background:var(--navy);color:#fff;border-radius:6px;font-size:12pt;
padding:2px 9px;margin-right:9px;vertical-align:2px;}
h3{font-size:12.4pt;color:var(--teal2);margin:14px 0 5px 0;font-weight:700;}
h4{font-size:10.8pt;color:var(--amber2);margin:11px 0 4px 0;font-weight:700;}
p{margin:0 0 7px 0;text-align:justify;}
.lead{font-size:11pt;color:#22303c;}
.sectionbar{height:4px;background:linear-gradient(90deg,var(--navy),var(--teal),var(--amber));border-radius:3px;margin:0 0 12px 0;}
a{color:var(--navy);}
ul,ol{margin:0 0 7px 0;padding-left:17px;}
li{margin:0 0 3.5px 0;text-align:justify;}
sup.cite{color:var(--navy);font-weight:700;font-size:7.4pt;}
.box{border-radius:8px;padding:9px 12px 6px 12px;margin:9px 0;font-size:9.7pt;page-break-inside:avoid;}
.box .t{font-weight:700;font-family:"Segoe UI",Helvetica,Arial,sans-serif;font-size:9.4pt;
text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px;}
.key{background:var(--bg2);border-left:5px solid var(--teal);}.key .t{color:var(--teal2);}
.warn{background:#FDF3E7;border-left:5px solid var(--amber);}.warn .t{color:var(--amber2);}
.crit{background:#FCEDEC;border-left:5px solid var(--red);}.crit .t{color:var(--red);}
.good{background:#EAF6EF;border-left:5px solid var(--green);}.good .t{color:var(--green);}
.abstractbox{background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:12px 15px 9px 15px;}
.abstractbox h2{font-size:14pt;margin-bottom:6px;}
.kws{font-size:9pt;color:var(--muted);margin-top:6px;}.kws b{color:var(--navy);}
figure{margin:11px 0;page-break-inside:avoid;}
figure svg{display:block;width:100%;height:auto;}
figcaption{font-size:8.9pt;color:#33424f;margin-top:5px;line-height:1.42;}
figcaption b{color:var(--navy);font-family:"Segoe UI",Helvetica,Arial,sans-serif;}
.tbl{width:100%;border-collapse:collapse;margin:9px 0;font-size:8.2pt;page-break-inside:auto;}
.tbl caption{caption-side:top;text-align:left;font-size:8.9pt;color:#33424f;margin-bottom:5px;line-height:1.4;}
.tbl caption b{color:var(--navy);font-family:"Segoe UI",Helvetica,Arial,sans-serif;}
.tbl th{background:var(--navy);color:#fff;text-align:left;padding:5px 6px;font-weight:600;font-size:7.9pt;
border:1px solid #0a3358;vertical-align:middle;}
.tbl td{border:1px solid var(--line);padding:4px 6px;vertical-align:top;}
.tbl tbody tr:nth-child(even){background:#F5F9FC;}
.tbl td.c{text-align:center;}
.tbl .sub{background:var(--bg2)!important;font-weight:700;color:var(--navy2);}
.pill{display:inline-block;border-radius:10px;padding:1px 7px;font-size:7.2pt;font-weight:700;color:#fff;}
.p-hi{background:var(--green);}.p-md{background:var(--amber);}.p-lo{background:var(--red);}
.refs p{font-size:8.8pt;margin:0 0 4px 0;padding-left:24px;text-indent:-24px;text-align:left;line-height:1.42;}
.refs p .n{color:var(--navy);font-weight:700;}
.refs .doi{color:var(--teal2);word-break:break-all;}
.tocrow{display:flex;justify-content:space-between;border-bottom:1px dotted #c3cedb;padding:6px 2px;
font-family:"Segoe UI",Helvetica,Arial,sans-serif;font-size:10pt;}
.tocrow .t{color:var(--navy2);}.tocrow .t .s{color:var(--teal);font-weight:700;margin-right:8px;}
.tocrow .p{color:var(--muted);font-variant-numeric:tabular-nums;}
.small{font-size:8.8pt;color:var(--muted);}
.keep{page-break-inside:avoid;}
.hr{height:1px;background:var(--line);border:0;margin:10px 0;}
"""


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def inline(text: str) -> str:
    out = esc(text)
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)
    out = CITE_RE.sub(lambda m: '<sup class="cite">[%s]</sup>' % m.group(1), out)
    return out


def md_table(rows, caption=None, cls="tbl"):
    if not rows:
        return ""
    head, body = rows[0], rows[1:]
    parts = ['<table class="%s">' % cls]
    if caption:
        parts.append("<caption>%s</caption>" % caption)
    parts.append("<thead><tr>" + "".join("<th>%s</th>" % inline(c) for c in head) + "</tr></thead><tbody>")
    for r in body:
        cells = []
        for c in r:
            klass = ' class="c"' if re.fullmatch(r"[0-9.%\u2013-]+", c.strip() or "x") and len(c.strip()) < 12 else ""
            rendered = c if c.lstrip().startswith("<span") else inline(c)
            cells.append("<td%s>%s</td>" % (klass, rendered))
        parts.append("<tr>" + "".join(cells) + "</tr>")
    parts.append("</tbody></table>")
    return "\n".join(parts)


def parse_pipe_table(lines):
    rows = []
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c or "-") for c in cells):
            continue
        rows.append(cells)
    return rows


def render_blocks(lines, workspace):
    out, para = [], []

    def flush():
        nonlocal para
        if para:
            text = " ".join(x.strip() for x in para).strip()
            if text:
                out.append("<p>%s</p>" % inline(text))
            para = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            flush(); i += 1; continue
        m = IMG_RE.match(stripped)
        if m:
            flush()
            src = (workspace / m.group(2)).resolve()
            if src.suffix.lower() == ".svg" and src.is_file():
                svg = re.sub(r"^<\?xml[^>]*\?>", "", src.read_text(encoding="utf-8")).strip()
                out.append("<figure>%s</figure>" % svg)
            i += 1; continue
        if stripped.startswith("|"):
            flush()
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i]); i += 1
            out.append(md_table(parse_pipe_table(block)))
            continue
        if stripped.startswith("- "):
            flush()
            items = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                items.append(lines[i].strip()[2:]); i += 1
            out.append("<ul>%s</ul>" % "".join("<li>%s</li>" % inline(x) for x in items))
            continue
        para.append(stripped); i += 1
    flush()
    return "\n".join(out)


def read_csv(path: Path):
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


PILL = {"high": ("p-hi", "High"), "moderate": ("p-md", "Moderate"), "low": ("p-lo", "Low"),
        "very_low": ("p-lo", "Very low"), "not_assessed": ("p-lo", "Not assessed")}


def evidence_table(sources, caption):
    if not sources or "theme" not in sources[0]:
        return ""
    themes = []
    for s in sources:
        if s.get("inclusion_status") in ("included", "cited_for_context") and s.get("theme") not in themes:
            themes.append(s.get("theme"))
    rows = [["Theme", "Sources", "Designs represented", "Included records"]]
    for theme in themes:
        group = [s for s in sources if s.get("theme") == theme
                 and s.get("inclusion_status") in ("included", "cited_for_context")]
        designs = []
        for s in group:
            d = (s.get("study_design") or "").split(" with ")[0].split("(")[0].strip(" ,;")
            if len(d) > 46:
                d = d[:44].rsplit(" ", 1)[0] + "\u2026"
            if d and d not in designs:
                designs.append(d)
        rows.append([(theme or "unassigned").replace("_", " ").capitalize(), str(len(group)),
                     "; ".join(designs[:3]), ", ".join(s["source_id"] for s in group)])
    return md_table(rows, caption="<b>Table 1.</b> " + caption)


def certainty_table(claims, caption):
    if not claims or "certainty" not in claims[0]:
        return ""
    rows = [["Claim", "Statement", "Direction", "Certainty", "Sources"]]
    for c in claims:
        klass, word = PILL.get(c.get("certainty", ""), ("p-lo", c.get("certainty", "")))
        rows.append([c.get("claim_id", ""), c.get("claim_summary", ""), c.get("direction", ""),
                     '<span class="pill %s">%s</span>' % (klass, word), c.get("source_ids", "")])
    return md_table(rows, caption="<b>Table 2.</b> " + caption)


def search_table(log, caption):
    if not log or "search_id" not in log[0]:
        return ""
    rows = [["ID", "Source", "Query", "Hits", "Included"]]
    for r in log:
        rows.append([r.get("search_id", ""), r.get("database", ""), r.get("query_string", ""),
                     r.get("hits_retrieved", ""), r.get("records_included", "")])
    return md_table(rows, caption="<b>Table A1.</b> " + caption)


def abbreviations_table(abbrevs):
    if not abbrevs:
        return ""
    rows = [["Abbreviation", "Expansion"]] + [[k, v] for k, v in abbrevs.items()]
    return md_table(rows, caption="<b>Table 3.</b> Abbreviations used in the review.", cls="tbl keep")


def load_sections(manuscript: Path):
    text = manuscript.read_text(encoding="utf-8")
    sections, current, title = [], None, None
    for line in text.splitlines():
        if line.startswith("# ") and title is None and current is None:
            title = line[2:].strip()
        elif line.startswith("## "):
            if current:
                sections.append(current)
            current = {"title": line[3:].strip(), "lines": []}
        elif current is not None:
            current["lines"].append(line)
    if current:
        sections.append(current)
    return title or "", sections


def plan_sections(sections, display_titles):
    plan, n, letter = [], 0, 0
    for sec in sections:
        raw = sec["title"]
        low = raw.lower()
        if low in SKIP_SECTIONS or any(hint in low for hint in SKIP_TITLE_HINTS):
            continue
        if low.startswith("appendix"):
            key = "s" + chr(ord("A") + letter)
            letter += 1
            label = re.sub(r"^appendix\s+[A-Za-z]\s*[:\u2014-]\s*", "", raw, flags=re.I)
            num = key[1:]
            heading = "Appendix %s \u2014 %s" % (num, label)
        elif low.startswith("declaration"):
            key, num, heading = "sdecl", "", "Declarations"
        else:
            n += 1
            key, num = "s%d" % n, str(n)
            heading = display_titles.get(raw, raw)
        plan.append({"key": key, "num": num, "heading": heading, "raw": raw, "lines": sec["lines"]})
    return plan


def cover(cfg):
    title = cfg["title"]
    accent_at = title.find(":")
    if cfg.get("accent"):
        head = title.replace(cfg["accent"], '<span class="accent">%s</span>' % esc(cfg["accent"]), 1)
    else:
        head = esc(title)
    meta = "".join("<div>%s</div>" % m for m in cfg["meta"])
    badges = "".join('<span class="badge">%s</span>' % b for b in cfg["badges"])
    right = cfg.get("footer_right") or ""
    return f"""<div class="cover">
  <div class="grid"></div><div class="glow g1"></div><div class="glow g2"></div>
  <div class="inner">
    <div class="eyebrow">{esc(cfg['eyebrow'])}</div>
    <h1>{head}</h1>
    <p class="sub">{cfg['subtitle']}</p>
    <div class="rule"></div>
    <div class="meta">{meta}</div>
    <div class="badges">{badges}</div>
  </div>
  <div class="foot"><span>{esc(cfg['footer_left'])}</span><span>{esc(right)}</span></div>
</div>"""


def abstract_section(sections, cfg):
    block = next((s for s in sections if s["title"].strip().lower() == "abstract"), None)
    if block is None:
        return ""
    labels, current, body, keywords = [], None, [], ""
    for line in block["lines"]:
        s = line.strip()
        if s.startswith("### "):
            if current:
                labels.append((current, " ".join(body)))
            current, body = s[4:].strip(), []
        elif s.lower().startswith("keywords:"):
            keywords = s.split(":", 1)[1].strip()
        elif s:
            body.append(s)
    if current:
        labels.append((current, " ".join(body)))
    paras = ["<p><b>%s.</b> %s</p>" % (name, inline(txt)) for name, txt in labels]
    kw = '<div class="kws"><b>Keywords:</b> %s</div>' % esc(keywords) if keywords else ""
    verdict = ""
    if cfg.get("verdict"):
        verdict = ('<div class="box key"><div class="t">%s</div><p style="margin-bottom:4px;">%s</p></div>'
                   % (esc(cfg["verdict_heading"]), cfg["verdict"]))
    return ('<section id="abstract"><div class="sectionbar"></div><h2>Abstract</h2>'
            '<div class="abstractbox">' + "".join(paras) + kw + '</div>' + verdict + '</section>')


def contents(plan, pages):
    rows = []
    for s in plan:
        rows.append('<div class="tocrow" data-toc="%s"><span class="t"><span class="s">%s</span>%s</span>'
                    '<span class="p">%s</span></div>' % (s["key"], s["num"] or "\u2014", esc(s["heading"]),
                                                         pages.get(s["key"], "\u2014")))
    rows.append('<div class="tocrow" data-toc="refs"><span class="t"><span class="s">\u2014</span>References</span>'
                '<span class="p">%s</span></div>' % pages.get("refs", "\u2014"))
    return '<section id="contents"><div class="sectionbar"></div><h2>Contents</h2>' + "\n".join(rows) + '</section>'


def build_sections(plan, cfg, workspace):
    sources = read_csv(workspace / "sources.csv")
    claims = read_csv(workspace / "claims.csv")
    log = read_csv(workspace / "search_log.csv")
    out = []
    for sec in plan:
        raw, lines = sec["raw"], sec["lines"]
        parts = ['<section id="%s"><div class="sectionbar"></div>' % sec["key"]]
        if sec["num"]:
            parts.append('<h2><span class="num">%s</span>%s</h2>' % (sec["num"], esc(sec["heading"])))
        else:
            parts.append("<h2>%s</h2>" % esc(sec["heading"]))

        blocks, cur_title, cur_body = [], None, []
        for line in lines:
            if line.startswith("### "):
                if cur_title is not None or any(x.strip() for x in cur_body):
                    blocks.append((cur_title, cur_body))
                cur_title, cur_body = line[4:].strip(), []
            else:
                cur_body.append(line)
        blocks.append((cur_title, cur_body))

        sub_i = 0
        for title, body_lines in blocks:
            if title:
                sub_i += 1
                if sec["num"].isdigit():
                    parts.append("<h3>%s.%d %s</h3>" % (sec["num"], sub_i, esc(title)))
                else:
                    parts.append("<h3>%s</h3>" % esc(title))
            if raw.lower().startswith("appendix a"):
                prose = [ln for ln in body_lines if not ln.strip().startswith("|")]
                parts.append(render_blocks(prose, workspace))
                if any(ln.strip().startswith("|") for ln in body_lines):
                    parts.append(search_table(log, cfg.get("search_caption",
                                 "Executed searches, with hit counts and availability.")))
            else:
                parts.append(render_blocks(body_lines, workspace))

        if raw.lower().startswith("methods"):
            parts.append("<h3>%s.%d Evidence base at a glance</h3>" % (sec["num"], sub_i + 1))
            parts.append(evidence_table(sources, cfg["evidence_table_caption"]))
            parts.append(certainty_table(claims, cfg["certainty_table_caption"]))

        for callout in cfg.get("callouts", []):
            if callout.get("section", "").strip().lower() in (raw.lower(), sec["heading"].lower(), sec["num"]):
                parts.append('<div class="box %s"><div class="t">%s</div><p>%s</p></div>'
                             % (callout.get("kind", "key"), esc(callout.get("heading", "")),
                                callout.get("text", "")))

        if cfg.get("abbreviations") and raw.lower().startswith("appendix d"):
            parts.append('<div style="page-break-before:always;"><h3>Abbreviations</h3></div>')
            parts.append(abbreviations_table(cfg["abbreviations"]))

        section_html = "\n".join(p for p in parts if p)
        for caption in cfg.get("table_captions", {}).get(raw, []):
            at = section_html.find('<table class="tbl">')
            if at == -1:
                break
            section_html = (section_html[:at] + '<table class="tbl"><caption><b>%s</b></caption>' % caption
                            + section_html[at + len('<table class="tbl">'):])

        if cfg.get("figure_caption") and raw.lower().startswith("appendix b"):
            section_html = section_html.replace("</figure>",
                "<figcaption><b>Figure 1.</b> %s</figcaption></figure>" % cfg["figure_caption"], 1)

        out.append(section_html + "</section>")
    return "\n".join(out)


def references_html(path: Path):
    if not path.is_file():
        return "", 0
    out, count = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(\d{1,3})\.\s+(.*)$", line.strip())
        if not m:
            continue
        count += 1
        rest = re.sub(r"(doi:\S+)", r'<span class="doi">\1</span>', esc(m.group(2)))
        out.append('<p><span class="n">%s.</span> %s</p>' % (m.group(1), rest))
    return "\n".join(out), count


def build(workspace: Path, config_path: Path | None, toc_path: Path | None):
    cfg = dict(DEFAULT_CONFIG)
    if config_path and config_path.is_file():
        cfg.update(json.loads(config_path.read_text(encoding="utf-8")))

    manuscript = workspace / "final" / "manuscript_cited.md"
    if not manuscript.is_file():
        raise SystemExit("missing %s: run build_reference_list.py first" % manuscript)
    title, sections = load_sections(manuscript)
    cfg["title"] = cfg.get("title") or title
    cfg["short_title"] = cfg.get("short_title") or cfg["title"].split(":")[0][:72]

    plan = plan_sections(sections, cfg.get("display_titles", {}))
    sources = read_csv(workspace / "sources.csv")
    claims = read_csv(workspace / "claims.csv")
    refs_html, ref_count = references_html(workspace / "final" / "references.md")

    if not cfg["meta"]:
        included = [s for s in sources if s.get("inclusion_status") in ("included", "cited_for_context")]
        cfg["meta"] = [
            "<b>Article type:</b> %s" % cfg.get("article_type", "Critical review \u2014 narrative synthesis with a documented, systematic search"),
            "<b>Citation style:</b> Vancouver (superscript) \u00b7 all references identifier-verified",
            "<b>Evidence base:</b> %d verified sources \u00b7 %d references" % (len(included), ref_count),
        ]
    if not cfg["badges"]:
        cfg["badges"] = cfg.get("keywords", []) or ["Evidence-mapped", "Identifier-verified"]

    pages = {}
    if toc_path and toc_path.is_file():
        pages = json.loads(toc_path.read_text(encoding="utf-8"))

    doc = ["<!DOCTYPE html>", '<html lang="en"><head><meta charset="utf-8">',
           "<title>%s</title>" % esc(cfg["title"]), "<style>%s</style></head><body>" % CSS,
           cover(cfg), abstract_section(sections, cfg), contents(plan, pages),
           build_sections(plan, cfg, workspace),
           '<section id="references"><div class="sectionbar"></div><h2>References</h2>',
           '<p class="small">Every reference was resolved against its authoritative record (Crossref, '
           'PubMed or Europe PMC) and checked for retraction. Entries are numbered in order of first '
           'appearance. No reference is cited that was not verified.</p>',
           '<div class="refs">%s</div></section>' % refs_html, "</body></html>"]
    html_doc = "\n".join(doc)

    if pages:
        for key, page in pages.items():
            html_doc = re.sub(
                r'(data-toc="%s"><span class="t">.*?<span class="p">)[^<]*(</span>)' % re.escape(key),
                lambda m: m.group(1) + str(page) + m.group(2), html_doc, flags=re.S)

    manifest = {"title": cfg["title"], "short_title": cfg["short_title"],
                "sections": [{"key": s["key"], "heading": s["heading"]} for s in plan]
                            + [{"key": "refs", "heading": "References"}],
                "references": ref_count}
    return html_doc, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the house-style HTML edition of a review.")
    parser.add_argument("--workspace", default=".", help="review workspace directory")
    parser.add_argument("--out", default="final/house_style.html", help="output HTML path")
    parser.add_argument("--config", default="house_style.json", help="presentation config (optional)")
    parser.add_argument("--toc", default="toc_pages.json", help="section page numbers (optional)")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    config_path = (workspace / args.config) if not Path(args.config).is_absolute() else Path(args.config)
    toc_path = (workspace / args.toc) if not Path(args.toc).is_absolute() else Path(args.toc)
    out_path = (workspace / args.out) if not Path(args.out).is_absolute() else Path(args.out)

    html_doc, manifest = build(workspace, config_path, toc_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_doc, encoding="utf-8")
    manifest_path = out_path.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(json.dumps({"tool": "house_style_build", "status": "pass",
                      "output": str(out_path), "manifest": str(manifest_path),
                      "sections": len(manifest["sections"]), "references": manifest["references"],
                      "tables": html_doc.count("<table"), "figures": html_doc.count("<figure")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
