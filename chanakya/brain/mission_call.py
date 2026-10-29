"""A conversation on a real mission: the brain talks, the mission runtime records, gates and verifies.

``MissionCall`` connects the planning agent to Track B's runtime:
- the mission moves CREATED/SCHEDULED -> CONTACTING -> IN_CONVERSATION when the call starts;
- every merchant turn, belief update, plan and agent turn is written to the mission ledger, so Mission Control
  and the Live Call View show the call live;
- AI disclosure, explicit consent and declines are recorded as the ledger events the safety gate checks;
- write actions go through the real safety gate and mock systems (``Runtime.submit``), so a sent onboarding link
  starts verification and the mission only reaches DONE when the onboarding system confirms it;
- distress is handed to the human queue with a context card; a clear no closes the mission.
"""

from datetime import timedelta

from agent.brain_agent import BrainAgent
from chanakya.brain import moves as lib
from chanakya.brain.contracts import events as brain_events
from chanakya.brain.contracts import schemas as brain
from chanakya.brain.core_adapters import to_brain_card, to_ledger_event
from chanakya.brain.forest.forest import default_forest
from chanakya.brain.planner_nrpa import NRPAPlanner
from chanakya.core import schemas as core

S = core.MissionState
VERDICTS = {core.Verdict.EXECUTED: "executed", core.Verdict.BLOCKED: "blocked", core.Verdict.FAILED: "failed",
            core.Verdict.REJECTED: "blocked"}
SUMMARY = {
    "en-IN": "Thank you for talking to Chanakya, an AI assistant. For product details and current charges, "
             "please use the official Paytm for Business app or website.",
    "default": "Chanakya (AI assistant) se baat karne ke liye dhanyavaad. Product aur charges ki sahi jaankari "
               "Paytm for Business ke official app ya website par milegi.",
}
# The link consent question also asks about a reminder (realizer), so a yes to it covers the verifier's reminders.
CONSENT_COVERS = {"send_onboarding_link": ["send_onboarding_link", "send_summary"]}


def tool_args(tool: str, card: brain.MissionCard, slot: str) -> dict:
    """Arguments for a write tool, filled from the mission card."""
    merchant = {"merchant_id": card.merchant.merchant_id}
    product = card.context or "soundbox"
    if tool == "send_onboarding_link":
        return merchant | {"product": product, "channel": "whatsapp", "language": card.merchant.language}
    if tool == "book_field_visit":
        return merchant | {"purpose": "technician", "slot": slot}
    if tool == "send_summary":
        return merchant | {"channel": "whatsapp", "text": SUMMARY.get(card.merchant.language, SUMMARY["default"])}
    return merchant


class LedgerBus:
    """The brain's event bus, writing each event to the mission ledger in the core shape."""

    def __init__(self, call: "MissionCall"):
        self.call = call

    async def publish(self, event: brain_events.Event) -> None:
        ledger_event = to_ledger_event(event)
        if ledger_event is not None:
            await self.call.runtime.ledger.bus.publish(ledger_event)
        if isinstance(event, brain_events.TurnCompleted) and event.move is not None \
                and event.move.type == brain.MoveType.DISCLOSE_AND_GREET:
            await self.call.record_disclosure(event.turn.text)

    def subscribe(self, kind, handler):
        """The ledger has its own subscribers; nothing subscribes here."""
        return lambda: None


class LedgerGate:
    """The brain's safety gate, delegating to Track B's gate so every write is checked and audited there."""

    def __init__(self, call: "MissionCall"):
        self.call = call

    async def check(self, call: brain.ToolCall, state: brain.DialogueState) -> brain.ActionDecision:
        runtime, mission_id = self.call.runtime, self.call.mission_id
        await self.call.sync(state)
        mission = runtime.ledger.store.get(mission_id)
        if mission.state == S.IN_CONVERSATION:
            await runtime.ledger.advance(mission_id, S.ACTION_PENDING, reason=f"merchant agreed to {call.tool}")
        slot = (runtime.clock() + timedelta(days=1)).replace(hour=5, minute=30, second=0, microsecond=0).isoformat()
        decision = await runtime.submit(core.ToolCall(mission_id=mission_id, tool=call.tool,
                                                      args=tool_args(call.tool, state.card, slot)))
        mission = runtime.ledger.store.get(mission_id)
        if mission.state == S.ACTION_PENDING:
            if decision.verdict == core.Verdict.EXECUTED:
                await runtime.ledger.advance(mission_id, S.AWAITING_CONFIRMATION,
                                             reason=f"{call.tool} done; waiting for the outcome")
            else:
                await runtime.ledger.advance(mission_id, S.IN_CONVERSATION, reason=f"{call.tool} {decision.reason}")
        result = decision.result
        return brain.ActionDecision(
            call=call, verdict=VERDICTS[decision.verdict], reason=decision.reason,
            result=brain.ToolResult(call_id=call.call_id, ok=result.ok, data=result.data, error=result.error)
            if result else None,
        )


class MissionCall:
    """One call on one mission. ``start`` once, then ``say`` each merchant utterance."""

    def __init__(self, runtime, mission_id: str, llm=None, planner=None):
        self.runtime = runtime
        self.mission_id = mission_id
        self.agent = BrainAgent(llm=llm, planner=planner or NRPAPlanner(forest=default_forest()),
                                bus=LedgerBus(self), gate=LedgerGate(self), actions_enabled=True)
        self.recorded_consents = 0
        self.disclosed = False
        self.declined = False

    @property
    def mission(self) -> core.Mission:
        mission = self.runtime.ledger.store.get(self.mission_id)
        if mission is None:
            raise LookupError(f"unknown mission {self.mission_id}")
        return mission

    @property
    def state(self) -> brain.DialogueState:
        return self.agent.threads[self.mission_id]

    @property
    def open(self) -> bool:
        return self.mission.is_open and not self.state.ended

    async def start(self) -> None:
        """Begin the conversation: the mission moves into IN_CONVERSATION."""
        mission = self.mission
        if not mission.is_open:
            raise ValueError(f"mission is {mission.state}")
        for target, reason in ((S.CONTACTING, "Chanakya is calling"), (S.IN_CONVERSATION, "merchant picked up")):
            if mission.state in {S.CREATED, S.SCHEDULED} or (mission.state == S.CONTACTING and target == S.IN_CONVERSATION):
                mission = await self.runtime.ledger.advance(self.mission_id, target, reason=reason)
        self.agent.start(self.mission_id, to_brain_card(mission))

    async def say(self, text: str, language: str | None = None) -> str | None:
        """The merchant says ``text``; returns what Chanakya says back, or None once the call is over."""
        if not self.open:
            return None
        language = language or self.mission.card.language
        await self.runtime.ledger.attach_turn(self.mission_id, core.Turn(speaker=core.Speaker.MERCHANT, text=text,
                                                                         language=language))
        if lib.merchant_declined(text) and not self.declined:
            self.declined = True
            await self.runtime.ledger.record(self.mission_id, core.EventKind.CONSENT_DECLINED, {"utterance": text})
        reply = await self.agent.respond(text, self.mission_id, language)
        await self.sync(self.state)
        await self._after(self.state.moves[-1])
        return reply

    async def astream(self, query: str, config=None, **kwargs):
        """The voice agent interface (``agent.graph.Agent.astream``), so a spoken call can run on this mission."""
        language = ((config or {}).get("configurable", {}).get("response_language")) or None
        reply = await self.say(query, language) or ""
        yield {"type": "token", "content": reply}
        yield {"type": "done", "full_content": reply, "tool_calls": []}

    async def sync(self, state: brain.DialogueState) -> None:
        """Write disclosure and any new explicit consent to the ledger, where the safety gate looks for them."""
        if state.transcript.disclosed_ai and not self.disclosed:
            await self.record_disclosure("")
        for consent in state.transcript.consents[self.recorded_consents:]:
            await self.runtime.ledger.record(self.mission_id, core.EventKind.CONSENT_GIVEN,
                                             {"tools": CONSENT_COVERS.get(consent.tool, [consent.tool]),
                                              "utterance": consent.utterance})
        self.recorded_consents = len(state.transcript.consents)

    async def record_disclosure(self, text: str) -> None:
        if not self.disclosed:
            self.disclosed = True
            await self.runtime.ledger.record(self.mission_id, core.EventKind.AI_DISCLOSED, {"text": text})

    async def _after(self, move: brain.Move) -> None:
        """Close, hand off or reschedule the mission according to the move just made."""
        mission, ledger = self.mission, self.runtime.ledger
        if not mission.is_open:
            return
        if move.type == brain.MoveType.ESCALATE:
            await self.runtime.handoffs.escalate(self.mission_id, reason=move.args.get("reason", "needs a person"),
                                                 urgent=True)
        elif move.type == brain.MoveType.SCHEDULE_FOLLOWUP and mission.state == S.IN_CONVERSATION:
            await ledger.advance(self.mission_id, S.SCHEDULED, reason="merchant asked for a later call")
            await ledger.record(self.mission_id, core.EventKind.FOLLOWUP_SCHEDULED,
                                {"kind": "callback", "due_at": (self.runtime.clock() + timedelta(days=1)).isoformat()})
        elif move.type == brain.MoveType.END_CALL_POLITELY and mission.state == S.IN_CONVERSATION:
            if self.declined:
                outcome = "merchant declined"
            elif "sensitive" in move.reason:
                outcome = "call ended after a request for sensitive data was refused"
            else:
                outcome = "call ended without a yes"
            await ledger.close(self.mission_id, S.CLOSED_NOT_INTERESTED, outcome=outcome)
