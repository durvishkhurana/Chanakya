import asyncio
import json

import pytest

from chanakya.brain.concern_bank import default_bank
from chanakya.brain.contracts.fakes import FakeLLM, sample_card, sample_state
from chanakya.brain.contracts.interfaces import Realizer
from chanakya.brain.contracts.llm import LLMError
from chanakya.brain.contracts.schemas import EndReason, Merchant, Move, MoveType, Turn
from chanakya.brain.moves import PRODUCTS
from chanakya.brain.realizer import LLMRealizer, TemplateRealizer, evidence_nodes, knowledge_texts, turn_nodes
from chanakya.sim.judge import safety_violations

BANK = default_bank()


def every_move():
    moves = [Move(type=t) for t in (MoveType.DISCLOSE_AND_GREET, MoveType.DISCOVER_NEED, MoveType.SCHEDULE_FOLLOWUP,
                                    MoveType.ESCALATE, MoveType.END_CALL_POLITELY)]
    moves.append(Move(type=MoveType.END_CALL_POLITELY, reason="refused sensitive data request",
                      end_reason=EndReason.SENSITIVE_REQUEST))
    for cid in BANK.ids:
        moves += [Move(type=MoveType.PROBE_CONCERN, concern=cid), Move(type=MoveType.RESOLVE_CONCERN, concern=cid)]
    moves += [Move(type=MoveType.RECOMMEND, product=p) for p in PRODUCTS]
    for tool in ("send_onboarding_link", "book_field_visit", "send_summary", "raise_ticket"):
        moves += [Move(type=MoveType.CONFIRM_CONSENT, tool=tool), Move(type=MoveType.TAKE_ACTION, tool=tool)]
    return moves


def state_in(language):
    card = sample_card(merchant=Merchant(merchant_id="m", name="mock", business_type="kirana", city="Jaipur",
                                         language=language))
    return sample_state(card)


@pytest.mark.parametrize("language", ["hi-IN", "en-IN", "pa-IN"])
def test_every_template_is_safe_and_non_empty(language):
    realizer = TemplateRealizer(BANK)
    state = state_in(language)
    for move in every_move():
        text = asyncio.run(realizer.realize(move, state))
        assert text and safety_violations(text) == [], (move.key(), text)


def test_greeting_discloses_ai_and_refusal_names_the_rule():
    realizer = TemplateRealizer(BANK)
    greeting = asyncio.run(realizer.realize(Move(type=MoveType.DISCLOSE_AND_GREET), state_in("en-IN")))
    assert "AI assistant" in greeting and "independent" in greeting
    refusal = asyncio.run(realizer.realize(Move(type=MoveType.END_CALL_POLITELY, end_reason=EndReason.SENSITIVE_REQUEST),
                                           state_in("hi-IN")))
    assert "OTP" in refusal


def test_action_line_never_claims_an_action_that_did_not_run():
    realizer = TemplateRealizer(BANK)
    text = asyncio.run(realizer.realize(Move(type=MoveType.TAKE_ACTION, tool="send_onboarding_link"),
                                        state_in("en-IN")))
    assert "can't" in text


def test_evidence_nodes_follow_concern_and_product():
    assert evidence_nodes(Move(type=MoveType.RESOLVE_CONCERN, concern="rental_cost"), BANK) == ["card_machine_plans", "onboarding", "soundbox",
                                                                                          "soundbox_models"]
    assert evidence_nodes(Move(type=MoveType.RECOMMEND, product="gateway"), BANK) == ["gateway", "pricing_online"]
    assert evidence_nodes(Move(type=MoveType.DISCOVER_NEED), BANK) == []
    assert set(knowledge_texts()) >= set(PRODUCTS)


def test_llm_realizer_grounds_the_prompt_and_strips_em_dashes():
    seen = {}

    def respond(role, messages):
        seen["role"], seen["prompt"] = role, messages[0]["content"]
        return json.dumps({"text": "Rent ki sahi jaankari official page par hai — main bata nahi sakta."})

    realizer = LLMRealizer(FakeLLM(respond), BANK)
    text = asyncio.run(realizer.realize(Move(type=MoveType.RESOLVE_CONCERN, concern="rental_cost"), state_in("hi-IN")))
    assert "—" not in text and text.startswith("Rent ki sahi")
    assert seen["role"] == "main"
    assert "voice payment confirmations" in seen["prompt"] and "Never request OTPs" in seen["prompt"]
    assert "soundbox-devices" not in seen["prompt"], "source URLs are stripped from the prompt"
    assert isinstance(realizer, Realizer)


@pytest.mark.parametrize("unsafe", [
    "Rent sirf Rs 99 hai, abhi le lo!",
    "Please share the OTP you received so I can verify.",
    "",
])
def test_llm_realizer_falls_back_to_the_template_on_unsafe_output(unsafe):
    realizer = LLMRealizer(FakeLLM(json.dumps({"text": unsafe})), BANK)
    move = Move(type=MoveType.RESOLVE_CONCERN, concern="hidden_charges")
    text = asyncio.run(realizer.realize(move, state_in("hi-IN")))
    assert text == asyncio.run(TemplateRealizer(BANK).realize(move, state_in("hi-IN")))
    assert realizer.last_fallback_reason


@pytest.mark.parametrize("move,line", [
    (Move(type=MoveType.RESOLVE_CONCERN, concern="settlement_delay"),
     "Paisa agle business day bank mein aata hai, aur Instant Settlement se Rs. 50 se upar kabhi bhi bhej sakte hain."),
    (Move(type=MoveType.RESOLVE_CONCERN, concern="per_swipe_charges"),
     "Kirana ke credit card par 1.40% aur RuPay debit par 0% lagta hai."),
    (Move(type=MoveType.RECOMMEND, product="qr"), "All-in-One QR Paytm for Business app se free milta hai."),
])
def test_llm_realizer_keeps_figures_found_in_the_evidence(move, line):
    realizer = LLMRealizer(FakeLLM(json.dumps({"text": line})), BANK)
    assert asyncio.run(realizer.realize(move, state_in("hi-IN"))) == line and not realizer.last_fallback_reason


@pytest.mark.parametrize("line", ["Instant Settlement sirf Rs 999 mein milta hai.", "Isme cashback bhi milega."])
def test_llm_realizer_still_rejects_figures_not_in_the_evidence(line):
    realizer = LLMRealizer(FakeLLM(json.dumps({"text": line})), BANK)
    move = Move(type=MoveType.RESOLVE_CONCERN, concern="settlement_delay")
    assert asyncio.run(realizer.realize(move, state_in("hi-IN"))) != line
    assert "overpromise" in realizer.last_fallback_reason


def test_llm_realizer_falls_back_when_the_model_is_down():
    def broken(role, messages):
        raise LLMError("down")

    text = asyncio.run(LLMRealizer(FakeLLM(broken), BANK).realize(Move(type=MoveType.DISCOVER_NEED), state_in("en-IN")))
    assert "How do your customers pay" in text and "calling about" in text


@pytest.mark.parametrize("claim", [
    "Main aapko official onboarding link bhej deta hoon.",
    "I'll send you the link right away.",
    "Maine link bhej diya hai.",
])
def test_claiming_an_action_that_did_not_run_falls_back(claim):
    realizer = LLMRealizer(FakeLLM(json.dumps({"text": claim})), BANK)
    move = Move(type=MoveType.RECOMMEND, product="soundbox")
    text = asyncio.run(realizer.realize(move, state_in("hi-IN")))
    assert "claims_action" in realizer.last_fallback_reason and text != claim


def test_a_consent_question_may_say_what_will_happen_if_they_agree():
    line = "Kya main official link bhej doon? Aap haan kahenge tabhi main bhej dunga."
    realizer = LLMRealizer(FakeLLM(json.dumps({"text": line})), BANK)
    text = asyncio.run(realizer.realize(Move(type=MoveType.CONFIRM_CONSENT, tool="send_onboarding_link"),
                                        state_in("hi-IN")))
    assert text == line


def test_a_consent_move_must_ask_not_announce():
    realizer = LLMRealizer(FakeLLM(json.dumps({"text": "Theek hai, main aapko official link bhej raha hoon."})), BANK)
    move = Move(type=MoveType.CONFIRM_CONSENT, tool="send_onboarding_link")
    text = asyncio.run(realizer.realize(move, state_in("hi-IN")))
    assert "?" in text and "consent_not_asked" in realizer.last_fallback_reason


def test_the_prompt_carries_the_mission_card_so_chanakya_can_say_why_it_called():
    seen = {}

    def respond(role, messages):
        seen["prompt"] = messages[0]["content"]
        return json.dumps({"text": "Main Soundbox ke baare mein call kar raha hoon. Grahak kaise payment karte hain?"})

    state = state_in("hi-IN")
    asyncio.run(LLMRealizer(FakeLLM(respond), BANK).realize(Move(type=MoveType.DISCOVER_NEED), state))
    assert state.card.why_now in seen["prompt"] and state.card.goal in seen["prompt"]
    assert "never mention lead lists" in seen["prompt"]



@pytest.mark.parametrize("line,expected", [
    ("Card pe kitna charge lagega?", "pricing_in_store"),
    ("पैसा बैंक में कब आएगा?", "settlement"),
    ("Battery kitni chalti hai?", "soundbox_models"),
    ("साउंड बॉक्स लेने का प्रोसेस क्या है?", "signup_kyc"),
])
def test_each_reply_gets_the_sections_the_merchant_asked_about(line, expected):
    state = state_in("hi-IN")
    state.transcript.turns.append(Turn(speaker="merchant", text=line))
    nodes = turn_nodes(Move(type=MoveType.DISCOVER_NEED), state, BANK)
    assert expected in nodes and len(nodes) <= 5
