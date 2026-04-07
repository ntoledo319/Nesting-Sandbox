import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.routes import runs, ws, reports, history
from app.engine.run_manager import RunManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Shared run manager instance
run_manager = RunManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.run_manager = run_manager
    app.state.run_history = run_manager.run_history
    logger.info("Nesting Sandbox started")
    yield


app = FastAPI(title="The Nesting Sandbox", version="1.0.0", lifespan=lifespan)

# CORS — allow_credentials=True is incompatible with allow_origins=["*"]
# per the CORS spec (browsers will reject the response).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(runs.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(ws.router)

# Mount frontend static files (must be last)
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
