from __future__ import annotations

from typing import Any, Protocol


class KubernetesGateway(Protocol):
    target_namespace: str

    def list_resource(self, resource: str, label_selector: str | None = None) -> list[dict[str, Any]]: ...
    def get_resource(self, resource: str, name: str) -> dict[str, Any]: ...
    def read_pod_logs(self, pod_name: str, container: str | None = None, tail_lines: int = 100) -> str: ...
    def list_events(self, kind: str | None = None, name: str | None = None) -> list[dict[str, Any]]: ...
    def read_persistent_volume(self, name: str) -> dict[str, Any]: ...


class RealKubernetesGateway:
    """Typed Kubernetes API wrapper with a fixed target scope."""

    def __init__(self, target_namespace: str, local_kubeconfig: bool = False):
        try:
            from kubernetes import client, config
        except ImportError as exc:
            raise RuntimeError("Install the 'kubernetes' Python package") from exc

        if local_kubeconfig:
            config.load_kube_config()
        else:
            config.load_incluster_config()

        self.target_namespace = target_namespace
        self._client = client
        self._api_client = client.ApiClient()
        self._core = client.CoreV1Api()
        self._apps = client.AppsV1Api()
        self._networking = client.NetworkingV1Api()
        self._discovery = client.DiscoveryV1Api()
        self._batch = client.BatchV1Api()
        self._autoscaling = client.AutoscalingV2Api()
        self._policy = client.PolicyV1Api()
        self._storage = client.StorageV1Api()

    def _clean(self, value: Any) -> Any:
        data = self._api_client.sanitize_for_serialization(value)
        return _compact(data)

    def _items(self, result: Any) -> list[dict[str, Any]]:
        return [self._clean(item) for item in (result.items or [])]

    def list_resource(self, resource: str, label_selector: str | None = None) -> list[dict[str, Any]]:
        ns = self.target_namespace
        kwargs: dict[str, Any] = {"limit": 200}
        if label_selector:
            kwargs["label_selector"] = label_selector

        if resource == "pods":
            return self._items(self._core.list_namespaced_pod(ns, **kwargs))
        if resource == "services":
            return self._items(self._core.list_namespaced_service(ns, **kwargs))
        if resource == "endpoints":
            return self._items(self._core.list_namespaced_endpoints(ns, **kwargs))
        if resource == "persistentvolumeclaims":
            return self._items(self._core.list_namespaced_persistent_volume_claim(ns, **kwargs))
        if resource == "configmaps":
            return self._items(self._core.list_namespaced_config_map(ns, **kwargs))
        if resource == "resourcequotas":
            return self._items(self._core.list_namespaced_resource_quota(ns, **kwargs))
        if resource == "limitranges":
            return self._items(self._core.list_namespaced_limit_range(ns, **kwargs))
        if resource == "events":
            return self.list_events()
        if resource == "deployments":
            return self._items(self._apps.list_namespaced_deployment(ns, **kwargs))
        if resource == "replicasets":
            return self._items(self._apps.list_namespaced_replica_set(ns, **kwargs))
        if resource == "statefulsets":
            return self._items(self._apps.list_namespaced_stateful_set(ns, **kwargs))
        if resource == "daemonsets":
            return self._items(self._apps.list_namespaced_daemon_set(ns, **kwargs))
        if resource == "ingresses":
            return self._items(self._networking.list_namespaced_ingress(ns, **kwargs))
        if resource == "networkpolicies":
            return self._items(self._networking.list_namespaced_network_policy(ns, **kwargs))
        if resource == "endpointslices":
            return self._items(self._discovery.list_namespaced_endpoint_slice(ns, **kwargs))
        if resource == "jobs":
            return self._items(self._batch.list_namespaced_job(ns, **kwargs))
        if resource == "cronjobs":
            return self._items(self._batch.list_namespaced_cron_job(ns, **kwargs))
        if resource == "horizontalpodautoscalers":
            return self._items(self._autoscaling.list_namespaced_horizontal_pod_autoscaler(ns, **kwargs))
        if resource == "poddisruptionbudgets":
            return self._items(self._policy.list_namespaced_pod_disruption_budget(ns, **kwargs))
        if resource == "ingressclasses":
            return self._items(self._networking.list_ingress_class(limit=200))
        if resource == "storageclasses":
            return self._items(self._storage.list_storage_class(limit=200))
        raise ValueError(f"Unsupported resource: {resource}")

    def get_resource(self, resource: str, name: str) -> dict[str, Any]:
        ns = self.target_namespace
        if resource == "pods":
            obj = self._core.read_namespaced_pod(name, ns)
        elif resource == "services":
            obj = self._core.read_namespaced_service(name, ns)
        elif resource == "endpoints":
            obj = self._core.read_namespaced_endpoints(name, ns)
        elif resource == "persistentvolumeclaims":
            obj = self._core.read_namespaced_persistent_volume_claim(name, ns)
        elif resource == "configmaps":
            obj = self._core.read_namespaced_config_map(name, ns)
        elif resource == "events":
            obj = self._core.read_namespaced_event(name, ns)
        elif resource == "resourcequotas":
            obj = self._core.read_namespaced_resource_quota(name, ns)
        elif resource == "limitranges":
            obj = self._core.read_namespaced_limit_range(name, ns)
        elif resource == "deployments":
            obj = self._apps.read_namespaced_deployment(name, ns)
        elif resource == "replicasets":
            obj = self._apps.read_namespaced_replica_set(name, ns)
        elif resource == "statefulsets":
            obj = self._apps.read_namespaced_stateful_set(name, ns)
        elif resource == "daemonsets":
            obj = self._apps.read_namespaced_daemon_set(name, ns)
        elif resource == "ingresses":
            obj = self._networking.read_namespaced_ingress(name, ns)
        elif resource == "networkpolicies":
            obj = self._networking.read_namespaced_network_policy(name, ns)
        elif resource == "endpointslices":
            obj = self._discovery.read_namespaced_endpoint_slice(name, ns)
        elif resource == "jobs":
            obj = self._batch.read_namespaced_job(name, ns)
        elif resource == "cronjobs":
            obj = self._batch.read_namespaced_cron_job(name, ns)
        elif resource == "horizontalpodautoscalers":
            obj = self._autoscaling.read_namespaced_horizontal_pod_autoscaler(name, ns)
        elif resource == "poddisruptionbudgets":
            obj = self._policy.read_namespaced_pod_disruption_budget(name, ns)
        elif resource == "ingressclasses":
            obj = self._networking.read_ingress_class(name)
        elif resource == "storageclasses":
            obj = self._storage.read_storage_class(name)
        else:
            raise ValueError(f"Unsupported get resource: {resource}")
        return self._clean(obj)

    def read_pod_logs(self, pod_name: str, container: str | None = None, tail_lines: int = 100) -> str:
        return self._core.read_namespaced_pod_log(
            name=pod_name,
            namespace=self.target_namespace,
            container=container,
            tail_lines=tail_lines,
            timestamps=True,
        )

    def list_events(self, kind: str | None = None, name: str | None = None) -> list[dict[str, Any]]:
        selector = None
        if kind and name:
            selector = f"involvedObject.kind={kind},involvedObject.name={name}"
        result = self._core.list_namespaced_event(
            namespace=self.target_namespace,
            field_selector=selector,
            limit=200,
        )
        return self._items(result)

    def read_persistent_volume(self, name: str) -> dict[str, Any]:
        return self._clean(self._core.read_persistent_volume(name))


def _compact(value: Any) -> Any:
    if isinstance(value, list):
        return [_compact(item) for item in value]
    if not isinstance(value, dict):
        return value

    result = {key: _compact(item) for key, item in value.items()}
    metadata = result.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("managedFields", None)
        annotations = metadata.get("annotations")
        if isinstance(annotations, dict):
            annotations.pop("kubectl.kubernetes.io/last-applied-configuration", None)
            if not annotations:
                metadata.pop("annotations", None)
    return result
