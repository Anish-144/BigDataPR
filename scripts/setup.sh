#!/usr/bin/env bash
# One-time setup + start: Python venv for host tools/tests, Docker images, stack.
#   scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

command -v docker >/dev/null || { echo "Docker is required (Docker Desktop on Windows/macOS)"; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker engine is not running - start Docker Desktop first"; exit 1; }

if [[ ! -d .venv ]]; then
  echo "==> creating Python virtualenv (.venv)"
  if command -v py >/dev/null; then py -3.12 -m venv .venv; else python3 -m venv .venv; fi
fi
source scripts/_common.sh
echo "==> installing Python dependencies into .venv"
$PY -m pip install -q --upgrade pip
$PY -m pip install -q -r requirements-dev.txt

[[ -f .env ]] || { cp .env.example .env; echo "==> created .env from .env.example"; }

echo "==> building images"
docker compose build

echo "==> starting stack (first start pulls images and may take several minutes)"
docker compose up -d
echo "==> waiting for the API"
wait_for_url http://localhost:8000/health 300
docker compose ps
echo
echo "AgentShield is up:"
echo "  Dashboard        http://localhost:3000   (if the frontend service is enabled)"
echo "  API docs         http://localhost:8000/docs"
echo "  Trino UI         http://localhost:8080"
echo "  Spark UI         http://localhost:4040"
echo "  MinIO console    http://localhost:9001"
echo "Next: scripts/generate_demo_data.sh"
