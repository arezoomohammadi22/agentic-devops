#!/usr/bin/env bash
set -euo pipefail

echo "== docker compose ps =="
docker compose ps

echo
echo "== dashboard files visible inside Grafana =="
docker compose exec -T grafana sh -lc 'ls -lah /etc/grafana/dashboards && echo && ls -lah /etc/grafana/provisioning/dashboards'

echo
echo "== provisioning-related Grafana logs =="
docker compose logs --no-color grafana | grep -Ei 'provision|dashboard|error|failed' | tail -100 || true

echo
echo "== Grafana health =="
curl -fsS http://localhost:3000/api/health || true
echo
