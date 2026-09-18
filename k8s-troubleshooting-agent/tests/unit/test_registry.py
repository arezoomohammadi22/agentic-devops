from app.inspectors import InspectorService
from app.tool_registry import ToolRegistry


class FakeGateway:
    target_namespace = "agent-lab"

    def __init__(self):
        self.calls = []

    def list_resource(self, resource, label_selector=None):
        self.calls.append(("list", resource, label_selector))
        if resource == "pods":
            return [{"metadata": {"name": "web-abc", "labels": {"app": "web"}}, "status": {"phase": "Running"}}]
        return []

    def get_resource(self, resource, name):
        self.calls.append(("get", resource, name))
        return {"metadata": {"name": name}}

    def read_pod_logs(self, pod_name, container=None, tail_lines=100):
        self.calls.append(("logs", pod_name, container, tail_lines))
        return "hello"

    def list_events(self, kind=None, name=None):
        self.calls.append(("events", kind, name))
        return []

    def read_persistent_volume(self, name):
        self.calls.append(("pv", name))
        return {"metadata": {"name": name}}


def test_registry_lists_allowed_resource_without_namespace_input():
    gateway = FakeGateway()
    registry = ToolRegistry(gateway, InspectorService(gateway), enable_pv_lookup=False)

    result = registry.execute("list_resources", {"resource": "pods"})

    assert result["target_namespace"] == "agent-lab"
    assert result["count"] == 1
    assert gateway.calls == [("list", "pods", None)]


def test_registry_rejects_unknown_arguments():
    gateway = FakeGateway()
    registry = ToolRegistry(gateway, InspectorService(gateway), enable_pv_lookup=False)

    result = registry.execute("list_resources", {"resource": "pods", "namespace": "kube-system"})

    assert result["ok"] is False
    assert "unexpected" in result["error"].lower()
    assert gateway.calls == []


def test_registry_rejects_disallowed_resource():
    gateway = FakeGateway()
    registry = ToolRegistry(gateway, InspectorService(gateway), enable_pv_lookup=False)

    result = registry.execute("list_resources", {"resource": "secrets"})

    assert result["ok"] is False
    assert gateway.calls == []
