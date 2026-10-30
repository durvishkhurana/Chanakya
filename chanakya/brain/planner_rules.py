"""Rule-and-belief baseline planner. It is the look-ahead planner's fallback and its benchmark."""

import time

from chanakya.brain.contracts.schemas import (
    DialogueState,
    EndReason,
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
    TriggerType.MERCHANT_CHURNED: "soundbox",
}
PRODUCT_WORDS = {"card": "card_machine", "pos": "card_machine", "soundbox": "soundbox", "qr": "qr",
                 "link": "payment_links", "gateway": "gateway", "website": "gateway"}
# The permission-first opening is never searched either.
PERMISSION_RULES = frozenset({"ask_permission", "ask_permission_again", "permission_declined", "permission_busy",
                              "permission_unclear"})
# Win-back rules are never searched by the look-ahead planner (they are also move preconditions).
WINBACK_RULES = frozenset({"winback_ask_why", "winback_probe", "winback_busy", "winback_not_needed",
                           "winback_settlement_read", "winback_answer", "winback_fix", "winback_accept_choice",
                           "winback_no_yes", "winback_too_long"})
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
    """The write action the mission asks consent for: an onboarding link for sales, a visit or summary otherwise.

    A win-back mission asks only for the fix that fits the merchant's reason for leaving (a ticket or a visit).
    """
    if card.kind == MissionKind.WIN_BACK:
        return (lib.winback_fix(state) if state is not None else None) or "raise_ticket"
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
            return Move(type=MoveType.END_CALL_POLITELY, reason="merchant declined", end_reason=EndReason.DECLINED), "declined"
        if lib.merchant_requests_sensitive_data(last):
            return Move(type=MoveType.END_CALL_POLITELY, reason="refused sensitive data request",
                        end_reason=EndReason.SENSITIVE_REQUEST), "sensitive_request"
        if state.transcript.has_consent(tool) and f"TAKE_ACTION({tool})" not in done:
            reason = lib.winback_reason(state) if lib.is_winback(state) else None
            return Move(type=MoveType.TAKE_ACTION, tool=tool, args={"reason": reason} if reason else {}), "consent_given"
        if f"TAKE_ACTION({tool})" in done:
            return Move(type=MoveType.END_CALL_POLITELY, reason="action taken", end_reason=EndReason.ACTION_TAKEN), "finished"
        if "SCHEDULE_FOLLOWUP" in done:
            return Move(type=MoveType.END_CALL_POLITELY, reason="follow-up scheduled",
                        end_reason=EndReason.FOLLOWUP_SCHEDULED), "after_followup"
        if not lib.permission_granted(state):
            return self.permission(state)
        if lib.is_winback(state):
            return self.winback(state)
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

    def permission(self, state: DialogueState) -> tuple[Move, str]:
        """Before any pitch on a call the merchant did not ask for: two minutes? A no ends it, busy reschedules."""
        answers = lib.permission_answers(state)
        if not answers:
            return Move(type=MoveType.ASK_PERMISSION), "ask_permission"
        if answers[-1] == "no":
            return Move(type=MoveType.END_CALL_POLITELY, reason="no to two minutes",
                        end_reason=EndReason.DECLINED), "permission_declined"
        if answers[-1] == "busy":
            return Move(type=MoveType.SCHEDULE_FOLLOWUP, args={"channel": "call"}), "permission_busy"
        if len(answers) < lib.MAX_PERMISSION_ASKS:
            return Move(type=MoveType.ASK_PERMISSION, reason="answer was not a clear yes"), "ask_permission_again"
        return Move(type=MoveType.END_CALL_POLITELY, reason="no clear yes to two minutes"), "permission_unclear"

    def winback(self, state: DialogueState) -> tuple[Move, str]:
        """Listen first, then act on the reason for leaving: fix it if a system can, otherwise stop politely."""
        done = {m.key() for m in state.moves}
        noted = {"evidence": lib.reason_evidence(state)} if lib.reason_evidence(state) else {}
        if "DISCOVER_NEED" not in done:
            return Move(type=MoveType.DISCOVER_NEED, reason="ask why they stopped", args=noted), "winback_ask_why"
        if len(state.transcript.turns) >= MAX_TURNS:
            return Move(type=MoveType.END_CALL_POLITELY, reason="call too long"), "winback_too_long"
        reason = lib.winback_reason(state)
        if reason is None:
            probed = {m.concern for m in state.moves if m.type == MoveType.PROBE_CONCERN}
            ranked = [cid for cid, _ in lib.open_concerns(state)]
            target = next((cid for cid in ranked if cid not in probed), ranked[0] if ranked else "not_needed")
            return Move(type=MoveType.PROBE_CONCERN, concern=target, args=noted), "winback_probe"
        locked = {"reason": reason}
        if reason == "just_busy":
            return Move(type=MoveType.SCHEDULE_FOLLOWUP, args={"channel": "call"} | locked), "winback_busy"
        if reason in lib.NO_NEED_REASONS:
            return Move(type=MoveType.END_CALL_POLITELY, args=locked, reason="no use for it",
                        end_reason=EndReason.NOT_NEEDED), "winback_not_needed"
        if reason == "settlement_delay" and not lib.settlement_read(state):
            return Move(type=MoveType.TAKE_ACTION, tool="get_settlement_status", args=locked), "winback_settlement_read"
        if reason not in lib.WINBACK_FIX_TOOLS and reason not in lib.resolved_concerns(state):
            return Move(type=MoveType.RESOLVE_CONCERN, concern=reason, args=locked), "winback_answer"
        if reason in lib.VISIT_REASONS and reason not in lib.resolved_concerns(state):
            return Move(type=MoveType.RESOLVE_CONCERN, concern=reason, args=locked), "winback_answer"
        tool = lib.WINBACK_FIX_TOOLS.get(reason)
        if tool is None:
            return Move(type=MoveType.END_CALL_POLITELY, args=locked, reason="their choice",
                        end_reason=EndReason.ACCEPTED_CHOICE), "winback_accept_choice"
        asks = sum(1 for m in state.moves if m.type == MoveType.CONFIRM_CONSENT and m.tool == tool)
        if asks < 2:
            return Move(type=MoveType.CONFIRM_CONSENT, tool=tool, args=locked), "winback_fix"
        return Move(type=MoveType.END_CALL_POLITELY, args=locked, reason="no yes to the fix",
                    end_reason=EndReason.ACCEPTED_CHOICE), "winback_no_yes"

    async def plan(self, state: DialogueState) -> PlanResult:
        """Choose the next move; the result is always legal under the move library's rules."""
        started = time.perf_counter()
        move, rule = self.choose(state)
        if not lib.is_legal(move, state, self.bank):
            move, rule = Move(type=MoveType.END_CALL_POLITELY, reason="no legal move",
                              end_reason=EndReason.NO_LEGAL_MOVE), "fallback"
        move = move.model_copy(update={"reason": move.reason or rule})
        return PlanResult(move=move, candidates=[ScoredMove(move=move, score=1.0)],
                          elapsed_ms=round((time.perf_counter() - started) * 1000, 3), tree={"rule": rule})

    async def reconsider(self, state: DialogueState, call: ToolCall) -> bool:
        """Re-check intent before an irreversible write: consent present, no decline, no distress since."""
        last = state.last_merchant_text()
        if call.tool in lib.WRITE_TOOLS and not state.transcript.has_consent(call.tool):
            return False
        return not (lib.merchant_declined(last) or lib.merchant_distressed(last))
