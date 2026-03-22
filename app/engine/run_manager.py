"""Run manager — orchestrates a full multi-box reasoning run.

Creates Box 1 (o4-mini), Box 2 (gpt-4.1), and any requested specialist
boxes (gpt-4.1-mini), launches them as concurrent async tasks, monitors
completion, and manages the budget lifecycle.
"""

import asyncio
import logging
from datetime import datetime
from typing import Callable, Optional

from openai import AsyncOpenAI

from app.config import settings
from app.engine.box_runner import BoxRunner
from app.engine.cost_tracker import CostTracker
from app.engine.event_store import EventStore
from app.models import Event, RunConfig, RunState

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# System prompts
# ------------------------------------------------------------------

BOX1_SYSTEM = """\
You are the primary solver in a multi-agent reasoning system. You have been \
given a question and possibly supporting documents. Your job is to work \
through this problem systematically.

RULES:
- Think step by step. Show your reasoning.
- When you form a hypothesis, label it: [HYPOTHESIS] ...
- When you find evidence for/against something, label it: [EVIDENCE] ...
- When you hit a dead end, label it: [DEAD_END] ... (explain WHY it failed \
— this is valuable)
- When you make a connection between ideas, label it: [CONNECTION] ...
- When you reach a conclusion, label it: [CONCLUSION] ...
- When you have a question that could help, label it: [QUESTION] ...
- When you have exhausted all productive avenues, output: [DONE]

You are solving a problem that is considered conventionally impossible. Do \
not give up easily. Explore unconventional approaches. Challenge assumptions. \
If a standard approach fails, explain why and try something radically \
different.\
{conclude_instruction}"""

BOX2_SYSTEM = """\
You are the extrapolation engine in a multi-agent reasoning system. You \
observe the primary solver's work in real-time and your job is to take \
EVERY finding and run it to its logical conclusion.

For each new finding from the solver:
1. If it's a hypothesis — what would be true if this hypothesis holds? What \
would it imply for adjacent domains? What would disprove it?
2. If it's evidence — what else does this evidence support or undermine? What \
patterns does it connect to?
3. If it's a dead end — WHY did it fail? What does the failure itself tell \
us? What constraint does it reveal?
4. If it's a connection — extend it. What's the second-order connection? The \
third?

Label your outputs the same way: [HYPOTHESIS], [EVIDENCE], [CONNECTION], \
[CONCLUSION], [DEAD_END], [DONE].

You are looking for emergent insights — things the solver wouldn't see \
because it's focused on the problem. You see the bigger picture.\
{conclude_instruction}"""

SPECIALIST_SYSTEM = """\
You are a specialist analyst focused on: {specialist_name}
Domain description: {specialist_description}

You have access to ALL findings from the primary solver, the extrapolation \
engine, and all other specialists. Your job is to analyze everything through \
the lens of your specialty.

Pull ONLY information pertinent to your domain. Ignore irrelevant findings. \
When you find something relevant:
1. Explain its significance within your domain
2. Identify implications the other agents would miss
3. Cross-reference with findings from other specialists if relevant
4. Build toward a comprehensive domain-specific conclusion

Label your outputs: [HYPOTHESIS], [EVIDENCE], [CONNECTION], [CONCLUSION], \
[DEAD_END], [DONE].\
{conclude_instruction}"""


# ------------------------------------------------------------------
# Visibility filters
# ------------------------------------------------------------------

def _box1_filter(events: list[Event]) -> list[Event]:
    """Box 1 sees NOTHING from other boxes (only initial question / docs)."""
    return []


def _box2_filter(events: list[Event]) -> list[Event]:
    """Box 2 sees ONLY Box 1 events."""
    return [e for e in events if e.source_box == "box1"]


def _specialist_filter(events: list[Event]) -> list[Event]:
    """Specialists see ALL events from ALL boxes (except done signals)."""
    return [e for e in events if e.event_type != "done"]


# ------------------------------------------------------------------
# Run manager
# ------------------------------------------------------------------

class RunManager:
    """Orchestrates multi-box reasoning runs."""

    def __init__(self) -> None:
        self.active_runs: dict[str, RunState] = {}
        self._tasks: dict[str, list[asyncio.Task]] = {}
        self._boxes: dict[str, list[BoxRunner]] = {}
        self._event_stores: dict[str, EventStore] = {}
        self._cost_trackers: dict[str, CostTracker] = {}
        self._complete_callbacks: dict[str, list[Callable]] = {}
        self._status_callbacks: dict[str, list[Callable]] = {}

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_run(self, run_id: str) -> Optional[RunState]:
        return self.active_runs.get(run_id)

    def get_event_store(self, run_id: str) -> Optional[EventStore]:
        return self._event_stores.get(run_id)

    def get_cost_tracker(self, run_id: str) -> Optional[CostTracker]:
        return self._cost_trackers.get(run_id)

    def on_run_complete(self, run_id: str, callback: Callable) -> None:
        """Register a callback to be invoked when the run finishes."""
        if run_id not in self._complete_callbacks:
            self._complete_callbacks[run_id] = []
        self._complete_callbacks[run_id].append(callback)

    def on_status_update(self, run_id: str, callback: Callable) -> None:
        """Register a callback for box status changes (box_id, status, cycle)."""
        if run_id not in self._status_callbacks:
            self._status_callbacks[run_id] = []
        self._status_callbacks[run_id].append(callback)

    # ------------------------------------------------------------------
    # Start a run
    # ------------------------------------------------------------------

    async def start_run(
        self,
        config: RunConfig,
        ws_event_callback: Optional[Callable] = None,
        ws_status_callback: Optional[Callable] = None,
        ws_cost_callback: Optional[Callable] = None,
    ) -> RunState:
        """Create all boxes, wire up the event/cost plumbing, and launch.

        Parameters
        ----------
        config:
            The ``RunConfig`` describing the question, docs, specialists,
            budget cap, etc.
        ws_event_callback:
            ``async callback(event: Event)`` — forwarded to ``EventStore``.
        ws_status_callback:
            ``async callback(box_id, status, cycle)`` — box status changes.
        ws_cost_callback:
            ``async callback(snapshot: dict)`` — cost tracker updates.

        Returns
        -------
        RunState
            The newly created run state (status will be ``"running"``).
        """
        # -- Initialise run state --------------------------------------
        run_state = RunState(config=config, budget_cap=config.budget_cap)
        run_id = run_state.run_id

        event_store = EventStore()
        cost_tracker = CostTracker(config.budget_cap)

        self.active_runs[run_id] = run_state
        self._event_stores[run_id] = event_store
        self._cost_trackers[run_id] = cost_tracker
        self._tasks[run_id] = []
        self._boxes[run_id] = []

        # -- Wire WebSocket callbacks ----------------------------------
        if ws_event_callback:
            event_store.add_ws_callback(ws_event_callback)
        if ws_cost_callback:
            cost_tracker.on_update(ws_cost_callback)

        # -- OpenAI client ---------------------------------------------
        client = AsyncOpenAI(api_key=config.api_key) if config.api_key else AsyncOpenAI()

        # -- Build initial context for Box 1 ---------------------------
        initial_context = f"Question: {config.question}"
        if config.documents:
            initial_context += "\n\nSupporting Documents:\n" + "\n---\n".join(
                config.documents
            )

        # -- Status callback factory -----------------------------------
        async def status_callback(box_id: str, status: str, cycle: int) -> None:
            box_state = run_state.boxes.get(box_id)
            if box_state:
                box_state.status = status
                box_state.current_cycle = cycle
            if ws_status_callback:
                await ws_status_callback(box_id, status, cycle)
            # Also notify any externally-registered status callbacks.
            for cb in self._status_callbacks.get(run_id, []):
                try:
                    await cb(box_id, status, cycle)
                except Exception:
                    pass

        # -- Total box count for done-detection (FIX 3) -----------------
        total_boxes = 2 + len(config.specialists)

        # -- Create Box 1 (primary solver) -----------------------------
        box1 = BoxRunner(
            box_id="box1",
            model=settings.box1_model,
            system_prompt=BOX1_SYSTEM,
            event_store=event_store,
            cost_tracker=cost_tracker,
            client=client,
            visibility_filter=_box1_filter,
            max_completion_tokens=settings.box1_max_completion_tokens,
            status_callback=status_callback,
            max_cycles=config.max_cycles,
            total_boxes=total_boxes,
        )
        run_state.boxes["box1"] = box1.state

        # -- Create Box 2 (extrapolation engine) -----------------------
        box2 = BoxRunner(
            box_id="box2",
            model=settings.box2_model,
            system_prompt=BOX2_SYSTEM,
            event_store=event_store,
            cost_tracker=cost_tracker,
            client=client,
            visibility_filter=_box2_filter,
            max_completion_tokens=8192,
            status_callback=status_callback,
            max_cycles=config.max_cycles,
            total_boxes=total_boxes,
        )
        run_state.boxes["box2"] = box2.state

        # -- Create specialist boxes -----------------------------------
        specialists: list[BoxRunner] = []
        for spec_config in config.specialists:
            spec_id = f"specialist:{spec_config.name}"
            spec_prompt = (
                SPECIALIST_SYSTEM.replace("{specialist_name}", spec_config.name)
                .replace("{specialist_description}", spec_config.description)
            )
            spec = BoxRunner(
                box_id=spec_id,
                model=settings.specialist_model,
                system_prompt=spec_prompt,
                event_store=event_store,
                cost_tracker=cost_tracker,
                client=client,
                visibility_filter=_specialist_filter,
                max_completion_tokens=4096,
                status_callback=status_callback,
                specialist_domain=spec_config.description,
                gate_model=settings.gate_model,
                max_cycles=config.max_cycles,
                total_boxes=total_boxes,
            )
            run_state.boxes[spec_id] = spec.state
            specialists.append(spec)

        all_boxes = [box1, box2, *specialists]
        self._boxes[run_id] = all_boxes

        # -- Launch all boxes concurrently -----------------------------
        run_state.status = "running"

        task1 = asyncio.create_task(box1.run(initial_context), name=f"{run_id}:box1")
        self._tasks[run_id].append(task1)

        task2 = asyncio.create_task(box2.run(), name=f"{run_id}:box2")
        self._tasks[run_id].append(task2)

        for spec in specialists:
            task = asyncio.create_task(spec.run(), name=f"{run_id}:{spec.box_id}")
            self._tasks[run_id].append(task)

        # -- Background monitor ---------------------------------------
        asyncio.create_task(
            self._monitor_run(run_id), name=f"{run_id}:monitor"
        )

        logger.info(
            "Run %s started: %d boxes (%d specialists)",
            run_id,
            len(all_boxes),
            len(specialists),
        )
        return run_state

    # ------------------------------------------------------------------
    # Run monitoring
    # ------------------------------------------------------------------

    async def _monitor_run(self, run_id: str) -> None:
        """Wait for all box tasks to finish, then finalise the RunState."""
        tasks = self._tasks.get(run_id, [])
        if not tasks:
            return

        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            # Log any unexpected exceptions.
            for i, result in enumerate(results):
                if isinstance(result, Exception) and not isinstance(
                    result, asyncio.CancelledError
                ):
                    logger.error(
                        "Run %s task %d raised: %s", run_id, i, result
                    )
        except Exception:
            logger.exception("Monitor for run %s failed", run_id)

        # -- Finalise --------------------------------------------------
        run_state = self.active_runs.get(run_id)
        if run_state is None:
            return

        if run_state.status == "running":
            run_state.status = "completed"

        run_state.end_time = datetime.utcnow()

        event_store = self._event_stores.get(run_id)
        if event_store:
            run_state.events = event_store.get_all_events()

        cost_tracker = self._cost_trackers.get(run_id)
        if cost_tracker:
            run_state.total_cost = cost_tracker.total_cost

        logger.info(
            "Run %s completed — status=%s, cost=$%.4f, events=%d",
            run_id,
            run_state.status,
            run_state.total_cost,
            len(run_state.events),
        )

        # Notify any registered completion callbacks (e.g. WebSocket).
        for cb in self._complete_callbacks.get(run_id, []):
            try:
                await cb(run_state)
            except Exception:
                logger.exception("Run complete callback failed for %s", run_id)

    # ------------------------------------------------------------------
    # Stop a run
    # ------------------------------------------------------------------

    async def stop_run(self, run_id: str) -> bool:
        """Gracefully stop all boxes in a running run.

        Returns ``True`` if the run existed and was stopped, ``False``
        otherwise.
        """
        run_state = self.active_runs.get(run_id)
        if run_state is None:
            return False

        # Signal each box to cancel.
        for box in self._boxes.get(run_id, []):
            box.cancel()

        # Cancel all async tasks.
        for task in self._tasks.get(run_id, []):
            if not task.done():
                task.cancel()

        # Allow cancellation to propagate.
        await asyncio.sleep(0)

        run_state.status = "stopped"
        run_state.end_time = datetime.utcnow()

        event_store = self._event_stores.get(run_id)
        if event_store:
            run_state.events = event_store.get_all_events()

        cost_tracker = self._cost_trackers.get(run_id)
        if cost_tracker:
            run_state.total_cost = cost_tracker.total_cost

        logger.info("Run %s stopped by user — cost=$%.4f", run_id, run_state.total_cost)
        return True

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def cleanup_run(self, run_id: str) -> None:
        """Release resources associated with a completed/stopped run."""
        # Cancel any lingering tasks.
        for task in self._tasks.pop(run_id, []):
            if not task.done():
                task.cancel()

        event_store = self._event_stores.pop(run_id, None)
        if event_store:
            event_store.clear()

        self._cost_trackers.pop(run_id, None)
        self._boxes.pop(run_id, None)
        # Clean up callback registrations (FIX 13)
        self._complete_callbacks.pop(run_id, None)
        self._status_callbacks.pop(run_id, None)
        # Keep the RunState in active_runs for later querying;
        # the caller can remove it when no longer needed.
