import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from app import config
from app.api.deps import require_key, workspace
from app.services import ocr, template_draft

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
            return await template_draft.draft_from_blank(str(path), config.extraction_models())
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


@router.delete("/{doc_type}", status_code=204)
def delete(workspace_id: str, doc_type: str):
    if not template_draft.delete_custom_type(workspace_id, doc_type):
        raise HTTPException(404, "No custom document type with that name.")
