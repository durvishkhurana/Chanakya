import asyncio

import httpx
import pytest

from chanakya.brain.contracts import fakes, interfaces
from chanakya.brain.contracts.events import BeliefUpdated, InProcessEventBus, MissionCreated, from_ledger, to_ledger
from chanakya.brain.contracts.llm import LLMClient, LLMError, complete_json, parse_json
from chanakya.brain.contracts.schemas import BeliefState, MissionState, Move, MoveType, ToolCall


def test_fakes_satisfy_every_protocol():
    pairs = [
        (fakes.FakeBeliefTracker(), interfaces.BeliefTracker),
        (fakes.FakePlanner(), interfaces.Planner),
        (fakes.FakeRealizer(), interfaces.Realizer),
        (fakes.FakeToolRegistry(), interfaces.ToolRegistry),
        (fakes.FakeSafetyGate(), interfaces.SafetyGate),
        (fakes.InMemoryMissionStore(), interfaces.MissionStore),
        (fakes.FakeMerchantTwin(), interfaces.MerchantTwin),
        (fakes.RecordingEventBus(), interfaces.EventBus),
        (fakes.FakeLLM(), LLMClient),
    ]
    for fake, protocol in pairs:
        assert isinstance(fake, protocol), f"{type(fake).__name__} does not satisfy {protocol.__name__}"


def test_event_bus_persists_before_delivering_and_survives_bad_subscribers():
    store = fakes.InMemoryMissionStore()
    bus = InProcessEventBus(store)
    seen = []

    def broken(event):
        raise RuntimeError("subscriber bug")

    async def good(event):
        seen.append((event.kind, len(store.ledger)))

    bus.subscribe(None, broken)
    unsubscribe = bus.subscribe("BeliefUpdated", good)
    belief = BeliefState(probabilities={"a": 1.0})

    async def run():
        await bus.publish(MissionCreated(mission_id="m_test", card=fakes.sample_card()))
        await bus.publish(BeliefUpdated(mission_id="m_test", belief=belief, latency_ms=3.0))
        unsubscribe()
        await bus.publish(BeliefUpdated(mission_id="m_test", belief=belief))

    asyncio.run(run())
    assert seen == [("BeliefUpdated", 2)]
    assert [event.kind for event in store.events("m_test")] == ["MissionCreated", "BeliefUpdated", "BeliefUpdated"]
    replayed = from_ledger(store.ledger[1])
    assert isinstance(replayed, BeliefUpdated) and replayed.belief == belief
    assert from_ledger(to_ledger(replayed)) == replayed


def test_fake_gate_blocks_unknown_tools_and_writes_without_consent():
    gate = fakes.FakeSafetyGate()
    state = fakes.sample_state()

    async def run():
        unknown = await gate.check(ToolCall(tool="transfer_money"), state)
        write = await gate.check(ToolCall(tool="send_onboarding_link"), state)
        read = await gate.check(ToolCall(tool="get_device_status", args={"merchant_id": "mer_test"}), state)
        return unknown, write, read

    unknown, write, read = asyncio.run(run())
    assert (unknown.verdict, unknown.reason) == ("blocked", "unknown_tool")
    assert (write.verdict, write.reason) == ("blocked", "no_consent")
    assert read.verdict == "executed" and read.result.data["mock"] is True


def test_store_refuses_to_move_a_terminal_mission():
    store = fakes.InMemoryMissionStore()
    store.create(fakes.sample_card())
    store.advance("m_test", MissionState.DONE)
    with pytest.raises(ValueError):
        store.advance("m_test", MissionState.CONTACTING)


def test_fake_planner_ends_politely_when_script_is_empty():
    planner = fakes.FakePlanner([Move(type=MoveType.DISCLOSE_AND_GREET)])
    state = fakes.sample_state()
    first = asyncio.run(planner.plan(state)).move
    second = asyncio.run(planner.plan(state)).move
    assert first.type == MoveType.DISCLOSE_AND_GREET and second.type == MoveType.END_CALL_POLITELY


def test_parse_json_tolerates_fences_and_rejects_garbage():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure: {"a": 2} done') == {"a": 2}
    with pytest.raises(LLMError):
        parse_json("no json here")
    assert asyncio.run(complete_json(fakes.FakeLLM('{"ok": true}'), "judge", [])) == {"ok": True}


def test_complete_json_wraps_provider_errors_without_leaking_details():
    def failing(request):
        return httpx.Response(401, json={"error": "bad key secret-key"})

    from chanakya.core.config import Settings
    from chanakya.core.llm import OpenRouterLLM

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(failing))
        llm = OpenRouterLLM(Settings(openrouter_api_key="secret-key"), client=client, retries=0)
        try:
            await complete_json(llm, "main", [{"role": "user", "content": "hi"}])
        finally:
            await client.aclose()

    with pytest.raises(LLMError) as error:
        asyncio.run(run())
    assert "secret-key" not in str(error.value)

