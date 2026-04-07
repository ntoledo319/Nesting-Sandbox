"""Report generator — compiles per-box reports and the final cost receipt.

After a run completes (or is stopped), this module builds structured
report data suitable for both the API JSON response and Markdown
rendering in the frontend.
"""

from datetime import timezone
from collections import Counter

from app.engine.cost_tracker import CostTracker
from app.models import Event, RunState

# ------------------------------------------------------------------
# Per-box report
# ------------------------------------------------------------------

_TYPE_LABELS: dict[str, str] = {
    # Core solve
    "hypothesis": "Hypotheses",
    "evidence": "Evidence",
    "conclusion": "Conclusions",
    "dead_end": "Dead Ends",
    "connection": "Connections",
    "question": "Open Questions",
    # Explore
    "discovery": "Discoveries",
    "constraint": "Constraints",
    "approach": "Approaches",
    "failure_analysis": "Failure Analyses",
    "partial_solution": "Partial Solutions",
    "assumption": "Assumptions Challenged",
    "unexpected": "Unexpected Findings",
    "boundary": "Boundaries Mapped",
    "pattern": "Patterns Found",
    "frontier": "Frontiers Identified",
    "impossibility_analysis": "Impossibility Analyses",
    "territory_map": "Territory Maps",
    "emergence": "Emergent Properties",
    # Conflict/debate
    "conflict": "Conflicts Detected",
    "debate_prompt": "Debate Prompts",
    "resolution": "Conflict Resolutions",
    "rebuttal": "Rebuttals",
    # Dynamic spawning
    "spawn_specialist": "Specialist Spawn Requests",
    "specialist_spawned": "Specialists Spawned",
    # User input
    "user_input": "User Injections",
}

_BOX_NAMES = {
    "solve": {"box1": "Base Box — Primary Solver", "box2": "Amplifier — Extrapolator"},
    "explore": {"box1": "Base Box — Explorer", "box2": "Amplifier — Cartographer"},
    "freeform": {"box1": "Base Box — Analyst", "box2": "Amplifier — Meta-Analyst"},
}

_SUMMARY_PRIORITIES: dict[str, list[str]] = {
    "solve": [
        "conclusion",
        "evidence",
        "hypothesis",
        "resolution",
        "connection",
        "question",
        "dead_end",
    ],
    "explore": [
        "frontier",
        "boundary",
        "discovery",
        "partial_solution",
        "failure_analysis",
        "constraint",
        "pattern",
        "impossibility_analysis",
    ],
    "freeform": [
        "conclusion",
        "frontier",
        "discovery",
        "partial_solution",
        "evidence",
        "pattern",
        "connection",
        "question",
    ],
}

_AMPLIFIER_PRIORITY_SUFFIX = [
    "resolution",
    "pattern",
    "conflict",
    "rebuttal",
    "specialist_spawned",
    "spawn_specialist",
]


def get_box_display_name(box_id: str, mode: str) -> str:
    """Mode-aware display name for a logical box."""
    if box_id in ("box1", "box2"):
        return _BOX_NAMES.get(mode, _BOX_NAMES["solve"]).get(box_id, box_id)
    if box_id.startswith("specialist:"):
        return box_id.replace("specialist:", "")
    if box_id == "user":
        return "User"
    if box_id.startswith("system:"):
        return box_id.replace("system:", "").replace("_", " ").title()
    return box_id


def _pick_summary_events(
    events: list[Event],
    priority_order: list[str],
    limit: int,
) -> list[Event]:
    """Select a small number of substantive events in priority order."""
    priority_index = {etype: idx for idx, etype in enumerate(priority_order)}
    ranked = [
        event for event in events
        if event.event_type in priority_index and event.event_type != "done"
    ]
    ranked.sort(
        key=lambda event: (
            priority_index.get(event.event_type, len(priority_order)),
            event.timestamp,
        )
    )

    chosen: list[Event] = []
    seen: set[tuple[str, str]] = set()
    for event in ranked:
        key = (event.source_box, event.content.strip())
        if key in seen:
            continue
        seen.add(key)
        chosen.append(event)
        if len(chosen) >= limit:
            break

    if chosen:
        return chosen

    fallback = [event for event in events if event.event_type != "done"]
    return fallback[:limit]


def _stack_profile(run_state: RunState) -> dict:
    """Describe which optional layers were active on top of Box 1."""
    specialist_count = sum(
        1 for box_id in run_state.boxes if box_id.startswith("specialist:")
    )
    enable_box2 = "box2" in run_state.boxes or run_state.config.enable_box2

    if enable_box2 and specialist_count:
        key = "fully_layered"
        label = "Base box + extrapolator + specialists"
    elif enable_box2:
        key = "base_plus_extrapolator"
        label = "Base box + extrapolator"
    elif specialist_count:
        key = "base_plus_specialists"
        label = f"Base box + {specialist_count} specialist{'s' if specialist_count != 1 else ''}"
    else:
        key = "base_only"
        label = "Base box only"

    components = ["Box 1"]
    if enable_box2:
        components.append("Box 2")
    if specialist_count:
        components.append(f"{specialist_count} specialist{'s' if specialist_count != 1 else ''}")
    if run_state.config.web_search_enabled:
        components.append("web search")
    if run_state.config.conflict_detection and len(run_state.boxes) > 1:
        components.append("conflict detection")
    if run_state.config.allow_spawning and enable_box2:
        components.append("dynamic spawning")

    return {
        "key": key,
        "label": label,
        "components": components,
        "specialist_count": specialist_count,
        "box2_enabled": enable_box2,
    }


def _source_footprint(
    run_state: RunState,
    events: list[Event],
    conflicts_section: dict | None,
) -> dict:
    """Summarize the evidence and context sources used by a run."""
    event_types = Counter(event.event_type for event in events)
    web_search_events = sum(
        1 for event in events if event.metadata.get("source") == "web_search"
    )

    return {
        "documents": len(run_state.config.documents),
        "seed_runs": len(run_state.config.seed_run_ids),
        "user_inputs": event_types.get("user_input", 0),
        "web_search_events": web_search_events,
        "conflicts": conflicts_section["total_conflicts"] if conflicts_section else 0,
        "specialist_events": sum(
            1 for event in events if event.source_box.startswith("specialist:")
        ),
    }


def generate_run_summary(
    run_state: RunState,
    events: list[Event],
    conflicts_section: dict | None = None,
) -> dict:
    """Generate a base-box-first summary for the overall run."""
    mode = run_state.config.mode or "solve"
    priority = _SUMMARY_PRIORITIES.get(mode, _SUMMARY_PRIORITIES["solve"])
    stack_profile = _stack_profile(run_state)

    base_events = [
        event for event in events
        if event.source_box == "box1" and event.event_type != "done"
    ]
    amplifier_events = [
        event for event in events
        if event.source_box not in ("box1", "user", "system:history")
        and event.event_type != "done"
    ]

    base_takeaways = _pick_summary_events(base_events, priority, limit=3)
    amplifier_takeaways = _pick_summary_events(
        amplifier_events,
        [*priority, *_AMPLIFIER_PRIORITY_SUFFIX],
        limit=3,
    )

    primary_event = base_takeaways[0] if base_takeaways else None
    if primary_event:
        primary_outcome = primary_event.content.strip()[:700]
        if primary_event.event_type in {"conclusion", "frontier", "boundary"}:
            base_box_status = "Box 1 produced a decisive top-line outcome."
        else:
            base_box_status = "Box 1 produced the strongest available base-case answer, but it remains exploratory."
    else:
        primary_outcome = "Box 1 did not reach a decisive top-line outcome."
        base_box_status = "Box 1 exhausted the run without a decisive conclusion."

    if stack_profile["key"] == "base_only":
        amplification_note = "No amplification layers were active. This run relied entirely on Box 1."
    elif amplifier_takeaways:
        amplification_note = "Optional layers extended or pressure-tested the base box rather than replacing it."
    else:
        amplification_note = "Optional layers were enabled, but Box 1 remained the main source of substantive findings."

    return {
        "primary_outcome": primary_outcome,
        "primary_event_type": primary_event.event_type if primary_event else None,
        "base_box_status": base_box_status,
        "stack_profile": stack_profile,
        "base_box_takeaways": [
            {
                "type": event.event_type,
                "label": _TYPE_LABELS.get(event.event_type, event.event_type.title()),
                "content": event.content,
            }
            for event in base_takeaways
        ],
        "amplifier_takeaways": [
            {
                "source_box": event.source_box,
                "source_label": get_box_display_name(event.source_box, mode),
                "type": event.event_type,
                "label": _TYPE_LABELS.get(event.event_type, event.event_type.title()),
                "content": event.content,
            }
            for event in amplifier_takeaways
        ],
        "amplification_note": amplification_note,
        "source_footprint": _source_footprint(run_state, events, conflicts_section),
    }


def generate_box_report(
    run_state: RunState,
    box_id: str,
    events: list[Event] | None = None,
) -> dict:
    """Generate a structured report for a single box."""
    box = run_state.boxes.get(box_id)
    if not box:
        return {}

    mode = run_state.config.mode or "solve"
    display_name = get_box_display_name(box_id, mode)

    # Check if this is an auto-spawned specialist
    all_events = events if events is not None else run_state.events
    is_spawned = any(
        e.event_type == "specialist_spawned"
        and e.metadata.get("spawned_name") in box_id
        for e in all_events
    )

    spawned_label = " (auto-spawned)" if is_spawned else ""

    # Collect non-done events emitted by this box.
    # Use the explicitly-passed events list when available to avoid
    # depending on (possibly stale/empty) run_state.events.
    source_events = events if events is not None else run_state.events
    box_events: list[Event] = [
        e
        for e in source_events
        if e.source_box == box_id and e.event_type != "done"
    ]

    # Categorise by event type, noting web search sources.
    categories: dict[str, list[str]] = {}
    for e in box_events:
        note = ""
        if e.metadata.get("source") == "web_search":
            note = " *(via web search)*"
        categories.setdefault(e.event_type, []).append(e.content + note)

    # Build a human-readable Markdown report.
    report_lines: list[str] = [f"# {display_name}{spawned_label} Report\n"]

    for etype, label in _TYPE_LABELS.items():
        items = categories.get(etype, [])
        if items:
            report_lines.append(f"\n## {label} ({len(items)})\n")
            for i, item in enumerate(items, 1):
                report_lines.append(f"{i}. {item}\n")

    return {
        "box_id": box_id,
        "display_name": display_name,
        "status": box.status,
        "cycles": box.current_cycle,
        "cost": round(box.total_cost, 4),
        "input_tokens": box.total_input_tokens,
        "output_tokens": box.total_output_tokens,
        "reasoning_tokens": box.total_reasoning_tokens,
        "finding_counts": {k: len(v) for k, v in categories.items()},
        "report_markdown": "\n".join(report_lines),
    }


# ------------------------------------------------------------------
# Cost receipt
# ------------------------------------------------------------------

def generate_receipt(run_state: RunState, cost_tracker: CostTracker) -> dict:
    """Generate the final cost receipt for a completed run."""
    duration = None
    if run_state.end_time is not None:
        # Normalise both to aware UTC so naive vs aware mismatch can't crash
        start = run_state.start_time
        end = run_state.end_time
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        duration = (end - start).total_seconds()

    return {
        "run_id": run_state.run_id,
        "question": run_state.config.question[:200],
        "mode": run_state.config.mode,
        "stack_profile": _stack_profile(run_state),
        "status": run_state.status,
        "total_cost": round(cost_tracker.total_cost, 4),
        "budget_cap": cost_tracker.budget_cap,
        "total_tokens": {
            "input": sum(
                bc.input_tokens for bc in cost_tracker.box_costs.values()
            ),
            "output": sum(
                bc.output_tokens for bc in cost_tracker.box_costs.values()
            ),
            "reasoning": sum(
                bc.reasoning_tokens for bc in cost_tracker.box_costs.values()
            ),
        },
        "cycles_completed": sum(bc.cycles for bc in cost_tracker.box_costs.values()),
        "cache_hit_rate": cost_tracker.calculate_cache_rate(),
        "per_box_breakdown": [
            {
                "box_id": bc.box_id,
                "input_tokens": bc.input_tokens,
                "output_tokens": bc.output_tokens,
                "reasoning_tokens": bc.reasoning_tokens,
                "cached_tokens": bc.cached_tokens,
                "cost": round(bc.total_cost, 4),
                "cycles": bc.cycles,
            }
            for bc in cost_tracker.box_costs.values()
        ],
        "duration_seconds": round(duration, 2) if duration is not None else None,
    }


# ------------------------------------------------------------------
# Conflicts & resolutions
# ------------------------------------------------------------------

def _build_conflicts_section(events: list[Event]) -> dict | None:
    """Build a conflicts & resolutions section."""
    conflicts = [e for e in events if e.event_type == "conflict"]
    resolutions = [e for e in events if e.event_type == "resolution"]
    rebuttals = [e for e in events if e.event_type == "rebuttal"]

    if not conflicts:
        return None

    items = []
    for conflict in conflicts:
        box_a = conflict.metadata.get("box_a", "unknown")
        box_b = conflict.metadata.get("box_b", "unknown")

        # Find related resolutions/rebuttals (from either involved box)
        related_resolutions = [
            r for r in resolutions
            if r.source_box in (box_a, box_b)
        ]
        related_rebuttals = [
            r for r in rebuttals
            if r.source_box in (box_a, box_b)
        ]

        items.append({
            "conflict": conflict.content,
            "between": [box_a, box_b],
            "resolutions": [r.content for r in related_resolutions],
            "rebuttals": [r.content for r in related_rebuttals],
            "resolved": len(related_resolutions) > 0,
        })

    return {
        "total_conflicts": len(conflicts),
        "resolved": sum(1 for i in items if i["resolved"]),
        "items": items,
    }


# ------------------------------------------------------------------
# Full report
# ------------------------------------------------------------------

def generate_full_report(
    run_state: RunState,
    cost_tracker: CostTracker,
    events: list[Event] | None = None,
) -> dict:
    """Generate the complete report for a run.

    Combines per-box reports, the cost receipt, and the raw event log
    into a single JSON-serialisable dict.

    Parameters
    ----------
    events:
        Optional override for the event list.  When supplied the report
        uses these events instead of ``run_state.events``, which avoids
        mutating shared state for in-progress runs.
    """
    # Use the explicit events list when provided, falling back to run_state.
    effective_events = events if events is not None else run_state.events

    # Pass effective_events explicitly — no longer mutates run_state.events.
    box_reports: list[dict] = []
    for box_id in run_state.boxes:
        report = generate_box_report(run_state, box_id, events=effective_events)
        if report:
            box_reports.append(report)

    receipt = generate_receipt(run_state, cost_tracker)
    conflicts_section = _build_conflicts_section(effective_events)
    summary = generate_run_summary(run_state, effective_events, conflicts_section)

    return {
        "run_id": run_state.run_id,
        "question": run_state.config.question,
        "mode": run_state.config.mode,
        "status": run_state.status,
        "summary": summary,
        "box_reports": box_reports,
        "conflicts": conflicts_section,
        "receipt": receipt,
        "event_log": [e.model_dump(mode="json") for e in effective_events],
    }
