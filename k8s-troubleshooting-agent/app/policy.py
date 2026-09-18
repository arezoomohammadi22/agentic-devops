from __future__ import annotations

import re

NAMESPACED_RESOURCES = {
    "pods",
    "services",
    "endpoints",
    "endpointslices",
    "ingresses",
    "deployments",
    "replicasets",
    "statefulsets",
    "daemonsets",
    "jobs",
    "cronjobs",
    "persistentvolumeclaims",
    "configmaps",
    "events",
    "networkpolicies",
    "horizontalpodautoscalers",
    "poddisruptionbudgets",
    "resourcequotas",
    "limitranges",
}

CLUSTER_METADATA_RESOURCES = {"ingressclasses", "storageclasses"}
ALLOWED_RESOURCES = NAMESPACED_RESOURCES | CLUSTER_METADATA_RESOURCES
WORKLOAD_RESOURCES = {"deployments", "replicasets", "statefulsets", "daemonsets", "jobs", "cronjobs"}

_DNS_SUBDOMAIN = re.compile(r"^[a-z0-9]([-a-z0-9.]*[a-z0-9])?$")


def validate_resource(resource: str) -> str:
    if resource not in ALLOWED_RESOURCES:
        raise ValueError(f"Resource '{resource}' is not allowed")
    return resource


def validate_workload_resource(resource: str) -> str:
    if resource not in WORKLOAD_RESOURCES:
        raise ValueError(f"Workload resource '{resource}' is not allowed")
    return resource


def validate_name(name: str) -> str:
    if not isinstance(name, str) or not (1 <= len(name) <= 253) or not _DNS_SUBDOMAIN.fullmatch(name):
        raise ValueError(f"Invalid Kubernetes resource name: {name!r}")
    return name


def validate_tail_lines(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 500:
        raise ValueError("tail_lines must be an integer between 1 and 500")
    return value


def require_exact_arguments(arguments: dict, expected: set[str]) -> None:
    actual = set(arguments)
    unexpected = actual - expected
    missing = expected - actual
    if unexpected:
        raise ValueError(f"Unexpected arguments: {sorted(unexpected)}")
    if missing:
        raise ValueError(f"Missing arguments: {sorted(missing)}")
