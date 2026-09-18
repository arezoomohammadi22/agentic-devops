# Manifests

The example target is `agent-lab` and the agent runs in `k8s-agent-system`.

For a real target, change `metadata.namespace` in `02-target-role.yaml` and `03-target-rolebinding.yaml`, and change `TARGET_NAMESPACE` in `08-deployment.yaml`. Keep the ServiceAccount subject namespace as `k8s-agent-system`.

Apply the normal files only:

```bash
kubectl apply -f 00-agent-system-namespace.yaml
kubectl apply -f 01-serviceaccount.yaml
kubectl apply -f 02-target-role.yaml
kubectl apply -f 03-target-rolebinding.yaml
kubectl apply -f 04-cluster-metadata-role.yaml
kubectl apply -f 05-cluster-metadata-rolebinding.yaml
kubectl apply -f 08-deployment.yaml
kubectl apply -f 09-service.yaml
```

Do **not** apply `06` or `07` unless you intentionally enable PV lookup. PVs are cluster-scoped.
