from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config, db
from app.services import tess
from app.api import extractions, registry, templates


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Document Extraction", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
app.include_router(extractions.router)
app.include_router(registry.router)
app.include_router(templates.router)


@app.get("/health")
def health():
    return {"ok": True, "llm": config.llm_enabled(), "tesseract": tess.available()}
