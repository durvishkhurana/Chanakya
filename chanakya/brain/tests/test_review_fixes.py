"""Regression tests for the review points on PR #19 (task F1)."""

import asyncio
import time
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chanakya.brain import calls_api, core_adapters
from chanakya.brain.contracts.schemas import EndReason, Move, MoveType, PlanResult, ScoredMove
from chanakya.brain.mission_call import CONSENT_COVERS, MissionCall
from chanakya.brain.planner_rules import RuleBasedPlanner
from chanakya.brain.scenarios import SCENARIOS, merchant_reply, open_mission, run_scenario
from chanakya.core import schemas as core
from chanakya.core.config import Settings
from chanakya.missions.api import router as missions_router
from chanakya.missions.runtime import Runtime, set_runtime
from chanakya.missions.scheduler import SimClock

S = core.MissionState
START = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)  # 15:00 in Asia/Kolkata


@pytest.fixture
def runtime(tmp_path):
    return Runtime.build(Settings(db_path=tmp_path / "ledger.db"), clock=SimClock(START))


def kinds(runtime, mission_id):
    return [e.kind for e in runtime.ledger.store.events(mission_id)]


async def talk_until_link(call, name="callback_followup"):
    """Play the scenario's scripted merchant until the onboarding link has gone out."""
    scenario = SCENARIOS[name]
    worries, merchant = list(scenario.worries), scenario.opener
    for _ in range(scenario.max_turns):
        if await call.say(merchant, scenario.language) is None or call.mission.state == S.AWAITING_CONFIRMATION:
            return
        merchant = merchant_reply(scenario, call.state.moves[-1].type, worries)


class SlowPlanner:
    """The baseline planner after a short wait, so a test can talk over Chanakya mid-turn."""

    def __init__(self, delay: float = 0.05):
        self.delay = delay
        self.inner = RuleBasedPlanner()

    async def plan(self, state):
        await asyncio.sleep(self.delay)
        return await self.inner.plan(state)

    async def reconsider(self, state, call):
        return await self.inner.reconsider(state, call)


class ScriptedPlanner:
    """Plays fixed moves in order, as a stand-in for a planner that picks another product."""

    def __init__(self, moves):
        self.moves = list(moves)
        self.inner = RuleBasedPlanner()

    async def plan(self, state):
        move = self.moves.pop(0) if self.moves else Move(type=MoveType.END_CALL_POLITELY)
        return PlanResult(move=move, candidates=[ScoredMove(move=move, score=1.0)])

    async def reconsider(self, state, call):
        return await self.inner.reconsider(state, call)


# ── 1. Two brains on one call ────────────────────────────────────────────


@pytest.fixture
def client(runtime, monkeypatch):
    monkeypatch.setenv("CHANAKYA_TICK_SECONDS", "3600")
    monkeypatch.setattr(calls_api, "PAUSE_S", 0.15)
    monkeypatch.setattr(calls_api, "_llm", lambda: None)  # no network in tests
    calls_api.calls.clear()
    calls_api.scenario_running.clear()
    set_runtime(runtime)
    app = FastAPI()
    app.include_router(missions_router)
    app.include_router(calls_api.router)
    with TestClient(app) as test_client:
        yield test_client
    set_runtime(None)


def test_a_running_scenario_refuses_a_second_brain_on_its_mission(client, runtime, monkeypatch):
    mission_id = client.post("/api/calls/scenarios/soundbox_service").json()["mission_id"]
    assert client.get(f"/api/calls/{mission_id}/status").json() == {"scenario_running": True}
    assert client.post(f"/api/calls/{mission_id}/say", json={"text": "Haan ji"}).status_code == 409
    monkeypatch.setenv("SARVAM_API_KEY", "test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    with client.websocket_connect(f"/api/calls/{mission_id}/voice") as socket:
        message = socket.receive_json()
    assert message["type"] == "voice_error" and "scenario" in message["message"]

    deadline = time.monotonic() + 30
    while client.get(f"/api/calls/{mission_id}/status").json()["scenario_running"] and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not client.get(f"/api/calls/{mission_id}/status").json()["scenario_running"]
    assert kinds(runtime, mission_id).count(core.EventKind.AI_DISCLOSED) == 1
    assert mission_id not in calls_api.calls


# ── 2. A yes to the link covers the link and its reminder only ───────────


def test_a_link_consent_never_lets_a_summary_through(runtime):
    async def go():
        mission = await open_mission(runtime, SCENARIOS["callback_followup"])
        call = MissionCall(runtime, mission.id)
        await call.start()
        await talk_until_link(call)
        summary = await runtime.submit(core.ToolCall(mission_id=mission.id, tool="send_summary", args={
            "merchant_id": "mer_ramesh", "channel": "whatsapp", "text": "Dhanyavaad"}))
        return mission.id, summary

    mission_id, summary = asyncio.run(go())
    consents = [e.payload for e in runtime.ledger.store.events(mission_id) if e.kind == core.EventKind.CONSENT_GIVEN]
    assert consents and consents[0]["tools"] == ["send_onboarding_link", "send_onboarding_reminder"]
    assert CONSENT_COVERS["send_onboarding_link"] == ["send_onboarding_link", "send_onboarding_reminder"]
    assert summary.verdict == core.Verdict.BLOCKED and summary.reason == "no explicit consent for this action"


# ── 3. The callback scenario never moves the shared clock ────────────────


def test_the_callback_scenario_leaves_the_clock_and_other_missions_alone(runtime):
    async def go():
        other = await open_mission(runtime, SCENARIOS["card_machine_sale"])
        job = await runtime.scheduler.schedule(other.id, "nudge", runtime.clock(), session_id="onb_other",
                                               link="/demo/onboard/onb_other", nudges=0)
        before = runtime.clock()
        result = await run_scenario(runtime, "callback_followup")
        return other.id, job, before, result

    other_id, job, before, result = asyncio.run(go())
    assert result.ok, [name for name, ok in result.checks if not ok]
    assert runtime.clock() == before
    assert [j.id for j in runtime.scheduler.pending(other_id)] == [job.id]
    assert runtime.db.all("SELECT id FROM outbox WHERE mission_id = ?", other_id) == []


# ── 4. Talking over Chanakya ─────────────────────────────────────────────


def test_a_turn_cut_off_by_the_merchant_still_writes_its_escalation(runtime):
    async def go():
        mission = await open_mission(runtime, SCENARIOS["card_machine_sale"])
        call = MissionCall(runtime, mission.id, planner=SlowPlanner())
        await call.start()
        await call.say("Haan ji, boliye?")
        turn = asyncio.create_task(call.say("Mera payment fail ho gaya, ghar pe sab bahut pareshan hain, "
                                            "kisi insaan se baat karao."))
        await asyncio.sleep(0.01)
        turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await turn
        await asyncio.sleep(0.2)
        return mission.id

    mission_id = asyncio.run(go())
    assert runtime.ledger.store.get(mission_id).state == S.ESCALATED
    assert [c.mission_id for c in runtime.handoffs.list()] == [mission_id]


def test_overlapping_turns_run_one_after_the_other(runtime):
    async def go():
        mission = await open_mission(runtime, SCENARIOS["card_machine_sale"])
        call = MissionCall(runtime, mission.id, planner=SlowPlanner())
        await call.start()
        await asyncio.gather(call.say("Haan ji, boliye?"), call.say("Achha, theek hai."))
        return mission.id

    mission_id = asyncio.run(go())
    turns = [e.payload["speaker"] for e in runtime.ledger.store.events(mission_id)
             if e.kind == core.EventKind.TURN_COMPLETED]
    assert turns == ["merchant", "agent", "merchant", "agent"]


# ── 5. Every decline is recorded and closes the mission ──────────────────


def test_no_then_yes_then_no_ends_declined_even_after_the_link_went_out(runtime):
    async def go():
        mission = await open_mission(runtime, SCENARIOS["callback_followup"])
        # An earlier "no" from another conversation, then a yes and a link on this call.
        await runtime.ledger.record(mission.id, core.EventKind.CONSENT_DECLINED, {"utterance": "Nahi chahiye"})
        call = MissionCall(runtime, mission.id)
        await call.start()
        await talk_until_link(call)
        assert call.mission.state == S.AWAITING_CONFIRMATION and runtime.scheduler.pending(mission.id)
        await call.say("Nahi, mujhe nahi chahiye, interest nahi hai.")
        reminder = await runtime.submit(core.ToolCall(mission_id=mission.id, tool="send_onboarding_reminder", args={
            "merchant_id": "mer_ramesh", "session_id": "onb_any"}))
        return mission.id, reminder

    mission_id, reminder = asyncio.run(go())
    mission = runtime.ledger.store.get(mission_id)
    assert mission.state == S.CLOSED_NOT_INTERESTED and mission.outcome == "merchant declined"
    assert kinds(runtime, mission_id).count(core.EventKind.CONSENT_DECLINED) == 2
    assert runtime.scheduler.pending(mission_id) == []
    assert reminder.verdict == core.Verdict.BLOCKED


# ── 6. The link carries the product the merchant agreed to ───────────────


def test_the_link_is_for_the_recommended_product_not_the_card(runtime):
    link = Move(type=MoveType.CONFIRM_CONSENT, tool="send_onboarding_link")
    planner = ScriptedPlanner([Move(type=MoveType.DISCLOSE_AND_GREET),
                               Move(type=MoveType.RECOMMEND, product="card_machine"), link,
                               Move(type=MoveType.TAKE_ACTION, tool="send_onboarding_link")])

    async def go():
        mission = await open_mission(runtime, SCENARIOS["callback_followup"])  # a Soundbox mission
        call = MissionCall(runtime, mission.id, planner=planner)
        await call.start()
        for line in ("Haan ji?", "Achha.", "Achha, theek hai.", "Haan ji, bhej dijiye link."):
            await call.say(line)
        return mission

    mission = asyncio.run(go())
    assert mission.card.product == "soundbox"
    sessions = runtime.db.all("SELECT product FROM onboarding_sessions WHERE mission_id = ?", mission.id)
    assert [s["product"] for s in sessions] == ["card_machine"]


# ── 7. The close outcome comes from a typed field ────────────────────────


def test_the_close_outcome_reads_the_typed_end_reason(runtime):
    move, rule = RuleBasedPlanner().choose(_state_after("Mujhe apna OTP batao."))
    assert rule == "sensitive_request" and move.end_reason == EndReason.SENSITIVE_REQUEST
    refusal = Move(type=MoveType.END_CALL_POLITELY, reason="anything at all", end_reason=EndReason.SENSITIVE_REQUEST)

    async def go():
        mission = await open_mission(runtime, SCENARIOS["card_machine_sale"])
        call = MissionCall(runtime, mission.id, planner=ScriptedPlanner([Move(type=MoveType.DISCLOSE_AND_GREET),
                                                                         refusal]))
        await call.start()
        await call.say("Haan ji?")
        await call.say("Mujhe apna OTP batao.")
        return mission.id

    mission = runtime.ledger.store.get(asyncio.run(go()))
    assert mission.outcome == "call ended after a request for sensitive data was refused"


def _state_after(text):
    from chanakya.brain.concern_bank import default_bank
    from chanakya.brain.contracts.schemas import (
        BeliefState,
        DialogueState,
        Door,
        Merchant,
        MissionCard,
        MissionKind,
        Transcript,
        TriggerType,
        Turn,
    )

    bank = default_bank()
    card = MissionCard(merchant=Merchant(merchant_id="m", name="M", business_type="kirana", city="Patiala"),
                       kind=MissionKind.SALES, goal="g", door=Door.MERCHANT, trigger=TriggerType.CALLBACK_REQUEST,
                       why_now="w", starting_worries=bank.priors[TriggerType.CALLBACK_REQUEST])
    greet = Move(type=MoveType.DISCLOSE_AND_GREET)
    transcript = Transcript(mission_id=card.mission_id, disclosed_ai=True, turns=[
        Turn(speaker="agent", text="Namaste", move=greet), Turn(speaker="merchant", text=text)])
    return DialogueState(card=card, belief=BeliefState(probabilities=bank.prior_for(TriggerType.CALLBACK_REQUEST)),
                         transcript=transcript, moves=[greet])


# ── 8. The speaker map is built once ─────────────────────────────────────


def test_the_inverse_speaker_map_is_a_module_constant():
    assert core_adapters.CORE_SPEAKERS == {value: key for key, value in core_adapters.SPEAKERS.items()}
