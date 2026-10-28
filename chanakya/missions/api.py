"""REST and WebSocket API for missions. Mounted by ``backend/main.py`` when MISSIONS_ENABLED is true."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from chanakya.core.interfaces import IllegalTransitionError
from chanakya.core.schemas import EventKind, MerchantSignal, MissionState
from chanakya.missions.runtime import get_runtime
from chanakya.missions.signals import demo_feed

logger = logging.getLogger(__name__)

# Events the conversation side (voice session, brain, coach) may write directly.
CONVERSATION_EVENTS = {
    EventKind.TURN_COMPLETED, EventKind.BELIEF_UPDATED, EventKind.PLAN_COMPUTED, EventKind.AI_DISCLOSED,
    EventKind.CONSENT_GIVEN, EventKind.CONSENT_DECLINED, EventKind.NOTE,
}


@contextlib.asynccontextmanager
async def lifespan(app):
    """Run due follow-up jobs in the background while the server is up."""
    interval = float(os.getenv("CHANAKYA_TICK_SECONDS", "5"))

    async def loop():
        while True:
            await asyncio.sleep(interval)
            try:
                await get_runtime().verifier.run_due()
            except Exception:
                logger.exception("Follow-up run failed")

    task = asyncio.create_task(loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


router = APIRouter(prefix="/api/missions", tags=["missions"], lifespan=lifespan)


class AdvanceRequest(BaseModel):
    state: MissionState
    reason: str = ""
    outcome: str | None = None


class EventRequest(BaseModel):
    kind: EventKind
    payload: dict[str, Any] = Field(default_factory=dict)


class ClockRequest(BaseModel):
    minutes: float = Field(gt=0, le=60 * 24 * 14)


def _not_found(error: LookupError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(error))


@router.get("")
async def list_missions() -> list[dict]:
    """Every mission, newest first; waiting ones carry their queue status."""
    runtime = get_runtime()
    queue = {e.mission.id: e for e in runtime.queue.entries()}
    return [
        {"mission": m.model_dump(mode="json"),
         "queue": {"ready": queue[m.id].ready, "reason": queue[m.id].reason} if m.id in queue else None}
        for m in runtime.ledger.store.list()
    ]


@router.get("/queue/next")
async def next_mission() -> dict:
    """The mission to contact now, if any."""
    mission = get_runtime().queue.next_ready()
    return {"mission": mission.model_dump(mode="json") if mission else None}


@router.get("/clock")
async def clock() -> dict:
    """The mission clock (real time plus any demo fast-forward)."""
    return {"now": get_runtime().clock().isoformat()}


@router.post("/signals")
async def ingest_signal(signal: MerchantSignal) -> dict:
    """Open (or refresh) a mission from a signal through any of the three doors."""
    try:
        mission, created = await get_runtime().intake.ingest(signal)
    except LookupError as error:
        raise _not_found(error) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"mission": mission.model_dump(mode="json"), "created": created}


@router.post("/signals/demo-feed")
async def ingest_demo_feed() -> dict:
    """Load the simulated signal feed for the demo merchants."""
    runtime = get_runtime()
    created = 0
    for signal in demo_feed():
        _, new = await runtime.intake.ingest(signal)
        created += new
    return {"created": created, "missions": len(runtime.ledger.store.list())}


@router.post("/tick")
async def tick() -> dict:
    """Run due follow-up jobs now."""
    return {"jobs_run": len(await get_runtime().verifier.run_due())}


@router.post("/clock/advance")
async def advance_clock(request: ClockRequest) -> dict:
    """Demo fast-forward: move the clock and run whatever became due."""
    runtime = get_runtime()
    jobs = await runtime.fast_forward(timedelta(minutes=request.minutes))
    return {"now": runtime.clock().isoformat(), "jobs_run": jobs}


@router.get("/{mission_id}")
async def get_mission(mission_id: str) -> dict:
    """One mission with its full ledger."""
    runtime = get_runtime()
    mission = runtime.ledger.store.get(mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail=f"unknown mission {mission_id}")
    events = runtime.ledger.store.events(mission_id)
    return {"mission": mission.model_dump(mode="json"), "events": [e.model_dump(mode="json") for e in events]}


@router.post("/{mission_id}/advance")
async def advance_mission(mission_id: str, request: AdvanceRequest) -> dict:
    """Move a mission to a new state through the state machine."""
    try:
        mission = await get_runtime().ledger.advance(mission_id, request.state, request.reason, request.outcome)
    except LookupError as error:
        raise _not_found(error) from error
    except IllegalTransitionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"mission": mission.model_dump(mode="json")}


@router.post("/{mission_id}/events")
async def record_event(mission_id: str, request: EventRequest) -> dict:
    """Record a conversation event (turn, belief, plan, disclosure, consent or note)."""
    runtime = get_runtime()
    if runtime.ledger.store.get(mission_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown mission {mission_id}")
    if request.kind not in CONVERSATION_EVENTS:
        raise HTTPException(status_code=422, detail=f"{request.kind} is written by the system, not by clients")
    event = await runtime.ledger.record(mission_id, request.kind, request.payload)
    return {"event": event.model_dump(mode="json")}


@router.websocket("/stream")
async def stream(websocket: WebSocket, mission_id: str | None = Query(None), replay: int = Query(0, ge=0, le=500)):
    """Live ledger events; ``replay`` first sends up to that many recent events."""
    runtime = get_runtime()
    await websocket.accept()
    subscription = runtime.ledger.bus.subscribe(mission_id)
    try:
        if replay:
            for event in runtime.ledger.store.events(mission_id)[-replay:]:
                await websocket.send_json(event.model_dump(mode="json"))
        async for event in subscription:
            await websocket.send_json(event.model_dump(mode="json"))
    except WebSocketDisconnect:
        pass
    finally:
        await subscription.aclose()
