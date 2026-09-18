# Kubernetes Troubleshooting Agent

A small, read-only Kubernetes troubleshooting agent written in Python. The LLM decides **which diagnostic tool to call**; the application and Kubernetes RBAC decide **what it is actually allowed to read**.

The important security property is that the model never receives a `namespace` parameter. `TARGET_NAMESPACE` is owned by the backend, and every namespaced Kubernetes API call uses that fixed value.

## 1. Architecture

```text
User / API client
      |
      v
FastAPI POST /v1/ask
      |
      v
OpenAI Responses API
      |
      | function_call
      v
ToolRegistry  <---- hard allowlist / argument validation
      |
      v
InspectorService
      |
      v
RealKubernetesGateway
      |
      v
ServiceAccount + Kubernetes RBAC
      |
      +---- namespaced resources: TARGET_NAMESPACE only
      |
      +---- cluster metadata: IngressClass + StorageClass read-only
```

The LLM never runs `kubectl`, never receives a shell, and never receives arbitrary Kubernetes API access.

## 2. What the agent can read

Namespaced resources in `TARGET_NAMESPACE`:

- Pods
- Pod logs
- Services
- legacy Endpoints
- EndpointSlices
- Ingresses
- Deployments
- ReplicaSets
- StatefulSets
- DaemonSets
- Jobs
- CronJobs
- PVCs
- ConfigMaps
- Events
- NetworkPolicies
- HPAs
- PodDisruptionBudgets
- ResourceQuotas
- LimitRanges

Cluster-scoped read-only metadata:

- IngressClasses
- StorageClasses

Disabled by default:

- PersistentVolumes

Not available to the agent:

- Secrets
- `pods/exec`
- create/update/patch/delete operations
- Nodes
- Namespaces
- Role / ClusterRole administration
- arbitrary shell commands

## 3. Why PV lookup is optional

`PersistentVolumeClaim` is namespaced, but `PersistentVolume` is cluster-scoped. Strict RBAC cannot say “allow PVs belonging only to PVCs in namespace X” because the PV itself has no namespace.

Therefore the base deployment does not grant PV access. If you explicitly enable it, the optional ClusterRole grants only `get` on PVs, not `list`, and the application reads only PV names found in PVCs from the configured target namespace.

This is still a weaker isolation boundary than having no PV permission at all, so leave it disabled unless you need it.

## 4. Tool model exposed to the LLM

The model receives these function tools:

```text
list_resources(resource)
get_resource(resource, name)
get_pod_logs(pod_name, container, tail_lines)
get_events(kind, name)
inspect_pod(name, include_logs, container, tail_lines)
inspect_service(name)
inspect_ingress(name)
inspect_pvc(name)
inspect_workload(resource, name)
```

When PV lookup is enabled, one extra tool appears:

```text
list_persistent_volumes_for_namespace()
```

There is deliberately no tool like:

```text
kubectl(command)
run_shell(command)
list_resources(namespace, resource)
```

## 5. What “describe” means here

`kubectl describe` is not a Kubernetes permission. It is a client-side composition of several API reads.

This project creates structured describe-like inspectors instead. For example:

```text
inspect_service("demo-web")
    |
    +-- Service
    +-- EndpointSlices
    +-- legacy Endpoints
    +-- Pods selected by Service selector
    +-- Service Events
```

and:

```text
inspect_ingress("demo-web")
    |
    +-- Ingress
    +-- IngressClass
    +-- backend Service(s)
          |
          +-- EndpointSlices
          +-- Endpoints
          +-- matching Pods
    +-- Ingress Events
```

That gives the model cleaner evidence than parsing human-oriented `kubectl describe` text.

## 6. How the LLM enters the flow

The project uses the OpenAI Responses API with custom function tools.

The first request sends the user question plus the tool schemas:

```python
response = client.responses.create(
    model=model,
    instructions=instructions,
    input=user_message,
    tools=tools,
    tool_choice="auto",
)
```

If the model returns a `function_call`, the application executes the named safe Python function. The tool result is then returned to the model as a `function_call_output` associated with the original `call_id`:

```python
response = client.responses.create(
    model=model,
    previous_response_id=response.id,
    input=[
        {
            "type": "function_call_output",
            "call_id": call.call_id,
            "output": json.dumps(tool_result),
        }
    ],
    tools=tools,
    tool_choice="auto",
)
```

The loop stops when there are no more function calls and the model returns final text. `MAX_TOOL_ROUNDS` bounds the loop so a bad model/tool interaction cannot run forever.

## 7. Repository structure

```text
k8s-troubleshooting-agent/
├── app/
│   ├── agent.py            # Responses API tool loop
│   ├── api.py              # FastAPI endpoints
│   ├── bootstrap.py        # wires settings, K8s, tools and OpenAI
│   ├── config.py           # environment configuration
│   ├── inspectors.py       # Service/Ingress/Pod/PVC/workload correlation
│   ├── k8s_gateway.py      # Kubernetes Python client adapter
│   ├── policy.py           # allowlists and validation
│   ├── tool_registry.py    # safe function dispatcher
│   └── tool_schemas.py     # exact tools visible to the LLM
├── manifests/              # ServiceAccount, RBAC, Deployment, Service
├── lab/                    # intentionally broken Kubernetes resources
├── scripts/                # local run, secret creation, RBAC verification
├── tests/unit/             # fake K8s/OpenAI tests
├── tests/integration/      # opt-in live cluster / live LLM tests
├── Dockerfile
├── pyproject.toml
└── .env.example
```

## 8. Local development

Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Set configuration:

```bash
export TARGET_NAMESPACE=agent-lab
export OPENAI_API_KEY='...'
export OPENAI_MODEL=gpt-5.6-sol
export LOCAL_KUBECONFIG=true
export ENABLE_PV_LOOKUP=false
```

Run the unit tests:

```bash
pytest -q tests/unit
```

Run the API locally against your current kubeconfig:

```bash
./scripts/run-local.sh
```

Check health:

```bash
curl http://127.0.0.1:8080/healthz
```

Ask the agent:

```bash
curl -sS http://127.0.0.1:8080/v1/ask \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "Inspect Service demo-web. Why does it have no working endpoints? Do not change anything."
  }'
```

## 9. Deploy the failure lab

Start with the intentional Service selector mismatch:

```bash
kubectl apply -f lab/broken-selector.yaml
kubectl -n agent-lab get pods
kubectl -n agent-lab get svc demo-web -o yaml
kubectl -n agent-lab get endpointslice \
  -l kubernetes.io/service-name=demo-web \
  -o yaml
```

Expected state:

```text
Deployment labels:  app=demo-web
Service selector:    app=demo-web-broken
Result:              Service selects zero Pods
```

This is a good first diagnostic because the Agent can prove the problem without shell access inside any container.

## 10. Deploy RBAC

The example assumes:

```text
Agent namespace:  k8s-agent-system
Target namespace: agent-lab
ServiceAccount:   k8s-troubleshooter
```

Apply:

```bash
kubectl apply -f manifests/00-agent-system-namespace.yaml
kubectl apply -f manifests/01-serviceaccount.yaml
kubectl apply -f manifests/02-target-role.yaml
kubectl apply -f manifests/03-target-rolebinding.yaml
kubectl apply -f manifests/04-cluster-metadata-role.yaml
kubectl apply -f manifests/05-cluster-metadata-rolebinding.yaml
```

For a different target namespace, change the namespace in:

```text
manifests/02-target-role.yaml
manifests/03-target-rolebinding.yaml
manifests/08-deployment.yaml -> TARGET_NAMESPACE
```

Do not change the ServiceAccount subject namespace in the RoleBinding; the Agent ServiceAccount remains in `k8s-agent-system`.

## 11. Verify RBAC before running the model

Run:

```bash
./scripts/verify-rbac.sh agent-lab
```

Expected YES:

```text
list pods
get pods/log
list services
list endpointslices.discovery.k8s.io
list ingresses.networking.k8s.io
list persistentvolumeclaims
list storageclasses.storage.k8s.io
list ingressclasses.networking.k8s.io
```

Expected NO:

```text
list secrets
create pods
delete pods
create pods/exec
list nodes
list namespaces
list persistentvolumes
```

This test matters because prompt instructions are not a security boundary; Kubernetes authorization is.

## 12. Build and deploy the Agent

Build the image:

```bash
docker build -t k8s-troubleshooting-agent:0.1.0 .
```

For kind:

```bash
kind load docker-image k8s-troubleshooting-agent:0.1.0
```

For minikube:

```bash
minikube image load k8s-troubleshooting-agent:0.1.0
```

For a remote cluster, push the image to your registry and update `image:` in `manifests/08-deployment.yaml`.

Create the OpenAI API key Secret without putting the key in Git:

```bash
export OPENAI_API_KEY='...'
./scripts/create-openai-secret.sh
```

Deploy:

```bash
kubectl apply -f manifests/08-deployment.yaml
kubectl apply -f manifests/09-service.yaml
kubectl -n k8s-agent-system rollout status deployment/k8s-troubleshooting-agent
```

Port-forward:

```bash
kubectl -n k8s-agent-system port-forward svc/k8s-troubleshooting-agent 8080:80
```

Then ask:

```bash
curl -sS http://127.0.0.1:8080/v1/ask \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "Traffic to Service demo-web is failing. Diagnose the current state. Follow Service to EndpointSlice to Pods. Do not change anything."
  }'
```

## 13. Expected investigation for the selector failure

A reasonable tool path is:

```text
User problem
   |
   v
inspect_service(name="demo-web")
   |
   +-- Service selector = app=demo-web-broken
   +-- EndpointSlice contains no usable endpoints
   +-- matching Pods = []
   |
   v
list_resources(resource="pods")
   |
   +-- demo-web-* Pods have label app=demo-web
   |
   v
LLM conclusion
   |
   +-- Service selector does not match Pod labels
```

The model should cite the actual resource evidence and must not claim it fixed anything.

Fix manually:

```bash
kubectl apply -f lab/fixed-selector.yaml
```

Then verify:

```bash
kubectl -n agent-lab get endpointslice \
  -l kubernetes.io/service-name=demo-web \
  -o wide
```

## 14. Second failure: targetPort mismatch

Once the selector is correct:

```bash
kubectl apply -f lab/broken-targetport.yaml
```

The Service now selects the Pods, but it sends traffic to `targetPort: 8080`; the demo nginx container uses port `80`.

Ask:

```text
Service demo-web has endpoints but requests still fail. Inspect the Service, EndpointSlice and Pods and explain the likely port problem. Do not change anything.
```

Restore:

```bash
kubectl apply -f lab/fixed-selector.yaml
```

## 15. Test layers

### A. Unit tests — no cluster, no API bill

```bash
pytest -q tests/unit
```

These verify:

- no namespace argument exists in the model tool contracts
- PV access is opt-in
- unexpected tool arguments are rejected
- disallowed resources such as Secrets cannot be requested
- Service/Ingress/PVC inspectors correlate evidence correctly
- the Responses API function-call loop returns tool results using the correct `call_id`

### B. Live Kubernetes integration — no LLM required

Use your local kubeconfig:

```bash
export TARGET_NAMESPACE=agent-lab
export LOCAL_KUBECONFIG=true
export RUN_K8S_INTEGRATION=1
pytest -q tests/integration/test_k8s_live.py
```

This proves the real Kubernetes Python client can read the configured resources.

### C. Live LLM + live Kubernetes

```bash
export TARGET_NAMESPACE=agent-lab
export LOCAL_KUBECONFIG=true
export OPENAI_API_KEY='...'
export OPENAI_MODEL=gpt-5.6-sol
export RUN_K8S_INTEGRATION=1
export RUN_LLM_INTEGRATION=1
pytest -q tests/integration/test_agent_live.py -s
```

This is a smoke test, not a deterministic correctness test. LLM wording and exact tool order can vary.

For diagnostic quality, use the failure lab and inspect whether the final answer is grounded in the actual Service selector, EndpointSlice state, Pod labels, ports, Events, and logs.

## 16. How to evaluate the Agent

Do not grade only the final sentence. Record the tool trace and evaluate these properties:

1. **Scope safety** — no request can move the Agent to another namespace.
2. **Evidence collection** — it calls tools before making a live-state claim.
3. **Dependency tracing** — it follows Kubernetes relationships instead of looking at one object in isolation.
4. **Root-cause quality** — it distinguishes evidence from hypotheses.
5. **No mutation** — it never claims to restart, patch, delete, scale, or exec.
6. **Efficiency** — it reaches the diagnosis without repeatedly listing unrelated resources.

A simple test dataset can contain prompts such as:

```text
Why does Service demo-web have no endpoints?
Why is Ingress demo-web returning 503?
Why is Pod api-xxx Pending?
Why is PVC data Pending?
Why does a Deployment have zero Ready replicas?
Service has endpoints but connection still fails; check ports.
```

For each scenario, keep a known expected root cause and compare the evidence the Agent gathered against that expected cause.

## 17. Adding a new safe tool

Use this sequence:

1. Decide whether the Kubernetes object is namespaced or cluster-scoped.
2. Add only the minimum RBAC verbs.
3. Add a failing unit test.
4. Add the gateway method or mapping.
5. Add argument validation in `ToolRegistry`.
6. Add the function schema with `additionalProperties: false`.
7. Do not add a namespace field.
8. Run the unit suite.
9. Run `kubectl auth can-i` checks for both intended YES and intended NO cases.
10. Only then expose it to the LLM.

## 18. Production hardening ideas

Before using this against sensitive production workloads, consider:

- network policies around the Agent Pod
- API authentication in front of `/v1/ask`
- per-user authorization before sending questions to the Agent
- audit logs for user question, tool name, arguments, result size, and final answer
- rate limits and per-request tool-call limits
- redaction of application logs before sending them to an external model
- a maximum serialized tool-output size
- separate ServiceAccounts per tenant/namespace rather than dynamically changing `TARGET_NAMESPACE`
- no PV permission unless the use case truly needs it
- an explicit evaluation suite for every new diagnostic tool

## 19. Official references

- Kubernetes RBAC: https://kubernetes.io/docs/reference/access-authn-authz/rbac/
- EndpointSlice API: https://kubernetes.io/docs/reference/kubernetes-api/discovery/endpoint-slice-v1/
- OpenAI Responses API: https://developers.openai.com/api/reference/cli/resources/responses/methods/create

The repository intentionally keeps the LLM orchestration small so you can see every security boundary and every Kubernetes API call rather than hiding them behind a large agent framework.
