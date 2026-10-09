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
