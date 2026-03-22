"""Conflict detection — finds contradictions between boxes and triggers debate."""

import asyncio
import logging
import re
from typing import Optional, Callable
from openai import AsyncOpenAI
from app.models import Event
from app.engine.event_store import EventStore
from app.engine.cost_tracker import CostTracker

logger = logging.getLogger(__name__)

# Event types worth checking for conflicts
_SUBSTANTIVE_TYPES = {
    "conclusion", "hypothesis", "evidence", "discovery",
    "resolution", "rebuttal", "connection", "approach",
}

# Maximum pairs to check per scan
_MAX_PAIRS_PER_SCAN = 10


class ConflictDetector:
    """Watches the event store for contradictory findings between boxes."""

    def __init__(
        self,
        event_store: EventStore,
        cost_tracker: CostTracker,
        client: AsyncOpenAI,
        gate_model: str = "gpt-4.1-nano",
        scan_interval: float = 8.0,
    ):
        self.event_store = event_store
        self.cost_tracker = cost_tracker
        self.client = client
        self.gate_model = gate_model
        self.scan_interval = scan_interval
        self._checked_pairs: set[tuple[str, str]] = set()
        self._cancelled = False
        self._last_scan_idx = 0

    def cancel(self):
        self._cancelled = True

    async def run(self):
        """Main loop — periodically scans for conflicts."""
        # Wait a bit before first scan to let findings accumulate
        await asyncio.sleep(15)

        while not self._cancelled:
            try:
                await self._scan()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Conflict detector scan failed")

            await asyncio.sleep(self.scan_interval)

    async def _scan(self):
        """Scan recent events for contradictions."""
        all_events = self.event_store.get_all_events()

        # Only look at new events since last scan
        new_events = all_events[self._last_scan_idx:]
        self._last_scan_idx = len(all_events)

        if not new_events:
            return

        # Get substantive events from different boxes
        substantive = [
            e for e in all_events
            if e.event_type in _SUBSTANTIVE_TYPES
            and not e.source_box.startswith("system:")
            and e.source_box != "user"
        ]

        if len(substantive) < 2:
            return

        # Build pairs from different boxes (focus on recent vs all)
        new_substantive = [e for e in new_events if e in substantive]
        if not new_substantive:
            return

        pairs = []
        for new_evt in new_substantive:
            for old_evt in substantive:
                if old_evt.id == new_evt.id:
                    continue
                if old_evt.source_box == new_evt.source_box:
                    continue
                pair_key = tuple(sorted([new_evt.id, old_evt.id]))
                if pair_key in self._checked_pairs:
                    continue
                pairs.append((new_evt, old_evt, pair_key))

        # Limit pairs per scan
        pairs = pairs[:_MAX_PAIRS_PER_SCAN]

        for event_a, event_b, pair_key in pairs:
            if self._cancelled:
                break

            self._checked_pairs.add(pair_key)
            is_conflict = await self._check_pair(event_a, event_b)

            if is_conflict:
                await self._handle_conflict(event_a, event_b)

    async def _check_pair(self, event_a: Event, event_b: Event) -> bool:
        """Use nano to check if two findings contradict each other."""
        try:
            response = await self.client.chat.completions.create(
                model=self.gate_model,
                max_tokens=10,
                temperature=0,
                messages=[{
                    "role": "user",
                    "content": (
                        "Do these two findings contradict each other? Answer only YES or NO.\n\n"
                        f"Finding A ({event_a.source_box}): {event_a.content[:300]}\n\n"
                        f"Finding B ({event_b.source_box}): {event_b.content[:300]}"
                    ),
                }],
            )

            # Record cost
            usage = response.usage
            await self.cost_tracker.record_usage(
                "system:conflict_detector",
                self.gate_model,
                {"prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens},
            )

            result = (response.choices[0].message.content or "").strip().upper()
            return result.startswith("YES")

        except Exception:
            logger.warning("Conflict check failed for pair")
            return False

    async def _handle_conflict(self, event_a: Event, event_b: Event):
        """Publish conflict event and debate prompts."""
        logger.info(
            "Conflict detected between %s and %s", event_a.source_box, event_b.source_box
        )

        # Publish conflict event (visible to all)
        conflict_event = Event(
            source_box="system:conflict_detector",
            event_type="conflict",
            content=(
                f"CONFLICT DETECTED between {event_a.source_box} and {event_b.source_box}:\n"
                f"  {event_a.source_box} says: {event_a.content[:200]}\n"
                f"  {event_b.source_box} says: {event_b.content[:200]}"
            ),
            metadata={
                "event_a_id": event_a.id,
                "event_b_id": event_b.id,
                "box_a": event_a.source_box,
                "box_b": event_b.source_box,
            },
        )
        await self.event_store.publish(conflict_event)

        # Publish debate prompt for box A
        debate_a = Event(
            source_box="system:debate",
            event_type="debate_prompt",
            content=(
                f"CONFLICT: Your finding '{event_a.content[:300]}' contradicts "
                f"{event_b.source_box}'s finding '{event_b.content[:300]}'. "
                f"Address this contradiction: either reconcile the findings, "
                f"explain why your position is correct and theirs is wrong, "
                f"or update your position. Label your response [RESOLUTION] or [REBUTTAL]."
            ),
            metadata={"target_box": event_a.source_box},
        )
        await self.event_store.publish(debate_a)

        # Publish debate prompt for box B
        debate_b = Event(
            source_box="system:debate",
            event_type="debate_prompt",
            content=(
                f"CONFLICT: Your finding '{event_b.content[:300]}' contradicts "
                f"{event_a.source_box}'s finding '{event_a.content[:300]}'. "
                f"Address this contradiction: either reconcile the findings, "
                f"explain why your position is correct and theirs is wrong, "
                f"or update your position. Label your response [RESOLUTION] or [REBUTTAL]."
            ),
            metadata={"target_box": event_b.source_box},
        )
        await self.event_store.publish(debate_b)
