"""Demo tool: Reset puts a mission back in the queue for another run. Laptop only, behind DEMO_TOOLS_ENABLED.

The ledger stays append-only: the old run keeps its events, is closed (or marked) with outcome "reset" and a note
naming its replacement, and a fresh copy of the mission opens in the queue. The mock systems drop the rows the old
run wrote, and the merchant's products go back to the seed, so a sale that ended in onboarding can be sold again.
"""

from fastapi import APIRouter, HTTPException, Request

from backend.phone_link import require_laptop
from chanakya.actions.systems.seed import FORMER_MERCHANTS, MERCHANTS
from chanakya.brain.calls_api import calls, scenario_running
from chanakya.core.schemas import EventKind, Mission, MissionState
from chanakya.missions.runtime import get_runtime

RESET = "reset"
# Mock tables whose rows carry the mission that wrote them.
MISSION_TABLES = ("interactions", "outbox", "onboarding_sessions", "field_visits", "callbacks", "tickets")
SEED_PRODUCTS = {m[0]: (m[7], m[8]) for m in MERCHANTS} | {m[0]: (0, 0) for m in FORMER_MERCHANTS}


def reset_mock_systems(db, mission: Mission) -> None:
    """Remove what this mission's run wrote to the mock systems and restore the merchant's seeded products."""
    merchant_id = mission.card.merchant_id
    for table in MISSION_TABLES:
        db.write(f"DELETE FROM {table} WHERE mission_id = ?", mission.id)  # table names from the fixed list above
    db.write("DELETE FROM leads WHERE merchant_id = ? AND created_at >= ?", merchant_id, mission.created_at.isoformat())
    if merchant_id in SEED_PRODUCTS:
        soundbox, card_machine = SEED_PRODUCTS[merchant_id]
        db.write("UPDATE merchants SET has_soundbox = ?, has_card_machine = ? WHERE id = ?",
                 soundbox, card_machine, merchant_id)


async def reset_mission(runtime, mission_id: str) -> Mission:
    """Retire ``mission_id`` and open a fresh copy of it in the queue. Returns the new mission."""
    old = runtime.ledger.store.get(mission_id)
    if old is None:
        raise LookupError(f"unknown mission {mission_id}")
    if mission_id in scenario_running:
        raise ValueError("A demo scenario is playing on this mission; wait for it to finish.")
    runtime.scheduler.cancel_all(mission_id)
    calls.pop(mission_id, None)
    if old.is_open:
        await runtime.ledger.close(mission_id, MissionState.FAILED, outcome=RESET)
    else:
        runtime.ledger.store.save(runtime.ledger.store.get(mission_id).model_copy(update={"outcome": RESET}))
    reset_mock_systems(runtime.db, old)
    signal = next((e.payload for e in runtime.ledger.store.events(mission_id) if e.kind == EventKind.SIGNAL_RECEIVED), {})
    new = await runtime.ledger.create(old.card)
    await runtime.ledger.record(new.id, EventKind.SIGNAL_RECEIVED, signal)
    await runtime.ledger.record(mission_id, EventKind.NOTE, {
        "text": "Reset for another demo run", "replaced_by": new.id,
        "previous_state": old.state.value, "previous_outcome": old.outcome,
    })
    return new


router = APIRouter(prefix="/api/demo-tools", tags=["demo"])


@router.post("/missions/{mission_id}/reset")
async def reset(mission_id: str, request: Request) -> dict:
    """Put a mission back in the queue: the old run is kept but hidden, and a fresh copy waits to be called."""
    require_laptop(request)
    try:
        new = await reset_mission(get_runtime(), mission_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    return {"mission_id": new.id, "replaced": mission_id}
