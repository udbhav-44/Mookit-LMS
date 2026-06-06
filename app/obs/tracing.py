"""
Observability setup (A4.4): Langfuse traces + structured logging correlation.

Langfuse is the primary tracing backend for LLM cost/token attribution.
OpenTelemetry GenAI conventions are wrapped here for forward-compatibility.

Usage:
    from app.obs.tracing import get_tracer, trace_llm_call

The `request_id` from RequestContext is propagated as the trace correlation id
through SSE events and ARQ jobs so all spans for one user turn are linked.
"""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ── Langfuse ─────────────────────────────────────────────────────────────────

_langfuse_client: Any = None


def init_langfuse() -> None:
    """Initialise the Langfuse client if credentials are available.

    Fails silently — tracing is optional; the service must work without it.
    """
    global _langfuse_client
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if not public_key or not secret_key:
        logger.info("Langfuse credentials not set — tracing disabled")
        return

    try:
        from langfuse import Langfuse
        _langfuse_client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )
        logger.info("Langfuse tracing initialised (host=%s)", host)
    except Exception as exc:
        logger.warning("Langfuse init failed: %s", exc)


def get_langfuse():
    return _langfuse_client


def create_trace(
    request_id: str,
    tenant_key: str,
    user_id: int,
    session_id: str,
    name: str = "chat_turn",
) -> Any:
    """Create a Langfuse trace for one chat turn.  Returns the trace object or None."""
    client = get_langfuse()
    if client is None:
        return None
    try:
        return client.trace(
            id=request_id,
            name=name,
            user_id=str(user_id),
            session_id=session_id,
            metadata={"tenant_key": tenant_key},
        )
    except Exception as exc:
        logger.warning("Langfuse trace creation failed: %s", exc)
        return None


def record_llm_generation(
    trace: Any,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float | None,
    name: str = "llm_call",
) -> None:
    """Record token usage and cost on a Langfuse trace generation span."""
    if trace is None:
        return
    try:
        trace.generation(
            name=name,
            model=model,
            usage={"input": prompt_tokens, "output": completion_tokens},
            metadata={"cost_usd": cost_usd},
        )
    except Exception as exc:
        logger.warning("Langfuse generation recording failed: %s", exc)


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
