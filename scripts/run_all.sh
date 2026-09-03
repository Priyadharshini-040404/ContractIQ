#!/usr/bin/env bash
# ContractIQ - One-shot end-to-end pipeline runner
#
# Runs the whole suite the way the proposal describes it — spec parsing,
# AI test generation (falls back to templates automatically if no AI keys
# or no network), execution against a live API, contract validation
# (Schemathesis + Dredd), and the HTML dashboard — without touching Java
# or Allure at any point.
#
# Usage: ./scripts/run_all.sh

set -euo pipefail
cd "$(dirname "$0")/.."

PORT=8000
BASE_URL="http://localhost:${PORT}"

echo "==> [1/7] Installing Python dependencies"
pip install -r requirements.txt --quiet

echo "==> [2/7] Running unit test suite with coverage"
rm -f .coverage
pytest -q --cov=. --cov-report=json:output/coverage.json --cov-report=term

echo "==> [3/7] Starting target API on ${BASE_URL}"
python -m uvicorn api.petstore_api:app --host 0.0.0.0 --port "${PORT}" > /tmp/contractiq_api.log 2>&1 &
API_PID=$!
trap 'echo "==> Stopping target API (pid ${API_PID})"; kill ${API_PID} 2>/dev/null || true' EXIT

# Wait for the API to become healthy instead of a fixed sleep.
for i in $(seq 1 20); do
    if curl -sf "${BASE_URL}/health" > /dev/null 2>&1; then
        break
    fi
    sleep 0.5
done
curl -sf "${BASE_URL}/health" > /dev/null || { echo "API failed to start — see /tmp/contractiq_api.log"; exit 1; }

echo "==> [4/7] Generating AI test cases (falls back to templates if no AI keys/network)"
python main.py generate --spec configs/openapi_spec.yaml

echo "==> [5/7] Executing generated tests against the live API"
python main.py execute --base-url "${BASE_URL}"

echo "==> [6/7] Running contract validation (Schemathesis + Dredd)"
python main.py contract --base-url "${BASE_URL}" --spec configs/openapi_spec.yaml || true

echo "==> [7/7] Building the reporting dashboard"
python main.py dashboard

echo ""
echo "Done. Open output/dashboard.html in a browser to see the results."
