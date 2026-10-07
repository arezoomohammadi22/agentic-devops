from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


TOOL_ITEM_TYPES = {
    "command_execution",
    "mcp_tool_call",
    "custom_tool_call",
    "collab_tool_call",
    "web_search",
    "file_change",
}


@dataclass
class ParsedEvent:
    event_type: str
    item_id: Optional[str] = None
    item_type: Optional[str] = None
    tool_type: Optional[str] = None
    is_tool: bool = False
    is_started: bool = False
    is_completed: bool = False
    is_error: bool = False
    looks_denied: bool = False
    input_tokens: int = 0
    output_tokens: int = 0


def _text_blob(value: Any, limit: int = 20_000) -> str:
    """Flatten enough event content to classify failures/denials without logging secrets as labels."""
    parts: list[str] = []

    def walk(node: Any) -> None:
        if sum(len(p) for p in parts) >= limit:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                # Keep values for classification only. Nothing is emitted as a metric label.
                if isinstance(v, (str, int, float, bool)):
                    parts.append(f"{k}={v}")
                else:
                    walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, (str, int, float, bool)):
            parts.append(str(node))

    walk(value)
    return " ".join(parts)[:limit].lower()


def _find_usage(node: Any) -> tuple[int, int]:
    """
    Best-effort token usage extraction across Codex versions.
    Returns (input_tokens, output_tokens).
    """
    input_total = 0
    output_total = 0

    input_keys = {
        "input_tokens",
        "input_token_count",
        "prompt_tokens",
    }
    output_keys = {
        "output_tokens",
        "output_token_count",
        "completion_tokens",
    }

    def walk(value: Any) -> None:
        nonlocal input_total, output_total

        if isinstance(value, dict):
            for key, child in value.items():
                key_l = str(key).lower()

                if key_l in input_keys and isinstance(child, (int, float)):
                    input_total = max(input_total, int(child))
                elif key_l in output_keys and isinstance(child, (int, float)):
                    output_total = max(output_total, int(child))
                elif isinstance(child, (dict, list)):
                    walk(child)

        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(node)
    return input_total, output_total


def _tool_name(item: dict[str, Any], item_type: str | None) -> str:
    # Keep this deliberately low-cardinality.
    # Exact shell commands are NEVER used as metric labels.
    if item_type == "command_execution":
        return "shell"

    for key in ("tool_name", "name", "tool"):
        value = item.get(key)
        if isinstance(value, str) and value:
            # MCP/custom tool names are normally bounded by the configured tool set.
            return value[:120]

    return item_type or "unknown_tool"


def parse_codex_event(event: dict[str, Any]) -> ParsedEvent:
    event_type = str(event.get("type", "unknown"))
    item = event.get("item")
    if not isinstance(item, dict):
        item = {}

    item_type_raw = item.get("type")
    item_type = str(item_type_raw) if item_type_raw is not None else None
    item_id_raw = item.get("id")
    item_id = str(item_id_raw) if item_id_raw is not None else None

    item_type_l = (item_type or "").lower()

    is_tool = (
        item_type_l in TOOL_ITEM_TYPES
        or "tool" in item_type_l
        or item_type_l == "command_execution"
    )

    is_started = event_type.endswith(".started") or event_type in {
        "item.started",
        "turn.started",
    }
    is_completed = event_type.endswith(".completed") or event_type in {
        "item.completed",
        "turn.completed",
    }

    blob = _text_blob(event)

    error_words = (
        "error",
        "failed",
        "failure",
        "exit_code=1",
        "exit code 1",
    )
    deny_words = (
        "denied",
        "forbidden",
        "not permitted",
        "permission denied",
        "sandbox denial",
        "rejected by policy",
    )

    is_error = (
        event_type == "error"
        or item_type_l == "error"
        or any(word in blob for word in error_words)
    )

    looks_denied = any(word in blob for word in deny_words)

    input_tokens, output_tokens = _find_usage(event)

    return ParsedEvent(
        event_type=event_type,
        item_id=item_id,
        item_type=item_type,
        tool_type=_tool_name(item, item_type) if is_tool else None,
        is_tool=is_tool,
        is_started=is_started,
        is_completed=is_completed,
        is_error=is_error,
        looks_denied=looks_denied,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
