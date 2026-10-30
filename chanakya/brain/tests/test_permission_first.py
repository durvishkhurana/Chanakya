"""Permission-first opening for lead-list calls: two minutes first, no pitch before a clear yes (task P1)."""

import asyncio
import json
from datetime import UTC, datetime

import pytest

from chanakya.brain import moves as lib
from chanakya.brain.concern_bank import default_bank
from chanakya.brain.contracts.fakes import FakeLLM, sample_card
from chanakya.brain.contracts.schemas import (
    BeliefState,
    DialogueState,
    Door,
    EndReason,
    Merchant,
    Move,
    MoveType,
    Transcript,
    TriggerType,
    Turn,
)
from chanakya.brain.core_adapters import to_brain_card
from chanakya.brain.mission_call import MissionCall
from chanakya.brain.planner_nrpa import NRPAPlanner
from chanakya.brain.planner_rules import RuleBasedPlanner
from chanakya.brain.realizer import GREET_ONLY, PERMISSION, PERMISSION_AGAIN, LLMRealizer, TemplateRealizer
from chanakya.core import schemas as core
from chanakya.core.config import Settings
from chanakya.missions.runtime import Runtime
from chanakya.missions.scheduler import SimClock
from chanakya.sim.judge import safety_violations

BANK = default_bank()
GREET = Move(type=MoveType.DISCLOSE_AND_GREET)
ASK = Move(type=MoveType.ASK_PERMISSION)
START = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)  # 15:00 in Asia/Kolkata


def card(language="hi-IN", permission_first=True):
    return sample_card(trigger=TriggerType.LEAD_LIST, door=Door.HUMAN, why_now="From Sunita's lead list",
                       starting_worries=BANK.priors[TriggerType.LEAD_LIST], permission_first=permission_first,
                       merchant=Merchant(merchant_id="mer_lead", name="Lead (mock)", business_type="kirana",
                                         city="Patna", language=language))


def state(*answers, language="hi-IN", pause=None):
    """Greeting, a reply, then one permission question per answer."""
    turns = [Turn(speaker="merchant", text="Hello"), Turn(speaker="agent", text="Namaste", move=GREET),
             Turn(speaker="merchant", text="Haan?")]
    moves = [GREET]
    for answer in answers:
        turns += [Turn(speaker="agent", text="Do minute?", move=ASK),
                  Turn(speaker="merchant", text=answer, pause_before_ms=pause)]
        moves.append(ASK)
    return DialogueState(card=card(language), belief=BeliefState(probabilities=BANK.prior_for(TriggerType.LEAD_LIST)),
                         transcript=Transcript(mission_id="m_test", turns=turns, disclosed_ai=True), moves=moves)


def choose(s):
    return RuleBasedPlanner(BANK).choose(s)


def test_the_flag_turns_it_on_for_lead_list_missions_only():
    def mission(kind):
        return core.Mission(id="m", card=core.MissionCard(
            merchant_id="mer", merchant_name="x", door=core.Door.HUMAN if kind == core.SignalKind.LEAD_LIST_ASSIGNED
            else core.Door.MERCHANT, signal_kind=kind, signal_id="s", mission_type=core.MissionType.SALES, goal="g",
            why_now="w", starting_worries={"just_busy": 1.0}))
    assert to_brain_card(mission(core.SignalKind.LEAD_LIST_ASSIGNED), permission_first=True).permission_first
    assert not to_brain_card(mission(core.SignalKind.LEAD_LIST_ASSIGNED)).permission_first  # flag off by default
    assert not to_brain_card(mission(core.SignalKind.CALLBACK_REQUEST), permission_first=True).permission_first
    assert not Settings().permission_first_enabled


def test_after_the_disclosure_the_only_next_step_is_the_permission_question():
    s = state()
    move, rule = choose(s)
    assert (move.type, rule) == (MoveType.ASK_PERMISSION, "ask_permission")
    for pitch in (Move(type=MoveType.RECOMMEND, product="soundbox"),
                  Move(type=MoveType.CONFIRM_CONSENT, tool="send_onboarding_link"),
                  Move(type=MoveType.TAKE_ACTION, tool="send_onboarding_link"),
                  Move(type=MoveType.RESOLVE_CONCERN, concern="hidden_charges"), Move(type=MoveType.DISCOVER_NEED)):
        assert "permission_first" in lib.violations(pitch, s, BANK)
    legal = lib.legal_moves(s, BANK, "soundbox", "send_onboarding_link")
    assert {m.type for m in legal} <= lib.PERMISSION_OPEN
    assert asyncio.run(NRPAPlanner(BANK, seed=5).plan(s)).move.type == MoveType.ASK_PERMISSION


@pytest.mark.parametrize("answer,pause,expected", [
    ("Haan ji, boliye.", None, "yes"),
    ("Haan.", None, "yes"),
    ("Haan.", 2500, "unclear"),  # a short haan after a long pause is deflection (cues.py)
    ("Hmm... haan.", None, "unclear"),
    ("Hmm.", None, "unclear"),
    ("Nahi.", None, "no"),
    ("Nahi chahiye.", None, "no"),
    ("Abhi busy hoon, baad mein call karo.", None, "busy"),
    ("Abhi time nahi hai.", None, "busy"),
    ("नहीं।", None, "no"),
    ("ਹਾਂ ਜੀ, ਦੱਸੋ।", None, "yes"),
])
def test_answers_to_the_permission_question(answer, pause, expected):
    assert lib.permission_reply(Turn(speaker="merchant", text=answer, pause_before_ms=pause)) == expected


def test_a_clear_yes_opens_the_normal_conversation():
    s = state("Haan ji, boliye.")
    assert lib.permission_granted(s)
    move, _ = choose(s)
    assert move.type not in {MoveType.ASK_PERMISSION, MoveType.END_CALL_POLITELY}
    assert lib.violations(Move(type=MoveType.RECOMMEND, product="soundbox"), s, BANK) == []


def test_a_no_ends_politely_as_a_decline_and_busy_schedules_a_callback():
    move, rule = choose(state("Nahi."))
    assert (move.type, move.end_reason, rule) == (MoveType.END_CALL_POLITELY, EndReason.DECLINED, "permission_declined")
    move, rule = choose(state("Abhi busy hoon, baad mein call karo."))
    assert (move.type, rule) == (MoveType.SCHEDULE_FOLLOWUP, "permission_busy")


def test_a_deflected_haan_is_asked_once_more_then_the_call_ends_without_a_pitch():
    move, rule = choose(state("Haan.", pause=2500))
    assert (move.type, rule) == (MoveType.ASK_PERMISSION, "ask_permission_again")
    move, rule = choose(state("Haan.", "Hmm.", pause=2500))
    assert (move.type, rule) == (MoveType.END_CALL_POLITELY, "permission_unclear")
    assert "permission_not_needed" in lib.violations(ASK, state("Hmm.", "Hmm."), BANK)


@pytest.mark.parametrize("language,merchant,label", [
    ("hi-IN", "Haan?", "hinglish"), ("hi-IN", "हाँ?", "hindi"), ("pa-IN", "ਹਾਂ ਜੀ?", "punjabi"), ("en-IN", "Yes?", "english"),
])
def test_the_question_exists_in_all_four_languages_without_a_pitch_or_an_em_dash(language, merchant, label):
    s = state(language=language)
    s.transcript.turns[-1] = Turn(speaker="merchant", text=merchant)
    text = asyncio.run(TemplateRealizer(BANK).realize(ASK, s))
    assert text == PERMISSION[label]
    for line in (PERMISSION[label], PERMISSION_AGAIN[label]):
        assert "?" in line and "AI" in line and "—" not in line and safety_violations(line) == []
    assert not any(word in line.lower() for line in PERMISSION.values() for word in ("soundbox", "rent", "price"))


def test_the_greeting_only_discloses_on_a_permission_first_call():
    for language in ("hi-IN", "en-IN"):
        text = asyncio.run(TemplateRealizer(BANK).realize(GREET, state(language=language)))
        assert "AI" in text and "?" not in text and text in GREET_ONLY.values()


def test_an_llm_permission_line_that_pitches_falls_back_to_the_template():
    llm = FakeLLM(json.dumps({"text": "Main AI assistant hoon. Soundbox ka rent bahut kam hai, do minute hain?"}))
    text = asyncio.run(LLMRealizer(llm, BANK).realize(ASK, state()))
    assert text == PERMISSION["hinglish"]


# ── On a real mission ────────────────────────────────────────────────────


def lead_call(tmp_path, enabled=True):
    runtime = Runtime.build(Settings(db_path=tmp_path / "ledger.db", permission_first_enabled=enabled),
                            clock=SimClock(START))

    async def go():
        signal = core.MerchantSignal(merchant_id="mer_sharma", kind=core.SignalKind.LEAD_LIST_ASSIGNED,
                                     door=core.Door.HUMAN, source="test", details={"assigned_by": "Sunita"})
        mission, _ = await runtime.intake.ingest(signal)
        call = MissionCall(runtime, mission.id)
        await call.start()
        return call

    return runtime, asyncio.run(go())


def test_a_no_on_a_lead_list_mission_is_recorded_as_a_decline_and_closes_it(tmp_path):
    runtime, call = lead_call(tmp_path)
    for line in ("Haan ji?", "Kaun? Haan boliye.", "Nahi."):
        asyncio.run(call.say(line))
    mission = runtime.ledger.store.get(call.mission_id)
    declines = [e.payload for e in runtime.ledger.store.events(call.mission_id)
                if e.kind == core.EventKind.CONSENT_DECLINED]
    assert mission.state == core.MissionState.CLOSED_NOT_INTERESTED and mission.outcome == "merchant declined"
    assert declines == [{"utterance": "Nahi.", "scope": "permission"}]


def test_busy_on_a_lead_list_mission_schedules_a_callback(tmp_path):
    runtime, call = lead_call(tmp_path)
    for line in ("Haan ji?", "Haan?", "Abhi busy hoon, baad mein call karo."):
        asyncio.run(call.say(line))
    assert runtime.ledger.store.get(call.mission_id).state == core.MissionState.SCHEDULED
    kinds = [e.payload.get("kind") for e in runtime.ledger.store.events(call.mission_id)
             if e.kind == core.EventKind.FOLLOWUP_SCHEDULED]
    assert kinds == ["callback"]


def test_with_the_flag_off_lead_list_calls_open_as_before(tmp_path):
    _, call = lead_call(tmp_path, enabled=False)
    greeting = asyncio.run(call.say("Haan ji?"))
    asyncio.run(call.say("Haan boliye."))
    assert not call.state.card.permission_first and "do minute" in greeting  # the original greeting and question
    assert MoveType.ASK_PERMISSION not in [m.type for m in call.state.moves]
