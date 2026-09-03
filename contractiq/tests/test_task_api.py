"""
ContractIQ - Unit Tests for the Task List Target API

This is the second, deliberately unrelated target API (Group 5) that
proves core/test_synthesizer.py generalizes beyond PetStore. These
tests cover the API implementation itself (mirroring
test_petstore_api.py's structure), independent of the generation
engine's own tests in test_test_synthesizer.py.
"""

import pytest


class TestHealthEndpoint:
    def test_health_check(self, task_client):
        resp = task_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert data["version"] == "1.0.0"


class TestListTasks:
    def test_list_tasks(self, task_client):
        resp = task_client.get("/api/v1/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 2  # seeded data

    def test_list_tasks_completed_filter(self, task_client):
        resp = task_client.get("/api/v1/tasks?completed=true")
        assert resp.status_code == 200
        assert all(t["completed"] is True for t in resp.json())

    def test_list_tasks_priority_filter(self, task_client):
        resp = task_client.get("/api/v1/tasks?priority=high")
        assert resp.status_code == 200
        assert all(t["priority"] == "high" for t in resp.json())

    def test_list_tasks_with_limit(self, task_client):
        resp = task_client.get("/api/v1/tasks?limit=1")
        assert resp.status_code == 200
        assert len(resp.json()) <= 1

    def test_list_tasks_invalid_priority(self, task_client):
        resp = task_client.get("/api/v1/tasks?priority=urgent")
        assert resp.status_code == 422

    def test_list_tasks_limit_out_of_range(self, task_client):
        resp = task_client.get("/api/v1/tasks?limit=0")
        assert resp.status_code == 422


class TestCreateTask:
    def test_create_task(self, task_client):
        resp = task_client.post("/api/v1/tasks", json={
            "title": "New task", "priority": "medium", "due_in_days": 5,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["title"] == "New task"
        assert data["priority"] == "medium"
        assert data["completed"] is False

    def test_create_task_missing_required_fields(self, task_client):
        resp = task_client.post("/api/v1/tasks", json={})
        assert resp.status_code == 422
        assert "detail" in resp.json()

    def test_create_task_title_too_long(self, task_client):
        resp = task_client.post("/api/v1/tasks", json={
            "title": "x" * 201, "priority": "low",
        })
        assert resp.status_code == 422

    def test_create_task_title_empty(self, task_client):
        resp = task_client.post("/api/v1/tasks", json={"title": "", "priority": "low"})
        assert resp.status_code == 422

    def test_create_task_invalid_priority(self, task_client):
        resp = task_client.post("/api/v1/tasks", json={"title": "x", "priority": "urgent"})
        assert resp.status_code == 422

    def test_create_task_due_in_days_out_of_range(self, task_client):
        resp = task_client.post("/api/v1/tasks", json={
            "title": "x", "priority": "low", "due_in_days": 400,
        })
        assert resp.status_code == 422


class TestGetUpdateDeleteTask:
    def _create(self, task_client):
        resp = task_client.post("/api/v1/tasks", json={"title": "t", "priority": "low"})
        return resp.json()["id"]

    def test_get_task(self, task_client):
        task_id = self._create(task_client)
        resp = task_client.get(f"/api/v1/tasks/{task_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == task_id

    def test_get_task_not_found(self, task_client):
        resp = task_client.get("/api/v1/tasks/nonexistent")
        assert resp.status_code == 404
        body = resp.json()
        assert body["error_code"] == "NOT_FOUND"
        assert "timestamp" in body

    def test_update_task(self, task_client):
        task_id = self._create(task_client)
        resp = task_client.put(f"/api/v1/tasks/{task_id}", json={"completed": True})
        assert resp.status_code == 200
        assert resp.json()["completed"] is True

    def test_update_task_priority(self, task_client):
        task_id = self._create(task_client)
        resp = task_client.put(f"/api/v1/tasks/{task_id}", json={"priority": "high"})
        assert resp.status_code == 200
        assert resp.json()["priority"] == "high"

    def test_update_task_not_found(self, task_client):
        resp = task_client.put("/api/v1/tasks/nonexistent", json={"completed": True})
        assert resp.status_code == 404

    def test_update_task_empty_body_is_noop(self, task_client):
        task_id = self._create(task_client)
        resp = task_client.put(f"/api/v1/tasks/{task_id}", json={})
        assert resp.status_code == 200

    def test_delete_task(self, task_client):
        task_id = self._create(task_client)
        resp = task_client.delete(f"/api/v1/tasks/{task_id}")
        assert resp.status_code == 204
        assert task_client.get(f"/api/v1/tasks/{task_id}").status_code == 404

    def test_delete_task_not_found(self, task_client):
        resp = task_client.delete("/api/v1/tasks/nonexistent")
        assert resp.status_code == 404


class TestStatsEndpoint:
    def test_get_stats(self, task_client):
        resp = task_client.get("/api/v1/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_tasks" in data
        assert "completed_tasks" in data
        assert "timestamp" in data

    def test_stats_reflect_data(self, task_client):
        before = task_client.get("/api/v1/stats").json()["total_tasks"]
        task_client.post("/api/v1/tasks", json={"title": "x", "priority": "low"})
        after = task_client.get("/api/v1/stats").json()["total_tasks"]
        assert after == before + 1
