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


def png_to_pdf(png: bytes) -> bytes:
    """One page of picture + invisible text. Raises RuntimeError with Tesseract's own message on failure."""
    exe = binary()
    if not exe:
        raise RuntimeError("Tesseract is not installed")
    with tempfile.TemporaryDirectory() as tmp:
        src, base = Path(tmp) / "in.png", Path(tmp) / "out"
        src.write_bytes(png)
        env = {**os.environ, "OMP_THREAD_LIMIT": "1"}  # pages run in parallel; one thread each avoids oversubscription
        proc = subprocess.run([exe, str(src), str(base), "-l", LANG, "--dpi", str(DPI), "pdf"],
                              capture_output=True, timeout=TIMEOUT_SECONDS, env=env)
        out = base.with_suffix(".pdf")
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError((proc.stderr or b"").decode(errors="replace")[:300] or "Tesseract failed")
        return out.read_bytes()


def render_png(page: "fitz.Page") -> bytes:
    return page.get_pixmap(dpi=DPI).tobytes("png")


def searchable_page(page: "fitz.Page") -> "fitz.Document":
    """A one-page document: `page`'s picture with Tesseract's text laid over it, at `page`'s size."""
    ocr = fitz.open("pdf", png_to_pdf(render_png(page)))
    out = fitz.open()
    new = out.new_page(width=page.rect.width, height=page.rect.height)
    new.show_pdf_page(new.rect, ocr, 0)
    ocr.close()
    return out
