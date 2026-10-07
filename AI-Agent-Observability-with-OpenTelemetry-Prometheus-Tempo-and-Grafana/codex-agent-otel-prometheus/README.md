# Codex Agent Observability v3

این پروژه مسیر کامل **Metrics + Traces** یک اجرای واقعی Codex CLI را نشان می‌دهد.

## معماری

```text
Codex CLI
   │
   │ codex exec --json
   ▼
Python monitoring wrapper
   │
   │ OpenTelemetry SDK
   │
   ├── Metrics ── OTLP/HTTP ──┐
   │                           │
   └── Traces ─── OTLP/HTTP ──┤
                               ▼
                      OpenTelemetry Collector
                         │             │
                         │             │
                 Prometheus Exporter  OTLP
                         │             │
                         ▼             ▼
                    Prometheus       Tempo
                         │             │
                         └──────┬──────┘
                                ▼
                              Grafana
```

- **Prometheus**: aggregate metrics
- **Tempo**: trace storage
- **Grafana**: dashboard + trace waterfall
- **OpenTelemetry Collector**: telemetry routing
- **Python Wrapper**: instrumentation around real `codex exec --json`

---

## 1. Prerequisites

```bash
codex --version
docker --version
docker compose version
python3 --version
```

Codex باید از قبل روی Host نصب و Login شده باشد.

---

## 2. Start the stack

```bash
docker compose up -d
```

یا:

```bash
make up
```

Check:

```bash
docker compose ps
```

Services:

```text
Grafana     http://localhost:3000
Prometheus  http://localhost:9090
Tempo       http://localhost:3200
OTel HTTP   http://localhost:4318
OTel gRPC   localhost:4317
Metrics     http://localhost:9464/metrics
```

Grafana local demo login:

```text
username: admin
password: admin
```

اگر سرور از اینترنت قابل دسترس است، قبل از expose کردن پورت 3000 پسورد را تغییر بده:

```bash
export GRAFANA_ADMIN_PASSWORD='a-strong-password'
docker compose up -d
```

---

## 3. Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate

pip install -r agent/requirements.txt
```

---

## 4. Run the real Codex agent

Safe read-only demo:

```bash
python agent/codex_agent_monitor.py \
  --workdir ./demo-workspace \
  --trace-tool-details \
  --prompt "Use shell tools to inspect this directory. Run pwd, list the files, read demo.txt, then summarize what you found. Do not modify files."
```

Expected console output:

```text
[tool:start] shell
[tool:done] shell
...

Codex exit code: 0
Trace ID: 0123456789abcdef...
```

`--trace-tool-details` فقط برای Demo روشن شده است تا commandهای harmless مثل `pwd` و `ls` را داخل Span ببینی.

برای پروژه واقعی بهتر است این flag را حذف کنی، چون command/tool content می‌تواند اطلاعات حساس داشته باشد.

---

# What gets traced?

هر Codex execution یک Root Span است:

```text
codex.run
```

هر turn:

```text
codex.turn
```

و هر Tool Call:

```text
codex.tool.shell
codex.tool.<tool-type>
```

در نتیجه یک Trace در Grafana تقریباً این شکل را دارد:

```text
codex.run
│
└── codex.turn
    ├── codex.tool.shell
    ├── codex.tool.shell
    ├── codex.tool.shell
    └── codex.tool.shell
```

هر Tool span شامل اطلاعاتی مثل:

```text
codex.tool.type
codex.tool.duration_seconds
codex.tool.denied
codex.item.id
```

است.

در حالت `--trace-tool-details` یک detail محدودشده هم اضافه می‌شود.

---

## 5. Open Grafana

```text
http://SERVER-IP:3000
```

Login:

```text
admin / admin
```

Dashboard از قبل Provision شده:

```text
AI Agent Observability
  └── Codex Agent Observability
```

در Dashboard می‌بینی:

- total Codex runs
- total tool calls
- failures
- active runs
- tool call rate
- p95 tool duration
- denied actions

---

## 6. See the full agent path

در Grafana:

```text
Explore
  ↓
Tempo
```

این TraceQL را اجرا کن:

```traceql
{ resource.service.name = "codex-agent-monitor" }
```

Trace موردنظر را باز کن.

حالا Waterfall را می‌بینی:

```text
codex.run
  └─ codex.turn
       ├─ codex.tool.shell
       ├─ codex.tool.shell
       └─ codex.tool.shell
```

Duration هر Span، Error status و Attributeها قابل مشاهده هستند.

TraceQL service filter بر اساس `resource.service.name` در Tempo/Grafana پشتیبانی می‌شود.

---

## 7. Search by Trace ID

Wrapper بعد از هر Run چاپ می‌کند:

```text
Trace ID: ...
```

این ID را می‌توانی در Grafana/Tempo برای رسیدن به همان Run استفاده کنی.

---

## 8. Metrics still work

قبل از Prometheus:

```bash
curl -s http://localhost:9464/metrics | grep codex_agent
```

Prometheus:

```text
http://SERVER-IP:9090
```

Example:

```promql
sum by (tool_type) (
  codex_agent_tool_calls_total
)
```

Failure:

```promql
sum by (tool_type) (
  codex_agent_tool_failures_total
)
```

p95 duration:

```promql
histogram_quantile(
  0.95,
  sum by (le, tool_type) (
    rate(codex_agent_tool_duration_seconds_bucket[5m])
  )
)
```

---

## 9. Data flow

### Metrics

```text
Codex event
  ↓
Wrapper instrumentation
  ↓
OpenTelemetry Counter / Histogram
  ↓
OTLP /v1/metrics
  ↓
OTel Collector
  ↓
Prometheus exporter :9464
  ↓
Prometheus scrape
  ↓
Grafana dashboard
```

### Traces

```text
Codex run
  ↓
Root span: codex.run
  ↓
Turn span
  ↓
Tool spans
  ↓
OTLP /v1/traces
  ↓
OTel Collector
  ↓
Tempo
  ↓
Grafana Trace View
```

---

## 10. Security note

این پروژه به صورت پیش‌فرض Prompt را داخل Trace ذخیره نمی‌کند.

همچنین command/tool detail فقط وقتی ذخیره می‌شود که explicitly این flag را بدهی:

```text
--trace-tool-details
```

برای محیط واقعی:

```bash
python agent/codex_agent_monitor.py \
  --workdir ./project \
  --prompt "..."
```

و `--trace-tool-details` را حذف کن.

Tempo و Grafana config این پروژه برای **local/demo** است، نه public production exposure.

---

## 11. Troubleshooting

### No traces in Grafana

```bash
docker compose ps
docker compose logs --tail=100 otel-collector
docker compose logs --tail=100 tempo
```

Tempo readiness:

```bash
curl http://localhost:3200/ready
```

OTel Collector metrics endpoint:

```bash
curl -s http://localhost:9464/metrics | grep codex_agent
```

در Grafana:

```text
Connections / Data sources
```

باید هر دو Data Source موجود باشند:

```text
Prometheus
Tempo
```

### Trace search

در Explore → Tempo:

```traceql
{ }
```

اگر Trace دیدی ولی service query خالی بود، بعد این را بزن:

```traceql
{ resource.service.name = "codex-agent-monitor" }
```

---

## 12. Stop

```bash
docker compose down
```

Delete local data too:

```bash
docker compose down -v
```

---

## Tests

```bash
python3 -m unittest discover -s tests -v
```
