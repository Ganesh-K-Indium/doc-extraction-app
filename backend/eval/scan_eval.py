"""
How well are scanned pages read, measured against the same document read from its own text?

A born-digital PDF gives an exact reading (digital path). Here that reading is the answer key: the pages are turned into
images that look scanned, the images go through the pipeline, and what comes out is compared with the key.

    python eval/scan_eval.py <pdf> [--pages 1,2] [--profile clean|scan|fax] [--strategy economy|balanced|accuracy]
                             [--out-dir DIR] [--keep]

Profiles: clean = rasterised only; scan = slight skew, blur, noise, JPEG; fax = 1-bit, low resolution, a transmission stamp.
Economy never calls a model. Balanced and Accuracy do, so use few pages.
"""
import argparse
import asyncio
import io
import json
import os
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pymupdf  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

PROFILES = {"clean": dict(dpi=200), "scan": dict(dpi=170, skew=0.6, blur=0.7, noise=9, jpeg=55), "fax": dict(dpi=150, bw=True, stamp=True)}


def degrade(img: Image.Image, p: dict, seed: int = 7) -> Image.Image:
    rng = np.random.default_rng(seed)
    img = img.convert("L")
    if p.get("skew"):
        img = img.rotate(p["skew"], resample=Image.BICUBIC, expand=False, fillcolor=255)
    if p.get("blur"):
        img = img.filter(ImageFilter.GaussianBlur(p["blur"]))
    if p.get("noise"):
        a = np.asarray(img, dtype=np.float32) + rng.normal(0, p["noise"], (img.height, img.width))
        img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    if p.get("bw"):
        img = img.point(lambda v: 255 if v > 150 else 0).convert("1").convert("L")
    if p.get("stamp"):
        ImageDraw.Draw(img).text((12, 4), "02/11/2025 09:14  FAX  P.1  TO: RECORDS DEPT  FROM: 555-0100", fill=0)
    return img


def scanned_copy(pdf: str, pages, profile: str, out: str) -> None:
    p = PROFILES[profile]
    src, dst = pymupdf.open(pdf), pymupdf.open()
    for n in pages:
        pix = src[n - 1].get_pixmap(dpi=p["dpi"])
        img = degrade(Image.open(io.BytesIO(pix.tobytes("png"))), p)
        buf = io.BytesIO()
        if p.get("jpeg"):
            img.convert("RGB").save(buf, "JPEG", quality=p["jpeg"])
        else:
            img.save(buf, "PNG")
        page = dst.new_page(width=src[n - 1].rect.width, height=src[n - 1].rect.height)
        page.insert_image(page.rect, stream=buf.getvalue())
    dst.save(out)


def subset(pdf: str, pages, out: str) -> None:
    src, dst = pymupdf.open(pdf), pymupdf.open()
    for n in pages:
        dst.insert_pdf(src, from_page=n - 1, to_page=n - 1, widgets=True)       # fillable values must travel with the page
    dst.save(out)


def _alnum(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _vals(rows):
    return [[_alnum(c["value"]) for c in r.values() if c.get("value") not in (None, "")] for r in rows]


def compare(truth: dict, got: dict) -> dict:
    """Fields: how many of the key's non-empty values are found (under the same label, or under any label). Tables: for each of the
    key's tables, the scan table that shares most cells; cell recall in that table, rows read exactly, rows and columns as counted."""
    tf = {k: c for k, c in truth["fields"].items() if c.get("value") not in (None, "", False)}
    gf = got["fields"]
    by_label = {_alnum(c.get("label") or k): c for k, c in gf.items()}
    gvals = Counter(_alnum(c.get("value")) for c in gf.values() if c.get("value") not in (None, ""))
    same_label = any_label = silent = 0
    for k, c in tf.items():
        want = _alnum(c["value"])
        g = by_label.get(_alnum(c.get("label") or k)) or gf.get(k)
        if g is not None and _alnum(g.get("value")) == want:
            same_label += 1
        elif gvals.get(want):
            any_label += 1
        elif g is not None and g.get("value") not in (None, "") and g.get("status") not in ("review", "undetermined"):
            silent += 1                                   # a wrong value, presented as fine
    out = {"fields": len(tf), "field_same_label": same_label, "field_other_label": any_label, "field_silent_wrong": silent,
           "extra_fields": max(0, sum(1 for c in gf.values() if c.get("value") not in (None, "")) - len(tf))}
    tc = tcell = trows = trow_ok = 0
    shape = []
    for tk, rows in truth["tables"].items():
        want = _vals(rows)
        cells = Counter(v for r in want for v in r)
        best, bs = None, 0.0
        for gk, grows in got["tables"].items():
            gc = Counter(v for r in _vals(grows) for v in r)
            ov = sum(min(n, gc[v]) for v, n in cells.items())
            if ov > bs:
                best, bs = gk, ov
        n = sum(cells.values())
        tc += n
        tcell += bs
        gr = _vals(got["tables"][best]) if best else []
        trows += len(want)
        trow_ok += sum(1 for r in want if r in gr)
        gcols = len(next(iter(got["tables"][best][0].values()), {})) if False else (len(got["tables"][best][0]) if best and got["tables"][best] else 0)
        shape.append((len(rows), len(rows[0]) if rows else 0, len(got["tables"][best]) if best else 0, gcols))
    out.update({"tables_key": len(truth["tables"]), "tables_got": len(got["tables"]), "cell_total": tc, "cell_found": int(tcell),
                "rows_total": trows, "rows_exact": trow_ok, "shape(key r,c | got r,c)": shape})
    boxed = [c for c in list(gf.values()) + [c for rows in got["tables"].values() for r in rows for c in r.values()] if c.get("value") not in (None, "", False)]
    out["highlightable"] = f"{sum(1 for c in boxed if c.get('bbox'))}/{len(boxed)}"
    return out


async def run(pdf: str, pages, profile: str, work: str, truth_cache: dict):
    from app.services import pipeline
    sub = os.path.join(work, "orig.pdf")
    subset(pdf, pages, sub)
    if "t" not in truth_cache:                        # the key: the digital path, no model
        res = await pipeline.process(sub, template_choice="discover")
        truth_cache["t"] = res["forms"][0]
    scan = os.path.join(work, f"scan_{profile}.pdf")
    scanned_copy(pdf, pages, profile, scan)
    res = await pipeline.process(scan, template_choice="discover")
    return truth_cache["t"], res["forms"][0] if res["forms"] else {"fields": {}, "tables": {}}, res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--pages", default="1")
    ap.add_argument("--profile", default="scan")
    ap.add_argument("--out-dir")
    a = ap.parse_args()
    pages = [int(x) for x in a.pages.split(",")]
    work = a.out_dir or tempfile.mkdtemp()
    Path(work).mkdir(parents=True, exist_ok=True)
    truth, got, res = asyncio.run(run(a.pdf, pages, a.profile, work, {}))
    r = compare(truth, got)
    r["stats"] = {k: res["stats"].get(k) for k in ("scanned_pages", "local_ocr_pages", "vision_pages", "needs_review", "errors")}
    print(json.dumps(r, indent=1, default=str))
    for f in Path(work).glob("*.work.pdf"):
        f.unlink()


if __name__ == "__main__":
    main()
