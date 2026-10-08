"""Metrics and traces for runs.

Prometheus counters answer "how many, how often" and are served at /metrics. OpenTelemetry spans answer
"where did this one run spend its time". Neither carries the text of an issue, a file or a tool result,
because those can hold customer data and secrets. Only names, tiers, counts, sizes and timings go in.

Tracing is off unless asked for: DEVFLOW_TRACE_CONSOLE=1 prints spans to stderr, and
OTEL_EXPORTER_OTLP_ENDPOINT sends them to an OTLP/HTTP collector (needs opentelemetry-exporter-otlp-proto-http).
The provider is kept here and not set as the global one, because OpenTelemetry allows that once per
process and the tests need a fresh exporter each time.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import trace
from prometheus_client import Counter, Histogram

SERVICE_NAME = "devflow-orchestrator"

RUNS = Counter("devflow_runs_total", "Runs that stopped, by how.", ["playbook", "status"])
RUN_SECONDS = Histogram(
    "devflow_run_seconds", "Time from starting or resuming a run to it stopping.", ["playbook"],
    buckets=(1, 5, 15, 30, 60, 120, 300, 900),
)
TOOL_DECISIONS = Counter(
    "devflow_tool_decisions_total", "What the policy decided for each proposed tool call.", ["tool", "tier", "decision"]
)
TOOL_RESULTS = Counter("devflow_tool_results_total", "Tool calls that ran.", ["tool", "ok"])
APPROVALS = Counter("devflow_approvals_total", "Human decisions on gated calls.", ["decision"])
TAINT_ESCALATIONS = Counter(
    "devflow_taint_escalations_total",
    "Publish calls that needed approval only because the run had read outside text.",
)
TOKENS = Counter("devflow_tokens_total", "Model tokens used.", ["direction"])

_provider = None


def configure() -> None:
    """Turn tracing on from the environment. Does nothing if neither variable is set."""
    global _provider
    console = os.environ.get("DEVFLOW_TRACE_CONSOLE") == "1"
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if _provider is not None or not (console or endpoint):
        return
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    if console:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(out=sys.stderr)))
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    _provider = provider


def use_provider(provider) -> None:
    """For tests: send spans to this provider."""
    global _provider
    _provider = provider


def tracer() -> trace.Tracer:
    if _provider is not None:
        return _provider.get_tracer(SERVICE_NAME)
    return trace.get_tracer(SERVICE_NAME)  # the no-op tracer unless someone set a global provider


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[trace.Span]:
    with tracer().start_as_current_span(name) as current:
        for key, value in attributes.items():
            current.set_attribute(key, value)
        yield current
