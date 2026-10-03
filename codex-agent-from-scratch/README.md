# Building a Simple AI Agent with Codex CLI

## A Practical Walkthrough of Agent Harness, Tool Calling, Context, State, and the Agent Loop

This document builds a small but complete AI agent around the Codex CLI. The goal is not to create a production-ready agent, but to make the internal architecture of an agent visible enough that every important concept can be demonstrated live during a class.

The project intentionally separates the **model** from the **harness**. Codex is used as the decision-making component, while Python is responsible for the actual tools, tool execution, state, context construction, guardrails, and the agent loop.

This gives us a concrete implementation of the architecture discussed conceptually in the previous lesson:

```text
User Goal
   |
   v
Python Harness
   |
   v
Build Context
   |
   v
Codex
   |
   +---- tool_call ----> Python executes the tool
   |                         |
   |                         v
   |                    Tool Result
   |                         |
   +----------- Context <----+
   |
   +---- final ---------> Stop
```

The most important idea in this lesson is simple:

> The model decides what should happen next, but the harness performs the real action.

---

# 1. What We Are Building

We are going to build a small diagnostic agent that investigates why an API service cannot connect to Redis.

The environment intentionally contains a configuration problem:

- The API configuration expects Redis to be available at hostname `redis`.
- The Docker Compose service is actually named `cache`.
- The application log shows `ENOTFOUND redis`.

The agent does not know this in advance. It must discover the problem by using tools.

The agent will have only three tools:

```text
list_files(path)
read_file(path)
grep_file(path, pattern)
```

It will not receive unrestricted shell access.

This is important because we want the agent to operate through a controlled tool surface rather than having arbitrary access to the machine.

---

# 2. Why We Use Codex CLI Instead of an API Key

For this example, we assume Codex CLI is already installed and authenticated using the user's ChatGPT account.

Python does not call the OpenAI API directly.

Instead, Python runs:

```bash
codex exec
```

as a subprocess.

Codex therefore acts as the decision engine inside our custom harness.

This architecture is useful for teaching because it lets us build the important agent components ourselves while still using Codex for reasoning.

The high-level structure is:

```text
Python
  |
  +--> codex exec
  |       |
  |       +--> decides the next action
  |
  +--> validates that decision
  |
  +--> executes a Python tool
  |
  +--> stores the tool result
  |
  +--> calls Codex again
```

---

# 3. Project Structure

Create the following directory structure:

```text
simple-codex-agent/
├── agent.py
├── decision-schema.json
├── README.md
└── demo_workspace/
    ├── compose.yaml
    ├── config/
    │   └── app.env
    └── logs/
        └── api.log
```

The important distinction is that `demo_workspace/` is the environment that the agent is allowed to inspect.

The rest of the project belongs to the harness itself.

---

# 4. Requirements

You need:

- Python 3.10 or newer
- Codex CLI
- Codex authenticated with your ChatGPT account

Check Python:

```bash
python3 --version
```

Check Codex:

```bash
codex --version
```

Check authentication:

```bash
codex login status
```

If Codex is not authenticated, run:

```bash
codex
```

and sign in with your ChatGPT account.

Before continuing, verify that non-interactive Codex execution works:

```bash
codex exec --skip-git-repo-check "Reply only with: CODEX_OK"
```

Expected result:

```text
CODEX_OK
```

If this simple test does not work, fix Codex authentication before debugging the Python agent.

---

# 5. Create the Demo Environment

The agent needs a small environment to investigate.

Create the directories:

```bash
mkdir -p simple-codex-agent/demo_workspace/config
mkdir -p simple-codex-agent/demo_workspace/logs
cd simple-codex-agent
```

---

# 6. Create the Application Configuration

Create:

```text
demo_workspace/config/app.env
```

with this content:

```text
APP_PORT=8080
REDIS_HOST=redis
REDIS_PORT=6379
```

This configuration contains the hostname the application will try to resolve.

At this point, nothing looks obviously wrong unless we compare it with the Compose service definition.

---

# 7. Create the Docker Compose File

Create:

```text
demo_workspace/compose.yaml
```

with:

```yaml
services:

  api:
    image: demo-api:latest
    env_file:
      - ./config/app.env
    depends_on:
      - cache

  cache:
    image: redis:7-alpine
```

Notice the important detail:

```yaml
cache:
```

The Redis service is named `cache`, not `redis`.

Inside a Docker Compose network, services are normally reachable through their service names, so the application configuration and the Compose service name do not match.

---

# 8. Create the Application Log

Create:

```text
demo_workspace/logs/api.log
```

with:

```text
2026-10-03T10:10:01Z INFO  starting api service
2026-10-03T10:10:02Z INFO  connecting to redis:6379
2026-10-03T10:10:02Z ERROR redis connection failed
2026-10-03T10:10:02Z ERROR getaddrinfo ENOTFOUND redis
2026-10-03T10:10:05Z INFO  retrying redis connection
2026-10-03T10:10:05Z ERROR getaddrinfo ENOTFOUND redis
```

Now our environment contains three pieces of evidence:

1. The application tries to connect to `redis`.
2. Name resolution for `redis` fails.
3. The actual Redis service is named `cache`.

The agent must collect these observations before producing a final answer.

---

# 9. Define the Tool-Call Contract

A model can generate natural language, but a harness needs structured data that it can validate and execute.

We therefore define a JSON schema.

Create:

```text
decision-schema.json
```

with:

```json
{
  "type": "object",
  "properties": {
    "kind": {
      "type": "string",
      "enum": ["tool_call", "final"]
    },
    "tool": {
      "type": "string",
      "enum": ["list_files", "read_file", "grep_file", "none"]
    },
    "path": {
      "type": "string"
    },
    "pattern": {
      "type": "string"
    },
    "answer": {
      "type": "string"
    },
    "note": {
      "type": "string"
    }
  },
  "required": [
    "kind",
    "tool",
    "path",
    "pattern",
    "answer",
    "note"
  ],
  "additionalProperties": false
}
```

This schema becomes the contract between Codex and our Python harness.

Codex is only allowed to return one of two high-level decisions:

```text
tool_call
```

or:

```text
final
```

A tool request might look like this:

```json
{
  "kind": "tool_call",
  "tool": "read_file",
  "path": "logs/api.log",
  "pattern": "",
  "answer": "",
  "note": "I need to inspect the application log."
}
```

A final response might look like this:

```json
{
  "kind": "final",
  "tool": "none",
  "path": "",
  "pattern": "",
  "answer": "The API is configured with the wrong Redis hostname.",
  "note": "The available evidence is sufficient."
}
```

This distinction is central to the agent architecture.

A `tool_call` is not the action itself.

It is only a request from the model to the harness.

---

# 10. Start Building the Harness

Create:

```text
agent.py
```

We begin by importing only Python standard-library modules:

```python
import json
import os
import subprocess
import sys
from pathlib import Path
```

No external Python package is required.

Now define the main paths:

```python
BASE_DIR = Path(__file__).resolve().parent
WORKSPACE = (BASE_DIR / "demo_workspace").resolve()
RUNTIME_DIR = (BASE_DIR / ".agent_runtime").resolve()
SCHEMA_FILE = BASE_DIR / "decision-schema.json"

MAX_STEPS = 10

RUNTIME_DIR.mkdir(exist_ok=True)
```

The important directories are:

```text
WORKSPACE
```

which contains the environment the agent may inspect, and:

```text
RUNTIME_DIR
```

which contains temporary files used by the harness when communicating with Codex.

---

# 11. Authentication Environment

Create this function:

```python
def codex_environment() -> dict:
    env = os.environ.copy()

    env.pop("OPENAI_API_KEY", None)
    env.pop("CODEX_API_KEY", None)

    return env
```

The purpose of this function is to make the demonstration use the existing Codex login instead of accidentally inheriting an API key from the shell environment.

This is an important architectural detail because our Python program is not authenticating directly with the OpenAI API. It is delegating authentication to the installed Codex CLI.

---

# 12. Verify Codex Authentication

Add:

```python
def verify_codex_login() -> None:
    result = subprocess.run(
        ["codex", "login", "status"],
        capture_output=True,
        text=True,
        env=codex_environment()
    )

    output = (result.stdout + "\n" + result.stderr).strip()

    if result.returncode != 0:
        raise RuntimeError(
            "Codex is not authenticated.\n"
            + output
        )

    print("\nAUTH")
    print(output)
```

This function does not create the login.

It only verifies that Codex authentication is already available before the agent loop starts.

That separation is useful because authentication is infrastructure configuration, not an agent decision.

---

# 13. Add a Workspace Guardrail

The first real safety mechanism in our agent is path isolation.

Add:

```python
def safe_path(relative_path: str) -> Path:
    relative_path = relative_path or "."
    candidate = (WORKSPACE / relative_path).resolve()

    if candidate != WORKSPACE and WORKSPACE not in candidate.parents:
        raise ValueError("Path escapes the allowed workspace")

    return candidate
```

This function ensures that a path requested by the model stays inside `demo_workspace`.

For example, if the model requests:

```text
logs/api.log
```

the path is allowed.

If the model requests something like:

```text
../../.ssh/id_rsa
```

the resolved path would escape the workspace, so the harness rejects it.

This demonstrates an important security rule:

> Guardrails should be enforced outside the model whenever possible.

We should not rely only on a prompt that says "do not read sensitive files."

The runtime should make that action impossible.

---

# 14. Implement the `list_files` Tool

Add:

```python
def list_files(path: str) -> str:
    target = safe_path(path)

    if not target.exists():
        return f"ERROR: path does not exist: {path}"

    if not target.is_dir():
        return f"ERROR: path is not a directory: {path}"

    entries = []

    for item in sorted(target.iterdir()):
        name = item.name + ("/" if item.is_dir() else "")
        entries.append(name)

    return "\n".join(entries[:100])
```

This is the real implementation of the first tool.

The model never executes `Path.iterdir()`.

The Python harness does.

From the model's point of view, the tool is simply described as:

```text
list_files(path)
```

This separation between tool description and tool implementation is one of the fundamental properties of agent systems.

---

# 15. Implement the `read_file` Tool

Add:

```python
def read_file(path: str) -> str:
    target = safe_path(path)

    if not target.exists():
        return f"ERROR: file does not exist: {path}"

    if not target.is_file():
        return f"ERROR: path is not a file: {path}"

    content = target.read_text(
        encoding="utf-8",
        errors="replace"
    )

    max_chars = 12000

    if len(content) > max_chars:
        content = content[:max_chars] + "\n...[truncated]"

    return content
```

This function introduces another important guardrail.

The agent cannot load an unlimited amount of text from a file into context.

The tool truncates large content.

This demonstrates that tool design and context management are connected.

Every tool result may eventually become part of the model context, so unbounded tool output can quickly become a context problem.

---

# 16. Implement the `grep_file` Tool

Add:

```python
def grep_file(path: str, pattern: str) -> str:
    target = safe_path(path)

    if not target.exists():
        return f"ERROR: path does not exist: {path}"

    pattern_lower = pattern.lower()
    matches = []

    if target.is_file():
        files = [target]
    else:
        files = [
            item
            for item in target.rglob("*")
            if item.is_file()
        ]

    for file_path in files:
        try:
            content = file_path.read_text(
                encoding="utf-8",
                errors="replace"
            )
        except Exception:
            continue

        for line_number, line in enumerate(
            content.splitlines(),
            start=1
        ):
            if pattern_lower in line.lower():
                relative = file_path.relative_to(WORKSPACE)

                matches.append(
                    f"{relative}:{line_number}: {line}"
                )

                if len(matches) >= 50:
                    return "\n".join(matches)

    if not matches:
        return "NO MATCHES"

    return "\n".join(matches)
```

This gives the agent a controlled search capability.

Again, the model does not directly walk the filesystem.

The harness does.

---

# 17. Create the Tool Dispatcher

The model returns a tool name as structured data.

We still need code that maps that name to the correct Python function.

Add:

```python
def execute_tool(decision: dict) -> str:
    tool = decision["tool"]

    try:
        if tool == "list_files":
            return list_files(
                decision["path"]
            )

        if tool == "read_file":
            return read_file(
                decision["path"]
            )

        if tool == "grep_file":
            return grep_file(
                decision["path"],
                decision["pattern"]
            )

        return f"ERROR: unknown tool: {tool}"

    except Exception as exc:
        return f"ERROR: {exc}"
```

This is the tool-dispatch layer.

The model may request a tool, but the harness decides whether that tool exists and how it is executed.

This is where a production system could also add:

- authorization
- approval requirements
- audit logging
- rate limits
- policy checks
- per-tool sandboxing

---

# 18. Build the Context for Codex

Now we need to construct the prompt that Codex receives on each step.

Add:

```python
def build_prompt(
    goal: str,
    history: list[dict]
) -> str:

    history_json = json.dumps(
        history,
        ensure_ascii=False,
        indent=2
    )

    return f"""
You are the decision component inside a tiny agent harness.

Your job is NOT to inspect the computer directly.

Do not use shell commands, filesystem tools, browser tools,
MCP tools, or any other Codex tool yourself.

The outer Python harness owns all real tools.

At each turn choose exactly ONE next action.

Available tools:

1. list_files(path)
   Lists files and directories inside the allowed workspace.

2. read_file(path)
   Reads one text file inside the allowed workspace.

3. grep_file(path, pattern)
   Searches a file or directory for a text pattern.

If more evidence is needed, return:
kind = "tool_call"

If enough evidence exists to answer the user's goal, return:
kind = "final"

Rules:

- Never invent tool results.
- Base decisions only on observations supplied below.
- Use one tool at a time.
- Do not request tools that are not listed above.
- When kind is "final", tool must be "none".
- When kind is "final", put the complete answer in the answer field.
- Fields that are not needed must be empty strings.
- note must contain only a short operational explanation.

USER GOAL:

{goal}

OBSERVATIONS FROM PREVIOUS STEPS:

{history_json}
"""
```

This function is our context builder.

Every model call receives:

- the current user goal
- the available tool descriptions
- the operating rules
- the observations collected in previous steps

This is a simple form of context engineering.

The model does not automatically know what happened in earlier subprocess calls.

The harness must explicitly provide the state that matters.

---

# 19. Context vs State

At this point we can clearly separate two concepts.

The Python variable:

```python
history
```

is state stored by the harness.

It exists outside the model.

The serialized version:

```python
history_json
```

that is inserted into the prompt becomes part of the model context.

This distinction is extremely important in agent architecture.

State is what the system remembers.

Context is what the model can currently see.

A production agent may store state in:

- a database
- Redis
- files
- Git history
- a session store
- a vector store
- an event log

The harness then chooses which part of that state should be placed into the model context for the next decision.

---

# 20. Call Codex for One Decision

Now we create the function that asks Codex for the next action.

Add:

```python
def ask_codex(prompt: str) -> dict:
    decision_file = RUNTIME_DIR / "decision.json"

    if decision_file.exists():
        decision_file.unlink()

    command = [
        "codex",
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--output-schema",
        str(SCHEMA_FILE),
        "--output-last-message",
        str(decision_file),
        "-"
    ]

    result = subprocess.run(
        command,
        input=prompt,
        capture_output=True,
        text=True,
        cwd=RUNTIME_DIR,
        env=codex_environment()
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Codex execution failed:\n"
            + result.stderr
        )

    if not decision_file.exists():
        raise RuntimeError(
            "Codex completed but decision.json was not created.\n"
            + result.stderr
        )

    raw = decision_file.read_text(
        encoding="utf-8"
    )

    return json.loads(raw)
```

This is where Python delegates the reasoning step to Codex.

The important command is conceptually:

```bash
codex exec ...
```

The prompt is passed through standard input.

The structured result is written to:

```text
.agent_runtime/decision.json
```

and Python reads that file back into a dictionary.

At this point the model has only produced a decision.

No tool has been executed yet.

---

# 21. Why `--sandbox read-only` Is Used

The Codex subprocess is run with:

```text
--sandbox read-only
```

because in this lesson Codex is supposed to act only as the decision component.

The actual tools belong to our Python harness.

This creates an intentional separation:

```text
Codex
  |
  +--> decides what should happen

Python
  |
  +--> performs the actual environment interaction
```

In production, these boundaries can be designed differently, but this separation is extremely useful for learning the architecture.

---

# 22. Build the Agent Loop

Now we create the central part of the agent.

Add:

```python
def run_agent(goal: str) -> None:
    verify_codex_login()

    history = []

    print("\nGOAL")
    print(goal)

    for step in range(1, MAX_STEPS + 1):

        print(
            f"\n{'=' * 60}\n"
            f"STEP {step}\n"
            f"{'=' * 60}"
        )

        prompt = build_prompt(
            goal,
            history
        )

        decision = ask_codex(prompt)

        print("\nMODEL DECISION")
        print(
            json.dumps(
                decision,
                ensure_ascii=False,
                indent=2
            )
        )

        if decision["kind"] == "final":
            print("\nFINAL ANSWER")
            print(decision["answer"])
            return

        if decision["kind"] != "tool_call":
            raise RuntimeError("Invalid decision kind")

        call_id = f"call_{step}"

        print("\nHARNESS")
        print(
            f"Executing {decision['tool']} "
            f"as {call_id}"
        )

        result = execute_tool(decision)

        print("\nTOOL RESULT")
        print(result)

        history.append(
            {
                "call_id": call_id,
                "tool": decision["tool"],
                "path": decision["path"],
                "pattern": decision["pattern"],
                "result": result
            }
        )

    raise RuntimeError(
        f"Agent exceeded maximum step count: {MAX_STEPS}"
    )
```

This function is the agent loop.

The loop performs the same cycle repeatedly:

```text
1. Build context
2. Ask the model for the next decision
3. Inspect the decision
4. Execute the requested tool
5. Store the tool result
6. Repeat
```

until the model returns:

```text
kind = final
```

or the harness reaches the maximum number of allowed steps.

---

# 23. The Agent Loop in Pseudocode

The core idea can be reduced to:

```text
while agent is not finished:

    context = build_context(state)

    decision = model(context)

    if decision == tool_call:
        result = execute_tool(decision)
        state.append(result)

    if decision == final:
        return answer
```

This simple loop is the foundation of many agent systems.

Real systems add more layers, but the basic shape remains recognizable.

---

# 24. Add the Program Entry Point

At the end of `agent.py`, add:

```python
if __name__ == "__main__":

    if len(sys.argv) > 1:
        user_goal = " ".join(sys.argv[1:])
    else:
        user_goal = (
            "Investigate why the API service cannot connect to Redis. "
            "Use the available evidence, do not modify any files, "
            "and explain the root cause."
        )

    run_agent(user_goal)
```

This lets us run the default task:

```bash
python3 agent.py
```

or provide another goal:

```bash
python3 agent.py "Find the Redis hostname problem and explain the evidence."
```

---

# 25. Complete `agent.py`

The complete source is:

```python
import json
import os
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
WORKSPACE = (BASE_DIR / "demo_workspace").resolve()
RUNTIME_DIR = (BASE_DIR / ".agent_runtime").resolve()
SCHEMA_FILE = BASE_DIR / "decision-schema.json"

MAX_STEPS = 10

RUNTIME_DIR.mkdir(exist_ok=True)


def codex_environment() -> dict:
    env = os.environ.copy()

    env.pop("OPENAI_API_KEY", None)
    env.pop("CODEX_API_KEY", None)

    return env


def verify_codex_login() -> None:
    result = subprocess.run(
        ["codex", "login", "status"],
        capture_output=True,
        text=True,
        env=codex_environment()
    )

    output = (result.stdout + "\n" + result.stderr).strip()

    if result.returncode != 0:
        raise RuntimeError(
            "Codex is not authenticated.\n"
            + output
        )

    print("\nAUTH")
    print(output)


def safe_path(relative_path: str) -> Path:
    relative_path = relative_path or "."
    candidate = (WORKSPACE / relative_path).resolve()

    if candidate != WORKSPACE and WORKSPACE not in candidate.parents:
        raise ValueError("Path escapes the allowed workspace")

    return candidate


def list_files(path: str) -> str:
    target = safe_path(path)

    if not target.exists():
        return f"ERROR: path does not exist: {path}"

    if not target.is_dir():
        return f"ERROR: path is not a directory: {path}"

    entries = []

    for item in sorted(target.iterdir()):
        name = item.name + ("/" if item.is_dir() else "")
        entries.append(name)

    return "\n".join(entries[:100])


def read_file(path: str) -> str:
    target = safe_path(path)

    if not target.exists():
        return f"ERROR: file does not exist: {path}"

    if not target.is_file():
        return f"ERROR: path is not a file: {path}"

    content = target.read_text(
        encoding="utf-8",
        errors="replace"
    )

    max_chars = 12000

    if len(content) > max_chars:
        content = content[:max_chars] + "\n...[truncated]"

    return content


def grep_file(path: str, pattern: str) -> str:
    target = safe_path(path)

    if not target.exists():
        return f"ERROR: path does not exist: {path}"

    pattern_lower = pattern.lower()
    matches = []

    if target.is_file():
        files = [target]
    else:
        files = [
            item
            for item in target.rglob("*")
            if item.is_file()
        ]

    for file_path in files:
        try:
            content = file_path.read_text(
                encoding="utf-8",
                errors="replace"
            )
        except Exception:
            continue

        for line_number, line in enumerate(
            content.splitlines(),
            start=1
        ):
            if pattern_lower in line.lower():
                relative = file_path.relative_to(WORKSPACE)

                matches.append(
                    f"{relative}:{line_number}: {line}"
                )

                if len(matches) >= 50:
                    return "\n".join(matches)

    if not matches:
        return "NO MATCHES"

    return "\n".join(matches)


def execute_tool(decision: dict) -> str:
    tool = decision["tool"]

    try:
        if tool == "list_files":
            return list_files(
                decision["path"]
            )

        if tool == "read_file":
            return read_file(
                decision["path"]
            )

        if tool == "grep_file":
            return grep_file(
                decision["path"],
                decision["pattern"]
            )

        return f"ERROR: unknown tool: {tool}"

    except Exception as exc:
        return f"ERROR: {exc}"


def build_prompt(
    goal: str,
    history: list[dict]
) -> str:

    history_json = json.dumps(
        history,
        ensure_ascii=False,
        indent=2
    )

    return f"""
You are the decision component inside a tiny agent harness.

Your job is NOT to inspect the computer directly.

Do not use shell commands, filesystem tools, browser tools,
MCP tools, or any other Codex tool yourself.

The outer Python harness owns all real tools.

At each turn choose exactly ONE next action.

Available tools:

1. list_files(path)
   Lists files and directories inside the allowed workspace.

2. read_file(path)
   Reads one text file inside the allowed workspace.

3. grep_file(path, pattern)
   Searches a file or directory for a text pattern.

If more evidence is needed, return:
kind = "tool_call"

If enough evidence exists to answer the user's goal, return:
kind = "final"

Rules:

- Never invent tool results.
- Base decisions only on observations supplied below.
- Use one tool at a time.
- Do not request tools that are not listed above.
- When kind is "final", tool must be "none".
- When kind is "final", put the complete answer in the answer field.
- Fields that are not needed must be empty strings.
- note must contain only a short operational explanation.

USER GOAL:

{goal}

OBSERVATIONS FROM PREVIOUS STEPS:

{history_json}
"""


def ask_codex(prompt: str) -> dict:
    decision_file = RUNTIME_DIR / "decision.json"

    if decision_file.exists():
        decision_file.unlink()

    command = [
        "codex",
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--output-schema",
        str(SCHEMA_FILE),
        "--output-last-message",
        str(decision_file),
        "-"
    ]

    result = subprocess.run(
        command,
        input=prompt,
        capture_output=True,
        text=True,
        cwd=RUNTIME_DIR,
        env=codex_environment()
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Codex execution failed:\n"
            + result.stderr
        )

    if not decision_file.exists():
        raise RuntimeError(
            "Codex completed but decision.json was not created.\n"
            + result.stderr
        )

    raw = decision_file.read_text(
        encoding="utf-8"
    )

    return json.loads(raw)


def run_agent(goal: str) -> None:
    verify_codex_login()

    history = []

    print("\nGOAL")
    print(goal)

    for step in range(1, MAX_STEPS + 1):

        print(
            f"\n{'=' * 60}\n"
            f"STEP {step}\n"
            f"{'=' * 60}"
        )

        prompt = build_prompt(
            goal,
            history
        )

        decision = ask_codex(prompt)

        print("\nMODEL DECISION")
        print(
            json.dumps(
                decision,
                ensure_ascii=False,
                indent=2
            )
        )

        if decision["kind"] == "final":
            print("\nFINAL ANSWER")
            print(decision["answer"])
            return

        if decision["kind"] != "tool_call":
            raise RuntimeError("Invalid decision kind")

        call_id = f"call_{step}"

        print("\nHARNESS")
        print(
            f"Executing {decision['tool']} "
            f"as {call_id}"
        )

        result = execute_tool(decision)

        print("\nTOOL RESULT")
        print(result)

        history.append(
            {
                "call_id": call_id,
                "tool": decision["tool"],
                "path": decision["path"],
                "pattern": decision["pattern"],
                "result": result
            }
        )

    raise RuntimeError(
        f"Agent exceeded maximum step count: {MAX_STEPS}"
    )


if __name__ == "__main__":

    if len(sys.argv) > 1:
        user_goal = " ".join(sys.argv[1:])
    else:
        user_goal = (
            "Investigate why the API service cannot connect to Redis. "
            "Use the available evidence, do not modify any files, "
            "and explain the root cause."
        )

    run_agent(user_goal)
```

---

# 26. Run the Agent

Run:

```bash
python3 agent.py
```

The output should contain repeated sections like:

```text
============================================================
STEP 1
============================================================

MODEL DECISION
...
```

A possible first decision is:

```json
{
  "kind": "tool_call",
  "tool": "list_files",
  "path": ".",
  "pattern": "",
  "answer": "",
  "note": "I need to inspect the workspace structure."
}
```

The important point is that Codex has not listed the directory itself.

It has only requested the tool.

The harness then prints:

```text
HARNESS
Executing list_files as call_1
```

and the actual Python tool returns:

```text
TOOL RESULT

compose.yaml
config/
logs/
```

This is the first complete agent step.

---

# 27. Follow the Second Step

The tool result is stored in:

```python
history
```

The next time `build_prompt()` runs, that observation becomes part of the context.

Codex may then request:

```json
{
  "kind": "tool_call",
  "tool": "read_file",
  "path": "logs/api.log",
  "pattern": "",
  "answer": "",
  "note": "The application log may reveal the failure."
}
```

The harness executes the tool and returns:

```text
2026-10-03T10:10:01Z INFO  starting api service
2026-10-03T10:10:02Z INFO  connecting to redis:6379
2026-10-03T10:10:02Z ERROR redis connection failed
2026-10-03T10:10:02Z ERROR getaddrinfo ENOTFOUND redis
```

Now the model has a new observation.

It knows DNS resolution for `redis` failed.

But this is not yet enough evidence to know what the correct hostname should be.

---

# 28. Continue the Investigation

A later step may read:

```text
compose.yaml
```

and discover:

```yaml
cache:
  image: redis:7-alpine
```

Another step may read:

```text
config/app.env
```

and discover:

```text
REDIS_HOST=redis
```

At this point the evidence is sufficient.

The model can connect the observations:

```text
Application configuration -> redis
Compose service name      -> cache
Runtime error             -> ENOTFOUND redis
```

and produce a final answer.

---

# 29. Final Decision

A final model response may look like:

```json
{
  "kind": "final",
  "tool": "none",
  "path": "",
  "pattern": "",
  "answer": "The API is configured to connect to the hostname redis, but the Redis service in compose.yaml is named cache. The log shows getaddrinfo ENOTFOUND redis, which is consistent with that hostname mismatch. REDIS_HOST should reference the service name that is resolvable on the Compose network.",
  "note": "The available evidence is sufficient to identify the root cause."
}
```

The harness sees:

```python
if decision["kind"] == "final":
```

prints the answer, and exits the loop.

---

# 30. Where the Agent Loop Actually Exists

The most important line to point out during the class is:

```python
for step in range(1, MAX_STEPS + 1):
```

Everything inside this loop is one agent iteration.

Inside each iteration:

```python
prompt = build_prompt(
    goal,
    history
)
```

builds the current context.

Then:

```python
decision = ask_codex(prompt)
```

gets the next model decision.

Then:

```python
result = execute_tool(decision)
```

performs the real action.

Finally:

```python
history.append(...)
```

stores the new observation.

Then the loop repeats.

This is the agent loop in executable form.

---

# 31. Mapping the Code to Agent Architecture

The project can now be mapped directly to the conceptual architecture:

```text
Codex
    = Model / Decision Maker

agent.py
    = Agent Harness

list_files()
read_file()
grep_file()
    = Tools

execute_tool()
    = Tool Dispatcher

history
    = Runtime State

build_prompt()
    = Context Builder

for step in range(...)
    = Agent Loop

demo_workspace/
    = Environment

safe_path()
    = Guardrail

MAX_STEPS
    = Stop / Budget Guardrail

decision-schema.json
    = Tool / Decision Contract
```

This mapping is the most important summary of the entire lesson.

---

# 32. Model vs Harness

The model is responsible for decisions such as:

```text
I need to inspect the logs.
```

or:

```text
I now have enough evidence to answer.
```

The harness is responsible for operational behavior such as:

```text
Which tools actually exist?
Can this path be accessed?
How is the tool executed?
Where is state stored?
What result is passed back?
When should execution stop?
```

That distinction is why an agent is more than just a model.

---

# 33. Tool Calling in This Project

This project implements tool calling through structured model output rather than direct API function calling.

Codex returns structured JSON like:

```json
{
  "kind": "tool_call",
  "tool": "read_file",
  "path": "logs/api.log"
}
```

The Python harness interprets that structure and calls the corresponding Python function.

The conceptual flow is still the same:

```text
Model
  |
  v
Tool Selection
  |
  v
Harness
  |
  v
Tool Execution
  |
  v
Tool Result
  |
  v
Model
```

This design is especially useful for teaching because every transition is visible.

---

# 34. Why the Model Gets Only One Tool per Step

The prompt says:

```text
Use one tool at a time.
```

This is intentional.

Allowing only one tool per iteration makes the loop easier to observe:

```text
Decision
  -> Tool
  -> Result
  -> New Decision
```

Production agents may support parallel or batched tool execution, but that would make the first implementation harder to understand.

---

# 35. Why We Keep the Agent Read-Only

The agent only has:

```text
list_files
read_file
grep_file
```

and no modification tool.

This means the agent can inspect the environment but cannot change it.

That allows us to understand the agent loop without immediately introducing higher-risk actions.

The next natural extension is to add tools such as:

```text
write_file(path, content)
run_command(command)
```

but once those exist, the harness should also introduce stronger controls such as:

- approval
- permissions
- command allowlists
- sandboxing
- verification
- rollback strategy

Capability and risk grow together.

---

# 36. The Importance of Verification

In this first agent, the task is diagnostic, so the final answer is based on collected evidence.

When the agent is later allowed to change the system, a new rule becomes necessary:

> An action is not complete until its result has been verified.

For example, after changing:

```text
REDIS_HOST=cache
```

the agent should not immediately say "fixed."

It should verify the result using something like:

```text
docker compose up
```

or:

```text
curl
```

or application logs.

That transforms the loop from:

```text
Observe -> Reason -> Act
```

into:

```text
Observe -> Reason -> Act -> Verify
```

which is much closer to a production agent.

---

# 37. Why `MAX_STEPS` Matters

The line:

```python
MAX_STEPS = 10
```

looks simple, but it represents a real agent control.

Without a limit, a model could keep requesting tools indefinitely.

Production agents often use several budgets at the same time:

```text
Step Budget
Token Budget
Time Budget
Cost Budget
Tool Budget
```

The basic principle is that autonomy must have boundaries.

---

# 38. Try a Different Goal

You can pass a different task directly:

```bash
python3 agent.py \
"Find the Redis hostname mismatch and explain the evidence."
```

or:

```bash
python3 agent.py \
"Inspect the workspace and explain why Redis name resolution fails."
```

The tools remain the same.

Only the goal changes.

This demonstrates another useful property of agent architecture:

> The same harness can solve different tasks as long as its tool surface provides the required capabilities.

---

# 39. Useful Commands During the Class

Show the project:

```bash
find . -maxdepth 3 -type f -print
```

Inspect the configuration:

```bash
cat demo_workspace/config/app.env
```

Inspect Compose:

```bash
cat demo_workspace/compose.yaml
```

Inspect the log:

```bash
cat demo_workspace/logs/api.log
```

Run the agent:

```bash
python3 agent.py
```

Run with a custom goal:

```bash
python3 agent.py \
"Investigate the Redis connection failure."
```

Inspect the last structured Codex decision:

```bash
cat .agent_runtime/decision.json
```

That last command is especially useful during teaching because it shows that the model response is a structured decision that the harness can parse.

---

# 40. Recommended Live Teaching Flow

A good classroom flow is not to explain every line of Python before running the project.

Instead, start by running:

```bash
python3 agent.py
```

and let the audience see:

```text
STEP 1
MODEL DECISION
HARNESS
TOOL RESULT
STEP 2
MODEL DECISION
...
```

Then stop and explain what just happened.

Show this flow:

```text
User Goal
   |
   v
Model Decision
   |
   v
Tool Call
   |
   v
Harness
   |
   v
Tool Execution
   |
   v
Tool Result
   |
   v
New Context
   |
   v
Model Decision
```

After that, open `agent.py` and map each visible runtime event to the exact part of the code.

This usually makes the architecture easier to understand because the students have already seen the behavior before reading the implementation.

---

# 41. What Students Should Understand After This Lesson

By the end of this implementation, students should be able to explain that an agent is not simply a model with a longer prompt.

They should understand that the working system contains several cooperating components:

```text
Model
Harness
Tools
Environment
Context
State
Guardrails
Loop
Stop Conditions
```

They should also understand that the model does not directly perform most real-world actions.

It requests actions.

The harness decides how those actions are validated and executed.

---

# 42. The Most Important Architectural Separation

Keep this distinction clear:

```text
Model:
"What should I do next?"

Harness:
"Can you do that, how will it be executed, and what result should come back?"
```

The model is probabilistic.

The harness should be deterministic wherever possible.

The model may choose:

```text
read_file("logs/api.log")
```

but the harness controls:

```text
whether that path is legal
how the file is opened
how much content is returned
how errors are represented
how the result enters state
```

This is why agent engineering is not only prompt engineering.

A large part of agent engineering is software architecture.

---

# 43. Troubleshooting

## `codex` command not found

Check:

```bash
which codex
```

and:

```bash
codex --version
```

If the command is unavailable, install or repair Codex CLI before continuing.

---

## Codex is not authenticated

Run:

```bash
codex login status
```

If needed, run:

```bash
codex
```

and sign in.

---

## `codex exec` fails before Python starts

Test Codex independently:

```bash
codex exec --skip-git-repo-check "Reply only with: CODEX_OK"
```

If this command fails, the issue is outside the Python harness.

---

## `decision.json` is not created

Inspect the error output from Codex.

Also verify that your installed Codex version supports the CLI flags used by this demo.

You can inspect help with:

```bash
codex exec --help
```

---

## The model requests strange paths

The harness should block paths outside `demo_workspace`.

This is expected behavior and demonstrates that runtime enforcement is working.

---

## The model uses too many steps

The harness stops after:

```python
MAX_STEPS = 10
```

You can increase this value for experimentation, but the limit is intentionally part of the design.

---

# 44. Next Extension: Add Write Capability

The next version of this project can add:

```text
write_file(path, content)
```

Once the agent can modify the environment, introduce:

```text
Approval
Permission
Verification
Rollback
```

For example, instead of executing immediately:

```text
write_file("config/app.env", ...)
```

the harness could print:

```text
The agent wants to modify config/app.env.
Approve? [y/N]
```

This introduces a human-in-the-loop control.

---

# 45. Next Extension: Add Command Execution

A later version can add a controlled command tool:

```text
run_command(command)
```

Do not begin with unrestricted shell execution.

A better first version might allow only a small set of commands such as:

```text
docker compose config
docker compose ps
git diff
pytest
npm test
```

This demonstrates another agent-engineering principle:

> Prefer narrow capabilities over broad unrestricted tools.

---

# 46. Next Extension: Add Verification

After modification tools exist, the harness can require verification before allowing a final answer.

For example:

```text
Agent edits config
      |
      v
Harness records change
      |
      v
Agent must run verification tool
      |
      v
Verification succeeds
      |
      v
Final answer allowed
```

This creates a stronger agent loop.

---

# 47. Next Extension: Add MCP

The same architecture can later be connected to external systems through MCP.

For example:

```text
GitLab MCP
Kubernetes MCP
Jira MCP
Database MCP
Monitoring MCP
```

The important point is that MCP does not replace the agent loop.

It expands the available tool surface.

The loop still remains:

```text
Model
  -> Tool Selection
  -> Tool Execution
  -> Tool Result
  -> Model
```

---

# 48. Final Summary

The project we built is intentionally small, but architecturally complete enough to expose the essential parts of an AI agent.

The complete flow is:

```text
User Goal
   |
   v
Harness builds Context
   |
   v
Codex decides the next action
   |
   +----> Tool Call
   |          |
   |          v
   |      Harness validates
   |          |
   |          v
   |      Tool executes
   |          |
   |          v
   |      Tool Result
   |          |
   +----------+
   |
   v
History / State updated
   |
   v
New Context
   |
   v
Codex reasons again
   |
   v
Final Answer
```

The most important lesson is not the Redis bug itself.

The important lesson is the architecture that discovered it.

Codex is the reasoning component.

Python is the harness.

The Python functions are the tools.

`history` is the state.

`build_prompt()` creates the context.

The loop controls repeated reasoning and execution.

`safe_path()` and `MAX_STEPS` are guardrails.

`decision-schema.json` defines the contract between the model and the runtime.

Once these pieces are understood, larger agent systems such as coding agents, DevOps agents, Kubernetes agents, CI/CD agents, and long-running autonomous workflows become much easier to reason about because they are extensions of the same basic pattern.
