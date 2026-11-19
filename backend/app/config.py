import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(os.getenv("DATA_DIR", "./data")).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
DB_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'extractions.db'}")
API_KEY = os.getenv("APP_API_KEY", "")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "50")) * 1024 * 1024
MAX_PAGES = int(os.getenv("MAX_PAGES", "200"))


def templates_dir() -> Path:
    """Legacy location of custom templates from before workspaces; read only when migrating."""
    return Path(os.getenv("DATA_DIR", "./data")).resolve() / "templates"


def custom_types_file() -> Path:
    return Path(os.getenv("DATA_DIR", "./data")).resolve() / "custom_types.json"


def llm_enabled() -> bool:
    return os.getenv("LLM_ENABLED", "1").lower() not in ("0", "false", "no") and bool(os.getenv("OPENAI_API_KEY"))


def extraction_models() -> list:
    raw = os.getenv("EXTRACTION_MODELS", "gpt-4.1,gpt-4.1-mini")
    return [m.strip() for m in raw.split(",") if m.strip()][:2]


def adjudicator_model() -> str:
    """Model for the third look at disputed values (see services/adjudicate.py). Empty when no model is available.
    Defaults to the primary extraction model: it is called once per page that has a dispute, never for pages that agree."""
    if not llm_enabled():
        return ""
    return os.getenv("ADJUDICATION_MODEL", "").strip() or (extraction_models() or [""])[0]


PIPELINE_VERSION = "2026.11-handwriting-discovery-v2"  # bump when extraction behaviour changes: older cached results are then not reused


def long_doc_pages() -> int:
    """Digital documents longer than this are read once per page (primary model only) instead of by two readers."""
    return int(os.getenv("DISCOVER_LONG_DOC_PAGES", "25"))


def digital_model_mode() -> str:
    """When a model reads a digital (text-layer) page with no template: "auto" (default) only for form-like pages code could
    not make sense of, "never" (code only), "always" (every digital page)."""
    v = os.getenv("DISCOVER_DIGITAL_MODEL", "auto").strip().lower()
    return v if v in ("auto", "never", "always") else "auto"


def classify_give_up_after() -> int:
    """The classifier model is only a second opinion for pages the keyword rules could not name. After this many in a row
    that it also could not name, stop asking: the rest of a long untyped document is not going to be a known form."""
    return int(os.getenv("CLASSIFY_UNKNOWN_STREAK", "3"))


def ensure_dirs() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
