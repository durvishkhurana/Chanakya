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
