"""Thread-safe async event store with pub/sub.

This is the spine of the Nesting Sandbox reasoning engine. Every box
publishes Events here; other boxes and the WebSocket layer subscribe to
receive them in real time.
"""

import asyncio
from datetime import datetime
from typing import Callable

from app.models import Event


class EventStore:
    """Thread-safe async event store with pub/sub."""

    def __init__(self) -> None:
        self.events: list[Event] = []
        self.subscribers: dict[str, asyncio.Queue[Event]] = {}
        self._lock = asyncio.Lock()
        self._ws_callbacks: list[Callable[[Event], object]] = []

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    async def publish(self, event: Event) -> None:
        """Add *event* and fan it out to every subscriber + WS callback.

        The sender (``event.source_box``) is **not** echoed back to its
        own subscription queue.
        """
        # Snapshot collections under the lock to avoid race conditions
        # with concurrent unsubscribe / remove_ws_callback (FIX 5).
        async with self._lock:
            self.events.append(event)
            subs = list(self.subscribers.items())
            cbs = list(self._ws_callbacks)

        # Fan-out to box subscribers (skip the sender)
        for sub_id, queue in subs:
            if sub_id != event.source_box:
                try:
                    await queue.put(event)
                except Exception:
                    pass

        # Fan-out to WebSocket broadcast callbacks
        for cb in cbs:
            try:
                await cb(event)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------

    async def subscribe(self, subscriber_id: str) -> asyncio.Queue[Event]:
        """Create and return a subscription queue for *subscriber_id*.

        If the subscriber already exists the existing queue is replaced.
        """
        queue: asyncio.Queue[Event] = asyncio.Queue()
        async with self._lock:
            self.subscribers[subscriber_id] = queue
        return queue

    async def unsubscribe(self, subscriber_id: str) -> None:
        """Remove a subscriber by id (no-op if absent)."""
        async with self._lock:
            self.subscribers.pop(subscriber_id, None)

    # ------------------------------------------------------------------
    # WebSocket integration
    # ------------------------------------------------------------------

    def add_ws_callback(self, callback: Callable[[Event], object]) -> None:
        """Register a coroutine / callable that receives every published event."""
        self._ws_callbacks.append(callback)

    def remove_ws_callback(self, callback: Callable[[Event], object]) -> None:
        """Remove a previously-registered WS callback (no-op if absent)."""
        try:
            self._ws_callbacks.remove(callback)
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_events_by_source(self, source: str) -> list[Event]:
        """Return all events emitted by *source* (e.g. ``"box1"``)."""
        return [e for e in self.events if e.source_box == source]

    def get_all_events(self) -> list[Event]:
        """Return a shallow copy of every event (for specialists with full read access)."""
        return list(self.events)

    def get_events_since(self, timestamp: datetime) -> list[Event]:
        """Return events with ``timestamp`` strictly after *timestamp*."""
        return [e for e in self.events if e.timestamp > timestamp]

    def get_events_by_type(self, event_type: str) -> list[Event]:
        """Return all events whose ``event_type`` matches *event_type*."""
        return [e for e in self.events if e.event_type == event_type]

    def get_events_by_source_and_type(
        self, source: str, event_type: str
    ) -> list[Event]:
        """Return events matching both *source* and *event_type*."""
        return [
            e
            for e in self.events
            if e.source_box == source and e.event_type == event_type
        ]

    @property
    def event_count(self) -> int:
        """Total number of stored events."""
        return len(self.events)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def clear(self) -> None:
        """Discard all events and tear down every subscriber queue."""
        async with self._lock:
            self.events.clear()
            self.subscribers.clear()
