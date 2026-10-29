import asyncio

from agent.brain_agent import BrainAgent
from chanakya.brain.contracts.fakes import FakeSafetyGate, InMemoryMissionStore, RecordingEventBus
from chanakya.brain.contracts.schemas import MoveType
from chanakya.brain.speculative import matches, measure


def test_matching_tolerates_case_and_punctuation_but_not_new_words():
    assert matches("rent kitna hai", "Rent kitna hai?")
    assert not matches("Rent", "Rent kitna hai")
    assert not matches("Haan", "Haan, bhej do")


def test_a_matching_final_commits_the_prepared_turn_and_publishes_once():
    bus = RecordingEventBus(InMemoryMissionStore())
    agent = BrainAgent(bus=bus)

    async def run():
        await agent.respond("Hello", "t", "hi-IN")
        await agent.prepare("koi hidden charge toh nahi hai na", "t", "hi-IN")
        return await agent.respond("Koi hidden charge toh nahi hai na?", "t", "hi-IN")

    reply = asyncio.run(run())
    state = agent.threads["t"]
    assert agent.speculation_hits == 1 and "pricing" in reply
    assert state.transcript.turns[-2].text == "Koi hidden charge toh nahi hai na?"
    assert [e.kind for e in bus.published].count("TurnCompleted") == 2


def test_a_changed_final_discards_the_speculation():
    agent = BrainAgent()

    async def run():
        await agent.respond("Hello", "t", "hi-IN")
        await agent.prepare("Rent", "t", "hi-IN")
        return await agent.respond("Mere paas pehle se dusra QR hai.", "t", "hi-IN")

    asyncio.run(run())
    state = agent.threads["t"]
    assert agent.speculation_hits == 0
    assert state.moves[-1].concern == "competitor_qr"
    assert [t.text for t in state.transcript.turns if t.speaker == "merchant"] == ["Hello", "Mere paas pehle se dusra QR hai."]


def test_write_actions_never_run_before_the_merchant_finishes():
    gate = FakeSafetyGate()
    agent = BrainAgent(gate=gate, actions_enabled=True)

    async def reach_consent():
        await agent.respond("Hello", "t", "en-IN")
        for _ in range(10):
            if agent.threads["t"].moves[-1].type == MoveType.CONFIRM_CONSENT:
                return
            await agent.respond("Okay.", "t", "en-IN")

    asyncio.run(reach_consent())
    asyncio.run(agent.prepare("Yes, please send it.", "t", "en-IN"))

    async def settle():
        await agent.speculations["t"].task

    asyncio.run(settle())
    assert gate.registry.executed == [] and agent.threads["t"].actions == []
    asyncio.run(agent.respond("Yes, please send it.", "t", "en-IN"))
    assert [c.tool for c in gate.registry.executed] == ["send_onboarding_link"] and agent.speculation_hits == 0


def test_stale_speculation_from_an_older_state_is_not_committed():
    agent = BrainAgent()

    async def run():
        await agent.respond("Hello", "t", "hi-IN")
        await agent.prepare("Rent kitna hai", "t", "hi-IN")
        await agent.respond("Achha", "t", "hi-IN")  # another turn lands first
        await agent.prepare("Rent kitna hai", "t", "hi-IN")
        agent.speculations["t"].version -= 2
        await agent.respond("Rent kitna hai", "t", "hi-IN")

    asyncio.run(run())
    assert agent.speculation_hits == 0


def test_planning_while_listening_lowers_median_turn_latency():
    result = asyncio.run(measure(turns=12, seed=1, lead_s=0.3, change_rate=0.25,
                                 delays={"rollout": 0.05, "main": 0.25}))
    assert result["planning_while_listening"]["p50_ms"] < result["planning_after_speech"]["p50_ms"]
