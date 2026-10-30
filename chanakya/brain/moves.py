"""The typed move library: preconditions, legal candidates and the conversational signals they depend on.

Hard rules enforced here, before any planner scores anything:
- DISCLOSE_AND_GREET comes first and only once.
- TAKE_ACTION with a write tool needs the merchant's explicit consent for that tool in the transcript.
- CONFIRM_CONSENT names exactly one known write tool.
- After the merchant declines, only END_CALL_POLITELY or ESCALATE remain.
- Unknown concerns, products and tools are rejected, never improvised.
- Permission-first missions (lead list): nothing but the permission question, a callback or a goodbye until the
  merchant clearly says yes to "do you have two minutes?".
- Win-back missions listen first: no answer, consent question or action until the reason for leaving is clear
  (or two probes were used); then only the fix that fits that reason, and nothing at all for "not needed".
"""

import re

from chanakya.brain.contracts.schemas import DialogueState, MissionKind, Move, MoveType

from .concern_bank import ConcernBank
from .cues import DEFLECTIONS, FILLERS, hesitation

PRODUCTS = ("qr", "soundbox", "card_machine", "gateway", "payment_links")
# Typed tools from docs/IDEA.md 3.7; the action registry (Track B) is the source of truth at run time.
WRITE_TOOLS = frozenset({
    "create_callback_request", "create_lead", "update_lead_stage", "log_interaction", "send_onboarding_link",
    "send_onboarding_reminder", "send_summary", "create_onboarding_session", "book_field_visit", "book_callback", "raise_ticket",
})
READ_TOOLS = frozenset({
    "get_onboarding_status", "get_device_status", "get_device_usage", "get_device_order_status",
    "get_settlement_status", "get_ticket_status", "read_pageindex",
})
TERMINAL_MOVES = frozenset({MoveType.END_CALL_POLITELY, MoveType.ESCALATE})

# Win-back (docs/TASKS.md W2). The Concern Bank's worries are the reasons for leaving; each maps to what Chanakya
# may do about it. Nothing here offers a discount, waiver or offer: the sources establish none.
CLEAR_REASON = 0.5  # belief needed before acting on a reason
MAX_PROBES = 2  # or act on the top reason after this many probes
NO_NEED_REASONS = frozenset({"not_needed", "customers_pay_cash"})  # thank them and stop: no pitch, no follow-up
ANSWER_ONCE_REASONS = frozenset({"competitor_qr", "trust_in_caller", "data_privacy", "language_comfort"})
VISIT_REASONS = frozenset({"rental_cost", "hidden_charges", "per_swipe_charges", "setup_hassle"})
WINBACK_FIX_TOOLS = {
    "device_issue": "raise_ticket",
    "settlement_delay": "raise_ticket",
    **{reason: "book_field_visit" for reason in VISIT_REASONS},
}
TICKET_CATEGORIES = {"device_issue": "device", "settlement_delay": "settlement"}
WINBACK_PITCH = frozenset({MoveType.RECOMMEND, MoveType.RESOLVE_CONCERN, MoveType.CONFIRM_CONSENT})

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
    r"\b(bhej|bhejo|bhejiye|send|kar do|kardo|kar dijiye|book|please|go ahead|daal do|chalega|bana do|bana dijiye"
    r"|banaiye|raise)\b|भेज|कर दीजिए|कर दो|बुक|बना दीजिए|बना दो|ਭੇਜ|ਕਰ ਦਿਓ|ਬਣਾ ਦਿਓ",
    re.IGNORECASE,
)
DENIAL = re.compile(
    r"\b(koi problem nahi|problem nahi hai|dikkat nahi|not a problem|no problem|not an issue|not worried)\b"
    r"|दिक्कत नहीं|समस्या नहीं|ਸਮੱਸਿਆ ਨਹੀਂ",
    re.IGNORECASE,
)
# Answers to "do you have two minutes?" (permission-first opening).
BUSY = re.compile(r"\b(busy|call later|later|baad mein (?:call|baat|phone)|abhi time nahi|time nahi hai|kal call"
                  r"|shaam ko call)\b|बाद में (?:कॉल|बात)|अभी टाइम नहीं|ਬਾਅਦ ਵਿੱਚ|ਹੁਣੇ ਸਮਾਂ ਨਹੀਂ", re.IGNORECASE)
GO_AHEAD = re.compile(r"\b(boliye|bataiye|batao|go ahead|tell me|haan ji|ji haan|sure|zaroor|bilkul)\b"
                      r"|बोलिए|बताइए|ज़रूर|ਦੱਸੋ|ਬੋਲੋ|ਜ਼ਰੂਰ", re.IGNORECASE)
PERMISSION_OPEN = frozenset({MoveType.ASK_PERMISSION, MoveType.SCHEDULE_FOLLOWUP, MoveType.END_CALL_POLITELY,
                             MoveType.ESCALATE, MoveType.DISCLOSE_AND_GREET})
MAX_PERMISSION_ASKS = 2
# "Let me think" is not an answer to "why did you stop?".
HESITANT = re.compile(r"\b(sochna padega|think about it|pata nahi|dekhte hain|not sure)\b|सोचना पड़ेगा|पता नहीं|ਸੋਚਣਾ ਪਵੇਗਾ",
                      re.IGNORECASE)
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


def permission_reply(turn) -> str:
    """Read an answer to "do you have two minutes?": ``yes``, ``no``, ``busy`` or ``unclear``.

    A short "haan" after a long pause is polite deflection (``cues.hesitation``), and a reply that is mostly
    fillers ("hmm... haan") is no answer either; both are ``unclear``, never permission.
    """
    text = turn.text
    if BUSY.search(text):
        return "busy"
    if merchant_declined(text) or (NEGATION.search(text) and not AFFIRM.search(text) and not GO_AHEAD.search(text)):
        return "no"
    if hesitation(turn).deflection or HESITANT.search(text) or len(FILLERS.findall(text)) * 3 >= max(1, len(text.split())):
        return "unclear"
    if NEGATION.search(text):
        return "unclear"
    return "yes" if AFFIRM.search(text) or GO_AHEAD.search(text) else "unclear"


def permission_answers(state: DialogueState) -> list[str]:
    """The merchant's answer to each permission question so far, in order."""
    answers, asked = [], False
    for turn in state.transcript.turns:
        if turn.speaker == "agent":
            asked = turn.move is not None and turn.move.type == MoveType.ASK_PERMISSION
        elif asked and turn.speaker == "merchant":
            answers.append(permission_reply(turn))
            asked = False
    return answers


def permission_granted(state: DialogueState) -> bool:
    """Whether the merchant clearly said yes to the permission question (always true when none is needed)."""
    return not state.card.permission_first or "yes" in permission_answers(state)


def is_winback(state: DialogueState) -> bool:
    """Whether this is a win-back mission for a merchant who stopped using the product."""
    return state.card.kind == MissionKind.WIN_BACK


def substantive(text: str) -> bool:
    """A real answer, not an acknowledgement ("achha"), a filler ("hmm") or a "let me think"."""
    words = max(1, len(text.split()))
    return not (DEFLECTIONS.match(text) or HESITANT.search(text) or len(FILLERS.findall(text)) * 3 >= words)


def reason_evidence(state: DialogueState) -> str | None:
    """The reason the merchant's latest real answer (after the disclosure) points to, if it is clear."""
    turns = state.transcript.turns
    disclosed_at = next((i for i, t in enumerate(turns) if t.speaker == "agent" and t.move is not None
                         and t.move.type == MoveType.DISCLOSE_AND_GREET), None)
    if disclosed_at is None or not turns or turns[-1].speaker != "merchant" or len(turns) - 1 <= disclosed_at:
        return None
    if not substantive(turns[-1].text):
        return None
    denied = ruled_out_concerns(state)
    ranked = [(cid, p) for cid, p in state.belief.top(len(state.belief.probabilities)) if cid not in denied]
    return ranked[0][0] if ranked and ranked[0][1] >= CLEAR_REASON else None


def answered_why(state: DialogueState) -> bool:
    """Whether the merchant has spoken since Chanakya asked why they stopped: only then can the reason be clear."""
    asked = False
    for turn in state.transcript.turns:
        if turn.speaker == "agent" and turn.move is not None and turn.move.type == MoveType.DISCOVER_NEED:
            asked = True
        elif asked and turn.speaker == "merchant":
            return True
    return False


def probes_used(state: DialogueState) -> int:
    """How many times Chanakya has gently asked about a specific worry."""
    return sum(1 for m in state.moves if m.type == MoveType.PROBE_CONCERN)


def winback_reason(state: DialogueState) -> str | None:
    """The reason for leaving Chanakya may act on: the belief's top worry once it is clear or two probes were used.

    Once Chanakya has acted on a reason (its moves carry ``args["reason"]``), that reason stays, so a yes that
    shifts the belief cannot strand the fix the merchant just agreed to.
    """
    locked = [m.args["reason"] for m in state.moves if m.args.get("reason")]
    if locked:
        return locked[-1]
    if not state.belief.probabilities or not answered_why(state):
        return None
    # A clear reason from a real answer is kept on Chanakya's next move as evidence, so a later "hmm" that swings
    # the belief does not erase what the merchant already said; "no, that was not it" after a probe rules one out.
    denied = ruled_out_concerns(state)
    noted = [m.args["evidence"] for m in state.moves if m.args.get("evidence") and m.args["evidence"] not in denied]
    evidence = reason_evidence(state) or (noted[-1] if noted else None)
    if evidence:
        return evidence
    ranked = [cid for cid, _ in state.belief.top(len(state.belief.probabilities)) if cid not in denied]
    return ranked[0] if ranked and probes_used(state) >= MAX_PROBES else None


def winback_fix(state: DialogueState) -> str | None:
    """The one write tool that fixes the current reason for leaving, if a system can fix it."""
    reason = winback_reason(state)
    return WINBACK_FIX_TOOLS.get(reason) if reason else None


def settlement_read(state: DialogueState) -> bool:
    """Whether the settlement system has been read on this call."""
    return any(d.call.tool == "get_settlement_status" for d in state.actions)


def winback_violations(move: Move, state: DialogueState) -> list[str]:
    """The win-back rules a move breaks; they bind every planner, including the look-ahead search."""
    problems = []
    reason = winback_reason(state)
    acting = move.type in WINBACK_PITCH or move.type == MoveType.TAKE_ACTION
    if move.type == MoveType.RECOMMEND:
        problems.append("winback_no_product_pitch")
    if reason is None and acting:
        problems.append("winback_listen_first")
    if reason in NO_NEED_REASONS and (acting or move.type in {MoveType.PROBE_CONCERN, MoveType.SCHEDULE_FOLLOWUP}):
        problems.append("winback_not_needed")
    if move.type == MoveType.CONFIRM_CONSENT and reason is not None and move.tool != WINBACK_FIX_TOOLS.get(reason):
        problems.append("winback_wrong_fix")
    if move.type == MoveType.TAKE_ACTION and move.tool in READ_TOOLS and move.tool == "get_settlement_status" \
            and reason != "settlement_delay":
        problems.append("winback_wrong_fix")
    if (move.type == MoveType.CONFIRM_CONSENT and reason == "settlement_delay" and not settlement_read(state)):
        problems.append("winback_read_first")
    answered = move.concern in resolved_concerns(state) if move.concern else False
    if move.type == MoveType.RESOLVE_CONCERN and (answered or (reason is not None and move.concern != reason)):
        problems.append("winback_answer_once")
    return problems


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
    if is_winback(state):
        problems.extend(winback_violations(move, state))
    if move.type == MoveType.ASK_PERMISSION:
        asks = sum(1 for m in state.moves if m.type == MoveType.ASK_PERMISSION)
        if not state.card.permission_first or permission_granted(state) or asks >= MAX_PERMISSION_ASKS:
            problems.append("permission_not_needed")
    elif not permission_granted(state) and move.type not in PERMISSION_OPEN:
        problems.append("permission_first")
    return problems


def is_legal(move: Move, state: DialogueState, bank: ConcernBank) -> bool:
    """Whether ``move`` satisfies every precondition."""
    return not violations(move, state, bank)


def legal_moves(state: DialogueState, bank: ConcernBank, product: str, consent_tool: str,
                top_concerns: int = 3) -> list[Move]:
    """Every legal candidate worth considering: moves for the top open concerns plus the mission moves."""
    open_concerns = [cid for cid, _ in open_belief(state).top(top_concerns)]
    candidates = [Move(type=MoveType.DISCLOSE_AND_GREET), Move(type=MoveType.ASK_PERMISSION),
                  Move(type=MoveType.DISCOVER_NEED)]
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
