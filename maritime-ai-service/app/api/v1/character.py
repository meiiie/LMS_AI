"""
Character State API — Sprint 120
GET /api/v1/character/state — returns Wiii's character blocks for UI display.

Exposes the internal CharacterStateManager to the desktop app.
Feature-gated: settings.enable_character_tools (default: True)
"""
import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from typing import List

from app.api.deps import RequireAuth
from app.core.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/character", tags=["character"])


class CharacterBlockResponse(BaseModel):
    """A single character block."""
    label: str
    content: str = ""
    char_limit: int = 1000
    usage_percent: float = Field(0.0, description="Percentage of char_limit used")


class CharacterCardResponse(BaseModel):
    """Immutable + live Wiii character card snapshot."""

    card_id: str = "wiii.living-core.v1"
    card_name: str = "Wiii Living Core Card"
    card_kind: str = "living_core"
    card_family: str = "core"
    contract_version: str = "1.0"
    name: str = "Wiii"
    summary: str = ""
    origin: str = ""
    greeting: str = ""
    traits: List[str] = Field(default_factory=list)
    quirks: List[str] = Field(default_factory=list)
    core_truths: List[str] = Field(default_factory=list)
    reasoning_style: List[str] = Field(default_factory=list)
    relationship_style: List[str] = Field(default_factory=list)
    anti_drift: List[str] = Field(default_factory=list)
    runtime_notes: List[str] = Field(default_factory=list)


class CharacterStateResponse(BaseModel):
    """Full character state response."""
    blocks: List[CharacterBlockResponse] = []
    total_blocks: int = 0
    card: CharacterCardResponse | None = None


@router.get("/state", response_model=CharacterStateResponse)
@limiter.limit("30/minute")
async def get_character_state(
    request: Request,
    auth: RequireAuth,
) -> CharacterStateResponse:
    """
    Get Wiii's current character state (all blocks).

    Returns character blocks with content and usage statistics.
    Feature-gated: requires enable_character_tools=True.
    """
    try:
        from app.core.config import settings
        if not settings.enable_character_tools:
            return CharacterStateResponse()

        from app.engine.character.character_state import get_character_state_manager
        manager = get_character_state_manager()
        # Sprint 124: Per-user character blocks
        blocks_dict = manager.get_blocks(
            user_id=str(auth.user_id),
            organization_id=auth.organization_id,
        )

        blocks = []
        for label, block in blocks_dict.items():
            content_len = len(block.content) if block.content else 0
            char_limit = block.char_limit or 1000
            usage = min((content_len / char_limit) * 100, 100.0) if char_limit > 0 else 0.0
            blocks.append(CharacterBlockResponse(
                label=label,
                content=block.content or "",
                char_limit=char_limit,
                usage_percent=round(usage, 1),
            ))

        card_payload = None
        try:
            from app.engine.character.character_card import build_character_card_payload

            card_payload = CharacterCardResponse(
                **build_character_card_payload(
                    user_id=str(auth.user_id),
                    organization_id=auth.organization_id,
                )
            )
        except Exception as exc:
            logger.debug("[CHARACTER_API] Card payload unavailable: %s", exc)

        return CharacterStateResponse(
            blocks=blocks,
            total_blocks=len(blocks),
            card=card_payload,
        )
    except Exception as e:
        logger.warning("[CHARACTER_API] Failed to get state: %s", e)
        return CharacterStateResponse()
