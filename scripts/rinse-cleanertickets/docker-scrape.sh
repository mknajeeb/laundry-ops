#!/usr/bin/env bash
# Run the portal CSV scrape in Docker (Chromium inside the container).
# Prereqs: Docker, this folder has .env and rinse-auth.json (npm run save-session on host first).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
IMAGE="${RINSE_SCRAPE_IMAGE:-rinse-portal-scrape:latest}"

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example and configure, or mount your own env file."
  exit 1
fi
if [[ ! -f rinse-auth.json ]]; then
  echo "Missing rinse-auth.json — run: npm install && npm run save-session (on host), then retry."
  exit 1
fi

mkdir -p "${ROOT}/out"

docker build -t "$IMAGE" "$ROOT"

# Paths inside the container: auth file is read-only at /secrets/rinse-auth.json
docker run --rm \
  --env-file "$ROOT/.env" \
  -e RINSE_STORAGE_STATE=/secrets/rinse-auth.json \
  -e OUTPUT_CSV="${OUTPUT_CSV:-/out/rinse-portal-$(date +%Y-%m-%d).csv}" \
  -v "$ROOT/rinse-auth.json:/secrets/rinse-auth.json:ro" \
  -v "$ROOT/out:/out" \
  "$IMAGE"

echo ""
echo "CSV is under ${ROOT}/out — upload it on Upload Orders (portal CSV → draft), or copy into your pipeline."
