"""Protocols that let the two tracks build against each other before either side is merged."""

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from .events import Event, Handler
from .schemas import (
    ActionDecision,
    BeliefState,
    DialogueState,
    Mission,
    MissionCard,
    MissionEvent,
    MissionState,
    Move,
    PlanResult,
    ToolCall,
    ToolResult,
    ToolSpec,
    Turn,
    TwinReply,
)


@runtime_checkable
class BeliefTracker(Protocol):
    """Keeps a probability over hidden concerns, starting from the mission card's prior."""

    def start(self, prior: dict[str, float]) -> BeliefState: ...

    async def update(self, belief: BeliefState, turn: Turn, history: list[Turn]) -> BeliefState: ...


@runtime_checkable
class Planner(Protocol):
    """Chooses the next move, and re-checks intent before an irreversible write."""

    async def plan(self, state: DialogueState) -> PlanResult: ...

    async def reconsider(self, state: DialogueState, call: ToolCall) -> bool: ...


@runtime_checkable
class Realizer(Protocol):
    """Turns a move into speech in the merchant's language, grounded in sourced product text."""

    async def realize(self, move: Move, state: DialogueState) -> str: ...


@runtime_checkable
class ToolRegistry(Protocol):
    """Registered typed actions. Unknown names are rejected, never improvised."""

    def get(self, name: str) -> ToolSpec | None: ...

    def specs(self) -> list[ToolSpec]: ...

    async def execute(self, call: ToolCall) -> ToolResult: ...


@runtime_checkable
class SafetyGate(Protocol):
    """Checks membership, consent and policy before any action runs."""

    async def check(self, call: ToolCall, state: DialogueState) -> ActionDecision: ...


@runtime_checkable
class MissionStore(Protocol):
    """Mission persistence and the append-only ledger."""

    def create(self, card: MissionCard) -> Mission: ...

    def get(self, mission_id: str) -> Mission | None: ...

    def advance(self, mission_id: str, state: MissionState, reason: str = "") -> Mission: ...

    def append_event(self, event: MissionEvent) -> None: ...

    def events(self, mission_id: str | None = None) -> list[MissionEvent]: ...


@runtime_checkable
class MerchantTwin(Protocol):
    """A simulated merchant that replies in character and may walk away."""

    def opening(self) -> str: ...

    async def respond(self, agent_text: str, move: Move | None) -> TwinReply: ...


@runtime_checkable
class EventBus(Protocol):
    """In-process typed events; every published event is persisted."""

    def subscribe(self, kind: str | None, handler: Handler) -> Callable[[], None]: ...

    async def publish(self, event: Event) -> None: ...
