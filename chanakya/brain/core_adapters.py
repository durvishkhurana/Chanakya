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
    core.SignalKind.MERCHANT_CHURNED: brain.TriggerType.MERCHANT_CHURNED,
}
# Concern ids used by Track B's intake rules that the Concern Bank names differently.
CONCERN_ALIASES = {
    "swipe_charges": "per_swipe_charges",
    "device_reliability": "device_issue",
    "cash_flow": "rental_cost",  # a missed rental is treated as the cost worry until the bank has its own entry
}
SPEAKERS = {core.Speaker.AGENT: "agent", core.Speaker.MERCHANT: "merchant", core.Speaker.HUMAN: "human_agent"}
CORE_SPEAKERS = {value: key for key, value in SPEAKERS.items()}


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


def to_brain_merchant(merchant: core.Merchant) -> brain.Merchant:
    """Core merchant -> brain merchant; owned devices become the brain's device list."""
    devices = [name for name, owned in (("soundbox", merchant.has_soundbox), ("card_machine", merchant.has_card_machine))
               if owned]
    return brain.Merchant(merchant_id=merchant.id, name=merchant.name, business_type=merchant.business_type,
                          city=merchant.city, language=merchant.language,
                          contact_window=brain.ContactWindow(**merchant.contact_window.model_dump()),
                          do_not_call=merchant.do_not_call, devices=devices, relationship=merchant.relationship,
                          churned_at=merchant.churned_at)


def to_core_merchant(merchant: brain.Merchant) -> core.Merchant:
    """Brain merchant -> core merchant."""
    window = core.ContactWindow(**merchant.contact_window.model_dump()) if merchant.contact_window else core.ContactWindow()
    return core.Merchant(id=merchant.merchant_id, name=merchant.name, business_type=merchant.business_type,
                         city=merchant.city, language=merchant.language, contact_window=window,
                         do_not_call=merchant.do_not_call, has_soundbox="soundbox" in merchant.devices,
                         has_card_machine="card_machine" in merchant.devices, relationship=merchant.relationship,
                         churned_at=merchant.churned_at)


def to_brain_card(mission: core.Mission, bank: ConcernBank | None = None,
                  permission_first: bool = False) -> brain.MissionCard:
    """The brain's view of a core mission.

    ``permission_first`` is the PERMISSION_FIRST_ENABLED setting: lead-list missions then open by asking for two
    minutes, because the merchant did not ask to be called.
    """
    bank = bank or default_bank()
    card = mission.card
    trigger = TRIGGERS[card.signal_kind]
    return brain.MissionCard(
        mission_id=mission.id,
        merchant=brain.Merchant(merchant_id=card.merchant_id, name=card.merchant_name, business_type="unknown",
                                city="unknown", language=card.language,
                                relationship="former" if trigger == brain.TriggerType.MERCHANT_CHURNED else "customer"),
        kind=brain.MissionKind(card.mission_type.value), goal=card.goal, door=brain.Door(card.door.value),
        trigger=trigger, why_now=card.why_now,
        starting_worries=worries(card.starting_worries, bank) if card.starting_worries else bank.priors[trigger],
        chance=min(1.0, card.priority) if card.priority else 0.5, context=card.product or "",
        permission_first=permission_first and trigger == brain.TriggerType.LEAD_LIST,
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


def to_core_belief(belief: brain.BeliefState, evidence: dict[str, float] | None = None,
                   scorer: str | None = None) -> core.BeliefState:
    """Brain belief -> core belief, with the scorer's evidence for the latest line when known."""
    evidence = {cid: round(score, 4) for cid, score in (evidence or {}).items()}
    return core.BeliefState(probabilities=dict(belief.probabilities), turn=belief.turn_index,
                            evidence=evidence, scorer=scorer)


class CorePlanner:
    """Implements ``chanakya.core.interfaces.Planner`` around any Track A planner."""

    def __init__(self, planner, bank: ConcernBank | None = None):
        self.planner = planner
        self.bank = bank or default_bank()

    async def plan(self, context: core.PlanContext) -> core.PlanResult:
        result = await self.planner.plan(to_brain_state(context, self.bank))
        return to_core_plan(result, context.mission.id)

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
    # Payloads are exactly the core models, because the gate, hand-off cards and dashboards parse them strictly.
    if isinstance(event, brain_events.BeliefUpdated):
        return core.MissionEvent.of(mission_id, core.EventKind.BELIEF_UPDATED, to_core_belief(event.belief, event.evidence, event.scorer))
    if isinstance(event, brain_events.PlanComputed):
        return core.MissionEvent.of(mission_id, core.EventKind.PLAN_COMPUTED, to_core_plan(event.plan, mission_id))
    if isinstance(event, brain_events.TurnCompleted):
        return core.MissionEvent.of(mission_id, core.EventKind.TURN_COMPLETED, to_core_turn(event.turn, mission_id))
    # Action decisions are written by the safety gate itself, so the brain's copy would be a duplicate.
    return None


def to_core_turn(turn: brain.Turn, mission_id: str) -> core.Turn:
    """Brain turn -> core turn; hesitation timing goes into ``cues``."""
    speaker = CORE_SPEAKERS[turn.speaker]
    cues = {"pause_ms": float(turn.pause_before_ms)} if turn.pause_before_ms is not None else {}
    return core.Turn(speaker=speaker, text=turn.text, language=turn.language, cues=cues, at=turn.at,
                     move=to_core_move(turn.move, mission_id) if turn.move else None)


def to_core_plan(plan: brain.PlanResult, mission_id: str) -> core.PlanResult:
    """Brain plan -> core plan."""
    return core.PlanResult(
        chosen=to_core_move(plan.move, mission_id),
        candidates=[core.ScoredMove(move=to_core_move(c.move, mission_id), score=c.score, visits=c.visits)
                    for c in plan.candidates],
        tree=plan.tree, elapsed_ms=plan.elapsed_ms, fallback=plan.fallback,
    )
