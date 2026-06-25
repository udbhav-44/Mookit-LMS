"""Observability bootstrap for Langfuse + optional OpenTelemetry."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _langfuse_host() -> str:
    # Langfuse docs use LANGFUSE_BASE_URL in many places; support both names.
    return (
        os.getenv("LANGFUSE_HOST")
        or os.getenv("LANGFUSE_BASE_URL")
        or "https://cloud.langfuse.com"
    )


def langfuse_enabled() -> bool:
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def init_langfuse() -> None:
    """Initialize Langfuse SDK once, if credentials are present."""
    if not langfuse_enabled():
        logger.info("Langfuse credentials not set — tracing disabled")
        return
    host = _langfuse_host()
    try:
        # Ensure client bootstrap is attempted early so startup logs make tracing state explicit.
        from langfuse import get_client

        get_client()
        logger.info("Langfuse tracing initialized (host=%s)", host)
    except Exception as exc:
        logger.warning("Langfuse init failed: %s", exc)


# ── OpenTelemetry (optional) ──────────────────────────────────────────────────

def init_otel(service_name: str = "mookit-ai-assistant") -> None:
    """Set up OpenTelemetry with OTLP exporter if the endpoint is configured.

    Uses the GenAI semantic conventions (still experimental as of 2025).
    """
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        logger.info("OTEL_EXPORTER_OTLP_ENDPOINT not set — OTel disabled")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
        logger.info("OpenTelemetry initialised (endpoint=%s)", endpoint)
    except Exception as exc:
        logger.warning("OTel init failed: %s", exc)


def get_tracer(name: str = "mookit"):
    try:
        from opentelemetry import trace
        return trace.get_tracer(name)
    except Exception:
        return None
