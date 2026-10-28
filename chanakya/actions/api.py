"""REST API for actions. Every call goes through the safety gate; mock systems are read-only here."""

from __future__ import annotations

from fastapi import APIRouter

from chanakya.actions.audit import audit_trail
from chanakya.core.schemas import ToolCall
from chanakya.missions.runtime import get_runtime

router = APIRouter(prefix="/api/actions", tags=["actions"])


@router.get("/tools")
async def list_tools() -> list[dict]:
    """Every registered tool with its kind and argument schema."""
    return [info.model_dump(mode="json") for info in get_runtime().registry.tools()]


@router.post("/submit")
async def submit(call: ToolCall) -> dict:
    """Run a tool call through the safety gate and return the decision."""
    decision = await get_runtime().submit(call)
    return decision.model_dump(mode="json")


@router.get("/audit/{mission_id}")
async def audit(mission_id: str) -> list[dict]:
    """Every attempted, blocked, failed and executed action for a mission."""
    return [d.model_dump(mode="json") for d in audit_trail(get_runtime().ledger.store, mission_id)]


@router.get("/merchants")
async def merchants() -> list[dict]:
    """Merchants in the mock CRM."""
    return get_runtime().db.all("SELECT * FROM merchants ORDER BY name")


@router.get("/outbox")
async def outbox(merchant_id: str | None = None, mission_id: str | None = None) -> list[dict]:
    """Messages the mock messaging system has sent, newest first."""
    rows = get_runtime().db.all("SELECT * FROM outbox ORDER BY at DESC, rowid DESC")
    return [r for r in rows if merchant_id in (None, r["merchant_id"]) and mission_id in (None, r["mission_id"])]
