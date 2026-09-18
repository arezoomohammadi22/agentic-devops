from __future__ import annotations

from app.policy import ALLOWED_RESOURCES, WORKLOAD_RESOURCES


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
        "strict": True,
    }


def build_tool_schemas(enable_pv_lookup: bool) -> list[dict]:
    resources = sorted(ALLOWED_RESOURCES)
    tools = [
        _fn(
            "list_resources",
            "List an allowed Kubernetes resource in the configured target scope. Cluster metadata is limited to IngressClass and StorageClass.",
            {"resource": {"type": "string", "enum": resources}},
            ["resource"],
        ),
        _fn(
            "get_resource",
            "Read one allowed Kubernetes object by name from the configured target scope or allowed cluster metadata.",
            {
                "resource": {"type": "string", "enum": resources},
                "name": {"type": "string"},
            },
            ["resource", "name"],
        ),
        _fn(
            "get_pod_logs",
            "Read recent logs from a Pod. Use null for container when the Pod has one container.",
            {
                "pod_name": {"type": "string"},
                "container": {"type": ["string", "null"]},
                "tail_lines": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            ["pod_name", "container", "tail_lines"],
        ),
        _fn(
            "get_events",
            "Read Events. Pass both kind and name to filter one object, or null for both to read recent Events in the target scope.",
            {
                "kind": {"type": ["string", "null"]},
                "name": {"type": ["string", "null"]},
            },
            ["kind", "name"],
        ),
        _fn(
            "inspect_pod",
            "Collect a Pod, its Events, and optionally its recent logs for troubleshooting.",
            {
                "name": {"type": "string"},
                "include_logs": {"type": "boolean"},
                "container": {"type": ["string", "null"]},
                "tail_lines": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            ["name", "include_logs", "container", "tail_lines"],
        ),
        _fn(
            "inspect_service",
            "Trace a Service to its EndpointSlices, legacy Endpoints, matching Pods, and Events.",
            {"name": {"type": "string"}},
            ["name"],
        ),
        _fn(
            "inspect_ingress",
            "Trace an Ingress through its IngressClass and backend Services to endpoints and Pods.",
            {"name": {"type": "string"}},
            ["name"],
        ),
        _fn(
            "inspect_pvc",
            "Inspect a PVC, its StorageClass and Events. Bound PV data is returned only when explicitly enabled.",
            {"name": {"type": "string"}},
            ["name"],
        ),
        _fn(
            "inspect_workload",
            "Inspect a workload, its selected Pods, and related Events.",
            {
                "resource": {"type": "string", "enum": sorted(WORKLOAD_RESOURCES)},
                "name": {"type": "string"},
            },
            ["resource", "name"],
        ),
    ]
    if enable_pv_lookup:
        tools.append(
            _fn(
                "list_persistent_volumes_for_namespace",
                "Read only PV objects whose names are referenced by PVCs in the configured target scope.",
                {},
                [],
            )
        )
    return tools
