#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
CFG_DIR="$ROOT/agent/workspace/.codex"
CFG="$CFG_DIR/config.toml"

if [[ ! -x "$PYTHON" ]]; then
  echo "ERROR: Python not found at $PYTHON"
  echo "Create the virtual environment first: python3 -m venv .venv && source .venv/bin/activate"
  exit 1
fi

mkdir -p "$CFG_DIR"
cat > "$CFG" <<TOML
[mcp_servers.secure_agent]
command = "$PYTHON"
args = ["$ROOT/mcp_server/server.py"]
cwd = "$ROOT"
env = { GATEWAY_URL = "http://127.0.0.1:8080" }
required = true
enabled_tools = [
  "get_logs",
  "restart_deployment",
  "get_approval_status",
  "execute_approved_action"
]
startup_timeout_sec = 10
tool_timeout_sec = 60
TOML

echo "Wrote $CFG"
echo "Next: codex mcp list"
