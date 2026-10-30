"""The four agent variants compared in docs/IDEA.md section 4, behind one turn-by-turn interface."""

import time
from dataclasses import dataclass, field

from agent.brain_agent import BrainAgent
from chanakya.brain import moves as lib
from chanakya.brain.belief import LexicalScorer
from chanakya.brain.concern_bank import ConcernBank, default_bank
from chanakya.brain.contracts.fakes import FakeSafetyGate
from chanakya.brain.contracts.schemas import (
    ActionDecision,
    ConsentRecord,
    DialogueState,
    MissionCard,
    Move,
    MoveType,
    ToolCall,
    Transcript,
    Turn,
)
from chanakya.brain.planner_nrpa import NRPAPlanner
from chanakya.brain.planner_rules import consent_tool, mission_product
from chanakya.brain.realizer import LINES, TemplateRealizer, template_language

VARIANTS = ("reactive", "actions_only", "chanakya", "chanakya_no_belief")


@dataclass
class AgentTurn:
    """What a variant said this turn, the move it declares (if any), and what it did."""

    text: str
    move: Move | None
    latency_ms: float
    actions: list[ActionDecision] = field(default_factory=list)


class NullScorer:
    """Ablation: no evidence from the merchant's words, so the belief stays at the card's prior."""

    async def score(self, text: str, history: list[Turn]) -> dict[str, float]:
        return {}


class CountingLLM:
    """Wraps an LLM client and counts calls, for calls-per-completed-mission."""

    def __init__(self, llm):
        self.llm = llm
        self.calls = 0

    async def complete(self, role, messages, **kwargs):
        self.calls += 1
        return await self.llm.complete(role, messages, **kwargs)


class BrainVariant:
    """Chanakya (belief, look-ahead planner, realizer, gated mock actions) or its no-belief ablation."""

    def __init__(self, name: str, llm=None, planner=None, belief: bool = True, scorer=None):
        self.name = name
        self.agent = BrainAgent(llm=llm, planner=planner or NRPAPlanner(), gate=FakeSafetyGate(),
                                actions_enabled=True, scorer=scorer if belief else NullScorer())
        self.thread = "eval"

    async def open(self, card: MissionCard) -> None:
        self.agent.start(self.thread, card)

    @property
    def state(self) -> DialogueState:
        return self.agent.threads[self.thread]

    async def turn(self, merchant_text: str) -> AgentTurn:
        started, before = time.perf_counter(), len(self.state.actions)
        text = await self.agent.respond(merchant_text, self.thread, self.state.card.merchant.language)
        return AgentTurn(text, self.state.moves[-1], (time.perf_counter() - started) * 1000,
                         list(self.state.actions[before:]))


class ReactiveVariant:
    """Answers what it hears and never plans. ``actions`` adds consent requests and gated mock actions.

    Offline it speaks reviewed template lines; with ``llm_agent`` (the original retrieval agent) it
    speaks free text, which the harness labels into moves exactly as it does for every variant.
    """

    def __init__(self, name: str, actions: bool, bank: ConcernBank | None = None, llm_agent=None):
        self.name, self.actions = name, actions
        self.bank = bank or default_bank()
        self.scorer = LexicalScorer(self.bank)
        self.templates = TemplateRealizer(self.bank)
        self.llm_agent = llm_agent
        self.gate = FakeSafetyGate()
        self.state: DialogueState | None = None
        self.errors = 0

    async def open(self, card: MissionCard) -> None:
        from chanakya.brain.contracts.schemas import BeliefState

        self.state = DialogueState(card=card, belief=BeliefState(probabilities=dict(card.starting_worries)),
                                   transcript=Transcript(mission_id=card.mission_id))

    def _move(self, merchant_text: str, scores: dict[str, float]) -> Move:
        state, tool = self.state, consent_tool(self.state.card, self.state)
        agent_turns = sum(1 for t in state.transcript.turns if t.speaker == "agent")
        if agent_turns == 0:
            return Move(type=MoveType.DISCLOSE_AND_GREET)
        if self.actions and state.transcript.has_consent(tool) and not state.actions:
            return Move(type=MoveType.TAKE_ACTION, tool=tool)
        if lib.merchant_declined(merchant_text):
            return Move(type=MoveType.END_CALL_POLITELY)
        top, score = max(scores.items(), key=lambda item: item[1], default=(None, 0.0))
        if top and score >= 0.3:
            return Move(type=MoveType.RESOLVE_CONCERN, concern=top)
        if self.actions and agent_turns % 2 == 0:
            return Move(type=MoveType.CONFIRM_CONSENT, tool=tool)
        if agent_turns % 2:
            return Move(type=MoveType.RECOMMEND, product=mission_product(state.card))
        return Move(type=MoveType.DISCOVER_NEED)

    async def turn(self, merchant_text: str) -> AgentTurn:
        started, state = time.perf_counter(), self.state
        state.transcript.turns.append(Turn(speaker="merchant", text=merchant_text))
        last = state.moves[-1] if state.moves else None
        if last and last.type == MoveType.CONFIRM_CONSENT and lib.explicit_consent(merchant_text):
            state.transcript.consents.append(ConsentRecord(tool=last.tool, turn_index=len(state.transcript.turns) - 1,
                                                           utterance=merchant_text))
        move = self._move(merchant_text, await self.scorer.score(merchant_text, state.transcript.turns))
        actions = []
        if move.type == MoveType.TAKE_ACTION:
            decision = await self.gate.check(ToolCall(tool=move.tool, mission_id=state.card.mission_id), state)
            state.actions.append(decision)
            actions.append(decision)
        if self.llm_agent is not None and move.type not in {MoveType.CONFIRM_CONSENT, MoveType.TAKE_ACTION}:
            text = await self._free_text(merchant_text)
            move = None
        else:
            text = await self.templates.realize(move, state)
            if self.llm_agent is not None and move.type == MoveType.CONFIRM_CONSENT:
                label = template_language(state.card.merchant.language)
                text = LINES[label].get(f"consent_{move.tool}", LINES[label]["consent_other"])
        state.moves.append(move or Move(type=MoveType.DISCOVER_NEED, reason="free text"))
        state.transcript.turns.append(Turn(speaker="agent", text=text, move=move))
        return AgentTurn(text, move, (time.perf_counter() - started) * 1000, actions)

    async def _free_text(self, merchant_text: str) -> str:
        try:
            events = [e async for e in self.llm_agent.astream(merchant_text, config={"configurable": {
                "thread_id": self.state.card.mission_id, "response_language": self.state.card.merchant.language,
                "retrieval_provider": "llm_batch"}})]
        except Exception:  # noqa: BLE001 - A provider failure is one failed turn, not a failed evaluation.
            self.errors += 1
            return "Sorry, could you say that again?"
        return next((e["full_content"] for e in events if e["type"] == "done"), "")


def make_variant(name: str, llm=None, llm_agent=None):
    """Build a fresh variant for one call."""
    if name == "reactive":
        return ReactiveVariant(name, actions=False, llm_agent=llm_agent)
    if name == "actions_only":
        return ReactiveVariant(name, actions=True, llm_agent=llm_agent)
    if name == "chanakya":
        return BrainVariant(name, llm=llm)
    if name == "chanakya_no_belief":
        return BrainVariant(name, llm=llm, belief=False)
    if name == "chanakya_forest":
        from chanakya.brain.forest.forest import default_forest

        return BrainVariant(name, llm=llm, planner=NRPAPlanner(forest=default_forest()))
    if name == "chanakya_embedding":
        from chanakya.neural.scorer import load_embedding_scorer

        scorer = load_embedding_scorer()
        if scorer is None:  # an evaluation must never quietly fall back to the lexical scorer
            raise RuntimeError("chanakya_embedding needs the encoder and data/neural/worry_head.npz: "
                               "pip install -r requirements-neural.txt; python -m chanakya.neural.encoder --download; "
                               "python -m chanakya.neural.train_worry")
        return BrainVariant(name, llm=llm, scorer=scorer)
    raise ValueError(f"Unknown variant {name}")
