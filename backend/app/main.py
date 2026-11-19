from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config, db
from app.engines.providers import llm
from app.engines.ocr import local
from app.api import engines, extractions, registry, settings, templates, workspaces


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Document Extraction", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
app.include_router(workspaces.router)
app.include_router(settings.router)
app.include_router(engines.router)
app.include_router(engines.ws_router)
app.include_router(extractions.router)
app.include_router(registry.router)
app.include_router(templates.router)


@app.get("/health")
def health():
    return {"ok": True, "llm": config.llm_enabled(), "tesseract": any(e.id == "tesseract" for e in local.ready()),
            "local_only": config.local_only(), "local_engines": [e.id for e in local.ready()],
            "providers": [p["id"] for p in llm.providers_status() if p["ready"]]}
