import os

from app.config import Settings


def test_settings_default_to_safe_read_only_pv_behavior(monkeypatch):
    monkeypatch.setenv("TARGET_NAMESPACE", "agent-lab")
    monkeypatch.delenv("ENABLE_PV_LOOKUP", raising=False)
    settings = Settings.from_env()
    assert settings.target_namespace == "agent-lab"
    assert settings.enable_pv_lookup is False
