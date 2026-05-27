"""Read-only Wiii Connect registry endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.engine.wiii_connect import provider_registry_public_metadata


router = APIRouter(prefix="/wiii-connect", tags=["wiii-connect"])


@router.get("/providers")
async def list_wiii_connect_providers() -> dict[str, object]:
    """Return the privacy-safe Wiii Connect provider catalog."""

    return provider_registry_public_metadata()
