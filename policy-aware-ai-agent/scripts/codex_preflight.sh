#!/usr/bin/env bash
set -euo pipefail
command -v codex >/dev/null || { echo "ERROR: codex not found"; exit 1; }
codex --version
H="$(codex exec --help 2>&1)"
for f in --sandbox --ignore-rules --ephemeral; do
  grep -q -- "$f" <<<"$H" || { echo "ERROR: missing $f"; exit 1; }
done
M="$(codex mcp list 2>&1)"
grep -q -- "secure_agent" <<<"$M" || { echo "ERROR: secure_agent MCP server not configured"; exit 1; }
echo "Codex + MCP preflight: OK"
