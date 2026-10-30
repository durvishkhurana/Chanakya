"""Pydantic v2 models for every piece of data that crosses a module boundary."""

import math
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def new_id(prefix: str) -> str:
    """Return a short unique identifier such as ``m_1a2b3c4d5e6f``."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def utc_now() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(UTC)


class Contract(BaseModel):
    """Base for all contracts: unknown fields are rejected so typos surface early."""

    model_config = ConfigDict(extra="forbid")


# ── Merchants and personas ──────────────────────────────────────────────


class ContactWindow(Contract):
    """Local hours in which a merchant prefers to be called, for example 14 to 17."""

    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24)

    @model_validator(mode="after")
    def _ordered(self) -> "ContactWindow":
        if self.end_hour <= self.start_hour:
            raise ValueError("end_hour must be after start_hour")
        return self

    def contains(self, hour: int) -> bool:
        """Return whether a local hour falls inside the window."""
        return self.start_hour <= hour < self.end_hour


class Merchant(Contract):
    """A merchant as the mission system sees them. Never stores a real phone number."""

    merchant_id: str
    name: str
    business_type: str
    city: str
    language: str = "hi-IN"
    contact_window: ContactWindow | None = None
    do_not_call: bool = False
    devices: list[str] = Field(default_factory=list)
    relationship: Literal["customer", "prospect", "former"] = "customer"
    churned_at: datetime | None = None


class Persona(Contract):
    """A simulated merchant: visible traits plus hidden concerns the agent must discover."""

    persona_id: str
    business_type: str
    city: str
    language: str
    patience: float = Field(ge=0, le=1)
    busyness: float = Field(ge=0, le=1)
    tech_comfort: float = Field(ge=0, le=1)
    hidden_concerns: list[str] = Field(min_length=1)
    willingness_prior: float = Field(ge=0, le=1)
    adversarial: Literal["angry", "prompt_injection", "fake_staff_otp", "distressed"] | None = None
    split: Literal["planning", "evaluation"] = "planning"
    # A former customer's first hidden concern is their hidden reason for leaving (win-back missions).
    relationship: Literal["prospect", "former"] = "prospect"
    notes: str = ""


# ── Concerns and belief ─────────────────────────────────────────────────


class ResolveCondition(Contract):
    """What genuinely resolves a concern, grounded in sourced knowledge nodes."""

    description: str
    knowledge_node_ids: list[str] = Field(min_length=1)


class Concern(Contract):
    """A hidden merchant worry from the Concern Bank."""

    concern_id: str
    description: str
    phrasings: dict[str, list[str]] = Field(description="Language label to example phrasings")
    resolve_conditions: list[ResolveCondition] = Field(min_length=1)


class BeliefState(Contract):
    """A probability for each concern in the Concern Bank."""

    probabilities: dict[str, float]
    turn_index: int = 0

    @field_validator("probabilities")
    @classmethod
    def _distribution(cls, value: dict[str, float]) -> dict[str, float]:
        if not value:
            raise ValueError("belief needs at least one concern")
        if any(not math.isfinite(p) or p < 0 for p in value.values()):
            raise ValueError("probabilities must be finite and non-negative")
        if abs(sum(value.values()) - 1.0) > 1e-6:
            raise ValueError("probabilities must sum to 1")
        return value

    def top(self, n: int = 3) -> list[tuple[str, float]]:
        """Return the ``n`` most likely concerns, highest first, ties broken by name."""
        return sorted(self.probabilities.items(), key=lambda item: (-item[1], item[0]))[:n]


# ── Moves and planning ──────────────────────────────────────────────────


class MoveType(StrEnum):
    """The typed move library from docs/IDEA.md 3.4."""

    DISCLOSE_AND_GREET = "DISCLOSE_AND_GREET"
    ASK_PERMISSION = "ASK_PERMISSION"
    DISCOVER_NEED = "DISCOVER_NEED"
    PROBE_CONCERN = "PROBE_CONCERN"
    RESOLVE_CONCERN = "RESOLVE_CONCERN"
    RECOMMEND = "RECOMMEND"
    CONFIRM_CONSENT = "CONFIRM_CONSENT"
    TAKE_ACTION = "TAKE_ACTION"
    SCHEDULE_FOLLOWUP = "SCHEDULE_FOLLOWUP"
    ESCALATE = "ESCALATE"
    END_CALL_POLITELY = "END_CALL_POLITELY"


class EndReason(StrEnum):
    """Why Chanakya ends a call; the mission's close outcome and the closing line are read from it."""

    DECLINED = "declined"
    SENSITIVE_REQUEST = "sensitive_request"
    ACTION_TAKEN = "action_taken"
    FOLLOWUP_SCHEDULED = "followup_scheduled"
    NO_LEGAL_MOVE = "no_legal_move"
    NOT_NEEDED = "not_needed"  # a win-back merchant who has no use for the product: thank them, no follow-up
    ACCEPTED_CHOICE = "accepted_choice"  # a win-back merchant who chose something else after one answer


class Move(Contract):
    """One planned conversational move with its typed arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: MoveType
    concern: str | None = None
    product: str | None = None
    tool: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    end_reason: EndReason | None = None

    def key(self) -> str:
        """Return a compact identity such as ``RESOLVE_CONCERN(hidden_charges)``."""
        target = self.concern or self.product or self.tool
        return f"{self.type.value}({target})" if target else self.type.value


class ScoredMove(Contract):
    """A candidate move with its look-ahead score."""

    move: Move
    score: float
    visits: int = 0
    prior: float = 0.0


class PlanResult(Contract):
    """The planner's choice, its alternatives and an optional search tree for the dashboard."""

    move: Move
    candidates: list[ScoredMove] = Field(default_factory=list)
    elapsed_ms: float = 0.0
    fallback: bool = False
    tree: dict[str, Any] | None = None


# ── Conversation ────────────────────────────────────────────────────────


class Turn(Contract):
    """One utterance. ``pause_before_ms`` and ``duration_ms`` feed hesitation cues."""

    speaker: Literal["agent", "merchant", "human_agent"]
    text: str
    language: str | None = None
    move: Move | None = None
    pause_before_ms: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    at: datetime = Field(default_factory=utc_now)


class ConsentRecord(Contract):
    """An explicit yes to one write action, tied to the merchant turn that gave it."""

    tool: str
    turn_index: int = Field(ge=0)
    utterance: str


class Transcript(Contract):
    """All turns of a conversation plus the consents captured in it."""

    mission_id: str
    turns: list[Turn] = Field(default_factory=list)
    consents: list[ConsentRecord] = Field(default_factory=list)
    disclosed_ai: bool = False

    def merchant_turns(self) -> list[Turn]:
        """Return only the merchant's turns."""
        return [turn for turn in self.turns if turn.speaker == "merchant"]

    def has_consent(self, tool: str) -> bool:
        """Return whether the merchant explicitly agreed to ``tool`` in this transcript."""
        return any(
            consent.tool == tool
            and consent.turn_index < len(self.turns)
            and self.turns[consent.turn_index].speaker == "merchant"
            for consent in self.consents
        )


# ── Missions ────────────────────────────────────────────────────────────


class Door(StrEnum):
    """How a mission entered: the merchant, their data, or a human colleague."""

    MERCHANT = "merchant"
    DATA = "data"
    HUMAN = "human"


class TriggerType(StrEnum):
    """Every mission trigger from docs/IDEA.md 3.2."""

    CALLBACK_REQUEST = "callback_request"
    ONBOARDING_STUCK = "onboarding_stuck"
    PRODUCT_QUESTION = "product_question"
    CARD_MACHINE_PRICE_QUESTION = "card_machine_price_question"
    UPI_RISING_NO_SOUNDBOX = "upi_rising_no_soundbox"
    CARD_DEMAND_NO_POS = "card_demand_no_pos"
    SOUNDBOX_UNUSED = "soundbox_unused"
    RENTAL_MISSED = "rental_missed"
    LEAD_LIST = "lead_list"
    FIELD_NOTE = "field_note"
    DROPPED_CALL = "dropped_call"
    MERCHANT_CHURNED = "merchant_churned"


TRIGGER_DOORS: dict[TriggerType, Door] = {
    TriggerType.CALLBACK_REQUEST: Door.MERCHANT,
    TriggerType.ONBOARDING_STUCK: Door.MERCHANT,
    TriggerType.PRODUCT_QUESTION: Door.MERCHANT,
    TriggerType.CARD_MACHINE_PRICE_QUESTION: Door.MERCHANT,
    TriggerType.UPI_RISING_NO_SOUNDBOX: Door.DATA,
    TriggerType.CARD_DEMAND_NO_POS: Door.DATA,
    TriggerType.SOUNDBOX_UNUSED: Door.DATA,
    TriggerType.RENTAL_MISSED: Door.DATA,
    TriggerType.LEAD_LIST: Door.HUMAN,
    TriggerType.FIELD_NOTE: Door.HUMAN,
    TriggerType.DROPPED_CALL: Door.HUMAN,
    TriggerType.MERCHANT_CHURNED: Door.DATA,
}


class MissionKind(StrEnum):
    """The broad goal of a mission."""

    SALES = "sales"
    RETENTION = "retention"
    FOLLOW_UP = "follow_up"
    WIN_BACK = "win_back"


class MissionState(StrEnum):
    """Mission states from docs/IDEA.md 3.1."""

    CREATED = "CREATED"
    SCHEDULED = "SCHEDULED"
    CONTACTING = "CONTACTING"
    IN_CONVERSATION = "IN_CONVERSATION"
    ACTION_PENDING = "ACTION_PENDING"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    VERIFYING = "VERIFYING"
    DONE = "DONE"
    ESCALATED = "ESCALATED"
    CLOSED_NOT_INTERESTED = "CLOSED_NOT_INTERESTED"
    CLOSED_UNREACHABLE = "CLOSED_UNREACHABLE"
    FAILED = "FAILED"


TERMINAL_STATES = frozenset({
    MissionState.DONE,
    MissionState.ESCALATED,
    MissionState.CLOSED_NOT_INTERESTED,
    MissionState.CLOSED_UNREACHABLE,
    MissionState.FAILED,
})


class MerchantSignal(Contract):
    """A raw trigger from any of the three doors, before it becomes a mission card."""

    signal_id: str = Field(default_factory=lambda: new_id("s"))
    merchant_id: str
    trigger: TriggerType
    observed_at: datetime = Field(default_factory=utc_now)
    data: dict[str, Any] = Field(default_factory=dict)
    source: str = ""


class MissionCard(Contract):
    """Why this merchant, why now, and the worries the call should start from."""

    mission_id: str = Field(default_factory=lambda: new_id("m"))
    merchant: Merchant
    kind: MissionKind
    goal: str
    door: Door
    trigger: TriggerType
    why_now: str
    starting_worries: dict[str, float]
    chance: float = Field(default=0.5, ge=0, le=1)
    value: float = Field(default=1.0, ge=0)
    context: str = ""
    # The merchant did not ask to be called (lead list, PERMISSION_FIRST_ENABLED): ask for two minutes before anything.
    permission_first: bool = False

    @field_validator("starting_worries")
    @classmethod
    def _prior(cls, value: dict[str, float]) -> dict[str, float]:
        if not value or any(p < 0 for p in value.values()) or abs(sum(value.values()) - 1.0) > 1e-6:
            raise ValueError("starting_worries must be a probability distribution")
        return value

    @property
    def priority(self) -> float:
        """Expected value: chance of success times value of the outcome."""
        return self.chance * self.value


class Mission(Contract):
    """A mission and its current state; its history lives in the ledger."""

    card: MissionCard
    state: MissionState = MissionState.CREATED
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @property
    def mission_id(self) -> str:
        """The mission's identifier, taken from its card."""
        return self.card.mission_id


class MissionEvent(Contract):
    """One append-only ledger entry; every bus event is persisted as one of these."""

    event_id: str = Field(default_factory=lambda: new_id("e"))
    mission_id: str | None = None
    kind: str
    at: datetime = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)


# ── Actions ─────────────────────────────────────────────────────────────


class ToolSpec(Contract):
    """A registered action: its name, whether it writes, and its JSON argument schema."""

    name: str
    access: Literal["read", "write"]
    system: str
    description: str
    args_schema: dict[str, Any] = Field(default_factory=dict)
    high_risk: bool = False


class ToolCall(Contract):
    """A request to run one registered tool."""

    call_id: str = Field(default_factory=lambda: new_id("c"))
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    mission_id: str | None = None


class ToolResult(Contract):
    """The outcome of a tool call."""

    call_id: str
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ActionDecision(Contract):
    """What the safety gate decided for a call, and why. Written to the ledger for every attempt."""

    call: ToolCall
    verdict: Literal["executed", "blocked", "pending_approval", "failed"]
    reason: str
    result: ToolResult | None = None
    at: datetime = Field(default_factory=utc_now)


# ── Dialogue state and humans ───────────────────────────────────────────


class DialogueState(Contract):
    """Everything the planner and realizer need to decide and phrase the next move."""

    card: MissionCard
    belief: BeliefState
    transcript: Transcript
    moves: list[Move] = Field(default_factory=list)
    actions: list[ActionDecision] = Field(default_factory=list)
    ended: bool = False

    def last_merchant_text(self) -> str:
        """Return the merchant's most recent utterance, or an empty string."""
        turns = self.transcript.merchant_turns()
        return turns[-1].text if turns else ""


class HandoffCard(Contract):
    """Context a human needs so the merchant never repeats themselves."""

    mission_id: str
    merchant: Merchant
    reason: str
    top_concerns: dict[str, float]
    tried_moves: list[Move] = Field(default_factory=list)
    actions: list[ActionDecision] = Field(default_factory=list)
    summary: str
    created_at: datetime = Field(default_factory=utc_now)


class TwinReply(Contract):
    """A simulated merchant's reply and its hidden state after the agent's turn."""

    text: str
    willingness: float = Field(ge=0, le=1)
    patience: float = Field(ge=0, le=1)
    ended: bool = False
    consented: bool = False
    resolved: list[str] = Field(default_factory=list)
