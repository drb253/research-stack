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

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

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
#: The scan refusal when the engine is present and OCR was switched off. Distinct from
#: `OCR_PRESENT`, which says the build cannot transcribe -- that would be false here, and a
#: reader who is told the wrong reason cannot close the gap.
OCR_DISABLED = (
    "tesseract is installed; OCR was switched off for this run (--no-ocr or "
    "CITATION_REPORT_OCR), so the scan was not transcribed. Re-run without it to read the "
    "scan"
)

#: The OCR tier's own refusals. Each names the condition and what would close it, and each
#: is an input gap: none of them is a statement about the document's contents.
OCR_FAILED = (
    "OCR was attempted on {name} and the engine failed: {detail}. Nothing was graded from "
    "the scan."
)
OCR_EMPTY = (
    "OCR read {name} and found no text over {pages} page(s): the scan may be blank, or its "
    "language may not match the language data installed. Nothing was graded from it."
)
OCR_PAGE_LIMIT = (
    "{name} is a scan with more than {cap} page(s), above the OCR page limit, so it was not "
    "read in full. Nothing was graded from it."
)
OCR_LANGUAGE = (
    "the language data for '{lang}' is not installed, so {name} was not transcribed. "
    "Installed: {available}."
)
OCR_RASTERIZER = (
    "tesseract is installed but no page rasteriser is, so {name} could not be turned into "
    "page images for OCR."
)

#: The OCR binary, probed with `shutil.which` and never imported or installed. It is
#: named only so the scan refusal can tell the reader the right thing to install.
OCR_BINARY = "tesseract"

#: OCR needs the page images, and the only rasteriser this tool uses is poppler's. Both
#: are probed, never installed, and never imported: the tier is optional in exactly the
#: way the text extractors are.
PDFTOPPM_BINARY = "pdftoppm"
PDFINFO_BINARY = "pdfinfo"

#: OCR settings. 300 dpi is the usual floor for body text; the page cap and the timeout
#: exist so a 900-page scan cannot turn a report into an unbounded job, and both are
#: reported as input gaps rather than silently truncating the document.
OCR_LANG_DEFAULT = "eng"
OCR_MAX_PAGES = 40
OCR_DPI = 300
OCR_TIMEOUT_SECONDS = 300

#: Set to `none`/`off`/`0`/`false` to disable OCR even where tesseract is installed, so the
#: refusal path stays testable on a machine that has the engine (and so a user can pin the
#: old behaviour without editing code).
OCR_ENV = "CITATION_REPORT_OCR"

#: Machine-readable names for the ways a PDF can be unreadable. They travel with the
#: refusal so the caller can put them in a structured `input_gaps[]` worklist instead of
#: leaving the reader to parse an English sentence.
GAP_NO_EXTRACTOR = "no_pdf_extractor"
GAP_NO_TEXT_LAYER = "no_text_layer"
GAP_UNREADABLE_PDF = "unreadable_pdf"
GAP_NO_RASTERIZER = "no_pdf_rasterizer"
GAP_OCR_FAILED = "ocr_failed"
GAP_OCR_EMPTY = "ocr_empty"
GAP_OCR_PAGE_LIMIT = "ocr_page_limit"
GAP_OCR_LANGUAGE = "ocr_language_missing"

#: What the reader would have to change to close each gap. One string per gap kind, kept
#: next to the refusal text it belongs to so the message and the worklist cannot drift.
WORKLIST_NO_EXTRACTOR = (
    "install poppler (`brew install poppler` / `apt install poppler-utils`) or the "
    "optional Python package (`pip install pypdf`); or export the document to .txt and "
    "pass that instead"
)
WORKLIST_NO_TEXT_LAYER = (
    "install tesseract (`brew install tesseract` / `apt install tesseract-ocr`) and "
    "export the scan to text, or supply a text export"
)
WORKLIST_UNREADABLE_PDF = (
    "supply a text export or a readable copy of the file: an extractor is installed, so "
    "the file itself is what could not be read"
)
WORKLIST_NO_RASTERIZER = (
    "install poppler for its page rasteriser (`brew install poppler` / "
    "`apt install poppler-utils`), or export the scan to text and supply that"
)
WORKLIST_OCR_LANGUAGE = (
    "install the language data (`brew install tesseract-lang`, or "
    "`apt install tesseract-ocr-<lang>`), or pass --ocr-lang with a language that is "
    "installed"
)
WORKLIST_OCR_PAGE_LIMIT = (
    "raise the limit with --ocr-max-pages N, or supply a text export: the document was "
    "not read in full, so nothing was graded from it"
)

#: Force the absent-extractor refusal even where poppler or pypdf is installed. Set to
#: `none`/`absent`/`off`. This exists because the branch that says "install an extractor"
#: can otherwise never be exercised on a machine that has one -- which is exactly how a
#: broken refusal message reaches a CI box that has none.
EXTRACTOR_ENV = "CITATION_REPORT_PDF_EXTRACTOR"
_FORCE_ABSENT = ("none", "absent", "off", "0", "false")


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
    #: Which input condition made the file unreadable (`GAP_*` above), and what would
    #: close it. Empty on a successful read. Both travel to the caller so the refusal can
    #: be reported as a gap with a worklist rather than only as prose.
    gap_kind: str = ""
    gap_worklist: str = ""
    #: True when the text came from OCR rather than from a text layer or a digital
    #: document. Every caller that grades or quotes this text must carry the flag, because
    #: a transcription error would otherwise be reported as a fact about the document --
    #: and a contradiction built on transcribed evidence is an accusation about an author
    #: resting on a machine's guess.
    transcribed: bool = False
    #: What produced the transcription, e.g. `tesseract:eng`. Empty when not transcribed.
    transcription: str = ""

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
            "transcribed": self.transcribed,
            "transcription": self.transcription,
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
    # pdftotext ends every page with a form feed, so the split leaves a trailing empty
    # segment that is not a page. Counting it made a one-page scan report "over 2 page(s)"
    # and made `page_of` fall back to a phantom page number.
    if len(pages) > 1 and not pages[-1].strip():
        pages = pages[:-1]
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


def _no_text_layer(result: PdfText, warnings: list, path, ocr_disabled: bool = False) -> PdfText:
    """The refusal for a file an extractor read but found no characters in: a scan.

    The OCR clause is chosen from what is actually true on this machine and this run: the
    engine is absent (name the install), present but switched off (name the switch), or --
    the case that cannot be reached from here -- present and willing, in which case the
    caller transcribes instead of refusing.
    """
    pages = max(1, len(result.pages))
    if shutil.which(OCR_BINARY):
        ocr = OCR_DISABLED if ocr_disabled else OCR_PRESENT
    else:
        ocr = OCR_ABSENT
    return PdfText(
        method="unavailable",
        text=result.text,
        pages=result.pages,
        error=NO_TEXT_LAYER.format(
            name=getattr(path, "name", path), pages=pages, ocr=ocr
        ),
        warnings=warnings + ["no text layer found; the file is a scan"],
        no_text_layer=True,
        gap_kind=GAP_NO_TEXT_LAYER,
        gap_worklist=WORKLIST_NO_TEXT_LAYER,
    )


def ocr_available() -> bool:
    """Whether the OCR tier could run here: engine and rasteriser both present."""
    return bool(shutil.which(OCR_BINARY)) and bool(shutil.which(PDFTOPPM_BINARY))


def ocr_languages() -> list:
    """The language data tesseract reports, or [] if it cannot be asked."""
    executable = shutil.which(OCR_BINARY)
    if not executable:
        return []
    try:
        completed = subprocess.run(
            [executable, "--list-langs"], capture_output=True, timeout=60, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return []
    lines = (completed.stdout or b"").decode("utf-8", "replace").splitlines()
    # The first line is a header ("List of available languages in ... (2):").
    return sorted(line.strip() for line in lines[1:] if line.strip())


def _pdf_page_count(path) -> int:
    """The page count from `pdfinfo`, or 0 when it cannot be determined."""
    executable = shutil.which(PDFINFO_BINARY)
    if not executable:
        return 0
    try:
        completed = subprocess.run(
            [executable, str(path)], capture_output=True, timeout=60, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    for line in (completed.stdout or b"").decode("utf-8", "replace").splitlines():
        if line.lower().startswith("pages:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return 0
    return 0


def _ocr_gap(path, kind: str, worklist: str, message: str, warnings: list) -> PdfText:
    return PdfText(
        method="unavailable",
        error=message,
        warnings=warnings,
        gap_kind=kind,
        gap_worklist=worklist,
    )


def _via_tesseract(
    path,
    first_page_only: bool = False,
    *,
    lang: str = OCR_LANG_DEFAULT,
    max_pages: int = OCR_MAX_PAGES,
) -> PdfText | None:
    """Transcribe a scan with tesseract, or return a gap explaining why not.

    Returns `None` only when the engine itself is absent -- the caller then refuses with
    the "install tesseract" wording it already has. Every other outcome is a `PdfText`:
    either transcribed text (`transcribed=True`, `transcription='tesseract:<lang>'`) or an
    input gap, never a document that quietly graded to zero sentences.

    poppler rasterises the pages, because tesseract reads images rather than PDFs; both
    binaries are probed, neither is installed or imported.
    """
    name = getattr(path, "name", path)
    engine = shutil.which(OCR_BINARY)
    if not engine:
        return None
    raster = shutil.which(PDFTOPPM_BINARY)
    if not raster:
        return _ocr_gap(
            path, GAP_NO_RASTERIZER, WORKLIST_NO_RASTERIZER,
            OCR_RASTERIZER.format(name=name), [],
        )
    available = ocr_languages()
    if available and lang not in available:
        return _ocr_gap(
            path, GAP_OCR_LANGUAGE, WORKLIST_OCR_LANGUAGE,
            OCR_LANGUAGE.format(lang=lang, name=name, available=", ".join(available)), [],
        )
    # Bound the work before rasterising: pdfinfo when it is there, otherwise rasterise one
    # page past the cap and let the count decide.
    declared = _pdf_page_count(path)
    if declared and declared > max_pages:
        return _ocr_gap(
            path, GAP_OCR_PAGE_LIMIT, WORKLIST_OCR_PAGE_LIMIT,
            OCR_PAGE_LIMIT.format(name=name, cap=max_pages), [],
        )

    warnings: list = []
    with tempfile.TemporaryDirectory(prefix="cr-ocr-") as work:
        prefix = str(Path(work) / "page")
        last = 1 if first_page_only else max_pages + 1
        command = [raster, "-r", str(OCR_DPI), "-png", "-f", "1", "-l", str(last),
                   str(path), prefix]
        try:
            rasterised = subprocess.run(
                command, capture_output=True, timeout=OCR_TIMEOUT_SECONDS, check=False
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return _ocr_gap(
                path, GAP_OCR_FAILED, WORKLIST_NO_RASTERIZER,
                OCR_FAILED.format(name=name, detail=type(exc).__name__), warnings,
            )
        images = sorted(Path(work).glob("page*.png"))
        if not images:
            detail = (rasterised.stderr or b"").decode("utf-8", "replace").strip()[:200]
            return _ocr_gap(
                path, GAP_OCR_FAILED, WORKLIST_NO_RASTERIZER,
                OCR_FAILED.format(name=name, detail=detail or "no page images were produced"),
                warnings,
            )
        if not first_page_only and len(images) > max_pages:
            return _ocr_gap(
                path, GAP_OCR_PAGE_LIMIT, WORKLIST_OCR_PAGE_LIMIT,
                OCR_PAGE_LIMIT.format(name=name, cap=max_pages), warnings,
            )
        warnings.append(
            "text came from OCR (%s, %s dpi): a transcription, not the document's own "
            "text layer" % (lang, OCR_DPI)
        )
        pages: list = []
        for image in images:
            try:
                completed = subprocess.run(
                    [engine, str(image), "stdout", "-l", lang],
                    capture_output=True, timeout=OCR_TIMEOUT_SECONDS, check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                return _ocr_gap(
                    path, GAP_OCR_FAILED, WORKLIST_NO_TEXT_LAYER,
                    OCR_FAILED.format(name=name, detail=type(exc).__name__), warnings,
                )
            text = (completed.stdout or b"").decode("utf-8", "replace")
            if completed.returncode != 0 and not text.strip():
                detail = (completed.stderr or b"").decode("utf-8", "replace").strip()[:200]
                return _ocr_gap(
                    path, GAP_OCR_FAILED, WORKLIST_NO_TEXT_LAYER,
                    OCR_FAILED.format(name=name, detail=detail or "tesseract exited %d"
                                      % completed.returncode),
                    warnings,
                )
            pages.append(text)

    joined = "\n".join(pages)
    if not joined.strip():
        return _ocr_gap(
            path, GAP_OCR_EMPTY, WORKLIST_NO_TEXT_LAYER,
            OCR_EMPTY.format(name=name, pages=len(pages)), warnings,
        )
    return PdfText(
        text=joined,
        pages=pages,
        method="tesseract",
        warnings=warnings,
        transcribed=True,
        transcription="tesseract:%s" % lang,
    )


def _pypdf_importable() -> bool:
    """Whether the optional `pypdf` extractor could be used, without importing it."""
    try:
        import importlib.util

        return importlib.util.find_spec("pypdf") is not None
    except Exception:  # noqa: BLE001 - a broken install must not mask the refusal
        return False


def _extractor_present() -> bool:
    """Whether *any* extractor is available on this machine."""
    return bool(shutil.which("pdftotext")) or _pypdf_importable()


def _refusal(path, *, extractor_present: bool, detail: str = "") -> PdfText:
    """The refusal for a file nothing could read.

    The distinction matters to the reader and to the exit-status contract: with no
    extractor installed the gap is closed by installing one, and without poppler/pypdf
    alive nothing at all could be read. `detail` carries an extractor's own failure for a
    file that *is* readable in principle, so a corrupt file is not blamed on missing
    tooling.
    """
    name = getattr(path, "name", path)
    if extractor_present:
        return PdfText(
            method="unavailable",
            error=detail or ("cannot read the text layer of %s; the file could not be "
                             "decoded" % name),
            gap_kind=GAP_UNREADABLE_PDF,
            gap_worklist=WORKLIST_UNREADABLE_PDF,
        )
    return PdfText(
        method="unavailable",
        error=REFUSAL.format(name=name),
        gap_kind=GAP_NO_EXTRACTOR,
        gap_worklist=WORKLIST_NO_EXTRACTOR,
    )


def ocr_enabled(flag: bool = True) -> bool:
    """Whether the OCR tier should be attempted: asked for, and not disabled."""
    if not flag:
        return False
    return os.environ.get(OCR_ENV, "").strip().lower() not in _FORCE_ABSENT


def extract_pdf(
    path,
    first_page_only: bool = False,
    *,
    ocr: bool = True,
    ocr_lang: str = OCR_LANG_DEFAULT,
    ocr_max_pages: int = OCR_MAX_PAGES,
) -> PdfText:
    """Extract text from `path`, declaring the method used or refusing legibly.

    ``first_page_only`` is for cheap DOI mining across a folder of sources whose
    filenames are opaque; it is not used for evidence, which always reads the whole
    document so that a page number is meaningful.

    ``ocr`` (default on) transcribes a scan when tesseract is installed; the result is
    marked ``transcribed`` so no caller can mistake a machine's reading for the
    document's own text. A scan with no OCR available still refuses.

    Every unreadable outcome returns a `PdfText` carrying a `gap_kind` and a
    `gap_worklist`, because "we could not read this" is a statement about our inputs and
    must never reach the caller in the same shape as a finding about the document.
    """
    warnings: list = []
    forced = os.environ.get(EXTRACTOR_ENV, "").strip().lower()
    if forced in _FORCE_ABSENT:
        return _refusal(path, extractor_present=False)

    def transcribe(reason_warnings: list, fallback_gap: PdfText) -> PdfText:
        """Try the OCR tier, then fall back to the refusal that names what to install."""
        if ocr_enabled(ocr):
            attempt = _via_tesseract(
                path, first_page_only, lang=ocr_lang, max_pages=ocr_max_pages
            )
            if attempt is not None:
                attempt.warnings = reason_warnings + attempt.warnings
                return attempt
        fallback_gap.warnings = reason_warnings + fallback_gap.warnings
        return fallback_gap

    result = _via_pdftotext(path, first_page_only)
    if result is None:
        warnings.append("pdftotext not found on PATH; fell back to pypdf")
        result = _via_pypdf(path, first_page_only)
    if result is None:
        # Nothing can read a text layer. OCR reads page images instead, so it is the only
        # remaining route, and it is the one route that does not need an extractor at all.
        return transcribe(warnings, _refusal(path, extractor_present=False))
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
            return transcribe(
                warnings,
                _no_text_layer(result, warnings, path, ocr_disabled=not ocr_enabled(ocr)),
            )
        refused = _refusal(
            path,
            extractor_present=_extractor_present(),
            detail=result.error,
        )
        refused.warnings.extend(warnings)
        return refused

    page_count = max(1, len(result.pages))
    per_page = len(result.text) / page_count
    if per_page < MIN_CHARS_PER_PAGE:
        # A sparse text layer is a scan with a stray header: too thin to grade, and thin
        # enough that OCR is the better reading of the same file.
        sparse = PdfText(
            method="unavailable",
            text=result.text,
            pages=result.pages,
            error=(
                "text layer yielded only %.1f characters per page over %d pages "
                "(below the %d threshold); the file is probably a scan"
                % (per_page, page_count, MIN_CHARS_PER_PAGE)
            ),
            warnings=warnings + ["extraction below the per-page threshold"],
            no_text_layer=True,
            gap_kind=GAP_NO_TEXT_LAYER,
            gap_worklist=WORKLIST_NO_TEXT_LAYER,
        )
        return transcribe([], sparse)
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
