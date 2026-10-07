from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
import socket
import uuid

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

from codex_event_parser import parse_codex_event


def build_telemetry(metrics_endpoint: str, traces_endpoint: str):
    service_instance_id = f"{socket.gethostname()}-{os.getpid()}"

    resource = Resource.create(
        {
            "service.name": "codex-agent-monitor",
            "service.version": "3.0.0",
            "service.instance.id": service_instance_id,
        }
    )

    # ------------------------
    # Metrics
    # ------------------------
    metric_exporter = OTLPMetricExporter(endpoint=metrics_endpoint)

    metric_reader = PeriodicExportingMetricReader(
        metric_exporter,
        export_interval_millis=2000,
    )

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[metric_reader],
    )

    metrics.set_meter_provider(meter_provider)

    meter = metrics.get_meter("codex.agent.monitoring")

    instruments = {
        "runs": meter.create_counter(
            "codex.agent.runs",
            description="Total Codex agent runs",
        ),
        "events": meter.create_counter(
            "codex.agent.events",
            description="Total Codex JSONL events observed",
        ),
        "tool_calls": meter.create_counter(
            "codex.agent.tool.calls",
            description="Codex tool calls observed",
        ),
        "tool_failures": meter.create_counter(
            "codex.agent.tool.failures",
            description="Codex tool calls that completed with a failure",
        ),
        "denied_actions": meter.create_counter(
            "codex.agent.denied.actions",
            description="Codex tool actions that appear denied by policy/sandbox/permissions",
        ),
        "errors": meter.create_counter(
            "codex.agent.errors",
            description="Codex error events observed",
        ),
        "run_duration": meter.create_histogram(
            "codex.agent.run.duration",
            unit="s",
            description="Codex run duration",
        ),
        "tool_duration": meter.create_histogram(
            "codex.agent.tool.duration",
            unit="s",
            description="Observed duration from tool item.started to item.completed",
        ),
        "active_runs": meter.create_up_down_counter(
            "codex.agent.active.runs",
            description="Currently active Codex runs",
        ),
        "input_tokens": meter.create_counter(
            "codex.agent.input.tokens",
            description="Best-effort input token usage extracted from Codex JSONL",
        ),
        "output_tokens": meter.create_counter(
            "codex.agent.output.tokens",
            description="Best-effort output token usage extracted from Codex JSONL",
        ),
    }

    # ------------------------
    # Traces
    # ------------------------
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=traces_endpoint)
        )
    )
    trace.set_tracer_provider(tracer_provider)

    tracer = trace.get_tracer("codex.agent.monitoring")

    return meter_provider, tracer_provider, instruments, tracer


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Run local Codex CLI and export metrics + traces "
            "through OpenTelemetry."
        )
    )

    parser.add_argument(
        "--prompt",
        required=True,
        help="Task sent to `codex exec`.",
    )

    parser.add_argument(
        "--workdir",
        default=".",
        help="Working directory passed to Codex.",
    )

    parser.add_argument(
        "--sandbox",
        choices=["read-only", "workspace-write", "danger-full-access"],
        default="read-only",
        help="Codex sandbox mode. Default: read-only.",
    )

    parser.add_argument(
        "--model",
        default=None,
        help="Optional Codex model override.",
    )

    parser.add_argument(
        "--otel-metrics-endpoint",
        default=os.getenv(
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
            "http://localhost:4318/v1/metrics",
        ),
        help="OTLP/HTTP metrics endpoint.",
    )

    parser.add_argument(
        "--otel-traces-endpoint",
        default=os.getenv(
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
            "http://localhost:4318/v1/traces",
        ),
        help="OTLP/HTTP traces endpoint.",
    )

    parser.add_argument(
        "--runs-dir",
        default="runs",
        help="Directory to store raw Codex JSONL event streams.",
    )

    parser.add_argument(
        "--skip-git-repo-check",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Pass --skip-git-repo-check to Codex (default: true).",
    )

    parser.add_argument(
        "--trace-tool-details",
        action="store_true",
        help=(
            "Include a truncated shell command/tool detail in trace span attributes. "
            "OFF by default because tool content can contain sensitive data."
        ),
    )

    return parser.parse_args()


def safe_tool_detail(event: dict, max_len: int = 500) -> str | None:
    """
    Best-effort detail extraction for demo traces.
    This is only used when --trace-tool-details is explicitly enabled.
    """
    item = event.get("item")
    if not isinstance(item, dict):
        return None

    for key in ("command", "name", "tool_name"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:max_len]

    return None


def main() -> int:
    args = parse_args()

    codex_path = shutil.which("codex")
    if not codex_path:
        print(
            "ERROR: `codex` was not found in PATH. "
            "Run `codex --version` first.",
            file=sys.stderr,
        )
        return 127

    workdir = Path(args.workdir).expanduser().resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    runs_dir = Path(args.runs_dir).expanduser().resolve()
    runs_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    raw_path = runs_dir / f"{stamp}-codex-events.jsonl"
    stderr_path = runs_dir / f"{stamp}-codex-stderr.log"

    meter_provider, tracer_provider, m, tracer = build_telemetry(
        args.otel_metrics_endpoint,
        args.otel_traces_endpoint,
    )

    run_id = uuid.uuid4().hex

    attrs_run = {
        "agent": "codex",
        "sandbox": args.sandbox,
    }
    if args.model:
        attrs_run["model"] = args.model

    trace_attrs = {
        "agent.name": "codex",
        "codex.run.id": run_id,
        "codex.sandbox": args.sandbox,
        "codex.workdir": str(workdir),
    }
    if args.model:
        trace_attrs["gen_ai.request.model"] = args.model

    command = [
        codex_path,
        "exec",
        "--json",
        "--sandbox",
        args.sandbox,
        "--config",
        'approval_policy="never"',
        "--cd",
        str(workdir),
    ]

    if args.skip_git_repo_check:
        command.append("--skip-git-repo-check")

    if args.model:
        command += ["--model", args.model]

    command.append(args.prompt)

    print("Running Codex:")
    print(
        " ".join(
            f'"{part}"' if " " in part else part
            for part in command[:-1]
        )
        + ' "<prompt>"'
    )
    print()
    print(f"Raw JSONL:    {raw_path}")
    print(f"stderr:       {stderr_path}")
    print(f"Metrics OTLP: {args.otel_metrics_endpoint}")
    print(f"Traces OTLP:  {args.otel_traces_endpoint}")
    print()

    started_at = time.monotonic()
    active_tool_spans: dict[str, tuple[object, float, str]] = {}
    active_turn_span = None
    seen_token_totals = {"input": 0, "output": 0}
    return_code = 1
    trace_id_hex = None

    try:
        with tracer.start_as_current_span(
            "codex.run",
            attributes=trace_attrs,
        ) as run_span:
            trace_id_hex = format(
                run_span.get_span_context().trace_id,
                "032x",
            )

            m["runs"].add(1, attrs_run)
            m["active_runs"].add(1, attrs_run)

            run_span.add_event(
                "codex.run.started",
                {
                    "codex.run.id": run_id,
                    "codex.sandbox": args.sandbox,
                },
            )

            with raw_path.open("w", encoding="utf-8") as raw_file, stderr_path.open(
                "w", encoding="utf-8"
            ) as err_file:
                proc = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=err_file,
                    text=True,
                    bufsize=1,
                )

                assert proc.stdout is not None

                for line in proc.stdout:
                    raw_file.write(line)
                    raw_file.flush()

                    stripped = line.strip()
                    if not stripped:
                        continue

                    try:
                        event = json.loads(stripped)
                    except json.JSONDecodeError:
                        m["events"].add(
                            1,
                            {
                                "agent": "codex",
                                "event_type": "non_json_stdout",
                            },
                        )
                        run_span.add_event(
                            "codex.non_json_stdout",
                            {"preview": stripped[:300]},
                        )
                        print(f"[non-json] {stripped[:300]}")
                        continue

                    parsed = parse_codex_event(event)

                    m["events"].add(
                        1,
                        {
                            "agent": "codex",
                            "event_type": parsed.event_type[:80],
                        },
                    )

                    event_attrs = {
                        "codex.event.type": parsed.event_type[:120],
                    }
                    if parsed.item_type:
                        event_attrs["codex.item.type"] = parsed.item_type[:120]
                    if parsed.item_id:
                        event_attrs["codex.item.id"] = parsed.item_id[:200]

                    run_span.add_event("codex.event", event_attrs)

                    # ------------------------
                    # Turn spans
                    # ------------------------
                    if parsed.event_type == "turn.started":
                        if active_turn_span is not None:
                            active_turn_span.set_attribute(
                                "codex.turn.incomplete",
                                True,
                            )
                            active_turn_span.end()

                        active_turn_span = tracer.start_span(
                            "codex.turn",
                            context=trace.set_span_in_context(run_span),
                            attributes={
                                "agent.name": "codex",
                                "codex.event.type": parsed.event_type,
                            },
                        )

                    elif parsed.event_type == "turn.completed":
                        if active_turn_span is not None:
                            if parsed.is_error:
                                active_turn_span.set_status(
                                    Status(StatusCode.ERROR)
                                )
                            else:
                                active_turn_span.set_status(
                                    Status(StatusCode.OK)
                                )
                            active_turn_span.end()
                            active_turn_span = None

                    if parsed.event_type == "error":
                        m["errors"].add(
                            1,
                            {"agent": "codex", "source": "event"},
                        )
                        run_span.set_status(
                            Status(StatusCode.ERROR, "Codex error event")
                        )

                    # Token usage is often emitted as cumulative totals.
                    if parsed.input_tokens > seen_token_totals["input"]:
                        delta = (
                            parsed.input_tokens
                            - seen_token_totals["input"]
                        )
                        m["input_tokens"].add(
                            delta,
                            {"agent": "codex"},
                        )
                        seen_token_totals["input"] = parsed.input_tokens

                    if parsed.output_tokens > seen_token_totals["output"]:
                        delta = (
                            parsed.output_tokens
                            - seen_token_totals["output"]
                        )
                        m["output_tokens"].add(
                            delta,
                            {"agent": "codex"},
                        )
                        seen_token_totals["output"] = parsed.output_tokens

                    # ------------------------
                    # Tool spans
                    # ------------------------
                    if parsed.is_tool:
                        tool_type = parsed.tool_type or "unknown_tool"

                        tool_attrs = {
                            "agent": "codex",
                            "tool_type": tool_type[:120],
                        }

                        if parsed.is_started:
                            m["tool_calls"].add(1, tool_attrs)

                            parent_span = active_turn_span or run_span
                            span_attrs = {
                                "agent.name": "codex",
                                "codex.tool.type": tool_type[:120],
                            }

                            if parsed.item_id:
                                span_attrs["codex.item.id"] = parsed.item_id[:200]

                            if args.trace_tool_details:
                                detail = safe_tool_detail(event)
                                if detail:
                                    span_attrs["codex.tool.detail"] = detail

                            tool_span = tracer.start_span(
                                f"codex.tool.{tool_type[:80]}",
                                context=trace.set_span_in_context(parent_span),
                                attributes=span_attrs,
                            )

                            key = parsed.item_id or f"anon-{time.monotonic_ns()}"
                            active_tool_spans[key] = (
                                tool_span,
                                time.monotonic(),
                                tool_type,
                            )

                            print(f"[tool:start] {tool_type}")

                        if parsed.is_completed:
                            span_entry = None

                            if parsed.item_id:
                                span_entry = active_tool_spans.pop(
                                    parsed.item_id,
                                    None,
                                )

                            if span_entry is not None:
                                tool_span, tool_started, started_tool_type = span_entry
                                elapsed = max(
                                    0.0,
                                    time.monotonic() - tool_started,
                                )

                                m["tool_duration"].record(
                                    elapsed,
                                    {
                                        "agent": "codex",
                                        "tool_type": started_tool_type[:120],
                                    },
                                )

                                tool_span.set_attribute(
                                    "codex.tool.duration_seconds",
                                    elapsed,
                                )

                                if parsed.looks_denied:
                                    tool_span.set_attribute(
                                        "codex.tool.denied",
                                        True,
                                    )

                                if parsed.is_error or parsed.looks_denied:
                                    tool_span.set_status(
                                        Status(
                                            StatusCode.ERROR,
                                            "tool failed or was denied",
                                        )
                                    )
                                else:
                                    tool_span.set_status(
                                        Status(StatusCode.OK)
                                    )

                                tool_span.end()

                            if parsed.is_error:
                                m["tool_failures"].add(1, tool_attrs)
                                print(f"[tool:failed] {tool_type}")
                            else:
                                print(f"[tool:done] {tool_type}")

                            if parsed.looks_denied:
                                m["denied_actions"].add(1, tool_attrs)
                                print(f"[tool:denied] {tool_type}")

                return_code = proc.wait()

            # Close any spans left open because Codex exited mid-event.
            for tool_span, _, _ in active_tool_spans.values():
                tool_span.set_attribute("codex.tool.incomplete", True)
                tool_span.set_status(
                    Status(StatusCode.ERROR, "tool span incomplete")
                )
                tool_span.end()
            active_tool_spans.clear()

            if active_turn_span is not None:
                active_turn_span.set_attribute(
                    "codex.turn.incomplete",
                    True,
                )
                active_turn_span.end()
                active_turn_span = None

            elapsed = max(0.0, time.monotonic() - started_at)

            run_span.set_attribute(
                "codex.exit_code",
                return_code,
            )
            run_span.set_attribute(
                "codex.run.duration_seconds",
                elapsed,
            )
            run_span.set_attribute(
                "gen_ai.usage.input_tokens",
                seen_token_totals["input"],
            )
            run_span.set_attribute(
                "gen_ai.usage.output_tokens",
                seen_token_totals["output"],
            )

            if return_code == 0:
                run_span.set_status(Status(StatusCode.OK))
            else:
                run_span.set_status(
                    Status(
                        StatusCode.ERROR,
                        f"Codex exited with code {return_code}",
                    )
                )

            run_span.add_event(
                "codex.run.completed",
                {
                    "codex.exit_code": return_code,
                    "codex.run.duration_seconds": elapsed,
                },
            )

    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        return_code = 130

    finally:
        elapsed = max(0.0, time.monotonic() - started_at)

        m["run_duration"].record(elapsed, attrs_run)
        m["active_runs"].add(-1, attrs_run)

        # Force final metric + trace exports before process exit.
        try:
            meter_provider.force_flush(timeout_millis=5000)
        except Exception as exc:
            print(
                f"Warning: final metric flush failed: {exc}",
                file=sys.stderr,
            )

        try:
            tracer_provider.force_flush(timeout_millis=5000)
        except Exception as exc:
            print(
                f"Warning: final trace flush failed: {exc}",
                file=sys.stderr,
            )

        try:
            meter_provider.shutdown()
        except Exception:
            pass

        try:
            tracer_provider.shutdown()
        except Exception:
            pass

    print()
    print(f"Codex exit code: {return_code}")
    print(f"Run duration:    {elapsed:.2f}s")

    if trace_id_hex:
        print(f"Trace ID:        {trace_id_hex}")

    print()
    print("Metrics:")
    print("  curl -s http://localhost:9464/metrics | grep -E 'codex|agent'")
    print()
    print("Prometheus:")
    print("  http://localhost:9090")
    print()
    print("Grafana:")
    print("  http://localhost:3000")
    print("  default demo login: admin / admin")
    print()
    print("Tempo query in Grafana Explore:")
    print('  { resource.service.name = "codex-agent-monitor" }')

    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
