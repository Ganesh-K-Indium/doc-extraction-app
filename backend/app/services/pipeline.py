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
from typing import Any, Callable, Dict, List, Optional

from app import config
from app.services import classify, cross, discover, form_extractor, kv, ocr, pdf_pages, remainder, router, tess, validation

logger = logging.getLogger("app.services.pipeline")

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
PAGE_CONCURRENCY = 4
AUTO, DISCOVER = "auto", "discover"

Progress = Callable[[str, int, int], None]


def load_template(name: str) -> Dict[str, Any]:
    """Built-in templates ship with the app; custom ones belong to the workspace in force."""
    from app.services import workspace_types
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


async def _page(path: str, work: str, n: int, models: List[str], use_llm: bool, reader, sem: asyncio.Semaphore) -> Dict[str, Any]:
    async with sem:
        base: Dict[str, Any] = {"page": n}
        try:
            original = await asyncio.to_thread(pdf_pages.analyze_page, path, n)
            route = router.decide_reader(router.profile_page(original), use_llm, tess.available())
            info = await asyncio.to_thread(pdf_pages.analyze_page, work, n)  # geometry from the work PDF (has OCR layer on scans)
            lines_meta: Dict[str, Any] = {}
            if route["reader"] == "ocr_dual":
                jpeg = await asyncio.to_thread(pdf_pages.render_jpeg, path, n)
                res = await ocr.read_page(jpeg, models, reader)
                raw = [l.text for l in res.lines]
                lines_meta = {l.text: l for l in res.lines}
                source, verified = "ocr", res.cross_checked
            elif route["reader"] == "ocr_local":
                raw = [l.strip() for l in info["text"].splitlines() if l.strip()]
                source, verified = "ocr-local", False
            else:
                raw = [l.strip() for l in original["text"].splitlines() if l.strip()]
                source = "text-layer" if route["reader"] == "text_layer" else "text-layer-unverified"
                verified = route["reader"] == "text_layer"
            content, meta = pdf_pages.strip_fax_stamp(raw)
            out_lines = []
            for t in content:
                l = lines_meta.get(t)
                out_lines.append({"text": t, "status": l.status if l else "agreed",
                                  "alternatives": l.alternatives if l else [], "reason": l.reason if l else None})
            text = "\n".join(content)
            return {**base, "size": info["size"], "source": source, "verified": verified, "scanned": original["scanned"],
                    "has_text_layer": bool(info["words"]), "page_meta": meta,
                    "classification": classify.classify_text(text), "text": text, "lines": out_lines,
                    "blocks": info["blocks"], "tables": info["tables"], "form_widgets": info["widgets"], "route": route}
        except Exception as e:
            logger.exception("Page %s failed", n)
            msg = str(e) if isinstance(e, ocr.OcrError) else "This page could not be read."
            return {**base, "size": None, "source": "failed", "verified": False, "scanned": False, "has_text_layer": False,
                    "page_meta": {}, "classification": {"type": "unknown", "label": "Unreadable", "confidence": 0.0},
                    "text": "", "lines": [], "blocks": [], "tables": [], "form_widgets": [], "route": None, "error": msg}


async def process(path: str, progress: Optional[Progress] = None, ocr_reader=None, form_reader=None, model_ask=None,
                  template_choice: str = AUTO, read_rest: bool = False) -> Dict[str, Any]:
    progress = progress or (lambda *_: None)
    n_pages = await asyncio.to_thread(pdf_pages.page_count, path)
    if n_pages > config.MAX_PAGES:
        raise ocr.OcrError(f"PDF has {n_pages} pages; the limit is {config.MAX_PAGES}.", 413)
    use_llm = config.llm_enabled() or ocr_reader is not None
    ocr_models = ocr.configured_models() if use_llm else []
    form_models = config.extraction_models() if (config.llm_enabled() or form_reader is not None) else []
    if ocr_reader is not None and not ocr_models:
        ocr_models = ["reader-a", "reader-b"]
    if form_reader is not None and not form_models:
        form_models = ["reader-a", "reader-b"]

    # Text layer for scans first: everything geometric (highlighting, label search, checkboxes, tables) depends on it.
    progress("preparing", 0, n_pages)
    work = work_path(path)
    needs = await asyncio.to_thread(pdf_pages.scanned_pages, path)
    layer = await asyncio.to_thread(pdf_pages.build_work_pdf, path, work, needs)
    layer_errors = {n: m for n, m in layer.items() if m != "ok"}

    sem = asyncio.Semaphore(PAGE_CONCURRENCY)
    done = 0

    async def tracked(n):
        nonlocal done
        p = await _page(path, work, n, ocr_models, use_llm, ocr_reader, sem)
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
        for i, p in enumerate(pages):  # rules could not name a non-trivial page: ask a small model, restricted to registered types
            if p["classification"]["type"] == "unknown" and p["text"].strip():
                prev = pages[i - 1]["text"] if i else ""
                p["classification"] = await classify.classify_with_model(p["text"], ocr_models, model_ask, prev)
    single_page = set()
    for t, name in type_templates().items():
        try:
            if load_template(name).get("single_page"):
                single_page.add(t)
        except FileNotFoundError:
            pass
    documents = classify.segment(pages, single_page)
    by_num = {p["page"]: p for p in pages}

    forms, others, templated = [], [], []
    templates = type_templates()
    for i, doc in enumerate(documents):
        progress("documents", i, len(documents))
        doc_pages = [by_num[n] for n in doc["pages"]]
        texts = {p["page"]: p["text"] for p in doc_pages}
        decision = router.decide_extractor(doc["type"], llm_available=bool(form_models))
        doc["route"] = decision
        tpl_name = templates.get(doc["type"]) if decision["extractor"] == "template_form" else None
        if tpl_name:
            tpl = load_template(tpl_name)
            usable = [p["page"] for p in doc_pages if p["classification"]["type"] == doc["type"]] or doc["pages"]
            # Box glyphs (☑ ☐) are only evidence on a born-digital page. In a vision model's transcript they are the model's
            # own guess about the box, so on scans the boxes are judged from the pixels instead.
            glyph_texts = {p["page"]: (p["text"] if p["source"] == "text-layer" else "") for p in doc_pages}
            res = await form_extractor.extract_document(work, usable, glyph_texts, tpl, form_models, form_reader)
            forms.append({"doc_index": doc["doc_index"], "doc_type": doc["type"], "template_id": tpl["template_id"],
                          "pages": doc["pages"], "readers": res["readers"], "fields": res["fields"], "tables": res["tables"],
                          "validation": validation.validate_form(tpl, res["fields"], res["tables"]),
                          "_template": tpl, "_text": "\n".join(texts.values())})
            templated.append((forms[-1], tpl))
        elif decision["extractor"] == "discover":
            usable = [p["page"] for p in doc_pages if p["source"] != "failed" and p["classification"]["type"] != "blank_or_logo"] or doc["pages"]
            res = await discover.discover_document(work, usable, form_models, form_reader)
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
                  "needs_review": sum(1 for f in forms for c in f["fields"].values() if c.get("status") in ("review", "undetermined")),
                  "errors": sum(1 for v in findings if v["severity"] == "error"),
                  "failed_pages": sum(1 for p in pages if p["source"] == "failed")},
    }
