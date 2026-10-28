"""Chanakya's planning voice agent: transcript -> belief -> planner -> realizer, behind PLANNER_ENABLED.

It exposes the same ``astream``/``forget_thread``/``aclose`` interface as ``agent.graph.Agent`` so the
voice session and phone transport can use either one unchanged.
"""

import asyncio

from chanakya.brain import moves as lib
from chanakya.brain.belief import BayesianBeliefTracker, LexicalScorer, LLMScorer
from chanakya.brain.concern_bank import default_bank
from chanakya.brain.planner_rules import RuleBasedPlanner
from chanakya.brain.realizer import LLMRealizer, TemplateRealizer
from chanakya.core.events import ActionDecided, PlanComputed, TurnCompleted
from chanakya.core.schemas import (
    ActionDecision,
    ConsentRecord,
    DialogueState,
    Door,
    Merchant,
    MissionCard,
    MissionKind,
    MoveType,
    ToolCall,
    Transcript,
    TriggerType,
    Turn,
)


def inbound_card(thread_id: str, language: str) -> MissionCard:
    """A Door 1 mission for someone who started a voice conversation with Chanakya."""
    bank = default_bank()
    return MissionCard(
        mission_id=f"call_{thread_id}",
        merchant=Merchant(merchant_id=f"caller_{thread_id}", name="Voice caller (demo)", business_type="unknown",
                          city="unknown", language=language),
        kind=MissionKind.SALES, goal="Help the caller choose a Paytm business payment product",
        door=Door.MERCHANT, trigger=TriggerType.CALLBACK_REQUEST, why_now="Caller started a conversation",
        starting_worries=bank.priors[TriggerType.CALLBACK_REQUEST],
    )


class BrainAgent:
    """Plans every reply as a typed move. Writes go through ``gate`` only with consent; without a gate they are blocked."""

    def __init__(self, llm=None, planner=None, realizer=None, bus=None, gate=None, actions_enabled=False):
        self.bank = default_bank()
        self.llm = llm
        self.planner = planner or RuleBasedPlanner(self.bank)
        self.realizer = realizer or (LLMRealizer(llm, self.bank) if llm is not None else TemplateRealizer(self.bank))
        self.scorer = LLMScorer(llm, self.bank) if llm is not None else LexicalScorer(self.bank)
        self.bus = bus
        self.gate = gate
        self.actions_enabled = actions_enabled
        self.threads: dict[str, DialogueState] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def state(self, thread_id: str, language: str) -> DialogueState:
        """The conversation state for ``thread_id``, created on first use."""
        if thread_id not in self.threads:
            card = inbound_card(thread_id, language)
            tracker = BayesianBeliefTracker(self.bank, scorer=self.scorer)
            self.threads[thread_id] = DialogueState(card=card, belief=tracker.start(card.starting_worries),
                                                    transcript=Transcript(mission_id=card.mission_id))
        return self.threads[thread_id]

    async def _act(self, state: DialogueState, tool: str) -> ActionDecision:
        call = ToolCall(tool=tool, args={"merchant_id": state.card.merchant.merchant_id},
                        mission_id=state.card.mission_id)
        if not await self.planner.reconsider(state, call):
            decision = ActionDecision(call=call, verdict="blocked", reason="reconsidered")
        elif self.gate is None or not self.actions_enabled:
            decision = ActionDecision(call=call, verdict="blocked", reason="actions_disabled")
        else:
            decision = await self.gate.check(call, state)
        state.actions.append(decision)
        if self.bus is not None:
            await self.bus.publish(ActionDecided(mission_id=state.card.mission_id, decision=decision))
        return decision

    async def respond(self, text: str, thread_id: str, language: str = "en-IN") -> str:
        """Fold in the merchant's words, plan one move, take it safely and return what Chanakya says."""
        lock = self._locks.setdefault(thread_id, asyncio.Lock())
        async with lock:
            state = self.state(thread_id, language)
            if state.card.merchant.language != language:
                merchant = state.card.merchant.model_copy(update={"language": language})
                state.card = state.card.model_copy(update={"merchant": merchant})
            turn = Turn(speaker="merchant", text=text, language=language)
            state.transcript.turns.append(turn)
            if state.moves and state.moves[-1].type == MoveType.CONFIRM_CONSENT and lib.explicit_consent(text):
                state.transcript.consents.append(ConsentRecord(
                    tool=state.moves[-1].tool, turn_index=len(state.transcript.turns) - 1, utterance=text))
            tracker = BayesianBeliefTracker(self.bank, scorer=self.scorer, bus=self.bus,
                                            mission_id=state.card.mission_id)
            state.belief = await tracker.update(state.belief, turn, state.transcript.turns)
            plan = await self.planner.plan(state)
            if self.bus is not None:
                await self.bus.publish(PlanComputed(mission_id=state.card.mission_id, plan=plan))
            move = plan.move
            if move.type == MoveType.TAKE_ACTION and move.tool in lib.WRITE_TOOLS:
                await self._act(state, move.tool)
            reply = await self.realizer.realize(move, state)
            agent_turn = Turn(speaker="agent", text=reply, language=language, move=move)
            state.moves.append(move)
            state.transcript.turns.append(agent_turn)
            if move.type == MoveType.DISCLOSE_AND_GREET:
                state.transcript.disclosed_ai = True
            if move.type in lib.TERMINAL_MOVES:
                state.ended = True
            if self.bus is not None:
                await self.bus.publish(TurnCompleted(mission_id=state.card.mission_id, turn=agent_turn,
                                                     belief=state.belief, move=move))
            return reply

    async def astream(self, query: str, config=None, **kwargs):
        """Yield the reply as one token event then ``done``, matching ``agent.graph.Agent.astream``."""
        configurable = (config or {}).get("configurable", {})
        reply = await self.respond(query, configurable.get("thread_id", "default"),
                                   configurable.get("response_language") or "en-IN")
        yield {"type": "token", "content": reply}
        yield {"type": "done", "full_content": reply, "tool_calls": []}

    async def forget_thread(self, thread_id: str) -> None:
        """Release a finished conversation."""
        self.threads.pop(thread_id, None)
        self._locks.pop(thread_id, None)

    async def aclose(self) -> None:
        """Close the LLM client if it has one."""
        close = getattr(self.llm, "aclose", None)
        if close is not None:
            await close()
