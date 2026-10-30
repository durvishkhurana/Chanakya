"""Typed events and an in-process async bus that persists every event through the mission store."""

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, TypeAdapter

from .schemas import (
    ActionDecision,
    BeliefState,
    Contract,
    HandoffCard,
    MissionCard,
    MissionEvent,
    MissionState,
    Move,
    PlanResult,
    Turn,
    utc_now,
)

logger = logging.getLogger(__name__)


class Event(Contract):
    """Base for bus events. ``kind`` is the discriminator stored in the ledger."""

    kind: str
    mission_id: str | None = None
    at: datetime = Field(default_factory=utc_now)


class MissionCreated(Event):
    kind: Literal["MissionCreated"] = "MissionCreated"
    card: MissionCard


class MissionStateChanged(Event):
    kind: Literal["MissionStateChanged"] = "MissionStateChanged"
    from_state: MissionState
    to_state: MissionState
    reason: str = ""


class BeliefUpdated(Event):
    kind: Literal["BeliefUpdated"] = "BeliefUpdated"
    belief: BeliefState
    latency_ms: float = 0.0
    evidence: dict[str, float] = Field(default_factory=dict)
    scorer: str | None = None  # lexical, llm or embedding


class PlanComputed(Event):
    kind: Literal["PlanComputed"] = "PlanComputed"
    plan: PlanResult


class TurnCompleted(Event):
    kind: Literal["TurnCompleted"] = "TurnCompleted"
    turn: Turn
    belief: BeliefState | None = None
    move: Move | None = None


class ActionDecided(Event):
    kind: Literal["ActionDecided"] = "ActionDecided"
    decision: ActionDecision


class HandoffCreated(Event):
    kind: Literal["HandoffCreated"] = "HandoffCreated"
    card: HandoffCard


class CoachSuggestion(Event):
    kind: Literal["CoachSuggestion"] = "CoachSuggestion"
    move: Move
    reason: str


AnyEvent = Annotated[
    MissionCreated | MissionStateChanged | BeliefUpdated | PlanComputed | TurnCompleted
    | ActionDecided | HandoffCreated | CoachSuggestion,
    Field(discriminator="kind"),
]
_EVENT_ADAPTER: TypeAdapter[Any] = TypeAdapter(AnyEvent)


def to_ledger(event: Event) -> MissionEvent:
    """Convert a bus event into its append-only ledger form."""
    return MissionEvent(
        mission_id=event.mission_id, kind=event.kind, at=event.at,
        payload=event.model_dump(mode="json", exclude={"kind", "mission_id", "at"}),
    )


def from_ledger(entry: MissionEvent) -> Event:
    """Rebuild the typed event from a ledger entry, for replay."""
    return _EVENT_ADAPTER.validate_python(
        {**entry.payload, "kind": entry.kind, "mission_id": entry.mission_id, "at": entry.at}
    )


Handler = Callable[[Event], Awaitable[None] | None]


class InProcessEventBus:
    """Publish persists first, then notifies subscribers; a failing subscriber never blocks others."""

    def __init__(self, store=None):
        self.store = store
        self._handlers: list[tuple[str | None, Handler]] = []

    def subscribe(self, kind: str | None, handler: Handler) -> Callable[[], None]:
        """Call ``handler`` for events of ``kind`` (``None`` for all). Returns an unsubscribe function."""
        entry = (kind, handler)
        self._handlers.append(entry)
        return lambda: self._handlers.remove(entry) if entry in self._handlers else None

    async def publish(self, event: Event) -> None:
        """Persist ``event`` through the store, then deliver it to matching subscribers."""
        if self.store is not None:
            self.store.append_event(to_ledger(event))
        for kind, handler in list(self._handlers):
            if kind is not None and kind != event.kind:
                continue
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception:  # One faulty subscriber must not lose events for others.
                logger.exception("Event subscriber failed for %s", event.kind)
