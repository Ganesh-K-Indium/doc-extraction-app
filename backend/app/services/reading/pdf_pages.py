"""
PyMuPDF layer: open a PDF and turn each page into a plain dict (size, embedded text, words/blocks with bboxes, tables,
scan detection) plus a JPEG render for the vision readers.

PyMuPDF (MuPDF) is not thread-safe; every use goes through FITZ_LOCK.
"""
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

import pymupdf as fitz

from app.services.reading import ocr

FITZ_LOCK = threading.RLock()

# Fax machines stamp every page twice: a header ("From <name> <number>  <date>  Page 1 of 9") and a footer
# ("PAGE 1/9 * RCVD AT ... * DURATION ..."). They are transmission metadata, not content.
# Spaces are optional throughout: some OCR engines drop them ("WedNov1109:21:382026MSTPage3of9").
_FAX_HEADER_RE = re.compile(r"^\s*From\b.*Page\s*(\d+)\s*of\s*(\d+)\s*$", re.I)
_FAX_FOOTER_RE = re.compile(r"^\s*PAGE\s*(\d+)\s*/\s*(\d+)\s*\*\s*RCVD\s*AT", re.I)
_FOOTER_FIELDS = {
    "received_at": re.compile(r"RCVD AT\s+(.+?)\s*\*\s*SVR", re.I),
    "server": re.compile(r"SVR:\s*(\S+)", re.I),
    "dnis": re.compile(r"DNIS:\s*(\S+)", re.I),
    "csid": re.compile(r"CSID:\s*(\S+)", re.I),
    "ani": re.compile(r"ANI:\s*(\S+)", re.I),
    "duration": re.compile(r"DURATION[^:]*:\s*(\S+)", re.I),
}


def round_rect(r) -> List[float]:
    return [round(float(v), 2) for v in r]


def strip_fax_stamp(lines: List[str]) -> Tuple[List[str], Dict[str, Any]]:
    """Split transmission stamps off a page's lines -> (content lines, page_meta)."""
    content, meta = [], {}
    for line in lines:
        m = _FAX_HEADER_RE.match(line)
        if m:
            meta["fax_header"] = line.strip()
            meta["fax_page"], meta["fax_pages"] = int(m.group(1)), int(m.group(2))
            continue
        m = _FAX_FOOTER_RE.match(line)
        if m:
            meta["fax_footer"] = line.strip()
            meta["fax_page"], meta["fax_pages"] = int(m.group(1)), int(m.group(2))
            for k, rx in _FOOTER_FIELDS.items():
                f = rx.search(line)
                if f:
                    meta[k] = f.group(1).strip()
            continue
        content.append(line)
    return content, meta


def open_pdf(path: str) -> fitz.Document:
    try:
        pdf = fitz.open(path)
    except Exception as e:
        raise ocr.OcrError("That PDF could not be read.", 422) from e
    if pdf.needs_pass:
        pdf.close()
        raise ocr.OcrError("Password-protected PDFs are not supported.", 422)
    return pdf


def page_count(path: str) -> int:
    with FITZ_LOCK, open_pdf(path) as pdf:
        return pdf.page_count


def _tables(page, page_num: int) -> List[Dict[str, Any]]:
    """Tables on a page. The word-position / ruling-line extractor (ported from the SEC pipeline) runs first because it
    keeps column alignment; PyMuPDF's generic find_tables() is the fallback for text-only tables it rejects."""
    out: List[Dict[str, Any]] = []
    try:
        from app.services.reading.table_extractor import extract_page_tables_with_bbox
        for t, bb in extract_page_tables_with_bbox(page, page_num):
            out.append({"bbox": round_rect(bb), "headers": t["headers"], "rows": t["rows"], "method": "layout"})
    except Exception:
        out = []
    if out:
        return out
    try:
        for t in page.find_tables().tables:
            rows = [[(c or "").strip() for c in r] for r in t.extract()]
            if rows and any(any(c for c in r) for r in rows):
                out.append({"bbox": round_rect(t.bbox), "headers": rows[0], "rows": rows[1:], "method": "grid"})
    except Exception:
        pass
    return out


def scanned_pages(path: str) -> "set[int]":
    """Pages with no usable embedded text, which need a Tesseract layer (picture-covered or almost no text)."""
    out = set()
    with FITZ_LOCK, open_pdf(path) as pdf:
        for i, page in enumerate(pdf, 1):
            if ocr._is_scanned_page(page) or len(page.get_text().strip()) < ocr.MIN_TEXT_LAYER_CHARS:
                out.add(i)
    return out


def analyze_page(path: str, page_num: int) -> Dict[str, Any]:
    """Embedded-text view of one page. `scanned` means a picture covers most of the page, so any text layer is a
    scanner's OCR and should not be trusted as the page text (it is still used to place bounding boxes)."""
    with FITZ_LOCK, open_pdf(path) as pdf:
        page = pdf[page_num - 1]
        words = [{"text": w[4], "bbox": round_rect(w[:4]), "block": w[5], "line": w[6]}
                 for w in page.get_text("words") if w[4].strip()]
        blocks = [{"id": f"b{b[5]}", "bbox": round_rect(b[:4]), "text": b[4].strip()}
                  for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
        tables = _tables(page, page_num)
        widgets = []
        try:  # fillable-form fields: a digitally filled form has its values here, exact
            for w in page.widgets() or []:
                if w.field_value not in (None, "", "Off"):
                    widgets.append({"name": w.field_name, "type": w.field_type_string, "value": str(w.field_value),
                                    "bbox": round_rect(w.rect)})
        except Exception:
            widgets = []
        return {
            "widgets": widgets,
            "size": {"width": round(page.rect.width, 2), "height": round(page.rect.height, 2)},
            "text": page.get_text().strip(),
            "words": words,
            "blocks": blocks,
            "tables": tables,
            "scanned": ocr._is_scanned_page(page),
        }


def build_work_pdf(src: str, dst: str, scanned: "set[int]", tsv_out: "Optional[dict[int, str]]" = None) -> "dict[int, str]":
    """Copy `src` to `dst`, replacing each page in `scanned` with a Tesseract-searchable version.
    Returns {page: 'ok' | error text} for the scanned pages; a failed page is copied through untouched.
    `tsv_out`, when given, receives each scanned page's Tesseract word table, so the page need not be OCR'd twice."""
    from app.services.reading import tess
    status: "dict[int, str]" = {}
    with FITZ_LOCK, open_pdf(src) as pdf, fitz.open() as out:
        for n in range(1, pdf.page_count + 1):
            if n in scanned and tess.available():
                try:
                    one, tsv = tess.searchable_page_with_words(pdf[n - 1])
                    if tsv_out is not None:
                        tsv_out[n] = tsv
                    out.insert_pdf(one)
                    one.close()
                    status[n] = "ok"
                    continue
                except Exception as e:  # keep the page; it just has no text layer
                    status[n] = f"tesseract failed: {e}"
            out.insert_pdf(pdf, from_page=n - 1, to_page=n - 1)
        out.save(dst)
    return status


def render_jpeg(path: str, page_num: int) -> bytes:
    with FITZ_LOCK, open_pdf(path) as pdf:
        png = pdf[page_num - 1].get_pixmap(dpi=ocr.RENDER_DPI).tobytes("png")
    return ocr.normalize_image(png)


def search_rects(path: str, page_num: int, needle: str) -> List[List[float]]:
    with FITZ_LOCK, open_pdf(path) as pdf:
        return [round_rect(r) for r in pdf[page_num - 1].search_for(needle)]


def layout_text(path: str, page_num: int) -> str:
    """A digital page's text with its rows kept: words on one line are joined, and a wide gap becomes " | ", so a table row
    reads "Revenue | 70,066 | 61,858" instead of one cell per line. This is what a text-only model reads."""
    with FITZ_LOCK, open_pdf(path) as pdf:
        words = pdf[page_num - 1].get_text("words")
    words = sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    rows: List[List[tuple]] = []
    for w in words:
        mid = (w[1] + w[3]) / 2
        if rows and abs(mid - sum((x[1] + x[3]) / 2 for x in rows[-1]) / len(rows[-1])) <= 3.0:
            rows[-1].append(w)
        else:
            rows.append([w])
    out = []
    for row in rows:
        row.sort(key=lambda w: w[0])
        line = row[0][4]
        for prev, w in zip(row, row[1:]):
            height = max(prev[3] - prev[1], 6.0)
            glue = prev[4] in ("$", "(", "($", "-$") or w[4] in (")", "%", "%)")   # a sign or bracket printed in its own cell
            line += (" " if glue and w[0] - prev[2] > height * 1.2 else " | " if w[0] - prev[2] > height * 1.2 else " ") + w[4]
        out.append(line.strip())
    return "\n".join(l for l in out if l)
