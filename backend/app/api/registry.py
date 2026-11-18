from fastapi import APIRouter, Depends

from app.api.extractions import require_key
from app.services import classify, pipeline, router as pipeline_router

router = APIRouter(prefix="/api/registry", tags=["registry"], dependencies=[Depends(require_key)])


@router.get("")
def registry():
    types = []
    for d in classify.DOC_TYPES:
        item = {"type": d["type"], "label": d["label"], "extractor": d["extractor"], "template": None, "fields": 0, "required": 0}
        if d.get("template"):
            tpl = pipeline.load_template(d["template"])
            fields = [f for s in tpl["sections"] for f in s["fields"]]
            cols = [c for t in tpl.get("tables", []) for c in t["columns"]]
            item.update({"template": tpl["template_id"], "fields": len(fields) + len(cols),
                         "required": sum(1 for f in fields + cols if f.get("required"))})
        types.append(item)
    return {"types": types, "readers": pipeline_router.READERS}
