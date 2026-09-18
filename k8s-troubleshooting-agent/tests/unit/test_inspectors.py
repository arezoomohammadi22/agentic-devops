from app.inspectors import InspectorService


class FakeGateway:
    target_namespace = "agent-lab"

    def list_resource(self, resource, label_selector=None):
        if resource == "endpointslices":
            return [
                {
                    "metadata": {
                        "name": "demo-web-xyz",
                        "labels": {"kubernetes.io/service-name": "demo-web"},
                    },
                    "endpoints": [],
                }
            ]
        if resource == "endpoints":
            return []
        if resource == "pods" and label_selector == "app=missing-label":
            return []
        if resource == "pods":
            return [
                {
                    "metadata": {"name": "demo-web-abc", "labels": {"app": "demo-web"}},
                    "status": {"phase": "Running"},
                }
            ]
        if resource == "ingressclasses":
            return [{"metadata": {"name": "nginx"}}]
        if resource == "storageclasses":
            return [{"metadata": {"name": "standard"}}]
        return []

    def get_resource(self, resource, name):
        if resource == "services" and name == "demo-web":
            return {
                "metadata": {"name": "demo-web"},
                "spec": {"selector": {"app": "missing-label"}, "ports": [{"port": 80, "targetPort": 80}]},
            }
        if resource == "ingresses" and name == "demo":
            return {
                "metadata": {"name": "demo"},
                "spec": {
                    "ingressClassName": "nginx",
                    "rules": [{"http": {"paths": [{"backend": {"service": {"name": "demo-web", "port": {"number": 80}}}}]}}],
                },
            }
        if resource == "persistentvolumeclaims" and name == "data":
            return {
                "metadata": {"name": "data"},
                "spec": {"storageClassName": "standard", "volumeName": "pvc-123"},
                "status": {"phase": "Bound"},
            }
        return {"metadata": {"name": name}}

    def read_pod_logs(self, pod_name, container=None, tail_lines=100):
        return "nginx started"

    def list_events(self, kind=None, name=None):
        return [{"reason": "Example", "message": "example event"}]

    def read_persistent_volume(self, name):
        return {"metadata": {"name": name}, "spec": {"storageClassName": "standard"}}


def test_service_inspection_exposes_selector_and_empty_backend_evidence():
    inspector = InspectorService(FakeGateway())

    result = inspector.inspect_service("demo-web")

    assert result["service"]["spec"]["selector"] == {"app": "missing-label"}
    assert result["matching_pods"] == []
    assert result["endpoint_slices"][0]["endpoints"] == []


def test_ingress_inspection_follows_backend_service():
    inspector = InspectorService(FakeGateway())

    result = inspector.inspect_ingress("demo")

    assert result["ingress_class"]["metadata"]["name"] == "nginx"
    assert result["backend_services"][0]["service"]["metadata"]["name"] == "demo-web"


def test_pvc_inspection_only_reads_pv_when_enabled():
    inspector = InspectorService(FakeGateway(), enable_pv_lookup=True)

    result = inspector.inspect_pvc("data")

    assert result["storage_class"]["metadata"]["name"] == "standard"
    assert result["persistent_volume"]["metadata"]["name"] == "pvc-123"
