"""A stalled LLM provider on a live call must give a safe line quickly, not silence (I3)."""

import asyncio
import time

from agent.brain_agent import BrainAgent, llm_timeout_s
from chanakya.brain.belief import LexicalScorer, LLMScorer
from chanakya.brain.concern_bank import default_bank
from chanakya.brain.contracts.fakes import sample_state
from chanakya.brain.contracts.schemas import Move, MoveType
from chanakya.brain.realizer import LLMRealizer, TemplateRealizer

BANK = default_bank()


class StalledLLM:
    """A provider that never answers in time."""

    async def complete(self, role, messages, **kwargs):
        await asyncio.sleep(30)
        return "{}"


def test_a_stalled_realizer_falls_back_to_the_template_within_the_bound():
    state, move = sample_state(), Move(type=MoveType.DISCLOSE_AND_GREET)
    realizer = LLMRealizer(StalledLLM(), BANK, timeout_s=0.05)
    started = time.perf_counter()
    text = asyncio.run(realizer.realize(move, state))
    assert time.perf_counter() - started < 2
    assert text == asyncio.run(TemplateRealizer(BANK).realize(move, state))
    assert realizer.last_fallback_reason == "empty"


def test_a_stalled_scorer_falls_back_to_lexical_evidence_within_the_bound():
    text = "Iska monthly rent kitna padega?"
    started = time.perf_counter()
    scores = asyncio.run(LLMScorer(StalledLLM(), BANK, timeout_s=0.05).score(text, []))
    assert time.perf_counter() - started < 2
    assert scores == asyncio.run(LexicalScorer(BANK).score(text, []))


def test_voice_calls_bound_llm_time_by_default_and_can_turn_it_off(monkeypatch):
    monkeypatch.delenv("VOICE_LLM_TIMEOUT_MS", raising=False)
    assert llm_timeout_s() == 4.0
    assert BrainAgent(llm=StalledLLM()).realizer.timeout_s == 4.0
    monkeypatch.setenv("VOICE_LLM_TIMEOUT_MS", "0")
    assert llm_timeout_s() is None
    monkeypatch.setenv("VOICE_LLM_TIMEOUT_MS", "not a number")
    assert llm_timeout_s() == 4.0
