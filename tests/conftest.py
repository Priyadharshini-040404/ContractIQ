"""
ContractIQ - Pytest Configuration and Fixtures
"""

import pytest
import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from api.petstore_api import app, pets_db, orders_db, seed_data
from api.task_api import app as task_app, tasks_db, seed_data as task_seed_data


@pytest.fixture
def api_client():
    """Create a FastAPI test client."""
    # Reset database state
    pets_db.clear()
    orders_db.clear()
    seed_data()
    client = TestClient(app)
    return client


@pytest.fixture
def task_client():
    """Create a FastAPI test client for the second (Task List) target
    API used in Group 5 to prove ContractIQ's generation is
    spec-driven rather than PetStore-specific."""
    tasks_db.clear()
    task_seed_data()
    client = TestClient(task_app)
    return client


@pytest.fixture
def spec_path():
    """Return path to the OpenAPI spec file."""
    return str(Path(__file__).parent.parent / "configs" / "openapi_spec.yaml")


@pytest.fixture
def sample_pet_data():
    """Sample pet data for testing."""
    return {
        "name": "TestDog",
        "species": "Dog",
        "age": 5,
        "status": "available",
        "tags": ["test", "friendly"],
        "price": 250.0,
    }


@pytest.fixture
def sample_pipeline_result():
    """Sample pipeline result for testing generators and executors."""
    return {
        "api_info": {
            "title": "Test API",
            "version": "1.0.0",
            "description": "Test",
            "openapi_version": "3.1.0",
        },
        "server_url": "http://localhost:8000",
        "test_suites": [
            {
                "endpoint": "GET /api/v1/pets",
                "operation_id": "list_pets",
                "test_cases": [
                    {
                        "test_id": "list_pets_positive_01",
                        "name": "List all pets",
                        "type": "positive",
                        "description": "Test listing all pets",
                        "request": {
                            "method": "GET",
                            "path": "/api/v1/pets",
                            "headers": {"Content-Type": "application/json"},
                            "query_params": {},
                            "body": None,
                        },
                        "expected": {
                            "status_code": 200,
                            "response_body_contains": [],
                            "response_type": "json",
                        },
                    },
                    {
                        "test_id": "list_pets_negative_01",
                        "name": "List pets with invalid status",
                        "type": "negative",
                        "description": "Test with invalid status filter",
                        "request": {
                            "method": "GET",
                            "path": "/api/v1/pets",
                            "headers": {"Content-Type": "application/json"},
                            "query_params": {"status": "invalid_status"},
                            "body": None,
                        },
                        "expected": {
                            "status_code": 422,
                            "response_body_contains": ["detail"],
                            "response_type": "json",
                        },
                    },
                ],
            },
            {
                "endpoint": "POST /api/v1/pets",
                "operation_id": "create_pet",
                "test_cases": [
                    {
                        "test_id": "create_pet_positive_01",
                        "name": "Create a new pet",
                        "type": "positive",
                        "description": "Test creating a pet",
                        "request": {
                            "method": "POST",
                            "path": "/api/v1/pets",
                            "headers": {"Content-Type": "application/json"},
                            "query_params": {},
                            "body": {
                                "name": "TestPet",
                                "species": "Cat",
                                "age": 2,
                                "price": 100.0,
                            },
                        },
                        "expected": {
                            "status_code": 201,
                            "response_body_contains": ["id", "name"],
                            "response_type": "json",
                        },
                    },
                    {
                        "test_id": "create_pet_edge_01",
                        "name": "Create pet with empty body",
                        "type": "edge_case",
                        "description": "Test with empty body",
                        "request": {
                            "method": "POST",
                            "path": "/api/v1/pets",
                            "headers": {"Content-Type": "application/json"},
                            "query_params": {},
                            "body": {},
                        },
                        "expected": {
                            "status_code": 422,
                            "response_body_contains": ["detail"],
                            "response_type": "json",
                        },
                    },
                ],
            },
        ],
        "assertions": [
            {
                "test_id": "list_pets_positive_01",
                "assertions": [
                    {
                        "type": "status_code",
                        "field": None,
                        "operator": "equals",
                        "expected_value": 200,
                        "description": "Status should be 200",
                    },
                    {
                        "type": "response_body",
                        "field": None,
                        "operator": "type_check",
                        "expected_value": "list",
                        "description": "Response should be a list",
                    },
                ],
            },
        ],
        "metadata": {
            "total_endpoints": 2,
            "total_test_cases": 4,
            "total_assertions": 2,
            "generation_method": "template",
        },
    }


@pytest.fixture
def sample_execution_results():
    """Sample execution results for testing failure analysis."""
    return {
        "total_tests": 4,
        "passed": 2,
        "failed": 2,
        "pass_rate": "50.0%",
        "total_duration_seconds": 1.5,
        "base_url": "http://localhost:8000",
        "results": [
            {
                "test_id": "list_pets_positive_01",
                "test_name": "List all pets",
                "test_type": "positive",
                "method": "GET",
                "url": "http://localhost:8000/api/v1/pets",
                "status": "passed",
                "actual_status_code": 200,
                "response_time_ms": 15.5,
                "assertions": [
                    {"type": "status_code", "expected": 200, "actual": 200, "passed": True}
                ],
            },
            {
                "test_id": "create_pet_positive_01",
                "test_name": "Create a new pet",
                "test_type": "positive",
                "method": "POST",
                "url": "http://localhost:8000/api/v1/pets",
                "status": "passed",
                "actual_status_code": 201,
                "response_time_ms": 22.3,
                "response_body": {"id": "abc123", "name": "TestPet"},
                "assertions": [
                    {"type": "status_code", "expected": 201, "actual": 201, "passed": True}
                ],
            },
        ],
        "failures": [
            {
                "test_id": "get_pet_negative_01",
                "test_name": "Get nonexistent pet",
                "test_type": "negative",
                "method": "GET",
                "url": "http://localhost:8000/api/v1/pets/nonexistent",
                "status": "failed",
                "actual_status_code": 404,
                "response_body": {"detail": "Pet nonexistent not found"},
                "assertions": [
                    {"type": "status_code", "expected": 200, "actual": 404, "passed": False}
                ],
            },
            {
                "test_id": "create_pet_edge_01",
                "test_name": "Create pet with empty body",
                "test_type": "edge_case",
                "method": "POST",
                "url": "http://localhost:8000/api/v1/pets",
                "status": "failed",
                "actual_status_code": 422,
                "response_body": {"detail": "Validation error"},
                "assertions": [
                    {"type": "status_code", "expected": 201, "actual": 422, "passed": False}
                ],
            },
        ],
    }
