"""Pydantic models for every piece of data that crosses a module boundary."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def new_id(prefix: str) -> str:
    """Return a short unique id such as ``m_3f9c2a1b7d4e``."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def utcnow() -> datetime:
    """Timezone-aware current time in UTC."""
    return datetime.now(UTC)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── Merchants and signals ────────────────────────────────────────────────


class ContactWindow(Model):
    """Preferred local hours for contact, 24-hour clock, end exclusive."""

    start_hour: int = Field(9, ge=0, le=23)
    end_hour: int = Field(21, ge=1, le=24)

    @model_validator(mode="after")
    def _ordered(self) -> ContactWindow:
        if self.end_hour <= self.start_hour:
            raise ValueError("end_hour must be after start_hour")
        return self

    def contains(self, hour: int) -> bool:
        """True when ``hour`` falls inside the window."""
        return self.start_hour <= hour < self.end_hour


class Merchant(Model):
    id: str
    name: str
    business_type: str
    city: str
    language: str = "hi-IN"
    contact_window: ContactWindow = Field(default_factory=ContactWindow)
    do_not_call: bool = False
    has_soundbox: bool = False
    has_card_machine: bool = False
    phone_last4: str | None = None
    relationship: Literal["customer", "prospect", "former"] = "customer"
    churned_at: datetime | None = None  # when a former customer stopped using the product


class Door(StrEnum):
    """How a mission reached Chanakya (docs/IDEA.md 3.2)."""

    MERCHANT = "merchant"  # the merchant raised a hand
    DATA = "data"  # the merchant's data says so
    HUMAN = "human"  # a colleague handed it over


class SignalKind(StrEnum):
    CALLBACK_REQUEST = "callback_request"
    ONBOARDING_STALLED = "onboarding_stalled"
    PRICE_QUESTION_DROPPED = "price_question_dropped"
    UPI_RISING_NO_SOUNDBOX = "upi_rising_no_soundbox"
    CARD_ATTEMPTS_NO_POS = "card_attempts_no_pos"
    SOUNDBOX_UNUSED = "soundbox_unused"
    RENTAL_MISSED = "rental_missed"
    LEAD_LIST_ASSIGNED = "lead_list_assigned"
    FIELD_AGENT_NOTE = "field_agent_note"
    HUMAN_CALL_DROPPED = "human_call_dropped"
    MERCHANT_CHURNED = "merchant_churned"


class MerchantSignal(Model):
    id: str = Field(default_factory=lambda: new_id("sig"))
    merchant_id: str
    kind: SignalKind
    door: Door
    source: str = Field(description="Who or what raised it, for example 'mock product page'")
    details: dict[str, Any] = Field(default_factory=dict)
    at: datetime = Field(default_factory=utcnow)


# ── Missions ─────────────────────────────────────────────────────────────


class MissionType(StrEnum):
    SALES = "sales"
    RETENTION = "retention"
    FOLLOW_UP = "follow_up"
    WIN_BACK = "win_back"


class MissionState(StrEnum):
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


TERMINAL_STATES = frozenset(
    {
        MissionState.DONE,
        MissionState.ESCALATED,
        MissionState.CLOSED_NOT_INTERESTED,
        MissionState.CLOSED_UNREACHABLE,
        MissionState.FAILED,
    }
)


def _normalized(probabilities: dict[str, float]) -> dict[str, float]:
    if any(value < 0 for value in probabilities.values()):
        raise ValueError("probabilities must be non-negative")
    total = sum(probabilities.values())
    if not probabilities or total <= 0:
        return {}
    return {key: value / total for key, value in probabilities.items()}


class MissionCard(Model):
    """Everything Chanakya knows about a mission before the first contact."""

    merchant_id: str
    merchant_name: str
    language: str = "hi-IN"
    door: Door
    signal_kind: SignalKind
    signal_id: str
    mission_type: MissionType
    goal: str
    product: str | None = None
    why_now: str
    starting_worries: dict[str, float] = Field(default_factory=dict)
    priority: float = Field(0.0, ge=0)
    contact_window: ContactWindow = Field(default_factory=ContactWindow)

    @field_validator("starting_worries")
    @classmethod
    def _normalize(cls, value: dict[str, float]) -> dict[str, float]:
        return _normalized(value)


class Mission(Model):
    id: str = Field(default_factory=lambda: new_id("m"))
    card: MissionCard
    state: MissionState = MissionState.CREATED
    outcome: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def is_open(self) -> bool:
        """False once the mission reached a terminal state."""
        return self.state not in TERMINAL_STATES


class EventKind(StrEnum):
    MISSION_CREATED = "mission_created"
    MISSION_UPDATED = "mission_updated"
    STATE_CHANGED = "state_changed"
    SIGNAL_RECEIVED = "signal_received"
    TURN_COMPLETED = "turn_completed"
    BELIEF_UPDATED = "belief_updated"
    PLAN_COMPUTED = "plan_computed"
    AI_DISCLOSED = "ai_disclosed"
    CONSENT_GIVEN = "consent_given"
    CONSENT_DECLINED = "consent_declined"
    ACTION_DECISION = "action_decision"
    FOLLOWUP_SCHEDULED = "followup_scheduled"
    VERIFICATION_CHECKED = "verification_checked"
    HANDOFF_CREATED = "handoff_created"
    HANDOFF_CLAIMED = "handoff_claimed"
    HANDOFF_RESOLVED = "handoff_resolved"
    LEAVING_REASON_RECORDED = "leaving_reason_recorded"  # a win-back call's top reason for leaving
    HOLDOUT_ASSIGNED = "holdout_assigned"  # an eligible former merchant kept out of win-back calls for comparison
    APPROVAL_REQUESTED = "approval_requested"  # a high-risk action waits for a person (B10)
    APPROVAL_DECIDED = "approval_decided"  # approved, rejected or expired
    NOTE = "note"


class MissionEvent(Model):
    """One append-only ledger entry. ``seq`` is assigned by the MissionStore."""

    id: str = Field(default_factory=lambda: new_id("ev"))
    mission_id: str
    seq: int = 0
    kind: EventKind
    payload: dict[str, Any] = Field(default_factory=dict)
    at: datetime = Field(default_factory=utcnow)

    @classmethod
    def of(cls, mission_id: str, kind: EventKind, data: BaseModel | dict[str, Any] | None = None) -> MissionEvent:
        """Build an event whose payload is a model dumped to JSON-safe data."""
        payload = data.model_dump(mode="json") if isinstance(data, BaseModel) else dict(data or {})
        return cls(mission_id=mission_id, kind=kind, payload=payload)


# ── Conversation and brain ───────────────────────────────────────────────


class Concern(Model):
    id: str
    label: str
    description: str
    phrasings: dict[str, list[str]] = Field(default_factory=dict, description="language code -> example phrasings")
    resolve_conditions: list[str] = Field(default_factory=list, description="knowledge node ids that resolve it")


class BeliefState(Model):
    """Probability of each hidden concern; always normalized."""

    probabilities: dict[str, float]
    turn: int = 0

    @field_validator("probabilities")
    @classmethod
    def _normalize(cls, value: dict[str, float]) -> dict[str, float]:
        return _normalized(value)

    def top(self, n: int = 3) -> list[tuple[str, float]]:
        """The ``n`` most likely concerns, highest first."""
        return sorted(self.probabilities.items(), key=lambda item: item[1], reverse=True)[:n]


class MoveType(StrEnum):
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


class ToolKind(StrEnum):
    READ = "read"
    WRITE = "write"


class ToolCall(Model):
    id: str = Field(default_factory=lambda: new_id("call"))
    mission_id: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolResult(Model):
    call_id: str
    tool: str
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ToolInfo(Model):
    """Registry description of a tool; ``args_schema`` is its JSON schema."""

    name: str
    system: str
    kind: ToolKind
    description: str
    args_schema: dict[str, Any] = Field(default_factory=dict)
    irreversible: bool = False


class Move(Model):
    type: MoveType
    concern_id: str | None = None
    product: str | None = None
    tool_call: ToolCall | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _needs(self) -> Move:
        if self.type == MoveType.TAKE_ACTION and self.tool_call is None:
            raise ValueError("TAKE_ACTION needs a tool_call")
        if self.type in {MoveType.PROBE_CONCERN, MoveType.RESOLVE_CONCERN} and not self.concern_id:
            raise ValueError(f"{self.type} needs a concern_id")
        return self


class ScoredMove(Model):
    move: Move
    score: float
    visits: int = 0


class PlanResult(Model):
    chosen: Move
    candidates: list[ScoredMove] = Field(default_factory=list)
    tree: dict[str, Any] | None = Field(None, description="search tree for the dashboard")
    elapsed_ms: float = 0.0
    fallback: bool = False


class Speaker(StrEnum):
    AGENT = "agent"
    MERCHANT = "merchant"
    HUMAN = "human"


class Turn(Model):
    speaker: Speaker
    text: str
    language: str | None = None
    move: Move | None = None
    cues: dict[str, float] = Field(default_factory=dict, description="for example pause_ms, filler_count")
    at: datetime = Field(default_factory=utcnow)


class Transcript(Model):
    mission_id: str
    turns: list[Turn] = Field(default_factory=list)


class TwinReply(Model):
    text: str
    willingness: float = Field(ge=0, le=1)
    ended: bool = False


class PlanContext(Model):
    """What the planner and realizer see on each turn."""

    mission: Mission
    belief: BeliefState
    transcript: Transcript


# ── Actions and humans ───────────────────────────────────────────────────


class Verdict(StrEnum):
    EXECUTED = "executed"
    BLOCKED = "blocked"
    FAILED = "failed"
    REJECTED = "rejected"  # unknown tool or invalid arguments
    PENDING = "pending"  # passed every check, waiting for a person's approval (B10)


class ActionDecision(Model):
    call: ToolCall
    verdict: Verdict
    reason: str
    kind: ToolKind | None = None
    result: ToolResult | None = None
    at: datetime = Field(default_factory=utcnow)


class HandoffStatus(StrEnum):
    OPEN = "open"
    CLAIMED = "claimed"
    RESOLVED = "resolved"


class HandoffCard(Model):
    id: str = Field(default_factory=lambda: new_id("ho"))
    mission_id: str
    merchant_name: str
    language: str
    reason: str
    summary: str
    open_concerns: dict[str, float] = Field(default_factory=dict)
    tried_moves: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    urgent: bool = False
    status: HandoffStatus = HandoffStatus.OPEN
    claimed_by: str | None = None
    resolution: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
