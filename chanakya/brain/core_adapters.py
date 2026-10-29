"""Expose the Track A brain through the shared ``chanakya.core`` protocols.

Track B's mission runtime speaks core types (``PlanContext``, core ``Move``, ``MissionEvent``); the
brain works on its own consent-aware ``DialogueState``. These adapters convert at the boundary so the
planner, belief tracker and realizer can be used by any module that codes against ``chanakya.core``.
"""

from chanakya.brain import moves as lib
from chanakya.brain.belief import BayesianBeliefTracker
from chanakya.brain.concern_bank import ConcernBank, default_bank
from chanakya.brain.contracts import events as brain_events
from chanakya.brain.contracts import schemas as brain
from chanakya.core import schemas as core

TRIGGERS = {
    core.SignalKind.CALLBACK_REQUEST: brain.TriggerType.CALLBACK_REQUEST,
    core.SignalKind.ONBOARDING_STALLED: brain.TriggerType.ONBOARDING_STUCK,
    core.SignalKind.PRICE_QUESTION_DROPPED: brain.TriggerType.CARD_MACHINE_PRICE_QUESTION,
    core.SignalKind.UPI_RISING_NO_SOUNDBOX: brain.TriggerType.UPI_RISING_NO_SOUNDBOX,
    core.SignalKind.CARD_ATTEMPTS_NO_POS: brain.TriggerType.CARD_DEMAND_NO_POS,
    core.SignalKind.SOUNDBOX_UNUSED: brain.TriggerType.SOUNDBOX_UNUSED,
    core.SignalKind.RENTAL_MISSED: brain.TriggerType.RENTAL_MISSED,
    core.SignalKind.LEAD_LIST_ASSIGNED: brain.TriggerType.LEAD_LIST,
    core.SignalKind.FIELD_AGENT_NOTE: brain.TriggerType.FIELD_NOTE,
    core.SignalKind.HUMAN_CALL_DROPPED: brain.TriggerType.DROPPED_CALL,
}
# Concern ids used by Track B's intake rules that the Concern Bank names differently.
CONCERN_ALIASES = {
    "swipe_charges": "per_swipe_charges",
    "device_reliability": "device_issue",
    "cash_flow": "rental_cost",  # a missed rental is treated as the cost worry until the bank has its own entry
}
SPEAKERS = {core.Speaker.AGENT: "agent", core.Speaker.MERCHANT: "merchant", core.Speaker.HUMAN: "human_agent"}


def concern_id(name: str | None) -> str | None:
    """The Concern Bank id for a concern name used anywhere in the system."""
    return CONCERN_ALIASES.get(name, name) if name else name


def worries(probabilities: dict[str, float], bank: ConcernBank) -> dict[str, float]:
    """Map core concern probabilities onto the Concern Bank, merging aliases and dropping unknown ids."""
    merged: dict[str, float] = {}
    for name, p in probabilities.items():
        cid = concern_id(name)
        if cid in bank.concerns:
            merged[cid] = merged.get(cid, 0.0) + p
    total = sum(merged.values())
    return {cid: p / total for cid, p in merged.items()} if total > 0 else bank.prior_for(brain.TriggerType.CALLBACK_REQUEST)


def to_brain_card(mission: core.Mission, bank: ConcernBank | None = None) -> brain.MissionCard:
    """The brain's view of a core mission."""
    bank = bank or default_bank()
    card = mission.card
    trigger = TRIGGERS[card.signal_kind]
    return brain.MissionCard(
        mission_id=mission.id,
        merchant=brain.Merchant(merchant_id=card.merchant_id, name=card.merchant_name, business_type="unknown",
                                city="unknown", language=card.language),
        kind=brain.MissionKind(card.mission_type.value), goal=card.goal, door=brain.Door(card.door.value),
        trigger=trigger, why_now=card.why_now,
        starting_worries=worries(card.starting_worries, bank) if card.starting_worries else bank.priors[trigger],
        chance=min(1.0, card.priority) if card.priority else 0.5, context=card.product or "",
    )


def to_brain_move(move: core.Move) -> brain.Move:
    """Core move -> brain move; a core ``tool_call`` names the move's tool."""
    tool = move.tool_call.tool if move.tool_call else None
    return brain.Move(type=brain.MoveType(move.type.value), concern=concern_id(move.concern_id),
                      product=move.product, tool=tool, reason=move.reason or "")


def to_core_move(move: brain.Move, mission_id: str) -> core.Move:
    """Brain move -> core move. ``TAKE_ACTION`` and ``CONFIRM_CONSENT`` carry the tool as a ``tool_call``."""
    call = None
    if move.tool:
        call = core.ToolCall(mission_id=mission_id, tool=move.tool, args=dict(move.args))
    return core.Move(type=core.MoveType(move.type.value), concern_id=move.concern, product=move.product,
                     tool_call=call, reason=move.reason or None)


def to_brain_state(context: core.PlanContext, bank: ConcernBank | None = None) -> brain.DialogueState:
    """Rebuild the brain's dialogue state from a core plan context.

    Moves come from the agent turns; consent is recorded only where the merchant gave an explicit yes
    right after the agent asked for it, exactly as the live agent records it.
    """
    bank = bank or default_bank()
    card = to_brain_card(context.mission, bank)
    turns, moves, consents, disclosed = [], [], [], False
    for turn in context.transcript.turns:
        move = to_brain_move(turn.move) if turn.move else None
        turns.append(brain.Turn(speaker=SPEAKERS[turn.speaker], text=turn.text, language=turn.language, move=move,
                                pause_before_ms=int(turn.cues["pause_ms"]) if "pause_ms" in turn.cues else None))
        if move is not None and turn.speaker != core.Speaker.MERCHANT:
            moves.append(move)
            disclosed = disclosed or move.type == brain.MoveType.DISCLOSE_AND_GREET
        if (turn.speaker == core.Speaker.MERCHANT and moves and moves[-1].type == brain.MoveType.CONFIRM_CONSENT
                and moves[-1].tool and lib.explicit_consent(turn.text)):
            consents.append(brain.ConsentRecord(tool=moves[-1].tool, turn_index=len(turns) - 1, utterance=turn.text))
    belief = brain.BeliefState(probabilities=worries(context.belief.probabilities, bank), turn_index=context.belief.turn)
    transcript = brain.Transcript(mission_id=card.mission_id, turns=turns, consents=consents, disclosed_ai=disclosed)
    return brain.DialogueState(card=card, belief=belief, transcript=transcript, moves=moves,
                               ended=not context.mission.is_open)


def to_core_belief(belief: brain.BeliefState) -> core.BeliefState:
    """Brain belief -> core belief."""
    return core.BeliefState(probabilities=dict(belief.probabilities), turn=belief.turn_index)


class CorePlanner:
    """Implements ``chanakya.core.interfaces.Planner`` around any Track A planner."""

    def __init__(self, planner, bank: ConcernBank | None = None):
        self.planner = planner
        self.bank = bank or default_bank()

    async def plan(self, context: core.PlanContext) -> core.PlanResult:
        result = await self.planner.plan(to_brain_state(context, self.bank))
        mission_id = context.mission.id
        return core.PlanResult(
            chosen=to_core_move(result.move, mission_id),
            candidates=[core.ScoredMove(move=to_core_move(c.move, mission_id), score=c.score, visits=c.visits)
                        for c in result.candidates],
            tree=result.tree, elapsed_ms=result.elapsed_ms, fallback=result.fallback,
        )

    async def reconsider(self, context: core.PlanContext, call: core.ToolCall) -> bool:
        brain_call = brain.ToolCall(tool=call.tool, args=dict(call.args), mission_id=call.mission_id)
        return await self.planner.reconsider(to_brain_state(context, self.bank), brain_call)


class CoreBeliefTracker:
    """Implements ``chanakya.core.interfaces.BeliefTracker`` around the Bayesian tracker."""

    def __init__(self, tracker: BayesianBeliefTracker | None = None, bank: ConcernBank | None = None):
        self.bank = bank or default_bank()
        self.tracker = tracker or BayesianBeliefTracker(self.bank)

    def initial(self, card: core.MissionCard) -> core.BeliefState:
        prior = worries(card.starting_worries, self.bank) if card.starting_worries else \
            self.bank.priors[TRIGGERS[card.signal_kind]]
        return to_core_belief(self.tracker.start(prior))

    async def update(self, belief: core.BeliefState, turn: core.Turn, transcript: core.Transcript) -> core.BeliefState:
        current = brain.BeliefState(probabilities=worries(belief.probabilities, self.bank), turn_index=belief.turn)
        history = [brain.Turn(speaker=SPEAKERS[t.speaker], text=t.text) for t in transcript.turns]
        brain_turn = brain.Turn(speaker=SPEAKERS[turn.speaker], text=turn.text, language=turn.language,
                                pause_before_ms=int(turn.cues["pause_ms"]) if "pause_ms" in turn.cues else None)
        return to_core_belief(await self.tracker.update(current, brain_turn, history))


class CoreRealizer:
    """Implements ``chanakya.core.interfaces.Realizer`` around a Track A realizer."""

    def __init__(self, realizer, bank: ConcernBank | None = None):
        self.realizer = realizer
        self.bank = bank or default_bank()

    async def realize(self, move: core.Move, context: core.PlanContext) -> str:
        return await self.realizer.realize(to_brain_move(move), to_brain_state(context, self.bank))


def to_ledger_event(event: brain_events.Event) -> core.MissionEvent | None:
    """A brain event as a core ledger event for Track B's bus and dashboards (``None`` if it has no core kind)."""
    mission_id = event.mission_id or ""
    if isinstance(event, brain_events.BeliefUpdated):
        payload = {"belief": to_core_belief(event.belief).model_dump(mode="json"), "latency_ms": event.latency_ms,
                   "evidence": event.evidence}
        return core.MissionEvent(mission_id=mission_id, kind=core.EventKind.BELIEF_UPDATED, payload=payload)
    if isinstance(event, brain_events.PlanComputed):
        payload = {"chosen": to_core_move(event.plan.move, mission_id).model_dump(mode="json"),
                   "tree": event.plan.tree, "elapsed_ms": event.plan.elapsed_ms, "fallback": event.plan.fallback}
        return core.MissionEvent(mission_id=mission_id, kind=core.EventKind.PLAN_COMPUTED, payload=payload)
    if isinstance(event, brain_events.TurnCompleted):
        move = to_core_move(event.move, mission_id).model_dump(mode="json") if event.move else None
        payload = {"speaker": event.turn.speaker, "text": event.turn.text, "move": move,
                   "belief": to_core_belief(event.belief).model_dump(mode="json") if event.belief else None}
        return core.MissionEvent(mission_id=mission_id, kind=core.EventKind.TURN_COMPLETED, payload=payload)
    if isinstance(event, brain_events.ActionDecided):
        decision = event.decision
        payload = {"tool": decision.call.tool, "verdict": decision.verdict, "reason": decision.reason}
        return core.MissionEvent(mission_id=mission_id, kind=core.EventKind.ACTION_DECISION, payload=payload)
    return None
