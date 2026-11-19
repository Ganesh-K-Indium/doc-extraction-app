"""
The structure of a page, from its layout alone: no template and no model.

Input is the page as rows of cells, each cell a piece of text with its position (see Reading.line_cells). Output is
blocks in reading order: headings, paragraphs, label/value groups, tables and lists, each with where it sits on the
page, plus the dates, amounts, phone numbers and so on found in them.

It is rule-based on purpose. Layout rules are explainable to a reviewer, cost nothing, and work offline. They are good
on printed documents with a clear layout (reports, statements, letters, forms). They are weak on handwriting and on
text set in several columns; a page that has no layout (read by a vision model) is built from its lines only and says so.
"""
import re
import statistics
from typing import Any, Dict, List, Optional, Tuple

Cell = Tuple[str, float, float, float, float]       # text, x0, y0, x1, y1 as fractions of the page

COLUMN_TOL = 0.02          # cells whose left edges are this close (page width) share a column
MAX_COLUMNS = 8
MAX_CELL_CHARS = 48        # cells longer than this are running text, not table cells
BIG_HEADING = 1.25         # a line this much taller than the page's usual text is a heading
PARAGRAPH_GAP = 1.0        # a gap above this many line heights starts a new paragraph

_LABEL = re.compile(r"^\s*([A-Z#][^:|]{0,48}?)\s*:\s*(.*)$")
_LIST = re.compile(r"^\s*([•●▪◦*\-]|\d{1,2}[.)]|[A-Za-z][.)])\s+(\S.*)$")
_SENTENCE_END = re.compile(r"[.!?]\s*$")

_ENTITIES: List[Tuple[str, "re.Pattern[str]"]] = [
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("url", re.compile(r"\bhttps?://\S+|\bwww\.\S+", re.I)),
    ("date", re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.? \d{1,2},? \d{4}\b|\b\d{4}-\d{2}-\d{2}\b", re.I)),
    ("amount", re.compile(r"[$€£]\s?\d[\d,]*(?:\.\d{1,2})?|\b\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?\b")),
    ("percent", re.compile(r"\b\d+(?:\.\d+)?\s?%")),
    ("phone", re.compile(r"(?<!\d)\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}(?!\d)")),
]


def _box(cells: List[Cell]) -> List[float]:
    return [round(min(c[1] for c in cells), 4), round(min(c[2] for c in cells), 4), round(max(c[3] for c in cells), 4), round(max(c[4] for c in cells), 4)]


class _Row:
    def __init__(self, cells: List[Cell]):
        self.cells = cells
        self.text = " | ".join(c[0] for c in cells)
        self.x0 = min(c[1] for c in cells)
        self.y0 = min(c[2] for c in cells)
        self.y1 = max(c[4] for c in cells)
        self.h = statistics.median([max(c[4] - c[2], 1e-6) for c in cells])
        self.kind = "text"            # text | heading | list | kv | multi | given
        self.level = 0
        self.table: Optional[Dict[str, Any]] = None

    @property
    def box(self) -> List[float]:
        return _box(self.cells)


def _label_value(text: str) -> Optional[Tuple[str, str]]:
    m = _LABEL.match(text)
    if not m:
        return None
    label, value = m.group(1).strip(" *"), m.group(2).strip()
    if len(label.split()) > 7 or value.startswith("//") or not re.search(r"[A-Za-z]", label):
        return None
    return label, value


def _pairs(cells: List[Cell]) -> List[Dict[str, Any]]:
    """Label/value pairs of one row. A label with nothing after it takes the next cell as its value."""
    out: List[Dict[str, Any]] = []
    i = 0
    while i < len(cells):
        lv = _label_value(cells[i][0])
        if lv is None:
            return []
        label, value = lv
        box = [cells[i][1], cells[i][2], cells[i][3], cells[i][4]]
        if not value and i + 1 < len(cells) and _label_value(cells[i + 1][0]) is None:
            value = cells[i + 1][0].strip()
            box = [box[0], min(box[1], cells[i + 1][2]), cells[i + 1][3], max(box[3], cells[i + 1][4])]
            i += 1
        out.append({"label": label, "value": value or None, "bbox": [round(v, 4) for v in box]})
        i += 1
    return out


def _classify(rows: List[_Row], median_h: float) -> None:
    for r in rows:
        if r.kind == "given":
            continue
        if len(r.cells) >= 2:
            r.kind = "kv" if _pairs(r.cells) else "multi"
            continue
        text = r.text.strip()
        if _pairs(r.cells):
            r.kind = "kv"
        elif _LIST.match(text):
            r.kind = "list"
        else:
            words = text.split()
            letters = re.sub(r"[^A-Za-z]", "", text)
            big = r.h >= median_h * BIG_HEADING
            shouty = len(letters) >= 3 and letters.isupper() and len(words) <= 10 and not _SENTENCE_END.search(text)
            if (big or shouty) and len(text) <= 100 and not _SENTENCE_END.search(text):
                r.kind = "heading"
                r.level = 1 if r.h >= median_h * 1.8 else 2 if r.h >= median_h * 1.4 else 3


def _columns(rows: List[_Row]) -> Optional[List[float]]:
    """Left edges shared by the cells of these rows, or None when they do not line up like a table."""
    xs = sorted(c[1] for r in rows for c in r.cells)
    anchors: List[List[float]] = []
    for x in xs:
        if anchors and x - statistics.fmean(anchors[-1]) <= COLUMN_TOL:
            anchors[-1].append(x)
        else:
            anchors.append([x])
    if len(anchors) > MAX_COLUMNS or len(anchors) < 2:
        return None
    if any(len(a) < 2 for a in anchors):
        return None                                   # a column that only one row has is not a column
    cells = [c for r in rows for c in r.cells]
    if statistics.fmean(len(c[0]) for c in cells) > MAX_CELL_CHARS:
        return None                                   # long cells are running text set in columns
    return [statistics.fmean(a) for a in anchors]


def _table(rows: List[_Row], anchors: List[float]) -> Dict[str, Any]:
    def col(x: float) -> int:
        return min(range(len(anchors)), key=lambda i: abs(anchors[i] - x))

    grid: List[List[str]] = []
    for r in rows:
        line = [""] * len(anchors)
        for c in r.cells:
            i = col(c[1])
            line[i] = (line[i] + " " + c[0]).strip()
        grid.append(line)
    has_digit = [any(re.search(r"\d", v) for v in line) for line in grid]
    header = bool(grid) and not has_digit[0] and any(has_digit[1:]) and all(grid[0])
    columns = [v or f"Column {i + 1}" for i, v in enumerate(grid[0])] if header else [f"Column {i + 1}" for i in range(len(anchors))]
    body = grid[1:] if header else grid
    return {"type": "table", "columns": columns, "header": header, "rows": body, "bbox": _box([c for r in rows for c in r.cells])}


def _entities(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    for i, b in enumerate(blocks):
        if b["type"] == "table":
            texts = [v for row in b["rows"] for v in row]
        elif b["type"] == "key_value":
            texts = [it["value"] for it in b["items"] if it.get("value")]
        elif b["type"] == "list":
            texts = b["items"]
        else:
            texts = [b.get("text", "")]
        seen = set()
        for t in texts:
            for kind, rx in _ENTITIES:
                for m in rx.finditer(t or ""):
                    key = (kind, m.group(0))
                    if key not in seen:
                        seen.add(key)
                        found.append({"type": kind, "value": m.group(0).strip(), "block": i})
    return found


def _given_table(t: Dict[str, Any]) -> Dict[str, Any]:
    """A table another extractor found (digital pages), in the shape of a table block."""
    cols = [re.sub(r"^Col (\d+)$", r"Column \1", str(h)) if str(h).strip() else f"Column {i + 1}" for i, h in enumerate(t.get("columns") or [])]
    rows = [[str(v) for v in r] for r in t.get("rows", []) if any(str(v).strip() for v in r)]
    return {"type": "table", "columns": cols, "header": bool(cols), "rows": rows, "bbox": [round(v, 4) for v in t["bbox"]], "method": t.get("method", "given")}


def build_page(rows_in: List[List[Cell]], has_layout: bool = True, tables: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """{"blocks": [...], "entities": [...], "layout": bool} for one page given its rows of cells.
    Fax transmission stamps are not content and are left out. `tables` are tables another extractor already found
    (bbox as page fractions, columns, rows): the rows they cover are not rebuilt, the table takes their place."""
    from app.services.reading import pdf_pages
    rows = [_Row(r) for r in rows_in if r and any(c[0].strip() for c in r) and not pdf_pages.is_fax_stamp(" ".join(c[0] for c in r))]
    for t in tables or []:
        x0, y0, x1, y1 = t["bbox"]
        flat_table = re.sub(r"[^a-z0-9]", "", " ".join(str(v) for row in t.get("rows", []) for v in row).lower())
        # only rows whose own text is in the table: the table's box may also hold a heading above it, which stays a heading
        inside = [r for r in rows if y0 - 0.002 <= (r.y0 + r.y1) / 2 <= y1 + 0.002 and r.x0 >= x0 - 0.02 and r.x0 <= x1
                  and all(re.sub(r"[^a-z0-9]", "", c[0].lower()) in flat_table for c in r.cells)]
        if not inside or not t.get("rows"):
            continue
        top = min(r.y0 for r in inside)                     # the table starts at its first row, not at the edge of its box
        marker = _Row([("", x0, top, x1, top + 0.001)])
        marker.kind, marker.table = "given", _given_table(t)
        rows = [r for r in rows if r not in inside]
        rows.append(marker)
        rows.sort(key=lambda r: r.y0)
    if not rows:
        return {"blocks": [], "entities": [], "layout": has_layout}
    median_h = statistics.median(r.h for r in rows if r.kind != "given") if any(r.kind != "given" for r in rows) else 0.01
    _classify(rows, median_h)

    blocks: List[Dict[str, Any]] = []
    i = 0
    while i < len(rows):
        r = rows[i]
        if r.kind == "given":
            blocks.append(r.table)  # type: ignore[arg-type]
            i += 1
        elif r.kind == "multi":
            j = i
            while j < len(rows) and rows[j].kind == "multi":
                j += 1
            group, anchors = rows[i:j], None
            if len(group) >= 2:
                anchors = _columns(group)
            if anchors:
                blocks.append(_table(group, anchors))
            else:                                       # side-by-side text that is not a table: keep it as lines
                for g in group:
                    blocks.append({"type": "paragraph", "text": " ".join(c[0] for c in g.cells), "bbox": g.box})
            i = j
        elif r.kind == "kv":
            items: List[Dict[str, Any]] = []
            j, prev = i, None
            while j < len(rows) and rows[j].kind == "kv" and (prev is None or rows[j].y0 - prev.y1 <= rows[j].h * 2.5):
                items += _pairs(rows[j].cells)
                prev = rows[j]
                j += 1
            # a long value wraps onto the lines under it: those lines belong to the last label, not to a paragraph of their own
            while has_layout and prev is not None and j < len(rows) and rows[j].kind == "text" and items and items[-1].get("value") \
                    and rows[j].y0 - prev.y1 <= rows[j].h * PARAGRAPH_GAP and rows[j].x0 >= prev.x0 - 0.02:
                items[-1]["value"] = (items[-1]["value"] + " " + rows[j].text.strip()).strip()
                items[-1]["bbox"][3] = round(max(items[-1]["bbox"][3], rows[j].y1), 4)
                prev = rows[j]
                j += 1
            blocks.append({"type": "key_value", "items": items, "bbox": _box([c for g in rows[i:j] for c in g.cells])})
            i = j
        elif r.kind == "heading":
            blocks.append({"type": "heading", "level": r.level, "text": r.text.strip(), "bbox": r.box})
            i += 1
        elif r.kind == "list":
            items, j = [], i
            ordered = not re.match(r"\s*[•●▪◦*\-]", r.text)
            while j < len(rows) and rows[j].kind == "list":
                m = _LIST.match(rows[j].text.strip())
                items.append(m.group(2).strip() if m else rows[j].text.strip())
                j += 1
            blocks.append({"type": "list", "ordered": ordered, "items": items, "bbox": _box([c for g in rows[i:j] for c in g.cells])})
            i = j
        else:
            j, text = i, []
            while j < len(rows) and rows[j].kind == "text":
                if j > i:
                    if has_layout:
                        if rows[j].y0 - rows[j - 1].y1 > rows[j].h * PARAGRAPH_GAP or abs(rows[j].x0 - rows[i].x0) > 0.04:
                            break
                    elif not rows[j].text.strip()[:1].islower() or _SENTENCE_END.search(rows[j - 1].text):
                        break                           # no positions: only an unfinished sentence continues on the next line
                text.append(rows[j].text.strip())
                j += 1
            blocks.append({"type": "paragraph", "text": " ".join(text), "bbox": _box([c for g in rows[i:j] for c in g.cells])})
            i = j
    return {"blocks": blocks, "entities": _entities(blocks), "layout": has_layout}


def build_from_lines(lines: List[str]) -> Dict[str, Any]:
    """A page with no positions (read by a vision model): each line becomes a row, and cells keep their order, so the
    rules that need no geometry still work (label/value, headings in capitals, lists, tables of equal-width rows).
    Bounding boxes are dropped, because the ones made up here mean nothing."""
    rows: List[List[Cell]] = []
    for n, line in enumerate(l for l in lines if l.strip()):
        parts = line.split(" | ")
        rows.append([(p, 0.1 + 0.2 * k, n * 0.02, 0.1 + 0.2 * k + 0.15, n * 0.02 + 0.01) for k, p in enumerate(parts)])
    page = build_page(rows, has_layout=False)
    for b in page["blocks"]:
        b.pop("bbox", None)
        for it in b.get("items", []) if b["type"] == "key_value" else []:
            it.pop("bbox", None)
    return page
