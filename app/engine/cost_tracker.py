"""Live cost tracking with budget enforcement.

Tracks per-box token usage, computes dollar costs based on model
pricing, and signals the orchestrator when the budget threshold is
approaching (80 %) or breached (95 %).
"""

import asyncio
from datetime import datetime
from typing import Callable

from app.models import BoxCost

# Prices are **per 1 M tokens** (USD) — sourced from the OpenAI pricing
# page as of 2025-04.
MODEL_PRICING: dict[str, dict[str, float]] = {
    "o4-mini": {"input": 1.10, "output": 4.40, "cached_input": 0.275},
    "gpt-4.1": {"input": 2.00, "output": 8.00, "cached_input": 0.50},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60, "cached_input": 0.10},
    "gpt-4.1-nano": {"input": 0.10, "output": 0.40, "cached_input": 0.025},
}

# Budget thresholds
_CONCLUDE_THRESHOLD = 0.80  # Signal boxes to wrap up
_STOP_THRESHOLD = 0.95       # Hard stop


class CostTracker:
    """Accumulates token-level costs per box and enforces a run budget."""

    def __init__(self, budget_cap: float) -> None:
        self.budget_cap: float = budget_cap
        self.box_costs: dict[str, BoxCost] = {}
        self.total_cost: float = 0.0
        self.start_time: datetime = datetime.utcnow()
        self._callbacks: list[Callable[[dict], object]] = []
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def on_update(self, callback: Callable[[dict], object]) -> None:
        """Register *callback* to be invoked with a snapshot after every cost update."""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable) -> None:
        """Remove a previously-registered update callback (no-op if absent — FIX 12)."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    async def record_usage(self, box_id: str, model: str, usage: dict) -> None:
        """Record token usage from an OpenAI API response.

        Parameters
        ----------
        box_id:
            Logical box identifier (``"box1"``, ``"specialist:Legal"`` etc.).
        model:
            Model name key into ``MODEL_PRICING``.
        usage:
            The ``usage`` dict returned by the OpenAI API (``prompt_tokens``,
            ``completion_tokens``, optional ``prompt_tokens_details``).
        """
        async with self._lock:
            pricing = MODEL_PRICING.get(model, MODEL_PRICING["gpt-4.1-mini"])

            prompt_tokens: int = usage.get("prompt_tokens", 0)
            completion_tokens: int = usage.get("completion_tokens", 0)

            cached: int = 0
            prompt_details = usage.get("prompt_tokens_details")
            if prompt_details:
                cached = prompt_details.get("cached_tokens", 0)

            # --- Dollar cost ---
            if cached:
                input_cost = (
                    ((prompt_tokens - cached) / 1_000_000) * pricing["input"]
                    + (cached / 1_000_000) * pricing["cached_input"]
                )
            else:
                input_cost = (prompt_tokens / 1_000_000) * pricing["input"]

            output_cost = (completion_tokens / 1_000_000) * pricing["output"]
            total = input_cost + output_cost

            # --- Accumulate ---
            if box_id not in self.box_costs:
                self.box_costs[box_id] = BoxCost(box_id=box_id)
            self.box_costs[box_id].add(usage, total)

            self.total_cost += total

        # Notify outside the lock to avoid deadlocks in callback chains.
        snapshot = self.get_snapshot()
        for cb in self._callbacks:
            try:
                await cb(snapshot)
            except Exception:
                pass  # Never let a callback crash the tracker

    # ------------------------------------------------------------------
    # Budget enforcement
    # ------------------------------------------------------------------

    def should_conclude(self) -> bool:
        """``True`` when spending has reached 80 % of the budget cap.

        Callers should signal boxes to begin wrapping up.
        """
        return self.total_cost >= self.budget_cap * _CONCLUDE_THRESHOLD

    def should_stop(self) -> bool:
        """``True`` when spending has reached 95 % of the budget cap.

        Callers should hard-stop all in-flight boxes.
        """
        return self.total_cost >= self.budget_cap * _STOP_THRESHOLD

    @property
    def remaining_budget(self) -> float:
        """Dollars still available under the cap."""
        return max(0.0, self.budget_cap - self.total_cost)

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def get_burn_rate(self) -> float:
        """Current spend rate in $/minute since the tracker was created."""
        elapsed_minutes = (datetime.utcnow() - self.start_time).total_seconds() / 60
        return self.total_cost / max(elapsed_minutes, 0.01)

    def _project_total(self) -> float:
        """Rough projection of the total run cost.

        Uses a simple heuristic: if we have cycle data, assume ~50 %
        more spend is still ahead, but never exceed the budget cap.
        """
        if self.total_cost == 0:
            return 0.0
        total_cycles = sum(bc.cycles for bc in self.box_costs.values())
        if total_cycles == 0:
            return self.total_cost
        return min(self.total_cost * 1.5, self.budget_cap)

    def calculate_cache_rate(self) -> float:
        """Overall prompt-cache hit rate across all boxes (0-100 %)."""
        total_input = sum(bc.input_tokens for bc in self.box_costs.values())
        total_cached = sum(bc.cached_tokens for bc in self.box_costs.values())
        if total_input == 0:
            return 0.0
        return round((total_cached / total_input) * 100, 1)

    # ------------------------------------------------------------------
    # Snapshot for the frontend
    # ------------------------------------------------------------------

    def get_snapshot(self) -> dict:
        """Return the full cost state as a JSON-serialisable dict."""
        return {
            "total_cost": round(self.total_cost, 4),
            "budget_cap": self.budget_cap,
            "budget_pct": round(
                (self.total_cost / max(self.budget_cap, 0.01)) * 100, 1
            ),
            "burn_rate": round(self.get_burn_rate(), 4),
            "projected_total": round(self._project_total(), 4),
            "cache_rate": self.calculate_cache_rate(),
            "remaining_budget": round(self.remaining_budget, 4),
            "boxes": {k: v.to_dict() for k, v in self.box_costs.items()},
            "should_conclude": self.should_conclude(),
            "should_stop": self.should_stop(),
        }
