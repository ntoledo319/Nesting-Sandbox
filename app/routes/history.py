"""REST endpoints for cross-run memory (run history)."""

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


@router.get("/history")
async def list_history(request: Request):
    """List all saved runs."""
    run_history = request.app.state.run_history
    return run_history.list_runs()


@router.get("/history/{run_id}")
async def get_history(run_id: str, request: Request):
    """Get full saved run data."""
    run_history = request.app.state.run_history
    data = run_history.get_run(run_id)
    if not data:
        raise HTTPException(status_code=404, detail="Run not found in history")
    return data


@router.delete("/history/{run_id}")
async def delete_history(run_id: str, request: Request):
    """Delete a saved run from history."""
    run_history = request.app.state.run_history
    success = run_history.delete_run(run_id)
    if not success:
        raise HTTPException(status_code=404, detail="Run not found in history")
    return {"status": "deleted"}
