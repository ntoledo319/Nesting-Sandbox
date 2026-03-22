from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from app.engine.cost_tracker import CostTracker
from app.engine.report_generator import generate_full_report, generate_box_report, generate_receipt

router = APIRouter()

@router.get("/runs/{run_id}/report")
async def get_report(run_id: str, request: Request):
    """Get the full report for a run (completed or in-progress)."""
    run_manager = request.app.state.run_manager
    run_state = run_manager.get_run(run_id)
    if not run_state:
        raise HTTPException(status_code=404, detail="Run not found")

    cost_tracker = run_manager.get_cost_tracker(run_id)
    if cost_tracker is None:
        # Run was cleaned up — build a stub tracker from the saved total cost
        cost_tracker = CostTracker(run_state.budget_cap)
        cost_tracker.total_cost = run_state.total_cost
    event_store = run_manager.get_event_store(run_id)

    # Use events from the right source without mutating shared state
    events = run_state.events if run_state.events else (
        event_store.get_all_events() if event_store else []
    )

    report = generate_full_report(run_state, cost_tracker, events)
    if run_state.status == "running":
        report["partial"] = True
    return report

@router.get("/runs/{run_id}/report/download")
async def download_report(run_id: str, request: Request):
    """Download the full report as JSON."""
    run_manager = request.app.state.run_manager
    run_state = run_manager.get_run(run_id)
    if not run_state:
        raise HTTPException(status_code=404, detail="Run not found")

    cost_tracker = run_manager.get_cost_tracker(run_id)
    if cost_tracker is None:
        cost_tracker = CostTracker(run_state.budget_cap)
        cost_tracker.total_cost = run_state.total_cost
    event_store = run_manager.get_event_store(run_id)

    # Use events from the right source without mutating shared state
    events = run_state.events if run_state.events else (
        event_store.get_all_events() if event_store else []
    )

    report = generate_full_report(run_state, cost_tracker, events)

    return JSONResponse(
        content=jsonable_encoder(report),
        headers={
            "Content-Disposition": f"attachment; filename=nesting-sandbox-{run_id[:8]}.json"
        }
    )
