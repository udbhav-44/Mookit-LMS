# ── Stage 1: build dependencies ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install uv for fast dependency resolution.
RUN pip install --no-cache-dir uv

COPY pyproject.toml ./

# Build the venv at the SAME path it will live at runtime (/app/.venv) and make it --relocatable,
# so the console-script shebangs (e.g. uvicorn) resolve correctly after the copy.
# (Resolve runtime deps from pyproject via `uv pip compile`; avoids bash process-substitution,
# which fails under the /bin/sh used by RUN, and needs no lockfile.)
RUN uv venv --relocatable /app/.venv && \
    uv pip compile pyproject.toml --output-file /build/requirements.txt && \
    uv pip install --python /app/.venv/bin/python --no-cache -r /build/requirements.txt

# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.12-slim

# libmagic is needed by python-magic for magic-bytes file validation.
RUN apt-get update && \
    apt-get install -y --no-install-recommends libmagic1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only the installed packages from the builder stage (same path → shebangs stay valid).
COPY --from=builder /app/.venv /app/.venv

# Copy application source.
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY sample-ui/ ./sample-ui/

# Use the venv Python.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Non-root user for security.
RUN adduser --disabled-password --gecos "" appuser && \
    mkdir -p /tmp/mookit_uploads && \
    chown appuser:appuser /tmp/mookit_uploads
USER appuser

EXPOSE 8000

# Graceful drain: uvicorn's --timeout-graceful-shutdown gives in-flight SSE
# streams time to finish before the process exits.
CMD ["/app/.venv/bin/python", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--timeout-graceful-shutdown", "30", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
