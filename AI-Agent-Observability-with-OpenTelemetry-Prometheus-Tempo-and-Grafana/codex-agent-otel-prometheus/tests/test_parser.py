import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

from codex_event_parser import parse_codex_event


class ParserTests(unittest.TestCase):
    def test_command_start_is_tool(self):
        event = {
            "type": "item.started",
            "item": {
                "id": "item_1",
                "type": "command_execution",
                "command": "pwd",
            },
        }

        p = parse_codex_event(event)

        self.assertTrue(p.is_tool)
        self.assertTrue(p.is_started)
        self.assertEqual(p.tool_type, "shell")
        self.assertEqual(p.item_id, "item_1")

    def test_denied_tool(self):
        event = {
            "type": "item.completed",
            "item": {
                "id": "item_2",
                "type": "command_execution",
                "result": "sandbox denial: permission denied",
            },
        }

        p = parse_codex_event(event)

        self.assertTrue(p.is_tool)
        self.assertTrue(p.is_completed)
        self.assertTrue(p.looks_denied)

    def test_usage_extraction(self):
        event = {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 1200,
                "output_tokens": 340,
            },
        }

        p = parse_codex_event(event)

        self.assertEqual(p.input_tokens, 1200)
        self.assertEqual(p.output_tokens, 340)


if __name__ == "__main__":
    unittest.main()
