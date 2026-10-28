"""In-process event bus: every event is persisted first, then fanned out."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from chanakya.core.interfaces import MissionStore
from chanakya.core.schemas import MissionEvent

QUEUE_SIZE = 1000


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

    async def subscribe(self, mission_id: str | None = None) -> AsyncIterator[MissionEvent]:
        """Yield events published after subscribing, until the consumer stops."""
        entry = (mission_id, asyncio.Queue(QUEUE_SIZE))
        self._queues.add(entry)
        try:
            while True:
                yield await entry[1].get()
        finally:
            self._queues.discard(entry)

    @property
    def subscriber_count(self) -> int:
        """Number of live subscribers."""
        return len(self._queues)
