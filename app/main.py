import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.routes import runs, ws, reports
from app.engine.run_manager import RunManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="The Nesting Sandbox", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared run manager instance
run_manager = RunManager()

@app.on_event("startup")
async def startup():
    app.state.run_manager = run_manager
    logger.info("Nesting Sandbox started")

# Include routers
app.include_router(runs.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(ws.router)

# Mount frontend static files (must be last)
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
