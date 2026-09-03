"""
ContractIQ - Second Target API: Task List API

A small, deliberately unrelated Task-List API. Its only purpose is to
prove (Group 5) that core/test_synthesizer.py generalizes to ANY
OpenAPI spec with zero code changes — it shares no path, parameter
name, or schema with api/petstore_api.py, but is exercised by the
exact same TestSynthesizer / ResourceDiscovery / AssertionSynthesizer
code.
"""

from fastapi import FastAPI, HTTPException, Query, Path, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum
import uuid
from datetime import datetime, timezone

app = FastAPI(
    title="ContractIQ Task List API",
    description="A small Task List API used to prove ContractIQ's test generation is spec-driven, not PetStore-specific",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


def _error_body(detail: str, error_code: str) -> dict:
    return {
        "detail": detail,
        "error_code": error_code,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    error_code_map = {404: "NOT_FOUND", 422: "VALIDATION_ERROR", 400: "BAD_REQUEST"}
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(str(exc.detail), error_code_map.get(exc.status_code, "ERROR")),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=_error_body("Request validation failed", "VALIDATION_ERROR"),
    )


class TaskPriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="Title of the task")
    priority: TaskPriority = Field(..., description="Task priority")
    completed: bool = Field(default=False, description="Whether the task is done")
    due_in_days: Optional[int] = Field(None, ge=0, le=365, description="Days until due")


class Task(TaskCreate):
    id: str = Field(..., description="Unique task identifier")
    created_at: str = Field(..., description="Creation timestamp")


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    priority: Optional[TaskPriority] = None
    completed: Optional[bool] = None
    due_in_days: Optional[int] = Field(None, ge=0, le=365)


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str


class ErrorResponse(BaseModel):
    detail: str
    error_code: str
    timestamp: str


tasks_db: dict[str, dict] = {}


def seed_data():
    sample_tasks = [
        {"title": "Write quarterly report", "priority": "high", "completed": False, "due_in_days": 2},
        {"title": "Water the plants", "priority": "low", "completed": True, "due_in_days": 0},
    ]
    for task_data in sample_tasks:
        task_id = str(uuid.uuid4())[:8]
        tasks_db[task_id] = {
            "id": task_id,
            **task_data,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


seed_data()


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    return HealthResponse(status="healthy", timestamp=datetime.now(timezone.utc).isoformat(), version="1.0.0")


@app.get("/api/v1/tasks", response_model=List[Task], tags=["Tasks"])
async def list_tasks(
    completed: Optional[bool] = Query(None),
    priority: Optional[TaskPriority] = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    results = list(tasks_db.values())
    if completed is not None:
        results = [t for t in results if t["completed"] == completed]
    if priority:
        results = [t for t in results if t["priority"] == priority.value]
    return results[:limit]


@app.get("/api/v1/tasks/{task_id}", response_model=Task, tags=["Tasks"],
         responses={404: {"model": ErrorResponse}})
async def get_task(task_id: str = Path(...)):
    if task_id not in tasks_db:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return tasks_db[task_id]


@app.post("/api/v1/tasks", response_model=Task, status_code=201, tags=["Tasks"],
          responses={422: {"model": ErrorResponse}})
async def create_task(task: TaskCreate):
    task_id = str(uuid.uuid4())[:8]
    task_data = {
        "id": task_id,
        **task.model_dump(),
        "priority": task.priority.value,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    tasks_db[task_id] = task_data
    return task_data


@app.put("/api/v1/tasks/{task_id}", response_model=Task, tags=["Tasks"],
         responses={404: {"model": ErrorResponse}})
async def update_task(task_id: str, task: TaskUpdate):
    if task_id not in tasks_db:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    existing = tasks_db[task_id]
    update_data = task.model_dump(exclude_unset=True)
    if "priority" in update_data and update_data["priority"] is not None:
        update_data["priority"] = update_data["priority"].value
    existing.update(update_data)
    tasks_db[task_id] = existing
    return existing


@app.delete("/api/v1/tasks/{task_id}", status_code=204, tags=["Tasks"],
            responses={404: {"model": ErrorResponse}})
async def delete_task(task_id: str):
    if task_id not in tasks_db:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    del tasks_db[task_id]
    return None


@app.get("/api/v1/stats", tags=["System"])
async def get_stats():
    return {
        "total_tasks": len(tasks_db),
        "completed_tasks": len([t for t in tasks_db.values() if t["completed"]]),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
