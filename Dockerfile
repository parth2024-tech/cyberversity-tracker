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
COPY src/ src/
COPY config/ config/
COPY web/ web/

# Install python package
RUN pip install --no-cache-dir -e .

EXPOSE 8000

ENV ENVIRONMENT=production

CMD ["python", "-m", "ai_security_monitor", "server", "--host", "0.0.0.0"]
