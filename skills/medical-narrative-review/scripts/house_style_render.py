#!/usr/bin/env python3
"""Render the house-style HTML edition to PDF, with contents pagination and a footer.

Optional: needs Playwright with Chromium, plus pypdf and reportlab. The skill's guaranteed
baseline (export_document.py) needs none of these; this renderer is the design upgrade.

Pass 1 prints the document and reads back the page each section heading lands on. Those
numbers are written to toc_pages.json, the HTML is rebuilt, and pass 2 prints the final PDF.
A footer (rule + short title + page n / N) is overlaid with reportlab on every page except
the cover, because Chromium print-to-PDF cannot emit CSS page counters.

Usage:
  python3 scripts/house_style_render.py --workspace <review-dir> [--html final/house_style.html] \
      [--out <workspace>/<Title>_Critical_Review.pdf]
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def require() -> None:
    missing = []
    for name in ("playwright", "pypdf", "reportlab", "pypdfium2"):
        try:
            __import__(name)
        except ImportError:
            missing.append(name)
    if missing:
        raise SystemExit(
            "house_style_render needs %s. Install them in a local venv and re-run with that "
            "interpreter, or use export_document.py for the baseline DOCX/PDF/HTML." % ", ".join(missing))


def slugify(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return re.sub(r"_+", "_", text)[:80]


async def print_pdf(html_path: Path, target: Path) -> None:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, errors = None, []
        for kwargs in ({"channel": "chromium"}, {"channel": "msedge"}, {"channel": "chrome"}, {}):
            try:
                browser = await p.chromium.launch(**kwargs)
                break
            except Exception as exc:  # noqa: BLE001
                errors.append("%s: %s" % (kwargs or "default", str(exc).splitlines()[0]))
        if browser is None:
            raise SystemExit("could not launch chromium:\n  " + "\n  ".join(errors))
        page = await browser.new_page()
        await page.goto(html_path.resolve().as_uri(), wait_until="load")
        await page.emulate_media(media="print")
        await page.pdf(path=str(target), print_background=True, prefer_css_page_size=True)
        await browser.close()


def locate_sections(pdf_path: Path, sections: list) -> tuple:
    from pypdf import PdfReader
    reader = PdfReader(str(pdf_path))
    texts = [(pg.extract_text() or "").replace("\n", " ") for pg in reader.pages]
    start = 3
    for idx, txt in enumerate(texts, start=1):
        if "contents" in txt.lower() and "references" in txt.lower():
            start = idx + 1
            break
    found = {}
    for sec in sections:
        needle = sec["heading"].lower()[:60]
        for idx, txt in enumerate(texts, start=1):
            if idx >= start and needle in txt[:240].lower():
                found[sec["key"]] = idx
                break
    return found, len(texts)


def overlay_footer(pdf: Path, total: int, short_title: str) -> None:
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas
    from reportlab.lib.colors import HexColor

    grey, rule, navy = HexColor("#5B6B7C"), HexColor("#CBD5E1"), HexColor("#0B3D6B")
    reader = PdfReader(str(pdf))
    writer = PdfWriter()
    for idx, page in enumerate(reader.pages):
        pnum = idx + 1
        if pnum > 1:
            w, h = float(page.mediabox.width), float(page.mediabox.height)
            buf = io.BytesIO()
            c = canvas.Canvas(buf, pagesize=(w, h))
            left, right, y = 39.0, w - 39.0, 34.0
            c.setStrokeColor(rule); c.setLineWidth(0.5); c.line(left, y + 11, right, y + 11)
            c.setFont("Helvetica", 6.6); c.setFillColor(grey); c.drawString(left, y, short_title)
            c.setFont("Helvetica-Bold", 6.6); c.setFillColor(navy)
            c.drawRightString(right, y, "%d / %d" % (pnum, total))
            c.save(); buf.seek(0)
            page.merge_page(PdfReader(buf).pages[0])
        writer.add_page(page)
    with open(pdf, "wb") as fh:
        writer.write(fh)


def rebuild(workspace: Path, html_rel: str, config_rel: str, toc_rel: str) -> None:
    subprocess.run([sys.executable, str(HERE / "house_style_build.py"),
                    "--workspace", str(workspace), "--out", html_rel,
                    "--config", config_rel, "--toc", toc_rel],
                   check=True, capture_output=True, text=True)


def cited_numbers(html_path: Path, refs_end: str = 'id="references"') -> set:
    body = html_path.read_text(encoding="utf-8").split(refs_end, 1)[0]
    nums = set()
    for inner in re.findall(r'<sup class="cite">\[([^<]+)\]</sup>', body):
        for part in re.split(r"[,\s]+", inner.strip()):
            if "-" in part:
                lo, _, hi = part.partition("-")
                if lo.isdigit() and hi.isdigit():
                    nums.update(range(int(lo), int(hi) + 1))
            elif part.isdigit():
                nums.add(int(part))
    return nums


def verify(pdf: Path, html: Path, manifest: dict) -> int:
    from pypdf import PdfReader
    reader = PdfReader(str(pdf))
    texts = [(pg.extract_text() or "").strip() for pg in reader.pages]
    whole = "\n".join(texts)
    problems = []
    blank = [i for i, t in enumerate(texts, start=1) if len(t) < 120]
    refs = int(manifest.get("references", 0))

    print("\n=== VERIFY %s ===" % pdf.name)
    print("pages: %d" % len(texts))
    print("chars extracted: %s" % format(len(whole), ","))
    print("blank/near-empty pages: %s" % (blank or "none"))
    if blank:
        problems.append("blank or near-empty pages: %s" % blank)

    for sec in manifest.get("sections", []):
        needle = sec["heading"].split("\u2014")[0].strip()[:40]
        if needle.lower() not in whole.lower():
            problems.append("missing heading: %r" % sec["heading"])

    missing = [i for i in range(1, refs + 1)
               if ("\n%d." % i) not in whole and (" %d. " % i) not in whole]
    if missing:
        problems.append("reference numbers not found: %s" % missing[:10])

    cited = cited_numbers(html)
    dangling = sorted(n for n in cited if n < 1 or n > refs)
    if dangling:
        problems.append("dangling inline citations: %s" % dangling)
    print("inline-cited references: %d of %d" % (len(cited), refs))

    toc = re.findall(r'data-toc="[^"]+"><span class="t">.*?<span class="p">([^<]*)</span>',
                     html.read_text(encoding="utf-8"), flags=re.S)
    if toc and not any(t.strip().isdigit() for t in toc):
        problems.append("contents page numbers were never populated")

    for bad in ["&nbsp;", "&mdash;", "&ndash;", "&amp;", "<sup>", "%s%s", "\\u00e2\\u20ac"]:
        if bad in whole:
            problems.append("unrendered markup/entity: %r" % bad)

    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print("  -", p)
        return 1
    print("\nAll checks passed: page count OK, no blank pages, all headings, references and "
          "citations present, no unrendered markup.")
    return 0


async def run(args) -> int:
    workspace = Path(args.workspace).resolve()
    html_path = (workspace / args.html) if not Path(args.html).is_absolute() else Path(args.html)
    manifest_path = html_path.with_suffix(".manifest.json")
    if not manifest_path.is_file():
        raise SystemExit("missing %s: run house_style_build.py first" % manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    out = Path(args.out) if args.out else (workspace / (slugify(
        manifest.get("title", "Review")) + "_Critical_Review.pdf"))
    if not out.is_absolute():
        out = workspace / out
    raw = workspace / "final" / "_house_style_render.pdf"
    toc_rel = args.toc

    rebuild(workspace, args.html, args.config, toc_rel)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))  # rebuilt above
    await print_pdf(html_path, raw)
    pages, total = locate_sections(raw, manifest.get("sections", []))
    print("pass 1: %d pages; located %d of %d headings" % (total, len(pages), len(manifest.get("sections", []))))
    if pages:
        (workspace / toc_rel).write_text(json.dumps(pages, indent=2), encoding="utf-8")
        rebuild(workspace, args.html, args.config, toc_rel)
        await print_pdf(html_path, raw)
        pages2, total = locate_sections(raw, manifest.get("sections", []))
        print("pass 2: %d pages; located %d headings" % (total, len(pages2)))

    shutil.copyfile(raw, out)
    overlay_footer(out, total, manifest.get("short_title", ""))
    print("wrote %s" % out)
    return verify(out, html_path, manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the house-style PDF edition.")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--html", default="final/house_style.html")
    parser.add_argument("--config", default="house_style.json")
    parser.add_argument("--toc", default="toc_pages.json")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    require()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
