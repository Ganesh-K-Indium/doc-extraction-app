import asyncio
import hashlib
import logging
from typing import Any, List

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import config, db
from app.services import export, ocr, pipeline, template_draft

logger = logging.getLogger("app.api.extractions")


def require_key(x_api_key: str = Header(default="")) -> None:
    if config.API_KEY and x_api_key != config.API_KEY:
        raise HTTPException(401, "Missing or invalid API key.")


router = APIRouter(prefix="/api/extractions", tags=["extractions"], dependencies=[Depends(require_key)])


def _summary(ex) -> dict:
    return {"id": ex.id, "filename": ex.filename, "status": ex.status, "stage": ex.stage,
            "progress": {"done": ex.progress_done, "total": ex.progress_total}, "error": ex.error,
            "template_choice": ex.template_choice, "created_at": ex.created_at.isoformat(), "stats": (ex.result or {}).get("stats")}


def _get(s, extraction_id: str):
    ex = s.get(db.Extraction, extraction_id)
    if not ex:
        raise HTTPException(404, "Extraction not found.")
    return ex


def pdf_file(extraction_id: str):
    return config.UPLOAD_DIR / f"{extraction_id}.pdf"


async def run_extraction(extraction_id: str) -> None:
    def progress(stage: str, done: int, total: int) -> None:
        with db.session() as s:
            ex = s.get(db.Extraction, extraction_id)
            ex.stage, ex.progress_done, ex.progress_total = stage, done, total
            s.commit()

    with db.session() as s:
        ex = s.get(db.Extraction, extraction_id)
        ex.status = "processing"
        s.commit()
    try:
        with db.session() as s:
            choice = s.get(db.Extraction, extraction_id).template_choice or "auto"
        result = await pipeline.process(str(pdf_file(extraction_id)), progress, template_choice=choice)
        status, error = "done", None
    except ocr.OcrError as e:
        result, status, error = None, "failed", str(e)
    except Exception:
        logger.exception("Extraction %s failed", extraction_id)
        result, status, error = None, "failed", "Extraction failed unexpectedly. See server logs."
    with db.session() as s:
        ex = s.get(db.Extraction, extraction_id)
        ex.status, ex.error, ex.result = status, error, result
        s.commit()


@router.post("", status_code=202)
async def upload(background: BackgroundTasks, file: UploadFile = File(...), template: str = Form("auto")):
    data = await file.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"The file is larger than {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    if not data.startswith(b"%PDF"):
        raise HTTPException(415, "Upload a PDF file.")
    if not pipeline.valid_choice(template):
        raise HTTPException(422, "That document type is not available. Pick one from the list, or choose automatic detection.")
    digest = hashlib.sha256(data).hexdigest()
    with db.session() as s:
        # Same bytes already read successfully: reuse that result instead of paying for the same OCR again.
        prior = s.query(db.Extraction).filter_by(sha256=digest, status="done", template_choice=template).order_by(db.Extraction.created_at.desc()).first()
        if prior and pdf_file(prior.id).is_file():
            return {"id": prior.id, "status": "done", "reused": True}
        ex = db.Extraction(filename=(file.filename or "document.pdf")[:255], sha256=digest, template_choice=template)
        s.add(ex)
        s.commit()
        extraction_id = ex.id
    await asyncio.to_thread(pdf_file(extraction_id).write_bytes, data)
    background.add_task(run_extraction, extraction_id)
    return {"id": extraction_id, "status": "queued"}


@router.get("")
def list_extractions():
    with db.session() as s:
        rows = s.query(db.Extraction).order_by(db.Extraction.created_at.desc()).limit(200).all()
        return [_summary(r) for r in rows]


@router.get("/{extraction_id}")
def get_extraction(extraction_id: str):
    with db.session() as s:
        ex = _get(s, extraction_id)
        out = _summary(ex)
        if ex.status == "done":
            out["pages"] = export.pages_json(ex)
            out["fields"] = export.fields_json(ex)
        return out


@router.get("/{extraction_id}/pages.json")
def download_pages(extraction_id: str):
    with db.session() as s:
        return export.pages_json(_get(s, extraction_id))


@router.get("/{extraction_id}/fields.json")
def download_fields(extraction_id: str):
    with db.session() as s:
        return export.fields_json(_get(s, extraction_id))


@router.get("/{extraction_id}/pdf")
def get_pdf(extraction_id: str):
    with db.session() as s:
        _get(s, extraction_id)
    p = pdf_file(extraction_id)
    if not p.is_file():
        raise HTTPException(404, "PDF is no longer available.")
    return FileResponse(p, media_type="application/pdf")


class Correction(BaseModel):
    doc_index: int
    key: str
    value: Any = None


@router.patch("/{extraction_id}/fields")
def correct_field(extraction_id: str, body: Correction):
    with db.session() as s:
        ex = _get(s, extraction_id)
        known = any(f["doc_index"] == body.doc_index and body.key in f["fields"] for f in (ex.result or {}).get("forms", []))
        if not known:
            raise HTTPException(404, "No such field.")
        ex.corrections = {**(ex.corrections or {}), f"{body.doc_index}:{body.key}": body.value}
        s.commit()
        return {"ok": True}


@router.delete("/{extraction_id}", status_code=204)
def delete_extraction(extraction_id: str):
    with db.session() as s:
        ex = _get(s, extraction_id)
        s.delete(ex)
        s.commit()
    pdf_file(extraction_id).unlink(missing_ok=True)
    pdf_file(extraction_id).with_suffix(".work.pdf").unlink(missing_ok=True)


class Promote(BaseModel):
    title: str = ""


@router.post("/{extraction_id}/forms/{doc_index}/promote")
def promote(extraction_id: str, doc_index: int, body: Promote):
    """Turn a reviewed, untemplated extraction into a registered document type, so the next file of that kind is
    recognised, validated and cross-checked."""
    with db.session() as s:
        ex = _get(s, extraction_id)
        form = next((f for f in (ex.result or {}).get("forms", []) if f["doc_index"] == doc_index), None)
        if not form:
            raise HTTPException(404, "No such document.")
        if not form.get("discovered"):
            raise HTTPException(409, "This document already uses a template.")
        draft = template_draft.from_discovery(form, body.title.strip() or None)
        try:
            doc_type = template_draft.save_custom_type(draft["template"], draft["entry"])
        except ValueError as e:
            raise HTTPException(422, str(e))
        return {"doc_type": doc_type, "title": draft["template"]["title"], "fields": sum(len(x["fields"]) for x in draft["template"]["sections"])}


@router.get("/{extraction_id}/truth.json")
def download_truth(extraction_id: str):
    """The current (reviewed) values as an answer key for eval/score.py. Review the extraction first: what you
    download is only as right as your corrections."""
    with db.session() as s:
        return export.truth_json(_get(s, extraction_id))
