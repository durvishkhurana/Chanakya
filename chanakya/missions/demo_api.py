"""Endpoints behind the mock product page and the mock onboarding page. Both pages are labelled mocks."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from chanakya.actions.systems.tools import complete_onboarding, resolve_ticket
from chanakya.missions.runtime import get_runtime

router = APIRouter(prefix="/api/demo", tags=["demo"])


def _session(session_id: str) -> dict:
    runtime = get_runtime()
    session = runtime.db.one("SELECT * FROM onboarding_sessions WHERE id = ?", session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown onboarding session")
    merchant = runtime.db.one("SELECT name, city, language FROM merchants WHERE id = ?", session["merchant_id"])
    return {"session": session, "merchant": merchant}


@router.get("/onboarding/{session_id}")
async def onboarding(session_id: str) -> dict:
    """What the mock onboarding page shows: the merchant, the product and the session status."""
    return _session(session_id)


@router.post("/onboarding/{session_id}/complete")
async def complete(session_id: str) -> dict:
    """The merchant finishes the mock onboarding; any mission waiting on it is verified at once."""
    _session(session_id)
    complete_onboarding(get_runtime().db, session_id)
    verified = await get_runtime().verifier.check_now(session_id)
    return _session(session_id) | {"verified_missions": verified}


@router.post("/tickets/{ticket_id}/resolve")
async def resolve(ticket_id: str) -> dict:
    """The mock ticketing team fixes the issue; any win-back mission waiting on the ticket is verified at once."""
    runtime = get_runtime()
    try:
        ticket = resolve_ticket(runtime.db, ticket_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"ticket": ticket, "verified_missions": await runtime.verifier.check_winback_now(ticket_id)}
