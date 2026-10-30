from datetime import UTC, datetime

from chanakya.brain.mission_call import MissionCall
from chanakya.core.config import Settings
from chanakya.missions.runtime import Runtime
from chanakya.missions.scheduler import SimClock


def test_a_mission_call_planner_gets_both_the_memory_and_the_value_setting(tmp_path):
    settings = Settings(db_path=tmp_path / "ledger.db", planner_memory="forest", planner_value="network")
    runtime = Runtime.build(settings, clock=SimClock(datetime(2026, 10, 31, 10, tzinfo=UTC)))
    planner = MissionCall(runtime, "mis_any").agent.planner
    assert planner.forest is not None and planner.leaf_value is not None

    runtime = Runtime.build(Settings(db_path=tmp_path / "other.db"), clock=SimClock(datetime(2026, 10, 31, 10, tzinfo=UTC)))
    assert MissionCall(runtime, "mis_any").agent.planner.leaf_value is None  # the formula stays the default


def test_ledger_beliefs_say_which_scorer_read_the_line_and_what_it_found(tmp_path):
    import asyncio

    from chanakya.brain.scenarios import SCENARIOS, open_mission
    from chanakya.core.schemas import EventKind

    runtime = Runtime.build(Settings(db_path=tmp_path / "ledger.db"), clock=SimClock(datetime(2026, 10, 29, 9, 30, tzinfo=UTC)))

    async def go():
        mission = await open_mission(runtime, SCENARIOS["callback_followup"])
        call = MissionCall(runtime, mission.id)
        await call.start()
        await call.say("Rent kitna lagega mahine ka?")
        return mission.id

    mission_id = asyncio.run(go())
    beliefs = [e.payload for e in runtime.ledger.store.events(mission_id) if e.kind == EventKind.BELIEF_UPDATED]
    assert beliefs[-1]["scorer"] == "lexical" and beliefs[-1]["evidence"]
