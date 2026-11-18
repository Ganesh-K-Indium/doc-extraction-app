import datetime as dt
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import JSON, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app import config


class Base(DeclarativeBase):
    pass


class Extraction(Base):
    __tablename__ = "extractions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | processing | done | failed
    stage: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    progress_done: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    template_choice: Mapped[str] = mapped_column(String(64), default="auto")  # auto | discover | a registered type
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    # reviewer edits: "{doc_index}:{field key}" -> value
    corrections: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)


_engine = None
_Session = None


def init_db() -> None:
    global _engine, _Session
    config.ensure_dirs()
    _engine = create_engine(config.DB_URL, connect_args={"check_same_thread": False} if config.DB_URL.startswith("sqlite") else {})
    Base.metadata.create_all(_engine)
    _add_missing_columns()
    _Session = sessionmaker(_engine, expire_on_commit=False)


def _add_missing_columns() -> None:
    """Small forward-only migration for databases created before a column existed."""
    from sqlalchemy import inspect, text
    have = {c["name"] for c in inspect(_engine).get_columns("extractions")}
    with _engine.begin() as conn:
        if "template_choice" not in have:
            conn.execute(text("ALTER TABLE extractions ADD COLUMN template_choice VARCHAR(64) DEFAULT 'auto'"))
        if "sha256" not in have:
            conn.execute(text("ALTER TABLE extractions ADD COLUMN sha256 VARCHAR(64)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_extractions_sha256 ON extractions (sha256)"))


def session():
    if _Session is None:
        init_db()
    return _Session()
