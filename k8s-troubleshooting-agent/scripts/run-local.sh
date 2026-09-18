#!/usr/bin/env bash
set -euo pipefail
: "${TARGET_NAMESPACE:?Set TARGET_NAMESPACE}"
: "${OPENAI_API_KEY:?Set OPENAI_API_KEY}"
export LOCAL_KUBECONFIG=true
uvicorn app.api:app --host 127.0.0.1 --port 8080 --reload
