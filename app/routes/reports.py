import json
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from app.engine.report_generator import generate_full_report, generate_box_report, generate_receipt

router = APIRouter()

@router.get("/runs/{run_id}/report")
async def get_report(run_id: str, request: Request):
    """Get the full report for a completed run."""
    run_manager = request.app.state.run_manager
    run_state = run_manager.get_run(run_id)
    if not run_state:
        raise HTTPException(status_code=404, detail="Run not found")

    cost_tracker = run_manager.get_cost_tracker(run_id)
    event_store = run_manager.get_event_store(run_id)

    # Make sure events are populated
    if event_store and not run_state.events:
        run_state.events = event_store.get_all_events()

    report = generate_full_report(run_state, cost_tracker)
    return report

@router.get("/runs/{run_id}/report/download")
async def download_report(run_id: str, request: Request):
    """Download the full report as JSON."""
    run_manager = request.app.state.run_manager
    run_state = run_manager.get_run(run_id)
    if not run_state:
        raise HTTPException(status_code=404, detail="Run not found")

    cost_tracker = run_manager.get_cost_tracker(run_id)
    event_store = run_manager.get_event_store(run_id)

    if event_store and not run_state.events:
        run_state.events = event_store.get_all_events()

    report = generate_full_report(run_state, cost_tracker)

    return JSONResponse(
        content=report,
        headers={
            "Content-Disposition": f"attachment; filename=nesting-sandbox-{run_id[:8]}.json"
        }
    )
