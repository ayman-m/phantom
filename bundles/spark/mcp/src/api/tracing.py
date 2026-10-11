"""OpenTelemetry tracing — observability's traces pillar.

Auto-instruments the embedded MCP's Starlette app and outbound httpx
calls. Spans flow to whatever endpoint the operator configures via
the standard OTel env vars:

    OTEL_EXPORTER_OTLP_ENDPOINT      e.g. http://collector:4318
    OTEL_EXPORTER_OTLP_HEADERS       e.g. authorization=Bearer xxx
    OTEL_SERVICE_NAME                defaults to "phantom-agent"
    OTEL_RESOURCE_ATTRIBUTES         e.g. deployment.environment=prod

# Activation gate

  * PHANTOM_OTEL=1 — operator opt-in. Off by default so the SDK
    stays out of the hot path for deploys that don't have a
    collector.
  * OTEL_EXPORTER_OTLP_ENDPOINT set — without an endpoint there's
    nowhere for spans to go; we'd just be allocating without
    purpose.

Both must be true to install. When either is false, install() logs
the reason and returns without touching the app.

# What gets instrumented

Auto:
  * Starlette middleware — every HTTP request is a span with
    method/path/status/duration. Uses route templates (low
    cardinality) when available.
  * httpx — every outbound call (Vertex embeddings, xlog GraphQL,
    Caldera, XSIAM PAPI) is a child span linked to the inbound
    request span via context propagation.

Manual instrumentation hooks remain available via
opentelemetry.trace.get_tracer("phantom") for tools that want to
add domain-specific spans (e.g. simulation_run with sim_id as a
span attribute). Today no manual instrumentation is wired; the
auto-instrumentation alone gives a useful waterfall.

# Why opt-in vs always-on

Empty span exports are cheap but not free — span allocation +
context propagation across async tasks adds ~1µs per call. For a
deploy with no collector configured, that's pure overhead. Operators
who want tracing turn it on; everyone else pays nothing.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("Phantom MCP.tracing")


def install(app, *, service_name: str = "phantom-agent") -> bool:
    """Install OTel auto-instrumentation onto the given Starlette app.

    Returns True iff instrumentation was actually installed (deps
    available + activation gate passed). Returns False (no exception)
    in all the no-op cases so main.py can call this unconditionally.
    """
    if os.getenv("PHANTOM_OTEL", "0").lower() not in {"1", "true", "yes"}:
        logger.info(
            "OTel tracing disabled (PHANTOM_OTEL not set). "
            "Set PHANTOM_OTEL=1 + OTEL_EXPORTER_OTLP_ENDPOINT to enable.",
        )
        return False

    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        logger.info(
            "OTel tracing requested via PHANTOM_OTEL=1 but "
            "OTEL_EXPORTER_OTLP_ENDPOINT is unset — no collector to ship to. "
            "Skipping install."
        )
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.starlette import StarletteInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        logger.warning(
            "OTel tracing requested but SDK not installed (%s). "
            "Add opentelemetry-* to requirements.txt and rebuild the image.",
            exc,
        )
        return False

    # Service name + resource attrs from env. The OTel SDK respects
    # OTEL_SERVICE_NAME and OTEL_RESOURCE_ATTRIBUTES out of the box;
    # we just supply a default service name when unset.
    if not os.getenv("OTEL_SERVICE_NAME"):
        os.environ["OTEL_SERVICE_NAME"] = service_name

    # Provider + exporter wiring. BatchSpanProcessor batches by 512
    # spans / 5s by default; fine for our throughput. The exporter
    # picks up endpoint + headers from env.
    resource = Resource.create({"service.name": os.environ["OTEL_SERVICE_NAME"]})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)

    # Auto-instrument the Starlette app + global httpx. Note that
    # StarletteInstrumentor.instrument_app() patches the GIVEN app
    # in-place; httpx instrumentation patches the global httpx.Client
    # (so any code that constructs `httpx.Client()` after this picks
    # it up automatically — including the Vertex embedder).
    try:
        StarletteInstrumentor.instrument_app(app)
    except Exception as exc:
        logger.warning("OTel: starlette instrumentation failed: %s", exc)
    try:
        HTTPXClientInstrumentor().instrument()
    except Exception as exc:
        logger.warning("OTel: httpx instrumentation failed: %s", exc)

    logger.info(
        "OTel tracing installed — service=%s endpoint=%s",
        os.environ["OTEL_SERVICE_NAME"],
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"],
    )
    return True
