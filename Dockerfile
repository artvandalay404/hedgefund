FROM python:3.12-slim

WORKDIR /app

# System deps for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
# Install only dependencies first (cached layer — reruns only when pyproject.toml changes)
RUN pip install --no-cache-dir \
    "alpaca-py>=0.33.0" "sqlalchemy>=2.0" "alembic>=1.13" \
    "pydantic-settings>=2.3" "structlog>=24.0" "resend>=2.0" \
    "apscheduler>=3.10,<4.0" "pandas>=2.1" "psycopg2-binary>=2.9" \
    "pytest>=8.0" "pytest-cov>=5.0"

# Copy source and install the package (non-editable)
COPY . .
RUN pip install --no-cache-dir .

# On Postgres: run migrations then start scheduler.
# On SQLite (local): scheduler auto-creates tables.
CMD ["sh", "-c", "alembic upgrade head && python -m hedgefund.scheduler"]
