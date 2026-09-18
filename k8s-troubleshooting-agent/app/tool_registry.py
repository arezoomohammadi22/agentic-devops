from __future__ import annotations

from typing import Any, Callable

from app.inspectors import InspectorService
from app.k8s_gateway import KubernetesGateway
from app.policy import (
    validate_name,
    validate_resource,
    validate_tail_lines,
    validate_workload_resource,
    require_exact_arguments,
)


class ToolRegistry:
    def __init__(self, gateway: KubernetesGateway, inspectors: InspectorService, enable_pv_lookup: bool):
        self.gateway = gateway
        self.inspectors = inspectors
        self.enable_pv_lookup = enable_pv_lookup
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            "list_resources": self._list_resources,
            "get_resource": self._get_resource,
            "get_pod_logs": self._get_pod_logs,
            "get_events": self._get_events,
            "inspect_pod": self._inspect_pod,
            "inspect_service": self._inspect_service,
            "inspect_ingress": self._inspect_ingress,
            "inspect_pvc": self._inspect_pvc,
            "inspect_workload": self._inspect_workload,
        }
        if enable_pv_lookup:
            self._handlers["list_persistent_volumes_for_namespace"] = self._list_pvs

    def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        try:
            handler = self._handlers.get(name)
            if handler is None:
                raise ValueError(f"Unknown or disabled tool: {name}")
            return handler(arguments)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "tool": name}

    def _list_resources(self, args: dict[str, Any]) -> dict[str, Any]:
        require_exact_arguments(args, {"resource"})
        resource = validate_resource(args["resource"])
        items = self.gateway.list_resource(resource)
        return {
            "ok": True,
            "target_namespace": self.gateway.target_namespace,
            "resource": resource,
            "count": len(items),
            "items": items,
        }

    def _get_resource(self, args: dict[str, Any]) -> dict[str, Any]:
        require_exact_arguments(args, {"resource", "name"})
        resource = validate_resource(args["resource"])
        name = validate_name(args["name"])
        return {"ok": True, "resource": resource, "item": self.gateway.get_resource(resource, name)}

    def _get_pod_logs(self, args: dict[str, Any]) -> dict[str, Any]:
        require_exact_arguments(args, {"pod_name", "container", "tail_lines"})
        pod_name = validate_name(args["pod_name"])
        container = args["container"]
        if container is not None:
            container = validate_name(container)
        tail_lines = validate_tail_lines(args["tail_lines"])
        return {
            "ok": True,
            "pod": pod_name,
            "container": container,
            "logs": self.gateway.read_pod_logs(pod_name, container=container, tail_lines=tail_lines),
        }

    def _get_events(self, args: dict[str, Any]) -> dict[str, Any]:
        require_exact_arguments(args, {"kind", "name"})
        kind, name = args["kind"], args["name"]
        if (kind is None) != (name is None):
            raise ValueError("kind and name must either both be null or both be set")
        if name is not None:
            validate_name(name)
        events = self.gateway.list_events(kind, name)
        return {"ok": True, "count": len(events), "items": events}

    def _inspect_pod(self, args: dict[str, Any]) -> dict[str, Any]:
        require_exact_arguments(args, {"name", "include_logs", "container", "tail_lines"})
        name = validate_name(args["name"])
        container = args["container"]
        if container is not None:
            container = validate_name(container)
        tail_lines = validate_tail_lines(args["tail_lines"])
        return self.inspectors.inspect_pod(name, bool(args["include_logs"]), container, tail_lines)

    def _inspect_service(self, args: dict[str, Any]) -> dict[str, Any]:
        require_exact_arguments(args, {"name"})
        return self.inspectors.inspect_service(validate_name(args["name"]))

    def _inspect_ingress(self, args: dict[str, Any]) -> dict[str, Any]:
        require_exact_arguments(args, {"name"})
        return self.inspectors.inspect_ingress(validate_name(args["name"]))

    def _inspect_pvc(self, args: dict[str, Any]) -> dict[str, Any]:
        require_exact_arguments(args, {"name"})
        return self.inspectors.inspect_pvc(validate_name(args["name"]))

    def _inspect_workload(self, args: dict[str, Any]) -> dict[str, Any]:
        require_exact_arguments(args, {"resource", "name"})
        return self.inspectors.inspect_workload(validate_workload_resource(args["resource"]), validate_name(args["name"]))

    def _list_pvs(self, args: dict[str, Any]) -> dict[str, Any]:
        require_exact_arguments(args, set())
        return self.inspectors.list_persistent_volumes_for_namespace()
