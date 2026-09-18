#!/usr/bin/env bash
set -euo pipefail

TARGET_NAMESPACE="${1:-agent-lab}"
SA="system:serviceaccount:k8s-agent-system:k8s-troubleshooter"

can() {
  local verb="$1" resource="$2" extra="${3:-}"
  if [[ -n "$extra" ]]; then
    kubectl auth can-i "$verb" "$resource" $extra --as="$SA"
  else
    kubectl auth can-i "$verb" "$resource" -n "$TARGET_NAMESPACE" --as="$SA"
  fi
}

echo "== Expected YES =="
printf "list pods: "; can list pods
printf "get pod logs: "; can get pods/log
printf "list services: "; can list services
printf "list endpointslices: "; can list endpointslices.discovery.k8s.io
printf "list ingresses: "; can list ingresses.networking.k8s.io
printf "list PVCs: "; can list persistentvolumeclaims
printf "list StorageClasses: "; kubectl auth can-i list storageclasses.storage.k8s.io --as="$SA"
printf "list IngressClasses: "; kubectl auth can-i list ingressclasses.networking.k8s.io --as="$SA"

echo
echo "== Expected NO =="
printf "list secrets: "; can list secrets
printf "create pods: "; can create pods
printf "delete pods: "; can delete pods
printf "create pod/exec: "; can create pods/exec
printf "list nodes: "; kubectl auth can-i list nodes --as="$SA"
printf "list namespaces: "; kubectl auth can-i list namespaces --as="$SA"
printf "list PVs: "; kubectl auth can-i list persistentvolumes --as="$SA"
