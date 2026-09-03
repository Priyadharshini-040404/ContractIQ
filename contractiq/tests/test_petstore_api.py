"""
ContractIQ - Unit Tests for PetStore Target API
Tests all CRUD operations and edge cases.
"""

import pytest
from fastapi.testclient import TestClient


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    def test_health_check(self, api_client):
        resp = api_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert data["version"] == "1.0.0"


class TestPetsEndpoints:
    """Tests for pet CRUD operations."""

    def test_list_pets(self, api_client):
        resp = api_client.get("/api/v1/pets")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 3  # Seeded data

    def test_list_pets_with_status_filter(self, api_client):
        resp = api_client.get("/api/v1/pets?status=available")
        assert resp.status_code == 200
        data = resp.json()
        assert all(p["status"] == "available" for p in data)

    def test_list_pets_with_species_filter(self, api_client):
        resp = api_client.get("/api/v1/pets?species=Dog")
        assert resp.status_code == 200
        data = resp.json()
        assert all(p["species"].lower() == "dog" for p in data)

    def test_list_pets_with_pagination(self, api_client):
        resp = api_client.get("/api/v1/pets?limit=1&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) <= 1

    def test_list_pets_invalid_status(self, api_client):
        resp = api_client.get("/api/v1/pets?status=invalid")
        assert resp.status_code == 422

    def test_create_pet(self, api_client, sample_pet_data):
        resp = api_client.post("/api/v1/pets", json=sample_pet_data)
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["name"] == sample_pet_data["name"]
        assert data["species"] == sample_pet_data["species"]
        assert data["age"] == sample_pet_data["age"]
        assert data["price"] == sample_pet_data["price"]
        assert "created_at" in data

    def test_create_pet_missing_required_fields(self, api_client):
        resp = api_client.post("/api/v1/pets", json={})
        assert resp.status_code == 422

    def test_create_pet_invalid_age(self, api_client, sample_pet_data):
        sample_pet_data["age"] = -1
        resp = api_client.post("/api/v1/pets", json=sample_pet_data)
        assert resp.status_code == 422

    def test_create_pet_invalid_price(self, api_client, sample_pet_data):
        sample_pet_data["price"] = -100
        resp = api_client.post("/api/v1/pets", json=sample_pet_data)
        assert resp.status_code == 422

    def test_create_pet_zero_price(self, api_client, sample_pet_data):
        sample_pet_data["price"] = 0
        resp = api_client.post("/api/v1/pets", json=sample_pet_data)
        assert resp.status_code == 422

    def test_create_pet_max_age(self, api_client, sample_pet_data):
        sample_pet_data["age"] = 30
        resp = api_client.post("/api/v1/pets", json=sample_pet_data)
        assert resp.status_code == 201

    def test_create_pet_exceeds_max_age(self, api_client, sample_pet_data):
        sample_pet_data["age"] = 31
        resp = api_client.post("/api/v1/pets", json=sample_pet_data)
        assert resp.status_code == 422

    def test_get_pet(self, api_client, sample_pet_data):
        # Create first
        create_resp = api_client.post("/api/v1/pets", json=sample_pet_data)
        pet_id = create_resp.json()["id"]

        # Get
        resp = api_client.get(f"/api/v1/pets/{pet_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == pet_id
        assert data["name"] == sample_pet_data["name"]

    def test_get_pet_not_found(self, api_client):
        resp = api_client.get("/api/v1/pets/nonexistent999")
        assert resp.status_code == 404
        assert "detail" in resp.json()

    def test_update_pet(self, api_client, sample_pet_data):
        create_resp = api_client.post("/api/v1/pets", json=sample_pet_data)
        pet_id = create_resp.json()["id"]

        update_data = {"name": "UpdatedName", "age": 7}
        resp = api_client.put(f"/api/v1/pets/{pet_id}", json=update_data)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "UpdatedName"
        assert data["age"] == 7

    def test_update_pet_not_found(self, api_client):
        resp = api_client.put("/api/v1/pets/nonexistent999", json={"name": "Test"})
        assert resp.status_code == 404

    def test_delete_pet(self, api_client, sample_pet_data):
        create_resp = api_client.post("/api/v1/pets", json=sample_pet_data)
        pet_id = create_resp.json()["id"]

        resp = api_client.delete(f"/api/v1/pets/{pet_id}")
        assert resp.status_code == 204

        # Verify deleted
        get_resp = api_client.get(f"/api/v1/pets/{pet_id}")
        assert get_resp.status_code == 404

    def test_delete_pet_not_found(self, api_client):
        resp = api_client.delete("/api/v1/pets/nonexistent999")
        assert resp.status_code == 404


class TestOrdersEndpoints:
    """Tests for order operations."""

    def test_create_order(self, api_client, sample_pet_data):
        # Create a pet first
        pet_resp = api_client.post("/api/v1/pets", json=sample_pet_data)
        pet_id = pet_resp.json()["id"]

        order_data = {"pet_id": pet_id, "quantity": 1}
        resp = api_client.post("/api/v1/orders", json=order_data)
        assert resp.status_code == 201
        data = resp.json()
        assert data["pet_id"] == pet_id
        assert data["quantity"] == 1
        assert data["total_price"] == sample_pet_data["price"]
        assert data["status"] == "placed"

    def test_create_order_pet_not_found(self, api_client):
        resp = api_client.post("/api/v1/orders", json={"pet_id": "fake", "quantity": 1})
        assert resp.status_code == 404

    def test_create_order_missing_fields(self, api_client):
        resp = api_client.post("/api/v1/orders", json={})
        assert resp.status_code == 422

    def test_get_order(self, api_client, sample_pet_data):
        pet_resp = api_client.post("/api/v1/pets", json=sample_pet_data)
        pet_id = pet_resp.json()["id"]

        order_resp = api_client.post("/api/v1/orders", json={"pet_id": pet_id, "quantity": 2})
        order_id = order_resp.json()["id"]

        resp = api_client.get(f"/api/v1/orders/{order_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == order_id
        assert data["total_price"] == sample_pet_data["price"] * 2

    def test_get_order_not_found(self, api_client):
        resp = api_client.get("/api/v1/orders/nonexistent")
        assert resp.status_code == 404

    def test_list_orders(self, api_client):
        resp = api_client.get("/api/v1/orders")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestStatsEndpoint:
    """Tests for the stats endpoint."""

    def test_get_stats(self, api_client):
        resp = api_client.get("/api/v1/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_pets" in data
        assert "total_orders" in data
        assert "pets_by_status" in data
        assert "timestamp" in data

    def test_stats_reflect_data(self, api_client, sample_pet_data):
        # Get initial stats
        initial = api_client.get("/api/v1/stats").json()

        # Add a pet
        api_client.post("/api/v1/pets", json=sample_pet_data)

        # Stats should update
        updated = api_client.get("/api/v1/stats").json()
        assert updated["total_pets"] == initial["total_pets"] + 1
