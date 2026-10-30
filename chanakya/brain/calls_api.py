"""Calls on real missions over HTTP: run a demo scenario, or speak as the merchant, and watch it on the dashboard.

Mounted with the mission APIs when MISSIONS_ENABLED is true. Every turn goes through ``MissionCall``, so the ledger,
the safety gate and the Live Call View see exactly what a phone call would produce.
"""

import asyncio
import os

from fastapi import APIRouter, HTTPException, WebSocket
from pydantic import BaseModel, Field

from chanakya.brain.contracts.llm import default_llm
from chanakya.brain.mission_call import MissionCall
from chanakya.brain.scenarios import SCENARIOS, WINBACK_SCENARIOS, open_mission, run_scenario
from chanakya.core import schemas as core
from chanakya.core.config import Settings
from chanakya.missions.runtime import get_runtime

router = APIRouter(prefix="/api/calls", tags=["calls"])
calls: dict[str, MissionCall] = {}
running: set[asyncio.Task] = set()
scenario_running: set[str] = set()  # missions a scenario is playing on; nobody else may speak on them meanwhile
SCENARIO_BUSY = "A demo scenario is playing on this mission; wait for it to finish."
PAUSE_S = 1.5  # time between lines when a scenario plays on the dashboard, so it can be followed live


class Utterance(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    language: str | None = None


def _llm():
    """The configured LLM when its key is set; otherwise Chanakya speaks from its templates."""
    settings = Settings.from_env()
    return default_llm(settings) if settings.llm_api_key else None


@router.get("/scenarios")
async def scenarios() -> list[dict]:
    """The demo scenarios the dashboard can run (win-back ones only with WINBACK_ENABLED)."""
    return [{"name": s.name, "title": s.title, "merchant_id": s.merchant_id} for s in SCENARIOS.values()
            if s.name in _available()]


def _available() -> set[str]:
    names = set(SCENARIOS)
    return names if get_runtime().settings.winback_enabled else names - WINBACK_SCENARIOS


@router.post("/scenarios/{name}")
async def start_scenario(name: str) -> dict:
    """Open the scenario's mission and play it in the background; returns the mission to watch."""
    if name not in _available():
        raise HTTPException(status_code=404, detail="unknown scenario")
    runtime = get_runtime()
    mission = await open_mission(runtime, SCENARIOS[name])
    if (mission.state not in {core.MissionState.CREATED, core.MissionState.SCHEDULED} or mission.id in calls
            or mission.id in scenario_running):
        raise HTTPException(status_code=409, detail=f"{mission.card.merchant_name} already has a mission in "
                                                    f"{mission.state.value}; finish it first")
    scenario_running.add(mission.id)
    task = asyncio.create_task(run_scenario(runtime, name, llm=_llm(), pause=PAUSE_S, mission=mission))
    running.add(task)
    task.add_done_callback(running.discard)
    task.add_done_callback(lambda _: scenario_running.discard(mission.id))
    return {"mission_id": mission.id}


@router.get("/{mission_id}/status")
async def status(mission_id: str) -> dict:
    """Whether a demo scenario is playing on this mission (the Live Call View hides its inputs meanwhile)."""
    return {"scenario_running": mission_id in scenario_running}


async def _call(mission_id: str) -> MissionCall:
    """The running call on this mission, started on first use. Refused while a scenario plays on it."""
    if mission_id in scenario_running:
        raise HTTPException(status_code=409, detail=SCENARIO_BUSY)
    runtime = get_runtime()
    mission = runtime.ledger.store.get(mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="unknown mission")
    call = calls.get(mission_id)
    if call is None:
        if not mission.is_open:
            raise HTTPException(status_code=409, detail=f"mission is {mission.state.value}")
        call = calls[mission_id] = MissionCall(runtime, mission_id, llm=_llm())
        await call.start()
    return call


@router.post("/{mission_id}/say")
async def say(mission_id: str, utterance: Utterance) -> dict:
    """The merchant says something on this mission's call; returns Chanakya's reply (None once the call is over)."""
    call = await _call(mission_id)
    reply = await call.say(utterance.text, utterance.language)
    if not call.open:
        calls.pop(mission_id, None)
    return {"reply": reply, "state": call.mission.state.value}


@router.websocket("/{mission_id}/voice")
async def voice(websocket: WebSocket, mission_id: str) -> None:
    """A spoken call on this mission: the browser voice protocol, with Chanakya answering through ``MissionCall``."""
    problem = None
    if mission_id in scenario_running:
        problem = SCENARIO_BUSY
    elif not Settings.from_env().llm_api_key or not os.getenv("SARVAM_API_KEY", "").strip():
        problem = "Voice is not configured yet. Add the provider keys to the server's .env file and restart the backend."
    else:
        try:
            call = await _call(mission_id)
        except HTTPException as error:
            problem = error.detail
    if problem:
        await websocket.accept()
        await websocket.send_json({"type": "voice_error", "message": problem})
        await websocket.close(code=1013)
        return
    from backend.voice_pipeline import voice_pipeline  # the inherited voice stack loads speech clients on import

    try:
        await voice_pipeline(websocket, call, "llm_batch")
    finally:
        if not call.open:
            calls.pop(mission_id, None)
