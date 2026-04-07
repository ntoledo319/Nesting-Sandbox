"""Cross-run memory — persists completed run summaries to disk."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from app.models import RunState, Event
from app.engine.cost_tracker import CostTracker
from app.engine.report_generator import generate_run_summary, get_box_display_name

logger = logging.getLogger(__name__)

DATA_DIR = Path("data/runs")


class RunHistory:
    """Manages persistent run history for cross-run memory."""

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def save_run(self, run_state: RunState, cost_tracker: CostTracker, events: list[Event]) -> None:
        """Save a completed run summary to disk."""
        try:
            key_findings = self._extract_key_findings(events)
            summary = generate_run_summary(run_state, events)
            mode = run_state.config.mode or "solve"

            # Build box report summaries
            box_reports = []
            for box_id, box_state in run_state.boxes.items():
                box_events = [e for e in events if e.source_box == box_id and e.event_type != "done"]
                report_lines = []
                for e in box_events:
                    report_lines.append(f"[{e.event_type.upper()}] {e.content}")

                box_reports.append({
                    "box_id": box_id,
                    "display_name": get_box_display_name(box_id, mode),
                    "report_markdown": "\n\n".join(report_lines) if report_lines else "No findings.",
                })

            data = {
                "run_id": run_state.run_id,
                "question": run_state.config.question,
                "mode": run_state.config.mode,
                "completed_at": datetime.now(timezone.utc).isoformat() + "Z",
                "total_cost": round(cost_tracker.total_cost, 4) if cost_tracker else 0,
                "specialists": [s.name for s in run_state.config.specialists],
                "summary": {
                    "primary_outcome": summary["primary_outcome"],
                    "base_box_status": summary["base_box_status"],
                    "stack_profile": summary["stack_profile"],
                    "base_box_takeaways": summary["base_box_takeaways"],
                    "amplifier_takeaways": summary["amplifier_takeaways"],
                    "source_footprint": summary["source_footprint"],
                    "box_reports": box_reports,
                },
                "key_findings": key_findings,
            }

            filepath = self.data_dir / f"{run_state.run_id}.json"
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2, default=str)

            logger.info("Saved run history: %s", run_state.run_id)
        except Exception:
            logger.exception("Failed to save run history for %s", run_state.run_id)

    def _extract_key_findings(self, events: list[Event], max_findings: int = 20) -> list[dict]:
        """Extract top findings from events, prioritized by type."""
        priority_order = [
            "conclusion", "discovery", "resolution",
            "frontier", "boundary", "pattern", "emergence",
            "failure_analysis", "impossibility_analysis",
            "hypothesis", "evidence", "connection",
            "approach", "constraint", "partial_solution",
            "rebuttal", "conflict",
        ]

        # Filter to substantive events only
        substantive = [e for e in events if e.event_type in priority_order]

        # Sort by priority and favor Box 1 when event types tie.
        def sort_key(event):
            try:
                priority = priority_order.index(event.event_type)
            except ValueError:
                priority = len(priority_order)
            base_penalty = 0 if event.source_box == "box1" else 1
            return (priority, base_penalty)

        substantive.sort(key=sort_key)

        findings = []
        for e in substantive[:max_findings]:
            findings.append({
                "type": e.event_type,
                "content": e.content[:500],
                "source": e.source_box,
            })
        return findings

    def list_runs(self) -> list[dict]:
        """List all saved runs (summary info only)."""
        runs = []
        for filepath in sorted(self.data_dir.glob("*.json"), reverse=True):
            try:
                with open(filepath) as f:
                    data = json.load(f)
                runs.append({
                    "run_id": data["run_id"],
                    "question": data["question"][:200],
                    "mode": data.get("mode", "solve"),
                    "completed_at": data.get("completed_at", ""),
                    "total_cost": data.get("total_cost", 0),
                    "specialists": data.get("specialists", []),
                    "primary_outcome": data.get("summary", {}).get("primary_outcome", ""),
                    "stack_profile": data.get("summary", {}).get("stack_profile", {}),
                })
            except Exception:
                logger.warning("Failed to read run history: %s", filepath)
        return runs

    def get_run(self, run_id: str) -> Optional[dict]:
        """Get full saved run data."""
        filepath = self.data_dir / f"{run_id}.json"
        if not filepath.exists():
            return None
        try:
            with open(filepath) as f:
                return json.load(f)
        except Exception:
            logger.warning("Failed to read run: %s", run_id)
            return None

    def delete_run(self, run_id: str) -> bool:
        """Delete a saved run."""
        filepath = self.data_dir / f"{run_id}.json"
        if filepath.exists():
            filepath.unlink()
            return True
        return False

    def build_seed_context(self, run_ids: list[str]) -> str:
        """Build seed context from prior runs for Box 1."""
        if not run_ids:
            return ""

        sections = []
        for run_id in run_ids:
            run_data = self.get_run(run_id)
            if not run_data:
                continue

            lines = [
                f"Run: {run_data['question'][:300]}",
                f"Primary outcome: {run_data.get('summary', {}).get('primary_outcome', 'No primary outcome recorded.')[:300]}",
                f"Key findings:",
            ]
            for i, finding in enumerate(run_data.get("key_findings", []), 1):
                lines.append(f"  {i}. [{finding['type'].upper()}] ({finding['source']}) {finding['content'][:300]}")

            sections.append("\n".join(lines))

        if not sections:
            return ""

        return (
            "=== PRIOR EXPLORATION (from previous runs) ===\n\n"
            + "\n\n---\n\n".join(sections)
            + "\n\n=== END PRIOR EXPLORATION ==="
        )
