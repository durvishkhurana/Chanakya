"""Protocols that let each track code against the other before it exists."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from chanakya.core.schemas import (
    ActionDecision,
    BeliefState,
    Mission,
    MissionCard,
    MissionEvent,
    MissionState,
    Move,
    PlanContext,
    PlanResult,
    ToolCall,
    ToolInfo,
    ToolResult,
    Transcript,
    Turn,
    TwinReply,
)


class UnknownToolError(LookupError):
    """Raised for a tool name that is not in the registry."""


class IllegalTransitionError(ValueError):
    """Raised for a mission state change the state machine does not allow."""


@runtime_checkable
class BeliefTracker(Protocol):
    def initial(self, card: MissionCard) -> BeliefState:
        """Starting belief, seeded from the mission card's starting worries."""
        ...

    async def update(self, belief: BeliefState, turn: Turn, transcript: Transcript) -> BeliefState:
        """Belief after one more merchant turn."""
        ...


@runtime_checkable
class Planner(Protocol):
    async def plan(self, context: PlanContext) -> PlanResult:
        """Choose the next move."""
        ...

    async def reconsider(self, context: PlanContext, call: ToolCall) -> bool:
        """Second look before an irreversible write; False cancels it."""
        ...


@runtime_checkable
class Realizer(Protocol):
    async def realize(self, move: Move, context: PlanContext) -> str:
        """Turn a move into what the agent says."""
        ...


@runtime_checkable
class ToolRegistry(Protocol):
    def tools(self) -> list[ToolInfo]:
        """Every registered tool."""
        ...

    def get(self, name: str) -> ToolInfo | None:
        """The tool's description, or None when unknown."""
        ...

    def validate(self, call: ToolCall) -> ToolCall:
        """Return the call with validated arguments; raise UnknownToolError or ValueError."""
        ...

    def execute(self, call: ToolCall) -> ToolResult:
        """Run a validated call against its system. Never call directly; go through the SafetyGate."""
        ...


@runtime_checkable
class SafetyGate(Protocol):
    async def submit(self, call: ToolCall) -> ActionDecision:
        """Check, execute or block a tool call and record the decision in the ledger."""
        ...


@runtime_checkable
class MissionStore(Protocol):
    def create(self, mission: Mission) -> Mission:
        """Persist a new mission."""
        ...

    def get(self, mission_id: str) -> Mission | None:
        """Current state of one mission."""
        ...

    def list(self, states: set[MissionState] | None = None) -> list[Mission]:
        """Missions, optionally filtered by state."""
        ...

    def save(self, mission: Mission) -> Mission:
        """Overwrite a mission's card, state or outcome."""
        ...

    def append(self, event: MissionEvent) -> MissionEvent:
        """Append an event and return it with its sequence number."""
        ...

    def events(self, mission_id: str | None = None, after_seq: int = 0) -> list[MissionEvent]:
        """Events in order, for one mission or all."""
        ...


@runtime_checkable
class MerchantTwin(Protocol):
    async def respond(self, transcript: Transcript, agent_text: str) -> TwinReply:
        """The simulated merchant's reply to what the agent just said."""
        ...


@runtime_checkable
class EventBus(Protocol):
    async def publish(self, event: MissionEvent) -> MissionEvent:
        """Persist the event through the MissionStore, then fan it out to subscribers."""
        ...

    def subscribe(self, mission_id: str | None = None) -> AsyncIterator[MissionEvent]:
        """Live events from the moment of this call, for one mission or all; supports ``aclose()``."""
        ...
