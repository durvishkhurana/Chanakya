import asyncio

import httpx
import pytest
from pydantic import ValidationError

from chanakya.core import interfaces
from chanakya.core.config import Settings
from chanakya.core.events import InProcessEventBus
from chanakya.core.fakes import (
    FakeBeliefTracker,
    FakeMerchantTwin,
    FakePlanner,
    FakeRealizer,
    FakeSafetyGate,
    FakeToolRegistry,
    InMemoryMissionStore,
)
from chanakya.core.llm import FakeLLM, OpenRouterLLM, Role
from chanakya.core.schemas import (
    ActionDecision,
    BeliefState,
    ContactWindow,
    Door,
    EventKind,
    HandoffCard,
    Merchant,
    MerchantSignal,
    Mission,
    MissionCard,
    MissionEvent,
    MissionType,
    Move,
    MoveType,
    PlanContext,
    PlanResult,
    ScoredMove,
    SignalKind,
    Speaker,
    ToolCall,
    ToolInfo,
    ToolKind,
    ToolResult,
    Transcript,
    Turn,
    TwinReply,
    Verdict,
)


def card(**overrides) -> MissionCard:
    data = {
        "merchant_id": "mer_1", "merchant_name": "Ramesh Kirana", "door": Door.MERCHANT,
        "signal_kind": SignalKind.CALLBACK_REQUEST, "signal_id": "sig_1", "mission_type": MissionType.SALES,
        "goal": "Sell Soundbox", "product": "soundbox", "why_now": "Requested a callback",
        "starting_worries": {"hidden_charges": 5, "competitor_qr": 3, "just_busy": 2}, "priority": 0.6,
    }
    return MissionCard(**(data | overrides))


def samples():
    mission = Mission(card=card())
    call = ToolCall(mission_id=mission.id, tool="send_onboarding_link", args={"product": "soundbox"})
    move = Move(type=MoveType.RESOLVE_CONCERN, concern_id="hidden_charges")
    transcript = Transcript(mission_id=mission.id, turns=[Turn(speaker=Speaker.MERCHANT, text="Kitna katega?", move=None)])
    return [
        Merchant(id="mer_1", name="Ramesh Kirana", business_type="kirana", city="Patiala"),
        MerchantSignal(merchant_id="mer_1", kind=SignalKind.SOUNDBOX_UNUSED, door=Door.DATA, source="signal feed"),
        mission,
        MissionEvent.of(mission.id, EventKind.NOTE, {"text": "hi"}),
        BeliefState(probabilities={"a": 1, "b": 3}),
        PlanResult(chosen=move, candidates=[ScoredMove(move=move, score=0.4, visits=3)], tree={"root": []}),
        transcript,
        PlanContext(mission=mission, belief=BeliefState(probabilities={"a": 1}), transcript=transcript),
        ToolInfo(name="get_device_status", system="devices", kind=ToolKind.READ, description="status"),
        ActionDecision(call=call, verdict=Verdict.EXECUTED, reason="ok",
                       result=ToolResult(call_id=call.id, tool=call.tool, ok=True)),
        HandoffCard(mission_id=mission.id, merchant_name="Ramesh", language="hi-IN", reason="distress", summary="s"),
        TwinReply(text="Haan", willingness=0.4),
    ]


@pytest.mark.parametrize("model", samples(), ids=lambda m: type(m).__name__)
def test_every_schema_round_trips_through_json(model):
    assert type(model).model_validate_json(model.model_dump_json()) == model


def test_probabilities_are_normalized():
    assert card().starting_worries == {"hidden_charges": 0.5, "competitor_qr": 0.3, "just_busy": 0.2}
    assert BeliefState(probabilities={"a": 1, "b": 3}).top(1) == [("b", 0.75)]
    with pytest.raises(ValidationError):
        BeliefState(probabilities={"a": -1})


def test_moves_enforce_their_required_fields():
    with pytest.raises(ValidationError):
        Move(type=MoveType.TAKE_ACTION)
    with pytest.raises(ValidationError):
        Move(type=MoveType.PROBE_CONCERN)


def test_contact_window():
    assert ContactWindow(start_hour=14, end_hour=17).contains(16)
    assert not ContactWindow(start_hour=14, end_hour=17).contains(17)
    with pytest.raises(ValidationError):
        ContactWindow(start_hour=17, end_hour=14)


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        Turn(speaker=Speaker.AGENT, text="hi", mood="happy")


def test_fakes_satisfy_protocols():
    store = InMemoryMissionStore()
    registry = FakeToolRegistry()
    pairs = [
        (FakeBeliefTracker(), interfaces.BeliefTracker),
        (FakePlanner(), interfaces.Planner),
        (FakeRealizer(), interfaces.Realizer),
        (registry, interfaces.ToolRegistry),
        (FakeSafetyGate(registry, store), interfaces.SafetyGate),
        (store, interfaces.MissionStore),
        (FakeMerchantTwin(), interfaces.MerchantTwin),
        (InProcessEventBus(store), interfaces.EventBus),
    ]
    for fake, protocol in pairs:
        assert isinstance(fake, protocol), protocol.__name__


def test_fake_gate_blocks_writes_without_consent_and_audits():
    store = InMemoryMissionStore()
    mission = store.create(Mission(card=card()))
    info = ToolInfo(name="send_onboarding_link", system="messaging", kind=ToolKind.WRITE, description="send")
    gate = FakeSafetyGate(FakeToolRegistry({info.name: (info, lambda args: {"sent": True})}), store)
    call = ToolCall(mission_id=mission.id, tool=info.name)

    assert asyncio.run(gate.submit(call)).verdict == Verdict.BLOCKED
    store.append(MissionEvent.of(mission.id, EventKind.CONSENT_GIVEN, {"for": info.name}))
    assert asyncio.run(gate.submit(call)).verdict == Verdict.EXECUTED
    assert asyncio.run(gate.submit(ToolCall(mission_id=mission.id, tool="invented"))).verdict == Verdict.REJECTED
    assert [e.kind for e in store.events(mission.id)].count(EventKind.ACTION_DECISION) == 3


def test_event_bus_persists_then_delivers_to_matching_subscribers():
    async def scenario():
        store = InMemoryMissionStore()
        bus = InProcessEventBus(store)
        everything, only_m1 = bus.subscribe(), bus.subscribe("m1")
        first_all = asyncio.ensure_future(anext(everything))
        first_m1 = asyncio.ensure_future(anext(only_m1))
        await asyncio.sleep(0)
        await bus.publish(MissionEvent.of("m2", EventKind.NOTE))
        await bus.publish(MissionEvent.of("m1", EventKind.NOTE))
        got_all, got_m1 = await first_all, await first_m1
        await everything.aclose()
        await only_m1.aclose()
        return store, got_all, got_m1, bus

    store, got_all, got_m1, bus = asyncio.run(scenario())
    assert got_all.mission_id == "m2" and got_m1.mission_id == "m1"
    assert got_m1.seq == 1 and len(store.events()) == 2
    assert bus.subscriber_count == 0


def test_subscription_receives_events_published_before_its_first_read():
    async def scenario():
        bus = InProcessEventBus(InMemoryMissionStore())
        subscription = bus.subscribe()
        await bus.publish(MissionEvent.of("m1", EventKind.NOTE))
        await bus.publish(MissionEvent.of("m1", EventKind.NOTE))
        got = [await anext(subscription), await anext(subscription)]
        await subscription.aclose()
        return got, bus.subscriber_count

    got, remaining = asyncio.run(scenario())
    assert [e.seq for e in got] == [1, 2] and remaining == 0


def test_flags_default_off(monkeypatch):
    for name in ("PLANNER_ENABLED", "ACTIONS_ENABLED", "MISSIONS_ENABLED", "COACH_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings.from_env()
    assert not any([settings.planner_enabled, settings.actions_enabled,
                    settings.missions_enabled, settings.coach_enabled])
    monkeypatch.setenv("MISSIONS_ENABLED", "true")
    assert Settings.from_env().missions_enabled


def test_winback_and_permission_first_flags_default_off(monkeypatch):
    for name in ("WINBACK_ENABLED", "PERMISSION_FIRST_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings.from_env()
    assert not settings.winback_enabled and not settings.permission_first_enabled
    assert not Settings().winback_enabled and not Settings().permission_first_enabled
    monkeypatch.setenv("WINBACK_ENABLED", "true")
    monkeypatch.setenv("PERMISSION_FIRST_ENABLED", "1")
    assert Settings.from_env().winback_enabled and Settings.from_env().permission_first_enabled


def test_a_former_merchant_round_trips_with_its_churn_date():
    merchant = Merchant(id="mer_x", name="x", business_type="kirana", city="Patna", relationship="former",
                        churned_at="2026-09-01T00:00:00+00:00")
    assert Merchant.model_validate_json(merchant.model_dump_json()) == merchant
    assert Merchant(id="m", name="n", business_type="b", city="c").relationship == "customer"
    with pytest.raises(ValidationError):
        Merchant(id="m", name="n", business_type="b", city="c", relationship="ex")


def test_twin_b_uses_a_different_model_family_by_default():
    models = Settings().models
    assert models["twin_a"].split("/")[0] != models["twin_b"].split("/")[0]


def test_openrouter_client_sends_role_model_and_reasoning_settings():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(__import__("json").loads(request.content))
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(200, json={"choices": [{"message": {"content": " 391 "}}]})

    llm = OpenRouterLLM(Settings(openrouter_api_key="k"), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert asyncio.run(llm.complete(Role.TWIN_A, [{"role": "user", "content": "17*23"}])) == "391"
    assert seen["model"].startswith("deepseek/") and seen["reasoning"] == {"enabled": False}
    assert seen["auth"] == "Bearer k"


def test_fake_llm_records_calls():
    llm = FakeLLM({Role.JUDGE: "yes"})
    assert asyncio.run(llm.complete(Role.JUDGE, [{"role": "user", "content": "?"}])) == "yes"
    assert llm.calls[0][0] == Role.JUDGE


def test_groq_is_chosen_when_only_its_key_is_set(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-secret")
    settings = Settings.from_env()
    assert settings.llm_provider == "groq" and settings.llm_api_key == "groq-test-secret"
    assert settings.models["twin_a"].split("/")[0] != settings.models["twin_b"].split("/")[0]
    assert "groq-test-secret" not in repr(settings)
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")
    assert Settings.from_env().llm_provider == "openrouter"
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    assert Settings.from_env().llm_provider == "groq"


def test_groq_client_uses_its_endpoint_json_mode_seed_and_retries_rate_limits():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), __import__("json").loads(request.content), request.headers["Authorization"]))
        if len(seen) == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    settings = Settings(llm_provider="groq", groq_api_key="g", models=dict(__import__("chanakya.core.config", fromlist=["GROQ_MODELS"]).GROQ_MODELS))
    llm = OpenRouterLLM(settings, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    reply = asyncio.run(llm.complete(Role.MAIN, [{"role": "user", "content": "hi"}], json_mode=True, seed=4))
    url, body, auth = seen[-1]
    assert reply == '{"ok": true}' and len(seen) == 2
    assert url == "https://api.groq.com/openai/v1/chat/completions" and auth == "Bearer g"
    assert body["response_format"] == {"type": "json_object"} and body["seed"] == 4
    assert body["reasoning_effort"] == "low" and "reasoning" not in body
    assert any("json" in m["content"].lower() for m in body["messages"])


def test_worry_scorer_defaults_to_lexical_and_rejects_unknown_values(monkeypatch):
    monkeypatch.delenv("WORRY_SCORER", raising=False)
    assert Settings.from_env().worry_scorer == "lexical"
    monkeypatch.setenv("WORRY_SCORER", " Embedding ")
    assert Settings.from_env().worry_scorer == "embedding"
    monkeypatch.setenv("WORRY_SCORER", "neural")
    with pytest.raises(ValueError, match="WORRY_SCORER"):
        Settings.from_env()


def test_planner_value_defaults_to_the_formula_and_rejects_unknown_values(monkeypatch):
    monkeypatch.delenv("PLANNER_VALUE", raising=False)
    assert Settings.from_env().planner_value == "formula" and Settings().planner_value == "formula"
    monkeypatch.setenv("PLANNER_VALUE", " Network ")
    assert Settings.from_env().planner_value == "network"
    monkeypatch.setenv("PLANNER_VALUE", "learned")
    with pytest.raises(ValueError, match="PLANNER_VALUE"):
        Settings.from_env()


def test_planner_memory_defaults_to_the_forest_and_rejects_unknown_values(monkeypatch):
    monkeypatch.delenv("PLANNER_MEMORY", raising=False)
    assert Settings.from_env().planner_memory == "forest" and Settings().planner_memory == "forest"
    monkeypatch.setenv("PLANNER_MEMORY", " Neural ")
    assert Settings.from_env().planner_memory == "neural"
    monkeypatch.setenv("PLANNER_MEMORY", "trigram")
    with pytest.raises(ValueError, match="PLANNER_MEMORY"):
        Settings.from_env()


def test_approval_settings_default_to_none_and_parse_a_tool_list(monkeypatch):
    monkeypatch.delenv("APPROVAL_TOOLS", raising=False)
    monkeypatch.delenv("APPROVAL_TIMEOUT_MINUTES", raising=False)
    settings = Settings.from_env()
    assert settings.approval_tools == () and settings.approval_timeout_minutes == 30
    monkeypatch.setenv("APPROVAL_TOOLS", " book_field_visit, raise_ticket ,")
    monkeypatch.setenv("APPROVAL_TIMEOUT_MINUTES", "5")
    settings = Settings.from_env()
    assert settings.approval_tools == ("book_field_visit", "raise_ticket") and settings.approval_timeout_minutes == 5
