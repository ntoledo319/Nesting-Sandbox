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
    "hypothesis": "Hypotheses",
    "evidence": "Evidence",
    "conclusion": "Conclusions",
    "dead_end": "Dead Ends",
    "connection": "Connections",
    "question": "Open Questions",
}


def generate_box_report(run_state: RunState, box_id: str) -> dict:
    """Generate a structured report for a single box.

    Returns an empty dict if *box_id* is not found in the run.
    """
    box = run_state.boxes.get(box_id)
    if not box:
        return {}

    # Collect non-done events emitted by this box.
    events: list[Event] = [
        e
        for e in run_state.events
        if e.source_box == box_id and e.event_type != "done"
    ]

    # Categorise by event type.
    categories: dict[str, list[str]] = {}
    for e in events:
        categories.setdefault(e.event_type, []).append(e.content)

    # Build a human-readable Markdown report.
    report_lines: list[str] = [f"# {box_id.upper()} Report\n"]

    for etype, label in _TYPE_LABELS.items():
        items = categories.get(etype, [])
        if items:
            report_lines.append(f"\n## {label} ({len(items)})\n")
            for i, item in enumerate(items, 1):
                report_lines.append(f"{i}. {item}\n")

    return {
        "box_id": box_id,
        "status": box.status,
        "cycles": box.current_cycle,
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
        report = generate_box_report(run_state, box_id)
        if report:
            box_reports.append(report)

    # Restore original events to avoid side-effects on shared state.
    run_state.events = original_events

    receipt = generate_receipt(run_state, cost_tracker)

    return {
        "run_id": run_state.run_id,
        "question": run_state.config.question,
        "status": run_state.status,
        "box_reports": box_reports,
        "receipt": receipt,
        "event_log": [e.model_dump(mode="json") for e in effective_events],
    }
