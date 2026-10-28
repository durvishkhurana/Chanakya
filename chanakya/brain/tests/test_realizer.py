import asyncio
import json

import pytest

from chanakya.brain.concern_bank import default_bank
from chanakya.brain.moves import PRODUCTS
from chanakya.brain.realizer import LLMRealizer, TemplateRealizer, evidence_nodes, knowledge_texts
from chanakya.core.fakes import FakeLLM, sample_card, sample_state
from chanakya.core.interfaces import Realizer
from chanakya.core.llm import LLMError
from chanakya.core.schemas import Merchant, Move, MoveType
from chanakya.sim.judge import safety_violations

BANK = default_bank()


def every_move():
    moves = [Move(type=t) for t in (MoveType.DISCLOSE_AND_GREET, MoveType.DISCOVER_NEED, MoveType.SCHEDULE_FOLLOWUP,
                                    MoveType.ESCALATE, MoveType.END_CALL_POLITELY)]
    moves.append(Move(type=MoveType.END_CALL_POLITELY, reason="refused sensitive data request"))
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
    refusal = asyncio.run(realizer.realize(Move(type=MoveType.END_CALL_POLITELY, reason="refused sensitive data"),
                                           state_in("hi-IN")))
    assert "OTP" in refusal


def test_action_line_never_claims_an_action_that_did_not_run():
    realizer = TemplateRealizer(BANK)
    text = asyncio.run(realizer.realize(Move(type=MoveType.TAKE_ACTION, tool="send_onboarding_link"),
                                        state_in("en-IN")))
    assert "can't" in text


def test_evidence_nodes_follow_concern_and_product():
    assert evidence_nodes(Move(type=MoveType.RESOLVE_CONCERN, concern="rental_cost"), BANK) == ["onboarding", "soundbox"]
    assert evidence_nodes(Move(type=MoveType.RECOMMEND, product="gateway"), BANK) == ["gateway"]
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
    assert "soundbox-devices" in seen["prompt"] and "Never request OTPs" in seen["prompt"]
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


def test_llm_realizer_falls_back_when_the_model_is_down():
    def broken(role, messages):
        raise LLMError("down")

    text = asyncio.run(LLMRealizer(FakeLLM(broken), BANK).realize(Move(type=MoveType.DISCOVER_NEED), state_in("en-IN")))
    assert text.startswith("How do your customers pay")


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
