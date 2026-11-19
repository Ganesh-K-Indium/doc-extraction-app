"""
End-to-end extraction for one uploaded PDF.

    work PDF  : scanned pages get a Tesseract text layer (tess.py); all geometry runs on it, the viewer shows the original
    per page  : profile -> router picks a reader -> text -> strip stamps -> classify
    documents : consecutive pages grouped; router picks an extractor per document
                template_form -> extract_document (dual readers, multi-page, grounded)   kv -> label/value pairs
    checks    : per-document rules (validation.py) + cross-document consistency (cross.py)

A page that fails to read is recorded with an error and the rest of the file carries on.

Output (stored as one JSON blob; the API serves it as two files):
    pages.json  = {"pages": [...], "documents": [...]}
    fields.json = {"forms": [...], "other_documents": [...], "validation": [...]}
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from app import config
from app.engines import ladder, plan as plans
from app.services.documents import classify
from app.services.quality import cross, validation
from app.services.extraction import discover, form_extractor, kv, remainder
from app.services.reading import ocr, pdf_pages, router, tess

logger = logging.getLogger("app.services.pipeline")

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
PAGE_CONCURRENCY = 4
AUTO, DISCOVER = "auto", "discover"

Progress = Callable[[str, int, int], None]


def load_template(name: str) -> Dict[str, Any]:
    """Built-in templates ship with the app; custom ones belong to the workspace in force."""
    from app.services.documents import workspace_types
    f = TEMPLATE_DIR / f"{name}.json"
    if f.is_file():
        return json.loads(f.read_text())
    custom = workspace_types.template(name)
    if custom is not None:
        return custom
    raise FileNotFoundError(f"No template named {name!r}")


def type_templates() -> Dict[str, str]:
    return {d["type"]: d["template"] for d in classify.all_types() if d.get("template")}


def valid_choice(choice: str) -> bool:
    """'auto' (detect), 'discover' (read as one document with no template) or any registered type with a template."""
    return choice in (AUTO, DISCOVER) or choice in type_templates()


def work_path(path: str) -> str:
    return str(Path(path).with_suffix(".work.pdf"))


async def _page(path: str, work: str, n: int, models: List[str], use_llm: bool, reader, sem: asyncio.Semaphore,
                plan: "plans.Plan", mode: str, force_vision: bool = False, tsv: Optional[str] = None) -> Dict[str, Any]:
    async with sem:
        base: Dict[str, Any] = {"page": n}
        try:
            original = await asyncio.to_thread(pdf_pages.analyze_page, path, n)
            route = router.decide_reader(router.profile_page(original), use_llm, plan.local_engine is not None, mode)
            info = await asyncio.to_thread(pdf_pages.analyze_page, work, n)  # geometry from the work PDF (has OCR layer on scans)
            lines_meta: Dict[str, Any] = {}
            handwritten = False
            reading: Dict[str, Any] = {"engine": "text-layer"}
            if route["reader"] in ("ocr_dual", "ocr_ladder", "ocr_local"):
                jpeg = await asyncio.to_thread(pdf_pages.render_jpeg, path, n)
                scan = await ladder.read_scanned(
                    mode={"ocr_dual": "vision", "ocr_ladder": "escalate"}.get(route["reader"], "local"), engine_id=plan.local_engine,
                    jpeg=jpeg, models=models, reader=reader, threshold=plan.escalate_below, token_cap=plan.token_cap,
                    force_vision=force_vision and route["reader"] != "ocr_local", tsv=tsv)
                raw = [l.text for l in scan.lines]
                lines_meta = {l.text: l for l in scan.lines}
                source, verified, handwritten, reading = scan.source, scan.verified, scan.handwritten, scan.reading
            else:
                raw = [l.strip() for l in original["text"].splitlines() if l.strip()]
                source = "text-layer" if route["reader"] == "text_layer" else "text-layer-unverified"
                verified = route["reader"] == "text_layer"
                if source != "text-layer":
                    reading = {"engine": "scanner text"}
            content, meta = pdf_pages.strip_fax_stamp(raw)
            out_lines = []
            for t in content:
                l = lines_meta.get(t)
                out_lines.append({"text": t, "status": l.status if l else "agreed",
                                  "alternatives": l.alternatives if l else [], "reason": l.reason if l else None})
            text = "\n".join(content)
            return {**base, "size": info["size"], "source": source, "verified": verified, "scanned": original["scanned"],
                    "has_text_layer": bool(info["words"]), "handwritten": handwritten, "page_meta": meta,
                    "classification": classify.classify_text(text), "text": text, "lines": out_lines,
                    "blocks": info["blocks"], "tables": info["tables"], "form_widgets": info["widgets"], "route": route, "reading": reading}
        except Exception as e:
            logger.exception("Page %s failed", n)
            msg = str(e) if isinstance(e, ocr.OcrError) else "This page could not be read."
            return {**base, "size": None, "source": "failed", "verified": False, "scanned": False, "has_text_layer": False, "handwritten": False,
                    "page_meta": {}, "classification": {"type": "unknown", "label": "Unreadable", "confidence": 0.0},
                    "text": "", "lines": [], "blocks": [], "tables": [], "form_widgets": [], "route": None, "reading": {}, "error": msg}


async def process(path: str, progress: Optional[Progress] = None, ocr_reader=None, form_reader=None, model_ask=None,
                  template_choice: str = AUTO, read_rest: bool = False, adjudicator=None, plan: Optional["plans.Plan"] = None,
                  force_vision: Iterable[int] = ()) -> Dict[str, Any]:
    """`plan` says how scans are read (engines/plan.py); without one the server's defaults apply. `force_vision` lists pages
    to send straight to the vision models whatever the plan says (a person asked for a better reading of them)."""
    plan = plan or plans.current()
    with plans.use(plan):
        result = await _process(path, progress, ocr_reader, form_reader, model_ask, template_choice, read_rest, adjudicator, plan, set(force_vision))
    result["reading"] = plan.describe()
    return result


async def _process(path: str, progress: Optional[Progress], ocr_reader, form_reader, model_ask, template_choice: str, read_rest: bool,
                   adjudicator, plan: "plans.Plan", force_vision: "set[int]") -> Dict[str, Any]:
    progress = progress or (lambda *_: None)
    n_pages = await asyncio.to_thread(pdf_pages.page_count, path)
    if n_pages > config.MAX_PAGES:
        raise ocr.OcrError(f"PDF has {n_pages} pages; the limit is {config.MAX_PAGES}.", 413)
    # "local" plans never call a model. Otherwise a model is used when one is configured (or a test supplied a reader).
    use_llm = (plan.llm or ocr_reader is not None) and plan.mode != "local"
    mode = plan.mode if use_llm else "local"
    ocr_models = plan.read_models if use_llm else []
    form_models = plan.extract_models if (plan.mode != "local" and (plan.llm or form_reader is not None)) else []
    if ocr_reader is not None and not ocr_models:
        ocr_models = ["reader-a", "reader-b"]
    if form_reader is not None and not form_models:
        form_models = ["reader-a", "reader-b"]

    # Text layer for scans first: everything geometric (highlighting, label search, checkboxes, tables) depends on it.
    progress("preparing", 0, n_pages)
    work = work_path(path)
    needs = await asyncio.to_thread(pdf_pages.scanned_pages, path)
    tsv_pages: Dict[int, str] = {}
    layer = await asyncio.to_thread(pdf_pages.build_work_pdf, path, work, needs, tsv_pages)
    layer_errors = {n: m for n, m in layer.items() if m != "ok"}

    sem = asyncio.Semaphore(PAGE_CONCURRENCY)
    done = 0

    async def tracked(n):
        nonlocal done
        p = await _page(path, work, n, ocr_models, use_llm, ocr_reader, sem, plan, mode, n in force_vision, tsv_pages.get(n))
        done += 1
        progress("pages", done, n_pages)
        return p

    pages = sorted(await asyncio.gather(*[tracked(n) for n in range(1, n_pages + 1)]), key=lambda p: p["page"])
    for p in pages:
        if p["page"] in layer_errors:
            p["text_layer_error"] = layer_errors[p["page"]]
    if template_choice != AUTO:
        # The user said what this file is. Every page that has content becomes that document; no guessing.
        reg = {d["type"]: d for d in classify.all_types()}
        forced = ({"type": template_choice, "label": reg[template_choice]["label"], "confidence": 1.0, "by": "user"}
                  if template_choice in reg else {"type": "unknown", "label": "Untemplated document", "confidence": 1.0, "by": "user"})
        for p in pages:
            if p["classification"]["type"] != "blank_or_logo" and p["source"] != "failed":
                p["classification"] = dict(forced)
    elif use_llm and ocr_models:
        streak = 0  # consecutive pages the model also could not name; a long untyped document stops costing a call per page
        for i, p in enumerate(pages):  # rules could not name a non-trivial page: ask a small model, restricted to registered types
            if p["classification"]["type"] == "unknown" and p["text"].strip():
                if streak >= config.classify_give_up_after():
                    continue
                prev = pages[i - 1]["text"] if i else ""
                p["classification"] = await classify.classify_with_model(p["text"], ocr_models, model_ask, prev)
                streak = streak + 1 if p["classification"]["type"] == "unknown" else 0
            elif p["classification"]["type"] != "unknown":
                streak = 0
    single_page = set()
    for t, name in type_templates().items():
        try:
            if load_template(name).get("single_page"):
                single_page.add(t)
        except FileNotFoundError:
            pass
    handwritten = {p["page"] for p in pages if p.get("handwritten")}
    documents = classify.segment(pages, single_page)
    by_num = {p["page"]: p for p in pages}

    forms, others, templated = [], [], []
    templates = type_templates()
    for i, doc in enumerate(documents):
        progress("documents", i, len(documents))
        doc_pages = [by_num[n] for n in doc["pages"]]
        texts = {p["page"]: p["text"] for p in doc_pages}
        decision = router.decide_extractor(doc["type"], llm_available=bool(form_models),
                                           all_digital=all(p["source"] == "text-layer" for p in doc_pages))
        doc["route"] = decision
        tpl_name = templates.get(doc["type"]) if decision["extractor"] == "template_form" else None
        if tpl_name:
            tpl = load_template(tpl_name)
            usable = [p["page"] for p in doc_pages if p["classification"]["type"] == doc["type"]] or doc["pages"]
            # Box glyphs (☑ ☐) are only evidence on a born-digital page. In a vision model's transcript they are the model's
            # own guess about the box, so on scans the boxes are judged from the pixels instead.
            glyph_texts = {p["page"]: (p["text"] if p["source"] == "text-layer" else "") for p in doc_pages}
            res = await form_extractor.extract_document(work, usable, glyph_texts, tpl, form_models, form_reader, handwritten, adjudicator)
            forms.append({"doc_index": doc["doc_index"], "doc_type": doc["type"], "template_id": tpl["template_id"],
                          "pages": doc["pages"], "readers": res["readers"], "fields": res["fields"], "tables": res["tables"],
                          "validation": validation.validate_form(tpl, res["fields"], res["tables"]),
                          "_template": tpl, "_text": "\n".join(texts.values())})
            templated.append((forms[-1], tpl))
        elif decision["extractor"] == "discover":
            usable = [p["page"] for p in doc_pages if p["source"] != "failed" and p["classification"]["type"] != "blank_or_logo"] or doc["pages"]
            digital = {n: {"lines": [l["text"] for l in by_num[n]["lines"]], "tables": by_num[n]["tables"]}
                       for n in usable if by_num[n]["source"] == "text-layer"}
            # A page a local OCR engine read well is structured from its text: a few hundred tokens instead of a page image.
            ocr_text = {n: by_num[n]["text"] for n in usable if form_models and by_num[n]["source"] == "ocr-local" and by_num[n]["text"].strip()}
            res = await discover.discover_document(work, usable, form_models, form_reader, handwritten, adjudicator,
                                                   text_pages=ocr_text, digital_pages=digital)
            if res["title"] and doc["type"] == "unknown":
                doc["label"] = res["title"]
            forms.append({"doc_index": doc["doc_index"], "doc_type": doc["type"], "template_id": "discovered", "discovered": True,
                          "label": res["title"] or doc["label"], "pages": doc["pages"], "readers": res["readers"],
                          "fields": res["fields"], "tables": res["tables"], "table_columns": res["table_columns"],
                          "validation": validation.review_notes(res["fields"], res["tables"]),
                          "_template": {"canonical": {}}, "_text": "\n".join(texts.values())})
        elif decision["extractor"] == "kv":
            lines = [l["text"] for p in doc_pages for l in p["lines"]]
            pairs = kv.parse_kv(lines)
            others.append({"doc_index": doc["doc_index"], "doc_type": doc["type"], "pages": doc["pages"],
                           "pairs": pairs, "canonical": kv.canonical(pairs)})

    rest_checked: List[int] = []
    if read_rest and form_models:
        # Text and structure around a template's own fields: read it with discovery, minus what the template covers.
        progress("rest", 0, len(templated))
        next_index = len(documents)               # indexes after the real documents, so nothing collides
        for n, (f, tpl) in enumerate(templated):
            rest_checked.append(f["doc_index"])
            extra = await remainder.remainder_form(work, f, tpl, form_models, form_reader)
            if extra:
                extra.update({"doc_index": next_index, "_template": {"canonical": {}}, "_text": ""})
                next_index += 1
                forms.append(extra)
            progress("rest", n + 1, len(templated))
    findings: List[Dict[str, Any]] = []
    for f in forms:
        findings += [{**v, "doc_index": f["doc_index"]} for v in f["validation"]]
    findings += cross.check([{"doc_index": f["doc_index"], "doc_type": f["doc_type"], "pages": f["pages"], "fields": f["fields"],
                              "tables": f["tables"], "text": f["_text"], "template": f["_template"]} for f in forms])
    for f in forms:  # internal helpers, not part of the stored output
        f.pop("_template"), f.pop("_text")
    progress("done", n_pages, n_pages)
    return {
        "pages": pages, "documents": documents, "forms": forms, "other_documents": others, "validation": findings,
        "rest_checked": rest_checked,
        "stats": {"pages": n_pages, "forms": len(forms),
                  "needs_review": sum(1 for f in forms for c in list(f["fields"].values()) + [x for rows in f["tables"].values() for r in rows for x in r.values()]
                                      if c.get("status") in ("review", "undetermined")),
                  "errors": sum(1 for v in findings if v["severity"] == "error"),
                  "failed_pages": sum(1 for p in pages if p["source"] == "failed"),
                  # how the file was read, for the Documents page: code (digital), models (scans), handwriting seen
                  "digital_pages": sum(1 for p in pages if p["source"] == "text-layer"),
                  "scanned_pages": sum(1 for p in pages if p["source"] in ("ocr", "ocr-local", "text-layer-unverified")),
                  "local_ocr_pages": sum(1 for p in pages if p["source"] == "ocr-local"),
                  "vision_pages": sum(1 for p in pages if p["source"] == "ocr"),
                  "escalated_pages": sum(1 for p in pages if (p.get("reading") or {}).get("escalated")),
                  "region_pages": sum(1 for p in pages if (p.get("reading") or {}).get("scope") == "regions"),
                  "handwritten_pages": sum(1 for p in pages if p.get("handwritten")),
                  "unverified_tables": sum(1 for f in forms for rows in f["tables"].values()
                                           if any(c.get("method") == "text-layer" and c.get("status") == "review" for r in rows for c in r.values()))},
    }
