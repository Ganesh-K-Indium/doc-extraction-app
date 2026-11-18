from fastapi import Header, HTTPException

from app import config, db


def require_key(x_api_key: str = Header(default="")) -> None:
    if config.API_KEY and x_api_key != config.API_KEY:
        raise HTTPException(401, "Missing or invalid API key.")


def workspace(workspace_id: str) -> str:
    """Path dependency: the workspace must exist. Everything else (documents, types) is looked up inside it."""
    with db.session() as s:
        if s.get(db.Workspace, workspace_id) is None:
            raise HTTPException(404, "Workspace not found.")
    return workspace_id
