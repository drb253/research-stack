"""Export the finished review as DOCX, PDF, and print-ready HTML.

All three formats are produced from the same document model, from the same final
Markdown, with no third-party packages and no network access:

  DOCX  hand-written OOXML: real Word styles, real tables, page numbers, images
  PDF   hand-written PDF: A4, Times metrics, ruled tables, vector screening figure
  HTML  print-ready CSS with page breaks, clickable citations, embedded SVG

Figures are never invented. The PDF draws the screening flow as vectors from
prisma_counts.json; the DOCX embeds a PNG if one exists or can be rasterised locally;
the HTML shows the SVG directly.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import _docxout
import _htmlout
import _markdown
import _pdfrender
from _common import issue, emit_report, read_text, run, write_text_lf

TOOL = "export_document"
FORMATS = ("docx", "pdf", "html")

RASTERIZERS = (
    ("rsvg-convert", ["-o", "{out}", "{src}"]),
    ("inkscape", ["{src}", "--export-type=png", "--export-filename={out}"]),
    ("magick", ["-density", "300", "-background", "white", "-alpha", "remove", "{src}", "{out}"]),
    ("convert", ["-density", "300", "-background", "white", "-alpha", "remove", "{src}", "{out}"]),
)


def parse_formats(value: str) -> list:
    if value.strip().lower() in ("all", "both", ""):
        return list(FORMATS)
    wanted: list = []
    for part in value.split(","):
        name = part.strip().lower()
        if not name:
            continue
        if name not in FORMATS:
            raise ValueError("unsupported format: %s (choose from %s)" % (name, ", ".join(FORMATS)))
        if name not in wanted:
            wanted.append(name)
    if not wanted:
        raise ValueError("no output format selected")
    return wanted


def build_blocks(manuscript: str, references: str, appends: list) -> list:
    blocks = _markdown.parse(read_text(manuscript, {".md", ".markdown"}))
    for path in appends:
        blocks.extend(_markdown.parse(read_text(path, {".md", ".markdown"})))
    if references:
        reference_text = read_text(references, {".md", ".markdown"})
        lines = reference_text.splitlines()
        if lines and lines[0].strip().lower().startswith("#"):
            lines = lines[1:]
        entry_text = "\n".join(line for line in lines if line.strip())
        blocks.extend(_markdown.parse("# References\n\n" + entry_text))
    return blocks


def rasterize_svg(svg_path: Path, png_path: Path, warnings: list) -> bool:
    """Try the local SVG rasterisers. Returns True when a PNG was produced."""
    for tool, template in RASTERIZERS:
        executable = shutil.which(tool)
        if not executable:
            continue
        command = [
            executable if part == "{tool}" else part.format(src=str(svg_path), out=str(png_path))
            for part in ([tool] + template)
        ]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            warnings.append("rasteriser %s failed: %s" % (tool, type(exc).__name__))
            continue
        if completed.returncode == 0 and png_path.is_file():
            warnings.append("rasterised with " + tool)
            return True
        warnings.append("rasteriser %s returned %d" % (tool, completed.returncode))
    quicklook = shutil.which("qlmanage")
    if quicklook:
        try:
            completed = subprocess.run(
                [quicklook, "-t", "-s", "2000", "-o", str(png_path.parent), str(svg_path)],
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            completed = None
        candidate = png_path.parent / (svg_path.name + ".png")
        if completed is not None and candidate.is_file():
            candidate.replace(png_path)
            warnings.append("rasterised with qlmanage")
            return True
    return False


def resolve_images(blocks: list, base: Path, want_png: bool, warnings: list) -> dict:
    """Map a Markdown image path to (relationship id, payload, media file name).

    The media name always carries the extension of the bytes actually embedded, so a
    rasterised PNG is never announced as an SVG: Word renders picture bytes by their
    real type.
    """
    images: dict = {}
    counter = 0
    if not want_png:
        return images
    for block in blocks:
        if block.kind != "image" or not block.path:
            continue
        key = block.path.replace("\\", "/").lstrip("./")
        candidates = [base / key]
        if (base / key).suffix.lower() == ".svg":
            candidates.append((base / key).with_suffix(".png"))
        payload = None
        chosen = None
        for candidate in candidates:
            if candidate.is_file() and candidate.suffix.lower() in (".png", ".jpg", ".jpeg"):
                payload = candidate.read_bytes()
                chosen = candidate
                break
        if payload is None and candidates and candidates[0].suffix.lower() == ".svg":
            if candidates[0].is_file():
                png_target = candidates[0].with_suffix(".png")
                if rasterize_svg(candidates[0], png_target, warnings) and png_target.is_file():
                    payload = png_target.read_bytes()
                    chosen = png_target
        if payload is None or chosen is None:
            warnings.append("no raster image available for " + key)
            continue
        counter += 1
        media_name = chosen.name
        if any(entry[2] == media_name for entry in images.values()):
            media_name = "%d-%s" % (counter, media_name)
        images[key] = ("rIdImage%d" % counter, payload, media_name)
        warnings.append("embedded %s from %s" % (key, chosen.name))
    return images



def ensure_figure(figure_json: str, base: Path, out_dir: Path, warnings: list) -> tuple:
    """Return (counts, svg_relative_path), generating the SVG if it is missing."""
    counts = json.loads(read_text(figure_json, {".json"})) if figure_json else None
    if counts is None:
        return None, ""
    import make_prisma_flow

    svg_dir = base / "figures"
    svg_dir.mkdir(parents=True, exist_ok=True)
    svg_path = svg_dir / "prisma_flow.svg"
    try:
        write_text_lf(svg_path, make_prisma_flow.render_svg(counts))
        write_text_lf(svg_dir / "prisma_flow.mmd", make_prisma_flow.render_mermaid(counts))
    except ValueError as exc:
        warnings.append("figure not drawn: " + str(exc)[:120])
        return None, ""
    try:
        relative = str(svg_path.relative_to(out_dir))
    except ValueError:
        relative = os.path.relpath(svg_path, out_dir)
    return counts, relative.replace(os.sep, "/")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export a finished review as DOCX, PDF, and print-ready HTML from the same "
            "final Markdown. Offline, dependency-free, deterministic."
        )
    )
    parser.add_argument("manuscript", help="final Markdown, for example final/manuscript_cited.md")
    parser.add_argument(
        "--format", default="all", help="comma-separated outputs: docx,pdf,html, or all (default)"
    )
    parser.add_argument("--out-dir", default=None, help="output directory (default: manuscript folder)")
    parser.add_argument(
        "--workspace", default=None, help="base directory for figure paths (default: manuscript folder)"
    )
    parser.add_argument("--references", default=None, help="reference list Markdown to append")
    parser.add_argument(
        "--append",
        action="append",
        default=[],
        help="extra Markdown to append, for example a generated table (repeatable)",
    )
    parser.add_argument(
        "--figure",
        default=None,
        help="prisma_counts.json: the PDF draws the flow as vectors, HTML embeds the SVG",
    )
    parser.add_argument("--title", default="", help="document title for file metadata")
    parser.add_argument("--author", default="", help="author name for file metadata")
    parser.add_argument("--citation-style", default="", help="recorded in the report only")
    parser.add_argument("--footer-left", default="", help="left-hand footer text, usually the short title")
    parser.add_argument(
        "--no-rasterise",
        action="store_true",
        help="do not attempt SVG to PNG conversion for DOCX figures",
    )
    return parser


def main_cli() -> int:
    args = build_parser().parse_args()
    formats = parse_formats(args.format)
    manuscript = Path(args.manuscript)
    out_dir = Path(args.out_dir) if args.out_dir else manuscript.parent
    workspace = Path(args.workspace) if args.workspace else manuscript.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    blocks = build_blocks(str(manuscript), args.references, args.append)
    warnings: list = []
    counts, svg_relative = ensure_figure(args.figure, workspace, out_dir, warnings)

    reference_count = 0
    if args.references and Path(args.references).is_file():
        reference_count = sum(
            1
            for line in read_text(args.references, {".md", ".markdown"}).splitlines()
            if _htmlout.REFERENCE_ENTRY_RE.match(line.strip())
        )
    summary = _markdown.summarise(blocks)
    generated_on = datetime.date.today().isoformat()
    byline = [line for line in (
        ("Citation style: " + args.citation_style) if args.citation_style else "",
        "Generated " + generated_on,
        "%d words, %d references" % (summary["words"], reference_count),
    ) if line]
    meta = {
        "title": args.title or "Medical narrative review",
        "author": args.author,
        "footer_left": args.footer_left,
        "citation_style": args.citation_style,
        "generated_on": generated_on,
        "byline": byline,
    }

    issues: list = []
    outputs: list = []
    stem = manuscript.stem.replace("_cited", "") or "manuscript"

    if "docx" in formats:
        images = resolve_images(blocks, workspace, not args.no_rasterise, warnings)
        target = out_dir / (stem + ".docx")
        report = _docxout.write_docx(str(target), blocks, meta, images)
        report["path"] = str(target)
        outputs.append(report)

    if "pdf" in formats:
        payload, report = _pdfrender.render(blocks, meta, counts)
        target = out_dir / (stem + ".pdf")
        target.write_bytes(payload)
        report["path"] = str(target)
        outputs.append(report)
        if report.get("substituted_characters"):
            issues.append(
                issue(
                    "warning",
                    "PDF_CHARACTERS_SUBSTITUTED",
                    detail=",".join(report["substituted_characters"])[:140],
                )
            )

    if "html" in formats:
        payload, report = _htmlout.render(blocks, meta, svg_relative)
        target = out_dir / (stem + ".html")
        write_text_lf(target, payload)
        report["path"] = str(target)
        outputs.append(report)

    seen: set = set()
    for message in warnings:
        if message in seen:
            continue
        seen.add(message)
        severity = "warning" if "no raster image" in message else "info"
        issues.append(issue(severity, "EXPORT_NOTE", detail=message[:140]))

    return emit_report(
        TOOL,
        issues,
        summary={
            "formats": formats,
            "blocks": summary["blocks"],
            "words": summary["words"],
            "references": reference_count,
            "figure": "included" if counts is not None else "not requested",
        },
        extra={"outputs": outputs},
    )


if __name__ == "__main__":
    run(TOOL, main_cli)

