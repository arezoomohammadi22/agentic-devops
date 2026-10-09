from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class CodexSettings:
    executable: str = "codex"
    model: str | None = None
    reasoning_effort: str | None = "medium"
    sandbox: str = "read-only"
    ignore_rules: bool = True
    ephemeral: bool = True


class CodexAgent:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        cfg = yaml.safe_load((repo_root / "agent/config.yaml").read_text())
        c = cfg.get("codex", {})
        self.settings = CodexSettings(
            executable=c.get("executable", "codex"),
            model=c.get("model"),
            reasoning_effort=c.get("reasoning_effort"),
            sandbox=c.get("sandbox", "read-only"),
            ignore_rules=bool(c.get("ignore_rules", True)),
            ephemeral=bool(c.get("ephemeral", True)),
        )
        self.workspace = repo_root / "agent/workspace"

    def preflight(self) -> str:
        exe = shutil.which(self.settings.executable)
        if not exe:
            raise RuntimeError("Codex CLI not found in PATH.")

        version = subprocess.run([exe, "--version"], capture_output=True, text=True)
        help_result = subprocess.run([exe, "exec", "--help"], capture_output=True, text=True)
        help_text = (help_result.stdout or "") + (help_result.stderr or "")
        required = ["--sandbox", "--ignore-rules", "--ephemeral"]
        missing = [flag for flag in required if flag not in help_text]
        if missing:
            raise RuntimeError("Codex CLI missing required flags: " + ", ".join(missing))

        mcp_result = subprocess.run([exe, "mcp", "list"], capture_output=True, text=True)
        if mcp_result.returncode != 0:
            raise RuntimeError("Unable to list Codex MCP servers:\n" + mcp_result.stderr)
        if "secure_agent" not in (mcp_result.stdout + mcp_result.stderr):
            raise RuntimeError(
                "The secure_agent MCP server is not configured. "
                "Create agent/workspace/.codex/config.toml or configure ~/.codex/config.toml first."
            )

        return (version.stdout or version.stderr).strip()

    def run(self, task: str, verbose: bool = True) -> str:
        exe = shutil.which(self.settings.executable)
        if not exe:
            raise RuntimeError("Codex CLI not available.")

        prompt = f"""You are the incident-response agent for the secure MCP output-validation lab.

Task:
{task}

Use the secure_agent MCP tools for every Kubernetes observation or action.
Do not use kubectl, shell commands, kubeconfig, or direct Kubernetes API access.
Prefer read-only investigation before write actions unless the task explicitly requires a specific action.
If the Gateway returns approval_required, report the approval ID and stop until a human approves it.
After human approval, use get_approval_status and execute_approved_action; never reconstruct or modify an approved action.
"""

        cmd = [
            exe,
            "exec",
            "--sandbox",
            self.settings.sandbox,
            "--config",
            'approval_policy="never"',
            "--cd",
            str(self.workspace),
            "--skip-git-repo-check",
        ]
        if self.settings.ignore_rules:
            cmd.append("--ignore-rules")
        if self.settings.ephemeral:
            cmd.append("--ephemeral")
        if self.settings.model:
            cmd += ["--model", self.settings.model]
        if self.settings.reasoning_effort:
            cmd += ["--config", f'model_reasoning_effort="{self.settings.reasoning_effort}"']
        cmd.append(prompt)

        result = subprocess.run(cmd, capture_output=True, text=True)
        if verbose and result.stderr.strip():
            print("\n--- Codex activity ---\n" + result.stderr.strip() + "\n--- end Codex activity ---\n")
        if result.returncode != 0:
            raise RuntimeError(f"Codex exited {result.returncode}: {result.stderr}")
        return result.stdout.strip()
