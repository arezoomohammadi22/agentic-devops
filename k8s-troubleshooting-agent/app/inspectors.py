from __future__ import annotations

from typing import Any

from app.k8s_gateway import KubernetesGateway
from app.policy import validate_name, validate_workload_resource

_KIND_FOR_RESOURCE = {
    "deployments": "Deployment",
    "replicasets": "ReplicaSet",
    "statefulsets": "StatefulSet",
    "daemonsets": "DaemonSet",
    "jobs": "Job",
    "cronjobs": "CronJob",
}


class InspectorService:
    def __init__(self, gateway: KubernetesGateway, enable_pv_lookup: bool = False):
        self.gateway = gateway
        self.enable_pv_lookup = enable_pv_lookup

    def inspect_pod(self, name: str, include_logs: bool, container: str | None, tail_lines: int) -> dict[str, Any]:
        name = validate_name(name)
        result: dict[str, Any] = {
            "pod": self.gateway.get_resource("pods", name),
            "events": self.gateway.list_events("Pod", name),
        }
        if include_logs:
            result["logs"] = self.gateway.read_pod_logs(name, container=container, tail_lines=tail_lines)
        return result

    def inspect_service(self, name: str) -> dict[str, Any]:
        name = validate_name(name)
        service = self.gateway.get_resource("services", name)
        selector = ((service.get("spec") or {}).get("selector") or {})
        label_selector = _selector_to_query(selector) if selector else None

        slices = [
            item
            for item in self.gateway.list_resource("endpointslices")
            if ((item.get("metadata") or {}).get("labels") or {}).get("kubernetes.io/service-name") == name
        ]
        legacy = [
            item
            for item in self.gateway.list_resource("endpoints")
            if (item.get("metadata") or {}).get("name") == name
        ]
        matching_pods = self.gateway.list_resource("pods", label_selector=label_selector) if label_selector else []
        return {
            "service": service,
            "endpoint_slices": slices,
            "legacy_endpoints": legacy,
            "matching_pods": matching_pods,
            "events": self.gateway.list_events("Service", name),
        }

    def inspect_ingress(self, name: str) -> dict[str, Any]:
        name = validate_name(name)
        ingress = self.gateway.get_resource("ingresses", name)
        spec = ingress.get("spec") or {}
        class_name = spec.get("ingressClassName")
        ingress_class = None
        if class_name:
            ingress_class = next(
                (item for item in self.gateway.list_resource("ingressclasses") if (item.get("metadata") or {}).get("name") == class_name),
                None,
            )

        service_names = _ingress_service_names(spec)
        backend_services = []
        for service_name in service_names:
            try:
                backend_services.append(self.inspect_service(service_name))
            except Exception as exc:
                backend_services.append({"service_name": service_name, "error": str(exc)})

        return {
            "ingress": ingress,
            "ingress_class": ingress_class,
            "backend_services": backend_services,
            "events": self.gateway.list_events("Ingress", name),
        }

    def inspect_pvc(self, name: str) -> dict[str, Any]:
        name = validate_name(name)
        pvc = self.gateway.get_resource("persistentvolumeclaims", name)
        spec = pvc.get("spec") or {}
        storage_class_name = spec.get("storageClassName")
        storage_class = None
        if storage_class_name:
            storage_class = next(
                (item for item in self.gateway.list_resource("storageclasses") if (item.get("metadata") or {}).get("name") == storage_class_name),
                None,
            )

        pv = None
        if self.enable_pv_lookup and spec.get("volumeName"):
            pv = self.gateway.read_persistent_volume(spec["volumeName"])

        return {
            "pvc": pvc,
            "storage_class": storage_class,
            "persistent_volume": pv,
            "events": self.gateway.list_events("PersistentVolumeClaim", name),
        }

    def inspect_workload(self, resource: str, name: str) -> dict[str, Any]:
        resource = validate_workload_resource(resource)
        name = validate_name(name)
        workload = self.gateway.get_resource(resource, name)
        selector = (((workload.get("spec") or {}).get("selector") or {}).get("matchLabels") or {})
        pods = self.gateway.list_resource("pods", label_selector=_selector_to_query(selector)) if selector else []
        return {
            "workload": workload,
            "pods": pods,
            "events": self.gateway.list_events(_KIND_FOR_RESOURCE[resource], name),
        }

    def list_persistent_volumes_for_namespace(self) -> dict[str, Any]:
        if not self.enable_pv_lookup:
            raise PermissionError("PersistentVolume lookup is disabled")
        pvcs = self.gateway.list_resource("persistentvolumeclaims")
        volume_names = sorted({
            ((pvc.get("spec") or {}).get("volumeName"))
            for pvc in pvcs
            if ((pvc.get("spec") or {}).get("volumeName"))
        })
        return {
            "pvcs": pvcs,
            "persistent_volumes": [self.gateway.read_persistent_volume(name) for name in volume_names],
        }


def _selector_to_query(selector: dict[str, str]) -> str:
    return ",".join(f"{key}={value}" for key, value in sorted(selector.items()))


def _ingress_service_names(spec: dict[str, Any]) -> list[str]:
    names: list[str] = []
    default_backend = (spec.get("defaultBackend") or {}).get("service") or {}
    if default_backend.get("name"):
        names.append(default_backend["name"])

    for rule in spec.get("rules") or []:
        for path in ((rule.get("http") or {}).get("paths") or []):
            service = ((path.get("backend") or {}).get("service") or {})
            if service.get("name"):
                names.append(service["name"])
    return list(dict.fromkeys(names))
