from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field


class TaskTool(str, Enum):
    """Enumeration of available browser automation tools for task execution."""
    navigate = "navigate"
    click = "click"
    type_text = "type_text"
    extract = "extract"
    search = "search"
    scroll = "scroll"


class TaskStep(BaseModel):
    """Represents a single step in a task execution plan with tool, target, and expected outcome."""
    step_number: int = Field(..., description="Sequential number of this step in the plan")
    tool: TaskTool = Field(..., description="The browser automation tool to use for this step")
    target: str = Field(..., description="URL, CSS selector, or search query depending on the tool")
    instruction: str = Field(..., description="Plain English description of what to do in this step")
    expected_outcome: str = Field(..., description="Description of what a successful step looks like")

    model_config = {"json_schema_extra": {"examples": [{"step_number": 1, "tool": "navigate", "target": "https://example.com", "instruction": "Go to the homepage", "expected_outcome": "Page loads successfully"}]}}


class TaskPlan(BaseModel):
    """Contains the goal and detailed step-by-step plan for completing a web task."""
    goal: str = Field(..., description="The user's goal in plain English")
    steps: list[TaskStep] = Field(default_factory=list, description="List of steps to execute the task")
    estimated_steps: int = Field(..., description="Estimated number of steps to complete the task")

    model_config = {"json_schema_extra": {"examples": [{"goal": "Find the price of a product", "steps": [], "estimated_steps": 3}]}}


class StepResult(BaseModel):
    """Captures the result of executing a single task step including observations and any extracted data."""
    step_number: int = Field(..., description="Sequential number of this step")
    success: bool = Field(..., description="Whether the step executed successfully")
    observation: str = Field(..., description="What the vision model observed on the screen")
    extracted_data: dict = Field(default_factory=dict, description="Any data extracted from the page")
    screenshot_path: str | None = Field(None, description="Path to saved screenshot of the page")
    error: str | None = Field(None, description="Error message if the step failed")

    model_config = {"json_schema_extra": {"examples": [{"step_number": 1, "success": True, "observation": "Page loaded with search bar visible", "extracted_data": {}, "screenshot_path": None, "error": None}]}}


class TaskMetrics(BaseModel):
    """Observability metrics for a task: token usage, USD cost, latency, and the
    vision-cache effectiveness. Populated from backend.metrics; all-zero when the
    METRICS_ENABLED flag is off."""
    input_tokens: int = Field(0, description="Prompt tokens summed across all LLM calls")
    output_tokens: int = Field(0, description="Completion tokens summed across all LLM calls")
    total_tokens: int = Field(0, description="Total tokens (input + output)")
    cost_usd: float = Field(0.0, description="Total USD cost from litellm.completion_cost")
    reasoning_calls: int = Field(0, description="Number of reasoning/tool-calling LLM calls")
    vision_calls: int = Field(0, description="Vision API calls actually made (cache misses)")
    vision_cache_hits: int = Field(0, description="Vision observations served from _ObservationCache")
    vision_cache_hit_rate: float = Field(0.0, description="hits / (hits + vision_calls)")
    vision_cost_saved_usd: float = Field(0.0, description="Estimated USD saved by cache hits")
    llm_latency_s: float = Field(0.0, description="Summed wall-clock latency of all LLM calls")
    avg_latency_s: float = Field(0.0, description="Average latency per LLM call")
    served_by: dict[str, int] = Field(default_factory=dict, description="provider/model -> call count")
    primary_provider: str = Field("", description="The model that served the most calls")


class TaskReport(BaseModel):
    """Comprehensive report of a completed task execution including plan, results, and final answer."""
    task_id: str = Field(..., description="Unique identifier for the task")
    goal: str = Field(..., description="The original user goal")
    status: Literal["completed", "failed", "partial"] = Field(..., description="Final status of the task")
    plan: TaskPlan = Field(..., description="The execution plan that was used")
    step_results: list[StepResult] = Field(default_factory=list, description="Results of each executed step")
    final_answer: str = Field(..., description="Structured result or answer to the user's goal")
    total_steps: int = Field(..., description="Total number of steps attempted")
    successful_steps: int = Field(..., description="Number of steps that succeeded")
    created_at: str = Field(..., description="ISO timestamp when the task was created")
    metrics: TaskMetrics = Field(default_factory=TaskMetrics, description="Token/cost/latency/cache metrics for this task")

    model_config = {"json_schema_extra": {"examples": [{"task_id": "task-123", "goal": "Find product price", "status": "completed", "plan": {"goal": "Find product price", "steps": [], "estimated_steps": 3}, "step_results": [], "final_answer": "The product costs $29.99", "total_steps": 3, "successful_steps": 3, "created_at": "2024-01-01T00:00:00Z", "metrics": {}}]}}
