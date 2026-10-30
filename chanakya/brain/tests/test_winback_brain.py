"""The win-back conversation: listen first, act on the reason, never an offer (task W2). Fictional merchants only."""

import asyncio
import json
import random

import pytest

from chanakya.brain import moves as lib
from chanakya.brain.concern_bank import default_bank, load_personas
from chanakya.brain.contracts.fakes import FakeLLM, sample_card
from chanakya.brain.contracts.schemas import (
    ActionDecision,
    BeliefState,
    ConsentRecord,
    DialogueState,
    Door,
    EndReason,
    Merchant,
    MissionKind,
    Move,
    MoveType,
    Persona,
    ToolCall,
    ToolResult,
    Transcript,
    TriggerType,
    Turn,
)
from chanakya.brain.planner_nrpa import NRPAPlanner
from chanakya.brain.planner_rules import RuleBasedPlanner
from chanakya.brain.realizer import OFFER, LLMRealizer, TemplateRealizer
from chanakya.sim.judge import initial_state, judge_turn, safety_violations

BANK = default_bank()
GREET = Move(type=MoveType.DISCLOSE_AND_GREET)
ASK_WHY = Move(type=MoveType.DISCOVER_NEED)


def card(language="hi-IN"):
    return sample_card(
        mission_id="m_wb", kind=MissionKind.WIN_BACK, trigger=TriggerType.MERCHANT_CHURNED, door=Door.DATA,
        goal="Find out why they stopped using Soundbox", why_now="Stopped 35 days ago", context="soundbox",
        merchant=Merchant(merchant_id="mer_wb", name="Old Kirana (mock)", business_type="kirana", city="Patna",
                          language=language, relationship="former"),
        starting_worries=BANK.priors[TriggerType.MERCHANT_CHURNED])


def belief(top=None, p=0.8):
    probabilities = BANK.prior_for(TriggerType.MERCHANT_CHURNED)
    if top:
        rest = 1 - p
        others = {c: v for c, v in probabilities.items() if c != top}
        total = sum(others.values())
        probabilities = {c: rest * v / total for c, v in others.items()} | {top: p}
    return BeliefState(probabilities=probabilities)


def state(*steps, top=None, p=0.8, language="hi-IN"):
    """A win-back call: greeting, a filler, then ``steps`` as alternating (agent move, merchant text) pairs."""
    turns = [Turn(speaker="merchant", text="Haan ji?"), Turn(speaker="agent", text="Namaste", move=GREET),
             Turn(speaker="merchant", text="Achha.")]
    moves = [GREET]
    for move, reply in steps:
        turns += [Turn(speaker="agent", text="...", move=move), Turn(speaker="merchant", text=reply)]
        moves.append(move)
    return DialogueState(card=card(language), belief=belief(top, p),
                         transcript=Transcript(mission_id="m_wb", turns=turns, disclosed_ai=True), moves=moves)


def after_why(top, p=0.8, reply="Isliye band kiya."):
    return state((ASK_WHY, reply), top=top, p=p)


def choose(s):
    return RuleBasedPlanner(BANK).choose(s)


# ── Listen first ─────────────────────────────────────────────────────────


def test_after_the_disclosure_chanakya_asks_why_they_stopped_before_anything_else():
    s = state(top="device_issue", p=0.9)  # even a confident prior is not a reason until they answer
    move, rule = choose(s)
    assert (move.type, rule) == (MoveType.DISCOVER_NEED, "winback_ask_why")
    for pitch in (Move(type=MoveType.RECOMMEND, product="soundbox"),
                  Move(type=MoveType.RESOLVE_CONCERN, concern="device_issue"),
                  Move(type=MoveType.CONFIRM_CONSENT, tool="raise_ticket"),
                  Move(type=MoveType.TAKE_ACTION, tool="get_settlement_status")):
        assert "winback_listen_first" in lib.violations(pitch, s, BANK)
    text = asyncio.run(TemplateRealizer(BANK).realize(move, s))
    assert "pehle" in text and "kyon band" in text and "?" in text


def test_an_unclear_reason_is_probed_at_most_twice_then_the_top_reason_is_acted_on():
    vague = after_why("device_issue", p=0.35)
    first, rule = choose(vague)
    assert rule == "winback_probe" and first.type == MoveType.PROBE_CONCERN
    twice = state((ASK_WHY, "Pata nahi."), (first, "Hmm."),
                  (Move(type=MoveType.PROBE_CONCERN, concern="settlement_delay"), "Hmm."), top="device_issue", p=0.35)
    move, rule = choose(twice)
    assert (move.type, move.tool, rule) == (MoveType.CONFIRM_CONSENT, "raise_ticket", "winback_fix")


def test_a_product_pitch_is_never_legal_on_a_win_back_call():
    s = after_why("device_issue")
    assert "winback_no_product_pitch" in lib.violations(Move(type=MoveType.RECOMMEND, product="soundbox"), s, BANK)


# ── Act on the reason ────────────────────────────────────────────────────


@pytest.mark.parametrize("reason,expected", [
    ("device_issue", (MoveType.CONFIRM_CONSENT, "raise_ticket", None)),
    ("settlement_delay", (MoveType.TAKE_ACTION, "get_settlement_status", None)),
    ("rental_cost", (MoveType.RESOLVE_CONCERN, None, None)),
    ("hidden_charges", (MoveType.RESOLVE_CONCERN, None, None)),
    ("per_swipe_charges", (MoveType.RESOLVE_CONCERN, None, None)),
    ("competitor_qr", (MoveType.RESOLVE_CONCERN, None, None)),
    ("not_needed", (MoveType.END_CALL_POLITELY, None, EndReason.NOT_NEEDED)),
    ("customers_pay_cash", (MoveType.END_CALL_POLITELY, None, EndReason.NOT_NEEDED)),
    ("just_busy", (MoveType.SCHEDULE_FOLLOWUP, None, None)),
])
def test_each_reason_gets_its_own_next_step(reason, expected):
    s = after_why(reason)
    move, _ = choose(s)
    assert (move.type, move.tool, move.end_reason) == expected
    assert move.args.get("reason") == reason  # the reason is locked once Chanakya acts on it
    assert lib.is_legal(move, s, BANK)


def test_settlement_is_read_then_explained_with_only_what_the_system_returned():
    read = Move(type=MoveType.TAKE_ACTION, tool="get_settlement_status", args={"reason": "settlement_delay"})
    s = after_why("settlement_delay")
    assert "winback_read_first" in lib.violations(Move(type=MoveType.CONFIRM_CONSENT, tool="raise_ticket"), s, BANK)
    data = {"settlements": [{"amount_inr": 9300, "status": "delayed", "expected_on": "2026-10-03",
                             "note": "bank account details mismatch"}]}
    s.actions.append(ActionDecision(call=ToolCall(tool="get_settlement_status"), verdict="executed", reason="ok",
                                    result=ToolResult(call_id="c", ok=True, data=data)))
    for language in ("hi-IN", "en-IN"):
        s.card = card(language)
        text = asyncio.run(TemplateRealizer(BANK).realize(read, s))
        assert "delayed" in text and "2026-10-03" in text and "mismatch" in text and "9300" not in text
        assert safety_violations(text) == []
    s.moves.append(read)
    move, rule = choose(s)
    assert (move.type, move.tool, rule) == (MoveType.CONFIRM_CONSENT, "raise_ticket", "winback_fix")


def test_charges_are_answered_from_sources_once_then_a_visit_needs_its_own_yes():
    answer = Move(type=MoveType.RESOLVE_CONCERN, concern="rental_cost", args={"reason": "rental_cost"})
    s = state((ASK_WHY, "Rent zyada lagta tha."), (answer, "Achha."), top="rental_cost")
    move, rule = choose(s)
    assert (move.type, move.tool, rule) == (MoveType.CONFIRM_CONSENT, "book_field_visit", "winback_fix")
    assert "winback_answer_once" in lib.violations(answer, s, BANK)
    for language in ("hi-IN", "en-IN"):
        s.card = card(language)
        for line in (asyncio.run(TemplateRealizer(BANK).realize(answer, s)),
                     asyncio.run(TemplateRealizer(BANK).realize(move, s))):
            assert safety_violations(line) == [] and not OFFER.search(line), line
    assert "technician" not in asyncio.run(TemplateRealizer(BANK).realize(move, s)).lower()


def test_a_competitor_choice_is_answered_once_and_then_accepted():
    answer = Move(type=MoveType.RESOLVE_CONCERN, concern="competitor_qr", args={"reason": "competitor_qr"})
    s = state((ASK_WHY, "Doosri company ka QR le liya."), (answer, "Nahi, wahi theek hai."), top="competitor_qr")
    move, rule = choose(s)
    assert (move.type, move.end_reason, rule) == (MoveType.END_CALL_POLITELY, EndReason.ACCEPTED_CHOICE,
                                                  "winback_accept_choice")


def test_not_needed_allows_nothing_but_a_polite_goodbye():
    s = after_why("not_needed", reply="Zaroorat hi nahi thi.")
    for move in (Move(type=MoveType.RESOLVE_CONCERN, concern="not_needed"),
                 Move(type=MoveType.CONFIRM_CONSENT, tool="send_summary"),
                 Move(type=MoveType.PROBE_CONCERN, concern="not_needed"),
                 Move(type=MoveType.SCHEDULE_FOLLOWUP)):
        assert "winback_not_needed" in lib.violations(move, s, BANK)
    move, _ = choose(s)
    for language in ("hi-IN", "en-IN"):
        s.card = card(language)
        text = asyncio.run(TemplateRealizer(BANK).realize(move, s))
        assert safety_violations(text) == [] and "official" not in text.lower()


@pytest.mark.parametrize("text,move_type", [
    ("Mera payment fail ho gaya, ghar pe sab bahut pareshan hain, kisi insaan se baat karao.", MoveType.ESCALATE),
    ("Nahi chahiye, call mat karo.", MoveType.END_CALL_POLITELY),
])
def test_distress_and_a_decline_behave_as_on_every_call(text, move_type):
    move, _ = choose(after_why("device_issue", reply=text))
    assert move.type == move_type


def test_the_consented_fix_runs_even_if_the_yes_shifts_the_belief():
    ask = Move(type=MoveType.CONFIRM_CONSENT, tool="raise_ticket", args={"reason": "device_issue"})
    s = state((ASK_WHY, "Machine kharab thi."), (ask, "Haan ji, ticket bana dijiye."), top="hidden_charges", p=0.6)
    s.transcript.consents.append(ConsentRecord(tool="raise_ticket", turn_index=len(s.transcript.turns) - 1,
                                               utterance="Haan ji, ticket bana dijiye."))
    move, rule = choose(s)
    assert (move.type, move.tool, rule) == (MoveType.TAKE_ACTION, "raise_ticket", "consent_given")
    assert lib.is_legal(move, s, BANK)


@pytest.mark.parametrize("reason", sorted(lib.WINBACK_FIX_TOOLS) + sorted(lib.NO_NEED_REASONS) + ["competitor_qr"])
def test_the_look_ahead_planner_follows_the_same_win_back_rules(reason):
    s = after_why(reason)
    rules = asyncio.run(RuleBasedPlanner(BANK).plan(s)).move
    searched = asyncio.run(NRPAPlanner(BANK, seed=3).plan(s)).move
    assert searched.key() == rules.key() and searched.type != MoveType.RECOMMEND
    assert all(m.type != MoveType.RECOMMEND for m in lib.legal_moves(s, BANK, "soundbox", "raise_ticket"))


# ── Realizer: no offers, no em dash ──────────────────────────────────────


@pytest.mark.parametrize("language", ["hi-IN", "en-IN", "pa-IN"])
def test_every_win_back_line_is_safe(language):
    realizer = TemplateRealizer(BANK)
    s = after_why("rental_cost", reply="Rent zyada tha.")
    s.card = card(language)
    lines = [asyncio.run(realizer.realize(m, s)) for m in (
        ASK_WHY, Move(type=MoveType.CONFIRM_CONSENT, tool="raise_ticket"),
        Move(type=MoveType.CONFIRM_CONSENT, tool="book_field_visit"),
        Move(type=MoveType.TAKE_ACTION, tool="get_settlement_status"),
        Move(type=MoveType.END_CALL_POLITELY, end_reason=EndReason.NOT_NEEDED),
        Move(type=MoveType.END_CALL_POLITELY, end_reason=EndReason.ACCEPTED_CHOICE))]
    for line in lines:
        assert line and safety_violations(line) == [] and "—" not in line and not OFFER.search(line), line


def test_an_llm_line_that_mentions_an_offer_falls_back_to_the_template():
    llm = FakeLLM(json.dumps({"text": "Aapke liye ek special discount hai, wapas aa jaiye!"}))
    s = state(top="device_issue")
    text = asyncio.run(LLMRealizer(llm, BANK).realize(ASK_WHY, s))
    assert not OFFER.search(text) and "kyon band" in text


# ── Simulated former customers ───────────────────────────────────────────


def test_former_customers_are_in_both_splits_and_kept_out_of_sales_evaluations():
    former = load_personas(relationship="former")
    assert {p.split for p in former} == {"planning", "evaluation"}
    assert all(p.hidden_concerns[0] in BANK.concerns and not p.adversarial for p in former)
    assert not [p for p in load_personas(split="evaluation") if p.relationship == "former"]


def test_a_former_twin_tells_its_reason_when_asked_and_takes_the_right_fix():
    persona = Persona(persona_id="t_former", business_type="kirana", city="Patna", language="hi-IN", patience=0.8,
                      busyness=0.3, tech_comfort=0.5, hidden_concerns=["device_issue"], willingness_prior=0.4,
                      split="evaluation", relationship="former")
    told = 0
    for seed in range(40):
        twin = initial_state(persona)
        judge_turn(twin, GREET, "", random.Random(seed))
        told += judge_turn(twin, ASK_WHY, "", random.Random(seed)).concern == "device_issue"
    assert told >= 24
    twin = initial_state(persona)
    yes = [judge_turn(initial_state(persona), Move(type=MoveType.CONFIRM_CONSENT, tool="raise_ticket"), "",
                      random.Random(seed)).kind for seed in range(20)]
    assert yes.count("agree") >= 10
    no_need = initial_state(persona.model_copy(update={"hidden_concerns": ["not_needed"]}))
    assert judge_turn(no_need, Move(type=MoveType.CONFIRM_CONSENT, tool="raise_ticket"), "", random.Random(0)).kind \
        == "decline"
