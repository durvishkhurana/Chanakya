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

import asyncio
from datetime import timedelta

from agent.brain_agent import BrainAgent
from chanakya.actions.gate import merchant_from_db
from chanakya.brain import moves as lib
from chanakya.brain.contracts import events as brain_events
from chanakya.brain.contracts import schemas as brain
from chanakya.brain.core_adapters import to_brain_card, to_ledger_event
from chanakya.brain.memory.memory import configured_memory
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
# The link consent question also asks about a reminder (realizer), so a yes to it covers the verifier's fixed-text
# onboarding reminder, and nothing else: an end-of-call summary needs its own yes.
CONSENT_COVERS = {"send_onboarding_link": ["send_onboarding_link", "send_onboarding_reminder"]}
# Brain product names -> the messaging tools' product names.
TOOL_PRODUCTS = {"gateway": "payment_gateway"}
LINK_PRODUCTS = frozenset({"soundbox", "card_machine", "qr", "payment_gateway", "payment_links", "business_app"})


def agreed_product(state: brain.DialogueState) -> str:
    """The product the merchant said yes to: the last one recommended before the link question, else the card's."""
    asked = max((i for i, m in enumerate(state.moves)
                 if m.type == brain.MoveType.CONFIRM_CONSENT and m.tool == "send_onboarding_link"), default=len(state.moves))
    recommended = [m.product for m in state.moves[:asked] if m.type == brain.MoveType.RECOMMEND and m.product]
    product = TOOL_PRODUCTS.get(recommended[-1], recommended[-1]) if recommended else None
    return product if product in LINK_PRODUCTS else (state.card.context or "soundbox")


# Fixed ticket text for a win-back fix: the merchant's reason, never free text from a model.
TICKET_TEXT = {
    "device": "Win-back call: the merchant stopped using the {product} because the device was not working properly.",
    "settlement": "Win-back call: the merchant stopped using the {product} after a delayed settlement.",
}


def tool_args(tool: str, card: brain.MissionCard, slot: str, product: str | None = None,
              reason: str | None = None) -> dict:
    """Arguments for a write tool, filled from the mission card (``product`` overrides the card's).

    ``reason`` is a win-back merchant's reason for leaving: it picks the ticket category or the visit's purpose.
    """
    merchant = {"merchant_id": card.merchant.merchant_id}
    product = product or card.context or "soundbox"
    if tool == "send_onboarding_link":
        return merchant | {"product": product, "channel": "whatsapp", "language": card.merchant.language}
    if tool == "book_field_visit":
        return merchant | {"purpose": "sales" if reason in lib.VISIT_REASONS else "technician", "slot": slot}
    if tool == "raise_ticket":
        category = lib.TICKET_CATEGORIES.get(reason, "device")
        return merchant | {"category": category,
                           "description": TICKET_TEXT[category].format(product=product.replace("_", " "))}
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
        write = call.tool in lib.WRITE_TOOLS  # a read (settlement status) changes nothing, so the mission stays put
        await self.call.sync(state)
        mission = runtime.ledger.store.get(mission_id)
        if write and mission.state == S.IN_CONVERSATION:
            await runtime.ledger.advance(mission_id, S.ACTION_PENDING, reason=f"merchant agreed to {call.tool}")
        slot = (runtime.clock() + timedelta(days=1)).replace(hour=5, minute=30, second=0, microsecond=0).isoformat()
        reason = lib.winback_reason(state) if lib.is_winback(state) else None
        args = tool_args(call.tool, state.card, slot, agreed_product(state), reason)
        decision = await runtime.submit(core.ToolCall(mission_id=mission_id, tool=call.tool, args=args))
        mission = runtime.ledger.store.get(mission_id)
        if write and mission.state == S.ACTION_PENDING:
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
        memory = configured_memory(runtime.settings.planner_memory)  # PLANNER_MEMORY: forest or neural (N2)
        self.agent = BrainAgent(llm=llm, planner=planner or NRPAPlanner(forest=memory),
                                bus=LedgerBus(self), gate=LedgerGate(self), actions_enabled=True)
        self.recorded_consents = 0
        self.disclosed = False
        self.declined = False  # the merchant's latest word on consent was a no
        self.reason_recorded = False
        self._lock = asyncio.Lock()  # one turn at a time, even when the merchant talks over Chanakya
        self._turns: set[asyncio.Task] = set()

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
        self.agent.start(self.mission_id, to_brain_card(
            mission, permission_first=self.runtime.settings.permission_first_enabled))

    async def say(self, text: str, language: str | None = None) -> str | None:
        """The merchant says ``text``; returns what Chanakya says back, or None once the call is over.

        The turn runs as its own task behind a shield: if the merchant talks over Chanakya and the caller is
        cancelled, the reply is dropped but the turn still finishes, so its ledger writes, escalation or close land.
        """
        turn = asyncio.ensure_future(self._say(text, language))
        self._turns.add(turn)
        turn.add_done_callback(self._turns.discard)
        return await asyncio.shield(turn)

    async def _say(self, text: str, language: str | None) -> str | None:
        async with self._lock:
            if not self.open:
                return None
            language = language or self.mission.card.language
            await self.runtime.ledger.attach_turn(self.mission_id, core.Turn(speaker=core.Speaker.MERCHANT, text=text,
                                                                             language=language))
            if lib.merchant_declined(text):
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
            self.declined = False  # a yes after a no; the gate reads the newest event the same way
            await self.runtime.ledger.record(self.mission_id, core.EventKind.CONSENT_GIVEN,
                                             {"tools": CONSENT_COVERS.get(consent.tool, [consent.tool]),
                                              "utterance": consent.utterance})
        self.recorded_consents = len(state.transcript.consents)

    async def record_disclosure(self, text: str) -> None:
        if not self.disclosed:
            self.disclosed = True
            await self.runtime.ledger.record(self.mission_id, core.EventKind.AI_DISCLOSED, {"text": text})

    async def record_leaving_reason(self, state: brain.DialogueState) -> None:
        """Write a win-back call's final top reason for leaving to the ledger, once.

        This is the brain's own ledger record, not a CRM write: ``log_interaction`` would need the merchant's consent.
        """
        if self.reason_recorded or not lib.is_winback(state) or not state.belief.probabilities:
            return
        self.reason_recorded = True
        top, p = state.belief.top(1)[0]
        reason = lib.winback_reason(state) or top
        merchant = merchant_from_db(self.runtime.registry, state.card.merchant.merchant_id)
        await self.runtime.ledger.record(self.mission_id, core.EventKind.LEAVING_REASON_RECORDED, {
            "reason": reason, "probability": round(state.belief.probabilities.get(reason, p), 3),
            "clear": lib.winback_reason(state) is not None, "probes": lib.probes_used(state),
            "merchant_id": state.card.merchant.merchant_id, "city": merchant.city if merchant else "unknown",
            "product": self.mission.card.product or "unknown"})

    async def _after(self, move: brain.Move) -> None:
        """Close, hand off or reschedule the mission according to the move just made."""
        mission, ledger = self.mission, self.runtime.ledger
        if not mission.is_open:
            return
        if move.end_reason == brain.EndReason.DECLINED and not self.declined:
            # A plain "no" to "do you have two minutes?" is a decline even without the usual decline words.
            self.declined = True
            await ledger.record(self.mission_id, core.EventKind.CONSENT_DECLINED,
                                {"utterance": self.state.last_merchant_text(), "scope": "permission"})
        ends = move.type in lib.TERMINAL_MOVES or move.type == brain.MoveType.SCHEDULE_FOLLOWUP
        fixed = move.type == brain.MoveType.TAKE_ACTION and move.tool in lib.WRITE_TOOLS
        if ends or fixed:
            await self.record_leaving_reason(self.state)
        if move.type == brain.MoveType.ESCALATE:
            await self.runtime.handoffs.escalate(self.mission_id, reason=move.args.get("reason", "needs a person"),
                                                 urgent=True)
        elif move.type == brain.MoveType.SCHEDULE_FOLLOWUP and mission.state == S.IN_CONVERSATION:
            await ledger.advance(self.mission_id, S.SCHEDULED, reason="merchant asked for a later call")
            await ledger.record(self.mission_id, core.EventKind.FOLLOWUP_SCHEDULED,
                                {"kind": "callback", "due_at": (self.runtime.clock() + timedelta(days=1)).isoformat()})
        elif move.type == brain.MoveType.END_CALL_POLITELY and (mission.state == S.IN_CONVERSATION or self.declined):
            # A no closes the mission wherever it is, even with a link out: verification and reminders stop too.
            if self.declined:
                outcome = "merchant declined"
            elif move.end_reason == brain.EndReason.SENSITIVE_REQUEST:
                outcome = "call ended after a request for sensitive data was refused"
            elif move.end_reason == brain.EndReason.NOT_NEEDED:
                outcome = "no use for the product; thanked them, no follow-up"
            elif move.end_reason == brain.EndReason.ACCEPTED_CHOICE:
                outcome = "answered their reason once and accepted their choice"
            else:
                outcome = "call ended without a yes"
            if mission.state == S.ACTION_PENDING:
                await ledger.advance(self.mission_id, S.IN_CONVERSATION, reason="merchant declined")
            self.runtime.scheduler.cancel_all(self.mission_id)
            await ledger.close(self.mission_id, S.CLOSED_NOT_INTERESTED, outcome=outcome)
