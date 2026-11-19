import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func

from app import config, db
from app.api.deps import require_key

logger = logging.getLogger("app.api.workspaces")
router = APIRouter(prefix="/api/workspaces", tags=["workspaces"], dependencies=[Depends(require_key)])


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)


def _stats(s) -> dict:
    """Per-workspace counts in one query each, reading the stored stats instead of loading every result."""
    docs = dict(s.query(db.Extraction.workspace_id, func.count()).group_by(db.Extraction.workspace_id).all())
    busy = dict(s.query(db.Extraction.workspace_id, func.count()).filter(db.Extraction.status.in_(("queued", "processing")))
                .group_by(db.Extraction.workspace_id).all())
    last = dict(s.query(db.Extraction.workspace_id, func.max(db.Extraction.created_at)).group_by(db.Extraction.workspace_id).all())
    review = dict(s.query(db.Extraction.workspace_id, func.sum(db.Extraction.result["stats"]["needs_review"].as_integer()))
                  .filter(db.Extraction.status == "done").group_by(db.Extraction.workspace_id).all())
    errors = dict(s.query(db.Extraction.workspace_id, func.sum(db.Extraction.result["stats"]["errors"].as_integer()))
                  .filter(db.Extraction.status == "done").group_by(db.Extraction.workspace_id).all())
    types = dict(s.query(db.CustomType.workspace_id, func.count()).group_by(db.CustomType.workspace_id).all())
    return {"docs": docs, "busy": busy, "last": last, "review": review, "errors": errors, "types": types}


def _row(w, st) -> dict:
    last = st["last"].get(w.id) or w.created_at
    return {"id": w.id, "name": w.name, "description": w.description, "created_at": w.created_at.isoformat(),
            "documents": st["docs"].get(w.id, 0), "processing": st["busy"].get(w.id, 0),
            "to_check": int(st["review"].get(w.id) or 0), "errors": int(st["errors"].get(w.id) or 0),
            "custom_types": st["types"].get(w.id, 0), "last_activity": last.isoformat()}


def _name_taken(s, name: str, except_id: Optional[str] = None) -> bool:
    q = s.query(db.Workspace).filter(func.lower(db.Workspace.name) == name.strip().lower())
    if except_id:
        q = q.filter(db.Workspace.id != except_id)
    return q.first() is not None


@router.get("")
def list_workspaces():
    with db.session() as s:
        st = _stats(s)
        rows = [_row(w, st) for w in s.query(db.Workspace).all()]
    return sorted(rows, key=lambda r: r["last_activity"], reverse=True)


@router.post("", status_code=201)
def create(body: WorkspaceIn):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Give the workspace a name.")
    with db.session() as s:
        if _name_taken(s, name):
            raise HTTPException(409, f"You already have a workspace named “{name}”. Choose another name.")
        w = db.Workspace(name=name, description=(body.description or "").strip())
        s.add(w)
        s.commit()
        return _row(w, _stats(s))


@router.get("/{workspace_id}")
def get_workspace(workspace_id: str):
    with db.session() as s:
        w = s.get(db.Workspace, workspace_id)
        if not w:
            raise HTTPException(404, "Workspace not found.")
        return _row(w, _stats(s))


@router.patch("/{workspace_id}")
def rename(workspace_id: str, body: WorkspaceIn):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Give the workspace a name.")
    with db.session() as s:
        w = s.get(db.Workspace, workspace_id)
        if not w:
            raise HTTPException(404, "Workspace not found.")
        if _name_taken(s, name, except_id=workspace_id):
            raise HTTPException(409, f"You already have a workspace named “{name}”. Choose another name.")
        w.name = name
        if body.description is not None:
            w.description = body.description.strip()
        s.commit()
        return _row(w, _stats(s))


@router.delete("/{workspace_id}", status_code=204)
def delete(workspace_id: str):
    """Deletes the workspace with its documents, results, uploaded files and custom types. Irreversible."""
    with db.session() as s:
        w = s.get(db.Workspace, workspace_id)
        if not w:
            raise HTTPException(404, "Workspace not found.")
        ids = [e.id for e in s.query(db.Extraction).filter_by(workspace_id=workspace_id).all()]
        s.query(db.Extraction).filter_by(workspace_id=workspace_id).delete()
        s.query(db.CustomType).filter_by(workspace_id=workspace_id).delete()
        s.query(db.WorkspaceReading).filter_by(workspace_id=workspace_id).delete()
        s.delete(w)
        s.commit()
    for eid in ids:
        pdf = config.UPLOAD_DIR / f"{eid}.pdf"
        pdf.unlink(missing_ok=True)
        pdf.with_suffix(".work.pdf").unlink(missing_ok=True)
