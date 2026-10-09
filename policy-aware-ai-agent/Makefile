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
