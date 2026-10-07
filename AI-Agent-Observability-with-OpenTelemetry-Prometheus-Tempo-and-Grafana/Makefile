.PHONY: up down ps logs test metrics run urls

up:
	docker compose up -d

down:
	docker compose down

ps:
	docker compose ps

logs:
	docker compose logs --tail=100

test:
	python3 -m unittest discover -s tests -v

metrics:
	curl -s http://localhost:9464/metrics | grep -E 'codex|agent' || true

urls:
	@echo "Grafana:    http://localhost:3000"
	@echo "Prometheus: http://localhost:9090"
	@echo "Tempo:      http://localhost:3200"
	@echo "OTel HTTP:  http://localhost:4318"

run:
	python3 agent/codex_agent_monitor.py \
	  --workdir ./demo-workspace \
	  --trace-tool-details \
	  --prompt "Use shell tools to inspect this directory. Run pwd, list the files, read demo.txt, then summarize what you found. Do not modify files."
