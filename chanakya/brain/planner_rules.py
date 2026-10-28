"""Rule-and-belief baseline planner. It is the look-ahead planner's fallback and its benchmark."""

import time

from chanakya.core.schemas import (
    DialogueState,
    MissionCard,
    MissionKind,
    Move,
    MoveType,
    PlanResult,
    ScoredMove,
    ToolCall,
    TriggerType,
)

from . import moves as lib
from .concern_bank import ConcernBank, default_bank

PRODUCT_BY_TRIGGER = {
    TriggerType.UPI_RISING_NO_SOUNDBOX: "soundbox",
    TriggerType.CARD_DEMAND_NO_POS: "card_machine",
    TriggerType.CARD_MACHINE_PRICE_QUESTION: "card_machine",
    TriggerType.SOUNDBOX_UNUSED: "soundbox",
    TriggerType.RENTAL_MISSED: "soundbox",
}
PRODUCT_WORDS = {"card": "card_machine", "pos": "card_machine", "soundbox": "soundbox", "qr": "qr",
                 "link": "payment_links", "gateway": "gateway", "website": "gateway"}
PROBE_THRESHOLD = 0.3
BUSY_THRESHOLD = 0.5
MAX_TURNS = 16


def mission_product(card: MissionCard) -> str:
    """The one product this mission is about, from its trigger or the words of its goal."""
    if card.trigger in PRODUCT_BY_TRIGGER:
        return PRODUCT_BY_TRIGGER[card.trigger]
    text = f"{card.goal} {card.context}".lower()
    return next((product for word, product in PRODUCT_WORDS.items() if word in text), "soundbox")


def consent_tool(card: MissionCard, state: DialogueState | None = None) -> str:
    """The write action the mission asks consent for: an onboarding link for sales, a visit or summary otherwise."""
    if card.kind == MissionKind.SALES:
        return "send_onboarding_link"
    if state is not None and "device_issue" in lib.resolved_concerns(state):
        return "book_field_visit"
    return "send_summary"


class RuleBasedPlanner:
    """Implements ``Planner`` with ordered rules over the belief; never proposes a write without consent."""

    def __init__(self, bank: ConcernBank | None = None):
        self.bank = bank or default_bank()

    def choose(self, state: DialogueState) -> tuple[Move, str]:
        """Return the next move and the rule that chose it."""
        card, last = state.card, state.last_merchant_text()
        tool = consent_tool(card, state)
        done = {m.key() for m in state.moves}
        if not lib.disclosed(state):
            return Move(type=MoveType.DISCLOSE_AND_GREET), "disclose_first"
        if lib.merchant_distressed(last):
            return Move(type=MoveType.ESCALATE, args={"reason": "distress"}), "distress"
        if lib.merchant_declined(last):
            return Move(type=MoveType.END_CALL_POLITELY, reason="merchant declined"), "declined"
        if lib.merchant_requests_sensitive_data(last):
            return Move(type=MoveType.END_CALL_POLITELY, reason="refused sensitive data request"), "sensitive_request"
        if state.transcript.has_consent(tool) and f"TAKE_ACTION({tool})" not in done:
            return Move(type=MoveType.TAKE_ACTION, tool=tool), "consent_given"
        if f"TAKE_ACTION({tool})" in done:
            return Move(type=MoveType.END_CALL_POLITELY, reason="action taken"), "finished"
        if "SCHEDULE_FOLLOWUP" in done:
            return Move(type=MoveType.END_CALL_POLITELY, reason="follow-up scheduled"), "after_followup"
        asked = state.moves and state.moves[-1].type == MoveType.CONFIRM_CONSENT
        asks = sum(1 for m in state.moves if m.type == MoveType.CONFIRM_CONSENT)
        if lib.explicit_consent(last) and not asked and asks < 3:
            # An unprompted yes is welcome, but consent is only recorded for a clear question.
            return Move(type=MoveType.CONFIRM_CONSENT, tool=tool), "confirm_unprompted_yes"
        if len(state.transcript.turns) >= MAX_TURNS:
            return Move(type=MoveType.SCHEDULE_FOLLOWUP, args={"channel": "call"}), "too_long"

        open_concerns = lib.open_concerns(state)
        top, p = open_concerns[0] if open_concerns else (None, 0.0)
        if top == "just_busy" and p >= BUSY_THRESHOLD:
            return Move(type=MoveType.SCHEDULE_FOLLOWUP, args={"channel": "call"}), "busy"
        if top is not None and p >= PROBE_THRESHOLD:
            probe = Move(type=MoveType.PROBE_CONCERN, concern=top)
            # A worry the merchant has clearly voiced, or one already probed, gets answered directly.
            if probe.key() in done or p >= 0.6:
                return Move(type=MoveType.RESOLVE_CONCERN, concern=top), "resolve_top_concern"
            return probe, "probe_top_concern"
        if "DISCOVER_NEED" not in done:
            return Move(type=MoveType.DISCOVER_NEED), "discover_need"
        product = mission_product(card)
        if card.kind == MissionKind.SALES and f"RECOMMEND({product})" not in done:
            return Move(type=MoveType.RECOMMEND, product=product), "recommend"
        ask = Move(type=MoveType.CONFIRM_CONSENT, tool=tool)
        asks = sum(1 for m in state.moves if m.key() == ask.key())
        if asks < 2:
            return ask, "ask_consent"
        return Move(type=MoveType.SCHEDULE_FOLLOWUP, args={"channel": "call"}), "no_consent_yet"

    async def plan(self, state: DialogueState) -> PlanResult:
        """Choose the next move; the result is always legal under the move library's rules."""
        started = time.perf_counter()
        move, rule = self.choose(state)
        if not lib.is_legal(move, state, self.bank):
            move, rule = Move(type=MoveType.END_CALL_POLITELY, reason="no legal move"), "fallback"
        move = move.model_copy(update={"reason": move.reason or rule})
        return PlanResult(move=move, candidates=[ScoredMove(move=move, score=1.0)],
                          elapsed_ms=round((time.perf_counter() - started) * 1000, 3), tree={"rule": rule})

    async def reconsider(self, state: DialogueState, call: ToolCall) -> bool:
        """Re-check intent before an irreversible write: consent present, no decline, no distress since."""
        last = state.last_merchant_text()
        if call.tool in lib.WRITE_TOOLS and not state.transcript.has_consent(call.tool):
            return False
        return not (lib.merchant_declined(last) or lib.merchant_distressed(last))
