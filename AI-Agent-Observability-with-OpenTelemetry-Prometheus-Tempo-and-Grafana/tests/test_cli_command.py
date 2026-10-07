from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class CliCommandTests(unittest.TestCase):
    def test_approval_flag_is_not_post_exec_global_flag(self):
        src = (ROOT / "agent" / "codex_agent_monitor.py").read_text()
        self.assertNotIn('"--ask-for-approval",\\n        "never"', src)
        self.assertIn('approval_policy="never"', src)
        self.assertIn('"--cd"', src)

if __name__ == "__main__":
    unittest.main()
