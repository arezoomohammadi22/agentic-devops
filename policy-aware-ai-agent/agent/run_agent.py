from __future__ import annotations

import argparse
from pathlib import Path

from codex_client import CodexAgent

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--quiet-codex", action="store_true")
    args = parser.parse_args()

    agent = CodexAgent(ROOT)
    print("Codex:", agent.preflight())
    print("\nRunning task through Codex + secure_agent MCP tools...\n")
    output = agent.run(args.task, verbose=not args.quiet_codex)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
