# Kubernetes Troubleshooting Agent Design

## Goal

Build a read-only LLM-assisted Kubernetes troubleshooting service that is hard-scoped to one configured target namespace for namespaced resources, while allowing only minimal cluster-scoped metadata reads required for Ingress and storage diagnosis.

## Security model

The LLM never receives a `namespace` argument in any tool schema. The Python gateway owns `TARGET_NAMESPACE`, and all namespaced API calls use that value. Kubernetes RBAC independently enforces the same scope with a Role and RoleBinding. Secrets, pod exec, mutation verbs, Nodes, Namespaces, RBAC objects, and arbitrary shell execution are not exposed.

IngressClass and StorageClass are cluster-scoped and are granted read-only `get/list`. PersistentVolume access is disabled by default. An optional ClusterRole grants only `get` on PVs; the application then reads PV names obtained from PVCs in the target namespace.

## Components

- `RealKubernetesGateway`: the only layer that talks to the Kubernetes Python client.
- `InspectorService`: builds structured troubleshooting evidence across related resources.
- `ToolRegistry`: validates tool names and arguments and dispatches to safe code paths.
- `tool_schemas.py`: defines the exact functions available to the model; no namespace parameter exists.
- `KubernetesTroubleshootingAgent`: OpenAI Responses API loop that executes function calls and returns tool outputs to the model.
- `FastAPI`: exposes `/healthz` and `/v1/ask`.

## Diagnostic paths

- Ingress -> IngressClass -> Service -> EndpointSlice/Endpoints -> Pods -> Events/logs.
- Service -> selector -> EndpointSlice/Endpoints -> matching Pods -> Events.
- Pod -> status -> Events -> optional logs.
- PVC -> StorageClass -> Events -> optional bound PV.
- Workload -> selector -> Pods -> Events.

## Testing

Unit tests use fake Kubernetes and OpenAI clients. Live Kubernetes and live LLM tests are opt-in through environment flags. A lab manifest intentionally creates a Service selector mismatch, then a second variant creates a targetPort mismatch.
