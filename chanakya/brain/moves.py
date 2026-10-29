"""The typed move library: preconditions, legal candidates and the conversational signals they depend on.

Hard rules enforced here, before any planner scores anything:
- DISCLOSE_AND_GREET comes first and only once.
- TAKE_ACTION with a write tool needs the merchant's explicit consent for that tool in the transcript.
- CONFIRM_CONSENT names exactly one known write tool.
- After the merchant declines, only END_CALL_POLITELY or ESCALATE remain.
- Unknown concerns, products and tools are rejected, never improvised.
"""

import re

from chanakya.brain.contracts.schemas import DialogueState, Move, MoveType

from .concern_bank import ConcernBank

PRODUCTS = ("qr", "soundbox", "card_machine", "gateway", "payment_links")
# Typed tools from docs/IDEA.md 3.7; the action registry (Track B) is the source of truth at run time.
WRITE_TOOLS = frozenset({
    "create_callback_request", "create_lead", "update_lead_stage", "log_interaction", "send_onboarding_link",
    "send_summary", "create_onboarding_session", "book_field_visit", "book_callback", "raise_ticket",
})
READ_TOOLS = frozenset({
    "get_onboarding_status", "get_device_status", "get_device_usage", "get_device_order_status",
    "get_settlement_status", "get_ticket_status", "read_pageindex",
})
TERMINAL_MOVES = frozenset({MoveType.END_CALL_POLITELY, MoveType.ESCALATE})

DECLINE = re.compile(
    r"\b(not interested|don't want|do not want|no thanks|don't call|stop calling|nahi chahiye|nahin chahiye"
    r"|mat karo call|call mat|band karo|interest nahi|zaroorat nahi hai mujhe)\b|नहीं चाहिए|कॉल मत|ਨਹੀਂ ਚਾਹੀਦਾ|ਕਾਲ ਨਾ",
    re.IGNORECASE,
)
DISTRESS = re.compile(
    r"\b(upset|crying|depressed|real person|human|insaan|pareshan hain|bahut pareshan|complaint|tension mein)\b"
    r"|इंसान|परेशान हैं|ਇਨਸਾਨ|ਪਰੇਸ਼ਾਨ ਹਨ",
    re.IGNORECASE,
)
SENSITIVE_REQUEST = re.compile(r"\b(otp|upi pin|cvv|password)\b|ओटीपी", re.IGNORECASE)
AFFIRM = re.compile(r"\b(haan|haa|han ji|yes|yeah|ok|okay|theek hai|thik hai|bilkul|zaroor|sure)\b|हाँ|ठीक है|ਹਾਂ|ਠੀਕ ਹੈ",
                    re.IGNORECASE)
ACTION_WORDS = re.compile(
    r"\b(bhej|bhejo|bhejiye|send|kar do|kardo|kar dijiye|book|please|go ahead|daal do|chalega)\b"
    r"|भेज|कर दीजिए|कर दो|बुक|ਭੇਜ|ਕਰ ਦਿਓ",
    re.IGNORECASE,
)
DENIAL = re.compile(
    r"\b(koi problem nahi|problem nahi hai|dikkat nahi|not a problem|no problem|not an issue|not worried)\b"
    r"|दिक्कत नहीं|समस्या नहीं|ਸਮੱਸਿਆ ਨਹੀਂ",
    re.IGNORECASE,
)
NEGATION = re.compile(r"\b(nahi|nahin|not|no|mat|don't)\b|नहीं|मत|ਨਹੀਂ", re.IGNORECASE)


def merchant_declined(text: str) -> bool:
    """A clear no: the pitch must stop."""
    return bool(DECLINE.search(text))


def merchant_distressed(text: str) -> bool:
    """Signs of distress or a request for a human: escalate early."""
    return bool(DISTRESS.search(text))


def merchant_requests_sensitive_data(text: str) -> bool:
    """The caller is asking about OTPs, PINs, CVVs or passwords (for example a fake 'Paytm staff')."""
    return bool(SENSITIVE_REQUEST.search(text))


def explicit_consent(text: str) -> bool:
    """An explicit yes to the action just asked about. A bare "haan" or "okay" is never consent."""
    if not AFFIRM.search(text) or NEGATION.search(text) or merchant_declined(text):
        return False
    return bool(ACTION_WORDS.search(text))


def disclosed(state: DialogueState) -> bool:
    """Whether the agent has already said it is an AI assistant."""
    return state.transcript.disclosed_ai or any(m.type == MoveType.DISCLOSE_AND_GREET for m in state.moves)


def declined_since_last_consent_request(state: DialogueState) -> bool:
    """Whether the latest merchant turn is a clear no."""
    return merchant_declined(state.last_merchant_text())


def resolved_concerns(state: DialogueState) -> set[str]:
    """Concerns the agent has already answered with RESOLVE_CONCERN."""
    return {m.concern for m in state.moves if m.type == MoveType.RESOLVE_CONCERN and m.concern}


def ruled_out_concerns(state: DialogueState) -> set[str]:
    """Concerns the merchant denied right after the agent probed them."""
    ruled_out, probed = set(), None
    for turn in state.transcript.turns:
        if turn.speaker == "agent":
            probed = turn.move.concern if turn.move and turn.move.type == MoveType.PROBE_CONCERN else None
        elif probed and DENIAL.search(turn.text):
            ruled_out.add(probed)
            probed = None
    return ruled_out


def violations(move: Move, state: DialogueState, bank: ConcernBank) -> list[str]:
    """Return every precondition ``move`` breaks in ``state``; an empty list means it is legal."""
    problems = []
    if state.ended:
        problems.append("conversation_ended")
    if not disclosed(state) and move.type != MoveType.DISCLOSE_AND_GREET:
        problems.append("disclose_first")
    if move.type == MoveType.DISCLOSE_AND_GREET and disclosed(state):
        problems.append("already_disclosed")
    if declined_since_last_consent_request(state) and move.type not in TERMINAL_MOVES:
        problems.append("merchant_declined")
    if move.type in {MoveType.PROBE_CONCERN, MoveType.RESOLVE_CONCERN} and move.concern not in bank.concerns:
        problems.append("unknown_concern")
    if move.type == MoveType.RECOMMEND and move.product not in PRODUCTS:
        problems.append("unknown_product")
    if move.type == MoveType.CONFIRM_CONSENT and move.tool not in WRITE_TOOLS:
        problems.append("consent_needs_write_tool")
    if move.type == MoveType.TAKE_ACTION:
        if move.tool in WRITE_TOOLS:
            if not state.transcript.has_consent(move.tool):
                problems.append("write_without_consent")
        elif move.tool not in READ_TOOLS:
            problems.append("unknown_tool")
    return problems


def is_legal(move: Move, state: DialogueState, bank: ConcernBank) -> bool:
    """Whether ``move`` satisfies every precondition."""
    return not violations(move, state, bank)


def legal_moves(state: DialogueState, bank: ConcernBank, product: str, consent_tool: str,
                top_concerns: int = 3) -> list[Move]:
    """Every legal candidate worth considering: moves for the top open concerns plus the mission moves."""
    open_concerns = [cid for cid, _ in open_belief(state).top(top_concerns)]
    candidates = [Move(type=MoveType.DISCLOSE_AND_GREET), Move(type=MoveType.DISCOVER_NEED)]
    for cid in open_concerns:
        candidates += [Move(type=MoveType.PROBE_CONCERN, concern=cid), Move(type=MoveType.RESOLVE_CONCERN, concern=cid)]
    candidates += [
        Move(type=MoveType.RECOMMEND, product=product),
        Move(type=MoveType.CONFIRM_CONSENT, tool=consent_tool),
        Move(type=MoveType.TAKE_ACTION, tool=consent_tool),
        Move(type=MoveType.SCHEDULE_FOLLOWUP, args={"channel": "call"}),
        Move(type=MoveType.ESCALATE, args={"reason": "planner"}),
        Move(type=MoveType.END_CALL_POLITELY),
    ]
    return [move for move in candidates if is_legal(move, state, bank)]


def open_concerns(state: DialogueState) -> list[tuple[str, float]]:
    """Concerns neither resolved nor ruled out, with their raw (not renormalised) belief, highest first."""
    closed = resolved_concerns(state) | ruled_out_concerns(state)
    return [(cid, p) for cid, p in state.belief.top(len(state.belief.probabilities)) if cid not in closed]


def open_belief(state: DialogueState):
    """The belief over concerns not yet resolved, renormalised (falls back to the full belief)."""
    resolved = resolved_concerns(state) | ruled_out_concerns(state)
    remaining = {cid: p for cid, p in state.belief.probabilities.items() if cid not in resolved}
    total = sum(remaining.values())
    if not remaining or total <= 0:
        return state.belief
    return state.belief.model_copy(update={"probabilities": {cid: p / total for cid, p in remaining.items()}})
