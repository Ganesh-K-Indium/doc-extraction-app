from fastapi import APIRouter, Depends

from app.api.deps import require_key, workspace
from app.services.documents import classify, workspace_types
from app.services import pipeline
from app.services.reading import router as pipeline_router

router = APIRouter(prefix="/api/workspaces/{workspace_id}/registry", tags=["registry"], dependencies=[Depends(require_key), Depends(workspace)])


@router.get("")
def registry(workspace_id: str):
    """The document types this workspace can recognise: built-in ones plus its own."""
    with workspace_types.use(workspace_id):
        types = []
        for d in classify.all_types():
            item = {"type": d["type"], "label": d["label"], "extractor": d["extractor"], "template": None, "fields": 0, "required": 0, "custom": bool(d.get("custom"))}
            if d.get("template"):
                try:  # one broken custom template must not take the whole list down
                    tpl = pipeline.load_template(d["template"])
                    fields = [f for s in tpl["sections"] for f in s["fields"]]
                    cols = [c for t in tpl.get("tables", []) for c in t["columns"]]
                    item.update({"template": tpl.get("template_id", d["template"]), "fields": len(fields) + len(cols),
                                 "required": sum(1 for f in fields + cols if f.get("required"))})
                except Exception:
                    item.update({"template": d["template"], "broken": True})
            types.append(item)
    return {"types": types, "readers": pipeline_router.READERS}
