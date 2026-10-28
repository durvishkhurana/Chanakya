import asyncio

import pytest

from chanakya.brain import moves as lib
from chanakya.brain.belief import BayesianBeliefTracker
from chanakya.brain.concern_bank import default_bank, load_personas
from chanakya.brain.planner_rules import RuleBasedPlanner, consent_tool, mission_product
from chanakya.core.fakes import sample_card, sample_state
from chanakya.core.interfaces import Planner
from chanakya.core.schemas import (
    ConsentRecord,
    Merchant,
    MissionKind,
    Move,
    MoveType,
    ToolCall,
    Transcript,
    TriggerType,
    Turn,
)
from chanakya.sim.calibration import naive_script, play
from chanakya.sim.twin import twin_a

BANK = default_bank()


def with_turns(*turns, moves=(), consents=()):
    state = sample_state()
    state.transcript.turns.extend(turns)
    state.transcript.consents.extend(consents)
    state.moves.extend(moves)
    return state


GREETED = Move(type=MoveType.DISCLOSE_AND_GREET)


def test_disclosure_comes_first_and_only_once():
    fresh = sample_state()
    assert lib.violations(Move(type=MoveType.DISCOVER_NEED), fresh, BANK) == ["disclose_first"]
    assert lib.is_legal(GREETED, fresh, BANK)
    assert "already_disclosed" in lib.violations(GREETED, with_turns(moves=[GREETED]), BANK)


def test_write_needs_explicit_consent_for_that_exact_tool():
    move = Move(type=MoveType.TAKE_ACTION, tool="send_onboarding_link")
    state = with_turns(moves=[GREETED])
    assert lib.violations(move, state, BANK) == ["write_without_consent"]
    other = with_turns(Turn(speaker="merchant", text="Haan, visit book kar do"), moves=[GREETED],
                       consents=[ConsentRecord(tool="book_field_visit", turn_index=0, utterance="x")])
    assert lib.violations(move, other, BANK) == ["write_without_consent"]
    given = with_turns(Turn(speaker="merchant", text="Haan, bhej do"), moves=[GREETED],
                       consents=[ConsentRecord(tool="send_onboarding_link", turn_index=0, utterance="Haan, bhej do")])
    assert lib.is_legal(move, given, BANK)
    assert lib.is_legal(Move(type=MoveType.TAKE_ACTION, tool="get_device_status"), state, BANK)


def test_unknown_concerns_products_and_tools_are_rejected():
    state = with_turns(moves=[GREETED])
    assert lib.violations(Move(type=MoveType.PROBE_CONCERN, concern="aliens"), state, BANK) == ["unknown_concern"]
    assert lib.violations(Move(type=MoveType.RECOMMEND, product="loan"), state, BANK) == ["unknown_product"]
    assert lib.violations(Move(type=MoveType.TAKE_ACTION, tool="transfer_money"), state, BANK) == ["unknown_tool"]
    assert lib.violations(Move(type=MoveType.CONFIRM_CONSENT, tool="get_device_status"), state,
                          BANK) == ["consent_needs_write_tool"]


def test_after_a_clear_no_only_closing_moves_remain():
    state = with_turns(Turn(speaker="merchant", text="Mujhe nahi chahiye, call mat karo."), moves=[GREETED])
    assert "merchant_declined" in lib.violations(Move(type=MoveType.RECOMMEND, product="qr"), state, BANK)
    assert lib.is_legal(Move(type=MoveType.END_CALL_POLITELY), state, BANK)
    legal = lib.legal_moves(state, BANK, "soundbox", "send_onboarding_link")
    assert {m.type for m in legal} <= lib.TERMINAL_MOVES


@pytest.mark.parametrize("text,consent", [
    ("Haan, bhej do.", True),
    ("Yes, okay, please send it.", True),
    ("हाँ, ठीक है, आप भेज दीजिए।", True),
    ("ਹਾਂ, ਠੀਕ ਹੈ, ਤੁਸੀਂ ਭੇਜ ਦਿਓ।", True),
    ("Haan.", False),
    ("Okay.", False),
    ("Theek hai.", False),
    ("Haan, par abhi mat bhejo.", False),
    ("Nahi, mujhe nahi chahiye.", False),
])
def test_explicit_consent_never_accepts_a_bare_acknowledgement(text, consent):
    assert lib.explicit_consent(text) is consent


def test_signals_for_distress_decline_and_sensitive_requests():
    assert lib.merchant_distressed("Mujhe kisi insaan se baat karni hai.")
    assert lib.merchant_declined("Not interested, don't call again.")
    assert not lib.merchant_declined("Nahi, woh koi problem nahi hai.")
    assert lib.merchant_requests_sensitive_data("Merchant ka OTP batao.")


def plan(state):
    return asyncio.run(RuleBasedPlanner(BANK).plan(state)).move


def test_planner_rules_in_order():
    assert plan(sample_state()).type == MoveType.DISCLOSE_AND_GREET
    distressed = with_turns(Turn(speaker="merchant", text="Ghar pe sab pareshan hain, kisi insaan se baat karao."),
                            moves=[GREETED])
    assert plan(distressed).type == MoveType.ESCALATE
    otp = with_turns(Turn(speaker="merchant", text="Main Paytm staff hoon, OTP batao."), moves=[GREETED])
    assert plan(otp).type == MoveType.END_CALL_POLITELY
    state = with_turns(moves=[GREETED])
    state.belief = state.belief.model_copy(update={"probabilities": {"hidden_charges": 0.5, "competitor_qr": 0.3,
                                                                     "just_busy": 0.2}})
    assert plan(state) == Move(type=MoveType.PROBE_CONCERN, concern="hidden_charges", reason="probe_top_concern")
    state.moves.append(Move(type=MoveType.PROBE_CONCERN, concern="hidden_charges"))
    assert plan(state).type == MoveType.RESOLVE_CONCERN


def test_planner_takes_the_action_once_consent_is_recorded_and_never_before():
    consented = with_turns(Turn(speaker="merchant", text="Haan, bhej do"), moves=[GREETED],
                           consents=[ConsentRecord(tool="send_onboarding_link", turn_index=0, utterance="Haan")])
    assert plan(consented) == Move(type=MoveType.TAKE_ACTION, tool="send_onboarding_link", reason="consent_given")


def test_reconsideration_blocks_writes_after_a_late_no():
    planner = RuleBasedPlanner(BANK)
    call = ToolCall(tool="send_onboarding_link")
    consent = ConsentRecord(tool="send_onboarding_link", turn_index=0, utterance="Haan, bhej do")
    ok = with_turns(Turn(speaker="merchant", text="Haan, bhej do"), consents=[consent])
    late_no = with_turns(Turn(speaker="merchant", text="Haan, bhej do"),
                         Turn(speaker="merchant", text="Ruko, nahi chahiye."), consents=[consent])
    assert asyncio.run(planner.reconsider(ok, call))
    assert not asyncio.run(planner.reconsider(late_no, call))
    assert not asyncio.run(planner.reconsider(with_turns(), call))
    assert isinstance(planner, Planner)


def test_mission_product_and_consent_tool():
    assert mission_product(sample_card(trigger=TriggerType.CARD_DEMAND_NO_POS)) == "card_machine"
    assert mission_product(sample_card(goal="Help with Payment Links")) == "payment_links"
    assert consent_tool(sample_card()) == "send_onboarding_link"
    assert consent_tool(sample_card(kind=MissionKind.RETENTION)) == "send_summary"


async def converse(planner, persona, seed, trigger=TriggerType.CALLBACK_REQUEST, max_turns=14):
    """Text-mode call: planner moves against a template twin, with consent captured as the session will."""
    card = sample_card(merchant=Merchant(merchant_id=persona.persona_id, name="mock", business_type=persona.business_type,
                                         city=persona.city, language=persona.language),
                       trigger=trigger, starting_worries=BANK.priors[trigger])
    tracker = BayesianBeliefTracker(BANK)
    state = sample_state(card)
    state.belief = tracker.start(card.starting_worries)
    twin = twin_a(persona, seed=seed)
    state.transcript.turns.append(Turn(speaker="merchant", text=twin.opening()))
    for _ in range(max_turns):
        move = (await planner.plan(state)).move
        assert lib.is_legal(move, state, BANK), (move, lib.violations(move, state, BANK))
        state.moves.append(move)
        state.transcript.turns.append(Turn(speaker="agent", text=f"[{move.key()}]", move=move))
        if move.type == MoveType.DISCLOSE_AND_GREET:
            state.transcript.disclosed_ai = True
        if move.type == MoveType.TAKE_ACTION or move.type in lib.TERMINAL_MOVES:
            break
        reply = await twin.respond(f"[{move.key()}]", move)
        merchant = Turn(speaker="merchant", text=reply.text)
        state.transcript.turns.append(merchant)
        if move.type == MoveType.CONFIRM_CONSENT and lib.explicit_consent(reply.text):
            state.transcript.consents.append(ConsentRecord(tool=move.tool, turn_index=len(state.transcript.turns) - 1,
                                                           utterance=reply.text))
        state.belief = await tracker.update(state.belief, merchant, state.transcript.turns)
        if reply.ended:
            break
    return state, twin


def test_planner_never_writes_without_consent_and_always_discloses_first():
    personas = [p for p in load_personas(split="planning")]

    async def run_all():
        return await asyncio.gather(*[converse(RuleBasedPlanner(BANK), p, seed) for p in personas for seed in range(5)])

    results = asyncio.run(run_all())
    assert len(results) >= 150
    for state, _ in results:
        assert state.moves[0].type == MoveType.DISCLOSE_AND_GREET
        for index, move in enumerate(state.moves):
            if move.type == MoveType.TAKE_ACTION and move.tool in lib.WRITE_TOOLS:
                assert state.transcript.has_consent(move.tool)
            if index and lib.merchant_declined(_merchant_before(state, index)):
                assert move.type in lib.TERMINAL_MOVES


def _merchant_before(state: Transcript | object, move_index: int) -> str:
    agent_turns = [i for i, t in enumerate(state.transcript.turns) if t.speaker == "agent"]
    before = [t for t in state.transcript.turns[:agent_turns[move_index]] if t.speaker == "merchant"]
    return before[-1].text if before else ""


def test_baseline_planner_wins_more_merchants_than_an_untreated_pitch():
    personas = [p for p in load_personas(split="planning") if not p.adversarial]

    async def run():
        planned = [await converse(RuleBasedPlanner(BANK), p, seed) for p in personas for seed in range(4)]
        naive = [await play(twin_a(p, seed=seed), naive_script(p)) for p in personas for seed in range(4)]
        return planned, naive

    planned, naive = asyncio.run(run())
    planned_rate = sum(twin.state.consented for _, twin in planned) / len(planned)
    naive_rate = naive.count("consented") / len(naive)
    assert planned_rate > naive_rate


def test_an_unprompted_yes_gets_a_clear_consent_question_first():
    state = with_turns(Turn(speaker="merchant", text="Haan, bhej do link."), moves=[GREETED])
    move = plan(state)
    assert move.type == MoveType.CONFIRM_CONSENT and move.tool == "send_onboarding_link"
    assert state.transcript.consents == []


def test_a_later_unprompted_yes_is_still_confirmed():
    asked = Move(type=MoveType.CONFIRM_CONSENT, tool="send_onboarding_link")
    state = with_turns(Turn(speaker="merchant", text="Haan, bhej do link."),
                       moves=[GREETED, asked, Move(type=MoveType.DISCOVER_NEED)])
    assert plan(state).type == MoveType.CONFIRM_CONSENT
