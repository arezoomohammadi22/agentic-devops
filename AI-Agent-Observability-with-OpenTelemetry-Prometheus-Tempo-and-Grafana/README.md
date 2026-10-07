# AI Agent Observability with OpenTelemetry, Prometheus, Tempo, and Grafana

This project demonstrates how to build a complete observability pipeline around a real AI coding agent.

Instead of treating an AI agent as a black box, the project instruments the agent's execution path so that we can answer operational questions such as:

- How many agent runs were executed?
- How many tools did the agent call?
- Which tool types were used?
- Which tool calls failed?
- Which actions were denied?
- How long did each tool call take?
- How long did the entire agent run take?
- How many input and output tokens were observed?
- What was the exact execution path of a specific agent run?
- Where, inside that run, did an error occur?

The system uses a real Codex CLI process as the agent, a custom Python wrapper as the instrumentation layer, OpenTelemetry as the telemetry standard, Prometheus for metrics, Tempo for traces, and Grafana as the visualization layer.

The goal of this repository is not only to provide working code. It is also intended to teach the architecture and reasoning behind AI agent observability.

---

## 1. Why AI Agents Need Observability

Traditional applications are observable because we instrument them.

We collect metrics, traces, and logs so that we can understand:

- whether the service is healthy,
- how much work it is doing,
- how long operations take,
- where failures happen,
- and what happened before an incident.

AI agents need the same treatment.

An agent may:

1. receive a task,
2. reason about the task,
3. inspect files,
4. call shell commands,
5. invoke MCP tools,
6. modify files,
7. run tests,
8. retry failed operations,
9. and finally return a result.

If we only look at the final answer, most of that execution path is invisible.

A response such as:

```text
Done.
```

does not tell us:

- how many tools were called,
- whether some calls failed,
- whether retries happened,
- whether a permission was denied,
- how much time was spent on external tools,
- or which operation created the bottleneck.

This project turns those internal operational events into observability signals.

---

# 2. What We Are Building

The final architecture is:

```text
                       Codex CLI
                           │
                    codex exec --json
                           │
                           ▼
                 Python Monitoring Wrapper
                           │
                    OpenTelemetry SDK
                     ↙            ↘
                Metrics          Traces
                   │                │
                   └───────┬────────┘
                           ▼
                OpenTelemetry Collector
                     ↙            ↘
              Prometheus         Tempo
                   │                │
                   └───────┬────────┘
                           ▼
                        Grafana
```

There are two observability paths.

### Metrics path

```text
Codex
  ↓
Wrapper
  ↓
OpenTelemetry Metrics
  ↓
OTel Collector
  ↓
Prometheus Exporter
  ↓
Prometheus
  ↓
Grafana Dashboard
```

### Trace path

```text
Codex Run
  ↓
Wrapper
  ↓
OpenTelemetry Spans
  ↓
OTel Collector
  ↓
Tempo
  ↓
Grafana Trace View
```

Metrics tell us what is happening across many runs.

Traces tell us exactly what happened inside one run.

That distinction is fundamental.

---

# 3. Why This Project Uses a Wrapper

The project deliberately places a Python wrapper around the Codex CLI.

The wrapper launches Codex using JSON event output:

```bash
codex exec --json
```

and continuously reads the JSONL event stream produced by the CLI.

This gives us an explicit instrumentation boundary:

```text
Codex Event
    ↓
Event Parser
    ↓
Telemetry Decision
    ↓
Metric and/or Span
```

The wrapper is useful because it gives us complete control over:

- which events count as tool calls,
- how tool types are normalized,
- how failures are detected,
- how denied operations are detected,
- which labels are safe for metrics,
- which attributes are attached to traces,
- how tool duration is measured,
- how agent runs are correlated,
- and what data is intentionally excluded for security reasons.

Some modern AI coding tools can expose native OpenTelemetry telemetry. That is useful in production.

This repository intentionally keeps the wrapper-based design because it teaches the instrumentation model explicitly and makes custom telemetry semantics easy to understand and modify.

---

# 4. Components

## 4.1 Codex CLI

Codex is the real AI agent in this project.

The project does not simulate agent behavior.

The wrapper launches a real Codex process with a command similar to:

```bash
codex exec \
  --json \
  --sandbox read-only \
  --config 'approval_policy="never"' \
  --cd ./demo-workspace \
  --skip-git-repo-check \
  "<prompt>"
```

The important option is:

```text
--json
```

It causes Codex to stream machine-readable JSON events.

The wrapper uses those events as its observability source.

Codex remains installed on the host machine rather than inside the Docker Compose stack.

This keeps the agent's authentication and local environment separate from the observability containers.

---

## 4.2 Python Monitoring Wrapper

The wrapper is the core instrumentation layer.

Its responsibilities are:

1. start the Codex process,
2. read Codex JSONL events,
3. store the raw event stream,
4. classify events,
5. identify tool execution,
6. detect completion and failures,
7. measure duration,
8. extract token usage when available,
9. create OpenTelemetry metrics,
10. create OpenTelemetry traces,
11. export telemetry to the OpenTelemetry Collector.

The wrapper is located at:

```text
agent/codex_agent_monitor.py
```

Event parsing is separated into:

```text
agent/codex_event_parser.py
```

This separation is intentional.

The monitoring code should not need to understand every version-specific detail of the Codex event format.

The parser converts raw events into a smaller internal model.

---

# 5. Event Parsing

The parser currently recognizes several tool-oriented item types:

```text
command_execution
mcp_tool_call
custom_tool_call
collab_tool_call
web_search
file_change
```

It also defensively treats item types containing the word `tool` as tool calls.

This allows the monitoring layer to remain reasonably tolerant of event format changes.

A parsed event includes fields such as:

```text
event_type
item_id
item_type
tool_type
is_tool
is_started
is_completed
is_error
looks_denied
input_tokens
output_tokens
```

---

## 5.1 Tool Type Normalization

Metric labels must have low cardinality.

For shell commands, the project does not use the full command as a metric label.

Instead of producing labels such as:

```text
tool="grep -R password /etc"
tool="cat /var/log/app.log"
tool="pytest tests/api"
```

the parser normalizes command execution to:

```text
tool_type="shell"
```

This is important because arbitrary command text would create an unbounded number of Prometheus time series.

For MCP or custom tools, bounded tool names can be used as the tool type.

---

## 5.2 Failure Detection

The parser performs best-effort classification of failures using:

- explicit error events,
- error item types,
- common failure words,
- non-success patterns such as exit-code failure text.

This is intentionally a monitoring heuristic, not an authorization mechanism.

Observability code should describe what happened.

It should never be responsible for enforcing security.

---

## 5.3 Denied Action Detection

The parser also looks for denial-related signals such as:

```text
denied
forbidden
not permitted
permission denied
sandbox denial
rejected by policy
```

When detected, the wrapper increments a denied-action metric and marks the corresponding tool span.

This makes security-policy failures observable without making the observability layer itself part of the security boundary.

---

# 6. OpenTelemetry

OpenTelemetry is the standard telemetry layer used by this project.

The wrapper does not send custom HTTP requests directly to Prometheus or Tempo.

Instead, it creates OpenTelemetry signals and exports them using OTLP.

This gives the architecture a clean boundary:

```text
Agent instrumentation
        ↓
   OpenTelemetry
        ↓
Telemetry backends
```

The project currently uses two OpenTelemetry signals:

- Metrics
- Traces

Logs can be added later.

---

# 7. Metrics

Metrics answer aggregate operational questions.

Examples:

- How many agent runs occurred?
- How many shell tools were called?
- What is the tool failure rate?
- How many operations were denied?
- What is the p95 tool duration?
- How many agent runs are currently active?

The wrapper creates the following instruments.

---

## 7.1 Agent Runs

OpenTelemetry name:

```text
codex.agent.runs
```

Prometheus-style exported name:

```text
codex_agent_runs_total
```

This counter increases once per monitored Codex run.

---

## 7.2 Agent Events

```text
codex.agent.events
```

Counts JSONL events observed from Codex.

A bounded `event_type` attribute is used to classify events.

---

## 7.3 Tool Calls

```text
codex.agent.tool.calls
```

Prometheus representation is typically:

```text
codex_agent_tool_calls_total
```

Useful dimensions include:

```text
agent="codex"
tool_type="shell"
```

Example query:

```promql
sum by (tool_type) (
  codex_agent_tool_calls_total
)
```

---

## 7.4 Tool Failures

```text
codex.agent.tool.failures
```

This counts tool calls that completed with a detected failure.

Example:

```promql
sum by (tool_type) (
  codex_agent_tool_failures_total
)
```

---

## 7.5 Denied Actions

```text
codex.agent.denied.actions
```

Tracks actions that appear to have been blocked by a sandbox, policy, or permission boundary.

This metric is useful for security monitoring.

A sudden increase may indicate:

- an agent trying unexpected operations,
- an incorrect permission configuration,
- a prompt causing unsafe actions,
- or a broken tool workflow.

---

## 7.6 Agent Errors

```text
codex.agent.errors
```

Counts general Codex error events observed by the wrapper.

---

## 7.7 Run Duration

```text
codex.agent.run.duration
```

A histogram containing total run duration.

This can be used for percentile calculations.

Example:

```promql
histogram_quantile(
  0.95,
  sum by (le) (
    rate(codex_agent_run_duration_seconds_bucket[5m])
  )
)
```

---

## 7.8 Tool Duration

```text
codex.agent.tool.duration
```

Measures elapsed time between tool start and tool completion.

Example p95 query:

```promql
histogram_quantile(
  0.95,
  sum by (le, tool_type) (
    rate(codex_agent_tool_duration_seconds_bucket[5m])
  )
)
```

---

## 7.9 Active Runs

```text
codex.agent.active.runs
```

This is an UpDownCounter.

It is incremented when an agent run begins and decremented when the run finishes.

It answers:

```text
How many monitored agent runs are currently active?
```

---

## 7.10 Token Usage

The parser performs best-effort extraction of:

```text
input_tokens
output_tokens
```

and exposes counters:

```text
codex.agent.input.tokens
codex.agent.output.tokens
```

Token fields can change between Codex versions, so extraction is deliberately defensive.

These metrics should be considered operational estimates rather than billing-authoritative values.

---

# 8. Why Metrics Alone Are Not Enough

Suppose Prometheus tells us:

```text
tool calls = 5
tool failures = 1
```

That information is useful.

But it cannot answer:

```text
Which specific run contained the failure?
```

or:

```text
Which tool ran before the failure?
```

or:

```text
Was the failure part of the same turn as the previous shell command?
```

Prometheus is designed for aggregated time-series data.

It is not designed to represent a complete execution tree.

That is why we also use tracing.

---

# 9. Tracing Model

Each monitored Codex execution becomes one OpenTelemetry trace.

The top-level span is:

```text
codex.run
```

A Codex turn is represented by:

```text
codex.turn
```

Tool calls become child spans:

```text
codex.tool.shell
codex.tool.<tool-type>
```

A trace may look like:

```text
codex.run
│
└── codex.turn
    ├── codex.tool.shell
    ├── codex.tool.shell
    ├── codex.tool.shell
    └── codex.tool.mcp_tool
```

This gives us a temporal execution tree.

---

# 10. Root Run Span

The wrapper creates one root span for the entire monitored process:

```text
codex.run
```

Typical attributes include:

```text
agent.name="codex"
codex.run.id
codex.sandbox
codex.workdir
codex.exit_code
codex.run.duration_seconds
gen_ai.usage.input_tokens
gen_ai.usage.output_tokens
```

The wrapper also prints the generated OpenTelemetry Trace ID after each run.

Example:

```text
Trace ID: 47f0f96871f54d3aa63fd7a7154f120c
```

This makes it easy to correlate terminal execution with Grafana/Tempo.

---

# 11. Turn Spans

When Codex emits:

```text
turn.started
```

the wrapper opens a:

```text
codex.turn
```

span.

When the corresponding turn completes, the span is closed.

If the turn reports an error, the OpenTelemetry span status is marked as an error.

---

# 12. Tool Spans

When a tool starts, the wrapper creates a child span such as:

```text
codex.tool.shell
```

When the tool completes, the span is closed.

The span can contain attributes such as:

```text
agent.name
codex.tool.type
codex.item.id
codex.tool.duration_seconds
codex.tool.denied
```

Successful calls receive an OK status.

Failed or denied calls receive an ERROR status.

This is what allows Grafana and Tempo to show failed operations directly in the trace waterfall.

---

# 13. Tool Details and Sensitive Data

The project supports an optional flag:

```text
--trace-tool-details
```

When enabled, the wrapper may attach a truncated tool detail, such as a shell command, to a trace span.

For example:

```text
pwd
ls -la
cat demo.txt
```

This is useful for local demonstrations.

It is intentionally disabled by default.

Tool arguments can contain:

- secrets,
- file paths,
- tokens,
- customer data,
- internal hostnames,
- credentials,
- infrastructure identifiers.

For real environments, tool content should only be captured after deliberate redaction and data-classification design.

---

# 14. OpenTelemetry Collector

The OpenTelemetry Collector is the central telemetry router.

The wrapper sends both metrics and traces to the Collector over OTLP.

The project exposes:

```text
4317  OTLP/gRPC
4318  OTLP/HTTP
```

The Python wrapper currently uses OTLP/HTTP.

Default endpoints:

```text
http://localhost:4318/v1/metrics
http://localhost:4318/v1/traces
```

The Collector then routes each signal to the correct backend.

---

## 14.1 Collector Metrics Pipeline

```text
OTLP Receiver
    ↓
Batch Processor
    ↓
Prometheus Exporter
```

The Prometheus exporter exposes metrics on:

```text
0.0.0.0:9464
```

Prometheus later scrapes this endpoint.

---

## 14.2 Collector Traces Pipeline

```text
OTLP Receiver
    ↓
Batch Processor
    ↓
OTLP Exporter
    ↓
Tempo
```

Tempo is addressed from Docker Compose using:

```text
tempo:4317
```

TLS is disabled because the communication occurs inside the local Compose network.

---

# 15. Prometheus

Prometheus stores and queries metrics.

The important detail is that the Python agent does not push metrics directly into Prometheus.

The flow is:

```text
Wrapper
   ↓
OpenTelemetry
   ↓
Collector
   ↓
Prometheus Exporter :9464
   ↑
Prometheus Scrape
```

Prometheus is configured to scrape:

```text
otel-collector:9464
```

every few seconds.

A minimal configuration is:

```yaml
global:
  scrape_interval: 5s
  evaluation_interval: 5s

scrape_configs:
  - job_name: "codex-agent-otel"
    static_configs:
      - targets:
          - "otel-collector:9464"
```

---

# 16. Tempo

Tempo stores distributed traces.

Prometheus tells us that an error happened.

Tempo tells us where the error happened inside a specific run.

For this lab, Tempo uses local filesystem storage.

This is appropriate for:

- development,
- demonstrations,
- training,
- small local experiments.

It should not be treated as a production storage architecture.

The demo configuration keeps traces for a limited period and stores WAL/block data in a Docker volume.

---

# 17. Grafana

Grafana is the visualization layer.

It is not the primary storage backend in this architecture.

Grafana queries:

```text
Prometheus → Metrics
Tempo      → Traces
```

This gives us two complementary views.

### Dashboard view

Used for operational overview:

```text
How many runs?
How many failures?
What is the current tool call rate?
What is p95 tool latency?
```

### Trace view

Used for investigation:

```text
What exactly happened in run X?
Which tool failed?
What ran before it?
How long did each step take?
```

---

# 18. Grafana Data Sources

The project provisions two Grafana data sources.

## Prometheus

```text
http://prometheus:9090
```

## Tempo

```text
http://tempo:3200
```

These addresses use Docker Compose service names.

Inside the Grafana container:

```text
localhost
```

means the Grafana container itself.

Therefore this would be incorrect:

```text
http://localhost:9090
```

The correct container-to-container address is:

```text
http://prometheus:9090
```

The same principle applies to Tempo.

---

# 19. Grafana Dashboard Provisioning

The repository contains a prebuilt dashboard:

```text
grafana/dashboards/codex-agent-observability.json
```

Grafana loads dashboards from:

```text
/etc/grafana/dashboards
```

The provisioning configuration creates the folder:

```text
AI Agent Observability
```

and loads:

```text
Codex Agent Observability
```

The dashboard contains panels for metrics such as:

- total agent runs,
- total tool calls,
- tool failures,
- active runs,
- tool call rate,
- p95 tool duration,
- denied actions.

---

# 20. Project Structure

```text
.
├── agent/
│   ├── codex_agent_monitor.py
│   ├── codex_event_parser.py
│   └── requirements.txt
│
├── demo-workspace/
│   └── demo.txt
│
├── grafana/
│   ├── dashboards/
│   │   └── codex-agent-observability.json
│   │
│   └── provisioning/
│       ├── dashboards/
│       │   └── dashboards.yml
│       │
│       └── datasources/
│           └── datasources.yml
│
├── tests/
│   ├── test_cli_command.py
│   ├── test_parser.py
│   └── test_tracing.py
│
├── docker-compose.yml
├── otel-collector.yaml
├── prometheus.yml
├── tempo.yaml
├── Makefile
├── run-demo.sh
└── README.md
```

---

# 21. Prerequisites

You need:

- Docker
- Docker Compose
- Python 3
- Codex CLI
- an authenticated Codex session

Verify:

```bash
docker --version
docker compose version
python3 --version
codex --version
```

Codex must be available in the host `PATH`.

---

# 22. Start the Observability Stack

Start the infrastructure:

```bash
docker compose up -d
```

Verify:

```bash
docker compose ps
```

You should see services for:

```text
otel-collector
prometheus
tempo
grafana
```

Useful endpoints:

| Component | URL |
|---|---|
| Grafana | `http://localhost:3000` |
| Prometheus | `http://localhost:9090` |
| Tempo HTTP API | `http://localhost:3200` |
| OTel HTTP | `http://localhost:4318` |
| OTel gRPC | `localhost:4317` |
| Collector Prometheus endpoint | `http://localhost:9464/metrics` |

For a remote server, replace `localhost` with the server address where appropriate.

---

# 23. Grafana Versioning

For reproducible environments, avoid depending indefinitely on:

```yaml
image: grafana/grafana:latest
```

Pin a tested Grafana version in your repository.

For example:

```yaml
image: grafana/grafana:<tested-version>
```

The exact version should be the one validated in your environment.

This avoids unexpected frontend, plugin, or provisioning changes after an upstream release.

---

# 24. Grafana Credentials

The Compose file can use:

```text
GRAFANA_ADMIN_USER
GRAFANA_ADMIN_PASSWORD
```

For local demos, simple credentials may be acceptable.

Do not expose a Grafana instance to an untrusted network using default credentials.

Example:

```bash
export GRAFANA_ADMIN_PASSWORD='use-a-strong-password'
docker compose up -d
```

---

# 25. Create the Python Environment

Create a virtual environment:

```bash
python3 -m venv .venv
```

Activate it:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r agent/requirements.txt
```

The project uses:

```text
opentelemetry-api
opentelemetry-sdk
opentelemetry-exporter-otlp-proto-http
```

---

# 26. Run the Agent

A safe read-only example:

```bash
python agent/codex_agent_monitor.py \
  --workdir ./demo-workspace \
  --trace-tool-details \
  --prompt "Use shell tools to inspect this directory. Run pwd, list the files, read demo.txt, then summarize what you found. Do not modify files."
```

During execution, the wrapper prints tool activity:

```text
[tool:start] shell
[tool:done] shell
[tool:start] shell
[tool:failed] shell
```

At the end:

```text
Codex exit code: 0
Run duration:    61.17s
Trace ID:        ...
```

The raw JSONL stream is also stored under:

```text
runs/
```

along with Codex stderr output.

---

# 27. Why Store the Raw Event Stream?

The raw JSONL event file is useful for:

- debugging parser behavior,
- adapting to new Codex event formats,
- investigating telemetry mismatches,
- writing regression tests,
- understanding what the agent actually emitted.

This is especially useful when an AI CLI changes its event schema between versions.

The raw event log is a debugging artifact.

It should not automatically be treated as safe long-term production audit storage.

---

# 28. Verify Metrics Before Prometheus

The first validation point is the Collector itself.

Run:

```bash
curl -s http://localhost:9464/metrics | grep codex_agent
```

You should see metrics such as:

```text
codex_agent_runs_total
codex_agent_tool_calls_total
codex_agent_tool_failures_total
codex_agent_tool_duration_seconds
```

This proves:

```text
Agent
→ Wrapper
→ OpenTelemetry
→ Collector
```

is working.

If metrics exist here but not in Prometheus, the problem is downstream of the Collector.

---

# 29. Verify Prometheus

Open:

```text
http://localhost:9090
```

Check:

```text
Status → Targets
```

The Collector target should be UP.

Then query:

```promql
codex_agent_tool_calls_total
```

or:

```promql
sum by (tool_type) (
  codex_agent_tool_calls_total
)
```

If the Collector endpoint contains the metric but Prometheus does not, inspect:

- Prometheus scrape configuration,
- target health,
- container DNS,
- Collector port exposure.

---

# 30. Verify Grafana Metrics

Open Grafana:

```text
http://localhost:3000
```

Confirm the Prometheus data source is available.

Then use:

```text
Explore → Prometheus
```

and query:

```promql
codex_agent_tool_calls_total
```

If the result appears, the complete metrics path is working:

```text
Codex
→ Wrapper
→ OTel
→ Collector
→ Prometheus
→ Grafana
```

---

# 31. Verify Tempo

Check readiness:

```bash
curl http://localhost:3200/ready
```

Then open Grafana:

```text
Explore → Tempo
```

Search using TraceQL:

```traceql
{ resource.service.name = "codex-agent-monitor" }
```

A successful run should produce a trace containing spans similar to:

```text
codex.run
  └── codex.turn
      ├── codex.tool.shell
      ├── codex.tool.shell
      └── codex.tool.shell
```

This proves the complete trace path:

```text
Codex
→ Wrapper
→ OTel
→ Collector
→ Tempo
→ Grafana
```

---

# 32. Search by Trace ID

The wrapper prints the OpenTelemetry Trace ID.

You can use that identifier to correlate:

```text
terminal execution
↔
Tempo trace
↔
Grafana investigation
```

This becomes especially important when many agent sessions execute concurrently.

---

# 33. Testing a Failure

Observability is not useful if it only works for successful runs.

A good test prompt intentionally causes a harmless failure.

For example:

```text
Inspect the directory.
Run pwd.
List the files.
Try to read a file named missing-file.txt.
Then continue and summarize what happened.
```

Expected result:

- at least one tool call succeeds,
- at least one tool call fails,
- the overall agent may still complete,
- the failure counter increases,
- the failed tool span is marked as an error.

Prometheus should show an increase in:

```text
codex_agent_tool_failures_total
```

Tempo should show the exact failed span inside the run.

This demonstrates the difference between metrics and traces.

Prometheus answers:

```text
How many failures occurred?
```

Tempo answers:

```text
Where exactly did the failure occur?
```

---

# 34. Dashboard Queries

## Total tool calls

```promql
sum(codex_agent_tool_calls_total)
```

## Calls by tool type

```promql
sum by (tool_type) (
  codex_agent_tool_calls_total
)
```

## Tool failure count

```promql
sum(codex_agent_tool_failures_total)
```

## Denied actions

```promql
sum(codex_agent_denied_actions_total)
```

## Tool call rate

```promql
sum by (tool_type) (
  rate(codex_agent_tool_calls_total[5m])
)
```

## p95 tool duration

```promql
histogram_quantile(
  0.95,
  sum by (le, tool_type) (
    rate(codex_agent_tool_duration_seconds_bucket[5m])
  )
)
```

---

# 35. Metric Cardinality

Cardinality is one of the most important design concerns in Prometheus.

Good metric labels are bounded.

Examples:

```text
agent
tool_type
status
model
reason
```

Bad metric labels include arbitrary values such as:

```text
session_id
trace_id
full shell command
prompt
file path
URL with dynamic IDs
customer ID
raw resource ID
```

Those values create a large number of unique time series and can make Prometheus expensive or unstable.

High-cardinality values belong in traces or logs, not metric labels.

This project therefore keeps command text out of Prometheus labels.

---

# 36. Metrics vs Traces

A useful mental model is:

## Metrics

Use metrics for:

```text
How often?
How many?
How slow?
What percentage failed?
Is the system getting worse?
```

## Traces

Use traces for:

```text
What happened in this exact run?
Which step was slow?
What happened before the error?
Which tool was involved?
What was the execution order?
```

Example:

```text
Prometheus:
5 tool calls
1 failure

Tempo:
Run 8f...
  ├── shell OK
  ├── shell OK
  ├── shell ERROR
  └── shell OK
```

Neither signal replaces the other.

Together they provide useful observability.

---

# 37. Security Model

Observability should never become a data-exfiltration mechanism.

This project follows several principles.

## Do not store prompt text by default

Prompt text may contain sensitive information.

The root span describes the run without automatically storing the full prompt.

## Do not use commands as metric labels

Commands can contain secrets and create high cardinality.

## Treat tool details as opt-in

The flag:

```text
--trace-tool-details
```

is intended for controlled demonstrations.

## Redact before exporting sensitive data

In production, instrumentation should support:

```text
classification
redaction
allowlisting
field-level filtering
```

## Observability is not authorization

The wrapper may detect that an operation was denied.

It does not enforce the denial.

Real enforcement must still exist in:

- operating-system permissions,
- containers,
- sandboxes,
- Kubernetes RBAC,
- IAM,
- network policies,
- tool authorization,
- approval gates.

---

# 38. Operational Security

Do not publicly expose these development ports without controls:

```text
3000
9090
3200
4317
4318
9464
```

For real deployments:

- place services behind trusted networks,
- use authentication,
- use TLS where appropriate,
- restrict Collector ingress,
- protect Grafana,
- avoid exposing raw Prometheus and Tempo endpoints,
- configure retention deliberately.

---

# 39. Docker Networking

Inside Docker Compose, services communicate using service names.

Examples:

```text
prometheus:9090
tempo:3200
otel-collector:9464
```

From the host, the exposed endpoints use:

```text
localhost:<port>
```

This distinction is important.

For example, Grafana connecting to:

```text
http://localhost:9090
```

would attempt to reach Prometheus inside the Grafana container itself.

The correct Docker Compose URL is:

```text
http://prometheus:9090
```

---

# 40. Troubleshooting

## No metrics at port 9464

Check the Collector:

```bash
docker compose logs --tail=100 otel-collector
```

Verify the wrapper is exporting to:

```text
http://localhost:4318/v1/metrics
```

Check whether the run actually generated telemetry.

---

## Collector has metrics but Prometheus does not

Check:

```text
Prometheus → Status → Targets
```

The target:

```text
otel-collector:9464
```

must be UP.

Inspect:

```bash
docker compose logs --tail=100 prometheus
```

---

## Prometheus works but Grafana does not

Check the Grafana Prometheus data source.

The URL should be:

```text
http://prometheus:9090
```

not:

```text
http://localhost:9090
```

---

## No traces in Tempo

Check:

```bash
docker compose logs --tail=100 otel-collector
docker compose logs --tail=100 tempo
```

Verify:

```bash
curl http://localhost:3200/ready
```

Then try a broad query in Grafana Explore:

```traceql
{}
```

If traces appear, filter by:

```traceql
{ resource.service.name = "codex-agent-monitor" }
```

---

## Grafana dashboard is missing

Verify that the dashboard exists on the host:

```bash
ls -lah grafana/dashboards/
```

Then verify the file exists inside the container:

```bash
docker compose exec grafana \
  ls -lah /etc/grafana/dashboards
```

Check dashboard provisioning:

```bash
docker compose exec grafana \
  cat /etc/grafana/provisioning/dashboards/dashboards.yml
```

Then inspect logs:

```bash
docker compose logs grafana \
  | grep -Ei "dashboard|provision|error|failed"
```

---

## Grafana data sources are missing

Check:

```bash
docker compose exec grafana \
  cat /etc/grafana/provisioning/datasources/datasources.yml
```

Prometheus should use:

```text
http://prometheus:9090
```

Tempo should use:

```text
http://tempo:3200
```

---

# 41. Tests

The repository contains regression tests for the parser, CLI command construction, and tracing instrumentation.

Run:

```bash
python3 -m unittest discover -s tests -v
```

The tests help detect changes in:

- CLI argument construction,
- event parsing,
- denied-operation classification,
- token extraction,
- trace instrumentation presence.

They do not replace an end-to-end test with a real Codex process and running telemetry stack.

---

# 42. A Practical End-to-End Validation Checklist

A useful validation sequence is:

1. Start the Compose stack.
2. Confirm all four services are running.
3. Confirm Tempo is ready.
4. Confirm Prometheus sees the Collector target as UP.
5. Start the monitored Codex run.
6. Observe tool-start and tool-complete messages.
7. Confirm the run exits successfully.
8. Copy the printed Trace ID.
9. Query `:9464/metrics`.
10. Verify `codex_agent_*` metrics exist.
11. Query the same metrics in Prometheus.
12. Query them in Grafana.
13. Open Tempo in Grafana Explore.
14. Locate the run trace.
15. Verify tool spans and duration.
16. Run a controlled failure test.
17. Verify both the failure metric and the failed trace span.

If every step succeeds, both observability pipelines are working end to end.

---

# 43. What This Project Teaches

This repository demonstrates several important observability concepts.

## Instrumentation happens at the application boundary

Prometheus cannot magically understand an AI agent.

Something must convert agent behavior into telemetry.

In this project, that component is the Python wrapper.

## Metrics require semantic design

Choosing what counts as:

```text
a tool call
a failure
a denial
a run
```

is part of observability design.

## Traces require correlation

Events become useful when they belong to one execution context.

That is why each run becomes a trace.

## Low-cardinality design matters

Not every useful piece of data belongs in Prometheus.

## One event can produce multiple signals

A tool execution can create:

```text
a counter
a duration histogram observation
a trace span
an error status
```

These signals serve different purposes.

---

# 44. Extending the Architecture

The current system supports:

```text
Metrics ✅
Traces  ✅
Grafana ✅
```

A natural next step is logs.

For example:

```text
OpenTelemetry
   ├── Metrics → Prometheus
   ├── Traces  → Tempo
   └── Logs    → Loki
```

Grafana can then correlate all three signals.

---

# 45. Alerting

Prometheus metrics can also drive alerts.

Example conditions:

```text
tool failure rate is too high
denied actions increase unexpectedly
p95 tool latency crosses a threshold
agent runs stop appearing
token consumption increases abnormally
```

A full alerting path could be:

```text
Prometheus
    ↓
Alert Rules
    ↓
Alertmanager
    ↓
Slack / Email / PagerDuty / Webhook
```

Alerting is intentionally separate from tracing.

Metrics are generally a better signal for alert conditions.

Traces are better for investigating why an alert happened.

---

# 46. Production Considerations

This repository is primarily a teaching and lab implementation.

Before production use, consider:

- authentication,
- TLS,
- storage durability,
- retention,
- Collector high availability,
- Tempo object storage,
- Prometheus HA or remote write,
- Grafana authentication and RBAC,
- secret redaction,
- telemetry sampling,
- trace-volume limits,
- metric cardinality limits,
- version pinning,
- schema evolution,
- audit retention requirements.

The local Tempo filesystem backend and default container topology are not intended to represent a large-scale production design.

---

# 47. Wrapper-Based vs Native Agent Telemetry

There are two general ways to observe an AI coding agent.

## Native telemetry

The agent or CLI directly emits OpenTelemetry signals.

Advantages:

- less custom instrumentation,
- fewer moving parts,
- telemetry semantics maintained by the tool vendor.

## Wrapper instrumentation

An external process observes the agent event stream and generates telemetry.

Advantages:

- complete control over metric semantics,
- custom failure and denial logic,
- custom labels and spans,
- consistent telemetry across tools,
- easier experimentation and teaching.

This repository uses wrapper instrumentation intentionally.

It provides a clear example of how an observability layer can be built around any agent that exposes a machine-readable event stream.

---

# 48. Final Mental Model

The simplest way to think about the system is:

```text
AI Agent
   ↓
Observable Events
   ↓
Instrumentation
   ↓
OpenTelemetry
   ↓
Collector
   ├── Metrics → Prometheus
   └── Traces  → Tempo
                     ↓
                  Grafana
```

The most important idea is this:

> The final answer of an AI agent is only one output.  
> Observability shows how the agent reached that answer.

Prometheus tells us:

```text
what is happening across the system
```

Tempo tells us:

```text
what happened inside one specific execution
```

Grafana gives us a single place to investigate both.

That is the foundation of practical AI agent observability.
