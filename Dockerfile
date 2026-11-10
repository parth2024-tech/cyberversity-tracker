FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create data directory for SQLite database
RUN mkdir -p data

# Copy pyproject.toml and source code
COPY pyproject.toml .
COPY README.md .
COPY src/ src/
COPY config/ config/
COPY web/ web/

# Install python package
RUN pip install --no-cache-dir -e .

EXPOSE 8080

ENV ENVIRONMENT=production
ENV USE_LIGHTWEIGHT_EMBEDDINGS=true

CMD ["sh", "-c", "python -m ai_security_monitor server --host 0.0.0.0 --port ${PORT:-8080}"]
