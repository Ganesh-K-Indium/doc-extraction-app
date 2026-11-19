import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from app import config
from app.api.deps import require_key, workspace
from app import db
from app.services import classify, ocr, pipeline, suggest, template_draft, workspace_types

logger = logging.getLogger("app.api.templates")
router = APIRouter(prefix="/api/workspaces/{workspace_id}/templates", tags=["templates"], dependencies=[Depends(require_key), Depends(workspace)])


@router.post("/draft")
async def draft(workspace_id: str, file: UploadFile = File(...)):
    """Upload a blank form (PDF or scan) and get a draft template back to review. Nothing is saved yet."""
    if not config.llm_enabled():
        raise HTTPException(503, "Drafting a template reads the form with a vision model; set OPENAI_API_KEY first.")
    data = await file.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "The file is too large.")
    if not data.startswith(b"%PDF"):
        raise HTTPException(415, "Upload a PDF file.")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "blank.pdf"
        path.write_bytes(data)
        try:
            drafted = await template_draft.draft_from_blank(str(path), config.extraction_models())
            try:  # best effort: a draft without locations is still a draft
                await asyncio.to_thread(template_draft.locate_fields, str(path), drafted["template"])
            except Exception:
                logger.exception("Could not locate the drafted fields on the blank form")
            return drafted
        except ocr.OcrError as e:
            raise HTTPException(e.status_code, str(e))
        except Exception:
            logger.exception("Template draft failed")
            raise HTTPException(502, "The form could not be read. Try again, or upload a clearer copy.")


class Save(BaseModel):
    template: Dict[str, Any]


@router.post("", status_code=201)
def save(workspace_id: str, body: Save):
    try:
        doc_type = template_draft.save_custom_type(workspace_id, body.template)
    except FileExistsError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"doc_type": doc_type}


@router.get("/suggestions")
def suggestions(workspace_id: str):
    """Document shapes that keep recurring among this workspace's untemplated files, each ready to be saved as a type
    (use the extraction/doc_index of an example with the promote endpoint)."""
    with db.session() as s:
        rows = [{"extraction_id": e.id, "filename": e.filename, "forms": (e.result or {}).get("forms", [])}
                for e in s.query(db.Extraction).filter_by(workspace_id=workspace_id, status="done").order_by(db.Extraction.created_at.desc()).limit(500)]
        titles = [t.title for t in s.query(db.CustomType).filter_by(workspace_id=workspace_id).all()]
    return {"suggestions": suggest.recurring_shapes(rows, titles)}


@router.get("/{doc_type}")
def get_template(workspace_id: str, doc_type: str):
    """A document type's template: built-in ones are read-only, the workspace's own can be edited."""
    with workspace_types.use(workspace_id):
        name = pipeline.type_templates().get(doc_type)
        if name is None:
            raise HTTPException(404, "No document type with that name.")
        template = pipeline.load_template(name)
    return {"template": template, "builtin": doc_type in {d["type"] for d in classify.DOC_TYPES}}


@router.put("/{doc_type}")
def replace(workspace_id: str, doc_type: str, body: Save):
    """Replace one of this workspace's own types (its name stays the same). Documents already extracted keep their results."""
    if body.template.get("doc_type") != doc_type:
        raise HTTPException(422, "The template's name does not match the type being edited.")
    with workspace_types.use(workspace_id):
        if doc_type not in {d["type"] for d in classify.custom_types()}:
            raise HTTPException(404, "No custom document type with that name. Built-in types cannot be edited.")
    try:
        template_draft.save_custom_type(workspace_id, body.template, replace=True)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"doc_type": doc_type}


@router.delete("/{doc_type}", status_code=204)
def delete(workspace_id: str, doc_type: str):
    if not template_draft.delete_custom_type(workspace_id, doc_type):
        raise HTTPException(404, "No custom document type with that name.")
