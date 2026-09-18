from __future__ import annotations

import os
from dataclasses import dataclass


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    target_namespace: str
    openai_model: str = "gpt-5.6-sol"
    max_tool_rounds: int = 8
    enable_pv_lookup: bool = False
    local_kubeconfig: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        target = os.getenv("TARGET_NAMESPACE", "").strip()
        if not target:
            raise RuntimeError("TARGET_NAMESPACE must be set")
        return cls(
            target_namespace=target,
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.6-sol").strip(),
            max_tool_rounds=int(os.getenv("MAX_TOOL_ROUNDS", "8")),
            enable_pv_lookup=_as_bool(os.getenv("ENABLE_PV_LOOKUP"), False),
            local_kubeconfig=_as_bool(os.getenv("LOCAL_KUBECONFIG"), False),
        )
