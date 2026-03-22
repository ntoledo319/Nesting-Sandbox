import asyncio
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.models import Event, RunState

router = APIRouter()
logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.connections: dict[str, list[WebSocket]] = {}

    async def connect(self, run_id: str, websocket: WebSocket):
        await websocket.accept()
        if run_id not in self.connections:
            self.connections[run_id] = []
        self.connections[run_id].append(websocket)

    def disconnect(self, run_id: str, websocket: WebSocket):
        if run_id in self.connections:
            self.connections[run_id] = [
                ws for ws in self.connections[run_id] if ws != websocket
            ]
            if not self.connections[run_id]:
                del self.connections[run_id]

    async def broadcast(self, run_id: str, message: dict):
        if run_id not in self.connections:
            return
        dead = []
        for ws in self.connections[run_id]:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in self.connections.get(run_id, []):
                self.connections[run_id].remove(ws)


manager = ConnectionManager()


@router.websocket("/ws/runs/{run_id}")
async def websocket_endpoint(websocket: WebSocket, run_id: str):
    await manager.connect(run_id, websocket)

    # Get run manager from app state
    run_manager = websocket.app.state.run_manager
    run_state = run_manager.get_run(run_id)
    event_store = run_manager.get_event_store(run_id)
    cost_tracker = run_manager.get_cost_tracker(run_id)

    if not run_state:
        await websocket.send_json(
            {"type": "error", "data": {"message": "Run not found"}}
        )
        await websocket.close()
        return

    # --- Guard flag to prevent sends after disconnect ---
    connected = True

    # --- Callbacks for real-time updates ---

    async def on_event(event: Event):
        if not connected:
            return
        await manager.broadcast(
            run_id, {"type": "event", "data": event.model_dump(mode="json")}
        )
        # Also send box_spawned for specialist spawn events
        if event.event_type == "specialist_spawned":
            await manager.broadcast(
                run_id,
                {
                    "type": "box_spawned",
                    "data": {
                        "box_id": f"specialist:{event.metadata.get('spawned_name', '')}",
                        "name": event.metadata.get("spawned_name", ""),
                        "domain": event.metadata.get("spawned_domain", ""),
                    },
                },
            )

    async def on_cost(snapshot: dict):
        if not connected:
            return
        await manager.broadcast(run_id, {"type": "cost_update", "data": snapshot})

    async def on_status(box_id: str, status: str, cycle: int):
        if not connected:
            return
        await manager.broadcast(
            run_id,
            {
                "type": "box_status",
                "data": {"box_id": box_id, "status": status, "cycle": cycle},
            },
        )

    async def on_complete(state: RunState):
        if not connected:
            return
        cost = cost_tracker.get_snapshot() if cost_tracker else {}
        await manager.broadcast(
            run_id,
            {
                "type": "run_complete",
                "data": {
                    "run_id": run_id,
                    "status": state.status,
                    "total_cost": state.total_cost,
                    "receipt": cost,
                },
            },
        )

    # Register callbacks
    if event_store:
        event_store.add_ws_callback(on_event)
    if cost_tracker:
        cost_tracker.on_update(on_cost)
    run_manager.on_status_update(run_id, on_status)
    run_manager.on_run_complete(run_id, on_complete)

    # Send initial state (catches up the client if it connected late)
    await websocket.send_json(
        {
            "type": "initial_state",
            "data": {
                "run_id": run_id,
                "status": run_state.status,
                "mode": run_state.config.mode,
                "boxes": {
                    k: v.model_dump(mode="json")
                    for k, v in run_state.boxes.items()
                },
                "events": [
                    e.model_dump(mode="json")
                    for e in (
                        event_store.get_all_events() if event_store else []
                    )
                ],
                "cost": cost_tracker.get_snapshot() if cost_tracker else {},
            },
        }
    )

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "data": {"message": "Invalid JSON"}})
                continue

            if msg.get("type") == "stop":
                await run_manager.stop_run(run_id)
            elif msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg.get("type") == "user_input":
                content = msg.get("content", "").strip()
                if content and event_store:
                    user_event = Event(
                        source_box="user",
                        event_type="user_input",
                        content=content,
                        metadata={"injected": True},
                    )
                    await event_store.publish(user_event)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for run %s", run_id)
    except Exception as e:
        logger.error("WebSocket error for run %s: %s", run_id, e)
    finally:
        connected = False
        manager.disconnect(run_id, websocket)
        if event_store:
            event_store.remove_ws_callback(on_event)
        if cost_tracker:
            cost_tracker.remove_callback(on_cost)
