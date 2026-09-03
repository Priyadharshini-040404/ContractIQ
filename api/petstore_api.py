"""
ContractIQ - Target API: PetStore API
A lightweight FastAPI-based PetStore API used as the testing target.
"""

from fastapi import FastAPI, HTTPException, Query, Path, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum
import uuid
from datetime import datetime

app = FastAPI(
    title="ContractIQ PetStore API",
    description="A lightweight PetStore API for intelligent API testing and validation",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


def _error_body(detail: str, error_code: str) -> dict:
    """Build an error response matching the ErrorResponse schema declared
    in the OpenAPI spec (detail + error_code + timestamp), so the API's
    actual error responses conform to what the contract promises. This
    closes a real spec-vs-implementation drift that Dredd caught: the spec
    required these three fields, but handlers previously only returned
    {"detail": ...}."""
    return {
        "detail": detail,
        "error_code": error_code,
        "timestamp": datetime.utcnow().isoformat(),
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


# --- Enums ---
class PetStatus(str, Enum):
    available = "available"
    pending = "pending"
    sold = "sold"

class OrderStatus(str, Enum):
    placed = "placed"
    approved = "approved"
    delivered = "delivered"

# --- Models ---
class PetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Name of the pet")
    species: str = Field(..., min_length=1, max_length=50, description="Species of the pet")
    age: int = Field(..., ge=0, le=30, description="Age of the pet in years")
    status: PetStatus = Field(default=PetStatus.available, description="Current status")
    tags: List[str] = Field(default=[], description="Tags for the pet")
    price: float = Field(..., gt=0, le=10000, description="Price of the pet")

class Pet(PetCreate):
    id: str = Field(..., description="Unique pet identifier")
    created_at: str = Field(..., description="Creation timestamp")

class PetUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    species: Optional[str] = Field(None, min_length=1, max_length=50)
    age: Optional[int] = Field(None, ge=0, le=30)
    status: Optional[PetStatus] = None
    tags: Optional[List[str]] = None
    price: Optional[float] = Field(None, gt=0, le=10000)

class OrderCreate(BaseModel):
    pet_id: str = Field(..., description="ID of the pet to order")
    quantity: int = Field(..., ge=1, le=10, description="Number of pets")

class Order(OrderCreate):
    id: str = Field(..., description="Unique order identifier")
    status: OrderStatus = Field(default=OrderStatus.placed)
    total_price: float = Field(..., description="Total order price")
    created_at: str = Field(..., description="Order creation timestamp")

class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str

class ErrorResponse(BaseModel):
    detail: str
    error_code: str
    timestamp: str

# --- In-Memory Store ---
pets_db: dict[str, dict] = {}
orders_db: dict[str, dict] = {}

# Seed some initial data
def seed_data():
    sample_pets = [
        {"name": "Buddy", "species": "Dog", "age": 3, "status": "available", "tags": ["friendly", "trained"], "price": 500.0},
        {"name": "Whiskers", "species": "Cat", "age": 2, "status": "available", "tags": ["indoor", "playful"], "price": 300.0},
        {"name": "Goldie", "species": "Fish", "age": 1, "status": "pending", "tags": ["aquatic"], "price": 50.0},
    ]
    for pet_data in sample_pets:
        pet_id = str(uuid.uuid4())[:8]
        pets_db[pet_id] = {
            "id": pet_id,
            **pet_data,
            "created_at": datetime.utcnow().isoformat()
        }

seed_data()

# --- Health Endpoint ---
@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Check API health status."""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow().isoformat(),
        version="1.0.0"
    )

# --- Pet Endpoints ---
@app.get("/api/v1/pets", response_model=List[Pet], tags=["Pets"])
async def list_pets(
    status: Optional[PetStatus] = Query(None, description="Filter by status"),
    species: Optional[str] = Query(None, description="Filter by species"),
    limit: int = Query(10, ge=1, le=100, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """List all pets with optional filtering."""
    results = list(pets_db.values())
    if status:
        results = [p for p in results if p["status"] == status.value]
    if species:
        results = [p for p in results if p["species"].lower() == species.lower()]
    return results[offset:offset + limit]

@app.get("/api/v1/pets/{pet_id}", response_model=Pet, tags=["Pets"],
         responses={404: {"model": ErrorResponse}})
async def get_pet(pet_id: str = Path(..., description="Pet ID")):
    """Get a specific pet by ID."""
    if pet_id not in pets_db:
        raise HTTPException(status_code=404, detail=f"Pet {pet_id} not found")
    return pets_db[pet_id]

@app.post("/api/v1/pets", response_model=Pet, status_code=201, tags=["Pets"],
          responses={422: {"model": ErrorResponse}})
async def create_pet(pet: PetCreate):
    """Create a new pet."""
    pet_id = str(uuid.uuid4())[:8]
    pet_data = {
        "id": pet_id,
        **pet.model_dump(),
        "status": pet.status.value,
        "created_at": datetime.utcnow().isoformat()
    }
    pets_db[pet_id] = pet_data
    return pet_data

@app.put("/api/v1/pets/{pet_id}", response_model=Pet, tags=["Pets"],
         responses={404: {"model": ErrorResponse}})
async def update_pet(pet_id: str, pet: PetUpdate):
    """Update an existing pet."""
    if pet_id not in pets_db:
        raise HTTPException(status_code=404, detail=f"Pet {pet_id} not found")
    existing = pets_db[pet_id]
    update_data = pet.model_dump(exclude_unset=True)
    if "status" in update_data and update_data["status"] is not None:
        update_data["status"] = update_data["status"].value
    existing.update(update_data)
    pets_db[pet_id] = existing
    return existing

@app.delete("/api/v1/pets/{pet_id}", status_code=204, tags=["Pets"],
            responses={404: {"model": ErrorResponse}})
async def delete_pet(pet_id: str):
    """Delete a pet."""
    if pet_id not in pets_db:
        raise HTTPException(status_code=404, detail=f"Pet {pet_id} not found")
    del pets_db[pet_id]
    return None

# --- Order Endpoints ---
@app.post("/api/v1/orders", response_model=Order, status_code=201, tags=["Orders"],
          responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})
async def create_order(order: OrderCreate):
    """Place a new order for a pet."""
    if order.pet_id not in pets_db:
        raise HTTPException(status_code=404, detail=f"Pet {order.pet_id} not found")
    pet = pets_db[order.pet_id]
    if pet["status"] == "sold":
        raise HTTPException(status_code=422, detail="Pet is already sold")
    order_id = str(uuid.uuid4())[:8]
    order_data = {
        "id": order_id,
        "pet_id": order.pet_id,
        "quantity": order.quantity,
        "status": OrderStatus.placed.value,
        "total_price": pet["price"] * order.quantity,
        "created_at": datetime.utcnow().isoformat()
    }
    orders_db[order_id] = order_data
    pets_db[order.pet_id]["status"] = "pending"
    return order_data

@app.get("/api/v1/orders/{order_id}", response_model=Order, tags=["Orders"],
         responses={404: {"model": ErrorResponse}})
async def get_order(order_id: str):
    """Get order details."""
    if order_id not in orders_db:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    return orders_db[order_id]

@app.get("/api/v1/orders", response_model=List[Order], tags=["Orders"])
async def list_orders(
    status: Optional[OrderStatus] = Query(None),
    limit: int = Query(10, ge=1, le=100),
):
    """List all orders."""
    results = list(orders_db.values())
    if status:
        results = [o for o in results if o["status"] == status.value]
    return results[:limit]

# --- Stats Endpoint ---
@app.get("/api/v1/stats", tags=["System"])
async def get_stats():
    """Get API statistics."""
    return {
        "total_pets": len(pets_db),
        "total_orders": len(orders_db),
        "pets_by_status": {
            s.value: len([p for p in pets_db.values() if p["status"] == s.value])
            for s in PetStatus
        },
        "timestamp": datetime.utcnow().isoformat()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
