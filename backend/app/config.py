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
    return Path(os.getenv("DATA_DIR", "./data")).resolve() / "templates"


def custom_types_file() -> Path:
    return Path(os.getenv("DATA_DIR", "./data")).resolve() / "custom_types.json"


def llm_enabled() -> bool:
    return os.getenv("LLM_ENABLED", "1").lower() not in ("0", "false", "no") and bool(os.getenv("OPENAI_API_KEY"))


def extraction_models() -> list:
    raw = os.getenv("EXTRACTION_MODELS", "gpt-4.1,gpt-4.1-mini")
    return [m.strip() for m in raw.split(",") if m.strip()][:2]


def ensure_dirs() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    templates_dir().mkdir(parents=True, exist_ok=True)
