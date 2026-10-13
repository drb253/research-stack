"""Extract text from a PDF, with a declared method and a legible refusal.

Three attempts, best first:

1. ``pdftotext -layout`` (poppler) when it is on PATH. Best quality: it preserves
   the visual line layout, which matters for two-column papers and for keeping a
   number next to its label.
2. ``pypdf`` when the package is importable. Optional dependency, exactly as the
   originality toolkit treats it.
3. Refuse, with a message that names both routes and suggests exporting to text.

The refusal is the important part. A PDF whose text cannot be read must never be
silently treated as a source that supports nothing: that would turn a tooling
problem into an accusation against the writer. The caller receives
``method="unavailable"`` and must disclose it.

No OCR. A scanned PDF has no text layer; inventing one is out of scope and would
be a different, much weaker kind of evidence. The refusal for that case is its own
message -- it says the file is a scan, not that an extractor is missing -- and it
probes for `tesseract` only to tell the reader what to install, so the reason is
accurate on a machine where OCR happens to be absent or present.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field

#: Below this many characters per page, extraction is treated as failed. A text
#: layer that yields a handful of characters per page is a scanned image with a
#: stray header, not readable evidence.
MIN_CHARS_PER_PAGE = 50

#: Refusal text, deliberately specific about both routes.
REFUSAL = (
    "cannot read the text layer of {name}: no PDF text extractor is available. "
    "Install poppler (`brew install poppler` / `apt install poppler-utils`) or the "
    "optional Python package (`pip install pypdf`), or export the document to .txt "
    "and pass that instead. Refusing to grade against unreadable evidence."
)

#: Refusal for a file that *has* no text layer. This is a property of the document, not
#: of the tooling, so it must never be reported with `REFUSAL`'s words: an extractor ran
#: and read everything there was, and there was nothing. The OCR clause is filled in
#: from a `shutil.which` probe so the message is true on the machine that reads it.
NO_TEXT_LAYER = (
    "cannot read the text layer of {name}: the file has no text layer over {pages} "
    "page(s), so it is a scan. {ocr}. Refusing to grade against unreadable evidence."
)
OCR_ABSENT = (
    "OCR is not installed; install tesseract (`brew install tesseract` / "
    "`apt install tesseract-ocr`) and export the scan to text, or supply a text export"
)
OCR_PRESENT = (
    "tesseract is installed, but this build does not transcribe scans: OCR output is a "
    "transcription, and a misread digit or citation marker would be reported as a "
    "finding about the document rather than about the scan"
)

#: The OCR binary, probed with `shutil.which` and never imported or installed. It is
#: named only so the scan refusal can tell the reader the right thing to install.
OCR_BINARY = "tesseract"


PAGE_SEPARATOR = "\f"


@dataclass
class PdfText:
    text: str = ""
    pages: list = field(default_factory=list)
    method: str = "unavailable"
    warnings: list = field(default_factory=list)
    error: str = ""
    #: True when an extractor ran and the file yielded no text at all: a scan. The
    #: caller uses this to refuse the document as an input condition rather than as a
    #: finding, and to keep it out of `REFUSAL`'s "no extractor" wording.
    no_text_layer: bool = False

    @property
    def available(self) -> bool:
        return self.method != "unavailable" and bool(self.text.strip())

    def page_of(self, offset: int) -> int:
        """1-based page number containing a character offset in `text`."""
        if not self.pages:
            return 1
        cursor = 0
        for number, page in enumerate(self.pages, start=1):
            cursor += len(page) + 1  # the separator
            if offset < cursor:
                return number
        return len(self.pages)

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "pages": len(self.pages),
            "chars": len(self.text),
            "warnings": list(self.warnings),
            "error": self.error,
        }


def _via_pdftotext(path, first_page_only: bool = False) -> PdfText | None:
    executable = shutil.which("pdftotext")
    if not executable:
        return None
    # Keep the page breaks: the form feed is what makes a source note citable to a
    # page, and every extracted evidence span is reported with one.
    command = [executable, "-layout", "-enc", "UTF-8"]
    if first_page_only:
        command += ["-f", "1", "-l", "1"]
    command += [str(path), "-"]
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=180, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        detail = (completed.stderr or b"").decode("utf-8", "replace").strip()[:200]
        return PdfText(method="unavailable", error=detail or "pdftotext failed")

    raw = completed.stdout.decode("utf-8", "replace")
    pages = raw.split(PAGE_SEPARATOR)
    # Replace each separator with a single newline so character offsets survive
    # and `PdfText.page_of` stays exact.
    return PdfText(
        text=raw.replace(PAGE_SEPARATOR, "\n"),
        pages=pages,
        method="pdftotext",
    )


def _via_pypdf(path, first_page_only: bool = False) -> PdfText | None:
    try:
        from pypdf import PdfReader  # optional dependency
    except ImportError:
        return None
    try:
        reader = PdfReader(str(path))
        pages = []
        for page in list(reader.pages)[: 1 if first_page_only else None]:
            try:
                pages.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001 - a broken page must not kill the run
                pages.append("")
    except Exception as exc:  # noqa: BLE001 - pypdf raises many exception types
        return PdfText(method="unavailable", error=type(exc).__name__ + ": " + str(exc)[:160])
    return PdfText(
        text="\n".join(pages),
        pages=pages,
        method="pypdf",
    )


def _no_text_layer(result: PdfText, warnings: list, path) -> PdfText:
    """The refusal for a file an extractor read but found no characters in: a scan.

    The OCR clause comes from a `shutil.which` probe so the refusal names what to
    install exactly when it is absent, and stays truthful when it is present.
    """
    pages = max(1, len(result.pages))
    ocr = OCR_PRESENT if shutil.which(OCR_BINARY) else OCR_ABSENT
    return PdfText(
        method="unavailable",
        text=result.text,
        pages=result.pages,
        error=NO_TEXT_LAYER.format(
            name=getattr(path, "name", path), pages=pages, ocr=ocr
        ),
        warnings=warnings + ["no text layer found; the file is a scan"],
        no_text_layer=True,
    )


def extract_pdf(path, first_page_only: bool = False) -> PdfText:
    """Extract text from `path`, declaring the method used or refusing legibly.

    ``first_page_only`` is for cheap DOI mining across a folder of sources whose
    filenames are opaque; it is not used for evidence, which always reads the whole
    document so that a page number is meaningful.
    """
    warnings: list = []
    result = _via_pdftotext(path, first_page_only)
    if result is None:
        warnings.append("pdftotext not found on PATH; fell back to pypdf")
        result = _via_pypdf(path, first_page_only)
    if result is None:
        return PdfText(method="unavailable", error=REFUSAL.format(name=getattr(path, "name", path)))
    if result.method == "unavailable":
        fallback = _via_pypdf(path, first_page_only)
        if fallback is not None and fallback.available:
            warnings.append("pdftotext failed; fell back to pypdf")
            fallback.warnings.extend(warnings)
            result = fallback
    if not result.available:
        # An extractor ran and produced nothing: the document itself has no text layer.
        # That is a scan, not a missing tool, and the two must not share one message --
        # only one of them is something the reader can install their way out of.
        if result.method != "unavailable" and not result.text.strip():
            return _no_text_layer(result, warnings, path)
        return PdfText(
            method="unavailable",
            error=result.error or REFUSAL.format(name=getattr(path, "name", path)),
            warnings=warnings,
        )

    page_count = max(1, len(result.pages))
    per_page = len(result.text) / page_count
    if per_page < MIN_CHARS_PER_PAGE:
        return PdfText(
            method="unavailable",
            text=result.text,
            pages=result.pages,
            error=(
                "text layer yielded only %.1f characters per page over %d pages "
                "(below the %d threshold); the file is probably a scan"
                % (per_page, page_count, MIN_CHARS_PER_PAGE)
            ),
            warnings=warnings + ["extraction below the per-page threshold"],
        )
    result.warnings.extend(warnings)
    return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("usage: _pdftext.py <file.pdf>")
        raise SystemExit(2)
    from pathlib import Path

    extracted = extract_pdf(Path(sys.argv[1]))
    print(extracted.to_dict())
    print(extracted.text[:400])
