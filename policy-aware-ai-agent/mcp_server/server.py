from __future__ import annotations

import os
from typing import Any, Literal

import httpx
from mcp.server import MCPServer

mcp = MCPServer(
    "secure-agent-tools",
    instructions=(
        "Kubernetes operations exposed by this server always go through the "
        "Secure Agent Gateway. The MCP server itself never talks directly to "
        "the Kubernetes API."
    ),
)

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:8080").rstrip("/")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("GATEWAY_TIMEOUT_SECONDS", "15"))

Namespace = Literal["agent-lab-staging", "agent-lab-production"]


def _json_or_text(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}


def _gateway_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = client.post(f"{GATEWAY_URL}{path}", json=payload)
    return {
        "http_status": response.status_code,
        "gateway_response": _json_or_text(response),
    }


def _gateway_get(path: str) -> tuple[int, Any]:
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = client.get(f"{GATEWAY_URL}{path}")
    return response.status_code, _json_or_text(response)


@mcp.tool()
def get_logs(
    namespace: Namespace,
    deployment: str,
    reason: str = "Inspect deployment logs before taking a write action.",
) -> dict[str, Any]:
    """Read logs for a Kubernetes deployment through the trusted security gateway."""
    action = {
        "tool": "get_logs",
        "namespace": namespace,
        "resource_kind": "deployment",
        "resource": deployment,
        "reason": reason,
    }
    return _gateway_post("/v1/actions/propose", action)


@mcp.tool()
def restart_deployment(
    namespace: Namespace,
    deployment: str,
    reason: str,
) -> dict[str, Any]:
    """Request a deployment restart through Gateway validation, OPA policy, approval, and RBAC."""
    action = {
        "tool": "restart_deployment",
        "namespace": namespace,
        "resource_kind": "deployment",
        "resource": deployment,
        "reason": reason,
    }
    return _gateway_post("/v1/actions/propose", action)


@mcp.tool()
def get_approval_status(approval_id: str) -> dict[str, Any]:
    """Read the trusted Gateway status for a previously created approval request."""
    status, body = _gateway_get(f"/v1/approvals/{approval_id}")
    return {"http_status": status, "gateway_response": body}


@mcp.tool()
def execute_approved_action(approval_id: str) -> dict[str, Any]:
    """Execute the exact action bound to an approved request; the model cannot replace its parameters."""
    status, approval = _gateway_get(f"/v1/approvals/{approval_id}")
    if status != 200 or not isinstance(approval, dict):
        return {"http_status": status, "gateway_response": approval}

    if approval.get("status") != "approved":
        return {
            "http_status": 409,
            "gateway_response": {
                "status": "not_approved",
                "approval_id": approval_id,
                "approval_status": approval.get("status"),
            },
        }

    action = approval.get("action")
    if not isinstance(action, dict):
        return {
            "http_status": 500,
            "gateway_response": {
                "status": "invalid_approval_record",
                "approval_id": approval_id,
            },
        }

    return _gateway_post(
        "/v1/actions/execute-approved",
        {"approval_id": approval_id, "action": action},
    )


if __name__ == "__main__":
    mcp.run()
