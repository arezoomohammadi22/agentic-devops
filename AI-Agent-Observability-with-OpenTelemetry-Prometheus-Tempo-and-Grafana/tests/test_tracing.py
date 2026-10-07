from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TraceInstrumentationTests(unittest.TestCase):
    def test_trace_instrumentation_exists(self):
        src = (ROOT / "agent" / "codex_agent_monitor.py").read_text()
        self.assertIn('tracer.start_as_current_span(', src)
        self.assertIn('"codex.run"', src)
        self.assertIn('"codex.turn"', src)
        self.assertIn('f"codex.tool.', src)
        self.assertIn('OTLPSpanExporter', src)

    def test_sensitive_tool_details_are_opt_in(self):
        src = (ROOT / "agent" / "codex_agent_monitor.py").read_text()
        self.assertIn('"--trace-tool-details"', src)
        self.assertIn("if args.trace_tool_details:", src)


if __name__ == "__main__":
    unittest.main()
