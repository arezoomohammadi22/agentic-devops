from types import SimpleNamespace

from app.agent import KubernetesTroubleshootingAgent


class FakeResponses:
    def __init__(self):
        self.calls = []
        self.n = 0

    def create(self, **kwargs):
        self.calls.append(kwargs)
        self.n += 1
        if self.n == 1:
            return SimpleNamespace(
                id="resp_1",
                output=[
                    SimpleNamespace(
                        type="function_call",
                        name="list_resources",
                        arguments='{"resource":"pods"}',
                        call_id="call_1",
                    )
                ],
                output_text="",
            )
        return SimpleNamespace(id="resp_2", output=[], output_text="All pods are Running.")


class FakeOpenAIClient:
    def __init__(self):
        self.responses = FakeResponses()


class FakeRegistry:
    def execute(self, name, arguments):
        assert name == "list_resources"
        assert arguments == {"resource": "pods"}
        return {"count": 1, "items": [{"metadata": {"name": "web"}, "status": {"phase": "Running"}}]}


def test_agent_executes_function_call_and_returns_final_text():
    client = FakeOpenAIClient()
    agent = KubernetesTroubleshootingAgent(
        client=client,
        registry=FakeRegistry(),
        tools=[{"type": "function", "name": "list_resources", "parameters": {"type": "object"}}],
        model="test-model",
        target_namespace="agent-lab",
        max_tool_rounds=4,
    )

    answer = agent.run("What is running?")

    assert answer == "All pods are Running."
    second_call = client.responses.calls[1]
    assert second_call["previous_response_id"] == "resp_1"
    assert second_call["input"][0]["type"] == "function_call_output"
    assert second_call["input"][0]["call_id"] == "call_1"
