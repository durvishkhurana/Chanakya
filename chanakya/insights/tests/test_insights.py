"""The insights count exactly what the ledger events say."""

from datetime import UTC, datetime

from chanakya.core.schemas import (
    Door,
    EventKind,
    HandoffCard,
    Mission,
    MissionCard,
    MissionEvent,
    MissionState,
    MissionType,
    SignalKind,
)
from chanakya.insights.insights import summarise

DAY = datetime(2026, 10, 30, 6, 0, tzinfo=UTC)  # 11:30 in Asia/Kolkata


def mission(mid, state, product="soundbox", language="hi-IN", kind=MissionType.SALES, start=None):
    card = MissionCard(merchant_id=f"mer_{mid}", merchant_name=mid, door=Door.DATA, signal_kind=SignalKind.SOUNDBOX_UNUSED,
                       signal_id=f"sig_{mid}", mission_type=kind, goal="g", product=product, why_now="w", language=language,
                       starting_worries=start or {"swipe_charges": 1.0})
    return Mission(id=mid, card=card, state=state, created_at=DAY)


def ev(mid, kind, **payload):
    return MissionEvent(mission_id=mid, kind=kind, payload=payload)


def call(mid, worry, *, consent=False, answered=None, executed=False, done=False):
    """Events of one call: contact, a merchant turn, an agent move, a belief, and optionally consent and an action."""
    events = [ev(mid, EventKind.STATE_CHANGED, to="CONTACTING"), ev(mid, EventKind.STATE_CHANGED, to="IN_CONVERSATION"),
              ev(mid, EventKind.TURN_COMPLETED, speaker="merchant", text="..."),
              ev(mid, EventKind.TURN_COMPLETED, speaker="agent", text="...",
                 move={"type": answered or "DISCOVER_NEED", "concern_id": worry if answered else None}),
              ev(mid, EventKind.BELIEF_UPDATED, probabilities={worry: 0.7, "just_busy": 0.3})]
    if consent:
        events.append(ev(mid, EventKind.CONSENT_GIVEN, tools=["send_onboarding_link"]))
    if executed:
        events.append(ev(mid, EventKind.ACTION_DECISION, verdict="executed", call={"tool": "send_onboarding_link"}))
        events.append(ev(mid, EventKind.ACTION_DECISION, verdict="executed", call={"tool": "get_merchant_profile"}))
    if done:
        events.append(ev(mid, EventKind.STATE_CHANGED, to="DONE"))
    return events


def ledger():
    missions = [mission("a", MissionState.DONE), mission("b", MissionState.CLOSED_NOT_INTERESTED),
                mission("c", MissionState.AWAITING_CONFIRMATION, product="card_machine", language="pa-IN"),
                mission("d", MissionState.CREATED, kind=MissionType.WIN_BACK)]
    events = (call("a", "rental_cost", consent=True, answered="RESOLVE_CONCERN", executed=True, done=True)
              + call("b", "rental_cost") + call("c", "per_swipe_charges", consent=True, answered="PROBE_CONCERN", executed=True))
    handoffs = [HandoffCard(mission_id="b", merchant_name="b", language="hi-IN", reason="distress", summary="s", urgent=True),
                HandoffCard(mission_id="d", merchant_name="d", language="hi-IN", summary="s",
                            reason="open device complaint t_1: a person answers it before any win-back call")]
    return summarise(missions, events, handoffs, {"total": 0}, now=DAY)


def test_worries_come_from_the_last_belief_with_intake_aliases_folded_in():
    w = ledger()["worries"]
    assert w["calls"] == 3 and w["overall"] == {"rental_cost": 2, "per_swipe_charges": 1}
    assert w["by_product"]["card_machine"] == {"per_swipe_charges": 1} and w["by_language"]["pa-IN"] == {"per_swipe_charges": 1}
    assert w["by_day"] == [{"day": "2026-10-30", "counts": {"rental_cost": 2, "per_swipe_charges": 1}}]
    assert w["differs_from_card"] == round(2 / 3, 3), "swipe_charges on the card is per_swipe_charges, so c matched"


def test_the_funnel_counts_each_stage_from_events_and_ignores_reads():
    f = ledger()["funnel"]
    assert [s["missions"] for s in f["overall"]] == [4, 3, 3, 2, 2, 1]
    assert [s["missions"] for s in f["by_type"]["win_back"]] == [1, 0, 0, 0, 0, 0]
    assert f["not_done"] == {"CLOSED_NOT_INTERESTED": 1, "AWAITING_CONFIRMATION": 1, "CREATED": 1}


def test_moves_compare_consent_when_the_worry_was_addressed_or_not():
    rent = next(r for r in ledger()["moves"] if r["worry"] == "rental_cost")
    assert rent["missions"] == 2 and rent["consent_rate"] == 0.5
    assert rent["addressed"] == {"missions": 1, "consent_rate": 1.0}
    assert rent["not_addressed"] == {"missions": 1, "consent_rate": 0.0}
    assert rent["moves"] == [{"move": "RESOLVE_CONCERN", "missions": 1, "consent_rate": 1.0}]


def test_escalation_reasons_are_grouped_and_the_headline_adds_up():
    data = ledger()
    assert data["escalations"]["by_reason"] == {"distress": 1, "open complaint": 1} and data["escalations"]["urgent"] == 1
    head = data["headline"]
    assert head["missions"] == 4 and head["talked"] == 3 and head["consent_rate"] == round(2 / 3, 3)
    assert head["done"] == 1 and head["escalated"] == 2 and head["median_agent_turns"] == 1
