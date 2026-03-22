"""Report generator — compiles per-box reports and the final cost receipt.

After a run completes (or is stopped), this module builds structured
report data suitable for both the API JSON response and Markdown
rendering in the frontend.
"""

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

    # Mode-aware box display names for the report
    _BOX_NAMES = {
        "solve":    {"box1": "Primary Solver", "box2": "Extrapolator"},
        "explore":  {"box1": "Explorer", "box2": "Cartographer"},
        "freeform": {"box1": "Analyst", "box2": "Meta-Analyst"},
    }

    if box_id in ("box1", "box2"):
        display_name = _BOX_NAMES.get(mode, _BOX_NAMES["solve"]).get(box_id, box_id)
    elif box_id.startswith("specialist:"):
        display_name = box_id.replace("specialist:", "")
    else:
        display_name = box_id

    # Check if this is an auto-spawned specialist
    all_events = events if events is not None else run_state.events
    is_spawned = any(
        e.event_type == "specialist_spawned"
        and e.metadata.get("spawned_name") in box_id
        for e in all_events
    )

    spawned_label = " (auto-spawned)" if is_spawned else ""

    # Collect non-done events emitted by this box.
    box_events: list[Event] = [
        e
        for e in run_state.events
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
        duration = (run_state.end_time - run_state.start_time).total_seconds()

    return {
        "run_id": run_state.run_id,
        "question": run_state.config.question[:200],
        "mode": run_state.config.mode,
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

    # Temporarily set run_state.events so generate_box_report can read them.
    original_events = run_state.events
    run_state.events = effective_events

    box_reports: list[dict] = []
    for box_id in run_state.boxes:
        report = generate_box_report(run_state, box_id, events=effective_events)
        if report:
            box_reports.append(report)

    # Restore original events to avoid side-effects on shared state.
    run_state.events = original_events

    receipt = generate_receipt(run_state, cost_tracker)
    conflicts_section = _build_conflicts_section(effective_events)

    return {
        "run_id": run_state.run_id,
        "question": run_state.config.question,
        "mode": run_state.config.mode,
        "status": run_state.status,
        "box_reports": box_reports,
        "conflicts": conflicts_section,
        "receipt": receipt,
        "event_log": [e.model_dump(mode="json") for e in effective_events],
    }
