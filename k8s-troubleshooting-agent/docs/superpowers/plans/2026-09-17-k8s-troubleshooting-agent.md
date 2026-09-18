# Kubernetes Troubleshooting Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a testable read-only Kubernetes troubleshooting agent with fixed target-namespace isolation and OpenAI function calling.

**Architecture:** Kubernetes access is isolated behind a gateway whose target namespace comes only from configuration. The model sees a narrow set of read-only function tools, while InspectorService correlates resources and RBAC independently limits credentials.

**Tech Stack:** Python 3.11+, FastAPI, OpenAI Responses API, Kubernetes Python client, pytest, Kubernetes RBAC.

**Spec:** `docs/superpowers/specs/2026-09-17-k8s-troubleshooting-agent-design.md`

## Global Constraints

- No tool accepts a namespace argument.
- No Secrets, `pods/exec`, mutation verbs, Nodes, Namespaces, or RBAC administration.
- IngressClass and StorageClass are cluster-scoped read-only metadata.
- PersistentVolume access is off by default and, when enabled, is `get` only.
- Every production feature is covered by a failing unit test before implementation.

---

### Task 1: Policy and tool contracts

**Files:**
- Create: `app/policy.py`
- Create: `app/tool_schemas.py`
- Test: `tests/unit/test_tool_schemas.py`

**Interfaces:**
- Produces: `build_tool_schemas(enable_pv_lookup: bool) -> list[dict]`
- Produces: resource/name/tail-line validation helpers used by the registry.

- [ ] Write tests asserting tool schemas expose no namespace argument and PV tools are opt-in.
- [ ] Run `PYTHONPATH=. pytest -q tests/unit/test_tool_schemas.py` and verify failure before implementation.
- [ ] Implement the allowlists, validators, and strict function schemas.
- [ ] Re-run the test and verify PASS.

### Task 2: Kubernetes gateway and inspectors

**Files:**
- Create: `app/k8s_gateway.py`
- Create: `app/inspectors.py`
- Test: `tests/unit/test_inspectors.py`

**Interfaces:**
- `list_resource(resource: str, label_selector: str | None = None) -> list[dict]`
- `get_resource(resource: str, name: str) -> dict`
- `read_pod_logs(pod_name: str, container: str | None, tail_lines: int) -> str`
- `list_events(kind: str | None, name: str | None) -> list[dict]`

- [ ] Write fake-gateway tests for Service, Ingress, PVC, and workload correlation.
- [ ] Run `PYTHONPATH=. pytest -q tests/unit/test_inspectors.py` and verify failure before implementation.
- [ ] Implement typed Kubernetes API calls with fixed `TARGET_NAMESPACE` and compact serialization.
- [ ] Implement Inspectors for Pod, Service, Ingress, PVC, and workloads.
- [ ] Re-run the tests and verify PASS.

### Task 3: Tool registry and LLM loop

**Files:**
- Create: `app/tool_registry.py`
- Create: `app/agent.py`
- Test: `tests/unit/test_registry.py`
- Test: `tests/unit/test_agent_loop.py`

**Interfaces:**
- `ToolRegistry.execute(name: str, arguments: dict) -> Any`
- `KubernetesTroubleshootingAgent.run(message: str) -> str`

- [ ] Write tests proving unexpected arguments such as `namespace` are rejected before Kubernetes is called.
- [ ] Write a fake Responses API test: first response emits `function_call`, second receives `function_call_output` and returns text.
- [ ] Run the focused tests and verify failure before implementation.
- [ ] Implement registry dispatch and the bounded function-calling loop using `previous_response_id` and `call_id`.
- [ ] Re-run focused tests and verify PASS.

### Task 4: Service runtime and Kubernetes deployment

**Files:**
- Create: `app/config.py`, `app/bootstrap.py`, `app/api.py`
- Create: `Dockerfile`, `pyproject.toml`
- Create: `manifests/00-agent-system-namespace.yaml` through `manifests/09-service.yaml`
- Create: `scripts/verify-rbac.sh`

**Interfaces:**
- HTTP `GET /healthz`
- HTTP `POST /v1/ask` with `{ "message": "..." }`

- [ ] Add configuration tests proving `ENABLE_PV_LOOKUP` defaults false.
- [ ] Implement FastAPI bootstrap and rootless container image.
- [ ] Add namespaced Role/RoleBinding and minimal cluster metadata ClusterRole/ClusterRoleBinding.
- [ ] Add optional PV `get` permission in separate manifests.
- [ ] Run `python -m compileall -q app` and the complete unit suite.

### Task 5: Failure lab and live tests

**Files:**
- Create: `lab/broken-selector.yaml`, `lab/fixed-selector.yaml`, `lab/broken-targetport.yaml`
- Create: `tests/integration/test_k8s_live.py`
- Create: `tests/integration/test_agent_live.py`

**Interfaces:**
- `RUN_K8S_INTEGRATION=1` enables real-cluster tests.
- `RUN_LLM_INTEGRATION=1` additionally enables a real model/tool-call test.

- [ ] Deploy the selector-mismatch lab and verify Pods are healthy while the Service has no usable endpoints.
- [ ] Ask the agent to diagnose Service -> EndpointSlice -> Pod evidence without mutation.
- [ ] Apply `lab/fixed-selector.yaml` and verify endpoints appear.
- [ ] Apply `lab/broken-targetport.yaml` and ask the agent to compare Service targetPort with Pod/container evidence.
- [ ] Restore the fixed Service and run the opt-in live tests.
