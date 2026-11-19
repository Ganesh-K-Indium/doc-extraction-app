"""
Template-free extraction: read whatever a page holds, whatever kind of document it is.

Two vision models each list every labelled field, checkbox and table they can see (the printed label as written, the
value as written). The two lists are matched by label and merged with the same trust model as templated extraction:
agreed / review / single / empty. Checkboxes are judged from pixels where the box can be located; every value is
located on the page (Tesseract layer) and checked against Tesseract's own reading.

The result has the same shape as a templated form, so the review UI, JSON export, corrections and answer-key export
all work unchanged. Fields are keyed "<section>.<label>" in snake case.
"""
import asyncio
import base64
import json
import logging
import re
import time
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from app.services import adjudicate, checkboxes, form_extractor as fx, locate, normalize as N, ocr, pdf_pages
from app.services.usage_tracker import record_usage

logger = logging.getLogger("app.services.discover")

TYPE_MAP = {"date": "date", "phone": "phone"}  # anything else compares as plain text
LABEL_MATCH = 0.86

PAGE_PROMPT = """You are extracting ALL the data on one page of a document, with no template. The page may be a form, a
letter, a statement, a note, an invoice or anything else.

Return JSON only:
{"title": "<the document's title as printed, or null>",
 "fields": [{"label": "<printed label>", "value": "<value as written, or null if the blank is empty>",
             "section": "<printed section heading it sits under, or null>",
             "type": "text|date|number|currency|phone|email|id"}],
 "checkboxes": [{"label": "<option text beside the box>", "group": "<question or heading it belongs to, or null>", "checked": true|false}],
 "tables": [{"title": "<caption or null>", "columns": ["<header>", ...], "rows": [["<cell>", ...], ...]}]}

Rules:
- Copy values exactly, digit for digit. If a character is unreadable write [?]. Never guess or complete.
- Keep a leading decimal point (.2% is not 2%), percent and currency signs, ranges (7-20), fractions and units exactly as written.
- Names and rare words: copy letter by letter, never swap in a common word. When a value is written both in digits and in words, give the digits.
- Each value belongs to ONE field. Never list the same value under two labels, and do not list a value again as a table cell.
- Some pages (handwritten notes, sketches, free-form records) have no printed labels: use the writer's own words as the label, short and in the same wording every time.
- Faint or mirrored writing showing through from the other side of the paper is not part of this page.
- Include labelled blanks that are empty (value null): an empty field is information.
- A label is something printed that names a value ("Date of Birth", "Invoice No."). Do not turn sentences of running text into fields.
- A checkbox is checked only if the box contains a tick, cross or fill.
- Put repeated structures (line items, rows of measurements) in "tables", every row on this page.
- Ignore fax header/footer stamps and page numbers.
"""

BLANK_PROMPT = """This is a BLANK form (nothing filled in) from a PDF. List its structure so a template can be made.

Return JSON only:
{"title": "<the form's title as printed>",
 "fields": [{"label": "<printed label>", "section": "<printed section heading or null>",
             "type": "text|date|phone|number|currency|email|id|state|zip|tax_id|icd10", "required": true|false}],
 "choice_groups": [{"label": "<the question or heading>", "section": "<section or null>", "options": ["<option text>", ...],
                    "multiple": true|false, "required": true|false}],
 "tables": [{"title": "<caption or null>", "columns": [{"label": "<header>", "required": true|false}]}]}

Rules:
- Every blank to be filled in is a field, in reading order. Use the exact printed label without the * mark.
- "required" is true when the label carries a star, asterisk or the word "required".
- Rows of check boxes belong in choice_groups; "multiple" is true when more than one may be ticked.
- A grid with column headers and empty rows is a table.
"""


def slug(s: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")[:48]


def _canon(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


async def _read(model: str, jpeg: bytes, prompt: str) -> Dict[str, Any]:
    b64 = base64.b64encode(jpeg).decode()
    kwargs: Dict[str, Any] = {"model": model, "response_format": {"type": "json_object"}, "messages": [{
        "role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"}}]}]}
    if model.startswith(("gpt-5", "o")):
        kwargs["reasoning_effort"] = "low"
    else:
        kwargs["temperature"] = 0
    start = time.perf_counter()
    resp = await ocr._get_client().chat.completions.create(**kwargs)
    usage = getattr(resp, "usage", None)
    record_usage(stage="discover", model=model, prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                 completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                 total_tokens=getattr(usage, "total_tokens", 0) or 0, duration_seconds=time.perf_counter() - start)
    return parse(resp.choices[0].message.content)


def _s(v: Any) -> Optional[str]:
    if v is None:
        return None
    t = str(v).strip()
    return t or None


def parse(raw: Any) -> Dict[str, Any]:
    """Defensive parse of a model reply (or an already-parsed dict) into the shape the rest of this module uses."""
    if isinstance(raw, str):
        try:
            raw = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip()))
        except ValueError:
            raw = {}
    d = raw if isinstance(raw, dict) else {}
    fields = [{"label": _s(f.get("label")), "value": _s(f.get("value")), "section": _s(f.get("section")),
               "type": str(f.get("type") or "text").lower(), "required": bool(f.get("required"))}
              for f in (d.get("fields") or []) if isinstance(f, dict) and _s(f.get("label"))]
    boxes = [{"label": _s(c.get("label")), "group": _s(c.get("group")), "checked": bool(c.get("checked"))}
             for c in (d.get("checkboxes") or []) if isinstance(c, dict) and _s(c.get("label"))]
    tables = []
    for t in d.get("tables") or []:
        if not isinstance(t, dict):
            continue
        cols = t.get("columns") or []
        cols = [(_s(c.get("label")) if isinstance(c, dict) else _s(c)) or "" for c in cols]
        rows = [[_s(c) for c in r] for r in (t.get("rows") or []) if isinstance(r, list)]
        if cols:
            tables.append({"title": _s(t.get("title")), "columns": cols, "rows": rows})
    groups = [{"label": _s(g.get("label")), "section": _s(g.get("section")), "options": [o for o in (_s(x) for x in (g.get("options") or [])) if o],
               "multiple": bool(g.get("multiple")), "required": bool(g.get("required"))}
              for g in (d.get("choice_groups") or []) if isinstance(g, dict) and _s(g.get("label"))]
    return {"title": _s(d.get("title")), "fields": fields, "checkboxes": boxes, "tables": tables, "choice_groups": groups}


def _unique(keys: List[str]) -> List[str]:
    seen: Dict[str, int] = {}
    out = []
    for k in keys:
        seen[k] = seen.get(k, 0) + 1
        out.append(k if seen[k] == 1 else f"{k}_{seen[k]}")
    return out


def _field_keys(items: List[Dict[str, Any]]) -> List[str]:
    return _unique([(f"{slug(i['section'])}." if slug(i.get("section")) else "") + (slug(i["label"]) or "field") for i in items])


def _pair(a_items, a_keys, b_items, b_keys) -> List[Tuple[Optional[int], Optional[int]]]:
    """Match the second reader's items to the first's, in three passes:
       1. the same key (section and label),
       2. a close label in the same section,
       3. a very close label in ANY section (the readers often file a field under different headings),
       4. the same value under a different label (handwritten notes, where the labels are the writer's own words).
    Among several candidates the one at the nearest relative position on the page wins, so a repeated label ("Tax ID"
    in two blocks) pairs with its own twin."""
    used: set = set()
    match: Dict[int, int] = {}
    na, nb = max(1, len(a_items)), max(1, len(b_items))

    def sim(i, j):
        return SequenceMatcher(None, _canon(a_items[i]["label"]), _canon(b_items[j]["label"]), autojunk=False).ratio()

    def best(i, ok):
        cands = [(abs(i / na - j / nb), j) for j in range(len(b_items)) if j not in used and ok(j)]
        return min(cands)[1] if cands else None

    def same_value(i, j):
        """Handwritten notes have no fixed labels, so two readers name the same value differently ("Name" / "President").
        An identical, substantial value is the same field whatever each reader called it."""
        va, vb = a_items[i].get("value"), b_items[j].get("value")
        return bool(va and vb) and len(_canon(va)) >= 3 and N.normalize(va, "text") == N.normalize(vb, "text")

    passes = (lambda i, j: a_keys[i] == b_keys[j],
              lambda i, j: slug(a_items[i].get("section")) == slug(b_items[j].get("section")) and sim(i, j) >= LABEL_MATCH,
              lambda i, j: sim(i, j) >= 0.92,
              same_value)
    for ok in passes:
        for i in range(len(a_items)):
            if i in match:
                continue
            j = best(i, lambda j, i=i: ok(i, j))
            if j is not None:
                match[i] = j
                used.add(j)
    pairs = [(i, match.get(i)) for i in range(len(a_items))]
    pairs.extend((None, j) for j in range(len(b_items)) if j not in used)
    return pairs


def merge_fields(a: List[Dict[str, Any]], b: Optional[List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    two = b is not None
    b = b or []
    ak, bk = _field_keys(a), _field_keys(b)
    out: Dict[str, Dict[str, Any]] = {}
    for i, j in _pair(a, ak, b, bk):
        fa, fb = (a[i] if i is not None else None), (b[j] if j is not None else None)
        src = fa or fb
        key = ak[i] if i is not None else bk[j]
        ftype = TYPE_MAP.get(src["type"], "text")
        cell = fx.merge_field(fa["value"] if fa else None, fb["value"] if fb else None, ftype, two)
        if two and (fa is None or fb is None):
            cell["value"] = (fa or fb)["value"]
            cell["alternatives"] = []
            if cell["value"] is None:
                cell["status"] = "empty"          # a blank the other reader did not list: nothing to check
            else:
                cell["status"] = "review"
                cell["reason"] = "only one reader found this field"
        cell.update({"label": src["label"], "section": src.get("section"), "type": src["type"], "normalized": N.normalize(cell["value"], ftype)})
        out[key] = cell
    return out


def _grid_index(tables: List[Dict[str, Any]]) -> Dict[str, Tuple[int, int, int, str]]:
    """'<row label> <column header>' (either order) -> (table, row, col, value), for tables whose first column labels the rows."""
    idx: Dict[str, Tuple[int, int, int, str]] = {}
    for ti, t in enumerate(tables):
        for ri, row in enumerate(t["rows"]):
            label = row[0] if row else None
            for ci, cell in enumerate(row):
                head = t["columns"][ci] if ci < len(t["columns"]) else ""
                if ci and label and head and cell is not None:
                    for k in (_canon(f"{label} {head}"), _canon(f"{head} {label}")):
                        idx[k] = (ti, ri, ci, cell)
    return idx


def reconcile(a: Dict[str, Any], b: Dict[str, Any]) -> Tuple[set, set]:
    """One reader may return a grid as a table and the other as flat fields ("Flexion Right: 170"). Same data, different
    shape. A flat field that equals a cell of the other reader's table confirms that cell and is dropped (its data lives
    in the table). Returns the confirmed (table, row, col) cells of a's tables and of b's tables."""
    conf_a: set = set()
    conf_b: set = set()

    def sweep(fields, other_index, confirmed):
        keep = []
        for f in fields:
            hit = other_index.get(_canon(f["label"]))
            if hit and _canon(f["value"] or "") == _canon(hit[3] or ""):
                confirmed.add(hit[:3])
            else:
                keep.append(f)
        fields[:] = keep

    sweep(a["fields"], _grid_index(b["tables"]), conf_b)
    sweep(b["fields"], _grid_index(a["tables"]), conf_a)
    for conf in (conf_a, conf_b):          # a row label is confirmed by any value in its row
        conf.update({(t, r, 0) for t, r, _ in list(conf)})
    return conf_a, conf_b


def _match_tables(a: List[Dict[str, Any]], b: List[Dict[str, Any]]) -> List[Tuple[Optional[int], Optional[int]]]:
    used: set = set()
    pairs = []
    for i, ta in enumerate(a):
        pick = None
        for j, tb in enumerate(b):
            if j in used:
                continue
            same_title = bool(ta["title"]) and _canon(ta["title"]) == _canon(tb["title"] or "")
            head = SequenceMatcher(None, _canon(" ".join(ta["columns"])), _canon(" ".join(tb["columns"]))).ratio()
            if same_title or (len(ta["columns"]) == len(tb["columns"]) and head >= 0.8):
                pick = j
                break
        if pick is not None:
            used.add(pick)
        pairs.append((i, pick))
    pairs.extend((None, j) for j in range(len(b)) if j not in used)
    return pairs


def merge_tables(a: List[Dict[str, Any]], b: Optional[List[Dict[str, Any]]], conf_a: Any = frozenset(), conf_b: Any = frozenset()):
    two = b is not None
    b = b or []
    pairs = _match_tables(a, b)
    titles = [(a[i] if i is not None else b[j])["title"] for i, j in pairs]
    keys = _unique([slug(t) or f"table_{n + 1}" for n, t in enumerate(titles)])
    tables: Dict[str, List[Dict[str, Any]]] = {}
    columns: Dict[str, List[str]] = {}
    for key, (i, j) in zip(keys, pairs):
        ta, tb = (a[i] if i is not None else None), (b[j] if j is not None else None)
        base = ta or tb
        base_conf = conf_a if ta else conf_b
        base_index = i if ta else j
        cols = _unique([slug(c) or f"col_{x + 1}" for x, c in enumerate(base["columns"])])
        both = ta is not None and tb is not None and len(ta["columns"]) == len(tb["columns"])
        rows = []
        for r in range(max(len(ta["rows"]) if ta else 0, len(tb["rows"]) if (tb and both) else 0) if both else len(base["rows"])):
            ra = ta["rows"][r] if ta and r < len(ta["rows"]) else None
            rb = tb["rows"][r] if both and r < len(tb["rows"]) else None
            src = ra if ra is not None else rb
            row = {}
            for c, ckey in enumerate(cols):
                va = ra[c] if ra and c < len(ra) else None
                vb = rb[c] if rb and c < len(rb) else None
                if both:
                    cell = fx.merge_field(va, vb, "text", two)
                    if two and (ra is None or rb is None):
                        cell.update({"status": "review", "reason": "only one reader saw this row", "value": va if ra is not None else vb})
                else:
                    value = (src[c] if src and c < len(src) else None)
                    cell = {"value": value, "status": "single", "alternatives": []}
                    if two and (base_index, r, c) in base_conf:
                        cell["status"] = "agreed"              # the other reader gave this cell as a flat field: same data
                    elif two and value is not None:
                        cell.update({"status": "review", "reason": "the readers did not find the same table"})
                cell["label"] = base["columns"][c]
                row[ckey] = cell
            rows.append(row)
        tables[key], columns[key] = rows, list(base["columns"])
    return tables, columns


def merge_checkboxes(path: str, page_num: int, a: List[Dict[str, Any]], b: Optional[List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    two = b is not None
    b = b or []
    ak, bk = (_unique([(f"{slug(i['group'])}." if slug(i.get("group")) else "checkboxes.") + (slug(i["label"]) or "box") for i in items]) for items in (a, b))
    pairs = _pair([{**i, "section": i.get("group")} for i in a], ak, [{**i, "section": i.get("group")} for i in b], bk)
    labels = {}
    for i, j in pairs:
        src = a[i] if i is not None else b[j]
        labels[src["label"]] = (0.0, 1e9)
    try:
        px = checkboxes.pixel_states(path, page_num, labels) if labels else {}
    except Exception as e:
        logger.warning("pixel checkbox read failed: %s", e)
        px = {}
    out: Dict[str, Dict[str, Any]] = {}
    for i, j in pairs:
        ca, cb = (a[i] if i is not None else None), (b[j] if j is not None else None)
        src = ca or cb
        key = ak[i] if i is not None else bk[j]
        ma = ca["checked"] if ca else None
        mb = cb["checked"] if cb else None
        seen = px.get(src["label"])
        if seen is not None:
            models = [m for m in (ma, mb) if m is not None]
            agrees = all(m == seen for m in models)
            cell = {"value": seen, "status": "agreed" if agrees else "review", "method": "pixel", "alternatives": [] if agrees else [str(models[0] if models else "")],
                    **({} if agrees else {"reason": "the model reading differs from the pixels"})}
        else:
            cell = fx.model_checkbox("checkbox", ma, mb, two) or {"value": None, "status": "undetermined", "alternatives": [], "method": None}
            if two and (ca is None or cb is None):
                cell["status"], cell["reason"] = "review", "only one reader found this box"
        cell.update({"label": src["label"], "section": src.get("group"), "type": "checkbox"})
        out[key] = cell
    return out


def _tokens(label: Optional[str]) -> set:
    return set(re.findall(r"[a-z0-9]+", (label or "").lower()))


def prune_empty_noise(fields: Dict[str, Dict[str, Any]], title: Optional[str]) -> int:
    """Models sometimes list the page title, or a whole sentence of running text, as an empty "blank". A blank is a short
    printed label with nothing written after it; neither of those is one. Filled fields are never touched."""
    drop = [k for k, c in fields.items() if c.get("status") == "empty" and c.get("type") != "checkbox"
            and ((title and _canon(c.get("label") or "") == _canon(title)) or len(re.findall(r"\S+", c.get("label") or "")) >= 7)]
    for k in drop:
        del fields[k]
    return len(drop)


def dedupe(fields: Dict[str, Dict[str, Any]], tables: Dict[str, List[Dict[str, Any]]]) -> int:
    """Drop repeats of one value that discovery lists twice, the way handwritten pages tend to produce them.

    A field repeats another when it has the same value and either the same place on the page or labels that are one
    inside the other ("Corporation" / "Corporation Name", "Day" / "Date - day"). A flat field whose long text is already
    a table cell is the table's data in another shape. The better-supported cell is kept. Returns how many were dropped."""
    rank = lambda c: fx._RANK.get(c.get("status"), 4)
    keys = [k for k, c in fields.items() if c.get("type") != "checkbox" and isinstance(c.get("value"), str)
            and len(_canon(c["value"])) >= 4 and c.get("status") not in ("empty", "corrected")]
    drop: set = set()
    for x, a in enumerate(keys):
        for b in keys[x + 1:]:
            if a in drop or b in drop:
                continue
            ca, cb = fields[a], fields[b]
            if N.normalize(ca["value"], "text") != N.normalize(cb["value"], "text"):
                continue
            ta, tb = _tokens(ca.get("label")), _tokens(cb.get("label"))
            same_place = bool(ca.get("bbox")) and ca.get("bbox") == cb.get("bbox")
            nested = bool(ta and tb) and (ta <= tb or tb <= ta)
            if same_place or nested:
                drop.add(b if rank(cb) >= rank(ca) else a)
    cells = {N.normalize(c.get("value"), "text") or "" for rows in tables.values() for r in rows for c in r.values()
             if isinstance(c.get("value"), str)}
    for k in keys:
        v = N.normalize(fields[k]["value"], "text") or ""
        if k not in drop and len(v) >= 12 and any(v in cell for cell in cells):
            drop.add(k)
    for k in drop:
        del fields[k]
    return len(drop)


async def discover_page(path: str, page_num: int, models: List[str], reader=None, handwritten: bool = False,
                        adjudicator=None) -> Dict[str, Any]:
    injected = reader is not None          # a caller-supplied reader (tests) means no real model calls, so no real third look either
    reader = reader or _read
    replies: List[Dict[str, Any]] = []
    jpeg = None
    if models:
        jpeg = await asyncio.to_thread(pdf_pages.render_jpeg, path, page_num)
        results = await asyncio.gather(*[asyncio.wait_for(reader(m, jpeg, PAGE_PROMPT), ocr.ENGINE_TIMEOUT_SECONDS + 5) for m in models],
                                       return_exceptions=True)
        for m, r in zip(models, results):
            if isinstance(r, BaseException):
                logger.warning("Discovery reader %s failed: %s", m, r)
            else:
                replies.append(parse(r))
    two = len(replies) > 1
    a = replies[0] if replies else parse({})
    b = replies[1] if two else None
    conf_a, conf_b = reconcile(a, b) if b else (set(), set())
    fields = merge_fields(a["fields"], b["fields"] if b else None)
    boxes = await asyncio.to_thread(merge_checkboxes, path, page_num, a["checkboxes"], b["checkboxes"] if b else None)
    fields.update({k: v for k, v in boxes.items() if k not in fields})
    tables, columns = merge_tables(a["tables"], b["tables"] if b else None, conf_a, conf_b)

    page_alnum = await asyncio.to_thread(locate.page_alnum, path, page_num)

    if two and jpeg is not None and (adjudicator is not None or not injected):
        # one focused extra call for this page, only because the readers left something in dispute
        items = [(f"f:{k}", c, TYPE_MAP.get(c.get("type"), "text")) for k, c in fields.items()]
        items += [(f"t:{k}:{r}:{ck}", c, "text") for k, rows in tables.items() for r, row in enumerate(rows) for ck, c in row.items()]
        await adjudicate.settle(jpeg, items, adjudicator)

    def ground():
        for cell in list(fields.values()) + [c for rows in tables.values() for r in rows for c in r.values()]:
            v = cell.get("value")
            if isinstance(v, str) and v:
                hit = locate.find_with_text(path, page_num, v, cell.get("label"))
                cell["bbox"] = hit[0] if hit else None
                if not handwritten:                  # Tesseract cannot read handwriting: its "second opinion" would only add noise
                    fx._third_opinion(cell, hit)
            elif cell.get("method") == "pixel" or isinstance(v, bool):
                hit = locate.find(path, page_num, cell.get("label") or "")
                cell["bbox"] = hit
            if two and cell.get("status") == "review" and not handwritten:
                fx._prefer_page_text(cell, "text", page_alnum)
    await asyncio.to_thread(ground)
    for cell in list(fields.values()) + [c for rows in tables.values() for r in rows for c in r.values()]:
        cell.setdefault("bbox", None)
        cell["page"] = page_num
    prune_empty_noise(fields, a["title"])
    dedupe(fields, tables)
    return {"title": a["title"], "fields": fields, "tables": tables, "table_columns": columns,
            "readers": models[:len(replies)] if models else []}


async def discover_document(path: str, pages: List[int], models: List[str], reader=None, handwritten: Any = (),
                            adjudicator=None) -> Dict[str, Any]:
    """All pages of one untemplated document, merged: the best-supported reading per field wins, tables continue."""
    results = await asyncio.gather(*[discover_page(path, n, models, reader, n in handwritten, adjudicator) for n in pages])
    fields: Dict[str, Dict[str, Any]] = {}
    tables: Dict[str, List[Dict[str, Any]]] = {}
    columns: Dict[str, List[str]] = {}
    for res in results:
        for k, cell in res["fields"].items():
            have = fields.get(k)
            if have is None or fx._RANK.get(cell["status"], 4) < fx._RANK.get(have["status"], 4):
                fields[k] = cell
        for k, rows in res["tables"].items():
            same = k in tables and len(columns[k]) == len(res["table_columns"][k])
            key = k if (k not in tables or same) else f"{k}_p{rows[0][next(iter(rows[0]))]['page']}" if rows else k
            tables.setdefault(key, []).extend(rows)
            columns.setdefault(key, res["table_columns"][k])
    title = next((r["title"] for r in results if r["title"]), None)
    return {"title": title, "fields": fields, "tables": tables, "table_columns": columns,
            "readers": results[0]["readers"] if results else []}
