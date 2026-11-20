"""
Tesseract text layer for scanned pages.

A fax is a picture, so PyMuPDF sees no words and nothing downstream (highlighting, label search, checkbox pixels,
table rebuild) has anything to work with. Tesseract turns each scanned page into a one-page PDF whose invisible text
sits exactly over the picture; we lay that onto the original page geometry and call the result the "work PDF".
Every geometric step then runs on the work PDF; the viewer keeps showing the original, and the coordinates match
because the page size is carried over.

Tesseract is also usable as a reader on its own (route `ocr_local`) when no model is configured, which keeps
patient documents off third-party services if that is required.
"""
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import pymupdf as fitz

logger = logging.getLogger("app.services.tess")

DPI = 300
TIMEOUT_SECONDS = 90
LANG = os.getenv("TESSERACT_LANG", "eng")


def binary() -> Optional[str]:
    return os.getenv("TESSERACT_CMD") or shutil.which("tesseract")


def available() -> bool:
    return binary() is not None


FEW_WORDS = 40          # a page with fewer recognised words than this, yet with ink on it, is read again on a cleaned image


def word_count(tsv: str) -> int:
    n = 0
    for line in tsv.splitlines()[1:]:
        f = line.split("\t")
        if len(f) > 11 and f[11].strip():
            try:
                if float(f[10]) > 0:
                    n += 1
            except ValueError:
                pass
    return n


def flatten(png: bytes) -> "tuple[bytes, float]":
    """The page with its lighting evened out (a phone photo is darker on one side, or has a shadow), and the share of it
    that is ink. Each pixel is compared with the paper around it, so uneven light stops hiding the text."""
    from io import BytesIO
    from PIL import Image, ImageChops, ImageFilter, ImageOps
    im = Image.open(BytesIO(png)).convert("L")
    small = im.resize((max(1, im.width // 4), max(1, im.height // 4)))
    paper = small.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(max(4, small.width // 40))).resize(im.size)
    dark = ImageChops.subtract(paper, im)                    # how much darker than the paper nearby
    ink = sum(dark.histogram()[40:]) / float(im.width * im.height)
    out = ImageOps.autocontrast(ImageOps.invert(dark), cutoff=2)
    buf = BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue(), ink


def _run(png: bytes) -> "tuple[bytes, str]":
    """One page of picture + invisible text, and Tesseract's word table (TSV) from the same run."""
    exe = binary()
    if not exe:
        raise RuntimeError("Tesseract is not installed")
    with tempfile.TemporaryDirectory() as tmp:
        src, base = Path(tmp) / "in.png", Path(tmp) / "out"
        src.write_bytes(png)
        env = {**os.environ, "OMP_THREAD_LIMIT": "1"}  # pages run in parallel; one thread each avoids oversubscription
        proc = subprocess.run([exe, str(src), str(base), "-l", LANG, "--dpi", str(DPI), "pdf", "tsv"],
                              capture_output=True, timeout=TIMEOUT_SECONDS, env=env)
        out, words = base.with_suffix(".pdf"), base.with_suffix(".tsv")
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError((proc.stderr or b"").decode(errors="replace")[:300] or "Tesseract failed")
        return out.read_bytes(), (words.read_text(errors="replace") if words.exists() else "")


def png_to_pdf_and_words(png: bytes) -> "tuple[bytes, str]":
    """One page of picture + invisible text, and Tesseract's word table (TSV) from the same run, so reading the page
    for its text costs no second pass. A page that comes back nearly empty although it has ink on it (a photo with uneven
    light, a shadow) is read once more on a cleaned copy, and the better reading is kept. Raises RuntimeError with
    Tesseract's own message on failure."""
    pdf, tsv = _run(png)
    if word_count(tsv) >= FEW_WORDS:
        return pdf, tsv
    try:
        clean, ink = flatten(png)
        if ink < 0.004:                                      # a blank page: nothing to find
            return pdf, tsv
        pdf2, tsv2 = _run(clean)
        if word_count(tsv2) > word_count(tsv):
            return pdf2, tsv2
    except Exception as e:                                   # the first reading stands
        logger.warning("Cleaned-image retry failed: %s", e)
    return pdf, tsv


def png_to_pdf(png: bytes) -> bytes:
    return png_to_pdf_and_words(png)[0]


def render_png(page: "fitz.Page") -> bytes:
    return page.get_pixmap(dpi=DPI).tobytes("png")


def searchable_page_with_words(page: "fitz.Page") -> "tuple[fitz.Document, str]":
    """A one-page document: `page`'s picture with Tesseract's text laid over it, at `page`'s size; plus the word table."""
    pdf_bytes, tsv = png_to_pdf_and_words(render_png(page))
    ocr = fitz.open("pdf", pdf_bytes)
    out = fitz.open()
    new = out.new_page(width=page.rect.width, height=page.rect.height)
    new.show_pdf_page(new.rect, ocr, 0)
    ocr.close()
    return out, tsv


def searchable_page(page: "fitz.Page") -> "fitz.Document":
    return searchable_page_with_words(page)[0]
