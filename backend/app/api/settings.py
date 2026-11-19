"""
Server settings: model provider keys and addresses.

    GET /api/settings/providers           every provider with its fields: whether each is set, where it came from, a masked preview
    PUT /api/settings/providers/{id}      save values ({"values": {"NAME": "value"}}; null removes a saved value, "" leaves it alone)

Keys are stored encrypted (engines/credentials.py) and are never returned. The whole screen is read-only when LOCK_SETTINGS=1.
"""
import logging
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import config
from app.api.deps import require_key
from app.engines import credentials, llm

logger = logging.getLogger("app.api.settings")
router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_key)])


def provider_view(p: dict) -> dict:
    return {**p, "fields": credentials.view(p["id"])}


@router.get("/providers")
def providers():
    return {"locked": credentials.locked(), "encryption": "ok" if credentials.encryption_ok() else "unavailable",
            "local_only": config.local_only(), "providers": [provider_view(p) for p in llm.providers_status()]}


class ProviderIn(BaseModel):
    values: Dict[str, Optional[str]]


@router.put("/providers/{provider_id}")
def save_provider(provider_id: str, body: ProviderIn):
    if credentials.locked():
        raise HTTPException(403, "Settings are locked on this server. Ask whoever runs it to change them.")
    if provider_id not in llm.PROVIDERS:
        raise HTTPException(404, "No such provider.")
    allowed = {f.name for f in credentials.FIELDS[provider_id]}
    changes = {k: v for k, v in body.values.items() if v != ""}          # an empty box means "leave it as it is"
    if any(k not in allowed for k in changes):
        raise HTTPException(422, "That setting does not belong to this provider.")
    try:
        credentials.save(changes)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except credentials.StorageError as e:
        raise HTTPException(503, str(e))
    logger.info("Provider settings changed for %s (%s)", provider_id, ", ".join(sorted(changes)))   # names only, never values
    return next(provider_view(p) for p in llm.providers_status() if p["id"] == provider_id)
