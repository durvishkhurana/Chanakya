"""REST API for the human hand-off queue."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from chanakya.core.interfaces import IllegalTransitionError
from chanakya.core.schemas import HandoffStatus
from chanakya.missions.runtime import get_runtime

router = APIRouter(prefix="/api/handoffs", tags=["handoffs"])


class EscalateRequest(BaseModel):
    mission_id: str
    reason: str = Field(min_length=1, max_length=300)
    urgent: bool = False


class ClaimRequest(BaseModel):
    agent: str = Field(min_length=1, max_length=80)


class ResolveRequest(BaseModel):
    resolution: str = Field(min_length=1, max_length=1000)


async def _call(coro):
    try:
        return (await coro).model_dump(mode="json")
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (IllegalTransitionError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("")
async def list_handoffs(status: HandoffStatus | None = None) -> list[dict]:
    """Hand-off cards, urgent first."""
    return [card.model_dump(mode="json") for card in get_runtime().handoffs.list(status)]


@router.post("/escalate")
async def escalate(request: EscalateRequest) -> dict:
    """Hand a mission to a human with a full context card."""
    return await _call(get_runtime().handoffs.escalate(request.mission_id, request.reason, request.urgent))


@router.post("/{handoff_id}/claim")
async def claim(handoff_id: str, request: ClaimRequest) -> dict:
    """A human takes the hand-off."""
    return await _call(get_runtime().handoffs.claim(handoff_id, request.agent))


@router.post("/{handoff_id}/resolve")
async def resolve(handoff_id: str, request: ResolveRequest) -> dict:
    """The human closes the hand-off."""
    return await _call(get_runtime().handoffs.resolve(handoff_id, request.resolution))
