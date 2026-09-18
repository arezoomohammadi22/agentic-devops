from __future__ import annotations

from functools import lru_cache

from openai import OpenAI

from app.agent import KubernetesTroubleshootingAgent
from app.config import Settings
from app.inspectors import InspectorService
from app.k8s_gateway import RealKubernetesGateway
from app.tool_registry import ToolRegistry
from app.tool_schemas import build_tool_schemas


@lru_cache(maxsize=1)
def build_agent() -> KubernetesTroubleshootingAgent:
    settings = Settings.from_env()
    gateway = RealKubernetesGateway(
        target_namespace=settings.target_namespace,
        local_kubeconfig=settings.local_kubeconfig,
    )
    inspectors = InspectorService(gateway, enable_pv_lookup=settings.enable_pv_lookup)
    registry = ToolRegistry(gateway, inspectors, enable_pv_lookup=settings.enable_pv_lookup)
    return KubernetesTroubleshootingAgent(
        client=OpenAI(),
        registry=registry,
        tools=build_tool_schemas(settings.enable_pv_lookup),
        model=settings.openai_model,
        target_namespace=settings.target_namespace,
        max_tool_rounds=settings.max_tool_rounds,
    )
