"""
ContractIQ - Load Testing with Locust
Fulfils the proposal's QA Strategy requirement:
  "Load Testing | Execution performance across multiple APIs | Locust | <30 sec execution"

Run with:
    locust -f qa/locustfile.py --host http://localhost:8000 --headless \
        -u 20 -r 5 --run-time 20s --csv=output/locust/locust_report

  -u 20        : 20 concurrent simulated users
  -r 5         : spawn rate of 5 users/second
  --run-time   : how long the test runs (keep under 30s per proposal's target)
  --csv        : writes locust_report_stats.csv / _failures.csv / _stats_history.csv
"""
import random
from locust import HttpUser, task, between


class PetStoreUser(HttpUser):
    """Simulates a realistic mix of PetStore API traffic."""
    wait_time = between(0.2, 1.0)

    def on_start(self):
        """Each simulated user creates one pet it can reuse for read/update calls."""
        self.owned_pet_id = None
        resp = self.client.post("/api/v1/pets", json={
            "name": f"LoadTestPet-{random.randint(1, 999999)}",
            "species": random.choice(["Dog", "Cat", "Rabbit", "Parrot"]),
            "age": random.randint(0, 15),
            "status": "available",
            "tags": ["load-test"],
            "price": round(random.uniform(10, 2000), 2),
        }, name="/api/v1/pets [setup: create pet]")
        if resp.status_code == 201:
            self.owned_pet_id = resp.json().get("id")

    @task(5)
    def list_pets(self):
        self.client.get("/api/v1/pets", name="/api/v1/pets [list]")

    @task(3)
    def get_own_pet(self):
        if self.owned_pet_id:
            self.client.get(f"/api/v1/pets/{self.owned_pet_id}", name="/api/v1/pets/{pet_id} [get]")

    @task(2)
    def update_own_pet(self):
        if self.owned_pet_id:
            self.client.put(f"/api/v1/pets/{self.owned_pet_id}", json={
                "price": round(random.uniform(10, 2000), 2),
            }, name="/api/v1/pets/{pet_id} [update]")

    @task(2)
    def create_order(self):
        if self.owned_pet_id:
            self.client.post("/api/v1/orders", json={
                "pet_id": self.owned_pet_id,
                "quantity": random.randint(1, 3),
            }, name="/api/v1/orders [create]")

    @task(2)
    def list_orders(self):
        self.client.get("/api/v1/orders", name="/api/v1/orders [list]")

    @task(1)
    def health_check(self):
        self.client.get("/health", name="/health")

    @task(1)
    def get_stats(self):
        self.client.get("/api/v1/stats", name="/api/v1/stats")
