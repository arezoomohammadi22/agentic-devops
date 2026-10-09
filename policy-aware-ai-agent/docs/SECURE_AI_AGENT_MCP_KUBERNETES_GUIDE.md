# Secure AI Agent on Kubernetes with MCP, OPA, Human Approval, and RBAC

This repository demonstrates how to build an AI agent that can **reason about infrastructure and use tools** without giving the LLM direct authority over Kubernetes.

The core principle is simple:

> **The model may decide what it wants to do, but it must not be the security authority that decides whether the action is allowed, and it should not hold the infrastructure credentials that perform the final side effect.**

This guide starts from a secure planner/executor lab and evolves it into a tool-using agent with a real **Model Context Protocol (MCP) server**. The MCP server gives Codex a standardized tool interface, while the existing Gateway, OPA policy, approval flow, deterministic executor, and Kubernetes RBAC remain the security boundary.

---

## 1. What we are building

The final architecture looks like this:

```mermaid
flowchart TD
    U[User] --> A[Codex Agent]
    A -->|MCP tool call| M[MCP Server]
    M -->|Structured action| G[Secure Execution Gateway]
    G --> V[Schema + semantic validation]
    V --> C[Trusted identity + rate context]
    C --> O[OPA Policy Engine]
    O -->|ALLOW| E[Deterministic Executor]
    O -->|DENY| D[Reject]
    O -->|REQUIRE_APPROVAL| H[Human Approval Gate]
    H -->|Approved exact action| O
    E --> K[Kubernetes API]
    K --> R[Kubernetes RBAC]
    R --> W[Workload]
    W --> E
    E --> G
    G --> M
    M --> A
    A --> U
```

The important design choice is that **MCP does not replace the security layers**. MCP only standardizes how the agent discovers and calls tools.

The responsibilities are deliberately separated:

| Component | Responsibility |
|---|---|
| Codex Agent | Reason about the task and choose tools |
| MCP Server | Expose typed tools and translate tool calls into Gateway requests |
| Gateway | Enforce the trust boundary, validate inputs, add trusted context, audit actions |
| OPA | Decide `allow`, `deny`, or `require_approval` |
| Human Approval | Approve one exact high-risk action |
| Deterministic Executor | Perform only pre-implemented side effects |
| Kubernetes RBAC | Enforce the final infrastructure permissions |

The model is therefore **not** the final authority. It cannot promote itself to admin, mark its own action as approved, or directly patch the cluster.

---

## 2. Why MCP is added to the original lab

The original version used three planner-specific files:

```text
tools.yaml
      ↓
codex_client.py injected the catalog into the prompt
      ↓
action.schema.json constrained the final model output
      ↓
run_agent.py parsed the JSON and POSTed it to the Gateway
```

That was useful for teaching structured output and output validation, but it was still a custom tool interface.

With MCP, the top half becomes:

```text
MCP Server
  ├── get_logs(...)
  ├── restart_deployment(...)
  ├── get_approval_status(...)
  └── execute_approved_action(...)
          ↑
        Codex
```

Codex discovers those tools through MCP and calls them directly. The type hints on the MCP tool functions become the tool input schema, so `tools.yaml` and the planner-level `action.schema.json` are no longer required for tool selection.

**The Gateway validation remains mandatory.** MCP input validation is useful for tool calling, but the Gateway is still the real trust boundary because any client can potentially call the Gateway.

---

## 3. The security boundary

The most important rule in this design is:

```text
Codex/MCP input is untrusted.
Gateway/OPA policy context is trusted.
Kubernetes credentials belong to the Executor, not the model.
```

The model is allowed to request:

```text
get_logs(namespace, deployment)
restart_deployment(namespace, deployment, reason)
```

But it is **not** allowed to decide:

```text
I am an admin.
This request is already approved.
Ignore the rate limit.
Use cluster-admin.
```

Those facts come from the Gateway configuration and the infrastructure itself.

A second important rule is that the MCP server does **not** run `kubectl` and does not talk directly to the Kubernetes API. Its implementation calls the existing Gateway:

```text
Codex
  ↓
MCP tool
  ↓
MCP Server
  ↓
POST /v1/actions/propose
  ↓
Gateway
```

This keeps the policy and audit path intact.

---

## 4. Request lifecycle

### 4.1 Read-only investigation

If the user asks the agent to investigate an unhealthy deployment, Codex can choose the `get_logs` MCP tool. The MCP server converts that tool call into a structured Gateway action. The Gateway validates it, attaches the trusted identity, OPA allows read-only log access, and the Kubernetes Executor reads the pod logs through the Kubernetes API. The logs then return through the same chain to Codex, which can reason again.

This creates a real agent loop:

```text
Observe → Reason → Tool call → Observe result → Reason again
```

### 4.2 Staging restart

For a staging restart, Codex calls `restart_deployment`. The Gateway validates the request, OPA checks the agent role, capability, namespace, and rate limit, and returns `allow`. The deterministic Executor patches the deployment pod-template annotation and Kubernetes performs a rollout.

### 4.3 Production restart

For a production restart, OPA returns `require_approval`. The Gateway stores the exact action and its SHA-256 hash, then returns an approval ID. The agent must stop and report that ID to the user.

After the human approves the request, the agent calls `get_approval_status`. When the status is `approved`, it calls `execute_approved_action(approval_id)`.

The MCP server deliberately does **not** ask the model to resubmit the action parameters. It fetches the stored action from the Gateway and submits that exact action to `/v1/actions/execute-approved`. This preserves action-hash binding and prevents the model from changing the resource after approval.

---

## 5. Repository layout

```text
secure-agent-output-validation-lab/
├── agent/
│   ├── codex_client.py
│   ├── config.yaml
│   ├── run_agent.py
│   └── workspace/
│       ├── AGENTS.md
│       ├── README.txt
│       └── .codex/
│           └── config.toml.example
├── mcp_server/
│   ├── server.py
│   └── requirements.txt
├── gateway/
│   ├── Dockerfile
│   ├── config.yaml
│   ├── requirements.txt
│   └── app/
│       ├── executor.py
│       ├── main.py
│       ├── models.py
│       ├── opa_client.py
│       ├── security.py
│       ├── settings.py
│       └── store.py
├── opa/
│   ├── config.yaml
│   └── policy/
│       ├── agent_authz.rego
│       └── agent_authz_test.rego
├── k8s/
│   ├── 00-namespaces.yaml
│   ├── 01-serviceaccount-rbac.yaml
│   ├── 02-demo-workloads.yaml
│   ├── 03-opa-configmap.yaml
│   ├── 04-gateway-configmap.yaml
│   ├── 05-gateway-deployment.yaml
│   └── 06-gateway-service.yaml
├── scripts/
├── tests/
├── docker-compose.yml
├── Makefile
└── requirements-dev.txt
```

---

# Part I — Step-by-step implementation

## 6. Prerequisites

You need:

- Linux server
- Python 3.10+
- Codex CLI authenticated and working
- Docker and Docker Compose for the local/mock phase
- `kubectl`
- Access to a Kubernetes cluster
- A way for the Kubernetes nodes to pull or load the Gateway image

Create the environment:

```bash
cd secure-agent-output-validation-lab
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -r gateway/requirements.txt
pip install -r mcp_server/requirements.txt
```

Verify Codex:

```bash
codex --version
codex exec --help
```

---

## 7. First understand the security backend without the agent

Before MCP or Codex is involved, prove that the policy backend works independently.

Start OPA and the Gateway in mock mode:

```bash
docker compose up -d --build
```

Check health:

```bash
curl http://localhost:8080/health
curl http://localhost:8181/health
```

The local Docker Compose setup uses `EXECUTOR_MODE=mock`, so the policy path is real but Kubernetes is not modified.

### Test schema validation

Send an illegal extra field:

```bash
curl -i \
  -X POST \
  http://localhost:8080/v1/actions/propose \
  -H 'Content-Type: application/json' \
  -d '{
    "tool": "restart_deployment",
    "namespace": "agent-lab-staging",
    "resource_kind": "deployment",
    "resource": "demo-api",
    "reason": "unhealthy",
    "command": "kubectl delete namespace production"
  }'
```

Expected result: `HTTP 422`. The request is rejected by the Gateway model before OPA is involved.

### Test staging allow

```bash
curl -s \
  -X POST \
  http://localhost:8080/v1/actions/propose \
  -H 'Content-Type: application/json' \
  -d '{
    "tool": "restart_deployment",
    "namespace": "agent-lab-staging",
    "resource_kind": "deployment",
    "resource": "demo-api",
    "reason": "health checks failing"
  }' | python3 -m json.tool
```

Expected policy effect: `allow`.

### Test production approval

Change the namespace to `agent-lab-production`. The expected HTTP status is `202` and the response contains an `approval_id`.

### Test denied namespace deletion

```bash
curl -i \
  -X POST \
  http://localhost:8080/v1/actions/propose \
  -H 'Content-Type: application/json' \
  -d '{
    "tool": "delete_namespace",
    "namespace": "agent-lab-production",
    "resource_kind": "namespace",
    "resource": "agent-lab-production",
    "reason": "security test"
  }'
```

Expected result: `HTTP 403`.

This dangerous action remains in the Gateway lab model only to demonstrate deny behavior. It is intentionally **not advertised as an MCP tool**.

---

## 8. Deploy the security backend to Kubernetes

### 8.1 Namespaces

```bash
kubectl apply -f k8s/00-namespaces.yaml
kubectl get ns | grep agent-
```

The lab uses:

```text
agent-system
agent-lab-staging
agent-lab-production
```

### 8.2 ServiceAccount and RBAC

```bash
kubectl apply -f k8s/01-serviceaccount-rbac.yaml
```

Verify the allowed permission:

```bash
kubectl auth can-i \
  patch deployments \
  -n agent-lab-staging \
  --as=system:serviceaccount:agent-system:incident-agent
```

Expected:

```text
yes
```

Verify the forbidden permission:

```bash
kubectl auth can-i \
  delete namespaces \
  --as=system:serviceaccount:agent-system:incident-agent
```

Expected:

```text
no
```

### 8.3 Demo workloads

```bash
kubectl apply -f k8s/02-demo-workloads.yaml
kubectl get deploy,pod -n agent-lab-staging
kubectl get deploy,pod -n agent-lab-production
```

Both namespaces should contain a `demo-api` deployment.

### 8.4 OPA and Gateway configuration

```bash
kubectl apply -f k8s/03-opa-configmap.yaml
kubectl apply -f k8s/04-gateway-configmap.yaml
```

The Kubernetes Gateway configuration sets the executor mode to `kubernetes`.

### 8.5 Build the Gateway image

```bash
docker build -t secure-agent-gateway:lab ./gateway
```

Make this image available to your Kubernetes nodes. For kind you can load it directly; for other clusters push it to a registry reachable by the nodes and update `k8s/05-gateway-deployment.yaml`.

### 8.6 Deploy Gateway + OPA sidecar

```bash
kubectl apply -f k8s/05-gateway-deployment.yaml
kubectl -n agent-system get pods
```

Expected state:

```text
2/2 Running
```

The pod contains two containers: `gateway` and `opa`.

The OPA container loads **one explicit Rego file**:

```text
/policy/agent_authz.rego
```

Do not load the entire ConfigMap mount directory on Kubernetes. ConfigMap volumes contain versioned symlink paths such as `..data`; loading the directory can cause OPA to read the same policy multiple times and raise `multiple default rules`.

Inspect logs:

```bash
kubectl -n agent-system logs deploy/secure-agent-gateway -c gateway
kubectl -n agent-system logs deploy/secure-agent-gateway -c opa
```

### 8.7 Service and port-forward

```bash
kubectl apply -f k8s/06-gateway-service.yaml
kubectl -n agent-system port-forward svc/secure-agent-gateway 8080:8080
```

Keep that terminal open.

In another terminal:

```bash
curl http://localhost:8080/health
```

---

## 9. Prove the Kubernetes Executor works before adding MCP

Send a staging restart directly to the Gateway:

```bash
curl -s \
  -X POST \
  http://localhost:8080/v1/actions/propose \
  -H 'Content-Type: application/json' \
  -d '{
    "tool": "restart_deployment",
    "namespace": "agent-lab-staging",
    "resource_kind": "deployment",
    "resource": "demo-api",
    "reason": "manual kubernetes executor test"
  }' | python3 -m json.tool
```

Verify the actual deployment patch:

```bash
kubectl -n agent-lab-staging \
  get deployment demo-api \
  -o jsonpath='{.spec.template.metadata.annotations.secure-agent-lab/restartedAt}'
```

If the timestamp changes, the full backend path is working:

```text
Gateway → OPA → KubernetesExecutor → Kubernetes API → RBAC
```

At this point `curl` is only acting as a temporary fake agent client.

---

# Part II — Add MCP

## 10. MCP server design

The MCP server exposes four tools:

```text
get_logs
restart_deployment
get_approval_status
execute_approved_action
```

It does not expose `delete_namespace`.

The MCP tool implementation never executes `kubectl`. Each tool simply translates its typed arguments into the existing Gateway contract.

The official MCP Python SDK can derive tool schemas from Python type hints. Local MCP servers can run over `stdio`, which is appropriate here because Codex and the MCP server run on the same host. For remotely deployed MCP servers, use Streamable HTTP instead of the older SSE transport.

---

## 11. Configure Codex to launch the MCP server

Copy the example:

```bash
cp agent/workspace/.codex/config.toml.example \
   agent/workspace/.codex/config.toml
```

Edit it and replace the absolute repository paths.

A convenient way to generate it is:

```bash
REPO_ROOT="$(pwd)"
mkdir -p agent/workspace/.codex
cat > agent/workspace/.codex/config.toml <<EOF
[mcp_servers.secure_agent]
command = "$REPO_ROOT/.venv/bin/python"
args = ["$REPO_ROOT/mcp_server/server.py"]
cwd = "$REPO_ROOT"
env = { GATEWAY_URL = "http://127.0.0.1:8080" }
required = true
enabled_tools = [
  "get_logs",
  "restart_deployment",
  "get_approval_status",
  "execute_approved_action"
]
startup_timeout_sec = 10
tool_timeout_sec = 60
EOF
```

Codex supports MCP configuration through `config.toml`, including stdio `command`, `args`, `cwd`, environment variables, tool allowlists, startup timeouts, and per-tool timeouts.

Project-level `.codex/config.toml` is loaded only for trusted projects. If your Codex installation does not load the workspace config, place the same MCP block in `~/.codex/config.toml`.

Verify discovery:

```bash
codex mcp list
```

You should see `secure_agent`.

---

## 12. Optional: inspect the MCP server before using Codex

The MCP Python SDK includes a development inspector:

```bash
mcp dev mcp_server/server.py
```

The default server transport used by `mcp.run()` is `stdio`. In stdio mode there is no MCP TCP port; Codex launches the server as a child process and communicates over stdin/stdout.

For application logging from a stdio MCP server, prefer Python logging to stderr. Do not print protocol-unrelated data to stdout before the MCP transport starts.

---

## 13. Run the real agent

Make sure the Gateway port-forward is still active, then run:

```bash
python3 agent/run_agent.py \
  --task "Inspect the demo-api deployment in agent-lab-staging and take the safest useful action."
```

The expected path is now:

```text
User task
  ↓
Codex
  ↓
MCP tool discovery
  ↓
get_logs(...)
  ↓
MCP Server
  ↓
Gateway
  ↓
OPA
  ↓
KubernetesExecutor
  ↓
Kubernetes
  ↓
logs returned to Codex
  ↓
Codex reasons again
```

Codex can now use observations from one tool call to make the next decision. This is the major difference from the earlier one-action planner lab.

---

## 14. Test an explicit staging restart through the agent

```bash
python3 agent/run_agent.py \
  --task "Restart the demo-api deployment in agent-lab-staging using only secure_agent MCP tools."
```

Verify the timestamp afterward:

```bash
kubectl -n agent-lab-staging \
  get deployment demo-api \
  -o jsonpath='{.spec.template.metadata.annotations.secure-agent-lab/restartedAt}'
```

The user did not call the Gateway directly in this test. Codex selected and invoked the MCP tool, and the MCP server routed the request through the same security backend.

---

## 15. Test production approval through MCP

Run:

```bash
python3 agent/run_agent.py \
  --task "Restart the demo-api deployment in agent-lab-production using only secure_agent MCP tools."
```

OPA should return `require_approval`. The Gateway response includes an approval ID, and the agent instructions require Codex to stop and report that ID rather than bypass the approval.

Open the approval UI:

```text
http://localhost:8080/approvals/ui
```

Approve the pending action.

Then run the agent again with a follow-up task such as:

```bash
python3 agent/run_agent.py \
  --task "Check approval APPROVAL_ID. If it is approved, execute the exact approved action."
```

The intended tool sequence is:

```text
get_approval_status(APPROVAL_ID)
        ↓
execute_approved_action(APPROVAL_ID)
```

`execute_approved_action` fetches the stored action from the Gateway. The model does not supply new namespace, deployment, or reason fields after approval.

---

## 16. Audit the behavior

```bash
curl -s http://localhost:8080/v1/audit | python3 -m json.tool
```

Useful events include policy decisions, approval requests, approval state changes, execution success, execution failure, and approval-hash mismatches.

OPA also has decision logging enabled in this lab, so the OPA container logs can be correlated with Gateway audit records.

---

## 17. Important hardening note: isolate Codex from Kubernetes credentials

`AGENTS.md` is an instruction layer, not a hard security boundary. A production-quality deployment should also ensure the Codex process itself cannot bypass the MCP/Gateway path.

Do **not** run the agent with a readable kubeconfig or a Kubernetes ServiceAccount that can mutate the cluster. Prefer a dedicated Unix user, container, or workload identity that has no direct Kubernetes credentials. Network policy can also prevent the agent runtime from reaching the Kubernetes API directly.

The only component that needs Kubernetes mutation permissions in this design is the deterministic execution backend.

---

## 18. What MCP does not replace

MCP solves the interface problem:

```text
What tools exist?
What arguments do they accept?
How does the agent call them?
```

MCP does not answer:

```text
Is this specific action authorized?
Does production require approval?
Has the rate limit been exceeded?
Does this identity have the infrastructure permission?
```

Those questions remain the job of the Gateway, OPA, approval service, and RBAC.

---

## 19. Next evolution: specialized executor agents

This repository intentionally keeps the final side-effect executor deterministic. A later architecture can introduce specialized executor agents, for example a Kubernetes incident agent, GitLab agent, or Linux operations agent.

Even then, the safe pattern remains:

```text
Planner / Orchestrator
        ↓
Specialized Agent
        ↓
MCP Tool Call
        ↓
Gateway + OPA
        ↓
Deterministic Side-Effect Executor
        ↓
Infrastructure
```

An executor agent can reason, investigate, and perform multi-step loops, but it should still cross a controlled tool boundary before creating infrastructure side effects.

---

## 20. Useful references

- [OpenAI Docs MCP and Codex MCP configuration](https://developers.openai.com/learn/docs-mcp)
- [Codex configuration reference](https://developers.openai.com/docs/config-file/config-reference)
- [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP Python SDK: running servers and transports](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/index.md)
- [Open Policy Agent documentation](https://www.openpolicyagent.org/docs/latest/)

---

# Part III — Complete reference source

The following files are a complete reference implementation for the MCP-integrated version of this lab. Generated files, caches, and the repository README itself are omitted.

## `.env.example`

```bash
GATEWAY_URL=http://localhost:8080
OPA_URL=http://opa:8181
EXECUTOR_MODE=mock
CONFIG_PATH=/config/config.yaml
DB_PATH=/data/lab.db
```

## `.gitignore`

```gitignore
.venv/
__pycache__/
*.pyc
.pytest_cache/
.env
*.db
data/
```

## `.pytest_cache/.gitignore`

```gitignore
# Created by pytest automatically.
*
```

## `.pytest_cache/CACHEDIR.TAG`

```text
Signature: 8a477f597d28d172789f06886806bc55
# This file is a cache directory tag created by pytest.
# For information about cache directory tags, see:
#	https://bford.info/cachedir/spec.html
```

## `.pytest_cache/v/cache/nodeids`

```text
[
  "tests/test_models.py::test_extra_field_rejected",
  "tests/test_models.py::test_hash_changes",
  "tests/test_models.py::test_hash_stable",
  "tests/test_models.py::test_valid_restart",
  "tests/test_models.py::test_wrong_kind_rejected"
]
```

## `Makefile`

```makefile
.PHONY: up down logs reset smoke test policy-test e2e codex-preflight mcp-preflight staging production
up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

reset:
	./scripts/reset_lab.sh

smoke:
	./scripts/smoke.sh

test:
	python3 -m pytest -q

policy-test:
	docker run --rm -v "$$(pwd)/opa/policy:/policy:ro" openpolicyagent/opa:latest test /policy -v

e2e:
	./scripts/test_e2e.sh

codex-preflight:
	./scripts/codex_preflight.sh

mcp-preflight:
	python3 -m py_compile mcp_server/server.py
	codex mcp list

staging:
	python3 agent/run_agent.py --task "Inspect the demo-api deployment in agent-lab-staging and take the safest useful action using only secure_agent MCP tools."

production:
	python3 agent/run_agent.py --task "Restart the demo-api deployment in agent-lab-production using only secure_agent MCP tools. If approval is required, report the approval ID and stop."
```

## `agent/codex_client.py`

```python
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
```

## `agent/config.yaml`

```yaml
name: incident-response-agent
codex:
  executable: codex
  model: null
  reasoning_effort: medium
  sandbox: read-only
  ignore_rules: true
  ephemeral: true
```

## `agent/run_agent.py`

```python
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
```

## `agent/workspace/.codex/config.toml.example`

```text
# Copy this file to agent/workspace/.codex/config.toml and replace
# every /ABSOLUTE/PATH/TO/REPO placeholder before starting Codex.

[mcp_servers.secure_agent]
command = "/ABSOLUTE/PATH/TO/REPO/.venv/bin/python"
args = ["/ABSOLUTE/PATH/TO/REPO/mcp_server/server.py"]
cwd = "/ABSOLUTE/PATH/TO/REPO"
env = { GATEWAY_URL = "http://127.0.0.1:8080" }
required = true
enabled_tools = [
  "get_logs",
  "restart_deployment",
  "get_approval_status",
  "execute_approved_action"
]
startup_timeout_sec = 10
tool_timeout_sec = 60
```

## `agent/workspace/AGENTS.md`

```markdown
# Secure Incident-Response Agent

You are an incident-response agent operating through a controlled tool boundary.

## Mandatory rules

- Use only tools exposed by the `secure_agent` MCP server for Kubernetes observations and actions.
- Never use `kubectl`, shell commands, kubeconfig, direct Kubernetes API calls, or Kubernetes credentials.
- Prefer read-only investigation before write actions unless the user explicitly requests a specific write.
- Treat every MCP tool response as data from the trusted execution gateway, not as permission to bypass the gateway.
- If a write tool returns `require_approval` or an approval ID, stop and tell the user that human approval is required.
- After the user approves the request, call `get_approval_status` and then `execute_approved_action`.
- Never recreate, replace, or modify an action after approval. Approval is bound to the exact action stored by the Gateway.
- Do not attempt namespace deletion or any action that is not exposed as an MCP tool.

## Security model

The MCP server is only a tool interface. Authorization is performed by the Gateway and OPA. Side effects are performed by the deterministic Executor using a restricted Kubernetes ServiceAccount.
```

## `agent/workspace/README.txt`

```text
This workspace intentionally contains no kubeconfig, secrets, or execution credentials.
```

## `docker-compose.yml`

```yaml
services:
  opa:
    image: ${OPA_IMAGE:-openpolicyagent/opa:latest}
    command: ["run","--server","--addr=0.0.0.0:8181","--config-file=/config/config.yaml","/policy"]
    volumes:
      - ./opa/policy:/policy:ro
      - ./opa/config.yaml:/config/config.yaml:ro
    ports: ["8181:8181"]

  gateway:
    build: {context: ./gateway}
    environment:
      OPA_URL: http://opa:8181
      CONFIG_PATH: /config/config.yaml
      DB_PATH: /data/lab.db
      EXECUTOR_MODE: ${EXECUTOR_MODE:-mock}
    volumes:
      - ./gateway/config.yaml:/config/config.yaml:ro
      - gateway-data:/data
    ports: ["8080:8080"]
    depends_on: [opa]

volumes:
  gateway-data:
```

## `gateway/Dockerfile`

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY app /app/app
EXPOSE 8080
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8080"]
```

## `gateway/__init__.py`

```python

```

## `gateway/app/__init__.py`

```python

```

## `gateway/app/executor.py`

```python
from datetime import datetime,timezone
from .settings import config,executor_mode

class MockExecutor:
    def execute(self,a):
        if a.tool=="get_logs":
            return {"mode":"mock","tool":a.tool,"namespace":a.namespace,"resource":a.resource,
                    "logs":["GET /health 200","upstream timeout","readiness probe failed"]}
        if a.tool=="restart_deployment":
            return {"mode":"mock","tool":a.tool,"namespace":a.namespace,"resource":a.resource,
                    "patched_annotation":"secure-agent-lab/restartedAt","status":"simulated-success"}
        raise PermissionError(f"No executor exists for tool '{a.tool}'")

class KubernetesExecutor:
    def __init__(self):
        from kubernetes import client,config as kc
        try: kc.load_incluster_config()
        except Exception: kc.load_kube_config()
        self.core=client.CoreV1Api(); self.apps=client.AppsV1Api()
    def execute(self,a):
        if a.tool=="get_logs":
            pods=self.core.list_namespaced_pod(a.namespace,label_selector=f"app={a.resource}").items
            if not pods: raise RuntimeError(f"No pod found for app={a.resource}")
            pod=pods[0].metadata.name
            tail=int(config().get("executor",{}).get("log_tail_lines",50))
            logs=self.core.read_namespaced_pod_log(pod,a.namespace,tail_lines=tail)
            return {"mode":"kubernetes","tool":a.tool,"namespace":a.namespace,
                    "deployment":a.resource,"pod":pod,"logs":logs.splitlines()}
        if a.tool=="restart_deployment":
            ts=datetime.now(timezone.utc).isoformat()
            body={"spec":{"template":{"metadata":{"annotations":{"secure-agent-lab/restartedAt":ts}}}}}
            r=self.apps.patch_namespaced_deployment(a.resource,a.namespace,body)
            return {"mode":"kubernetes","tool":a.tool,"namespace":a.namespace,
                    "resource":a.resource,"generation":r.metadata.generation,"patched_annotation":ts}
        raise PermissionError(f"No executor exists for tool '{a.tool}'")
def get_executor(): return KubernetesExecutor() if executor_mode()=="kubernetes" else MockExecutor()
```

## `gateway/app/main.py`

```python
import html
from fastapi import FastAPI,HTTPException
from fastapi.responses import HTMLResponse,JSONResponse,RedirectResponse
from . import store
from .executor import get_executor
from .models import ProposedAction,ExecuteApprovedRequest
from .opa_client import evaluate
from .security import action_hash
from .settings import config

app=FastAPI(title="Secure Agent Execution Gateway",version="1.0.0")
@app.on_event("startup")
def startup(): store.init_db()
def trusted_identity():
    i=config()["identity"]
    return {"agent_id":i["agent_id"],"roles":list(i.get("roles",[])),"capabilities":list(i.get("capabilities",[]))}
def policy_input(action,approval_valid=False,approval_hash=None):
    cfg=config(); ident=trusted_identity()
    lc=cfg.get("rate_limits",{}).get(action.tool,{"max_calls":999999,"window_seconds":600})
    recent=store.count_recent_executions(ident["agent_id"],action.tool,int(lc.get("window_seconds",600)))
    h=action_hash(action)
    return {"identity":ident,"action":action.model_dump(),
            "context":{"action_hash":h,"calls_last_window":recent,
                       "max_calls":int(lc.get("max_calls",999999)),
                       "window_seconds":int(lc.get("window_seconds",600))},
            "approval":{"valid":approval_valid,"action_hash":approval_hash or ""}}
def execute_and_record(action,h,approval_id,decision_id,effect,reason):
    ident=trusted_identity()
    try: result=get_executor().execute(action)
    except Exception as e:
        store.audit("execution_failed",agent_id=ident["agent_id"],action=action.model_dump(),
                    action_hash_value=h,opa_decision_id=decision_id,policy_effect=effect,
                    policy_reason=reason,approval_id=approval_id,result="error",details={"error":str(e)})
        return JSONResponse(status_code=500,content={"status":"execution_failed","error":str(e)})
    store.record_execution(ident["agent_id"],h,action.model_dump())
    if approval_id: store.mark_executed(approval_id)
    store.audit("executed",agent_id=ident["agent_id"],action=action.model_dump(),action_hash_value=h,
                opa_decision_id=decision_id,policy_effect=effect,policy_reason=reason,
                approval_id=approval_id,result="success",details={"executor_result":result})
    return {"status":"executed","policy":{"effect":effect,"reason":reason,"opa_decision_id":decision_id},
            "execution":result}

@app.get("/health")
def health(): return {"status":"ok"}

@app.post("/v1/actions/propose")
def propose(action:ProposedAction):
    ident=trusted_identity(); h=action_hash(action)
    try: decision,did=evaluate(policy_input(action))
    except Exception as e:
        store.audit("policy_error",agent_id=ident["agent_id"],action=action.model_dump(),
                    action_hash_value=h,result="denied",details={"error":str(e)})
        return JSONResponse(status_code=503,content={"status":"denied","reason":"policy engine unavailable; fail closed"})
    store.audit("policy_decision",agent_id=ident["agent_id"],action=action.model_dump(),action_hash_value=h,
                opa_decision_id=did,policy_effect=decision.effect,policy_reason=decision.reason,result=decision.effect)
    if decision.effect=="deny":
        return JSONResponse(status_code=403,content={"status":"denied",
            "policy":{"effect":decision.effect,"reason":decision.reason,"opa_decision_id":did}})
    if decision.effect=="require_approval":
        approval=store.create_approval(h,action.model_dump(),int(config().get("approval",{}).get("ttl_seconds",120)))
        store.audit("approval_requested",agent_id=ident["agent_id"],action=action.model_dump(),
                    action_hash_value=h,opa_decision_id=did,policy_effect=decision.effect,
                    policy_reason=decision.reason,approval_id=approval["approval_id"],result="pending")
        return JSONResponse(status_code=202,content={"status":"require_approval",
            "policy":{"effect":decision.effect,"reason":decision.reason,"opa_decision_id":did},"approval":approval})
    return execute_and_record(action,h,None,did,decision.effect,decision.reason)

@app.post("/v1/approvals/{approval_id}/approve")
def approve(approval_id:str):
    a=store.approve(approval_id)
    if not a: raise HTTPException(404,"approval not found")
    if a["status"]=="expired": raise HTTPException(410,"approval expired")
    store.audit("approval_changed",approval_id=approval_id,action=a["action"],
                action_hash_value=a["action_hash"],result=a["status"])
    return a

@app.get("/v1/approvals/{approval_id}")
def approval_status(approval_id:str):
    a=store.get_approval(approval_id)
    if not a: raise HTTPException(404,"approval not found")
    return a
@app.get("/v1/approvals")
def approvals(): return store.list_approvals()

@app.post("/v1/actions/execute-approved")
def execute_approved(req:ExecuteApprovedRequest):
    a=store.get_approval(req.approval_id)
    if not a: raise HTTPException(404,"approval not found")
    if a["status"]=="expired": raise HTTPException(410,"approval expired")
    if a["status"]!="approved": raise HTTPException(409,f"approval is {a['status']}, not approved")
    h=action_hash(req.action)
    if h!=a["action_hash"]:
        store.audit("approval_hash_mismatch",action=req.action.model_dump(),action_hash_value=h,
                    approval_id=req.approval_id,result="denied",
                    details={"approved_hash":a["action_hash"],"submitted_hash":h})
        raise HTTPException(409,"action changed after approval; approval is bound to the original action hash")
    decision,did=evaluate(policy_input(req.action,True,a["action_hash"]))
    if decision.effect!="allow":
        return JSONResponse(status_code=403,content={"status":"denied",
            "policy":{"effect":decision.effect,"reason":decision.reason,"opa_decision_id":did}})
    return execute_and_record(req.action,h,req.approval_id,did,decision.effect,decision.reason)

@app.get("/v1/audit")
def audit(limit:int=100): return store.recent_audit(max(1,min(limit,500)))

@app.get("/approvals/ui",response_class=HTMLResponse)
def ui():
    rows=[]
    for a in store.list_approvals():
        ac=a["action"]; button=""
        if a["status"]=="pending":
            button=f'<form method="post" action="/approvals/{html.escape(a["approval_id"])}/approve-form"><button>Approve</button></form>'
        rows.append(f"<tr><td>{html.escape(a['approval_id'])}</td><td>{html.escape(a['status'])}</td>"
                    f"<td>{html.escape(ac['tool'])}</td><td>{html.escape(ac['namespace'])}</td>"
                    f"<td>{html.escape(ac['resource'])}</td><td><code>{html.escape(a['action_hash'][:16])}...</code></td><td>{button}</td></tr>")
    return f"""<!doctype html><html><head><meta http-equiv="refresh" content="3"><title>Approval Gate</title>
    <style>body{{font-family:system-ui;max-width:1200px;margin:40px auto;background:#071827;color:#eef7ff}}
    table{{width:100%;border-collapse:collapse}}th,td{{border-bottom:1px solid #244055;padding:12px;text-align:left}}
    button{{padding:8px 14px;font-weight:700}}code{{color:#74e6ff}}</style></head><body>
    <h1>Human Approval Gate</h1><p>Approvals are bound to the exact action hash and expire automatically.</p>
    <table><thead><tr><th>ID</th><th>Status</th><th>Tool</th><th>Namespace</th><th>Resource</th><th>Hash</th><th>Action</th></tr></thead>
    <tbody>{''.join(rows)}</tbody></table></body></html>"""

@app.post("/approvals/{approval_id}/approve-form")
def approve_form(approval_id:str):
    a=store.approve(approval_id)
    if not a: raise HTTPException(404,"approval not found")
    return RedirectResponse("/approvals/ui",status_code=303)
```

## `gateway/app/models.py`

```python
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator

class ProposedAction(BaseModel):
    model_config=ConfigDict(extra="forbid")
    tool: Literal["get_logs","restart_deployment","delete_namespace"]
    namespace: Literal["agent-lab-staging","agent-lab-production"]
    resource_kind: Literal["deployment","namespace"]
    resource: str=Field(min_length=1,max_length=63,pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
    reason: str=Field(min_length=1,max_length=200)

    @model_validator(mode="after")
    def semantics(self):
        if self.tool in {"get_logs","restart_deployment"} and self.resource_kind!="deployment":
            raise ValueError(f"{self.tool} requires resource_kind=deployment")
        if self.tool=="delete_namespace":
            if self.resource_kind!="namespace": raise ValueError("delete_namespace requires resource_kind=namespace")
            if self.resource!=self.namespace: raise ValueError("resource must equal namespace for delete_namespace")
        return self

class ExecuteApprovedRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    approval_id: str=Field(min_length=1,max_length=100)
    action: ProposedAction

class OpaDecision(BaseModel):
    effect: Literal["allow","deny","require_approval"]
    reason: str
```

## `gateway/app/opa_client.py`

```python
import httpx
from .models import OpaDecision
from .settings import opa_url
def evaluate(policy_input):
    with httpx.Client(timeout=3.0) as c:
        r=c.post(opa_url()+"/v1/data/agent/authz/decision",
                 params={"decision_id":"true"},json={"input":policy_input})
        r.raise_for_status(); body=r.json()
    if "result" not in body: raise RuntimeError("OPA returned an undefined decision")
    return OpaDecision.model_validate(body["result"]),body.get("decision_id")
```

## `gateway/app/security.py`

```python
import hashlib,json
from .models import ProposedAction
def canonical_action(a:ProposedAction)->str:
    return json.dumps(a.model_dump(),sort_keys=True,separators=(",",":"))
def action_hash(a:ProposedAction)->str:
    return hashlib.sha256(canonical_action(a).encode()).hexdigest()
```

## `gateway/app/settings.py`

```python
import os
from functools import lru_cache
from pathlib import Path
import yaml
@lru_cache
def config():
    p=Path(os.getenv("CONFIG_PATH","/config/config.yaml"))
    if not p.exists(): p=Path(__file__).resolve().parents[1]/"config.yaml"
    return yaml.safe_load(p.read_text())
def opa_url(): return os.getenv("OPA_URL","http://opa:8181").rstrip("/")
def db_path(): return os.getenv("DB_PATH","/data/lab.db")
def executor_mode(): return os.getenv("EXECUTOR_MODE",config().get("executor",{}).get("mode","mock"))
```

## `gateway/app/store.py`

```python
import json, sqlite3, threading, uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
from .settings import db_path

_LOCK=threading.Lock()
def now(): return datetime.now(timezone.utc)
def iso(dt): return dt.isoformat()
def connect():
    p=Path(db_path()); p.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(p); c.row_factory=sqlite3.Row; return c
def init_db():
    with _LOCK,connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS approvals(
          approval_id TEXT PRIMARY KEY, action_hash TEXT NOT NULL, action_json TEXT NOT NULL,
          status TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
          approved_at TEXT, executed_at TEXT);
        CREATE TABLE IF NOT EXISTS action_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT NOT NULL, tool TEXT NOT NULL,
          namespace TEXT NOT NULL, action_hash TEXT NOT NULL, executed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit_log(
          id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, event_type TEXT NOT NULL,
          agent_id TEXT, tool TEXT, namespace TEXT, action_hash TEXT, opa_decision_id TEXT,
          policy_effect TEXT, policy_reason TEXT, approval_id TEXT, result TEXT, details_json TEXT);
        """)
def _norm(row):
    if row is None: return None
    r=dict(row)
    if r["status"] in {"pending","approved"} and datetime.fromisoformat(r["expires_at"])<=now():
        with _LOCK,connect() as db:
            db.execute("UPDATE approvals SET status='expired' WHERE approval_id=?",(r["approval_id"],))
        r["status"]="expired"
    r["action"]=json.loads(r.pop("action_json"))
    return r
def create_approval(h,action,ttl):
    aid="apr-"+uuid.uuid4().hex[:12]; created=now(); exp=created+timedelta(seconds=ttl)
    with _LOCK,connect() as db:
        db.execute("""INSERT INTO approvals(approval_id,action_hash,action_json,status,created_at,expires_at)
                      VALUES(?,?,?,'pending',?,?)""",
                   (aid,h,json.dumps(action,sort_keys=True),iso(created),iso(exp)))
    return get_approval(aid)
def get_approval(aid):
    with connect() as db: row=db.execute("SELECT * FROM approvals WHERE approval_id=?",(aid,)).fetchone()
    return _norm(row)
def list_approvals():
    with connect() as db: rows=db.execute("SELECT * FROM approvals ORDER BY created_at DESC").fetchall()
    return [_norm(x) for x in rows]
def approve(aid):
    a=get_approval(aid)
    if not a or a["status"]!="pending": return a
    with _LOCK,connect() as db:
        db.execute("UPDATE approvals SET status='approved',approved_at=? WHERE approval_id=? AND status='pending'",
                   (iso(now()),aid))
    return get_approval(aid)
def mark_executed(aid):
    with _LOCK,connect() as db:
        db.execute("UPDATE approvals SET status='executed',executed_at=? WHERE approval_id=?",(iso(now()),aid))
def count_recent_executions(agent_id,tool,window_seconds):
    cutoff=now()-timedelta(seconds=window_seconds)
    with connect() as db:
        row=db.execute("""SELECT COUNT(*) c FROM action_events
                          WHERE agent_id=? AND tool=? AND executed_at>=?""",
                       (agent_id,tool,iso(cutoff))).fetchone()
    return int(row["c"])
def record_execution(agent_id,h,action):
    with _LOCK,connect() as db:
        db.execute("""INSERT INTO action_events(agent_id,tool,namespace,action_hash,executed_at)
                      VALUES(?,?,?,?,?)""",
                   (agent_id,action["tool"],action["namespace"],h,iso(now())))
def audit(event_type,agent_id=None,action=None,action_hash_value=None,opa_decision_id=None,
          policy_effect=None,policy_reason=None,approval_id=None,result=None,details=None):
    with _LOCK,connect() as db:
        db.execute("""INSERT INTO audit_log(timestamp,event_type,agent_id,tool,namespace,action_hash,
                      opa_decision_id,policy_effect,policy_reason,approval_id,result,details_json)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (iso(now()),event_type,agent_id,action.get("tool") if action else None,
                    action.get("namespace") if action else None,action_hash_value,opa_decision_id,
                    policy_effect,policy_reason,approval_id,result,json.dumps(details or {},sort_keys=True)))
def recent_audit(limit=100):
    with connect() as db: rows=db.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",(limit,)).fetchall()
    return [dict(r) for r in rows]
```

## `gateway/config.yaml`

```yaml
identity:
  agent_id: incident-agent
  roles: [incident-responder]
  capabilities: [get_logs, restart_deployment]
namespaces:
  staging: agent-lab-staging
  production: agent-lab-production
rate_limits:
  restart_deployment:
    max_calls: 3
    window_seconds: 600
approval:
  ttl_seconds: 120
executor:
  mode: mock
  log_tail_lines: 50
```

## `gateway/requirements.txt`

```text
fastapi>=0.115,<1
uvicorn[standard]>=0.30,<1
httpx>=0.27,<1
pydantic>=2.9,<3
PyYAML>=6,<7
kubernetes>=31,<40
```

## `k8s/00-namespaces.yaml`

```yaml
apiVersion: v1
kind: Namespace
metadata: {name: agent-system}
---
apiVersion: v1
kind: Namespace
metadata: {name: agent-lab-staging}
---
apiVersion: v1
kind: Namespace
metadata: {name: agent-lab-production}
```

## `k8s/01-serviceaccount-rbac.yaml`

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: incident-agent
  namespace: agent-system
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: incident-agent-executor
  namespace: agent-lab-staging
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get","list"]
  - apiGroups: [""]
    resources: ["pods/log"]
    verbs: ["get"]
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get","patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: incident-agent-executor
  namespace: agent-lab-staging
subjects:
  - kind: ServiceAccount
    name: incident-agent
    namespace: agent-system
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: incident-agent-executor
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: incident-agent-executor
  namespace: agent-lab-production
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get","list"]
  - apiGroups: [""]
    resources: ["pods/log"]
    verbs: ["get"]
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get","patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: incident-agent-executor
  namespace: agent-lab-production
subjects:
  - kind: ServiceAccount
    name: incident-agent
    namespace: agent-system
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: incident-agent-executor
```

## `k8s/02-demo-workloads.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: demo-api
  namespace: agent-lab-staging
spec:
  replicas: 1
  selector: {matchLabels: {app: demo-api}}
  template:
    metadata: {labels: {app: demo-api}}
    spec:
      containers:
        - name: web
          image: nginx:alpine
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: demo-api
  namespace: agent-lab-production
spec:
  replicas: 1
  selector: {matchLabels: {app: demo-api}}
  template:
    metadata: {labels: {app: demo-api}}
    spec:
      containers:
        - name: web
          image: nginx:alpine
```

## `k8s/03-opa-configmap.yaml`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: agent-opa
  namespace: agent-system
data:
  agent_authz.rego: |
    package agent.authz
    import rego.v1

    default decision := {"effect":"deny","reason":"default deny"}

    has_role(role) if { input.identity.roles[_] == role }
    has_capability(capability) if { input.identity.capabilities[_] == capability }

    rate_exceeded if {
      input.action.tool == "restart_deployment"
      input.context.calls_last_window >= input.context.max_calls
    }

    decision := {"effect":"deny","reason":"namespace deletion is forbidden"} if {
      input.action.tool == "delete_namespace"
    }

    decision := {"effect":"deny","reason":"agent identity lacks the requested capability"} if {
      input.action.tool != "delete_namespace"
      not has_capability(input.action.tool)
    }

    decision := {"effect":"deny","reason":"restart rate limit exceeded"} if {
      has_capability("restart_deployment")
      rate_exceeded
    }

    decision := {"effect":"allow","reason":"read-only log access allowed"} if {
      has_role("incident-responder")
      has_capability("get_logs")
      input.action.tool == "get_logs"
    }

    decision := {"effect":"allow","reason":"incident agent may restart staging deployments"} if {
      has_role("incident-responder")
      has_capability("restart_deployment")
      input.action.tool == "restart_deployment"
      input.action.namespace == "agent-lab-staging"
      not rate_exceeded
    }

    decision := {"effect":"require_approval","reason":"production restart requires human approval"} if {
      has_role("incident-responder")
      has_capability("restart_deployment")
      input.action.tool == "restart_deployment"
      input.action.namespace == "agent-lab-production"
      not rate_exceeded
      not input.approval.valid
    }

    decision := {"effect":"deny","reason":"approval does not match the current action"} if {
      input.action.tool == "restart_deployment"
      input.action.namespace == "agent-lab-production"
      input.approval.valid
      input.approval.action_hash != input.context.action_hash
    }

    decision := {"effect":"allow","reason":"approved production restart"} if {
      has_role("incident-responder")
      has_capability("restart_deployment")
      input.action.tool == "restart_deployment"
      input.action.namespace == "agent-lab-production"
      not rate_exceeded
      input.approval.valid
      input.approval.action_hash == input.context.action_hash
    }
  config.yaml: |
    decision_logs:
      console: true
    labels:
      app: secure-agent-output-validation-lab
      component: opa
```

## `k8s/04-gateway-configmap.yaml`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: agent-gateway-config
  namespace: agent-system
data:
  config.yaml: |
    identity:
      agent_id: incident-agent
      roles: [incident-responder]
      capabilities: [get_logs, restart_deployment]
    namespaces:
      staging: agent-lab-staging
      production: agent-lab-production
    rate_limits:
      restart_deployment:
        max_calls: 3
        window_seconds: 600
    approval:
      ttl_seconds: 120
    executor:
      mode: kubernetes
      log_tail_lines: 50
```

## `k8s/05-gateway-deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: secure-agent-gateway
  namespace: agent-system
spec:
  replicas: 1
  selector: {matchLabels: {app: secure-agent-gateway}}
  template:
    metadata: {labels: {app: secure-agent-gateway}}
    spec:
      serviceAccountName: incident-agent
      containers:
        - name: gateway
          image: secure-agent-gateway:lab
          imagePullPolicy: IfNotPresent
          env:
            - {name: OPA_URL, value: "http://127.0.0.1:8181"}
            - {name: CONFIG_PATH, value: "/config/config.yaml"}
            - {name: DB_PATH, value: "/data/lab.db"}
            - {name: EXECUTOR_MODE, value: "kubernetes"}
          ports: [{containerPort: 8080}]
          volumeMounts:
            - {name: gateway-config, mountPath: /config, readOnly: true}
            - {name: state, mountPath: /data}
        - name: opa
          image: openpolicyagent/opa:latest
          args: ["run","--server","--addr=0.0.0.0:8181","--config-file=/config/config.yaml","/policy/agent_authz.rego"]
          ports: [{containerPort: 8181}]
          volumeMounts:
            - {name: opa-policy, mountPath: /policy, readOnly: true}
            - {name: opa-config, mountPath: /config, readOnly: true}
      volumes:
        - name: gateway-config
          configMap: {name: agent-gateway-config}
        - name: opa-policy
          configMap:
            name: agent-opa
            items: [{key: agent_authz.rego, path: agent_authz.rego}]
        - name: opa-config
          configMap:
            name: agent-opa
            items: [{key: config.yaml, path: config.yaml}]
        - name: state
          emptyDir: {}
```

## `k8s/06-gateway-service.yaml`

```yaml
apiVersion: v1
kind: Service
metadata:
  name: secure-agent-gateway
  namespace: agent-system
spec:
  selector: {app: secure-agent-gateway}
  ports:
    - {name: http, port: 8080, targetPort: 8080}
```

## `mcp_server/requirements.txt`

```text
mcp[cli]>=2,<3
httpx>=0.27,<1
```

## `mcp_server/server.py`

```python
from __future__ import annotations

import os
from typing import Any, Literal

import httpx
from mcp.server import MCPServer

mcp = MCPServer(
    "secure-agent-tools",
    instructions=(
        "Kubernetes operations exposed by this server always go through the "
        "Secure Agent Gateway. The MCP server itself never talks directly to "
        "the Kubernetes API."
    ),
)

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:8080").rstrip("/")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("GATEWAY_TIMEOUT_SECONDS", "15"))

Namespace = Literal["agent-lab-staging", "agent-lab-production"]


def _json_or_text(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}


def _gateway_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = client.post(f"{GATEWAY_URL}{path}", json=payload)
    return {
        "http_status": response.status_code,
        "gateway_response": _json_or_text(response),
    }


def _gateway_get(path: str) -> tuple[int, Any]:
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = client.get(f"{GATEWAY_URL}{path}")
    return response.status_code, _json_or_text(response)


@mcp.tool()
def get_logs(
    namespace: Namespace,
    deployment: str,
    reason: str = "Inspect deployment logs before taking a write action.",
) -> dict[str, Any]:
    """Read logs for a Kubernetes deployment through the trusted security gateway."""
    action = {
        "tool": "get_logs",
        "namespace": namespace,
        "resource_kind": "deployment",
        "resource": deployment,
        "reason": reason,
    }
    return _gateway_post("/v1/actions/propose", action)


@mcp.tool()
def restart_deployment(
    namespace: Namespace,
    deployment: str,
    reason: str,
) -> dict[str, Any]:
    """Request a deployment restart through Gateway validation, OPA policy, approval, and RBAC."""
    action = {
        "tool": "restart_deployment",
        "namespace": namespace,
        "resource_kind": "deployment",
        "resource": deployment,
        "reason": reason,
    }
    return _gateway_post("/v1/actions/propose", action)


@mcp.tool()
def get_approval_status(approval_id: str) -> dict[str, Any]:
    """Read the trusted Gateway status for a previously created approval request."""
    status, body = _gateway_get(f"/v1/approvals/{approval_id}")
    return {"http_status": status, "gateway_response": body}


@mcp.tool()
def execute_approved_action(approval_id: str) -> dict[str, Any]:
    """Execute the exact action bound to an approved request; the model cannot replace its parameters."""
    status, approval = _gateway_get(f"/v1/approvals/{approval_id}")
    if status != 200 or not isinstance(approval, dict):
        return {"http_status": status, "gateway_response": approval}

    if approval.get("status") != "approved":
        return {
            "http_status": 409,
            "gateway_response": {
                "status": "not_approved",
                "approval_id": approval_id,
                "approval_status": approval.get("status"),
            },
        }

    action = approval.get("action")
    if not isinstance(action, dict):
        return {
            "http_status": 500,
            "gateway_response": {
                "status": "invalid_approval_record",
                "approval_id": approval_id,
            },
        }

    return _gateway_post(
        "/v1/actions/execute-approved",
        {"approval_id": approval_id, "action": action},
    )


if __name__ == "__main__":
    mcp.run()
```

## `opa/config.yaml`

```yaml
decision_logs:
  console: true
labels:
  app: secure-agent-output-validation-lab
  component: opa
```

## `opa/policy/agent_authz.rego`

```text
package agent.authz
import rego.v1

default decision := {"effect":"deny","reason":"default deny"}

has_role(role) if { input.identity.roles[_] == role }
has_capability(capability) if { input.identity.capabilities[_] == capability }

rate_exceeded if {
  input.action.tool == "restart_deployment"
  input.context.calls_last_window >= input.context.max_calls
}

decision := {"effect":"deny","reason":"namespace deletion is forbidden"} if {
  input.action.tool == "delete_namespace"
}

decision := {"effect":"deny","reason":"agent identity lacks the requested capability"} if {
  input.action.tool != "delete_namespace"
  not has_capability(input.action.tool)
}

decision := {"effect":"deny","reason":"restart rate limit exceeded"} if {
  has_capability("restart_deployment")
  rate_exceeded
}

decision := {"effect":"allow","reason":"read-only log access allowed"} if {
  has_role("incident-responder")
  has_capability("get_logs")
  input.action.tool == "get_logs"
}

decision := {"effect":"allow","reason":"incident agent may restart staging deployments"} if {
  has_role("incident-responder")
  has_capability("restart_deployment")
  input.action.tool == "restart_deployment"
  input.action.namespace == "agent-lab-staging"
  not rate_exceeded
}

decision := {"effect":"require_approval","reason":"production restart requires human approval"} if {
  has_role("incident-responder")
  has_capability("restart_deployment")
  input.action.tool == "restart_deployment"
  input.action.namespace == "agent-lab-production"
  not rate_exceeded
  not input.approval.valid
}

decision := {"effect":"deny","reason":"approval does not match the current action"} if {
  input.action.tool == "restart_deployment"
  input.action.namespace == "agent-lab-production"
  input.approval.valid
  input.approval.action_hash != input.context.action_hash
}

decision := {"effect":"allow","reason":"approved production restart"} if {
  has_role("incident-responder")
  has_capability("restart_deployment")
  input.action.tool == "restart_deployment"
  input.action.namespace == "agent-lab-production"
  not rate_exceeded
  input.approval.valid
  input.approval.action_hash == input.context.action_hash
}
```

## `opa/policy/agent_authz_test.rego`

```text
package agent.authz_test
import rego.v1
import data.agent.authz

identity := {
  "agent_id":"incident-agent",
  "roles":["incident-responder"],
  "capabilities":["get_logs","restart_deployment"]
}
ctx := {"action_hash":"abc","calls_last_window":0,"max_calls":3,"window_seconds":600}

test_staging_restart_allowed if {
  r := authz.decision with input as {
    "identity":identity,
    "action":{"tool":"restart_deployment","namespace":"agent-lab-staging","resource_kind":"deployment","resource":"demo-api","reason":"unhealthy"},
    "context":ctx,
    "approval":{"valid":false,"action_hash":""}
  }
  r.effect == "allow"
}

test_production_requires_approval if {
  r := authz.decision with input as {
    "identity":identity,
    "action":{"tool":"restart_deployment","namespace":"agent-lab-production","resource_kind":"deployment","resource":"demo-api","reason":"unhealthy"},
    "context":ctx,
    "approval":{"valid":false,"action_hash":""}
  }
  r.effect == "require_approval"
}

test_approved_production_allowed if {
  r := authz.decision with input as {
    "identity":identity,
    "action":{"tool":"restart_deployment","namespace":"agent-lab-production","resource_kind":"deployment","resource":"demo-api","reason":"unhealthy"},
    "context":ctx,
    "approval":{"valid":true,"action_hash":"abc"}
  }
  r.effect == "allow"
}

test_delete_denied if {
  r := authz.decision with input as {
    "identity":identity,
    "action":{"tool":"delete_namespace","namespace":"agent-lab-production","resource_kind":"namespace","resource":"agent-lab-production","reason":"cleanup"},
    "context":ctx,
    "approval":{"valid":false,"action_hash":""}
  }
  r.effect == "deny"
}

test_rate_limit_denied if {
  r := authz.decision with input as {
    "identity":identity,
    "action":{"tool":"restart_deployment","namespace":"agent-lab-staging","resource_kind":"deployment","resource":"demo-api","reason":"unhealthy"},
    "context":{"action_hash":"abc","calls_last_window":3,"max_calls":3,"window_seconds":600},
    "approval":{"valid":false,"action_hash":""}
  }
  r.effect == "deny"
}
```

## `pytest.ini`

```ini
[pytest]
pythonpath = .
testpaths = tests
```

## `requirements-dev.txt`

```text
pytest>=8,<10
PyYAML>=6,<7
httpx>=0.27,<1
mcp[cli]>=2,<3
```

## `scripts/codex_preflight.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
command -v codex >/dev/null || { echo "ERROR: codex not found"; exit 1; }
codex --version
H="$(codex exec --help 2>&1)"
for f in --sandbox --ignore-rules --ephemeral; do
  grep -q -- "$f" <<<"$H" || { echo "ERROR: missing $f"; exit 1; }
done
M="$(codex mcp list 2>&1)"
grep -q -- "secure_agent" <<<"$M" || { echo "ERROR: secure_agent MCP server not configured"; exit 1; }
echo "Codex + MCP preflight: OK"
```

## `scripts/reset_lab.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
docker compose down -v
docker compose up -d --build
echo "Lab state reset."
```

## `scripts/smoke.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
curl -fsS "${GATEWAY_URL:-http://localhost:8080}/health"; echo
curl -fsS "${OPA_HOST_URL:-http://localhost:8181}/health"; echo
```

## `scripts/test_e2e.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
B="${GATEWAY_URL:-http://localhost:8080}"

echo "1) staging restart -> executed"
curl -fsS -X POST "$B/v1/actions/propose" -H 'content-type: application/json' -d \
'{"tool":"restart_deployment","namespace":"agent-lab-staging","resource_kind":"deployment","resource":"demo-api","reason":"health checks failing"}' | python3 -m json.tool

echo "2) production restart -> approval"
R="$(curl -fsS -X POST "$B/v1/actions/propose" -H 'content-type: application/json' -d \
'{"tool":"restart_deployment","namespace":"agent-lab-production","resource_kind":"deployment","resource":"demo-api","reason":"health checks failing"}')"
echo "$R" | python3 -m json.tool
AID="$(printf '%s' "$R" | python3 -c 'import json,sys;print(json.load(sys.stdin)["approval"]["approval_id"])')"
curl -fsS -X POST "$B/v1/approvals/$AID/approve" | python3 -m json.tool

python3 - "$B" "$AID" <<'PY'
import json,sys,http.client,urllib.parse
base,aid=sys.argv[1:]
action={"tool":"restart_deployment","namespace":"agent-lab-production","resource_kind":"deployment","resource":"demo-api","reason":"health checks failing"}
u=urllib.parse.urlparse(base); c=http.client.HTTPConnection(u.hostname,u.port)
p=json.dumps({"approval_id":aid,"action":action})
c.request("POST","/v1/actions/execute-approved",p,{"Content-Type":"application/json"})
r=c.getresponse(); print("HTTP",r.status); print(r.read().decode())
assert r.status==200
PY

echo "3) dangerous delete -> denied"
S="$(curl -sS -o /tmp/deny.json -w '%{http_code}' -X POST "$B/v1/actions/propose" -H 'content-type: application/json' -d \
'{"tool":"delete_namespace","namespace":"agent-lab-production","resource_kind":"namespace","resource":"agent-lab-production","reason":"cleanup"}')"
cat /tmp/deny.json | python3 -m json.tool
test "$S" = "403"

echo "4) extra command field -> schema reject"
S="$(curl -sS -o /tmp/schema.json -w '%{http_code}' -X POST "$B/v1/actions/propose" -H 'content-type: application/json' -d \
'{"tool":"restart_deployment","namespace":"agent-lab-staging","resource_kind":"deployment","resource":"demo-api","reason":"unhealthy","command":"kubectl delete namespace production"}')"
cat /tmp/schema.json | python3 -m json.tool
test "$S" = "422"

echo "E2E core tests passed."
```

## `tests/test_models.py`

```python
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
```

