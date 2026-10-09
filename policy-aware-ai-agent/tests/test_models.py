import pytest
from pydantic import ValidationError
from gateway.app.models import ProposedAction
from gateway.app.security import action_hash

def test_valid_restart():
    a=ProposedAction(tool="restart_deployment",namespace="agent-lab-staging",
                     resource_kind="deployment",resource="demo-api",reason="unhealthy")
    assert a.tool=="restart_deployment"

def test_extra_field_rejected():
    with pytest.raises(ValidationError):
        ProposedAction.model_validate({"tool":"restart_deployment","namespace":"agent-lab-staging",
          "resource_kind":"deployment","resource":"demo-api","reason":"x","command":"rm -rf /"})

def test_wrong_kind_rejected():
    with pytest.raises(ValidationError):
        ProposedAction(tool="restart_deployment",namespace="agent-lab-staging",
                       resource_kind="namespace",resource="demo-api",reason="x")

def test_hash_stable():
    a=ProposedAction(tool="restart_deployment",namespace="agent-lab-production",
                     resource_kind="deployment",resource="demo-api",reason="x")
    b=ProposedAction.model_validate(a.model_dump())
    assert action_hash(a)==action_hash(b)

def test_hash_changes():
    a=ProposedAction(tool="restart_deployment",namespace="agent-lab-production",
                     resource_kind="deployment",resource="demo-api",reason="x")
    b=ProposedAction(tool="restart_deployment",namespace="agent-lab-production",
                     resource_kind="deployment",resource="database",reason="x")
    assert action_hash(a)!=action_hash(b)
