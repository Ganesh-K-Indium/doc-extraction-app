import datetime as dt
import json
import logging
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app import config


class Base(DeclarativeBase):
    pass


logger = logging.getLogger("app.db")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class Workspace(Base):
    """An independent container: its own documents and its own custom document types."""
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class CustomType(Base):
    """A document type a user added to ONE workspace (drafted from a blank form, or saved from an extraction)."""
    __tablename__ = "custom_types"
    __table_args__ = (UniqueConstraint("workspace_id", "doc_type", name="uq_custom_type"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    doc_type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    template: Mapped[Dict[str, Any]] = mapped_column(JSON)
    entry: Mapped[Dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class Extraction(Base):
    __tablename__ = "extractions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | processing | done | failed
    stage: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    progress_done: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    template_choice: Mapped[str] = mapped_column(String(64), default="auto")  # auto | discover | a registered type
    read_rest: Mapped[bool] = mapped_column(Boolean, default=False)  # also read what templates do not cover
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
    _migrate_legacy()


def _add_missing_columns() -> None:
    """Small forward-only migration for databases created before a column existed."""
    from sqlalchemy import inspect, text
    have = {c["name"] for c in inspect(_engine).get_columns("extractions")}
    with _engine.begin() as conn:
        if "template_choice" not in have:
            conn.execute(text("ALTER TABLE extractions ADD COLUMN template_choice VARCHAR(64) DEFAULT 'auto'"))
        if "read_rest" not in have:
            conn.execute(text("ALTER TABLE extractions ADD COLUMN read_rest BOOLEAN DEFAULT 0"))
        if "workspace_id" not in have:
            conn.execute(text("ALTER TABLE extractions ADD COLUMN workspace_id VARCHAR(36)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_extractions_workspace_id ON extractions (workspace_id)"))
        if "sha256" not in have:
            conn.execute(text("ALTER TABLE extractions ADD COLUMN sha256 VARCHAR(64)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_extractions_sha256 ON extractions (sha256)"))


def _migrate_legacy() -> None:
    """Before workspaces, documents and custom types were global. Move whatever exists into one 'My workspace' so
    nothing is lost. A fresh install has nothing to move and gets no workspace (the first screen offers to create one)."""
    old_file = config.custom_types_file()
    legacy: list = []
    try:
        for entry in json.loads(old_file.read_text()):
            tpl_path = config.templates_dir() / f"{entry.get('type')}.json"
            if isinstance(entry, dict) and entry.get("type") and tpl_path.is_file():
                legacy.append((entry, json.loads(tpl_path.read_text())))
    except (OSError, ValueError):
        legacy = []
    with session() as s:
        orphans = s.query(Extraction).filter(Extraction.workspace_id.is_(None)).all()
        if not orphans and not legacy:
            return
        ws = s.query(Workspace).filter(Workspace.name == "My workspace").first()
        if ws is None:
            ws = Workspace(name="My workspace", description="Documents and document types from before workspaces existed.")
            s.add(ws)
            s.flush()
        for e in orphans:
            e.workspace_id = ws.id
        for entry, tpl in legacy:
            if not s.query(CustomType).filter_by(workspace_id=ws.id, doc_type=entry["type"]).first():
                s.add(CustomType(workspace_id=ws.id, doc_type=entry["type"], title=tpl.get("title") or entry["type"], template=tpl, entry=entry))
        s.commit()
    if legacy:
        try:
            old_file.rename(old_file.with_suffix(".json.migrated"))
        except OSError:
            logger.warning("Could not rename %s after migrating it", old_file)
    logger.info("Moved %d document(s) and %d custom type(s) into 'My workspace'", len(orphans), len(legacy))


def session():
    if _Session is None:
        init_db()
    return _Session()
