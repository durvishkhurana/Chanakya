import asyncio

from chanakya.brain.concern_bank import default_bank
from chanakya.brain.contracts import events as brain_events
from chanakya.brain.contracts import schemas as brain
from chanakya.brain.core_adapters import (
    CONCERN_ALIASES,
    CoreBeliefTracker,
    CorePlanner,
    CoreRealizer,
    to_brain_state,
    to_core_move,
    to_ledger_event,
    worries,
)
from chanakya.brain.planner_nrpa import NRPAPlanner
from chanakya.brain.planner_rules import RuleBasedPlanner
from chanakya.brain.realizer import TemplateRealizer
from chanakya.core import interfaces
from chanakya.core import schemas as core

BANK = default_bank()


def mission(kind=core.SignalKind.PRICE_QUESTION_DROPPED, worries_=None):
    card = core.MissionCard(
        merchant_id="mer_1", merchant_name="Ramesh Kirana (mock)", language="hi-IN", door=core.Door.MERCHANT,
        signal_kind=kind, signal_id="sig_1", mission_type=core.MissionType.SALES, goal="Sell card machine",
        product="card_machine", why_now="Asked the price", priority=0.4,
        starting_worries=worries_ if worries_ is not None else {"swipe_charges": 0.55, "rental_cost": 0.3,
                                                              "setup_hassle": 0.15},
    )
    return core.Mission(id="m_core", card=card, state=core.MissionState.IN_CONVERSATION)


def context(*turns, belief=None):
    m = mission()
    tracker = CoreBeliefTracker()
    return core.PlanContext(mission=m, belief=belief or tracker.initial(m.card),
                            transcript=core.Transcript(mission_id=m.id, turns=list(turns)))


def agent(text, move):
    return core.Turn(speaker=core.Speaker.AGENT, text=text, move=move)


def merchant(text):
    return core.Turn(speaker=core.Speaker.MERCHANT, text=text)


def test_adapters_satisfy_the_core_protocols():
    assert isinstance(CorePlanner(RuleBasedPlanner()), interfaces.Planner)
    assert isinstance(CoreBeliefTracker(), interfaces.BeliefTracker)
    assert isinstance(CoreRealizer(TemplateRealizer()), interfaces.Realizer)


def test_track_b_concern_ids_map_onto_the_concern_bank():
    assert all(target in BANK.concerns for target in CONCERN_ALIASES.values())
    mapped = worries({"swipe_charges": 0.5, "device_reliability": 0.25, "cash_flow": 0.25, "made_up": 1.0}, BANK)
    assert set(mapped) == {"per_swipe_charges", "device_issue", "rental_cost"}
    assert abs(sum(mapped.values()) - 1) < 1e-9
    initial = CoreBeliefTracker().initial(mission().card)
    assert initial.top(1)[0][0] == "per_swipe_charges"


def test_planner_through_core_types_discloses_first_and_returns_a_core_plan():
    result = asyncio.run(CorePlanner(NRPAPlanner()).plan(context(merchant("Hello?"))))
    assert isinstance(result, core.PlanResult) and result.chosen.type == core.MoveType.DISCLOSE_AND_GREET


def test_consent_is_rebuilt_from_the_core_transcript_and_unlocks_the_action():
    greet = core.Move(type=core.MoveType.DISCLOSE_AND_GREET)
    ask = core.Move(type=core.MoveType.CONFIRM_CONSENT,
                    tool_call=core.ToolCall(mission_id="m_core", tool="send_onboarding_link"))
    bare = context(agent("Namaste, main ek AI assistant hoon.", greet), merchant("Haan"), agent("Link bhej doon?", ask),
                   merchant("Haan."))
    assert to_brain_state(bare).transcript.consents == []
    clear = context(agent("Namaste, main ek AI assistant hoon.", greet), merchant("Haan"), agent("Link bhej doon?", ask),
                    merchant("Haan, bhej do."))
    state = to_brain_state(clear)
    assert state.transcript.has_consent("send_onboarding_link") and state.transcript.disclosed_ai
    result = asyncio.run(CorePlanner(RuleBasedPlanner()).plan(clear))
    assert result.chosen.type == core.MoveType.TAKE_ACTION and result.chosen.tool_call.tool == "send_onboarding_link"
    call = core.ToolCall(mission_id="m_core", tool="send_onboarding_link")
    assert asyncio.run(CorePlanner(RuleBasedPlanner()).reconsider(clear, call))
    assert not asyncio.run(CorePlanner(RuleBasedPlanner()).reconsider(bare, call))


def test_belief_updates_and_realization_through_core_types():
    tracker = CoreBeliefTracker()
    ctx = context()
    updated = asyncio.run(tracker.update(ctx.belief, merchant("Har card swipe pe kitna katega?"), ctx.transcript))
    assert isinstance(updated, core.BeliefState) and updated.top(1)[0][0] == "per_swipe_charges"
    move = core.Move(type=core.MoveType.RESOLVE_CONCERN, concern_id="swipe_charges")
    text = asyncio.run(CoreRealizer(TemplateRealizer()).realize(move, ctx))
    assert "card" in text.lower() and "Rs" not in text


def test_brain_events_become_core_ledger_events():
    belief = brain.BeliefState(probabilities={"rental_cost": 1.0})
    move = brain.Move(type=brain.MoveType.TAKE_ACTION, tool="send_onboarding_link")
    events = [
        brain_events.BeliefUpdated(mission_id="m_core", belief=belief, latency_ms=2.0),
        brain_events.PlanComputed(mission_id="m_core", plan=brain.PlanResult(move=move)),
        brain_events.TurnCompleted(mission_id="m_core", turn=brain.Turn(speaker="agent", text="Ho gaya."), move=move),
    ]
    kinds = [to_ledger_event(e).kind for e in events]
    assert kinds == [core.EventKind.BELIEF_UPDATED, core.EventKind.PLAN_COMPUTED, core.EventKind.TURN_COMPLETED]
    assert to_ledger_event(events[1]).payload["chosen"]["tool_call"]["tool"] == "send_onboarding_link"
    core_move = to_core_move(move, "m_core")
    assert core_move.tool_call.mission_id == "m_core"
