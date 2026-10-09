#!/usr/bin/env bash
set -euo pipefail
curl -fsS "${GATEWAY_URL:-http://localhost:8080}/health"; echo
curl -fsS "${OPA_HOST_URL:-http://localhost:8181}/health"; echo
