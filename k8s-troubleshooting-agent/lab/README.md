# Failure Lab

## Scenario A: Service selector mismatch

```bash
kubectl apply -f lab/broken-selector.yaml
kubectl -n agent-lab get pods -l app=demo-web
kubectl -n agent-lab get svc demo-web -o yaml
kubectl -n agent-lab get endpointslice -l kubernetes.io/service-name=demo-web -o yaml
```

The Deployment Pods are healthy, but the Service selector is `app=demo-web-broken`, so it selects no Pods and has no usable endpoints.

Ask the agent:

```text
Traffic to Service demo-web is failing. Diagnose the current Kubernetes state. Do not change anything. Follow Service -> EndpointSlice -> Pod evidence and tell me the most likely root cause.
```

A good investigation should use `inspect_service`, notice an empty backend set, and then compare the Service selector with Pod labels (possibly via `list_resources` for Pods).

Fix it:

```bash
kubectl apply -f lab/fixed-selector.yaml
```

## Scenario B: targetPort mismatch

After Scenario A is fixed:

```bash
kubectl apply -f lab/broken-targetport.yaml
```

Now EndpointSlices can exist, but the Service sends traffic to port `8080` while the demo container declares/listens on port `80`. Ask:

```text
Service demo-web has endpoints but requests still fail. Inspect the Service, EndpointSlice, and Pods and explain the likely port problem. Do not change anything.
```

Restore:

```bash
kubectl apply -f lab/fixed-selector.yaml
```
