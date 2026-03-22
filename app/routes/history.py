"""REST endpoints for cross-run memory (run history)."""

import re
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

# UUID pattern — prevents path traversal via run_id
_RUN_ID_RE = re.compile(r'^[a-f0-9\-]{36}$')


def _validate_run_id(run_id: str) -> None:
    """Raise 404 if run_id is not a valid UUID string (also prevents path traversal)."""
    if not _RUN_ID_RE.match(run_id):
        raise HTTPException(status_code=404, detail="Run not found in history")


@router.get("/history")
async def list_history(request: Request):
    """List all saved runs."""
    run_history = request.app.state.run_history
    return run_history.list_runs()


@router.get("/history/{run_id}")
async def get_history(run_id: str, request: Request):
    """Get full saved run data."""
    _validate_run_id(run_id)
    run_history = request.app.state.run_history
    data = run_history.get_run(run_id)
    if not data:
        raise HTTPException(status_code=404, detail="Run not found in history")
    return data


@router.delete("/history/{run_id}")
async def delete_history(run_id: str, request: Request):
    """Delete a saved run from history."""
    _validate_run_id(run_id)
    run_history = request.app.state.run_history
    success = run_history.delete_run(run_id)
    if not success:
        raise HTTPException(status_code=404, detail="Run not found in history")
    return {"status": "deleted"}
