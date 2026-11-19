"""
Local OCR engines: read a page picture on this machine, for free, and say how sure they are.

Every engine turns a page image into words with boxes and a confidence, and `build_reading` turns those into lines (a wide
gap inside a line becomes " | ", so table rows survive) plus a page-level quality summary. The pipeline uses that summary to
decide whether the local reading is good enough or the page should be read by a vision model (see ladder.py).

Engines
    tesseract  classic OCR; needs the `tesseract` program (the Docker image has it)
    rapidocr   PaddleOCR models on ONNX: light, fast on CPU, good on printed scans.  pip install rapidocr-onnxruntime
    paddleocr  PaddleOCR itself.                                                      pip install paddleocr
    doctr      docTR (PyTorch): strong on printed pages and tables.                    pip install python-doctr[torch]

Only installed engines are offered. Nothing here sends anything off the machine.
"""
import asyncio
import importlib.util
import io
import logging
import os
import re
import statistics
import subprocess
import tempfile
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.services.reading import ocr, tess

logger = logging.getLogger("app.engines.local")

LOW_WORD = 0.60        # a word read with less confidence than this is doubtful
LOW_DIGIT = 0.70       # numbers are held to a stricter standard: one wrong digit is a wrong value
GAP_FACTOR = 1.5       # a gap wider than this many text heights starts a new cell in the row
MAX_LOW_WORDS = 0.25   # more than this share of doubtful words: the page is not read well enough
MAX_LOW_DIGITS = 0.20
BLANK_INK = 0.003      # a page with less dark ink than this is blank
MIN_AGREEMENT = 0.75   # two local engines must share this much of the page's words (clean pages score 0.80-0.90, handwriting under 0.35)


@dataclass
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    conf: Optional[float] = None    # 0..1, None when the engine does not say


@dataclass
class Reading:
    engine: str
    lines: List[str]
    line_conf: List[Optional[float]]
    words: int = 0
    confidence: Optional[float] = None
    low_share: float = 0.0
    digit_low_share: float = 0.0
    seconds: float = 0.0
    agreement: Optional[float] = None     # share of words another local engine also read (see cross_check)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


_ALNUM = re.compile(r"[A-Za-z0-9]")
_DIGIT = re.compile(r"\d")


def build_reading(words: List[Word], engine: str, seconds: float = 0.0) -> Reading:
    """Group words into rows (by vertical position), join each row left to right, and summarise confidence."""
    words = [w for w in words if w.text and w.text.strip()]
    if not words:
        return Reading(engine, [], [], 0, None, 0.0, 0.0, seconds)
    heights = [max(w.y1 - w.y0, 1.0) for w in words]
    typical = statistics.median(heights)
    ordered = sorted(words, key=lambda w: ((w.y0 + w.y1) / 2, w.x0))
    rows: List[List[Word]] = []
    for w in ordered:
        mid = (w.y0 + w.y1) / 2
        if rows and abs(mid - statistics.fmean((x.y0 + x.y1) / 2 for x in rows[-1])) <= typical * 0.6:
            rows[-1].append(w)
        else:
            rows.append([w])
    lines: List[str] = []
    line_conf: List[Optional[float]] = []
    for row in rows:
        row.sort(key=lambda w: w.x0)
        text = row[0].text.strip()
        for prev, w in zip(row, row[1:]):
            gap = w.x0 - prev.x1
            h = max(prev.y1 - prev.y0, typical, 1.0)
            text += (" | " if gap > h * GAP_FACTOR else " ") + w.text.strip()
        lines.append(text)
        confs = [w.conf for w in row if w.conf is not None and _ALNUM.search(w.text)]
        line_conf.append(statistics.fmean(confs) if confs else None)
    real = [w for w in words if _ALNUM.search(w.text) and w.conf is not None]
    digits = [w for w in real if _DIGIT.search(w.text)]
    return Reading(
        engine=engine, lines=lines, line_conf=line_conf, words=len([w for w in words if _ALNUM.search(w.text)]),
        confidence=statistics.fmean(w.conf for w in real) if real else None,
        low_share=(sum(1 for w in real if w.conf < LOW_WORD) / len(real)) if real else 0.0,
        digit_low_share=(sum(1 for w in digits if w.conf < LOW_DIGIT) / len(digits)) if digits else 0.0,
        seconds=seconds)


# ---------------------------------------------------------------------------------------------------------------------
# Is the local reading good enough?
# ---------------------------------------------------------------------------------------------------------------------

def ink_ratio(jpeg: bytes) -> float:
    """Share of dark pixels on the page: a blank page has almost none."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(jpeg)).convert("L")
        img.thumbnail((400, 400))
        hist = img.histogram()
        return sum(hist[:140]) / max(sum(hist), 1)
    except Exception:
        return 1.0     # cannot tell: treat the page as having content, so it is not silently skipped


_TOKEN = re.compile(r"[a-z0-9]+(?:[.,/\-][a-z0-9]+)*")


def tokens(text: str) -> List[str]:
    """The words and numbers of a text, for comparing two readings of the same page."""
    return [t for t in _TOKEN.findall((text or "").lower()) if len(t) > 1 or t.isdigit()]


def agreement(a: str, b: str) -> float:
    """How much of two readings is the same (Dice overlap of their words, order ignored)."""
    ca, cb = Counter(tokens(a)), Counter(tokens(b))
    na, nb = sum(ca.values()), sum(cb.values())
    return 2 * sum((ca & cb).values()) / (na + nb) if na and nb else 0.0


def cross_check(primary: Reading, other: Reading) -> Reading:
    """Judge `primary` by how well a second, independent engine agrees with it. Some engines (RapidOCR, PaddleOCR, docTR) report
    confidences that look the same on clean print and on handwriting, so their own number cannot decide anything; two
    different engines agreeing on a page is evidence, and disagreeing on a line marks exactly that line as doubtful."""
    theirs = Counter(tokens(other.text))
    conf: List[Optional[float]] = []
    for line in primary.lines:
        ts = tokens(line)
        conf.append(sum(1 for t in ts if theirs[t] > 0) / len(ts) if ts else None)
    primary.line_conf = conf
    primary.agreement = agreement(primary.text, other.text)
    return primary


@dataclass
class Verdict:
    ok: bool
    reasons: List[str] = field(default_factory=list)


def assess(reading: Reading, threshold: float, jpeg: Optional[bytes] = None) -> Verdict:
    """Decide whether this reading can stand without a vision model. Every reason is plain language for the review screen."""
    if reading.words == 0:
        if jpeg is not None and ink_ratio(jpeg) < BLANK_INK:
            return Verdict(True)                                   # a blank page has nothing to read
        return Verdict(False, ["the page has marks but no text was recognised (handwriting, a photo or a poor scan)"])
    reasons: List[str] = []
    if reading.confidence is not None and reading.confidence < threshold:
        reasons.append(f"OCR confidence {reading.confidence:.0%} is below the {threshold:.0%} needed")
    if reading.low_share > MAX_LOW_WORDS:
        reasons.append(f"{reading.low_share:.0%} of the words were hard to read")
    if reading.digit_low_share > MAX_LOW_DIGITS:
        reasons.append(f"{reading.digit_low_share:.0%} of the numbers were hard to read")
    if ocr.text_is_garbled(reading.text):
        reasons.append("the recognised text is garbled")
    return Verdict(not reasons, reasons)


def assess_cross(reading: Reading, jpeg: Optional[bytes] = None) -> Verdict:
    """The verdict for a reading that was cross-checked against a second engine (see cross_check)."""
    if reading.words == 0:
        return assess(reading, 0.0, jpeg)
    reasons: List[str] = []
    if reading.agreement is not None and reading.agreement < MIN_AGREEMENT:
        reasons.append(f"two OCR engines agree on only {reading.agreement:.0%} of the page")
    if ocr.text_is_garbled(reading.text):
        reasons.append("the recognised text is garbled")
    return Verdict(not reasons, reasons)


# ---------------------------------------------------------------------------------------------------------------------
# Engines
# ---------------------------------------------------------------------------------------------------------------------

class Engine:
    calibrated = True     # False: its confidence cannot tell clean print from handwriting, so a second engine must agree
    id = ""
    label = ""
    summary = ""
    install = ""

    def available(self) -> bool:
        raise NotImplementedError

    def _words(self, jpeg: bytes) -> List[Word]:
        raise NotImplementedError

    async def read(self, jpeg: bytes) -> Reading:
        start = time.perf_counter()
        words = await asyncio.to_thread(self._words, jpeg)
        return build_reading(words, self.id, time.perf_counter() - start)

    def info(self) -> Dict[str, Any]:
        ok = self.available()
        return {"id": self.id, "label": self.label, "summary": self.summary, "ready": ok, "cross_checked": not self.calibrated,
                "status": "ready" if ok else "not_installed", "hint": "" if ok else self.install}


def words_from_tsv(tsv: str) -> List[Word]:
    """Tesseract's TSV output: one row per word with its box and a 0..100 confidence."""
    out: List[Word] = []
    for row in tsv.splitlines()[1:]:
        c = row.split("\t", 11)
        if len(c) < 12 or c[0] != "5" or not c[11].strip():
            continue
        try:
            x, y, w, h, conf = float(c[6]), float(c[7]), float(c[8]), float(c[9]), float(c[10])
        except ValueError:
            continue
        out.append(Word(x, y, x + w, y + h, c[11].strip(), conf / 100.0 if conf >= 0 else None))
    return out


class Tesseract(Engine):
    id = "tesseract"
    label = "Tesseract"
    summary = "Classic OCR. Fast and free; good on clean printed pages, weak on handwriting and poor photos."
    install = "Install the tesseract program (apt install tesseract-ocr, or brew install tesseract)."

    def available(self) -> bool:
        return tess.available()

    def _words(self, jpeg: bytes) -> List[Word]:
        exe = tess.binary()
        if not exe:
            raise RuntimeError("Tesseract is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "page.jpg"
            src.write_bytes(jpeg)
            proc = subprocess.run([exe, str(src), "stdout", "-l", tess.LANG, "--dpi", "200", "tsv"], capture_output=True,
                                  timeout=tess.TIMEOUT_SECONDS, env={**os.environ, "OMP_THREAD_LIMIT": "1"})
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or b"").decode(errors="replace")[:300] or "Tesseract failed")
        return words_from_tsv(proc.stdout.decode(errors="replace"))


def _array(jpeg: bytes):
    import numpy as np
    from PIL import Image
    img = Image.open(io.BytesIO(jpeg)).convert("RGB")
    return np.array(img), img.size


def _box_words(items: List[Tuple[Any, str, Optional[float]]]) -> List[Word]:
    """(polygon or rectangle, text, confidence) -> Words. A polygon is a list of (x, y) corners."""
    out: List[Word] = []
    for box, text, conf in items:
        pts = [(float(p[0]), float(p[1])) for p in box] if len(box) and hasattr(box[0], "__len__") else None
        if pts:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        else:
            x0, y0, x1, y1 = (float(v) for v in box)
        if text and text.strip():
            out.append(Word(x0, y0, x1, y1, str(text).strip(), None if conf is None else max(0.0, min(1.0, float(conf)))))
    return out


class _Lazy:
    """Model loading is slow and heavy: do it once, on first use, from one thread at a time."""

    def __init__(self, make: Callable[[], Any]):
        self._make, self._obj, self._lock = make, None, threading.Lock()

    def get(self):
        with self._lock:
            if self._obj is None:
                self._obj = self._make()
            return self._obj


class RapidOCR(Engine):
    calibrated = False
    id = "rapidocr"
    label = "RapidOCR"
    summary = "PaddleOCR models on ONNX. Light and quick on a CPU; a good local step up from Tesseract for printed scans."
    install = "pip install rapidocr-onnxruntime"

    def __init__(self):
        self._model = _Lazy(self._load)

    def available(self) -> bool:
        return importlib.util.find_spec("rapidocr_onnxruntime") is not None or importlib.util.find_spec("rapidocr") is not None

    @staticmethod
    def _load():
        try:
            from rapidocr_onnxruntime import RapidOCR as R
        except ImportError:
            from rapidocr import RapidOCR as R
        return R()

    def _words(self, jpeg: bytes) -> List[Word]:
        arr, _ = _array(jpeg)
        res = self._model.get()(arr)
        items: List[Tuple[Any, str, Optional[float]]] = []
        if isinstance(res, tuple):                                   # rapidocr_onnxruntime: (result, timings)
            for r in (res[0] or []):
                items.append((r[0], r[1], float(r[2])))
        else:                                                        # rapidocr 2+/3: an object with parallel lists
            boxes, txts, scores = getattr(res, "boxes", None), getattr(res, "txts", None), getattr(res, "scores", None)
            if boxes is not None and txts is not None:
                items = [(b, t, float(s) if scores is not None else None) for b, t, s in zip(boxes, txts, scores if scores is not None else [None] * len(txts))]
        return _box_words(items)


class PaddleOCR(Engine):
    calibrated = False
    id = "paddleocr"
    label = "PaddleOCR"
    summary = "Strong open-source OCR with good layout handling. Heavier to install than RapidOCR."
    install = "pip install paddleocr paddlepaddle"

    def __init__(self):
        self._model = _Lazy(self._load)

    def available(self) -> bool:
        return importlib.util.find_spec("paddleocr") is not None

    @staticmethod
    def _load():
        from paddleocr import PaddleOCR as P
        try:                                                         # 3.x
            return P(lang="en", use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False)
        except (TypeError, ValueError):                              # 2.x
            return P(lang="en", use_angle_cls=False, show_log=False)

    def _words(self, jpeg: bytes) -> List[Word]:
        arr, _ = _array(jpeg)
        model = self._model.get()
        items: List[Tuple[Any, str, Optional[float]]] = []
        if hasattr(model, "predict"):                                # 3.x: dict-like results
            for page in model.predict(arr) or []:
                texts, scores = page.get("rec_texts") or [], page.get("rec_scores") or []
                polys = page.get("rec_polys") if page.get("rec_polys") is not None else page.get("rec_boxes")
                for i, t in enumerate(texts):
                    items.append((polys[i].tolist() if hasattr(polys[i], "tolist") else polys[i], t, float(scores[i]) if i < len(scores) else None))
        else:                                                        # 2.x: [[ [box, (text, conf)], ... ]]
            for page in model.ocr(arr, cls=False) or []:
                for box, (t, c) in (page or []):
                    items.append((box, t, float(c)))
        return _box_words(items)


class DocTR(Engine):
    calibrated = False
    id = "doctr"
    label = "docTR"
    summary = "Deep-learning OCR (PyTorch) with strong results on printed pages and tables. Needs more memory."
    install = "pip install 'python-doctr[torch]'"

    def __init__(self):
        self._model = _Lazy(self._load)

    def available(self) -> bool:
        return importlib.util.find_spec("doctr") is not None

    @staticmethod
    def _load():
        from doctr.models import ocr_predictor
        return ocr_predictor(pretrained=True)

    def _words(self, jpeg: bytes) -> List[Word]:
        from doctr.io import DocumentFile
        _, (w, h) = _array(jpeg)
        result = self._model.get()(DocumentFile.from_images([jpeg]))
        out: List[Word] = []
        for page in result.pages:
            for block in page.blocks:
                for line in block.lines:
                    for word in line.words:
                        (x0, y0), (x1, y1) = word.geometry
                        out.append(Word(x0 * w, y0 * h, x1 * w, y1 * h, word.value, float(word.confidence)))
        return out


_ENGINES: Dict[str, Engine] = {e.id: e for e in (Tesseract(), RapidOCR(), PaddleOCR(), DocTR())}


def engines() -> List[Engine]:
    return list(_ENGINES.values())


def get(engine_id: Optional[str]) -> Optional[Engine]:
    return _ENGINES.get(engine_id or "")


def ready() -> List[Engine]:
    return [e for e in _ENGINES.values() if e.available()]


def listing() -> List[Dict[str, Any]]:
    return [e.info() for e in _ENGINES.values()]
