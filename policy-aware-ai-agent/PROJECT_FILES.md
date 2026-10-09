# Project Files

This ZIP contains the complete MCP-enabled reference implementation:

- `agent/` — Codex runtime wrapper and agent instructions
- `mcp_server/` — MCP v2 tool server; tools call the trusted Gateway, never Kubernetes directly
- `gateway/` — FastAPI trust boundary, validation, approval store, audit, and deterministic executor
- `opa/` — Rego authorization policy and tests
- `k8s/` — namespaces, RBAC, demo workloads, ConfigMaps, Gateway+OPA deployment, Service
- `scripts/` — preflight, local smoke/E2E, reset, and Codex MCP configuration helpers
- `tests/` — Python validation/hash tests
- `README.md` — full architecture and step-by-step guide
- `docs/SECURE_AI_AGENT_MCP_KUBERNETES_GUIDE.md` — copy of the long-form guide

The MCP-enabled runtime intentionally does not use the old planner-only `tools.yaml` + `action.schema.json` path. MCP tool schemas replace that top-level tool interface, while Gateway validation remains mandatory.
