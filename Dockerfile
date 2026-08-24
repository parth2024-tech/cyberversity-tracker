# Multi-stage production Dockerfile for AI Security Monitor / AETHER-GUARD
FROM python:3.12-slim AS builder

WORKDIR /app

# Install system build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir --user -r requirements.txt

# Final runtime image
FROM python:3.12-slim AS runner

WORKDIR /app

# Create non-root system user
RUN groupadd -r aether && useradd -r -g aether aether \
    && mkdir -p /app/data /app/logs /app/config \
    && chown -R aether:aether /app

# Copy installed packages from builder
COPY --from=builder /root/.local /home/aether/.local

# Copy application source and web UI
COPY --chown=aether:aether src /app/src
COPY --chown=aether:aether config /app/config
COPY --chown=aether:aether web /app/web
COPY --chown=aether:aether cli.py pyproject.toml /app/

ENV PATH=/home/aether/.local/bin:$PATH \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production

USER aether

# Expose Web Command Center Port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

# Default entrypoint
CMD ["python3", "-m", "ai_security_monitor", "server", "--host", "0.0.0.0", "--port", "8000"]
