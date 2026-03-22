from fastapi import APIRouter, HTTPException, Request
from app.models import RunConfig, CostEstimate
from app.engine.cost_estimator import estimate_run_cost
from openai import AsyncOpenAI

router = APIRouter()

@router.post("/runs")
async def create_run(config: RunConfig, request: Request):
    """Start a new run."""
    run_manager = request.app.state.run_manager

    # Check concurrent run limit
    active = sum(1 for r in run_manager.active_runs.values() if r.status == "running")
    if active >= 3:
        raise HTTPException(status_code=429, detail="Max concurrent runs reached")

    run_state = await run_manager.start_run(config)
    return {
        "run_id": run_state.run_id,
        "status": run_state.status,
    }

@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request):
    """Get current run state."""
    run_manager = request.app.state.run_manager
    run_state = run_manager.get_run(run_id)
    if not run_state:
        raise HTTPException(status_code=404, detail="Run not found")

    cost_tracker = run_manager.get_cost_tracker(run_id)

    return {
        "run_id": run_state.run_id,
        "status": run_state.status,
        "config": run_state.config.model_dump(exclude={"api_key"}),
        "boxes": {k: v.model_dump() for k, v in run_state.boxes.items()},
        "total_cost": cost_tracker.total_cost if cost_tracker else 0,
        "budget_cap": run_state.budget_cap,
        "start_time": run_state.start_time.isoformat(),
        "end_time": run_state.end_time.isoformat() if run_state.end_time else None,
        "event_count": len(run_state.events) if run_state.events else (
            len(run_manager.get_event_store(run_id).get_all_events()) if run_manager.get_event_store(run_id) else 0
        ),
    }

@router.post("/runs/{run_id}/stop")
async def stop_run(run_id: str, request: Request):
    """Stop a running run."""
    run_manager = request.app.state.run_manager
    success = await run_manager.stop_run(run_id)
    if not success:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"status": "stopped"}

@router.post("/estimate")
async def estimate_cost(config: RunConfig):
    """Get pre-run cost estimate."""
    api_key = config.api_key
    client = AsyncOpenAI(api_key=api_key) if api_key else AsyncOpenAI()
    estimate = await estimate_run_cost(client, config)
    return estimate.model_dump()
