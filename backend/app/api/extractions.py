import asyncio
import hashlib
import logging
import re
from typing import Any, List

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import config, db
from app.api.deps import require_key, workspace
from app.services import export, ocr, pipeline, remainder, template_draft, workspace_types

logger = logging.getLogger("app.api.extractions")


router = APIRouter(prefix="/api/workspaces/{workspace_id}/extractions", tags=["extractions"], dependencies=[Depends(require_key), Depends(workspace)])


def _summary(ex) -> dict:
    return {"id": ex.id, "filename": ex.filename, "status": ex.status, "stage": ex.stage,
            "progress": {"done": ex.progress_done, "total": ex.progress_total}, "error": ex.error,
            "template_choice": ex.template_choice, "read_rest": bool(ex.read_rest), "created_at": ex.created_at.isoformat(), "stats": (ex.result or {}).get("stats")}


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
        s.commit()
    try:
        with workspace_types.use(ws_id):
            result = await pipeline.process(str(pdf_file(extraction_id)), progress, template_choice=choice, read_rest=rest)
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
                 read_rest: bool = Form(False)):
    data = await file.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"The file is larger than {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    if not data.startswith(b"%PDF"):
        raise HTTPException(415, "Upload a PDF file.")
    with workspace_types.use(workspace_id):
        valid = pipeline.valid_choice(template)
    if not valid:
        raise HTTPException(422, "That document type is not available. Pick one from the list, or choose automatic detection.")
    digest = hashlib.sha256(data).hexdigest()
    with db.session() as s:
        # Same bytes already read successfully by this version of the pipeline: reuse that result instead of paying again.
        prior = s.query(db.Extraction).filter_by(workspace_id=workspace_id, sha256=digest, status="done", template_choice=template, read_rest=read_rest).order_by(db.Extraction.created_at.desc()).first()
        if prior and pdf_file(prior.id).is_file() and (prior.result or {}).get("pipeline_version") == config.PIPELINE_VERSION:
            return {"id": prior.id, "status": "done", "reused": True}
        ex = db.Extraction(workspace_id=workspace_id, filename=(file.filename or "document.pdf")[:255], sha256=digest, template_choice=template, read_rest=read_rest)
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
        return out


@router.get("/{extraction_id}/pages.json")
def download_pages(workspace_id: str, extraction_id: str):
    with db.session() as s:
        return export.pages_json(_get(s, workspace_id, extraction_id))


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
        extra = await remainder.remainder_form(work, form, template, config.extraction_models())
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
