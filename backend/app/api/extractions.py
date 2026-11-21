import asyncio
import copy
import hashlib
import logging
import re
from typing import Any, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from app import config, db
from app.api.deps import require_key, workspace
from app.engines.strategy import plan as plans
from app.services import export, pipeline
from app.services.documents import classify
from app.services.reading import ocr, pdf_pages
from app.services.extraction import figures, remainder
from app.services.documents import template_draft, workspace_types
from app.services.usage_tracker import track_usage

logger = logging.getLogger("app.api.extractions")


router = APIRouter(prefix="/api/workspaces/{workspace_id}/extractions", tags=["extractions"], dependencies=[Depends(require_key), Depends(workspace)])


def _summary(ex) -> dict:
    return {"id": ex.id, "filename": ex.filename, "status": ex.status, "stage": ex.stage,
            "progress": {"done": ex.progress_done, "total": ex.progress_total}, "error": ex.error,
            "template_choice": ex.template_choice, "read_rest": bool(ex.read_rest), "created_at": ex.created_at.isoformat(), "stats": (ex.result or {}).get("stats"), "reading": (ex.result or {}).get("reading"),
            # what the file turned out to be: the discovered title, else the classified label, for the first few documents
            "labels": _labels(ex)}


def _labels(ex) -> list:
    res = ex.result or {}
    titles = {f["doc_index"]: f.get("label") for f in res.get("forms", []) if f.get("label") and not f.get("remainder")}
    out: list = []
    for d in res.get("documents", []):
        label = titles.get(d["doc_index"]) or d.get("label")
        if label and label not in classify.GENERIC_LABELS and label not in out:
            out.append(label)
    return out[:3]


def _get(s, workspace_id: str, extraction_id: str):
    ex = s.get(db.Extraction, extraction_id)
    if not ex or ex.workspace_id != workspace_id:
        raise HTTPException(404, "Extraction not found.")
    return ex


def _templates(workspace_id: str) -> dict:
    """Every template this workspace can use, by document type (built-in and its own)."""
    out = {}
    with workspace_types.use(workspace_id):
        for doc_type, name in pipeline.type_templates().items():
            try:
                out[doc_type] = pipeline.load_template(name)
            except FileNotFoundError:
                pass
    return out


def pdf_file(extraction_id: str):
    return config.UPLOAD_DIR / f"{extraction_id}.pdf"


async def run_extraction(extraction_id: str) -> None:
    def progress(stage: str, done: int, total: int) -> None:
        with db.session() as s:
            ex = s.get(db.Extraction, extraction_id)
            if ex is None:
                return
            ex.stage, ex.progress_done, ex.progress_total = stage, done, total
            s.commit()

    with db.session() as s:
        ex = s.get(db.Extraction, extraction_id)
        if ex is None:  # the workspace was deleted while this was queued
            return
        ex.status = "processing"
        choice, ws_id, rest = ex.template_choice or "auto", ex.workspace_id, bool(ex.read_rest)
        override = dict(ex.reading or {})
        s.commit()
    try:
        plan = plans.for_workspace(ws_id, {"strategy": override.get("strategy")})
        with workspace_types.use(ws_id), track_usage(f"extraction:{extraction_id[:8]}") as usage:
            result = await pipeline.process(str(pdf_file(extraction_id)), progress, template_choice=choice, read_rest=rest, plan=plan,
                                            force_vision=override.get("force_vision") or ())
        summary = usage.summary()
        result["stats"]["usage"] = {"calls": len(usage.entries), "tokens": summary["total_tokens"],
                                    "by_stage": {k: v["tokens"] for k, v in summary["by_stage"].items()}}
        result["pipeline_version"] = config.PIPELINE_VERSION
        status, error = "done", None
    except ocr.OcrError as e:
        result, status, error = None, "failed", str(e)
    except Exception:
        logger.exception("Extraction %s failed", extraction_id)
        result, status, error = None, "failed", "Extraction failed unexpectedly. See server logs."
    with db.session() as s:
        ex = s.get(db.Extraction, extraction_id)
        if ex is None:
            return
        ex.status, ex.error, ex.result = status, error, result
        s.commit()


@router.post("", status_code=202)
async def upload(workspace_id: str, background: BackgroundTasks, file: UploadFile = File(...), template: str = Form("auto"),
                 read_rest: bool = Form(False), reading: str = Form("")):
    data = await file.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"The file is larger than {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    if not data.startswith(b"%PDF"):
        raise HTTPException(415, "Upload a PDF file.")
    with workspace_types.use(workspace_id):
        valid = pipeline.valid_choice(template)
    if not valid:
        raise HTTPException(422, "That document type is not available. Pick one from the list, or choose automatic detection.")
    if reading and reading not in {s["id"] for s in plans.STRATEGIES}:
        raise HTTPException(422, "Choose Economy, Balanced or Accuracy for how scanned pages are read.")
    digest = hashlib.sha256(data).hexdigest()
    wanted = plans.for_workspace(workspace_id, {"strategy": reading or None}).fingerprint()
    with db.session() as s:
        # Same bytes already read successfully by this version of the pipeline, under the same reading plan: reuse that
        # result instead of paying again. (A page-by-page re-read is never reused: it was a deliberate exception.)
        candidates = s.query(db.Extraction).filter_by(workspace_id=workspace_id, sha256=digest, status="done", template_choice=template, read_rest=read_rest).order_by(db.Extraction.created_at.desc()).all()
        prior = next((c for c in candidates if not (c.reading or {}).get("force_vision")
                      and (c.result or {}).get("reading", {}).get("fingerprint") == wanted), None)
        if prior and pdf_file(prior.id).is_file() and (prior.result or {}).get("pipeline_version") == config.PIPELINE_VERSION:
            return {"id": prior.id, "status": "done", "reused": True}
        ex = db.Extraction(workspace_id=workspace_id, filename=(file.filename or "document.pdf")[:255], sha256=digest, template_choice=template, read_rest=read_rest,
                           reading={"strategy": reading} if reading else {})
        s.add(ex)
        s.commit()
        extraction_id = ex.id
    await asyncio.to_thread(pdf_file(extraction_id).write_bytes, data)
    background.add_task(run_extraction, extraction_id)
    return {"id": extraction_id, "status": "queued"}


@router.get("")
def list_extractions(workspace_id: str):
    with db.session() as s:
        rows = s.query(db.Extraction).filter_by(workspace_id=workspace_id).order_by(db.Extraction.created_at.desc()).limit(200).all()
        return [_summary(r) for r in rows]


@router.get("/{extraction_id}")
def get_extraction(workspace_id: str, extraction_id: str):
    with db.session() as s:
        ex = _get(s, workspace_id, extraction_id)
        out = _summary(ex)
        if ex.status == "done":
            out["pages"] = export.pages_json(ex)
            out["fields"] = export.fields_json(ex, _templates(workspace_id))
            out["structure"] = export.structure_json(ex)
        return out


@router.get("/{extraction_id}/pages.json")
def download_pages(workspace_id: str, extraction_id: str):
    with db.session() as s:
        return export.pages_json(_get(s, workspace_id, extraction_id))


@router.get("/{extraction_id}/structure.json")
def download_structure(workspace_id: str, extraction_id: str):
    with db.session() as s:
        return export.structure_json(_get(s, workspace_id, extraction_id))


@router.get("/{extraction_id}/fields.json")
def download_fields(workspace_id: str, extraction_id: str):
    with db.session() as s:
        return export.fields_json(_get(s, workspace_id, extraction_id), _templates(workspace_id))


@router.get("/{extraction_id}/pdf")
def get_pdf(workspace_id: str, extraction_id: str):
    with db.session() as s:
        _get(s, workspace_id, extraction_id)
    p = pdf_file(extraction_id)
    if not p.is_file():
        raise HTTPException(404, "PDF is no longer available.")
    return FileResponse(p, media_type="application/pdf")


class Correction(BaseModel):
    doc_index: int
    key: str
    value: Any = None


_CELL = re.compile(r"^(?P<t>[^\[\]]+)\[(?P<r>\d+)\]\.(?P<c>.+)$")


def _has_cell(form: dict, key: str) -> bool:
    """A field key, or `table[row].column` (row from 0) naming a cell that exists."""
    if key in form["fields"]:
        return True
    m = _CELL.match(key)
    rows = form["tables"].get(m["t"]) if m else None
    return bool(m) and rows is not None and int(m["r"]) < len(rows) and m["c"] in rows[int(m["r"])]


@router.patch("/{extraction_id}/fields")
def correct_field(workspace_id: str, extraction_id: str, body: Correction):
    """Edit or confirm one value (a field, or a table cell as `table[row].column`). Also refreshes the workspace's
    "to check" count so it falls as values are settled."""
    with db.session() as s:
        ex = _get(s, workspace_id, extraction_id)
        result = ex.result or {}
        if not any(f["doc_index"] == body.doc_index and _has_cell(f, body.key) for f in result.get("forms", [])):
            raise HTTPException(404, "No such field.")
        corrections = {**(ex.corrections or {}), f"{body.doc_index}:{body.key}": body.value}
        ex.corrections = corrections
        ex.result = {**result, "stats": {**result.get("stats", {}), "needs_review": export.review_count(result, corrections)}}
        s.commit()
        return {"ok": True, "needs_review": ex.result["stats"]["needs_review"]}


@router.delete("/{extraction_id}", status_code=204)
def delete_extraction(workspace_id: str, extraction_id: str):
    with db.session() as s:
        ex = _get(s, workspace_id, extraction_id)
        s.delete(ex)
        s.commit()
    pdf_file(extraction_id).unlink(missing_ok=True)
    pdf_file(extraction_id).with_suffix(".work.pdf").unlink(missing_ok=True)


class Reread(BaseModel):
    strategy: str = ""                  # economy | balanced | accuracy | custom; empty keeps the workspace's setting
    pages: List[int] = []               # pages to send straight to the vision models; empty means the whole document


@router.post("/{extraction_id}/reread", status_code=202)
async def reread(workspace_id: str, extraction_id: str, body: Reread, background: BackgroundTasks):
    """Read this file again with a different reading strategy, or send some pages to the vision models. The original
    extraction is left as it is: this creates a second one to compare with."""
    if body.strategy and body.strategy not in {s["id"] for s in plans.STRATEGIES}:
        raise HTTPException(422, "Choose Economy, Balanced, Accuracy or Custom.")
    strategy = body.strategy or ("" if body.pages else "accuracy")
    if (strategy != "economy" or body.pages) and not config.llm_enabled():
        raise HTTPException(503, "A better reading needs a vision model, and none is configured on this server.")
    with db.session() as s:
        src = _get(s, workspace_id, extraction_id)
        if not pdf_file(extraction_id).is_file():
            raise HTTPException(404, "The original PDF is no longer available.")
        filename, sha, choice, rest = src.filename, src.sha256, src.template_choice, src.read_rest
    n_pages = await asyncio.to_thread(pdf_pages.page_count, str(pdf_file(extraction_id)))
    if any(p < 1 or p > n_pages for p in body.pages):
        raise HTTPException(422, f"Pages must be between 1 and {n_pages}.")
    reading: dict = {}
    if strategy:
        reading["strategy"] = strategy
    if body.pages:
        reading["force_vision"] = sorted(set(body.pages))
    with db.session() as s:
        ex = db.Extraction(workspace_id=workspace_id, filename=filename, sha256=sha, template_choice=choice, read_rest=rest, reading=reading)
        s.add(ex)
        s.commit()
        new_id = ex.id
    await asyncio.to_thread(lambda: pdf_file(new_id).write_bytes(pdf_file(extraction_id).read_bytes()))
    background.add_task(run_extraction, new_id)
    return {"id": new_id, "status": "queued"}


class Promote(BaseModel):
    title: str = ""


@router.post("/{extraction_id}/forms/{doc_index}/promote")
def promote(workspace_id: str, extraction_id: str, doc_index: int, body: Promote):
    """Turn a reviewed, untemplated extraction into a registered document type, so the next file of that kind is
    recognised, validated and cross-checked."""
    with db.session() as s:
        ex = _get(s, workspace_id, extraction_id)
        form = next((f for f in (ex.result or {}).get("forms", []) if f["doc_index"] == doc_index), None)
        if not form:
            raise HTTPException(404, "No such document.")
        if not form.get("discovered"):
            raise HTTPException(409, "This document already uses a template.")
        draft = template_draft.from_discovery(form, body.title.strip() or None)
        try:
            doc_type = template_draft.save_custom_type(workspace_id, draft["template"])
        except FileExistsError as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))
        return {"doc_type": doc_type, "title": draft["template"]["title"], "fields": sum(len(x["fields"]) for x in draft["template"]["sections"])}


@router.get("/{extraction_id}/truth.json")
def download_truth(workspace_id: str, extraction_id: str):
    """The current (reviewed) values as an answer key for eval/score.py. Review the extraction first: what you
    download is only as right as your corrections."""
    with db.session() as s:
        return export.truth_json(_get(s, workspace_id, extraction_id))


@router.post("/{extraction_id}/documents/{doc_index}/rest")
async def read_the_rest(workspace_id: str, extraction_id: str, doc_index: int):
    """Read what a templated document's template does not cover (text around the form, other fields and tables), on
    demand. Adds a separate "Other content" entry; the form's own fields are never touched."""
    if not config.llm_enabled():
        raise HTTPException(503, "Reading the rest of a page needs a vision model, and none is configured on this server.")
    with db.session() as s:
        ex = _get(s, workspace_id, extraction_id)
        result = ex.result or {}
        forms = result.get("forms", [])
        form = next((f for f in forms if f["doc_index"] == doc_index), None)
        if form is None:
            raise HTTPException(404, "No such document.")
        if form.get("discovered"):
            raise HTTPException(409, "This document was already read without a template, so there is no rest to read.")
        if doc_index in result.get("rest_checked", []):
            raise HTTPException(409, "The rest of this document has already been read.")
    with workspace_types.use(workspace_id):
        name = pipeline.type_templates().get(form["doc_type"])
        if name is None:
            raise HTTPException(409, "This document's type no longer exists in the workspace.")
        template = pipeline.load_template(name)
    work = pipeline.work_path(str(pdf_file(extraction_id)))
    try:
        extra = await remainder.remainder_form(work, form, template, plans.for_workspace(workspace_id).extract_models)
    except Exception:
        logger.exception("Reading the rest of %s failed", extraction_id)
        raise HTTPException(502, "The pages could not be read just now. Try again in a minute.")
    with db.session() as s:
        ex = _get(s, workspace_id, extraction_id)
        result = dict(ex.result or {})
        result["rest_checked"] = sorted(set(result.get("rest_checked", [])) | {doc_index})
        added = 0
        if extra:
            idx = 1 + max([f["doc_index"] for f in result["forms"]] + [d["doc_index"] for d in result["documents"]])
            extra["doc_index"] = idx
            result["forms"] = [*result["forms"], extra]
            result["validation"] = [*result["validation"], *({**v, "doc_index": idx} for v in extra["validation"])]
            added = len(extra["fields"]) + sum(len(r) for r in extra["tables"].values())
            result["stats"] = {**result.get("stats", {}), "needs_review": export.review_count(result, ex.corrections or {})}
        ex.result = result
        s.commit()
    return {"added": bool(extra), "doc_index": extra["doc_index"] if extra else None, "items": added}


def _figure_blocks(result: dict):
    """(page, block) of every figure in an extraction's pages, in reading order."""
    for p in result.get("pages", []):
        for b in (p.get("structure") or {}).get("blocks", []):
            if b.get("type") == "figure":
                yield p, b


def _figure_box(page: dict, block: dict) -> list:
    size = page.get("size") or {}
    w, h = size.get("width") or 0, size.get("height") or 0
    x0, y0, x1, y1 = block["bbox"]
    return [x0 * w, y0 * h, x1 * w, y1 * h]


class FigureRead(BaseModel):
    page: int = 0                       # which figure: its page and its number on the page...
    index: int = 0
    all: bool = False                   # ...or every figure not yet read
    force: bool = False                 # read again a figure that already has a reading


@router.post("/{extraction_id}/figures/read")
async def read_figures(workspace_id: str, extraction_id: str, body: FigureRead):
    """Read figures (charts, diagrams, drawings, pictures) with a vision model, on request. One crop and one reply per figure, from
    the workspace's first extraction model; a figure that already has a reading is not read again unless asked. The number of
    figures read is capped (FIGURE_READ_MAX) because each is a model call."""
    if not config.llm_enabled():
        raise HTTPException(503, "Reading a figure needs a vision model, and none is configured on this server.")
    with db.session() as s:
        ex = _get(s, workspace_id, extraction_id)
        result = copy.deepcopy(ex.result or {})
    if not pdf_file(extraction_id).is_file():
        raise HTTPException(404, "The original PDF is no longer available.")
    every = list(_figure_blocks(result))
    if not body.all and not any(p["page"] == body.page and b.get("index") == body.index for p, b in every):
        raise HTTPException(404, "No such figure.")
    wanted = [(p, b) for p, b in every if (body.all or (p["page"] == body.page and b.get("index") == body.index)) and (body.force or not b.get("reading"))]
    already = sum(1 for _, b in every if b.get("reading"))
    room = max(0, config.figure_read_max() - (0 if body.force else already)) if body.all else config.figure_read_max()
    skipped = max(0, len(wanted) - room)
    wanted = wanted[:room]
    if not wanted:
        return {"read": 0, "failed": 0, "skipped": skipped, "tokens": 0, "figures": []}
    models = plans.for_workspace(workspace_id).extract_models
    if not models:
        raise HTTPException(503, "No model is set up to read figures.")
    path = str(pdf_file(extraction_id))
    sem = asyncio.Semaphore(2)
    done: list = []
    failed = 0

    async def one(p: dict, b: dict) -> None:
        nonlocal failed
        async with sem:
            try:
                reading = await figures.read(path, p["page"], _figure_box(p, b), b.get("labels") or [], models[0], fresh=body.force)
            except Exception:
                logger.exception("Reading figure %s of page %s failed", b.get("index"), p["page"])
                failed += 1
                return
        b["reading"], b["kind"] = reading, reading.get("kind")
        b["decorative"] = reading.get("kind") == "logo"
        done.append({"page": p["page"], "index": b.get("index"), "kind": reading.get("kind")})

    with track_usage(f"figures:{extraction_id[:8]}") as usage:
        await asyncio.gather(*[one(p, b) for p, b in wanted])
    if failed and not done:
        raise HTTPException(502, "The figure could not be read just now. Try again in a minute.")
    tokens = usage.summary()["total_tokens"]
    with db.session() as s:
        ex = _get(s, workspace_id, extraction_id)
        stats = dict(result.get("stats", {}))
        u = dict(stats.get("usage") or {"calls": 0, "tokens": 0, "by_stage": {}})
        u["calls"], u["tokens"] = u.get("calls", 0) + len(usage.entries), u.get("tokens", 0) + tokens
        u["by_stage"] = {**u.get("by_stage", {}), "figures": u.get("by_stage", {}).get("figures", 0) + tokens}
        stats["usage"], stats["figures_read"] = u, sum(1 for _, b in _figure_blocks(result) if b.get("reading"))
        result["stats"] = stats
        ex.result = result
        s.commit()
    return {"read": len(done), "failed": failed, "skipped": skipped, "tokens": tokens, "figures": sorted(done, key=lambda d: (d["page"], d["index"]))}


@router.get("/{extraction_id}/figures/{page}/{index}.jpg")
async def figure_image(workspace_id: str, extraction_id: str, page: int, index: int):
    """The figure as cropped from its page: what a reader would be sent, for showing next to its reading."""
    with db.session() as s:
        result = _get(s, workspace_id, extraction_id).result or {}
    hit = next(((p, b) for p, b in _figure_blocks(result) if p["page"] == page and b.get("index") == index), None)
    if hit is None or not pdf_file(extraction_id).is_file():
        raise HTTPException(404, "No such figure.")
    jpeg = await asyncio.to_thread(figures.crop_jpeg, str(pdf_file(extraction_id)), page, _figure_box(*hit))
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


class FigureEdit(BaseModel):
    page: int
    index: int
    field: str                          # "summary", "title", "s0.name" (a series' name), "s0.p2.x" or "s0.p2.y" (a point of a chart)
    value: str


_FIGURE_FIELD = re.compile(r"^(?:summary|title|s(?P<s>\d+)\.name|s(?P<s2>\d+)\.p(?P<p>\d+)\.(?P<axis>[xy]))$")
MAX_EDIT_CHARS = 1000


@router.patch("/{extraction_id}/figures")
def edit_figure(workspace_id: str, extraction_id: str, body: FigureEdit):
    """Correct what a model read off a figure, by hand. No model is called, so it costs nothing. The value is changed where it is
    stored (so pages.json and structure.json carry it) and the item is marked manually_corrected. A chart value a person has set is
    no longer an estimate. Reading the figure again replaces the reading, edits included."""
    m = _FIGURE_FIELD.match(body.field)
    text = body.value.strip()[:MAX_EDIT_CHARS]
    if not m:
        raise HTTPException(422, "That part of a figure cannot be edited.")
    if not text:
        raise HTTPException(422, "Type a value.")
    with db.session() as s:
        ex = _get(s, workspace_id, extraction_id)
        result = copy.deepcopy(ex.result or {})
        hit = next(((p, b) for p, b in _figure_blocks(result) if p["page"] == body.page and b.get("index") == body.index), None)
        if hit is None or not hit[1].get("reading"):
            raise HTTPException(404, "No such figure, or it has not been read yet.")
        reading = hit[1]["reading"]
        if body.field in ("summary", "title"):
            reading[body.field] = text
            reading["manually_corrected"] = True
        else:
            series = (reading.get("chart") or {}).get("series") or []
            si = int(m.group("s") if m.group("s") is not None else m.group("s2"))
            if si >= len(series):
                raise HTTPException(404, "No such value on this figure.")
            if m.group("s") is not None:
                series[si]["name"] = text
                series[si]["manually_corrected"] = True
            else:
                points = series[si].get("points") or []
                pi = int(m.group("p"))
                if pi >= len(points):
                    raise HTTPException(404, "No such value on this figure.")
                point = points[pi]
                point[m.group("axis")] = text
                if m.group("axis") == "y":
                    nums = figures._numbers(text)
                    point["value"] = float(nums[0]) if nums else None
                    point["estimated"] = False                     # a person set it
                point["manually_corrected"] = True
        ex.result = result
        s.commit()
        return {"ok": True}
