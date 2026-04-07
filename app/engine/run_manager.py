"""Run manager — orchestrates a base-box-first reasoning run.

Creates Box 1 (o4-mini) as the required base case, optionally adds
Box 2 (gpt-4.1) as an amplification layer, and then any requested
specialist boxes (gpt-4.1-mini). Launches them as concurrent async tasks,
monitors completion, and manages the budget lifecycle.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from openai import AsyncOpenAI

from app.config import settings
from app.engine.box_runner import BoxRunner
from app.engine.conflict_detector import ConflictDetector
from app.engine.cost_tracker import CostTracker
from app.engine.event_store import EventStore
from app.engine.run_history import RunHistory
from app.models import Event, RunConfig, RunState

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# System prompts
# ------------------------------------------------------------------

# ------------------------------------------------------------------
# Shared label blocks used across modes
# ------------------------------------------------------------------

_SOLVE_LABELS = """\
Label your findings:
- [HYPOTHESIS] — A theory or potential answer you're testing
- [EVIDENCE] — Data or reasoning that supports or undermines something
- [CONCLUSION] — A firm conclusion you've reached
- [DEAD_END] — An approach that failed (explain WHY — this is valuable)
- [CONNECTION] — A link between two ideas or findings
- [QUESTION] — A question that could help if answered
- [DONE] — You've exhausted all productive avenues"""

_EXPLORE_LABELS = """\
Label your findings:
- [DISCOVERY] — Something you learned about the problem, domain, or constraints
- [CONSTRAINT] — A specific limitation or boundary that blocks progress
- [APPROACH] — A strategy you're attempting, with your reasoning
- [FAILURE_ANALYSIS] — An approach that didn't work and a detailed autopsy of WHY \
(these are among the most valuable outputs)
- [PARTIAL_SOLUTION] — Something that works for part of the problem but not all
- [ASSUMPTION] — A hidden assumption you've identified, whether or not you can break it
- [UNEXPECTED] — Something surprising you found that you weren't looking for
- [CONNECTION] — A link between two ideas, domains, or findings
- [BOUNDARY] — You've mapped the exact edge of what IS possible vs what ISN'T
- [DONE] — You've exhausted all productive avenues of exploration"""

_FREEFORM_LABELS = """\
Label your findings with ANY of these tags as appropriate:
- [HYPOTHESIS], [EVIDENCE], [CONCLUSION], [DEAD_END], [CONNECTION], [QUESTION]
- [DISCOVERY], [CONSTRAINT], [APPROACH], [FAILURE_ANALYSIS], [PARTIAL_SOLUTION]
- [ASSUMPTION], [UNEXPECTED], [BOUNDARY], [PATTERN], [FRONTIER]
- [DONE] — When you've exhausted all productive avenues"""

# ------------------------------------------------------------------
# Mode-keyed system prompts
# ------------------------------------------------------------------

_BOX1_USER_INPUT_BLOCK = """\

You are the REQUIRED base box. Your output must stand on its own even if no other boxes exist for this run.
You may receive [USER_INPUT] events from the human operator. Treat them as high-priority context — the human knows things you don't.
You have access to web search. Use it when you need current data, want to verify claims, or hit a knowledge gap. Search strategically — don't search for things you already know.
"""

BOX1_PROMPTS = {
    "solve": """\
You are the primary solver in a multi-agent reasoning system. You have been \
given a question and possibly supporting documents. Your job is to work \
through this problem systematically.

Think step by step. Show your reasoning. Do not give up easily. Explore \
unconventional approaches. Challenge assumptions. If a standard approach \
fails, explain why and try something radically different.

"""
    + _SOLVE_LABELS
    + _BOX1_USER_INPUT_BLOCK
    + "\n{conclude_instruction}",
    "explore": """\
You are the primary explorer in a multi-agent reasoning system. You have been \
given a problem that may be conventionally impossible to solve. THAT IS THE POINT. \
You are not expected to find a solution — you are expected to explore the problem \
space exhaustively and document everything you discover along the way.

Your mission is to LEARN, not to SOLVE.

APPROACH:
- Start by mapping the problem space. What are the known constraints? What makes this "impossible"?
- Try multiple approaches — conventional first, then increasingly unconventional.
- When an approach fails, DO NOT move on quickly. Linger on the failure. WHY did it fail? \
What does the failure reveal about the structure of the problem?
- Challenge every assumption. If the problem is "impossible," there are hidden assumptions \
making it so. Name them. Question them.
- Look for partial solutions. Can you solve 80%? 50%? What specifically blocks the rest?
- Look for adjacent discoveries — unexpected insights that aren't the answer but are \
valuable in their own right.

The richest output you can produce is a detailed [FAILURE_ANALYSIS]. When something fails, \
that failure is data. Treat it as such.

"""
    + _EXPLORE_LABELS
    + _BOX1_USER_INPUT_BLOCK
    + "\n{conclude_instruction}",
    "freeform": """\
You are the primary analyst in a multi-agent reasoning system. You have been \
given a question and possibly supporting documents. Approach it however you see fit — \
whether that means solving it directly, exploring the problem space, or something \
in between.

Use your judgment. If the problem seems solvable, solve it. If it seems impossible, \
explore it and document what you learn. If it's ambiguous, do both. Shift strategies \
as your understanding evolves.

Think step by step. Show your reasoning. Be thorough, creative, and persistent.

"""
    + _FREEFORM_LABELS
    + _BOX1_USER_INPUT_BLOCK
    + "\n{conclude_instruction}",
}

_BOX2_USER_INPUT_BLOCK = """\

Box 1 is the required base case for the run. You are an OPTIONAL amplification layer: extend it, pressure-test it, and surface second-order implications, but never replace its job.
You may receive [USER_INPUT] events from the human operator. Treat them as high-priority context.
If you identify a domain that is not covered by the current specialists and would benefit from dedicated analysis, you can request a new specialist by outputting: [SPAWN_SPECIALIST] Name: <name> | Domain: <description of what this specialist should focus on>. Be judicious — only spawn when a domain is clearly underserved and would meaningfully contribute.
"""

BOX2_PROMPTS = {
    "solve": """\
You are the extrapolation engine in a multi-agent reasoning system. You \
observe the primary solver's work in real-time and your job is to take \
EVERY finding and run it to its logical conclusion.

For each new finding from the solver:
1. If it's a hypothesis — what would be true if this hypothesis holds? What \
would it imply for adjacent domains? What would disprove it?
2. If it's evidence — what else does this evidence support or undermine?
3. If it's a dead end — WHY did it fail? What does the failure itself tell us?
4. If it's a connection — extend it. Second-order? Third?

You are looking for emergent insights — things the solver wouldn't see \
because it's focused on the problem. You see the bigger picture.

"""
    + _SOLVE_LABELS
    + _BOX2_USER_INPUT_BLOCK
    + "\n{conclude_instruction}",
    "explore": """\
You are the cartographer in a multi-agent reasoning system. You observe \
the primary explorer's work in real-time. The explorer is deliberately tackling \
problems that may be impossible. Your job is NOT to help solve the problem — \
it's to build a map of everything the exploration reveals.

Think of it this way: the explorer is hacking through a jungle. You're drawing \
the map from above — marking dead ends, terrain features, rivers that block \
progress, and unexpected clearings.

FOR EACH FINDING FROM THE EXPLORER:
1. [DISCOVERY] or [CONSTRAINT] — Add it to the map. What territory does it open or close?
2. [FAILURE_ANALYSIS] — This is gold. What does the failure reveal about the topology \
of the problem? Is it fundamentally impossible or just currently impossible?
3. [PARTIAL_SOLUTION] — Map what's solved vs unsolved. Where is the frontier?
4. [ASSUMPTION] — If this assumption were broken, what new territory opens up?

YOUR UNIQUE OUTPUTS:
- [PATTERN] — Patterns across multiple exploration attempts that the explorer is too close to see
- [FRONTIER] — The exact boundary between what CAN be done and what CAN'T
- [IMPOSSIBILITY_ANALYSIS] — Decompose WHY: logically impossible? physically? computationally? practically?

Also use: [DISCOVERY], [CONNECTION], [UNEXPECTED], [BOUNDARY], [DONE]
"""
    + _BOX2_USER_INPUT_BLOCK
    + "\n{conclude_instruction}",
    "freeform": """\
You are the meta-analyst in a multi-agent reasoning system. You observe \
the primary analyst's work in real-time and your job is to find what they miss.

Adapt to what you see. If they're solving, extrapolate their findings. If they're \
exploring, map the terrain. If they shift strategies, follow and document the shift itself.

Look for emergent insights, patterns across attempts, and second-order implications. \
You see the bigger picture.

"""
    + _FREEFORM_LABELS
    + _BOX2_USER_INPUT_BLOCK
    + "\n{conclude_instruction}",
}

_SPECIALIST_USER_INPUT_BLOCK = """\

You may receive [USER_INPUT] events from the human operator. Treat them as high-priority context.
"""

SPECIALIST_PROMPTS = {
    "solve": """\
You are a specialist analyst focused on: {specialist_name}
Domain description: {specialist_description}

Box 1 is the required base case for the run. You have access to all visible \
findings from the base box, any amplification layer, and all other specialists. \
Analyze everything through the lens of your specialty.

Pull ONLY information pertinent to your domain. When you find something relevant:
1. Explain its significance within your domain
2. Identify implications the other agents would miss
3. Cross-reference with other specialists if relevant
4. Build toward a comprehensive domain-specific conclusion

"""
    + _SOLVE_LABELS
    + _SPECIALIST_USER_INPUT_BLOCK
    + "\n{conclude_instruction}",
    "explore": """\
You are a specialist analyst focused on: {specialist_name}
Domain description: {specialist_description}

Box 1 is the required base case for the run. You have access to all visible \
findings from the base explorer, any mapping/amplification layer, and all other specialists. The system is exploring a problem that may be impossible. \
Your job is to analyze everything through the lens of your specialty.

Focus on what the exploration REVEALS within your domain, not on solving the problem. \
When you find something relevant:
1. What does this discovery or failure mean for {specialist_name}?
2. What domain-specific constraints or possibilities does it reveal?
3. What would a {specialist_name} expert notice that generalists would miss?
4. Build toward a domain-specific map of the explored territory.

"""
    + _EXPLORE_LABELS
    + _SPECIALIST_USER_INPUT_BLOCK
    + "\n{conclude_instruction}",
    "freeform": """\
You are a specialist analyst focused on: {specialist_name}
Domain description: {specialist_description}

Box 1 is the required base case for the run. You have access to all visible \
findings from the other active layers. Analyze everything through the lens of your specialty. Adapt to whatever mode the system is \
operating in — solving, exploring, or both.

Pull ONLY information pertinent to your domain. Build toward domain-specific insights.

"""
    + _FREEFORM_LABELS
    + _SPECIALIST_USER_INPUT_BLOCK
    + "\n{conclude_instruction}",
}


# ------------------------------------------------------------------
# Visibility filters
# ------------------------------------------------------------------

def _box1_filter(events: list[Event]) -> list[Event]:
    """Box 1 sees ONLY user_input events (and debate prompts targeted at it)."""
    return [e for e in events if e.source_box == "user"]


def _box2_filter(events: list[Event]) -> list[Event]:
    """Box 2 sees Box 1 events AND user events."""
    return [e for e in events if e.source_box in ("box1", "user")]


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
        self._detectors: dict[str, ConflictDetector] = {}
        self._monitor_tasks: dict[str, asyncio.Task] = {}
        self.run_history = RunHistory()

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

    def remove_complete_callback(self, run_id: str, callback: Callable) -> None:
        """Remove a previously-registered completion callback (no-op if absent)."""
        cbs = self._complete_callbacks.get(run_id)
        if cbs and callback in cbs:
            cbs.remove(callback)

    def remove_status_callback(self, run_id: str, callback: Callable) -> None:
        """Remove a previously-registered status callback (no-op if absent)."""
        cbs = self._status_callbacks.get(run_id)
        if cbs and callback in cbs:
            cbs.remove(callback)

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

        # -- Load seed context from prior runs -------------------------
        if config.seed_run_ids:
            seed_context = self.run_history.build_seed_context(config.seed_run_ids)
            if seed_context:
                initial_context = seed_context + "\n\n" + initial_context

        # -- Status callback factory -----------------------------------
        async def status_callback(box_id: str, status: str, cycle: int) -> None:
            box_state = run_state.boxes.get(box_id)
            if box_state:
                box_state.status = status
                box_state.current_cycle = cycle
            if ws_status_callback:
                await ws_status_callback(box_id, status, cycle)
            # Also notify any externally-registered status callbacks.
            # Snapshot the list to avoid RuntimeError if a callback
            # modifies the registration list during iteration.
            for cb in list(self._status_callbacks.get(run_id, [])):
                try:
                    await cb(box_id, status, cycle)
                except Exception:
                    pass

        # -- Total box count for done-detection (FIX 3) -----------------
        enable_box2 = config.enable_box2
        total_boxes = 1 + len(config.specialists) + (1 if enable_box2 else 0)

        # -- Resolve mode-aware prompts --------------------------------
        mode = config.mode or "solve"
        box1_system = BOX1_PROMPTS.get(mode, BOX1_PROMPTS["solve"])
        box2_system = BOX2_PROMPTS.get(mode, BOX2_PROMPTS["solve"])

        if not config.web_search_enabled:
            box1_system += "\n\nWeb search is disabled for this run. Work only from the provided context, prior seeded context, and your own reasoning."
        if not config.allow_spawning:
            box2_system += "\n\nDynamic specialist spawning is disabled for this run. Do not request new specialists."

        # -- Create Box 1 (primary solver) -----------------------------
        box1 = BoxRunner(
            box_id="box1",
            model=settings.box1_model,
            system_prompt=box1_system,
            event_store=event_store,
            cost_tracker=cost_tracker,
            client=client,
            visibility_filter=_box1_filter,
            max_completion_tokens=settings.box1_max_completion_tokens,
            status_callback=status_callback,
            max_cycles=config.max_cycles,
            total_boxes=total_boxes,
            mode=mode,
            tools_enabled=config.web_search_enabled,
        )
        run_state.boxes["box1"] = box1.state

        # -- Create Box 2 (optional amplification layer) ---------------
        box2: BoxRunner | None = None
        if enable_box2:
            box2 = BoxRunner(
                box_id="box2",
                model=settings.box2_model,
                system_prompt=box2_system,
                event_store=event_store,
                cost_tracker=cost_tracker,
                client=client,
                visibility_filter=_box2_filter,
                max_completion_tokens=8192,
                status_callback=status_callback,
                max_cycles=config.max_cycles,
                total_boxes=total_boxes,
                mode=mode,
            )
            run_state.boxes["box2"] = box2.state

        # -- Create specialist boxes -----------------------------------
        specialists: list[BoxRunner] = []
        for spec_config in config.specialists:
            spec_id = f"specialist:{spec_config.name}"
            spec_prompt = (
                SPECIALIST_PROMPTS.get(mode, SPECIALIST_PROMPTS["solve"])
                .replace("{specialist_name}", spec_config.name)
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
                mode=mode,
            )
            run_state.boxes[spec_id] = spec.state
            specialists.append(spec)

        all_boxes = [box1, *([box2] if box2 else []), *specialists]
        self._boxes[run_id] = all_boxes

        # -- Launch all boxes concurrently -----------------------------
        run_state.status = "running"

        task1 = asyncio.create_task(box1.run(initial_context), name=f"{run_id}:box1")
        self._tasks[run_id].append(task1)

        if box2:
            task2 = asyncio.create_task(box2.run(), name=f"{run_id}:box2")
            self._tasks[run_id].append(task2)

        for spec in specialists:
            task = asyncio.create_task(spec.run(), name=f"{run_id}:{spec.box_id}")
            self._tasks[run_id].append(task)

        # -- Conflict detector -----------------------------------------
        if config.conflict_detection and total_boxes > 1:
            detector = ConflictDetector(
                event_store=event_store,
                cost_tracker=cost_tracker,
                client=client,
                gate_model=settings.gate_model,
            )
            detector_task = asyncio.create_task(
                detector.run(), name=f"{run_id}:conflict_detector"
            )
            self._tasks[run_id].append(detector_task)
            self._detectors[run_id] = detector

        # -- Spawn monitor ---------------------------------------------
        if config.allow_spawning and enable_box2:
            spawn_task = asyncio.create_task(
                self._spawn_monitor(run_id), name=f"{run_id}:spawn_monitor"
            )
            self._tasks[run_id].append(spawn_task)

        # -- Seed context as prior_context event for Box 2 -------------
        if config.seed_run_ids:
            seed_context = self.run_history.build_seed_context(config.seed_run_ids)
            if seed_context:
                prior_event = Event(
                    source_box="system:history",
                    event_type="evidence",
                    content=seed_context,
                    metadata={"prior_context": True},
                )
                await event_store.publish(prior_event)

        # -- Background monitor ---------------------------------------
        # NOTE: The monitor task gathers self._tasks[run_id], so it must
        # NOT be added to that list (it would await itself -> deadlock).
        # Store it separately so stop_run / cleanup_run can cancel it.
        monitor_task = asyncio.create_task(
            self._monitor_run(run_id), name=f"{run_id}:monitor"
        )
        self._monitor_tasks[run_id] = monitor_task

        logger.info(
            "Run %s started: %d boxes (%d specialists, box2=%s)",
            run_id,
            len(all_boxes),
            len(specialists),
            enable_box2,
        )
        return run_state

    # ------------------------------------------------------------------
    # Run monitoring
    # ------------------------------------------------------------------

    async def _monitor_run(self, run_id: str) -> None:
        """Wait for all box tasks to finish, then finalise the RunState.

        Re-gathers in a loop because the spawn monitor can dynamically
        add new specialist tasks to ``self._tasks[run_id]`` after the
        initial ``gather`` has started.
        """
        try:
            while True:
                tasks = list(self._tasks.get(run_id, []))
                if not tasks:
                    break

                results = await asyncio.gather(*tasks, return_exceptions=True)
                # Log any unexpected exceptions.
                for i, result in enumerate(results):
                    if isinstance(result, Exception) and not isinstance(
                        result, asyncio.CancelledError
                    ):
                        logger.error(
                            "Run %s task %d raised: %s", run_id, i, result
                        )

                # Check whether new tasks were appended while we were waiting
                # (e.g. dynamically-spawned specialists).
                current_tasks = self._tasks.get(run_id, [])
                pending = [t for t in current_tasks if not t.done()]
                if not pending:
                    break
        except Exception:
            logger.exception("Monitor for run %s failed", run_id)

        # -- Finalise --------------------------------------------------
        run_state = self.active_runs.get(run_id)
        if run_state is None:
            return

        if run_state.status == "running":
            run_state.status = "completed"

        run_state.end_time = datetime.now(timezone.utc)

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

        # Save to run history (guard against cost_tracker being None
        # if the tracker was removed before the monitor finalised).
        if run_state.status == "completed" and cost_tracker is not None:
            try:
                self.run_history.save_run(run_state, cost_tracker, run_state.events)
            except Exception:
                logger.exception("Failed to save run history for %s", run_id)

        # Notify any registered completion callbacks (e.g. WebSocket).
        # Snapshot the list to avoid RuntimeError if a callback modifies it.
        for cb in list(self._complete_callbacks.get(run_id, [])):
            try:
                await cb(run_state)
            except Exception:
                logger.exception("Run complete callback failed for %s", run_id)

    # ------------------------------------------------------------------
    # Spawn monitor
    # ------------------------------------------------------------------

    async def _spawn_monitor(self, run_id: str) -> None:
        """Watch for spawn_specialist events and create new boxes."""
        run_state = self.active_runs.get(run_id)
        event_store = self._event_stores.get(run_id)
        cost_tracker = self._cost_trackers.get(run_id)
        if not run_state or not event_store or not cost_tracker:
            return

        config = run_state.config
        if not config.allow_spawning:
            return

        queue = await event_store.subscribe("spawn_monitor")
        client = AsyncOpenAI(api_key=config.api_key) if config.api_key else AsyncOpenAI()

        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    # Check if run is done
                    if run_state.status != "running":
                        break
                    continue

                if event.event_type != "spawn_specialist":
                    continue

                spawn_name = event.metadata.get("spawn_name")
                spawn_domain = event.metadata.get("spawn_domain")
                if not spawn_name or not spawn_domain:
                    continue

                spec_id = f"specialist:{spawn_name}"

                # Check if already exists
                if spec_id in run_state.boxes:
                    continue

                # Check box count limit
                if len(run_state.boxes) >= config.max_total_boxes:
                    continue

                # Check budget
                if cost_tracker and cost_tracker.should_conclude():
                    continue

                # Create new specialist
                mode = config.mode or "solve"
                spec_prompt = (
                    SPECIALIST_PROMPTS.get(mode, SPECIALIST_PROMPTS["solve"])
                    .replace("{specialist_name}", spawn_name)
                    .replace("{specialist_description}", spawn_domain)
                )

                total_boxes = len(run_state.boxes) + 1

                # Get status callback (reuse the existing one)
                status_cb = None
                existing_boxes = self._boxes.get(run_id, [])
                if existing_boxes:
                    status_cb = existing_boxes[0].status_callback

                spec = BoxRunner(
                    box_id=spec_id,
                    model=settings.specialist_model,
                    system_prompt=spec_prompt,
                    event_store=event_store,
                    cost_tracker=cost_tracker,
                    client=client,
                    visibility_filter=_specialist_filter,
                    max_completion_tokens=4096,
                    status_callback=status_cb,
                    specialist_domain=spawn_domain,
                    gate_model=settings.gate_model,
                    max_cycles=config.max_cycles,
                    total_boxes=total_boxes,
                    mode=mode,
                )

                run_state.boxes[spec_id] = spec.state
                self._boxes[run_id].append(spec)

                task = asyncio.create_task(spec.run(), name=f"{run_id}:{spec_id}")
                self._tasks[run_id].append(task)

                # Publish spawned event
                spawned_event = Event(
                    source_box="system:spawn",
                    event_type="specialist_spawned",
                    content=f'New specialist "{spawn_name}" has joined the analysis.',
                    metadata={
                        "spawned_name": spawn_name,
                        "spawned_domain": spawn_domain,
                    },
                )
                await event_store.publish(spawned_event)

                # Broadcast box_spawned for WS
                for cb in list(self._status_callbacks.get(run_id, [])):
                    try:
                        await cb(spec_id, "waiting", 0)
                    except Exception:
                        pass

                logger.info(
                    "Spawned specialist '%s' for run %s", spawn_name, run_id
                )

        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Spawn monitor error for run %s", run_id)
        finally:
            event_store.unsubscribe("spawn_monitor")

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

        # Cancel conflict detector if running.
        detector = self._detectors.get(run_id)
        if detector:
            detector.cancel()

        # Cancel all async tasks.
        for task in self._tasks.get(run_id, []):
            if not task.done():
                task.cancel()

        # Cancel the monitor task (stored separately to avoid self-gather deadlock).
        monitor_task = self._monitor_tasks.get(run_id)
        if monitor_task and not monitor_task.done():
            monitor_task.cancel()

        # Allow cancellation to propagate.
        await asyncio.sleep(0)

        run_state.status = "stopped"
        run_state.end_time = datetime.now(timezone.utc)

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

        # Cancel the monitor task (stored separately).
        monitor_task = self._monitor_tasks.pop(run_id, None)
        if monitor_task and not monitor_task.done():
            monitor_task.cancel()

        event_store = self._event_stores.pop(run_id, None)
        if event_store:
            await event_store.clear()

        self._cost_trackers.pop(run_id, None)
        self._boxes.pop(run_id, None)
        self._detectors.pop(run_id, None)
        # Clean up callback registrations (FIX 13)
        self._complete_callbacks.pop(run_id, None)
        self._status_callbacks.pop(run_id, None)
        # Keep the RunState in active_runs for later querying;
        # the caller can remove it when no longer needed.
