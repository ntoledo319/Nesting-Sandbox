from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
import uuid


class SpecialistConfig(BaseModel):
    name: str  # e.g., "Legal Implications"
    description: str  # Domain focus description for the system prompt


class RunConfig(BaseModel):
    question: str
    documents: list[str] = []  # Document text content
    specialists: list[SpecialistConfig] = []
    budget_cap: float = 10.0  # USD
    max_cycles: int = 50  # Safety limit even with budget
    api_key: Optional[str] = None  # Optional per-run API key


class Event(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source_box: str  # "box1", "box2", "specialist:Legal Implications"
    event_type: str  # "hypothesis", "evidence", "conclusion", "dead_end", "question", "connection", "done"
    content: str
    metadata: dict = {}  # token counts, model used, cycle number, etc.


class BoxState(BaseModel):
    box_id: str
    status: str = "waiting"  # "running", "thinking", "waiting", "concluding", "done", "error"
    current_cycle: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_reasoning_tokens: int = 0  # For o4-mini
    total_cost: float = 0.0
    findings: list[Event] = []


class RunState(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "created"  # "estimating", "running", "concluding", "completed", "stopped", "error"
    config: RunConfig
    boxes: dict[str, BoxState] = {}
    total_cost: float = 0.0
    budget_cap: float = 10.0
    start_time: datetime = Field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    events: list[Event] = []


class CostEstimate(BaseModel):
    input_tokens: int
    complexity_score: int
    estimated_cycles: int
    cost_low: float
    cost_high: float
    cost_per_cycle: float
    warnings: list[str] = []


class BoxCost(BaseModel):
    box_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    total_cost: float = 0.0
    cycles: int = 0

    def add(self, usage: dict, cost: float):
        self.input_tokens += usage.get("prompt_tokens", 0)
        self.output_tokens += usage.get("completion_tokens", 0)
        self.reasoning_tokens += usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0) if usage.get("completion_tokens_details") else 0
        self.cached_tokens += usage.get("prompt_tokens_details", {}).get("cached_tokens", 0) if usage.get("prompt_tokens_details") else 0
        self.total_cost += cost
        self.cycles += 1

    def to_dict(self):
        return self.model_dump()
