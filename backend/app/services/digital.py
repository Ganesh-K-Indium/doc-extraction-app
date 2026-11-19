"""
Digital (born-digital) pages: read them with code, not a model.

A PDF with a real text layer already holds its text and its table cells exactly. Asking a model to read them back costs
tokens and can only add mistakes. So for these pages:

    tables    the layout table extractor's cells, copied verbatim            (free, exact)
    fields    "Label: value" pairs found in the text                         (free, exact)
    headers   a column header that spans several rows is combined by a model (a few lines of text, once per distinct
              header; without a model the raw header cells are joined)

and a model reads the page only when the page is form-like but gave code almost nothing to work with (labels above
values, no ruled structure). Prose pages are left as text: there is no field to extract from a paragraph.

Values copied from the text layer are marked "agreed" with method "text-layer": there is no second opinion to disagree
with, the PDF itself is the source.
"""
import asyncio
import json
import logging
import re
from collections import Counter
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from app import config
from app.services import kv, labels, locate, pdf_pages

logger = logging.getLogger("app.services.digital")

MIN_KV_FOR_STRUCTURE = 3     # fewer "Label: value" pairs than this, and no table, means code found no structure
MIN_LINES_FOR_FORM = 6       # a page with less text than this is a stub, not a form
PROSE_WORDS_PER_LINE = 8     # a line this long is a sentence, not a label
MAX_VALUE_CHARS = 80         # a labelled value is short; "Cybersecurity: Our board oversees..." is a sentence with a lead-in
MAX_PAIR_LINE = 90           # ...and so is a whole line this long


def _is_year(c: str) -> bool:
    return bool(re.fullmatch(r"(19|20)\d\d", c.strip()))


def _is_data(c: str) -> bool:
    """A cell holding an amount (not a year, not a date part): digits with a separator, sign, currency or percent."""
    c = c.strip()
    return bool(c) and bool(re.search(r"\d", c)) and not _is_year(c) and bool(re.fullmatch(r"[\s$(\-.\d,%)—–]+", c))


def split_header(table: Dict[str, Any]) -> Tuple[List[List[str]], List[List[str]]]:
    """(header rows, body rows). The header block is the leading rows that put text over the value columns and hold no
    amounts yet ("Three | Months Ended", "March 31,", "2026 | 2025"). A row that is only a label ("Revenue:") starts the body."""
    rows = [[(c or "").strip() for c in r] for r in table["rows"]]
    n = 0
    for r in rows:
        values = r[1:]
        if any(_is_data(c) for c in values) or not any(values):
            break
        n += 1
    return rows[:n], rows[n:]


def raw_labels(header_rows: List[List[str]], ncols: int) -> List[str]:
    """No model: each column's header cells joined top to bottom. Correct for a one-row header, merely readable otherwise."""
    out = ["Item"]
    for j in range(1, ncols):
        parts = [r[j] for r in header_rows if j < len(r) and r[j]]
        out.append(" ".join(parts) or f"Column {j}")
    return out


Ask = Callable[[str, str], Awaitable[str]]


async def default_ask(model: str, prompt: str) -> str:
    """A short text-only call (no image). Recorded in the usage tracker like every other model call."""
    import time
    from app.services import ocr
    from app.services.usage_tracker import record_usage
    start = time.perf_counter()
    resp = await ocr._get_client().chat.completions.create(
        model=model, temperature=0, response_format={"type": "json_object"}, messages=[{"role": "user", "content": prompt}])
    usage = getattr(resp, "usage", None)
    record_usage(stage="header_labels", model=model, prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                 completion_tokens=getattr(usage, "completion_tokens", 0) or 0, total_tokens=getattr(usage, "total_tokens", 0) or 0,
                 duration_seconds=time.perf_counter() - start)
    return resp.choices[0].message.content
_HEADER_PROMPT = """The first rows of a table from a PDF are shown below, cells separated by " | ". A heading that spans several
columns was split across cells. Write ONE short label per value column, combining the rows that apply to it (for example
"Three Months Ended March 31, 2026"). The first cell of each row is the row-label column: skip it.

Rows:
{rows}

Return JSON only: {{"columns": ["<label for column 1>", "<label for column 2>", ...]}} with exactly {n} labels."""


async def header_labels(header_rows: List[List[str]], ncols: int, model: Optional[str], ask: Optional[Ask], memo: Dict[str, List[str]]) -> List[str]:
    """Column labels for a table. One short model call per distinct header (a filing repeats the same header on every
    statement), none when the header is a single row or no model is available."""
    fallback = raw_labels(header_rows, ncols)
    if len(header_rows) < 2 or not model or ask is None:
        return fallback
    shown = "\n".join(" | ".join(r) for r in header_rows)
    if shown in memo:
        return memo[shown]
    try:
        data = json.loads(await ask(model, _HEADER_PROMPT.format(rows=shown, n=ncols - 1)))
        cols = [str(c).strip() for c in data.get("columns", [])] if isinstance(data, dict) else []
    except Exception as e:
        logger.warning("Header labelling failed, using the raw header cells: %s", e)
        cols = []
    got = (["Item"] + cols) if len(cols) == ncols - 1 and all(cols) else fallback
    memo[shown] = got
    return got


_TITLE_OK = re.compile(r"[A-Za-z]{3}")
_SECTION_MARKER = re.compile(r"^(?:(?:PART|ITEM|NOTE|SECTION|PAGE)\s+[IVX\d]+\.?|TABLE OF CONTENTS)$", re.I)


def table_title(lines: List[str], first_label: str = "") -> Optional[str]:
    """The heading just above a table: the last mostly-capitalised short line before the table's first row label."""
    first_word = first_label.split()[0] if first_label.split() else ""
    stop = next((i for i, l in enumerate(lines) if first_label and l.strip().startswith(first_label[:20])), None)
    if stop is None and len(first_word) >= 4:         # a merged row label ("Assets Current assets:") is several lines in the text
        stop = next((i for i, l in enumerate(lines) if l.strip().split()[:1] == [first_word]), None)
    if stop is None:
        return None                                   # cannot place the table in the text: leave it untitled rather than guess a footer
    for line in reversed(lines[:stop]):
        t = line.strip()
        letters = [c for c in t if c.isalpha()]
        if _SECTION_MARKER.match(t):
            continue                                   # "PART I", "ITEM 2", "Table of Contents": running headers, not a table's name
        if 4 <= len(t) <= 80 and _TITLE_OK.search(t) and letters and sum(c.isupper() for c in letters) / len(letters) >= 0.7:
            return t.title() if t.isupper() else t
    return None



# ---------------------------------------------------------------------------------------------------------------------
# Self-verification. Code is only as good as its table detector, and PDFs are endlessly varied. So every table is checked
# against the page itself: each number printed inside the table's region must appear in the cells that were extracted.
# ---------------------------------------------------------------------------------------------------------------------
COVERAGE_OK = 0.98      # share of the numbers printed in a table's region that must be in its cells
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(tokens: List[str]) -> Counter:
    """Amounts only (signs and currency marks are formatting here): "$15,089" and "(1,234)" count as 15089 and 1234."""
    return Counter(m.replace(",", "") for t in tokens for m in _NUM.findall(t))


_HEADING_WORDS = {"note", "notes", "item", "part", "section", "exhibit", "schedule", "table", "figure", "page", "chapter", "article", "appendix"}
_MARKER = re.compile(r"\(?\d{1,2}\)?\.?")


def _words_in(path: str, page_num: int, bbox: List[float]) -> List[str]:
    """The text tokens printed inside `bbox`, minus footnote and note markers (a 1-2 digit token set noticeably smaller
    than the surrounding text): those are references, not table data, and must not count as numbers a table lost."""
    x0, y0, x1, y1 = bbox
    spans: List[Tuple[str, float]] = []
    with pdf_pages.FITZ_LOCK, pdf_pages.open_pdf(path) as pdf:
        for b in pdf[page_num - 1].get_text("dict")["blocks"]:
            for line in b.get("lines", []):
                for sp in line["spans"]:
                    bx0, by0, bx1, by1 = sp["bbox"]
                    if x0 - 1 <= (bx0 + bx1) / 2 <= x1 + 1 and y0 - 1 <= (by0 + by1) / 2 <= y1 + 1:
                        spans.append((sp["text"], sp["size"]))
    sizes = sorted(sz for _, sz in spans)
    median = sizes[len(sizes) // 2] if sizes else 0.0
    out: List[str] = []
    for text, sz in spans:
        for tok in text.split():
            if sz < 0.8 * median and _MARKER.fullmatch(tok):
                continue
            if out and out[-1].lower().strip(".:") in _HEADING_WORDS and _MARKER.fullmatch(tok):
                continue                                 # "NOTE 7", "ITEM 6.": a heading's number, not table data
            out.append(tok)
    return out


def coverage(path: str, page_num: int, bbox: List[float], rows: List[List[str]]) -> Tuple[float, List[str]]:
    """(share of the page's numbers in `bbox` found in `rows`, the numbers that were not)."""
    page = _numbers(_words_in(path, page_num, bbox))
    if not page:
        return 1.0, []
    got = _numbers([c for r in rows for c in r if c])
    missing = page - got
    lost = sum(missing.values())
    return 1.0 - lost / sum(page.values()), sorted(missing.elements())[:6]


def _raw_rows(t: Dict[str, Any]) -> List[List[str]]:
    rows = [[(c or "").strip() for c in r] for r in t["rows"]]
    return ([[(c or "").strip() for c in t["headers"]]] + rows) if t.get("method") == "grid" else rows


def grid_alternative(path: str, page_num: int, bbox: List[float]) -> Optional[Dict[str, Any]]:
    """PyMuPDF's own ruled-grid finder over the same region: a second, independent way to read the table."""
    try:
        with pdf_pages.FITZ_LOCK, pdf_pages.open_pdf(path) as pdf:
            found = pdf[page_num - 1].find_tables(clip=tuple(bbox)).tables
            rows = [[(c or "").strip() for c in r] for t in found[:1] for r in t.extract()]
    except Exception:
        return None
    return {"rows": rows, "headers": [], "method": "layout", "bbox": bbox} if rows and any(any(r) for r in rows) else None


def verified_table(path: str, page_num: int, t: Dict[str, Any]) -> Tuple[Dict[str, Any], float, List[str]]:
    """The better of the two table readings for this region, with its coverage and what it missed."""
    best, (cov, missing) = t, coverage(path, page_num, t["bbox"], _raw_rows(t))
    if cov < COVERAGE_OK:
        alt = grid_alternative(path, page_num, t["bbox"])
        if alt:
            acov, amissing = coverage(path, page_num, t["bbox"], _raw_rows(alt))
            if acov > cov:
                best, cov, missing = alt, acov, amissing
    return best, cov, missing


_NUM_LINE = re.compile(r"\d[\d,]*(?:\.\d+)?%?")


def looks_tabular(lines: List[str]) -> bool:
    """Several lines that each carry two or more amounts: a table, whether or not the detector found one."""
    rows = sum(1 for l in lines if len(_NUM_LINE.findall(l)) >= 2 and len(re.findall(r"[A-Za-z]{3}", l)) >= 1)
    return rows >= 4


_FORM_LINE = re.compile(r"^(?:SCHEDULE|FORM)\s+[A-Z0-9][\w\-/.]*(?:\s+[A-Z0-9][\w\-/.]*)?$", re.I)


def page_title(lines: List[str]) -> Optional[str]:
    """The document's heading near the top of a page. A line that names a form ("FORM 10-Q", "Form W-9") wins; otherwise the
    longest short, capitalised line without a colon (the first one would often be a letterhead such as "UNITED STATES")."""
    top = [l.strip() for l in lines[:12]]
    for t in top:
        if _FORM_LINE.match(t) and len(t) <= 40:
            return t.upper() if len(t.split()) <= 3 and t.upper() == t else t
    best: Optional[str] = None
    for t in top:
        letters = [c for c in t if c.isalpha()]
        if 3 <= len(t) <= 80 and ":" not in t and letters and sum(c.isupper() for c in letters) / len(letters) >= 0.7:
            if best is None or len(t) > len(best):
                best = t
    return (best.title() if best.isupper() else best) if best else None


def _cell(value: str, page: int) -> Dict[str, Any]:
    return {"value": value or None, "status": "agreed" if value else "empty", "alternatives": [], "method": "text-layer", "bbox": None, "page": page}


async def read_page(path: str, page_num: int, lines: List[str], tables: List[Dict[str, Any]], model: Optional[str] = None,
                    ask: Optional[Ask] = None, memo: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    """Everything code can read from one digital page, in the same shape as discover.discover_page returns."""
    memo = memo if memo is not None else {}
    out_tables: Dict[str, List[Dict[str, Any]]] = {}
    out_cols: Dict[str, List[str]] = {}
    title = None
    unverified: List[str] = []
    for n, t in enumerate(tables, 1):
        t, cov, missing = await asyncio.to_thread(verified_table, path, page_num, t)
        header, body = split_header(t)
        body = [r for r in body if any(r)]
        ncols = max((len(r) for r in body), default=0)
        if not body or ncols < 2:
            continue
        cols = await header_labels(header, ncols, model, ask, memo)
        ttl = table_title(lines, body[0][0] if body[0] else "")
        title = title or ttl
        key = labels.key(ttl or "", f"table_{n}")
        key = key if key not in out_tables else f"{key}_{n}"
        keys: List[str] = []
        for j, c in enumerate(cols):
            k = labels.key(c, f"col_{j + 1}")
            keys.append(k if k not in keys else f"{k}_{j + 1}")
        out_tables[key], out_cols[key] = [], cols
        note = None
        if cov < COVERAGE_OK:                               # neither reading captured every number printed in this region
            note = f"{round((1 - cov) * 100)}% of the numbers in this table were not captured (for example {', '.join(missing[:3])})"
            unverified.append(note)
        for r in body:
            r = r + [""] * (ncols - len(r))
            row = {k: {**_cell(r[j], page_num), "label": cols[j]} for j, k in enumerate(keys)}
            if note:
                for c in row.values():
                    if c["value"]:
                        c.update({"status": "review", "reason": note})
            out_tables[key].append(row)
    fields: Dict[str, Dict[str, Any]] = {}
    for p in kv.parse_kv(lines):
        label, value = p["label"], p["value"]
        if len(value) > MAX_VALUE_CHARS or len(lines[p["line"]]) > MAX_PAIR_LINE or re.search(r"\d", label):
            continue                                   # a sentence, or "Heading: running text": not a labelled value
        key = labels.key(label)
        if key and key not in fields:
            hit = locate.find_with_text(path, page_num, value, label)
            fields[key] = {**_cell(value, page_num), "label": label, "section": None, "type": "text", "normalized": None,
                           "bbox": hit[0] if hit else None}
    if not tables and looks_tabular(lines):
        unverified.append("this page has rows of amounts but no table was detected")
    heading = page_title(lines)
    return {"title": title or heading, "heading": heading, "fields": fields, "tables": out_tables, "table_columns": out_cols,
            "readers": ["text-layer"], "unverified": unverified}


def looks_like_prose(lines: List[str]) -> bool:
    chars = sum(len(l) for l in lines) or 1
    long_chars = sum(len(l) for l in lines if len(l.split()) >= PROSE_WORDS_PER_LINE)
    return long_chars / chars > 0.6


def needs_model(lines: List[str], result: Dict[str, Any]) -> bool:
    """Only a form-like page that code could not make sense of: short label lines, no table, almost no "Label: value"."""
    if config.digital_model_mode() == "always":
        return True
    if config.digital_model_mode() == "never":
        return False
    if result.get("unverified"):                       # code could not prove it read the page completely
        return True
    structured = bool(result["tables"]) or len(result["fields"]) >= MIN_KV_FOR_STRUCTURE
    return not structured and len(lines) >= MIN_LINES_FOR_FORM and not looks_like_prose(lines)
