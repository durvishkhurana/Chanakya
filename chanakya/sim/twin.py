"""Simulated merchants: Twin-A for planning and Twin-B for held-out evaluation."""

import random

from chanakya.brain.concern_bank import ConcernBank, default_bank
from chanakya.core.llm import LLMClient
from chanakya.core.schemas import Move, Persona, TwinReply

from .judge import TwinState, initial_state, judge_turn
from .voice import LLMVoice, TemplateVoice


class SimulatedMerchant:
    """Implements ``MerchantTwin``: the judge decides, the voice speaks, the seed fixes every choice."""

    def __init__(self, persona: Persona, voice, seed: int = 0, name: str = "twin"):
        self.persona = persona
        self.voice = voice
        self.name = name
        self.rng = random.Random(f"{seed}:{persona.persona_id}")
        self.state: TwinState = initial_state(persona)
        self.history: list[tuple[str, str]] = []

    def opening(self) -> str:
        """The merchant's first words when the call connects."""
        text = self.voice.opening(self.persona, self.rng)
        self.history.append(("merchant", text))
        return text

    async def respond(self, agent_text: str, move: Move | None) -> TwinReply:
        """React to one agent turn and return the reply with the merchant's hidden state."""
        if self.state.ended:
            return self._reply("")
        self.history.append(("agent", agent_text))
        intent = judge_turn(self.state, move, agent_text, self.rng)
        text = await self.voice.say(self.persona, intent, agent_text, self.rng)
        self.history.append(("merchant", text))
        return self._reply(text)

    def _reply(self, text: str) -> TwinReply:
        return TwinReply(text=text, willingness=self.state.willingness, patience=self.state.patience,
                         ended=self.state.ended, consented=self.state.consented, resolved=list(self.state.resolved))


def twin_a(persona: Persona, llm: LLMClient | None = None, seed: int = 0,
           bank: ConcernBank | None = None) -> SimulatedMerchant:
    """Planning twin on the fast model. Without ``llm`` it speaks from templates, which the planner uses."""
    bank = bank or default_bank()
    voice = LLMVoice(llm, "twin_a", bank) if llm is not None else TemplateVoice(bank)
    return SimulatedMerchant(persona, voice, seed, name="twin_a")


def twin_b(persona: Persona, llm: LLMClient | None = None, seed: int = 0,
           bank: ConcernBank | None = None) -> SimulatedMerchant:
    """Evaluation twin on a different model family; refuses planning personas so evaluation stays held out."""
    if persona.split != "evaluation":
        raise ValueError(f"Twin-B only plays held-out evaluation personas, not {persona.persona_id}")
    bank = bank or default_bank()
    voice = LLMVoice(llm, "twin_b", bank) if llm is not None else TemplateVoice(bank)
    return SimulatedMerchant(persona, voice, seed, name="twin_b")
