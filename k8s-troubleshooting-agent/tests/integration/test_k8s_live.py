import os

import pytest

from app.config import Settings
from app.k8s_gateway import RealKubernetesGateway

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_K8S_INTEGRATION") != "1",
    reason="Set RUN_K8S_INTEGRATION=1 to query a real cluster",
)


def test_can_read_target_scope_from_real_cluster():
    settings = Settings.from_env()
    gateway = RealKubernetesGateway(settings.target_namespace, local_kubeconfig=settings.local_kubeconfig)
    pods = gateway.list_resource("pods")
    services = gateway.list_resource("services")
    assert isinstance(pods, list)
    assert isinstance(services, list)
