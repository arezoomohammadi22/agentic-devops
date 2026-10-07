#!/usr/bin/env bash
set -euo pipefail

if ! command -v codex >/dev/null 2>&1; then
  echo "ERROR: codex is not in PATH"
  exit 1
fi

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

pip install -r agent/requirements.txt

docker compose up -d

python agent/codex_agent_monitor.py \
  --workdir ./demo-workspace \
  --trace-tool-details \
  --prompt "Use shell tools to inspect this directory. Run pwd, list the files, read demo.txt, then summarize what you found. Do not modify files."

echo
echo "Metrics:"
curl -s http://localhost:9464/metrics | grep -E 'codex|agent' || true

echo
echo "Grafana:    http://localhost:3000  (admin/admin for local demo)"
echo "Prometheus: http://localhost:9090"
echo "Tempo:      http://localhost:3200"
echo
echo 'Tempo TraceQL: { resource.service.name = "codex-agent-monitor" }'
