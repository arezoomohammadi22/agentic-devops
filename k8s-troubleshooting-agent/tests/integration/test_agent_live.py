import os

import pytest

if not (os.getenv("RUN_K8S_INTEGRATION") == "1" and os.getenv("RUN_LLM_INTEGRATION") == "1"):
    pytest.skip(
        "Set RUN_K8S_INTEGRATION=1 and RUN_LLM_INTEGRATION=1 for the live agent test",
        allow_module_level=True,
    )

from app.bootstrap import build_agent


def test_live_agent_can_investigate_without_mutating():
    answer = build_agent().run(
        "Inspect the current target and summarize Pods, Services, and any obvious endpoint problems. Do not change anything."
    )
    assert isinstance(answer, str)
    assert len(answer.strip()) > 20
