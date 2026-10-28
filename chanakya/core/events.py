"""In-process event bus: every event is persisted first, then fanned out."""

from __future__ import annotations

import asyncio
import contextlib

from chanakya.core.interfaces import MissionStore
from chanakya.core.schemas import MissionEvent

QUEUE_SIZE = 1000


class Subscription:
    """Live events for one mission or all. Registered on creation, so nothing published afterwards is missed."""

    def __init__(self, bus: InProcessEventBus, mission_id: str | None):
        self._bus = bus
        self._entry = (mission_id, asyncio.Queue(QUEUE_SIZE))
        bus._queues.add(self._entry)

    def __aiter__(self) -> Subscription:
        return self

    async def __anext__(self) -> MissionEvent:
        return await self._entry[1].get()

    async def aclose(self) -> None:
        """Stop receiving events."""
        self._bus._queues.discard(self._entry)


class InProcessEventBus:
    """Fan-out of ledger events to live subscribers such as dashboard sockets."""

    def __init__(self, store: MissionStore):
        self.store = store
        self._queues: set[tuple[str | None, asyncio.Queue[MissionEvent]]] = set()

    async def publish(self, event: MissionEvent) -> MissionEvent:
        """Persist the event, then deliver it to every matching subscriber."""
        stored = self.store.append(event)
        for mission_id, queue in list(self._queues):
            if mission_id in (None, stored.mission_id):
                if queue.full():
                    # A stalled subscriber loses its oldest event, never blocks the publisher.
                    with contextlib.suppress(asyncio.QueueEmpty):
                        queue.get_nowait()
                queue.put_nowait(stored)
        return stored

    def subscribe(self, mission_id: str | None = None) -> Subscription:
        """Start receiving events published from now on, for one mission or all."""
        return Subscription(self, mission_id)

    @property
    def subscriber_count(self) -> int:
        """Number of live subscribers."""
        return len(self._queues)
