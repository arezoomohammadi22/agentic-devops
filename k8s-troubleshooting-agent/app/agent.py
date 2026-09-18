from __future__ import annotations

import json
from typing import Any


class KubernetesTroubleshootingAgent:
    def __init__(
        self,
        *,
        client: Any,
        registry: Any,
        tools: list[dict],
        model: str,
        target_namespace: str,
        max_tool_rounds: int = 8,
    ):
        self.client = client
        self.registry = registry
        self.tools = tools
        self.model = model
        self.target_namespace = target_namespace
        self.max_tool_rounds = max_tool_rounds

    def _instructions(self) -> str:
        return (
            f"You are a read-only Kubernetes troubleshooting agent for target '{self.target_namespace}'. "
            "Use tools before asserting live state. Correlate Ingress->Service->EndpointSlice->Pod and PVC->StorageClass. "
            "Never claim to change resources. State evidence as resource/name and clearly mark uncertainty."
        )

    def run(self, message: str) -> str:
        response = self.client.responses.create(
            model=self.model,
            instructions=self._instructions(),
            input=message,
            tools=self.tools,
            tool_choice="auto",
        )

        for _ in range(self.max_tool_rounds):
            calls = [item for item in response.output if getattr(item, "type", None) == "function_call"]
            if not calls:
                return response.output_text or "No textual response was produced."

            tool_outputs = []
            for call in calls:
                try:
                    args = json.loads(call.arguments or "{}")
                except json.JSONDecodeError as exc:
                    result = {"ok": False, "error": f"Invalid tool JSON: {exc}"}
                else:
                    result = self.registry.execute(call.name, args)

                tool_outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )

            response = self.client.responses.create(
                model=self.model,
                previous_response_id=response.id,
                input=tool_outputs,
                tools=self.tools,
                tool_choice="auto",
            )

        raise RuntimeError(f"Agent exceeded MAX_TOOL_ROUNDS={self.max_tool_rounds}")
