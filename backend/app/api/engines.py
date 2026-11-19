"""
Reading engines and the per-workspace reading plan.

    GET  /api/engines                       what this server can use: local OCR engines, model providers, strategies
    POST /api/engines/test                  try one engine or model on a small built-in sample page
    GET  /api/workspaces/{id}/reading       the workspace's saved reading settings and the plan they resolve to
    PUT  /api/workspaces/{id}/reading       save them (validated; keys for cloud models stay in the server's environment)
"""
import asyncio
import io
import logging
import time
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import config
from app.api.deps import require_key, workspace
from app.engines import llm, local, plan
from app.services.reading import ocr
from app.services.usage_tracker import track_usage

logger = logging.getLogger("app.api.engines")

router = APIRouter(prefix="/api/engines", tags=["engines"], dependencies=[Depends(require_key)])
ws_router = APIRouter(prefix="/api/workspaces/{workspace_id}/reading", tags=["engines"], dependencies=[Depends(require_key), Depends(workspace)])

SAMPLE_LINES = ["Invoice No. 48213", "Date: 03/14/2026", "Total due $1,250.75", "Ref AB-9071"]
SAMPLE_TOKENS = ["48213", "03/14/2026", "1,250.75", "AB-9071"]


def overview() -> Dict[str, Any]:
    return {"local_only": config.local_only(), "llm_enabled": config.llm_enabled(),
            "local_engines": local.listing(), "providers": llm.providers_status(),
            "strategies": [dict(s) for s in plan.STRATEGIES],
            "defaults": {"models": llm.default_models(), "escalate_below": plan.DEFAULT_THRESHOLD, "plan": plan.resolve().describe()}}


@router.get("")
def engines():
    return overview()


def sample_page() -> bytes:
    """A small clean page with a few labelled values, drawn here so the test needs no file."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (900, 420), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=40)
    for i, t in enumerate(SAMPLE_LINES):
        d.text((50, 40 + i * 85), t, fill="black", font=font)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=92)
    return out.getvalue()


def _found(text: str) -> float:
    compact = text.replace(" ", "").lower()
    return sum(1 for t in SAMPLE_TOKENS if t.replace(" ", "").lower() in compact) / len(SAMPLE_TOKENS)


class TestIn(BaseModel):
    kind: str            # "local" | "model"
    id: str              # a local engine id, or a model spec


@router.post("/test")
async def test_engine(body: TestIn):
    """Read the built-in sample page with one engine and report what came back. A model test costs a few hundred tokens."""
    jpeg = await asyncio.to_thread(sample_page)
    start = time.perf_counter()
    if body.kind == "local":
        eng = local.get(body.id)
        if eng is None:
            raise HTTPException(404, "No such engine.")
        if not eng.available():
            return {"ok": False, "error": f"{eng.label} is not installed. {eng.install}"}
        try:
            r = await eng.read(jpeg)
        except Exception as e:
            logger.warning("Engine test %s failed: %s", body.id, e)
            return {"ok": False, "error": f"{eng.label} could not read the sample page."}
        return {"ok": True, "seconds": round(time.perf_counter() - start, 2), "text": r.text, "confidence": r.confidence,
                "score": _found(r.text), "tokens": 0}
    if body.kind == "model":
        if not llm.valid_spec(body.id):
            raise HTTPException(422, "Write the model as provider:model.")
        try:
            with track_usage("engine-test") as usage:
                reply = await asyncio.wait_for(llm.complete(body.id, ocr.PROMPT, jpeg, stage="engine_test"), 90)
            lines = ocr.parse_lines(reply)
        except llm.LLMError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.warning("Model test %s failed: %s", body.id, e)
            return {"ok": False, "error": "The model did not answer. Check the key, the model name and the network."}
        text = "\n".join(lines)
        return {"ok": True, "seconds": round(time.perf_counter() - start, 2), "text": text, "confidence": None,
                "score": _found(text), "tokens": sum(e.total_tokens for e in usage.entries)}
    raise HTTPException(422, "kind must be local or model.")


def reading_view(workspace_id: str) -> Dict[str, Any]:
    saved = plan.stored(workspace_id)
    return {"settings": saved, "plan": plan.resolve(saved).describe(), "strategy_default": plan.resolve().strategy}


@ws_router.get("")
def get_reading(workspace_id: str):
    return reading_view(workspace_id)


@ws_router.put("")
def put_reading(workspace_id: str, body: Dict[str, Any]):
    try:
        cleaned = plan.clean(body)
    except ValueError as e:
        raise HTTPException(422, str(e))
    plan.save(workspace_id, cleaned)
    return reading_view(workspace_id)
