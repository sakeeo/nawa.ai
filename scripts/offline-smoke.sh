#!/usr/bin/env bash
# Phase 0 acceptance: the stack works offline with local models and cannot reach the internet.
set -euo pipefail
cd "$(dirname "$0")/.."

ONLINE="docker compose --profile local-llm"
OFFLINE="docker compose -f docker-compose.yml -f docker-compose.offline.yml --profile local-llm"

# Online and offline runs define the default network differently (internal or not), so Compose
# must delete and recreate it. That fails while any container is attached; stop them all first.
# Volumes are kept, so pulled models and data survive.
stop_all() { docker compose --profile "*" down --remove-orphans; }

echo "1/3 Pull local models while online (first run downloads several GB)..."
stop_all
$ONLINE up -d ollama
$ONLINE run --rm ollama-pull

echo "2/3 Restart the stack on an internal-only network with OFFLINE_MODE=true..."
stop_all
$OFFLINE up -d --build --force-recreate postgres redis ollama migrate api

for _ in $(seq 1 60); do
  if $OFFLINE exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)" 2>/dev/null; then
    break
  fi
  sleep 2
done

echo "3/3 Run the offline check inside the API container..."
$OFFLINE exec -T api python -m nawa.intelligence.smoke
